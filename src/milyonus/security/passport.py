"""Cryptographic Agent Passports & Verifiable Skill Credentials (PLAN-SINGULARITY S2).

Issues and offline-verifies tamper-evident digital passports (`milyonus.passport.v1`)
binding an autonomous agent's live security posture & identity:
  - `did:milyonus:<fingerprint>` decentralized subject identifier,
  - Live verified `chaos_immunity_score` & `chaos_grade`,
  - Active `constitution_name` & canonical `constitution_hash` (H4),
  - Memory ledger integrity flag & `ledger_head` (M1/Core),
  - Sealed Skill Immune manifest digests & health score (H7),
  - Cryptographic attestation via Ed25519 operator key OR per-vault HMAC-SHA256.

`verify_passport()` fails closed on tampered payloads, expired passports, invalid
signatures, or unmet policy gates (`min_chaos_score`, `required_constitution_hash`).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from milyonus.imece.constitution import builtin_constitutions
from milyonus.memory.store import MemoryStore
from milyonus.security.operator import fingerprint as operator_fingerprint
from milyonus.security.operator import sign as operator_sign
from milyonus.security.operator import verify as operator_verify
from milyonus.skills.immune import scan_skills_health

PASSPORT_SCHEMA_VERSION = "milyonus.passport.v1"


@dataclass(slots=True)
class PassportVerification:
    valid: bool
    trust_badge: str
    checks_passed: int
    errors: list[str] = field(default_factory=list)
    did: str = ""
    signature_algorithm: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _canonical(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _trust_badge(
    *,
    chaos_score: int,
    ledger_intact: bool,
    skill_health: int,
    signed: bool,
) -> str:
    if signed and chaos_score >= 98 and ledger_intact and skill_health >= 90:
        return "SOVEREIGN"
    if chaos_score >= 90 and ledger_intact and skill_health >= 75:
        return "VERIFIED"
    if chaos_score >= 70 and ledger_intact:
        return "PROVISIONAL"
    return "UNTRUSTED"


def issue_passport(
    *,
    agent_name: str,
    constitution_name: str = "fortress-security",
    chaos_score: int = 100,
    chaos_grade: str = "A+",
    memory_store: MemoryStore | None = None,
    skills_root: Path | None = None,
    ttl_seconds: float = 86_400.0,
    sign_key: Path | None = None,
    pubkey_path: Path | None = None,
    hmac_secret: bytes | None = None,
) -> dict[str, Any]:
    """Issue a cryptographically bound `milyonus.passport.v1` credential."""
    presets = builtin_constitutions()
    const = presets.get(constitution_name) or presets["balanced-default"]

    ledger_intact = memory_store.verify_ledger() if memory_store is not None else True
    ledger_head = memory_store.ledger_head() if memory_store is not None else "0" * 64
    active_mem = len(memory_store.active()) if memory_store is not None else 0

    if skills_root is not None and skills_root.is_dir():
        immune = scan_skills_health(skills_root)
        skill_health = immune.health_score
        skill_digests = {e.name: e.sha256 for e in immune.entries if e.status != "compromised"}
    else:
        skill_health = 100
        skill_digests = {}

    now = round(time.time(), 3)
    expires = round(now + max(60.0, min(float(ttl_seconds), 30 * 86_400.0)), 3)
    id_seed = f"{agent_name}:{const.constitution_hash}:{ledger_head}:{now}"
    did = "did:milyonus:" + _sha256_hex(id_seed.encode("utf-8"))[:24]

    signed_flag = sign_key is not None or hmac_secret is not None
    badge = _trust_badge(
        chaos_score=int(chaos_score),
        ledger_intact=ledger_intact,
        skill_health=skill_health,
        signed=signed_flag,
    )

    claims: dict[str, Any] = {
        "schema_version": PASSPORT_SCHEMA_VERSION,
        "did": did,
        "agent_name": agent_name.strip() or "milyonus-agent",
        "issued_at": now,
        "expires_at": expires,
        "trust_badge": badge,
        "security_posture": {
            "chaos_immunity_score": int(chaos_score),
            "chaos_grade": chaos_grade,
            "ledger_intact": ledger_intact,
            "ledger_head": ledger_head,
            "active_memory_count": active_mem,
            "skill_health_score": skill_health,
        },
        "constitution": {
            "name": const.name,
            "version": const.version,
            "constitution_hash": const.constitution_hash,
        },
        "verified_skills": skill_digests,
    }
    digest = _sha256_hex(_canonical(claims))
    passport: dict[str, Any] = {**claims, "passport_sha256": digest, "attestation": None}

    if sign_key is not None:
        sig_bytes = operator_sign(sign_key, digest.encode("ascii"))
        passport["attestation"] = {
            "algorithm": "ed25519",
            "signature_b64": base64.b64encode(sig_bytes).decode("ascii"),
            "pubkey_fingerprint": operator_fingerprint(pubkey_path),
        }
    elif hmac_secret is not None:
        mac = hmac.new(hmac_secret, digest.encode("ascii"), hashlib.sha256).hexdigest()
        passport["attestation"] = {
            "algorithm": "hmac-sha256",
            "signature_hex": mac,
        }
    return passport


def verify_passport(
    passport: dict[str, Any],
    *,
    pubkey_path: Path | None = None,
    hmac_secret: bytes | None = None,
    require_signature: bool = False,
    min_chaos_score: int = 0,
    required_constitution_hash: str | None = None,
    now: float | None = None,
) -> PassportVerification:
    """Offline fail-closed verification of a `milyonus.passport.v1` Agent Passport."""
    errors: list[str] = []
    passed = 0

    if not isinstance(passport, dict) or passport.get("schema_version") != PASSPORT_SCHEMA_VERSION:
        return PassportVerification(
            valid=False,
            trust_badge="UNTRUSTED",
            checks_passed=0,
            errors=[f"invalid or missing schema_version (expected {PASSPORT_SCHEMA_VERSION})"],
        )
    passed += 1

    did = str(passport.get("did") or "")
    badge = str(passport.get("trust_badge") or "UNTRUSTED")

    claim_keys = (
        "schema_version",
        "did",
        "agent_name",
        "issued_at",
        "expires_at",
        "trust_badge",
        "security_posture",
        "constitution",
        "verified_skills",
    )
    recomputed = _sha256_hex(_canonical({k: passport.get(k) for k in claim_keys}))
    if passport.get("passport_sha256") != recomputed:
        errors.append("passport_sha256 mismatch (passport tampered)")
    else:
        passed += 1

    ts = now if now is not None else time.time()
    exp = passport.get("expires_at")
    if not isinstance(exp, (int, float)) or ts > float(exp):
        errors.append("passport expired")
    else:
        passed += 1

    posture = passport.get("security_posture") or {}
    chaos_val = int(posture.get("chaos_immunity_score") or 0)
    if chaos_val < min_chaos_score:
        errors.append(f"chaos_immunity_score {chaos_val} < required {min_chaos_score}")
    else:
        passed += 1

    if not bool(posture.get("ledger_intact", False)):
        errors.append("memory ledger is not intact")
    else:
        passed += 1

    if required_constitution_hash is not None:
        chash = str((passport.get("constitution") or {}).get("constitution_hash") or "")
        if chash != required_constitution_hash:
            errors.append("constitution_hash does not match required policy")
        else:
            passed += 1

    att = passport.get("attestation")
    alg = ""
    if isinstance(att, dict):
        alg = str(att.get("algorithm") or "")
        if alg == "ed25519":
            sig_b64 = att.get("signature_b64")
            try:
                ok = isinstance(sig_b64, str) and operator_verify(
                    recomputed.encode("ascii"),
                    base64.b64decode(sig_b64, validate=True),
                    pubkey_path=pubkey_path,
                )
            except Exception:  # noqa: BLE001 - fail closed
                ok = False
            if ok:
                passed += 1
            else:
                errors.append("Ed25519 attestation failed verification")
        elif alg == "hmac-sha256":
            sig_hex = att.get("signature_hex")
            if hmac_secret is None or not isinstance(sig_hex, str):
                errors.append("HMAC secret missing for hmac-sha256 passport verification")
            else:
                expected_mac = hmac.new(
                    hmac_secret, recomputed.encode("ascii"), hashlib.sha256
                ).hexdigest()
                if hmac.compare_digest(sig_hex, expected_mac):
                    passed += 1
                else:
                    errors.append("HMAC-SHA256 attestation failed verification")
        else:
            errors.append(f"unsupported attestation algorithm: {alg}")
    elif require_signature:
        errors.append("attestation required but passport is unsigned")

    return PassportVerification(
        valid=len(errors) == 0,
        trust_badge=badge if len(errors) == 0 else "UNTRUSTED",
        checks_passed=passed,
        errors=errors,
        did=did,
        signature_algorithm=alg or "none",
    )
