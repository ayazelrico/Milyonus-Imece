"""Cryptographic Selective Disclosure Merkle Proofs (PLAN-HYPERNOVA H6).

Extends M2's `.milyonus-proof.json` Evidence Bundles into verifiable **Selective
Disclosure Proofs (`milyonus.disclosure.v1`)**:

  - Reveal ONLY chosen claims (e.g., `gate2_reality` + `gate3_approval`) to an
    external auditor while completely blinding sensitive claims (proprietary
    deliverable source code, user chat messages, tool payloads).
  - Generates genuine binary SHA-256 **Merkle Authentication Paths**
    (`[{sibling, side: "left" | "right"}, ...]`) matching `security.proof.merkle_root`.
  - `verify_disclosure_proof()` fails closed on any tampered claim, forged sibling
    hash, wrong root, duplicate proof leaf, or invalid Ed25519 operator signature —
    WITHOUT ever needing a single byte of the blinded claims.
"""

from __future__ import annotations

import base64
import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from milyonus.security.operator import verify as operator_verify
from milyonus.security.proof import SCHEMA_VERSION as PROOF_SCHEMA_VERSION
from milyonus.security.proof import _canonical_json, _sha256_hex, merkle_root

DISCLOSURE_SCHEMA_VERSION = "milyonus.disclosure.v1"


@dataclass(slots=True)
class MerkleStep:
    sibling: str
    side: str  # "left" | "right" — position of `sibling` relative to running hash

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(slots=True)
class DisclosureVerification:
    valid: bool
    checks_passed: int
    disclosed_count: int
    blinded_count: int
    merkle_root: str
    signed: bool = False
    signature_valid: bool | None = None
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_merkle_path(leaf_hashes: list[str], target_hash: str) -> list[MerkleStep]:
    """Compute the binary SHA-256 Merkle authentication path for `target_hash`.

    Uses the exact same sorted-leaf duplication algorithm as `security.proof.merkle_root`:
    at each level, pairs `(left, right)` hash as `SHA-256(f"{left}:{right}")`; odd nodes
    pair with themselves (`right = left`).
    """
    if not leaf_hashes:
        raise ValueError("cannot build Merkle path for empty leaf set")
    level = sorted(leaf_hashes)
    try:
        idx = level.index(target_hash)
    except ValueError as exc:
        raise ValueError(f"target leaf hash not found in leaf set: {target_hash}") from exc

    steps: list[MerkleStep] = []
    while len(level) > 1:
        if idx % 2 == 0:
            sibling = level[idx + 1] if idx + 1 < len(level) else level[idx]
            steps.append(MerkleStep(sibling=sibling, side="right"))
        else:
            sibling = level[idx - 1]
            steps.append(MerkleStep(sibling=sibling, side="left"))

        nxt: list[str] = []
        for i in range(0, len(level), 2):
            left = level[i]
            right = level[i + 1] if i + 1 < len(level) else left
            nxt.append(_sha256_hex((left + ":" + right).encode("ascii")))
        idx //= 2
        level = nxt
    return steps


def verify_merkle_path(leaf_hash: str, path: list[dict[str, Any]], expected_root: str) -> bool:
    """Recompute root from `leaf_hash` + authentication path and compare to `expected_root`."""
    cur = leaf_hash
    for step in path:
        if not isinstance(step, dict):
            return False
        sib = step.get("sibling")
        side = step.get("side")
        if not isinstance(sib, str) or side not in ("left", "right"):
            return False
        combined = f"{sib}:{cur}" if side == "left" else f"{cur}:{sib}"
        cur = _sha256_hex(combined.encode("ascii"))
    return cur == expected_root


def create_disclosure_proof(
    bundle: dict[str, Any],
    *,
    reveal_kinds: list[str] | None = None,
    reveal_indices: list[int] | None = None,
) -> dict[str, Any]:
    """Create a Selective Disclosure Proof revealing only chosen claims from a ProofBundle.

    Blinded claims are omitted completely — only their count and the shared Merkle root
    remain, along with inclusion proofs proving every disclosed claim belongs to the root.
    """
    if not isinstance(bundle, dict) or bundle.get("schema_version") != PROOF_SCHEMA_VERSION:
        raise ValueError(f"source bundle must have schema_version={PROOF_SCHEMA_VERSION}")
    raw_claims = bundle.get("claims")
    if not isinstance(raw_claims, list) or not raw_claims:
        raise ValueError("source bundle contains no claims to disclose")

    # Recompute canonical leaf hashes so we never trust precomputed claim hashes blindly.
    leaf_hashes: list[str] = []
    for c in raw_claims:
        lh = _sha256_hex(
            _canonical_json(
                {"kind": c.get("kind"), "label": c.get("label"), "payload": c.get("payload")}
            )
        )
        if c.get("sha256") != lh:
            raise ValueError(f"source bundle claim '{c.get('label')}' failed integrity check")
        leaf_hashes.append(lh)

    root = merkle_root(leaf_hashes)
    if bundle.get("merkle_root") != root:
        raise ValueError("source bundle merkle_root mismatch — refusing to derive disclosure proof")

    kind_set = {k.strip() for k in (reveal_kinds or []) if k.strip()}
    idx_set = set(reveal_indices or [])
    if not kind_set and not idx_set:
        # Default safe audit view: reveal gate & telemetry claims, blind deliverables & messages.
        kind_set = {"gate1_frame", "gate2_reality", "gate3_approval", "telemetry"}

    disclosed: list[dict[str, Any]] = []
    for i, claim in enumerate(raw_claims):
        if i in idx_set or str(claim.get("kind")) in kind_set:
            lh = leaf_hashes[i]
            steps = build_merkle_path(leaf_hashes, lh)
            disclosed.append(
                {
                    "index": i,
                    "claim": claim,
                    "leaf_sha256": lh,
                    "merkle_path": [s.to_dict() for s in steps],
                }
            )

    if not disclosed:
        raise ValueError(
            "disclosure filter matched 0 claims; specify reveal_kinds or reveal_indices"
        )

    envelope: dict[str, Any] = {
        "schema_version": DISCLOSURE_SCHEMA_VERSION,
        "created_at": round(time.time(), 3),
        "subject_id": bundle.get("subject_id"),
        "source_kind": bundle.get("kind"),
        "source_bundle_sha256": bundle.get("bundle_sha256"),
        "merkle_root": root,
        "memory_anchor": bundle.get("memory_anchor"),
        "total_claims": len(raw_claims),
        "disclosed_count": len(disclosed),
        "blinded_count": len(raw_claims) - len(disclosed),
        "disclosed": disclosed,
        "signature": bundle.get("signature"),
    }
    envelope["disclosure_sha256"] = hashlib.sha256(
        json.dumps(envelope, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
            "utf-8"
        )
    ).hexdigest()
    return envelope


