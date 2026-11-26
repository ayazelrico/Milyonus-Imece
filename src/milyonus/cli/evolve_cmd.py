"""`milyonus evolve ...` — Swarm DNA & Evolutionary Strategy Genome CLI (H5)."""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from milyonus.brand import GLYPH, PALETTE
from milyonus.imece.evolution import EvolutionStore, evolve_swarm

evolve_app = typer.Typer(
    help="Evolve multi-agent Swarm DNA strategy genomes across generations (H5)."
)
console = Console()


@evolve_app.command("run")
def evolve_run(
    task: str = typer.Argument(..., help="Target task domain to optimize Swarm DNA for"),
    generations: int = typer.Option(6, "--generations", "-g", min=1, max=30),
    population: int = typer.Option(12, "--population", "-p", min=4, max=60),
    seed: int = typer.Option(42, "--seed"),
) -> None:
    """Run seeded genetic evolution over Swarm DNA genomes and persist phylogeny."""
    store = EvolutionStore()
    try:
        rep = evolve_swarm(
            task, generations=generations, population_size=population, seed=seed, store=store
        )
    finally:
        store.close()
    ch = rep.champion
    console.print(
        f"[bold {PALETTE['ok']}]{GLYPH} Evolution {rep.run_id} complete[/] "
        f"· champion={ch.genome_id} (fitness {ch.fitness:.4f}, style={ch.system_style}, "
        f"temp={ch.temperature}, verif={ch.verification_bias}, scale={ch.scale_agents})"
    )
    console.print(f"  traits: {', '.join(ch.traits)}")
    curve = " → ".join(f"G{c['generation']}:{c['best_fitness']:.3f}" for c in rep.generation_curve)
    console.print(f"  [dim]curve: {curve}[/]")


@evolve_app.command("history")
def evolve_history(limit: int = typer.Option(15, "--limit")) -> None:
    """Show recent Swarm DNA evolution runs."""
    store = EvolutionStore()
    try:
        runs = store.list_runs(limit=limit)
    finally:
        store.close()
    if not runs:
        console.print(f"[dim]{GLYPH} no evolution runs recorded yet.[/]")
        return
    table = Table(title=f"{GLYPH} Swarm DNA Evolution History")
    table.add_column("Run ID", style=f"bold {PALETTE['cyan_400']}")
    table.add_column("Gens")
    table.add_column("Best Fitness")
    table.add_column("Task")
    for r in runs:
        table.add_row(
            r["run_id"], str(r["generations"]), f"{r['best_fitness']:.4f}", r["task"][:55]
        )
    console.print(table)
