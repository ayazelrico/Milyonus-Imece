"""`milyonus imece` — run a task through the İmece-İRADE collective."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from milyonus.brand import GLYPH, PALETTE

imece_app = typer.Typer(
    help="Milyonus-Imece: many subagents, IRADE council, three independent gates."
)
console = Console()

_KIND_MARK = {"independent": "bağımsız", "flexible": "esnek", "fixed": "sabit"}
_NEED_MARK = {"mandatory": "🔴", "conditional": "🟠", "scale": "🟡"}


def _stop_file() -> Path:
    from milyonus.config.paths import data_root

    return data_root() / "imece.stop"


def _allocation_table(total: int) -> Table:
    from milyonus.imece.scale import COUNCIL_SIZE, allocate

    alloc = allocate(total)
    t = Table(title=f"{GLYPH} İmece dağılımı — {total} ajan (+{COUNCIL_SIZE} IRADE konseyi)")
    t.add_column("Blok")
    t.add_column("", justify="center")
    t.add_column("Tür")
    t.add_column("10.000'de", justify="right")
    t.add_column("Bu koşuda", justify="right")
    for spec, n in alloc.rows():
        t.add_row(
            spec.label, _NEED_MARK[spec.necessity], _KIND_MARK[spec.kind], str(spec.weight), str(n)
        )
    return t


def _seat_providers(cfg) -> tuple[dict, list[str]]:
    """Build seat -> Provider and independence warnings."""
    from milyonus.config.schema import IMECE_SEATS
    from milyonus.providers.router import build_provider

    seats = {"pool": build_provider(cfg.provider)}
    models = {"pool": f"{cfg.provider.name}:{cfg.provider.model}"}
    for key in IMECE_SEATS:
        pc = cfg.imece.seats.get(key)
        if pc is None:
            models[key] = models["pool"]
            continue
        seat = key.replace("council_", "council:", 1)
        seats[seat] = build_provider(pc)
        models[key] = f"{pc.name}:{pc.model}"

    warnings: list[str] = []
    council = [models[k] for k in IMECE_SEATS if k.startswith("council_")]
    if len(set(council)) < len(council):
        warnings.append(
            f"IRADE council uses {len(set(council))} distinct model(s) for 5 seats — "
            "correlated errors (ρ) stay high. Set [imece.seats.council_*] to different vendors."
        )
    if models["approval"] in council:
        warnings.append(
            "Onay Merci shares a model with the IRADE council — Kapı 3 is not fully independent. "
            "Set [imece.seats.approval]."
        )
    return seats, warnings


@imece_app.command("plan")
def plan_cmd(
    agents: int = typer.Option(None, "--agents", "-n", help="Total subagents (default: config)"),
) -> None:
    """Show how N agents are distributed across blocks (no model calls)."""
    from milyonus.config.loader import load_config
    from milyonus.imece.scale import ScaleError

    total = agents or load_config().imece.agents
    try:
        console.print(_allocation_table(total))
    except ScaleError as exc:
        console.print(f"[{PALETTE['risk']}]{exc}[/]")
        raise typer.Exit(1) from exc


@imece_app.command("seats")
def seats_cmd() -> None:
    """Show which model sits in each seat, and independence warnings."""
    from milyonus.config.env import load_env
    from milyonus.config.loader import load_config
    from milyonus.config.schema import IMECE_SEATS

    load_env()
    cfg = load_config()
    t = Table(title=f"{GLYPH} İmece seats")
    t.add_column("Seat")
    t.add_column("Model")
    for key in IMECE_SEATS:
        pc = cfg.imece.seats.get(key)
        t.add_row(
            key,
            f"{pc.name}:{pc.model}" if pc else f"(pool) {cfg.provider.name}:{cfg.provider.model}",
        )
    console.print(t)
    try:
        _, warnings = _seat_providers(cfg)
    except Exception as exc:  # a missing key should not hide the table
        console.print(f"[{PALETTE['warn']}]could not build providers: {exc}[/]")
        return
    for w in warnings:
        console.print(f"[{PALETTE['warn']}]⚠ {w}[/]")


@imece_app.command("stop")
def stop_cmd() -> None:
    """Ask a running imece to stop before its next phase (human stop authority)."""
    path = _stop_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(time.strftime("%Y-%m-%dT%H:%M:%S"), encoding="utf-8")
    console.print(f"stop requested → {path}")


@imece_app.command("run")
def run_cmd(
    task: str = typer.Argument(..., help="The task / problem for the collective"),
    agents: int = typer.Option(None, "--agents", "-n", help="Total subagents (default: config)"),
    parallel: int = typer.Option(None, "--parallel", "-p", help="Concurrent subagents"),
    rounds: int = typer.Option(None, "--rounds", help="Max rounds"),
    max_tokens: int = typer.Option(None, "--max-tokens", help="Shared token pool"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the cost confirmation"),
    out: str = typer.Option(None, "--out", help="Write the deliverable to this file"),
) -> None:
    """Run a task through Kapı 1 → imece ↔ IRADE → Kapı 2 → Kapı 3."""
    raise typer.Exit(
        run_imece(
            task,
            agents=agents,
            parallel=parallel,
            rounds=rounds,
            max_tokens=max_tokens,
            yes=yes,
            out=Path(out) if out else None,
        )
    )


def run_imece(
    task: str,
    *,
    agents: int | None = None,
    parallel: int | None = None,
    rounds: int | None = None,
    max_tokens: int | None = None,
    yes: bool = False,
    out: Path | None = None,
) -> int:
    import asyncio

    from milyonus.config.env import load_env
    from milyonus.config.loader import load_config
    from milyonus.config.paths import data_root, logs_dir
    from milyonus.imece.agents import LLMAgentFn
    from milyonus.imece.irade import Calibrator, Decision, DecisionRequest, IradeSettings
    from milyonus.imece.orchestrator import Imece, ImeceSettings
    from milyonus.imece.scale import ScaleError
    from milyonus.tools.fs.tools import make_fs_tools
    from milyonus.tools.registry import ToolRegistry
    from milyonus.tools.web.tools import make_web_tools

    load_env()
    cfg = load_config()
    ic = cfg.imece
    settings = ImeceSettings(
        agents=agents or ic.agents,
        max_parallel=parallel or ic.max_parallel,
        max_tokens=max_tokens or ic.max_tokens,
        max_rounds=rounds or ic.max_rounds,
        max_clusters=ic.max_clusters,
        shortlist=ic.shortlist,
        pass_threshold=ic.pass_threshold,
        irade=IradeSettings(
            veto_floor=ic.veto_floor,
            hard_veto_floor=ic.hard_veto_floor,
            spread_threshold=ic.spread_threshold,
            audit_rate=ic.audit_rate,
        ),
    )
    try:
        console.print(_allocation_table(settings.agents))
    except ScaleError as exc:
        console.print(f"[{PALETTE['risk']}]{exc}[/]")
        return 1

    seats, warnings = _seat_providers(cfg)
    for w in warnings:
        console.print(f"[{PALETTE['warn']}]⚠ {w}[/]")
    console.print(
        f"[dim]parallel {settings.max_parallel} · token pool {settings.max_tokens:,} · "
        f"rounds ≤ {settings.max_rounds}. Every agent is a real model call.[/]"
    )
    interactive = sys.stdin.isatty()
    if not yes and interactive and not typer.confirm("Start the run?", default=True):
        return 1

    tools = ToolRegistry()
    for tool in [*make_fs_tools(Path.cwd()), *make_web_tools()]:
        tools.register(tool)
    agent_fn = LLMAgentFn(
        seats=seats,
        tools=tools,
        allow_tools=frozenset(ic.allow_tools),
        max_output_tokens=ic.max_output_tokens,
    )

    async def human(req: DecisionRequest, d: Decision) -> str | None:
        """Tier 4: the human has the last word on irreversible or deadlocked decisions."""
        console.print(
            f"\n[bold {PALETTE['warn']}]Kademe 4 — human decision required[/] ({req.kind})"
        )
        console.print(f"  why: {', '.join(d.escalations) or 'irreversible'}")
        for o in req.options:
            veto = f" [red]veto: {', '.join(d.vetoed[o.id])}[/]" if o.id in d.vetoed else ""
            console.print(
                f"  [{o.id}] total {d.totals.get(o.id, 0):.2f}{veto}  {o.summary[:160]!r}"
            )
        if not interactive:
            return None
        answer = await asyncio.to_thread(input, "  choose an option id (empty = stop): ")
        return answer.strip() or None

    stop = _stop_file()
    stop.unlink(missing_ok=True)
    started = time.time()

    def on_phase(name: str) -> None:
        console.print(
            f"[{PALETTE['cyan_400']}]{GLYPH}[/] {name} [dim]({time.time() - started:.0f}s)[/]"
        )

    imece = Imece(
        agent_fn,
        settings,
        human=human if interactive else None,
        should_stop=stop.exists,
        calibrator=Calibrator(data_root() / "imece" / "calibration.jsonl"),
        on_phase=on_phase,
    )
    try:
        result = asyncio.run(imece.run(task))
    except KeyboardInterrupt:
        console.print("[dim]interrupted[/]")
        return 130

    report_dir = logs_dir() / "imece"
    report_dir.mkdir(parents=True, exist_ok=True)
    report = report_dir / f"{time.strftime('%Y%m%d-%H%M%S')}.json"
    report.write_text(
        json.dumps(result.to_dict(), ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )

    colour = {"accepted": "ok", "rejected": "risk", "stopped": "warn", "budget": "warn"}[
        result.status
    ]
    console.print(
        f"\n[bold {PALETTE.get(colour, 'white')}]status: {result.status}[/] · rounds {result.rounds} · tokens {result.tokens:,}"
    )
    if result.verdict:
        v = result.verdict
        console.print(
            f"Kapı 3: {v.accepts} accept · {v.conditional} conditional · {v.rejects} reject"
        )
        for r in v.reasons[:5]:
            console.print(f"  - {r}")
    for n in result.notes:
        console.print(f"[dim]· {n}[/]")
    if result.failed_by_block:
        console.print(f"[{PALETTE['warn']}]failed agent runs by block: {result.failed_by_block}[/]")
    for w in result.warnings:
        console.print(f"[{PALETTE['warn']}]⚠ observer: {w}[/]")
    if result.deliverable:
        if out:
            out.write_text(result.deliverable, encoding="utf-8")
            console.print(f"deliverable → {out}")
        else:
            console.rule("deliverable")
            console.print(result.deliverable)
    console.print(f"[dim]full report → {report}[/]")
    return 0 if result.status == "accepted" else 2
