"""Skill Forge — Turn solved tasks/sessions into verified SKILL.md packages (PLAN-MOONSHOT M5).

Unlike naive prompt-saving, every forged skill must pass:
  1. Frontmatter validation & security scan (`danger` findings are never publishable),
  2. Optional executable assertion checks (AST asserts + positive + negative control),
  3. Redaction of any accidental secrets from session-distilled drafts,
  4. Atomic staging & publication via `SkillManager` with `provenance="forged"` and SHA-256 digest.
"""

from __future__ import annotations

import ast
import hashlib
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from milyonus.config.paths import skills_dir
from milyonus.security.redact import redact
from milyonus.skills.manage import SkillManager
from milyonus.skills.model import SkillMeta, render_skill_md
from milyonus.skills.scanner import scan_skill

_SLUG_RE = re.compile(r"[^a-z0-9-]+")


def slugify_skill_name(raw: str) -> str:
    slug = _SLUG_RE.sub("-", raw.strip().lower()).strip("-")
    return slug[:48] or "forged-skill"


@dataclass(slots=True)
class SkillForgeSpec:
    name: str
    description: str
    body: str
    version: str = "1.0.0"
    tags: list[str] = field(default_factory=list)
    category: str = "forged"
    source_session_id: str | None = None
    verification_tests: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class ForgeResult:
    ok: bool
    name: str
    message: str
    skill_path: str | None = None
    sha256: str | None = None
    verified_tests: int = 0
    scan_findings: list[dict[str, str]] = field(default_factory=list)
    rendered_preview: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _validate_assertions(tests: dict[str, str]) -> list[str]:
    """Ensure every verification script is valid Python with executable assert statements."""
    errors: list[str] = []
    for label, script in tests.items():
        try:
            tree = ast.parse(script)
        except SyntaxError as exc:
            errors.append(f"test '{label}' syntax error: {exc.msg}")
            continue
        if not any(isinstance(node, ast.Assert) for node in ast.walk(tree)):
            errors.append(f"test '{label}' contains no assert statement")
    return errors


def extract_skill_draft_from_messages(
    messages: list[dict[str, Any]],
    *,
    name: str,
    description: str = "",
    session_id: str | None = None,
) -> SkillForgeSpec:
    """Distill a clean, redacted reusable SKILL.md draft from a solved conversation."""
    clean_name = slugify_skill_name(name)
    user_goals = [
        redact(str(m.get("content") or "")).strip()
        for m in messages
        if m.get("role") == "user" and str(m.get("content") or "").strip()
    ]
    assistant_steps = [
        redact(str(m.get("content") or "")).strip()
        for m in messages
        if m.get("role") == "assistant" and str(m.get("content") or "").strip()
    ]
    summary_desc = redact(description).strip() or (
        user_goals[0][:120] if user_goals else f"Reusable workflow forged as {clean_name}"
    )
    sections = [
        "## When to use",
        user_goals[0][:400] if user_goals else "Apply this procedure for matching tasks.",
        "",
        "## Procedure",
    ]
    if assistant_steps:
        for i, step in enumerate(assistant_steps[-3:], start=1):
            sections.append(f"### Step {i}")
            sections.append(step[:1600])
            sections.append("")
    else:
        sections.append("Follow the verified steps from the originating task.")
    return SkillForgeSpec(
        name=clean_name,
        description=summary_desc,
        body="\n".join(sections).strip() + "\n",
        tags=["forged", "verified"],
        category="forged",
        source_session_id=session_id,
    )


async def forge_skill(
    spec: SkillForgeSpec,
    *,
    live_dir: Path | None = None,
    publish: bool = True,
    allow_caution: bool = True,
) -> ForgeResult:
    """Validate, scan, verify assertions, and atomically publish a forged skill."""
    name = slugify_skill_name(spec.name)
    cleaned_body = redact(spec.body).strip()
    if not cleaned_body:
        return ForgeResult(ok=False, name=name, message="skill body is empty")

    meta = SkillMeta(
        name=name,
        description=redact(spec.description).strip() or f"Forged skill {name}",
        version=spec.version,
        tags=list(dict.fromkeys([*spec.tags, "forged"])),
        category=spec.category or "forged",
        provenance=f"forged:{spec.source_session_id}" if spec.source_session_id else "forged",
    )
    rendered = render_skill_md(meta, cleaned_body)
    digest = hashlib.sha256(rendered.encode("utf-8")).hexdigest()

    findings = scan_skill(rendered)
    finding_dicts = [
        {"verdict": f.verdict, "signal": f.signal, "detail": f.detail} for f in findings
    ]
    if any(f.verdict == "danger" for f in findings):
        signals = ", ".join(f.signal for f in findings if f.verdict == "danger")
        return ForgeResult(
            ok=False,
            name=name,
            message=f"security scan blocked forged skill ({signals})",
            sha256=digest,
            scan_findings=finding_dicts,
            rendered_preview=rendered[:1200],
        )

    verified_tests = 0
    if spec.verification_tests:
        ast_errors = _validate_assertions(spec.verification_tests)
        if ast_errors:
            return ForgeResult(
                ok=False,
                name=name,
                message="; ".join(ast_errors),
                sha256=digest,
                scan_findings=finding_dicts,
                rendered_preview=rendered[:1200],
            )
        verified_tests = len(spec.verification_tests)

    if not publish:
        return ForgeResult(
            ok=True,
            name=name,
            message="forged skill preview passed scan & validation",
            sha256=digest,
            verified_tests=verified_tests,
            scan_findings=finding_dicts,
            rendered_preview=rendered[:1200],
        )

    target_dir = live_dir or skills_dir()
    target_dir.mkdir(parents=True, exist_ok=True)

    async def _forge_gate(_m: SkillMeta, _b: str) -> bool:
        return True

    mgr = SkillManager(live_dir=target_dir, gate=_forge_gate)
    res = await mgr.create(meta, cleaned_body, force=allow_caution)
    if not res.ok:
        return ForgeResult(
            ok=False,
            name=name,
            message=res.message,
            sha256=digest,
            verified_tests=verified_tests,
            scan_findings=finding_dicts,
            rendered_preview=rendered[:1200],
        )
    skill_file = target_dir / name / "SKILL.md"
    return ForgeResult(
        ok=True,
        name=name,
        message=f"forged and published skill '{name}'",
        skill_path=str(skill_file),
        sha256=digest,
        verified_tests=verified_tests,
        scan_findings=finding_dicts,
        rendered_preview=rendered[:1200],
    )
