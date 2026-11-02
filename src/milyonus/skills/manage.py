"""Agent-managed skills — the self-improving learning loop (PLAN §5.4).

The agent creates, patches, and deletes its own skills. Unlike Hermes, a new
skill is not trusted on write: it lands in a staging directory and must pass a
REPRODUCIBILITY GATE (a caller-supplied check that the skill's steps actually
work) plus the security scanner before it is promoted into the live skills dir.
Every skill also carries provenance so `skills why` can show where it came from.
"""

from __future__ import annotations

import re
import shutil
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from milyonus.config.paths import skills_dir
from milyonus.skills.model import SkillMeta, parse_skill_md, render_skill_md
from milyonus.skills.replay import replay_python
from milyonus.skills.scanner import may_install, scan_skill, worst_verdict

# A gate returns True if the drafted skill was validated (e.g. dry-run passed).
# Default gate executes named Python examples in isolation; other skill types
# require an injected domain-specific gate and otherwise remain staged.
ReproGate = Callable[[SkillMeta, str], Awaitable[bool]]


@dataclass(slots=True)
class ManageResult:
    ok: bool
    message: str
    name: str | None = None


class SkillManager:
    def __init__(
        self,
        *,
        live_dir: Path | None = None,
        staging_dir: Path | None = None,
        gate: ReproGate | None = None,
    ) -> None:
        self.live_dir = live_dir or skills_dir()
        self.staging_dir = staging_dir or (self.live_dir / "_staging")
        self.gate = gate or replay_python
        self.live_dir.mkdir(mode=0o700, parents=True, exist_ok=True)

    def _path(self, root: Path, name: str) -> Path:
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}", name):
            raise ValueError("invalid skill name")
        target = root / name
        if target.is_symlink() or target.resolve().parent != root.resolve():
            raise ValueError("skill path escapes its root")
        return target

    async def create(self, meta: SkillMeta, body: str, *, force: bool = False) -> ManageResult:
        try:
            staged = self._path(self.staging_dir, meta.name)
            target = self._path(self.live_dir, meta.name)
        except ValueError as exc:
            return ManageResult(False, str(exc), meta.name)
        text = render_skill_md(meta, body)

        # 1. Security scan — danger is never installable.
        findings = scan_skill(text)
        if not may_install(findings, force=force):
            v = worst_verdict(findings)
            sigs = ", ".join(f.signal for f in findings)
            return ManageResult(False, f"security scan blocked ({v}): {sigs}", meta.name)

        # 2. Reproducibility gate — the skill must be validated before promotion.
        staged.mkdir(parents=True, exist_ok=True)
        (staged / "SKILL.md").write_text(text, "utf-8")
        try:
            passed = await self.gate(meta, body)
        except Exception:
            passed = False
        if passed is not True:
            return ManageResult(
                False,
                "reproducibility gate failed — skill retained in staging, not promoted",
                meta.name,
            )

        # 3. Promote into the live directory.
        if target.exists():
            shutil.rmtree(target)
        shutil.move(str(staged), str(target))
        return ManageResult(True, f"skill created: {meta.name}", meta.name)

    def delete(self, name: str) -> ManageResult:
        try:
            target = self._path(self.live_dir, name)
        except ValueError as exc:
            return ManageResult(False, str(exc), name)
        if not target.exists():
            return ManageResult(False, f"no such skill: {name}", name)
        shutil.rmtree(target)
        return ManageResult(True, f"skill deleted: {name}", name)

    async def patch(self, name: str, new_body: str, *, force: bool = False) -> ManageResult:
        try:
            target = self._path(self.live_dir, name) / "SKILL.md"
        except ValueError as exc:
            return ManageResult(False, str(exc), name)
        if not target.exists():
            return ManageResult(False, f"no such skill: {name}", name)
        skill = parse_skill_md(target.read_text("utf-8"), target.parent)
        return await self.create(skill.meta, new_body, force=force)
