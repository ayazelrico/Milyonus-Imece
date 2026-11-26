"""Milyonus CLI entry point.

This is the single binary users invoke as `milyonus` (alias `mil`). In F0 it
exposes the first live surface: version, banner, and `doctor`. Later phases add
`run`, `setup`, `memory`, `skills`, `gateway`, `cron`, `selfmod`, and `audit`
as subcommands on this same app.
"""

from __future__ import annotations

import typer
from rich.console import Console

from milyonus import __version__
from milyonus.brand import GLYPH, PALETTE, PRODUCT

app = typer.Typer(
    name="milyonus",
    help=f"{GLYPH} {PRODUCT} — remembers, verifies, evolves.",
    no_args_is_help=False,
    invoke_without_command=True,
    add_completion=False,
)
console = Console()


def _version_callback(value: bool) -> None:
    if value:
        console.print(
            f"[bold {PALETTE['cyan_400']}]{GLYPH} {PRODUCT}[/] "
            f"[{PALETTE['chrome_200']}]v{__version__}[/]"
        )
        raise typer.Exit()


@app.callback()
def _main(
    ctx: typer.Context,
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        callback=_version_callback,
        is_eager=True,
        help="Show the version and exit.",
    ),
) -> None:
    """Milyonus Agent command-line interface. Starts an interactive session
    when called with no arguments."""
    from pathlib import Path

    from milyonus.selfmod.harness import SelfModHarness

    core = Path(__file__).resolve().parents[2]
    repo = next((p for p in core.parents if (p / ".git").exists()), None)
    if repo is not None and ctx.invoked_subcommand not in ("selfmod", "doctor"):
        h = SelfModHarness(repo)
        if h.pending() is not None:
            console.print(
                f"Core changed after a test-gated self-edit. Review it in {repo}; run 'milyonus selfmod accept' there, or 'milyonus selfmod rollback'."
            )
            raise typer.Exit(1)
    # No subcommand -> start the interactive session (the default surface).
    if ctx.invoked_subcommand is None:
        from milyonus.cli.tui import run_tui

        raise typer.Exit(code=run_tui())


@app.command()
def doctor() -> None:
    """Run environment and health diagnostics."""
    from milyonus.cli.doctor import run_doctor

    raise typer.Exit(code=run_doctor())


@app.command()
def setup() -> None:
    """First-run setup wizard: provider and key."""
    from milyonus.cli.setup import run_setup

    raise typer.Exit(code=run_setup())


@app.command()
def acp() -> None:
    """Run as an ACP server (editor integration, stdio/JSON-RPC)."""
    import asyncio

    from milyonus.acp.server import run_stdio
    from milyonus.config.env import load_env
    from milyonus.config.loader import load_config

    load_env()
    asyncio.run(run_stdio(load_config()))


@app.command()
def research(
    query: str = typer.Argument(..., help="The research question"),
    sources: int = typer.Option(6, help="Max sources to read"),
    subqueries: int = typer.Option(3, help="How many sub-queries to plan"),
) -> None:
    """Deep web research: plan, search, read sources, synthesize a cited report."""
    from milyonus.cli.research_cmd import run_research

    raise typer.Exit(code=run_research(query, sources=sources, subqueries=subqueries))


@app.command()
def chat() -> None:
    """Start an interactive terminal session (same as bare `milyonus`)."""
    from milyonus.cli.tui import run_tui

    raise typer.Exit(code=run_tui())


