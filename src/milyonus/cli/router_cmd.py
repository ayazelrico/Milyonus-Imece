"""`milyonus router ...` — Multi-Model Cost-Latency-Trust Pareto Frontier Router CLI (H9)."""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from milyonus.brand import GLYPH, PALETTE
from milyonus.providers.pareto import ParetoRouter

router_app = typer.Typer(help="Compute 3D Pareto frontiers and route tasks across models (H9).")
console = Console()


@router_app.command("frontier")
def router_frontier(
    max_cost: float | None = typer.Option(None, "--max-cost"),
    max_latency: int | None = typer.Option(None, "--max-latency"),
    local_only: bool = typer.Option(False, "--local-only"),
) -> None:
    """Display the mathematically non-dominated Pareto frontier of models."""
    r = ParetoRouter()
    try:
        items = r.compute_pareto_frontier(
            max_cost_per_1m=max_cost, max_latency_ms=max_latency, require_local=local_only
        )
    finally:
        r.close()
    table = Table(title=f"{GLYPH} Cost-Latency-Trust Pareto Frontier")
    table.add_column("Model", style=f"bold {PALETTE['cyan_400']}")
    table.add_column("Quality")
    table.add_column("USD / 1M")
    table.add_column("Latency")
    table.add_column("Local")
    for m in items:
        table.add_row(
            m["model_id"],
            f"{m['effective_quality']:.3f}",
            f"${m['cost_per_1m_usd']:.2f}",
            f"{m['effective_latency_ms']}ms",
            "yes" if m["local_private"] else "no",
        )
    console.print(table)


@router_app.command("route")
def router_route(
    prompt: str = typer.Argument(..., help="Task prompt to classify and route"),
    budget_pressure: float = typer.Option(0.0, "--budget-pressure", min=0.0, max=1.0),
    local_only: bool = typer.Option(False, "--local-only"),
) -> None:
    """Classify task risk/complexity and choose the Pareto-optimal model."""
    r = ParetoRouter()
    try:
        res = r.route_task(prompt, budget_pressure=budget_pressure, require_local=local_only)
    finally:
        r.close()
    console.print(f"[{PALETTE['ok']}]{GLYPH} Selected:[/] [bold]{res['selected_model']}[/]")
    console.print(f"  {res['rationale']}")


@router_app.command("record")
def router_record(
    model_id: str = typer.Argument(...),
    success: bool = typer.Option(True, "--success/--fail"),
    latency_ms: int = typer.Option(500, "--latency-ms"),
    cost_usd: float = typer.Option(0.002, "--cost-usd"),
) -> None:
    """Record an empirical model outcome into the online Beta/UCB bandit store."""
    r = ParetoRouter()
    try:
        st = r.record_outcome(model_id, success=success, latency_ms=latency_ms, cost_usd=cost_usd)
    finally:
        r.close()
    console.print(
        f"[{PALETTE['ok']}]{GLYPH} Recorded[/] {st['model_id']} "
        f"(W={st['successes']} L={st['failures']} EMA={st['latency_ema_ms']}ms)"
    )
