"""`milyonus constitution ...` — IRADE Constitutional Policy Engine & Simulator (H4)."""

from __future__ import annotations

import json

import typer
from rich.console import Console
from rich.table import Table

from milyonus.brand import GLYPH, PALETTE
from milyonus.imece.constitution import builtin_constitutions, evaluate_text, simulate_constitutions

constitution_app = typer.Typer(
    help="Inspect, evaluate, and simulate IRADE Constitutional governance profiles (H4)."
)
console = Console()


@constitution_app.command("presets")
def constitution_presets() -> None:
    """List built-in Milyonus Constitutions and their SHA-256 hashes."""
    presets = builtin_constitutions()
    table = Table(title=f"{GLYPH} IRADE Constitutional Presets")
    table.add_column("Name", style=f"bold {PALETTE['cyan_400']}")
    table.add_column("Safety Floor")
    table.add_column("Articles")
    table.add_column("Hash", style="dim")
    table.add_column("Description")
    for c in presets.values():
        table.add_row(
            c.name,
            f"{c.veto_floors.get('safety', 0.5):.2f}",
            str(len(c.articles)),
            c.constitution_hash[:12],
            c.description,
        )
    console.print(table)


@constitution_app.command("evaluate")
def constitution_evaluate(
    text: str = typer.Argument(
        ..., help="Proposal or command text to check against Constitutional Articles"
    ),
    preset: str = typer.Option("fortress-security", "--preset", "-p"),
) -> None:
    """Check text against all Inviolable Articles of a Constitution."""
    presets = builtin_constitutions()
    const = presets.get(preset)
    if const is None:
        console.print(f"[{PALETTE['risk']}]unknown preset: {preset}[/]")
        raise typer.Exit(1)
    violations = evaluate_text(const, text)
    if not violations:
        console.print(f"[{PALETTE['ok']}]{GLYPH} Compliant with '{const.name}' (0 violations)[/]")
        return
    console.print(
        f"[{PALETTE['risk']}]{GLYPH} {len(violations)} violation(s) under '{const.name}':[/]"
    )
    for v in violations:
        console.print(f"  - [{v.severity}] {v.article_id} {v.title}: matched {v.matched_text!r}")
    raise typer.Exit(1)


@constitution_app.command("simulate")
def constitution_simulate(
    options_json: str = typer.Option(
        "",
        "--options-json",
        help="Optional JSON list of options; uses built-in security vs speed trade-off demo if omitted",
    ),
) -> None:
    """Simulate how every Constitution preset votes and vetoes side-by-side."""
    if options_json.strip():
        options = json.loads(options_json)
    else:
        options = [
            {
                "id": "opt_fast",
                "text": "Quick deploy using unverified cache shortcut",
                "scores": {
                    "correctness": 0.80,
                    "safety": 0.62,
                    "reversibility": 0.60,
                    "legal": 0.78,
                    "cost": 0.92,
                    "speed": 0.95,
                },
            },
            {
                "id": "opt_hardened",
                "text": "Sandboxed verified deployment with full rollback plan",
                "scores": {
                    "correctness": 0.91,
                    "safety": 0.94,
                    "reversibility": 0.90,
                    "legal": 0.92,
                    "cost": 0.58,
                    "speed": 0.55,
                },
            },
        ]
    sim = simulate_constitutions(options)
    table = Table(title=f"{GLYPH} Multi-Constitution Counterfactual Simulation")
    table.add_column("Constitution", style=f"bold {PALETTE['cyan_400']}")
    table.add_column("Winner")
    table.add_column("Tier")
    table.add_column("Vetoed")
    for v in sim["verdicts"]:
        table.add_row(
            v["constitution_name"],
            str(v["winner"] or "VETOED"),
            f"Kademe {v['tier']}",
            ", ".join(v["vetoed"].keys()) or "-",
        )
    console.print(table)
