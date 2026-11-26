"""`milyonus proof ...` — create and verify offline `.milyonus-proof.json` capsules (M2)."""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console

from milyonus.brand import GLYPH, PALETTE
from milyonus.memory.store import MemoryStore
from milyonus.security.proof import build_imece_proof, verify_proof

proof_app = typer.Typer(help="Create and verify cryptographic `.milyonus-proof.json` capsules.")
console = Console()


@proof_app.command("create-from-imece")
def proof_create_from_imece(
    report_path: str = typer.Argument(..., help="Path to an İmece JSON run report"),
    out: str = typer.Option(
        "bundle.milyonus-proof.json", "--out", "-o", help="Output proof bundle path"
    ),
    sign_key: str | None = typer.Option(
        None, "--sign", help="Optional Ed25519 operator private key PEM to sign the capsule"
    ),
    pubkey: str | None = typer.Option(
        None, "--pubkey", help="Optional public key path for fingerprint metadata"
    ),
    no_memory_anchor: bool = typer.Option(
        False, "--no-memory-anchor", help="Omit local memory ledger anchor"
    ),
) -> None:
    """Wrap an İmece run report into a Merkle-verified (and optionally signed) proof capsule."""
    report_file = Path(report_path)
    out_file = Path(out)
    if not report_file.is_file():
        console.print(f"[{PALETTE['risk']}]report not found: {report_file}[/]")
        raise typer.Exit(code=1)
    report = json.loads(report_file.read_text(encoding="utf-8"))
    ms = None if no_memory_anchor else MemoryStore()
    try:
        bundle = build_imece_proof(
            report,
            memory_store=ms,
            sign_key=Path(sign_key) if sign_key is not None else None,
            pubkey_path=Path(pubkey) if pubkey is not None else None,
        )
    finally:
        if ms is not None:
            ms.close()
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(bundle, indent=2, ensure_ascii=False), encoding="utf-8")
    signed_tag = " · Ed25519 signed" if bundle.get("signature") else " · unsigned"
    console.print(
        f"[{PALETTE['ok']}]{GLYPH} proof capsule written[/] → {out_file} "
        f"[dim](merkle {bundle['merkle_root'][:12]}…{signed_tag})[/]"
    )


@proof_app.command("verify")
def proof_verify(
    bundle_path: str = typer.Argument(..., help="Path to `.milyonus-proof.json` capsule"),
    pubkey: str | None = typer.Option(
        None, "--pubkey", help="Explicit Ed25519 operator public key PEM"
    ),
    require_signature: bool = typer.Option(
        False, "--require-signature", help="Fail if the bundle is not Ed25519 signed"
    ),
) -> None:
    """Verify every leaf digest, Merkle root, bundle hash, and optional Ed25519 signature."""
    bundle_file = Path(bundle_path)
    if not bundle_file.is_file():
        console.print(f"[{PALETTE['risk']}]bundle not found: {bundle_file}[/]")
        raise typer.Exit(code=1)
    try:
        bundle = json.loads(bundle_file.read_text(encoding="utf-8"))
    except ValueError as exc:
        console.print(f"[{PALETTE['risk']}]invalid JSON: {exc}[/]")
        raise typer.Exit(code=1) from exc
    result = verify_proof(
        bundle,
        pubkey_path=Path(pubkey) if pubkey is not None else None,
        require_signature=require_signature,
    )
    if result.valid:
        sig_note = " · Ed25519 verified" if result.signature_valid else " · hash-verified"
        console.print(
            f"[{PALETTE['ok']}]{GLYPH} PROOF VALID[/] "
            f"({result.checks_passed} checks{sig_note} · merkle {result.merkle_root[:12]}…)"
        )
    else:
        console.print(f"[{PALETTE['risk']}]{GLYPH} PROOF INVALID[/]")
        for err in result.errors:
            console.print(f"  - {err}")
        raise typer.Exit(code=1)
