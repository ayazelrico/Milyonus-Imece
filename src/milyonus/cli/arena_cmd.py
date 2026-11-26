"""`milyonus arena ...` — Multi-Strategy Arena & Elo Leaderboard CLI (M5)."""

from __future__ import annotations

import asyncio

import typer
from rich.console import Console
from rich.table import Table

from milyonus.brand import GLYPH, PALETTE
from milyonus.imece.arena import ArenaContender, ArenaStore, run_arena_match

arena_app = typer.Typer(help="Pit strategies/models head-to-head and track persistent Elo ratings.")
console = Console()


@arena_app.command("leaderboard")
def arena_leaderboard(limit: int = typer.Option(25, "--limit", help="Max rows to show")) -> None:
    """Display the persistent Elo leaderboard."""
    store = ArenaStore()
    try:
        rows = store.leaderboard(limit=limit)
    finally:
        store.close()
    if not rows:
        console.print(f"[dim]{GLYPH} no arena matches recorded yet.[/]")
        return
    table = Table(title=f"{GLYPH} Strategy Arena Leaderboard")
    table.add_column("#", style="dim")
    table.add_column("Contender", style=f"bold {PALETTE['cyan_400']}")
    table.add_column("Elo")
    table.add_column("W-L-D")
    for idx, r in enumerate(rows, start=1):
        table.add_row(
            str(idx),
            f"{r['label']} ({r['contender_id']})",
            f"{float(r['rating']):.1f}",
            f"{r['wins']}-{r['losses']}-{r['draws']}",
        )
    console.print(table)


@arena_app.command("run")
def arena_run(
    task: str = typer.Argument(..., help="Task prompt to run head-to-head"),
    contender_a: str = typer.Option("direct", "--a", help="Contender A id/strategy"),
    contender_b: str = typer.Option("structured", "--b", help="Contender B id/strategy"),
    expect_substring: str | None = typer.Option(
        None,
        "--expect",
        help="Optional objective oracle substring that a winning output must contain",
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Run deterministic local simulation without calling LLM APIs"
    ),
) -> None:
    """Run a head-to-head match between two strategies and record Elo updates."""

    async def _go() -> None:
        if dry_run:

            async def _sim_a(t: str) -> str:
                return f"[{contender_a}] direct answer for: {t}"

            async def _sim_b(t: str) -> str:
                return f"[{contender_b}] structured step-by-step verified answer for: {t}"

            ca = ArenaContender(contender_a, contender_a, _sim_a)
            cb = ArenaContender(contender_b, contender_b, _sim_b)
        else:
            from milyonus.config.env import load_env
            from milyonus.config.loader import load_config
            from milyonus.providers.base import CompletionRequest, Message
            from milyonus.providers.router import build_provider

            load_env()
            cfg = load_config()
            provider = build_provider(cfg.provider)

            def _make_llm(style: str):
                async def _run(t: str) -> str:
                    chunks: list[str] = []
                    req = CompletionRequest(
                        system=f"Follow strategy '{style}'. Be accurate, concise, and verifiable.",
                        messages=[Message(role="user", content=t)],
                        max_output_tokens=cfg.provider.max_output_tokens,
                    )
                    async for ev in provider.stream(req):
                        if ev.kind == "text":
                            chunks.append(ev.delta)
                    return "".join(chunks)

                return _run

            ca = ArenaContender(contender_a, contender_a, _make_llm(contender_a))
            cb = ArenaContender(contender_b, contender_b, _make_llm(contender_b))

        oracle = None
        if expect_substring is not None:
            needle = expect_substring

            def _oracle(_t: str, out: str) -> tuple[bool, float]:
                ok = needle in out
                return ok, 1.0 if ok else 0.0

            oracle = _oracle

        store = ArenaStore()
        try:
            res = await run_arena_match(store, task, ca, cb, oracle_fn=oracle)
        finally:
            store.close()
        console.print(
            f"[{PALETTE['ok']}]{GLYPH} Winner:[/] [bold]{res.winner}[/] "
            f"[dim]({res.reason} · match {res.match_id})[/]"
        )
        for cid, delta in res.rating_changes.items():
            sign = "+" if delta["delta"] >= 0 else ""
            console.print(
                f"  {cid}: {delta['before']:.1f} → {delta['after']:.1f} ({sign}{delta['delta']:.1f})"
            )

    asyncio.run(_go())
