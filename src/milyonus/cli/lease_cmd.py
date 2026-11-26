"""`milyonus lease ...` — Zero-Trust Capability Leases & Canary Kill-Switch (H3)."""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from milyonus.brand import GLYPH, PALETTE
from milyonus.security.leases import LeaseVault

lease_app = typer.Typer(
    help="Mint, verify, and revoke signed Capability Leases & Canary traps (H3)."
)
console = Console()


@lease_app.command("mint")
def lease_mint(
    subject: str = typer.Option("agent", "--subject", "-s"),
    tools: str = typer.Option(
        "read_file,list_dir", "--tools", "-t", help="Comma-separated tool allowlist"
    ),
    paths: str = typer.Option("", "--paths", "-p", help="Comma-separated path globs"),
    domains: str = typer.Option("", "--domains", "-d", help="Comma-separated domain allowlist"),
    ttl: float = typer.Option(900.0, "--ttl", help="Lease TTL in seconds"),
    max_calls: int = typer.Option(25, "--max-calls"),
) -> None:
    """Mint a cryptographically signed, TTL-bounded Capability Lease."""
    vault = LeaseVault()
    try:
        lease = vault.mint(
            subject=subject,
            tools=[x.strip() for x in tools.split(",") if x.strip()],
            path_globs=[x.strip() for x in paths.split(",") if x.strip()],
            domains=[x.strip() for x in domains.split(",") if x.strip()],
            ttl_seconds=ttl,
            max_calls=max_calls,
        )
    finally:
        vault.close()
    console.print(
        f"[{PALETTE['ok']}]{GLYPH} Minted lease[/] {lease.lease_id} "
        f"[dim](subject={lease.subject} · tools={','.join(lease.tools)} · "
        f"max_calls={lease.max_calls} · sig={lease.signature_hex[:12]}…)[/]"
    )


@lease_app.command("list")
def lease_list(active_only: bool = typer.Option(False, "--active")) -> None:
    """List capability leases in the vault."""
    vault = LeaseVault()
    try:
        rows = vault.list_leases(active_only=active_only)
    finally:
        vault.close()
    if not rows:
        console.print(f"[dim]{GLYPH} no capability leases found.[/]")
        return
    table = Table(title=f"{GLYPH} Capability Leases")
    table.add_column("Lease ID", style=f"bold {PALETTE['cyan_400']}")
    table.add_column("Subject")
    table.add_column("Tools")
    table.add_column("Calls")
    table.add_column("Status")
    for lr in rows:
        st = f"[{PALETTE['risk']}]revoked[/]" if lr.revoked_at else f"[{PALETTE['ok']}]active[/]"
        table.add_row(
            lr.lease_id,
            lr.subject,
            ",".join(lr.tools),
            f"{lr.calls_used}/{lr.max_calls}",
            st,
        )
    console.print(table)


@lease_app.command("verify")
def lease_verify(
    lease_id: str = typer.Argument(...),
    tool: str = typer.Option("read_file", "--tool"),
    path: str | None = typer.Option(None, "--path"),
    domain: str | None = typer.Option(None, "--domain"),
    consume: bool = typer.Option(False, "--consume"),
) -> None:
    """Verify a Capability Lease against a tool/path/domain request."""
    vault = LeaseVault()
    try:
        dec = vault.verify_and_consume(
            lease_id, tool_name=tool, path=path, domain=domain, consume=consume
        )
    finally:
        vault.close()
    color = PALETTE["ok"] if dec.allowed else PALETTE["risk"]
    console.print(
        f"[{color}]{GLYPH} {'ALLOWED' if dec.allowed else 'DENIED'}[/] — {dec.reason} "
        f"(remaining={dec.remaining_calls})"
    )
    if not dec.allowed:
        raise typer.Exit(1)


@lease_app.command("revoke")
def lease_revoke(lease_id: str = typer.Argument(...)) -> None:
    """Immediately revoke a Capability Lease."""
    vault = LeaseVault()
    try:
        ok = vault.revoke(lease_id)
    finally:
        vault.close()
    if not ok:
        console.print(f"[{PALETTE['risk']}]lease not found or already revoked: {lease_id}[/]")
        raise typer.Exit(1)
    console.print(f"[{PALETTE['ok']}]{GLYPH} Revoked lease {lease_id}[/]")


@lease_app.command("canary-mint")
def lease_canary_mint(label: str = typer.Option("prompt-trap", "--label")) -> None:
    """Mint a Honeytoken Canary that trips an instant global lease kill-switch if leaked."""
    vault = LeaseVault()
    try:
        c = vault.mint_canary(label=label)
    finally:
        vault.close()
    console.print(
        f"[{PALETTE['ok']}]{GLYPH} Canary minted[/] ({c['canary_id']}) token={c['token']}"
    )


@lease_app.command("canary-scan")
def lease_canary_scan(
    text: str = typer.Argument(..., help="Text to inspect for canary leakage"),
) -> None:
    """Inspect text for canary leakage; revokes ALL active leases if tripped."""
    vault = LeaseVault()
    try:
        rep = vault.scan_for_canary_leak(text, context="cli-scan")
    finally:
        vault.close()
    if rep.tripped:
        console.print(f"[{PALETTE['risk']}]{GLYPH} {rep.detail}[/]")
        raise typer.Exit(1)
    console.print(f"[{PALETTE['ok']}]{GLYPH} {rep.detail}[/]")
