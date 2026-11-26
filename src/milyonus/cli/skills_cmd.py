"""`milyonus skills ...` — inspect and manage skills from the terminal."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from milyonus.brand import GLYPH, PALETTE
from milyonus.skills.engine import SkillEngine

skills_app = typer.Typer(help="Inspect and manage skills.")
console = Console()


@skills_app.command("list")
def skills_list() -> None:
    """List registered skills."""
    eng = SkillEngine()
    skills = eng.load_all()
    if not skills:
        console.print(f"[dim]{GLYPH} no registered skills.[/]")
        raise typer.Exit()
    table = Table(title=f"{GLYPH} Skills")
    table.add_column("Name", style=f"bold {PALETTE['cyan_400']}")
    table.add_column("Category")
    table.add_column("Description", overflow="fold")
    table.add_column("Source", style="dim")
    table.add_column("Version", style="dim")
    for s in skills:
        table.add_row(
            s.meta.name,
            s.meta.category,
            s.meta.description,
            s.meta.provenance,
            s.meta.version,
        )
    console.print(table)


@skills_app.command("view")
def skills_view(name: str, ref: str = typer.Argument(None)) -> None:
    """Show a skill's content."""
    eng = SkillEngine()
    console.print(eng.view(name, ref))


@skills_app.command("why")
def skills_why(name: str) -> None:
    """Show a skill's provenance."""
    eng = SkillEngine()
    skill = eng.get(name)
    if skill is None:
        console.print(f"[{PALETTE['risk']}]not found: {name}[/]")
        raise typer.Exit(code=1)
    m = skill.meta
    console.print(f"[bold]{GLYPH} {m.name}[/] v{m.version}")
    console.print(f"  source    : {m.provenance}")
    console.print(f"  category  : {m.category}")
    console.print(f"  platforms : {', '.join(m.platforms) or 'all'}")
    console.print(f"  path      : {skill.path}")
    refs = skill.reference_files()
    if refs:
        console.print(f"  references: {', '.join(refs)}")