def verify_disclosure_proof(
    disclosure: dict[str, Any],
    *,
    pubkey_path: Path | None = None,
    require_signature: bool = False,
) -> DisclosureVerification:
    """Verify a Selective Disclosure Proof offline — fail closed on any single-bit tamper."""
    errors: list[str] = []
    passed = 0

    if (
        not isinstance(disclosure, dict)
        or disclosure.get("schema_version") != DISCLOSURE_SCHEMA_VERSION
    ):
        return DisclosureVerification(
            valid=False,
            checks_passed=0,
            disclosed_count=0,
            blinded_count=0,
            merkle_root="",
            errors=[
                f"unsupported or missing schema_version (expected {DISCLOSURE_SCHEMA_VERSION})"
            ],
        )
    passed += 1

    root = str(disclosure.get("merkle_root") or "")
    disclosed = disclosure.get("disclosed")
    if not root or not isinstance(disclosed, list) or not disclosed:
        return DisclosureVerification(
            valid=False,
            checks_passed=passed,
            disclosed_count=0,
            blinded_count=int(disclosure.get("blinded_count") or 0),
            merkle_root=root,
            errors=["missing merkle_root or empty disclosed list"],
        )

    # Check outer disclosure digest integrity.
    unsigned_keys = (
        "schema_version",
        "created_at",
        "subject_id",
        "source_kind",
        "source_bundle_sha256",
        "merkle_root",
        "memory_anchor",
        "total_claims",
        "disclosed_count",
        "blinded_count",
        "disclosed",
        "signature",
    )
    recomputed_disc = _sha256_hex(_canonical_json({k: disclosure.get(k) for k in unsigned_keys}))
    if disclosure.get("disclosure_sha256") != recomputed_disc:
        errors.append("disclosure_sha256 mismatch (envelope tampered)")
    else:
        passed += 1

    seen_indices: set[int] = set()
    for pos, entry in enumerate(disclosed):
        if not isinstance(entry, dict) or not isinstance(entry.get("claim"), dict):
            errors.append(f"disclosed[{pos}] malformed")
            continue
        idx = entry.get("index")
        if isinstance(idx, int):
            if idx in seen_indices:
                errors.append(f"duplicate disclosed claim index {idx}")
                continue
            seen_indices.add(idx)

        claim = entry["claim"]
        expected_leaf = _sha256_hex(
            _canonical_json(
                {
                    "kind": claim.get("kind"),
                    "label": claim.get("label"),
                    "payload": claim.get("payload"),
                }
            )
        )
        if claim.get("sha256") != expected_leaf or entry.get("leaf_sha256") != expected_leaf:
            errors.append(f"disclosed[{pos}] leaf sha256 mismatch (claim tampered)")
            continue
        passed += 1

        path = entry.get("merkle_path")
        if not isinstance(path, list) or not verify_merkle_path(expected_leaf, path, root):
            errors.append(f"disclosed[{pos}] Merkle authentication path failed against root")
        else:
            passed += 1

    sig_obj = disclosure.get("signature")
    signed = isinstance(sig_obj, dict)
    sig_valid: bool | None = None
    if isinstance(sig_obj, dict):
        sig_b64 = sig_obj.get("signature_b64")
        src_hash = str(disclosure.get("source_bundle_sha256") or "")
        if sig_obj.get("algorithm") != "ed25519" or not isinstance(sig_b64, str) or not src_hash:
            errors.append("invalid Ed25519 signature block")
            sig_valid = False
        else:
            try:
                sig_bytes = base64.b64decode(sig_b64, validate=True)
                ok = operator_verify(src_hash.encode("ascii"), sig_bytes, pubkey_path=pubkey_path)
            except Exception:  # noqa: BLE001 - fail closed
                ok = False
            sig_valid = ok
            if ok:
                passed += 1
            else:
                errors.append("Ed25519 operator signature failed verification")
    elif require_signature:
        errors.append("operator signature required but disclosure proof is unsigned")
        sig_valid = False

    return DisclosureVerification(
        valid=len(errors) == 0,
        checks_passed=passed,
        disclosed_count=len(disclosed),
        blinded_count=int(disclosure.get("blinded_count") or 0),
        merkle_root=root,
        signed=signed,
        signature_valid=sig_valid,
        errors=errors,
    )
