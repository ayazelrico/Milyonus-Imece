"""Zero-Trust Capability Leases & Prompt-Injection Canary Kill-Switch (PLAN-HYPERNOVA H3).

Replaces coarse, sticky "allow session" flags with cryptographically signed,
TTL-bounded, scope-locked capability tokens (`milyonus.lease.v1`):
  - Tool allowlist (exact names or `*` wildcard — never bypassing irreversible lock),
  - Path glob jail (`fnmatch` scoped relative paths; `..` traversal fails closed),
  - Outbound domain allowlist,
  - Max call count & token ceiling,
  - Instant O(1) revocation + HMAC-SHA256 constant-time signature check.

Also provides a **Honeytoken Canary Kill-Switch**: mints decoy canary secrets placed in
untrusted/system boundaries; if a prompt injection ever causes an agent to echo or leak
an active canary into any inspected output/tool call, EVERY active lease in the vault is
immediately revoked in one atomic sweep.
"""

from __future__ import annotations

import fnmatch
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from milyonus.config.paths import state_db

LEASE_SCHEMA_VERSION = "milyonus.lease.v1"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS capability_leases (
    lease_id           TEXT PRIMARY KEY,
    subject            TEXT NOT NULL,
    tools_json         TEXT NOT NULL,
    path_globs_json    TEXT NOT NULL,
    domains_json       TEXT NOT NULL,
    max_calls          INTEGER NOT NULL,
    calls_used         INTEGER NOT NULL DEFAULT 0,
    max_tokens         INTEGER NOT NULL,
    allow_irreversible INTEGER NOT NULL DEFAULT 0,
    issued_at          REAL NOT NULL,
    expires_at         REAL NOT NULL,
    revoked_at         REAL,
    revoke_reason      TEXT,
    signature_hex      TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS lease_canaries (
    canary_id   TEXT PRIMARY KEY,
    label       TEXT NOT NULL,
    token_hash  TEXT NOT NULL UNIQUE,
    token_hint  TEXT NOT NULL,
    created_at  REAL NOT NULL,
    tripped_at  REAL,
    trip_context TEXT
);
"""


@dataclass(slots=True)
class CapabilityLease:
    lease_id: str
    subject: str
    tools: list[str]
    path_globs: list[str]
    domains: list[str]
    max_calls: int
    calls_used: int
    max_tokens: int
    allow_irreversible: bool
    issued_at: float
    expires_at: float
    revoked_at: float | None = None
    revoke_reason: str | None = None
    signature_hex: str = ""
    schema_version: str = LEASE_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class LeaseDecision:
    allowed: bool
    reason: str
    lease_id: str
    remaining_calls: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class CanaryTripReport:
    tripped: bool
    matched_canary_ids: list[str] = field(default_factory=list)
    revoked_lease_ids: list[str] = field(default_factory=list)
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _canonical_lease_body(lease: dict[str, Any]) -> bytes:
    payload = {
        "schema_version": LEASE_SCHEMA_VERSION,
        "lease_id": lease["lease_id"],
        "subject": lease["subject"],
        "tools": sorted(str(t) for t in lease["tools"]),
        "path_globs": sorted(str(p) for p in lease["path_globs"]),
        "domains": sorted(str(d).lower() for d in lease["domains"]),
        "max_calls": int(lease["max_calls"]),
        "max_tokens": int(lease["max_tokens"]),
        "allow_irreversible": bool(lease["allow_irreversible"]),
        "issued_at": round(float(lease["issued_at"]), 3),
        "expires_at": round(float(lease["expires_at"]), 3),
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def _load_or_create_secret(db_path: Path) -> bytes:
    secret_path = db_path.parent / ".lease_hmac.key"
    secret_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if secret_path.is_file() and not secret_path.is_symlink():
        raw = secret_path.read_bytes()
        if len(raw) >= 32:
            return raw[:32]
    key = secrets.token_bytes(32)
    fd = os.open(str(secret_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, key)
    finally:
        os.close(fd)
    return key


def _sign_body(secret: bytes, body: bytes) -> str:
    return hmac.new(secret, body, hashlib.sha256).hexdigest()


def _extract_host(url_or_domain: str) -> str:
    if "://" in url_or_domain:
        return (urlsplit(url_or_domain).hostname or "").lower().rstrip(".")
    return url_or_domain.strip().lower().rstrip(".")


class LeaseVault:
    """Persistent, cryptographically signed Capability Lease & Canary Vault."""

    def __init__(self, path: Path | None = None, *, secret: bytes | None = None) -> None:
        self.path = path or state_db()
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._secret = secret if secret is not None else _load_or_create_secret(self.path)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def _row_to_lease(self, r: sqlite3.Row) -> CapabilityLease:
        return CapabilityLease(
            lease_id=str(r["lease_id"]),
            subject=str(r["subject"]),
            tools=list(json.loads(r["tools_json"])),
            path_globs=list(json.loads(r["path_globs_json"])),
            domains=list(json.loads(r["domains_json"])),
            max_calls=int(r["max_calls"]),
            calls_used=int(r["calls_used"]),
            max_tokens=int(r["max_tokens"]),
            allow_irreversible=bool(r["allow_irreversible"]),
            issued_at=float(r["issued_at"]),
            expires_at=float(r["expires_at"]),
            revoked_at=float(r["revoked_at"]) if r["revoked_at"] is not None else None,
            revoke_reason=str(r["revoke_reason"]) if r["revoke_reason"] is not None else None,
            signature_hex=str(r["signature_hex"]),
        )

    def mint(
        self,
        *,
        subject: str,
        tools: list[str],
        path_globs: list[str] | None = None,
        domains: list[str] | None = None,
        ttl_seconds: float = 900.0,
        max_calls: int = 25,
        max_tokens: int = 32_000,
        allow_irreversible: bool = False,
    ) -> CapabilityLease:
        """Mint and sign a new TTL-bounded Capability Lease."""
        now = round(time.time(), 3)
        clamped_ttl = max(1.0, min(float(ttl_seconds), 86_400.0))
        if allow_irreversible:
            # Irreversible leases are strictly short-lived (<= 120s) and capped (<= 3 calls).
            clamped_ttl = min(clamped_ttl, 120.0)
            max_calls = min(max_calls, 3)
        expires = round(now + clamped_ttl, 3)
        lid = f"lease_{uuid.uuid4().hex[:14]}"
        norm_tools = sorted({t.strip() for t in tools if t.strip()})
        norm_paths = sorted({p.strip() for p in (path_globs or []) if p.strip()})
        norm_domains = sorted({_extract_host(d) for d in (domains or []) if d.strip()})
        clamped_calls = max(1, int(max_calls))
        clamped_tokens = max(100, int(max_tokens))
        clean_subject = subject.strip() or "agent"
        lease_dict: dict[str, Any] = {
            "lease_id": lid,
            "subject": clean_subject,
            "tools": norm_tools,
            "path_globs": norm_paths,
            "domains": norm_domains,
            "max_calls": clamped_calls,
            "max_tokens": clamped_tokens,
            "allow_irreversible": bool(allow_irreversible),
            "issued_at": now,
            "expires_at": expires,
        }
        sig = _sign_body(self._secret, _canonical_lease_body(lease_dict))
        with self._lock:
            self._conn.execute(
                "INSERT INTO capability_leases(lease_id, subject, tools_json, path_globs_json, "
                "domains_json, max_calls, calls_used, max_tokens, allow_irreversible, "
                "issued_at, expires_at, signature_hex) VALUES (?,?,?,?,?,?,0,?,?,?,?,?)",
                (
                    lid,
                    clean_subject,
                    json.dumps(norm_tools),
                    json.dumps(norm_paths),
                    json.dumps(norm_domains),
                    clamped_calls,
                    clamped_tokens,
                    1 if allow_irreversible else 0,
                    now,
                    expires,
                    sig,
                ),
            )
            self._conn.commit()
        return CapabilityLease(
            lease_id=lid,
            subject=clean_subject,
            tools=norm_tools,
            path_globs=norm_paths,
            domains=norm_domains,
            max_calls=clamped_calls,
            calls_used=0,
            max_tokens=clamped_tokens,
            allow_irreversible=bool(allow_irreversible),
            issued_at=now,
            expires_at=expires,
            signature_hex=sig,
        )

    def get(self, lease_id: str) -> CapabilityLease | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM capability_leases WHERE lease_id=?", (lease_id,)
            ).fetchone()
            return self._row_to_lease(row) if row is not None else None

    def list_leases(self, *, active_only: bool = False) -> list[CapabilityLease]:
        now = time.time()
        with self._lock:
            if active_only:
                rows = self._conn.execute(
                    "SELECT * FROM capability_leases WHERE revoked_at IS NULL AND expires_at > ? "
                    "ORDER BY issued_at DESC",
                    (now,),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM capability_leases ORDER BY issued_at DESC LIMIT 100"
                ).fetchall()
            return [self._row_to_lease(r) for r in rows]

    def revoke(self, lease_id: str, *, reason: str = "manual_revoke") -> bool:
        with self._lock:
            cur = self._conn.execute(
                "UPDATE capability_leases SET revoked_at=?, revoke_reason=? "
                "WHERE lease_id=? AND revoked_at IS NULL",
                (time.time(), reason, lease_id),
            )
            self._conn.commit()
            return (cur.rowcount or 0) > 0

    def revoke_all(self, *, reason: str = "emergency_kill_switch") -> list[str]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT lease_id FROM capability_leases WHERE revoked_at IS NULL"
            ).fetchall()
            ids = [str(r["lease_id"]) for r in rows]
            if ids:
                self._conn.execute(
                    "UPDATE capability_leases SET revoked_at=?, revoke_reason=? "
                    "WHERE revoked_at IS NULL",
                    (time.time(), reason),
                )
                self._conn.commit()
            return ids

    def verify_signature(self, lease: CapabilityLease | dict[str, Any]) -> bool:
        """Fail-closed constant-time HMAC-SHA256 verification of a lease envelope."""
        d = lease.to_dict() if isinstance(lease, CapabilityLease) else lease
        provided = str(d.get("signature_hex") or "")
        if not provided:
            return False
        try:
            expected = _sign_body(self._secret, _canonical_lease_body(d))
        except (KeyError, TypeError, ValueError):
            return False
        return hmac.compare_digest(provided, expected)

    def verify_and_consume(
        self,
        lease_id: str,
        *,
        tool_name: str,
        path: str | None = None,
        domain: str | None = None,
        irreversible: bool = False,
        consume: bool = True,
        signature_override: str | None = None,
        now: float | None = None,
    ) -> LeaseDecision:
        """Enforce zero-trust lease policy and atomically consume 1 call if allowed."""
        ts = now if now is not None else time.time()
        with self._lock:
            lease = self.get(lease_id)
            if lease is None:
                return LeaseDecision(False, "lease not found (fail-closed)", lease_id)
            check_dict = lease.to_dict()
            if signature_override is not None:
                check_dict["signature_hex"] = signature_override
            if not self.verify_signature(check_dict):
                return LeaseDecision(False, "cryptographic lease signature invalid", lease_id)
            if lease.revoked_at is not None:
                return LeaseDecision(
                    False, f"lease revoked ({lease.revoke_reason or 'revoked'})", lease_id
                )
            if ts > lease.expires_at:
                return LeaseDecision(False, "lease expired", lease_id)
            if lease.calls_used >= lease.max_calls:
                return LeaseDecision(False, "lease call budget exhausted", lease_id)
            if irreversible and not lease.allow_irreversible:
                return LeaseDecision(
                    False, "irreversible action denied by capability lease", lease_id
                )
            if "*" not in lease.tools and tool_name not in lease.tools:
                return LeaseDecision(False, f"tool '{tool_name}' outside lease allowlist", lease_id)
            if path is not None:
                norm_p = path.replace("\\", "/").lstrip("/")
                if ".." in Path(norm_p).parts or Path(path).is_absolute():
                    return LeaseDecision(False, "path traversal / absolute path denied", lease_id)
                if lease.path_globs and not any(
                    fnmatch.fnmatch(norm_p, g) for g in lease.path_globs
                ):
                    return LeaseDecision(
                        False, f"path '{norm_p}' outside lease path_globs", lease_id
                    )
            if domain is not None and lease.domains:
                host = _extract_host(domain)
                if not any(host == d or host.endswith("." + d) for d in lease.domains):
                    return LeaseDecision(
                        False, f"domain '{host}' outside lease domain allowlist", lease_id
                    )

            remaining = lease.max_calls - lease.calls_used
            if consume:
                self._conn.execute(
                    "UPDATE capability_leases SET calls_used=calls_used+1 WHERE lease_id=?",
                    (lease_id,),
                )
                self._conn.commit()
                remaining -= 1
            return LeaseDecision(True, "lease authorized", lease_id, remaining_calls=remaining)

    # --- Honeytoken Canary Kill-Switch ----------------------------------

    def mint_canary(self, label: str = "system-boundary") -> dict[str, Any]:
        """Mint a decoy honeytoken canary that auto-revokes all leases if leaked."""
        cid = f"can_{uuid.uuid4().hex[:10]}"
        token = f"mil_canary_{secrets.token_hex(12)}"
        thash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        hint = token[:15] + "…" + token[-4:]
        now = time.time()
        with self._lock:
            self._conn.execute(
                "INSERT INTO lease_canaries(canary_id, label, token_hash, token_hint, created_at) "
                "VALUES (?,?,?,?,?)",
                (cid, label.strip()[:80], thash, hint, now),
            )
            self._conn.commit()
        return {"canary_id": cid, "label": label, "token": token, "hint": hint, "created_at": now}

    def list_canaries(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT canary_id, label, token_hint, created_at, tripped_at, trip_context "
                "FROM lease_canaries ORDER BY created_at DESC LIMIT 50"
            ).fetchall()
            return [dict(r) for r in rows]

    def scan_for_canary_leak(self, text: str, *, context: str = "outbound") -> CanaryTripReport:
        """Inspect text for any active canary token; trip kill-switch if leaked."""
        import re

        candidates = re.findall(r"mil_canary_[0-9a-f]{24}", text)
        if not candidates:
            return CanaryTripReport(tripped=False, detail="clean — no canary tokens detected")
        matched: list[str] = []
        now = time.time()
        with self._lock:
            for cand in set(candidates):
                thash = hashlib.sha256(cand.encode("utf-8")).hexdigest()
                row = self._conn.execute(
                    "SELECT canary_id FROM lease_canaries WHERE token_hash=?", (thash,)
                ).fetchone()
                if row is not None:
                    cid = str(row["canary_id"])
                    matched.append(cid)
                    self._conn.execute(
                        "UPDATE lease_canaries SET tripped_at=?, trip_context=? WHERE canary_id=?",
                        (now, context[:160], cid),
                    )
            if not matched:
                return CanaryTripReport(tripped=False, detail="unregistered canary-like string")
            revoked = self.revoke_all(reason=f"canary_tripped:{','.join(matched)}")
            self._conn.commit()
        return CanaryTripReport(
            tripped=True,
            matched_canary_ids=matched,
            revoked_lease_ids=revoked,
            detail=(
                f"KILL-SWITCH TRIPPED: {len(matched)} canary leaked in '{context}'; "
                f"revoked {len(revoked)} active lease(s)"
            ),
        )