@skills_app.command("promote-repair")
def skills_promote_repair(name: str, task_manifest: str) -> None:
    """Promote a staged repair after replaying independently authored task oracles.

    Supply a JSON object mapping task names to Python oracle file paths,
    relative to the manifest. Each script imports the staged artifact.
    """
    import asyncio
    import json
    from pathlib import Path

    from milyonus.skills.manage import SkillManager

    path = Path(task_manifest)
    try:
        entries = json.loads(path.read_text("utf-8"))
        if not isinstance(entries, dict) or not all(isinstance(p, str) for p in entries.values()):
            raise ValueError("expected a JSON mapping of task labels to oracle paths")
        tasks = {k: (path.parent / v).read_text("utf-8") for k, v in entries.items()}
        result = asyncio.run(SkillManager().promote_repair(name, tasks))
    except (OSError, ValueError, SyntaxError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    console.print(result.message, markup=False)
    if not result.ok:
        raise typer.Exit(1)


@skills_app.command("revoke-oracle")
def skills_revoke_oracle(sha256: str) -> None:
    """Revoke an oracle for future promotion/use and withdraw dependent skills."""
    from milyonus.skills.manage import SkillManager

    try:
        removed = SkillManager().revoke_oracle(sha256)
    except (OSError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    console.print(f"Oracle revoked. Skills withdrawn: {len(removed)}", markup=False)
    for name in removed:
        console.print(name, markup=False)


@skills_app.command("recover-publications")
def skills_recover_publications(apply: bool = typer.Option(False, "--apply")) -> None:
    """Inspect interrupted publications; --apply restores only eligible previous versions."""
    import json

    from milyonus.config.paths import skills_dir
    from milyonus.skills.publication import recover_publications

    root = skills_dir()
    if not root.exists():
        console.print("[]", markup=False)
        return
    try:
        rows = recover_publications(root, apply=apply)
    except (OSError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    console.print(json.dumps(rows, indent=2), markup=False, soft_wrap=True)
    if any(row["status"] in {"unrecognized", "ambiguous", "recovery_failed"} for row in rows):
        raise typer.Exit(2)


@skills_app.command("install")
def skills_install(
    source: str = typer.Argument(
        ...,
        help="Skill locator: github:owner/repo[@ref][:path], well-known:host/name, or https://...",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Allow caution-level findings (danger findings can NEVER be overridden).",
    ),
) -> None:
    """Install a skill from GitHub, /.well-known/skills/, or an HTTPS hub URL."""
    import asyncio

    from milyonus.skills.hub import install_from_hub

    res = asyncio.run(install_from_hub(source, force=force))
    color = PALETTE["ok"] if res.ok else PALETTE["risk"]
    console.print(f"[{color}]{res.message}[/]")
    if not res.ok:
        raise typer.Exit(1)


@skills_app.command("check")
def skills_check() -> None:
    """Check installed hub skills for upstream content-hash drift (PLAN §5.3)."""
    import asyncio

    from milyonus.skills.hub import check_drift

    reports = asyncio.run(check_drift())
    if not reports:
        console.print(f"[dim]{GLYPH} no hub-tracked skills installed.[/]")
        return
    table = Table(title=f"{GLYPH} Skill Upstream Drift")
    table.add_column("Name", style=f"bold {PALETTE['cyan_400']}")
    table.add_column("Status")
    table.add_column("Source", style="dim")
    table.add_column("Local → Remote", style="dim")
    has_drift = False
    for r in reports:
        color = (
            PALETTE["ok"]
            if r.status == "up_to_date"
            else (PALETTE["warn"] if r.status == "drifted" else PALETTE["risk"])
        )
        if r.status != "up_to_date":
            has_drift = True
        hashes = (
            f"{r.local_sha256[:10]} → {(r.remote_sha256 or '')[:10]}"
            if r.remote_sha256
            else r.detail
        )
        table.add_row(r.name, f"[{color}]{r.status}[/]", r.source_id, hashes)
    console.print(table)
    if has_drift:
        raise typer.Exit(2)


@skills_app.command("forge")
def skills_forge(
    name: str = typer.Argument(..., help="Target skill name"),
    description: str = typer.Option(..., "--description", "-d", help="One-line skill description"),
    body_file: str | None = typer.Option(
        None, "--body-file", "-f", help="Markdown file containing the skill procedure"
    ),
    body: str = typer.Option("", "--body", "-b", help="Inline Markdown procedure body"),
    from_session: str | None = typer.Option(
        None, "--from-session", help="Distill procedure from a saved core session id"
    ),
    test_file: str | None = typer.Option(
        None, "--test", help="Optional Python assertion script to validate via AST before publish"
    ),
    preview_only: bool = typer.Option(False, "--preview", help="Validate without publishing"),
) -> None:
    """Forge, scan, validate, and atomically publish a verified SKILL.md package (M5)."""
    import asyncio

    from milyonus.core.store import SessionStore
    from milyonus.skills.forge import (
        SkillForgeSpec,
        extract_skill_draft_from_messages,
        forge_skill,
    )

    if from_session is not None:
        ss = SessionStore()
        try:
            msgs = [dict(r) for r in ss.history(from_session)]
        finally:
            ss.close()
        if not msgs:
            console.print(f"[{PALETTE['risk']}]session not found or empty: {from_session}[/]")
            raise typer.Exit(1)
        spec = extract_skill_draft_from_messages(
            msgs, name=name, description=description, session_id=from_session
        )
    else:
        content = Path(body_file).read_text(encoding="utf-8") if body_file is not None else body
        spec = SkillForgeSpec(name=name, description=description, body=content)

    if test_file is not None:
        tf = Path(test_file)
        spec.verification_tests[tf.name] = tf.read_text(encoding="utf-8")

    res = asyncio.run(forge_skill(spec, publish=not preview_only))
    color = PALETTE["ok"] if res.ok else PALETTE["risk"]
    console.print(f"[{color}]{GLYPH} {res.message}[/]")
    if res.sha256:
        console.print(f"  [dim]sha256={res.sha256[:16]}… · tests={res.verified_tests}[/]")
    if not res.ok:
        raise typer.Exit(1)
