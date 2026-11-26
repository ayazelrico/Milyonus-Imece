"""Signed Evidence Bundles — Verifiable `.milyonus-proof.json` Capsules (PLAN-MOONSHOT M2).

Produces self-contained, offline-verifiable cryptographic proof capsules binding:
  - deliverables / session transcripts / tool execution results (canonical SHA-256 leaves),
  - Kapı 1/2/3 gate reports and sandboxed execution evidence IDs,
  - the active memory audit ledger head & integrity flag,
  - a deterministic binary SHA-256 Merkle root over all claims,
  - an optional Ed25519 operator signature (`milyonus.security.operator`).

Any single-byte tamper in claims, deliverable content, ledger anchor, or signature
fails `verify_proof()` closed.
"""

from __future__ import annotations

import base64
import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from milyonus.memory.store import MemoryStore
from milyonus.security.operator import fingerprint as operator_fingerprint
from milyonus.security.operator import sign as operator_sign
from milyonus.security.operator import verify as operator_verify
from milyonus.security.redact import redact

SCHEMA_VERSION = "milyonus.proof.v1"


def _canonical_json(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def merkle_root(leaf_hashes: list[str]) -> str:
    """Compute a deterministic SHA-256 Merkle root over hex leaf hashes."""
    if not leaf_hashes:
        return _sha256_hex(b"milyonus:empty-merkle")
    level = sorted(leaf_hashes)
    while len(level) > 1:
        nxt: list[str] = []
        for i in range(0, len(level), 2):
            left = level[i]
            right = level[i + 1] if i + 1 < len(level) else left
            nxt.append(_sha256_hex((left + ":" + right).encode("ascii")))
        level = nxt
    return level[0]


@dataclass(slots=True)
class ProofClaim:
    kind: str
    label: str
    payload: dict[str, Any]
    sha256: str = ""

    def __post_init__(self) -> None:
        if not self.sha256:
            self.sha256 = _sha256_hex(
                _canonical_json({"kind": self.kind, "label": self.label, "payload": self.payload})
            )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ProofVerification:
    valid: bool
    checks_passed: int
    errors: list[str] = field(default_factory=list)
    signed: bool = False
    signature_valid: bool | None = None
    merkle_root: str = ""
    bundle_sha256: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _memory_anchor(memory_store: MemoryStore | None) -> dict[str, Any]:
    if memory_store is None:
        return {"ledger_head": None, "ledger_intact": None, "active_count": 0}
    return {
        "ledger_head": memory_store.ledger_head(),
        "ledger_intact": memory_store.verify_ledger(),
        "active_count": len(memory_store.active()),
    }


def _finalize_bundle(
    *,
    kind: str,
    subject_id: str,
    summary: dict[str, Any],
    claims: list[ProofClaim],
    memory_anchor: dict[str, Any],
    sign_key: Path | None = None,
    pubkey_path: Path | None = None,
) -> dict[str, Any]:
    root = merkle_root([c.sha256 for c in claims])
    envelope: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "kind": kind,
        "created_at": round(time.time(), 3),
        "subject_id": subject_id,
        "summary": summary,
        "memory_anchor": memory_anchor,
        "claims": [c.to_dict() for c in claims],
        "merkle_root": root,
    }
    bundle_hash = _sha256_hex(_canonical_json(envelope))
    envelope["bundle_sha256"] = bundle_hash

    if sign_key is not None:
        sig_bytes = operator_sign(sign_key, bundle_hash.encode("ascii"))
        envelope["signature"] = {
            "algorithm": "ed25519",
            "signature_b64": base64.b64encode(sig_bytes).decode("ascii"),
            "pubkey_fingerprint": operator_fingerprint(pubkey_path),
        }
    else:
        envelope["signature"] = None
    return envelope


def build_imece_proof(
    report: dict[str, Any],
    *,
    subject_id: str | None = None,
    memory_store: MemoryStore | None = None,
    sign_key: Path | None = None,
    pubkey_path: Path | None = None,
) -> dict[str, Any]:
    """Build a verifiable `.milyonus-proof.json` capsule from an İmece run report."""
    claims: list[ProofClaim] = []
    deliverable = str(report.get("deliverable") or "")
    if deliverable:
        claims.append(
            ProofClaim(
                kind="deliverable",
                label="final_deliverable",
                payload={
                    "chars": len(deliverable),
                    "content_sha256": _sha256_hex(deliverable.encode("utf-8")),
                    "preview": redact(deliverable)[:500],
                },
            )
        )
    if "frame" in report and report["frame"]:
        claims.append(
            ProofClaim(
                kind="gate1_frame", label="frozen_contract", payload={"frame": report["frame"]}
            )
        )
    if "approval" in report and report["approval"]:
        claims.append(
            ProofClaim(
                kind="gate3_approval",
                label="blind_approval",
                payload={"approval": report["approval"]},
            )
        )
    if "gate_reports" in report and report["gate_reports"]:
        claims.append(
            ProofClaim(
                kind="gate2_reality",
                label="independent_verification",
                payload={"gate_reports": report["gate_reports"]},
            )
        )
    if "metrics" in report and report["metrics"]:
        claims.append(
            ProofClaim(
                kind="telemetry", label="run_metrics", payload={"metrics": report["metrics"]}
            )
        )

    sid = subject_id or f"imece_{_sha256_hex(_canonical_json(report))[:12]}"
    summary = {
        "accepted": bool(report.get("accepted", False)),
        "rounds": int(report.get("rounds", 0)),
        "claim_count": len(claims),
    }
    return _finalize_bundle(
        kind="imece_run",
        subject_id=sid,
        summary=summary,
        claims=claims,
        memory_anchor=_memory_anchor(memory_store),
        sign_key=sign_key,
        pubkey_path=pubkey_path,
    )


