"""`milyonus mesh ...` — Federated İmece Mesh Protocol CLI (H10)."""

from __future__ import annotations

import asyncio

import typer
from rich.console import Console
from rich.table import Table

from milyonus.brand import GLYPH, PALETTE
from milyonus.imece.mesh import MeshCoordinator, MeshStore

mesh_app = typer.Typer(
    help="Manage federated Milyonus peers and run Byzantine-resilient signed quorums (H10)."
)
console = Console()


@mesh_app.command("peers")
def mesh_peers() -> None:
    """List federated mesh peers, reputation scores, and quarantine state."""
    st = MeshStore()
    try:
        peers = st.list_peers()
    finally:
        st.close()
    if not peers:
        console.print(
            f"[dim]{GLYPH} no peers registered yet (dispatch will bootstrap a 3-node cluster).[/]"
        )
        return
    table = Table(title=f"{GLYPH} Federated İmece Mesh Peers")
    table.add_column("Node ID", style=f"bold {PALETTE['cyan_400']}")
    table.add_column("Label")
    table.add_column("Role")
    table.add_column("Reputation")
    table.add_column("Verified / Slashed")
    table.add_column("Status")
    for p in peers:
        status = (
            f"[{PALETTE['risk']}]QUARANTINED[/]" if p.quarantined else f"[{PALETTE['ok']}]active[/]"
        )
        table.add_row(
            p.node_id,
            p.label,
            p.role,
            f"{p.reputation:.2f}",
            f"{p.verified_tasks} / {p.slashed_count}",
            status,
        )
    console.print(table)


@mesh_app.command("register")
def mesh_register(
    label: str = typer.Argument(..., help="Human label for peer node"),
    node_id: str | None = typer.Option(None, "--id"),
    role: str = typer.Option("worker", "--role"),
    endpoint: str = typer.Option("local://in-process", "--endpoint"),
) -> None:
    """Register a new authenticated peer node in the mesh."""
    st = MeshStore()
    try:
        peer, _secret = st.register_peer(node_id=node_id, label=label, role=role, endpoint=endpoint)
    finally:
        st.close()
    console.print(
        f"[{PALETTE['ok']}]{GLYPH} Registered mesh peer[/] {peer.node_id} ({peer.label} · role={peer.role})"
    )


@mesh_app.command("dispatch")
def mesh_dispatch(
    task: str = typer.Argument(..., help="Task to broadcast across the signed federated mesh"),
    byzantine: str = typer.Option(
        "",
        "--simulate-byzantine",
        help="Optional comma-separated node IDs to simulate Byzantine tampering",
    ),
) -> None:
    """Broadcast a signed task across active mesh peers and synthesize weighted quorum consensus."""
    bad = {x.strip() for x in byzantine.split(",") if x.strip()}
    st = MeshStore()
    try:
        coord = MeshCoordinator(st)
        rep = asyncio.run(coord.dispatch(task, byzantine_nodes=bad))
    finally:
        st.close()
    color = PALETTE["ok"] if rep.quorum_reached else PALETTE["risk"]
    console.print(
        f"[bold {color}]{GLYPH} Mesh Dispatch {rep.dispatch_id}[/] · "
        f"quorum={'REACHED' if rep.quorum_reached else 'FAILED'} · "
        f"verified={rep.verified_peers} · rejected={rep.rejected_peers} · "
        f"weight={rep.consensus_weight:.2f}/{rep.total_weight:.2f}"
    )
    if rep.slashed_nodes:
        console.print(
            f"  [{PALETTE['risk']}]Slashed Byzantine peers:[/] {', '.join(rep.slashed_nodes)}"
        )
    for o in rep.peer_outcomes:
        oc = PALETTE["ok"] if o.accepted else PALETTE["risk"]
        console.print(
            f"  [{oc}]{'✓' if o.accepted else '✗'}[/] {o.node_id} (rep={o.reputation_after:.2f}) — {o.reason}"
        )
    if not rep.quorum_reached:
        raise typer.Exit(1)
