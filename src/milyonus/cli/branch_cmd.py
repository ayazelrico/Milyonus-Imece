"""`milyonus branch ...` — Git-style cognitive branching over verified memory (H2)."""

from __future__ import annotations

import asyncio

import typer
from rich.console import Console
from rich.table import Table

from milyonus.brand import GLYPH, PALETTE
from milyonus.memory.branch import BranchError, MemoryBranchManager
from milyonus.memory.store import MemoryStore

branch_app = typer.Typer(help="Fork, diff, and verified-merge cognitive memory branches (H2).")
console = Console()


@branch_app.command("list")
def branch_list() -> None:
    """List all cognitive memory branches."""
    mgr = MemoryBranchManager()
    try:
        branches = mgr.list_branches()
    finally:
        mgr.close()
    if not branches:
        console.print(
            f"[dim]{GLYPH} no memory branches yet. Create one with `milyonus branch create <name>`.[/]"
        )
        return
    table = Table(title=f"{GLYPH} Cognitive Memory Branches")
    table.add_column("Name", style=f"bold {PALETTE['cyan_400']}")
    table.add_column("Snapshot")
    table.add_column("+Adds / -Revokes")
    table.add_column("Hash", style="dim")
    table.add_column("Status")
    for b in branches:
        st = f"[{PALETTE['ok']}]merged[/]" if b.merged_at else "open"
        table.add_row(
            b.name,
            str(b.snapshot_count),
            f"+{b.staged_adds} / -{b.staged_revokes}",
            b.branch_hash[:12],
            st,
        )
    console.print(table)


@branch_app.command("create")
def branch_create(
    name: str = typer.Argument(..., help="Branch name (e.g. exp/new-db)"),
    description: str = typer.Option("", "--desc", "-d"),
) -> None:
    """Fork live verified memory into a hash-anchored cognitive branch."""
    ms = MemoryStore()
    mgr = MemoryBranchManager()
    try:
        b = mgr.create_branch(name, ms, description=description)
    except BranchError as exc:
        console.print(f"[{PALETTE['risk']}]{exc}[/]")
        raise typer.Exit(1) from exc
    finally:
        ms.close()
        mgr.close()
    console.print(
        f"[{PALETTE['ok']}]{GLYPH} Created branch '{b.name}'[/] "
        f"[dim](snapshot={b.snapshot_count} · hash={b.branch_hash[:12]}…)[/]"
    )


@branch_app.command("add")
def branch_add(
    name: str = typer.Argument(..., help="Target branch name"),
    content: str = typer.Argument(..., help="Hypothetical memory claim to stage"),
) -> None:
    """Stage a hypothetical memory addition on a branch (zero live mutation)."""
    mgr = MemoryBranchManager()
    try:
        res = mgr.stage_add(name, content)
    except BranchError as exc:
        console.print(f"[{PALETTE['risk']}]{exc}[/]")
        raise typer.Exit(1) from exc
    finally:
        mgr.close()
    console.print(
        f"[{PALETTE['ok']}]{GLYPH} Staged on '{name}'[/] ({res['id']} · hash {res['branch_hash'][:12]}…)"
    )


@branch_app.command("diff")
def branch_diff(name: str = typer.Argument(..., help="Branch name to diff against main")) -> None:
    """Show 3-way cognitive diff and epistemic conflict check against live memory."""
    ms = MemoryStore()
    mgr = MemoryBranchManager()
    try:
        d = mgr.diff_branch(name, ms)
    except BranchError as exc:
        console.print(f"[{PALETTE['risk']}]{exc}[/]")
        raise typer.Exit(1) from exc
    finally:
        ms.close()
        mgr.close()
    console.print(
        f"[bold {PALETTE['cyan_400']}]{GLYPH} Branch diff '{d.branch_name}' vs main[/]\n"
        f"  staged adds   : {len(d.staged_adds)}\n"
        f"  staged revokes: {len(d.staged_revokes)}\n"
        f"  main diverged : {d.main_diverged}\n"
        f"  conflicts     : {len(d.conflicts)}"
    )
    for c in d.conflicts:
        console.print(f"  [{PALETTE['risk']}]CONFLICT[/] {c['explanation']}")


@branch_app.command("merge")
def branch_merge(
    name: str = typer.Argument(..., help="Branch name to merge into live verified memory"),
    force: bool = typer.Option(
        False, "--force", help="Merge even if epistemic contradictions exist"
    ),
) -> None:
    """Merge staged branch mutations into live memory strictly through MemoryPipeline."""
    ms = MemoryStore()
    mgr = MemoryBranchManager()
    try:
        res = asyncio.run(mgr.merge_branch(name, ms, force=force))
    except BranchError as exc:
        console.print(f"[{PALETTE['risk']}]{exc}[/]")
        raise typer.Exit(1) from exc
    finally:
        ms.close()
        mgr.close()
    color = PALETTE["ok"] if res.merged else PALETTE["risk"]
    console.print(f"[{color}]{GLYPH} {res.message}[/]")
    if not res.merged:
        raise typer.Exit(1)


@branch_app.command("delete")
def branch_delete(name: str = typer.Argument(..., help="Branch name to delete")) -> None:
    """Delete a cognitive memory branch."""
    mgr = MemoryBranchManager()
    try:
        ok = mgr.delete_branch(name)
    finally:
        mgr.close()
    if not ok:
        console.print(f"[{PALETTE['risk']}]branch not found: {name}[/]")
        raise typer.Exit(1)
    console.print(f"[{PALETTE['ok']}]{GLYPH} Deleted branch '{name}'[/]")
