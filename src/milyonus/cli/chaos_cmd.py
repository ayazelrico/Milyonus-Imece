"""`milyonus chaos ...` — Adversarial Chaos & Red-Team Autopilot CLI (M4)."""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from milyonus.brand import GLYPH, PALETTE
from milyonus.security.chaos import run_chaos_sync

chaos_app = typer.Typer(help="Run isolated adversarial chaos probes across all defense layers.")
console = Console()


@chaos_app.command("run")
def chaos_run(
    min_score: int = typer.Option(
        100, "--min-score", help="Fail with exit code 1 if Immunity Score is below this threshold"
    ),
    no_web: bool = typer.Option(False, "--no-web", help="Skip FastAPI web tenant isolation probe"),
    json_out: str | None = typer.Option(
        None, "--json-out", help="Write full Immunity Scorecard JSON to this file"
    ),
) -> None:
    """Attack Milyonus across 6 vectors in isolated sandboxes and print the Immunity Scorecard."""
    report = run_chaos_sync(include_web=not no_web)
    table = Table(
        title=f"{GLYPH} Adversarial Chaos Scorecard — {report.immunity_score}/100 ({report.grade})"
    )
    table.add_column("Vector", style=f"bold {PALETTE['cyan_400']}")
    table.add_column("Probe")
    table.add_column("Attack")
    table.add_column("Status")
    table.add_column("Detail", style="dim")
    for p in report.probes:
        status = (
            f"[{PALETTE['ok']}]BLOCKED ✓[/]" if p.blocked else f"[{PALETTE['risk']}]BREACHED ✗[/]"
        )
        table.add_row(p.vector, p.id, p.attack, status, p.detail)
    console.print(table)
    color = PALETTE["ok"] if report.immunity_score >= min_score else PALETTE["risk"]
    console.print(
        f"[{color}]{GLYPH} Immunity Score: {report.immunity_score}/100 ({report.grade})[/] "
        f"· {report.passed}/{report.total} blocked · {report.duration_ms}ms"
    )
    if json_out is not None:
        out_path = Path(json_out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
        console.print(f"[dim]scorecard → {out_path}[/]")
    if report.immunity_score < min_score:
        raise typer.Exit(code=1)