@app.command()
def run(
    task: str = typer.Argument(..., help="One-shot task prompt for the agent"),
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Approve caution/danger tools automatically (hard-blocked patterns stay blocked).",
    ),
    max_iterations: int = typer.Option(25, "--max-iterations", min=1, max=100),
) -> None:
    """Run a single non-interactive task and print the final answer (PLAN §10)."""
    import asyncio
    from pathlib import Path

    from milyonus.config.env import load_env
    from milyonus.config.loader import load_config
    from milyonus.core.budget import Budget
    from milyonus.core.loop import AgentLoop
    from milyonus.core.store import SessionStore
    from milyonus.memory.factory import verified_pipeline
    from milyonus.memory.render import build_snapshot
    from milyonus.memory.store import MemoryStore
    from milyonus.memory.tool import make_memory_tools
    from milyonus.prompt.builder import build_system_prompt, skill_index_section
    from milyonus.prompt.compressor import compact_history
    from milyonus.providers.base import Message, ProviderError, ToolCall
    from milyonus.providers.router import build_provider
    from milyonus.research.tool import make_research_tools
    from milyonus.security.context_files import safe_context_sections
    from milyonus.security.risk import RiskEngine
    from milyonus.skills.engine import SkillEngine
    from milyonus.skills.manage import SkillManager
    from milyonus.skills.tool import make_skill_tools
    from milyonus.tools.clarify import ClarifyBudget, make_clarify_tool
    from milyonus.tools.fs.tools import make_fs_tools
    from milyonus.tools.registry import ToolRegistry
    from milyonus.tools.terminal.tools import make_shell_tool
    from milyonus.tools.web.tools import make_web_tools

    load_env()
    try:
        cfg = load_config()
    except Exception as exc:  # noqa: BLE001
        console.print(f"[{PALETTE['risk']}]Config error:[/] {exc}")
        raise typer.Exit(code=1) from exc

    async def _exec() -> int:
        root = Path.cwd()
        provider = build_provider(cfg.provider)
        mem_store = MemoryStore()
        store = SessionStore()
        try:
            pipeline = verified_pipeline(mem_store, cfg)
            sid = store.create_session("cli", user_ref="local", title=task[:60])
            reg = ToolRegistry()
            for t in make_fs_tools(root):
                reg.register(t)
            reg.register(
                make_shell_tool(
                    root,
                    backend=cfg.security.sandbox_backend,
                    image=cfg.security.sandbox_image,
                )
            )
            for t in make_web_tools():
                reg.register(t)
            for t in make_memory_tools(pipeline, session_id=sid, user_ref="local"):
                reg.register(t)
            skill_eng = SkillEngine()
            for t in make_skill_tools(skill_eng, SkillManager()):
                reg.register(t)
            for t in make_research_tools(provider):
                reg.register(t)
            clarify_budget = ClarifyBudget(max_per_turn=1)
            reg.register(make_clarify_tool(None, budget=clarify_budget))

            snapshot = build_snapshot(mem_store, config=cfg.memory, user_ref="local")
            extras = [skill_index_section(skill_eng.list_level0())]
            ctx_sections, _ = safe_context_sections(root)
            extras.extend(ctx_sections)
            system = build_system_prompt(memory=snapshot, extra_sections=extras)
            risk_engine = RiskEngine()

            async def approve(call: ToolCall, risk: str) -> bool:
                decision, _reason, _ = risk_engine.classify(call, risk)
                if decision == "block":
                    return False
                return decision == "auto" or yes

            async def _compress(msgs, pressure):
                res = await compact_history(msgs, pressure=pressure)
                return res.messages, (res.banner if res.compacted else None)

            loop = AgentLoop(
                provider=provider,
                tools=reg,
                system_prompt=system,
                budget=Budget(max_iterations=max_iterations),
                approve=approve,
                risk_engine=risk_engine,
                clarify_budget=clarify_budget,
                compressor=_compress,
                max_output_tokens=cfg.provider.max_output_tokens,
                max_tool_result_chars=8_000,
            )
            store.append_message(sid, turn=1, role="user", content=task)
            history = [Message(role="user", content=task)]
            try:
                answer = await loop.run_turn(history)
            except ProviderError as exc:
                console.print(f"[{PALETTE['risk']}]Provider error:[/] {exc}")
                return 1
            store.append_message(sid, turn=1, role="assistant", content=answer)
            console.print(answer, markup=False)
            return 0
        finally:
            store.close()
            mem_store.close()

    raise typer.Exit(code=asyncio.run(_exec()))


from milyonus.cli.admin_cmd import admin_app  # noqa: E402
from milyonus.cli.arena_cmd import arena_app  # noqa: E402
from milyonus.cli.chaos_cmd import chaos_app  # noqa: E402
from milyonus.cli.cron_cmd import cron_app  # noqa: E402
from milyonus.cli.eval_cmd import eval_app  # noqa: E402
from milyonus.cli.gateway_cmd import gateway_app  # noqa: E402
from milyonus.cli.imece_cmd import imece_app  # noqa: E402
from milyonus.cli.mcp_cmd import mcp_app  # noqa: E402
from milyonus.cli.memory_cmd import audit_app, memory_app  # noqa: E402
from milyonus.cli.proactive_cmd import proactive_app  # noqa: E402
from milyonus.cli.proof_cmd import proof_app  # noqa: E402
from milyonus.cli.selfmod_cmd import selfmod_app  # noqa: E402
from milyonus.cli.skills_cmd import skills_app  # noqa: E402
from milyonus.cli.user_cmd import user_app  # noqa: E402
from milyonus.cli.web_cmd import web_app  # noqa: E402

app.add_typer(memory_app, name="memory")
app.add_typer(admin_app, name="admin")
app.add_typer(audit_app, name="audit")
app.add_typer(skills_app, name="skills")
app.add_typer(gateway_app, name="gateway")
app.add_typer(selfmod_app, name="selfmod")
app.add_typer(eval_app, name="eval")
app.add_typer(cron_app, name="cron")
app.add_typer(proactive_app, name="proactive")
app.add_typer(mcp_app, name="mcp")
app.add_typer(user_app, name="user")
app.add_typer(imece_app, name="imece")
app.add_typer(web_app, name="web")
app.add_typer(proof_app, name="proof")
app.add_typer(chaos_app, name="chaos")
app.add_typer(arena_app, name="arena")


def main() -> None:
    """console_scripts entry point."""
    app()


if __name__ == "__main__":
    main()
