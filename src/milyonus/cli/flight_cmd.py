"""`milyonus flight ...` — Black-Box Session DVR & Anomaly Detector CLI (H8)."""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console

from milyonus.brand import GLYPH, PALETTE
from milyonus.core.flight_recorder import detect_anomalies, diff_flights, verify_flight

flight_app = typer.Typer(
    help="Inspect, verify, analyze, and diff `.milyonus-flight.json` DVR files (H8)."
)
console = Console()


@flight_app.command("inspect")
def flight_inspect(
    flight_path: str = typer.Argument(..., help="Path to `.milyonus-flight.json`"),
) -> None:
    """Verify hash chain and inspect frames & anomalies of a Flight Recording."""
    p = Path(flight_path)
    if not p.is_file():
        console.print(f"[{PALETTE['risk']}]flight file not found: {p}[/]")
        raise typer.Exit(1)
    rec = json.loads(p.read_text(encoding="utf-8"))
    intact, errs = verify_flight(rec)
    anomalies = detect_anomalies(rec)
    status = f"[{PALETTE['ok']}]CHAIN INTACT[/]" if intact else f"[{PALETTE['risk']}]TAMPERED[/]"
    console.print(
        f"[bold {PALETTE['cyan_400']}]{GLYPH} Flight {rec.get('subject_id')}[/] · {status} · "
        f"{rec.get('frame_count')} frames · {rec.get('total_tokens')} tok · "
        f"{rec.get('total_latency_ms')}ms · {len(anomalies)} anomalies"
    )
    for err in errs:
        console.print(f"  [{PALETTE['risk']}]ERR[/] {err}")
    for a in anomalies:
        console.print(f"  [{PALETTE['warn']}][{a.severity}] {a.code}[/] {a.message}")
    if not intact:
        raise typer.Exit(1)


@flight_app.command("diff")
def flight_diff(
    flight_a: str = typer.Argument(..., help="Baseline flight JSON"),
    flight_b: str = typer.Argument(..., help="Comparison flight JSON"),
) -> None:
    """Pinpoint the exact divergence frame between two Flight Recordings."""
    a = json.loads(Path(flight_a).read_text(encoding="utf-8"))
    b = json.loads(Path(flight_b).read_text(encoding="utf-8"))
    d = diff_flights(a, b)
    console.print(
        f"[bold {PALETTE['cyan_400']}]{GLYPH} Flight Diff[/] {d['subject_a']} vs {d['subject_b']}\n"
        f"  first divergence: {d['first_divergence_seq']} ({d['divergence_detail']})\n"
        f"  deltas          : frames {d['frames_delta']:+d} · tokens {d['tokens_delta']:+d} · "
        f"latency {d['latency_ms_delta']:+d}ms"
    )