def build_session_proof(
    session_id: str,
    messages: list[dict[str, Any]],
    *,
    tool_results: list[dict[str, Any]] | None = None,
    memory_store: MemoryStore | None = None,
    sign_key: Path | None = None,
    pubkey_path: Path | None = None,
) -> dict[str, Any]:
    """Build a redacted, verifiable `.milyonus-proof.json` capsule for a chat session."""
    claims: list[ProofClaim] = []
    for idx, msg in enumerate(messages):
        content = redact(str(msg.get("content") or ""))
        claims.append(
            ProofClaim(
                kind="message",
                label=f"{msg.get('role', 'unknown')}#{idx}",
                payload={
                    "id": str(msg.get("id", idx)),
                    "role": str(msg.get("role", "unknown")),
                    "content_sha256": _sha256_hex(content.encode("utf-8")),
                    "chars": len(content),
                    "created_at": msg.get("created_at"),
                },
            )
        )
    for tr in tool_results or []:
        clean_out = redact(str(tr.get("content") or ""))
        claims.append(
            ProofClaim(
                kind="tool_result",
                label=f"{tr.get('tool_name', 'tool')}:{tr.get('call_id', '')}",
                payload={
                    "turn_id": tr.get("turn_id"),
                    "call_id": tr.get("call_id"),
                    "tool_name": tr.get("tool_name"),
                    "ok": bool(tr.get("ok", False)),
                    "duration_ms": int(tr.get("duration_ms", 0)),
                    "output_sha256": _sha256_hex(clean_out.encode("utf-8")),
                },
            )
        )
    summary = {
        "session_id": session_id,
        "message_count": len(messages),
        "tool_result_count": len(tool_results or []),
        "claim_count": len(claims),
    }
    return _finalize_bundle(
        kind="web_session",
        subject_id=session_id,
        summary=summary,
        claims=claims,
        memory_anchor=_memory_anchor(memory_store),
        sign_key=sign_key,
        pubkey_path=pubkey_path,
    )


def verify_proof(
    bundle: dict[str, Any],
    *,
    pubkey_path: Path | None = None,
    require_signature: bool = False,
) -> ProofVerification:
    """Verify every leaf hash, Merkle root, bundle hash, and optional Ed25519 signature."""
    errors: list[str] = []
    passed = 0

    if not isinstance(bundle, dict) or bundle.get("schema_version") != SCHEMA_VERSION:
        return ProofVerification(
            valid=False,
            checks_passed=0,
            errors=[f"unsupported or missing schema_version (expected {SCHEMA_VERSION})"],
        )
    passed += 1

    raw_claims = bundle.get("claims")
    if not isinstance(raw_claims, list):
        return ProofVerification(
            valid=False, checks_passed=passed, errors=["claims must be a list"]
        )

    leaf_hashes: list[str] = []
    for i, claim in enumerate(raw_claims):
        if not isinstance(claim, dict):
            errors.append(f"claim[{i}] is not an object")
            continue
        expected_leaf = _sha256_hex(
            _canonical_json(
                {
                    "kind": claim.get("kind"),
                    "label": claim.get("label"),
                    "payload": claim.get("payload"),
                }
            )
        )
        if claim.get("sha256") != expected_leaf:
            errors.append(f"claim[{i}] ({claim.get('label')}) sha256 mismatch")
        else:
            passed += 1
        leaf_hashes.append(expected_leaf)

    computed_root = merkle_root(leaf_hashes)
    if bundle.get("merkle_root") != computed_root:
        errors.append("merkle_root mismatch (bundle tampered)")
    else:
        passed += 1

    unsigned_keys = (
        "schema_version",
        "kind",
        "created_at",
        "subject_id",
        "summary",
        "memory_anchor",
        "claims",
        "merkle_root",
    )
    unsigned = {k: bundle.get(k) for k in unsigned_keys}
    computed_bundle_hash = _sha256_hex(_canonical_json(unsigned))
    if bundle.get("bundle_sha256") != computed_bundle_hash:
        errors.append("bundle_sha256 mismatch (envelope tampered)")
    else:
        passed += 1

    sig_obj = bundle.get("signature")
    signed = isinstance(sig_obj, dict)
    sig_valid: bool | None = None
    if isinstance(sig_obj, dict):
        sig_b64 = sig_obj.get("signature_b64")
        if sig_obj.get("algorithm") != "ed25519" or not isinstance(sig_b64, str):
            errors.append("invalid signature block format")
            sig_valid = False
        else:
            try:
                sig_bytes = base64.b64decode(sig_b64, validate=True)
                ok = operator_verify(
                    computed_bundle_hash.encode("ascii"),
                    sig_bytes,
                    pubkey_path=pubkey_path,
                )
            except Exception:  # noqa: BLE001 - fail closed
                ok = False
            sig_valid = ok
            if ok:
                passed += 1
            else:
                errors.append("Ed25519 operator signature failed verification")
    elif require_signature:
        errors.append("operator signature required but bundle is unsigned")
        sig_valid = False

    return ProofVerification(
        valid=len(errors) == 0,
        checks_passed=passed,
        errors=errors,
        signed=signed,
        signature_valid=sig_valid,
        merkle_root=computed_root,
        bundle_sha256=computed_bundle_hash,
    )
