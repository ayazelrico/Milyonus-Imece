"""`milyonus cron ...` — manage scheduled tasks (the automation definitions)."""

from __future__ import annotations

import time

import typer
from rich.console import Console
from rich.table import Table

from milyonus.brand import GLYPH, PALETTE
from milyonus.cron.schedule import ScheduleError, parse_schedule
from milyonus.cron.store import CronStore

cron_app = typer.Typer(help="Manage scheduled tasks.")
console = Console()


@cron_app.command("add")
def cron_add(
    name: str = typer.Argument(..., help="Task name"),
    when: str = typer.Argument(..., help="Schedule: '30m', '0 9 * * *', or 'every day at 9:00'"),
    prompt: str = typer.Argument(..., help="What the agent should do"),
    channel: str = typer.Option(None, help="Deliver result to this channel"),
    authorized: bool = typer.Option(
        False,
        "--authorized",
        help="Pre-approve outward/irreversible actions (otherwise safe-only)",
    ),
) -> None:
    """Add a scheduled task. Creating a standing rule — review the schedule."""
    try:
        sched = parse_schedule(when)
    except ScheduleError as exc:
        console.print(f"[{PALETTE['risk']}]{exc}[/]")
        raise typer.Exit(code=1) from exc
    store = CronStore()
    autonomy = "authorized" if authorized else "safe-only"
    tid = store.add(name, when, prompt, channel=channel, autonomy=autonomy)
    nxt = time.strftime("%Y-%m-%d %H:%M", time.localtime(sched.next_after(time.time())))
    console.print(
        f"[{PALETTE['ok']}]{GLYPH} scheduled[/] [bold]{name}[/] ({sched.display}) "
        f"· next {nxt} · autonomy={autonomy} · {tid}"
    )
    if authorized:
        console.print(
            f"[{PALETTE['warn']}]⚠ this task may take outward/irreversible actions unattended.[/]"
        )


@cron_app.command("list")
def cron_list() -> None:
    """List scheduled tasks."""
    store = CronStore()
    tasks = store.list()
    if not tasks:
        console.print(f"[dim]{GLYPH} no scheduled tasks.[/]")
        raise typer.Exit()
    table = Table(title=f"{GLYPH} Scheduled Tasks")
    table.add_column("Name", style=f"bold {PALETTE['cyan_400']}")
    table.add_column("Schedule")
    table.add_column("Next run")
    table.add_column("Autonomy")
    table.add_column("id", style="dim")
    for t in tasks:
        nxt = time.strftime("%m-%d %H:%M", time.localtime(t.next_run)) if t.next_run else "-"
        color = PALETTE["warn"] if t.autonomy == "authorized" else PALETTE["chrome_500"]
        table.add_row(t.name, t.schedule, nxt, f"[{color}]{t.autonomy}[/]", t.id)
    console.print(table)


@cron_app.command("remove")
def cron_remove(task_id: str) -> None:
    """Remove a scheduled task."""
    store = CronStore()
    ok = store.remove(task_id)
    if ok:
        console.print(f"[{PALETTE['ok']}]{GLYPH} removed {task_id}[/]")
    else:
        console.print(f"[{PALETTE['risk']}]not found: {task_id}[/]")
        raise typer.Exit(code=1)


@cron_app.command("run")
def cron_run(
    task_id: str | None = typer.Argument(
        None, help="Run a specific task id immediately (otherwise runs all due tasks)."
    ),
) -> None:
    """Execute due scheduled tasks (or one specific task) immediately."""
    import asyncio
    from pathlib import Path

    from milyonus.config.env import load_env
    from milyonus.config.loader import load_config
    from milyonus.proactive.runner import run_scheduled_task
    from milyonus.providers.router import build_provider

    load_env()
    cfg = load_config()
    provider = build_provider(cfg.provider)
    store = CronStore()
    if task_id is not None:
        tasks = [t for t in store.list() if t.id == task_id]
        if not tasks:
            console.print(f"[{PALETTE['risk']}]not found: {task_id}[/]")
            raise typer.Exit(code=1)
    else:
        tasks = store.due()
        if not tasks:
            console.print(f"[dim]{GLYPH} no due scheduled tasks.[/]")
            return

    async def _run_all() -> int:
        failures = 0
        for t in tasks:
            answer, trace, denied = await run_scheduled_task(
                t,
                provider=provider,
                workspace=Path.cwd(),
                max_output_tokens=cfg.provider.max_output_tokens,
            )
            store.mark_ran(t.id)
            color = PALETTE["ok"] if trace.success else PALETTE["risk"]
            console.print(f"[{color}]{GLYPH} {t.name}[/] ({trace.outcome})")
            console.print(answer, markup=False)
            if denied:
                console.print(f"[{PALETTE['warn']}]denied: {', '.join(denied)}[/]")
            if not trace.success:
                failures += 1
        return failures

    if asyncio.run(_run_all()):
        raise typer.Exit(code=1)
