"""Agent-managed skills — the self-improving learning loop (PLAN §5.4).

The agent creates, patches, and deletes its own skills. Unlike Hermes, a new
skill is not trusted on write: it lands in a staging directory and must pass a
REPRODUCIBILITY GATE (a caller-supplied check that the skill's steps actually
work) plus the security scanner before it is promoted into the live skills dir.
Every skill also carries provenance so `skills why` can show where it came from.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
from collections.abc import Awaitable, Callable
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from tempfile import mkdtemp

from milyonus.config.paths import skills_dir
from milyonus.imece.execution import PythonExecutor, python_files
from milyonus.skills.model import SkillMeta, parse_skill_md, render_skill_md
from milyonus.skills.repair import (
    MAX_RECEIPT_BYTES,
    RepairSkillError,
    _read_file,
    _record_oracle_revocation,
    _refuse_revoked_oracles,
    _repair_catalog_lock,
)
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

    def _publish_reviewed(self, name: str, text: str, receipt: dict | None = None) -> None:
        """Publish frozen bytes; keep the previous version if rollback fails.

        The catalog lock coordinates readers and revocation, but two directory
        renames are not an atomic crash-recovery transaction.
        """
        from milyonus.skills.publication import sync_renames, tree_digest, write_journal

        transaction = Path(mkdtemp(dir=self.live_dir, prefix=".publish-"))
        retain_recovery = False
        try:
            new = transaction / "new"
            new.mkdir()
            (new / "SKILL.md").write_text(text, "utf-8")
            if receipt is not None:
                (new / "replays.json").write_text(json.dumps(receipt, indent=2), "utf-8")
            with _repair_catalog_lock(self.live_dir) as catalog:
                if receipt is not None:
                    _refuse_revoked_oracles(catalog, receipt["tasks"].values())
                target = self._path(self.live_dir, name)
                backup = transaction / "previous"
                previous = None
                if target.exists():
                    if not target.is_dir():
                        raise NotADirectoryError(f"skill target is not a directory: {target}")
                    previous = tree_digest(catalog, name)
                write_journal(catalog, transaction, name, previous)
                try:
                    if previous is not None:
                        target.rename(backup)
                        sync_renames(catalog, transaction)
                    new.rename(target)
                    sync_renames(catalog, transaction)
                except BaseException:
                    if backup.exists():
                        try:
                            backup.rename(target)
                            sync_renames(catalog, transaction)
                        except BaseException as exc:
                            # Automatic TemporaryDirectory cleanup would delete
                            # the only remaining copy of the previous skill.
                            retain_recovery = True
                            location = backup if backup.exists() else target
                            raise OSError(
                                f"skill publication rollback failed; previous version retained at {location}"
                            ) from exc
                    elif not new.exists():
                        retain_recovery = True  # published, but durability is uncertain
                    raise
        finally:
            if not retain_recovery:
                shutil.rmtree(transaction)

    async def create(
        self, meta: SkillMeta, body: str, *, force: bool = False, stage_only: bool = False
    ) -> ManageResult:
        meta = deepcopy(meta)
        try:
            staged = self._path(self.staging_dir, meta.name)
            self._path(self.live_dir, meta.name)
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
        if (staged / "SKILL.md").is_symlink():
            return ManageResult(False, "invalid staged skill file", meta.name)
        (staged / "SKILL.md").write_text(text, "utf-8")
        try:
            passed = await self.gate(deepcopy(meta), body)
        except Exception:
            passed = False
        if passed is not True:
            return ManageResult(
                False,
                "reproducibility gate failed — skill retained in staging, not promoted",
                meta.name,
            )

        if stage_only:
            return ManageResult(
                True, "skill staged; two independent task replays required", meta.name
            )

        # 3. Publish only the exact reviewed text, never mutable staging files.
        self._publish_reviewed(meta.name, text)
        return ManageResult(True, f"skill created: {meta.name}", meta.name)

    def delete(self, name: str) -> ManageResult:
        try:
            target = self._path(self.live_dir, name)
        except ValueError as exc:
            return ManageResult(False, str(exc), name)
        with _repair_catalog_lock(self.live_dir):
            target = self._path(self.live_dir, name)
            if not target.exists():
                return ManageResult(False, f"no such skill: {name}", name)
            shutil.rmtree(target)
        return ManageResult(True, f"skill deleted: {name}", name)

    async def patch(
        self, name: str, new_body: str, *, force: bool = False, stage_only: bool = False
    ) -> ManageResult:
        try:
            target = self._path(self.live_dir, name) / "SKILL.md"
        except ValueError as exc:
            return ManageResult(False, str(exc), name)
        if not target.exists():
            return ManageResult(False, f"no such skill: {name}", name)
        skill = parse_skill_md(target.read_text("utf-8"), target.parent)
        return await self.create(skill.meta, new_body, force=force, stage_only=stage_only)

    async def promote_repair(self, name: str, tasks: dict[str, str]) -> ManageResult:
        """Operator-supplied task labels and independent runnable oracles, never agent input."""
        import ast

        staged = self._path(self.staging_dir, name) / "SKILL.md"
        self._path(self.live_dir, name)
        if staged.is_symlink() or not staged.is_file():
            return ManageResult(False, "no staged skill", name)
        text = staged.read_text("utf-8")
        skill = parse_skill_md(text, staged.parent)
        if skill.meta.name != name or not may_install(scan_skill(text), force=False):
            return ManageResult(False, "staged skill failed identity or security check", name)
        # Snapshot caller input before any awaited replay.
        tasks = dict(tasks)
        trees = [ast.parse(script) for script in tasks.values()]
        if (
            len(tasks) < 2
            or any(not label.strip() for label in tasks)
            or len({label.strip() for label in tasks}) < 2
            or len({ast.dump(tree) for tree in trees}) < 2
            or any(not any(isinstance(n, ast.Assert) for n in ast.walk(tree)) for tree in trees)
        ):
            return ManageResult(
                False, "two distinct tasks with executable assertions required", name
            )
        evidence = {
            label: hashlib.sha256(script.encode()).hexdigest() for label, script in tasks.items()
        }
        with _repair_catalog_lock(self.live_dir) as catalog:
            try:
                _refuse_revoked_oracles(catalog, evidence.values())
            except RepairSkillError as exc:
                return ManageResult(False, str(exc), name)
        files = python_files(skill.body)
        executor = PythonExecutor(backend="macos" if sys.platform == "darwin" else "docker")
        for label, script in tasks.items():
            result = await executor.run(files, script)
            if not result.passed:
                return ManageResult(False, f"independent replay failed: {label}", name)
        try:
            passed = await self.gate(deepcopy(skill.meta), skill.body)
        except Exception:
            passed = False
        if passed is not True:
            return ManageResult(False, "skill reproducibility gate failed", name)
        try:
            self._publish_reviewed(
                name,
                text,
                {
                    "skill_sha256": hashlib.sha256(text.encode()).hexdigest(),
                    "backend": executor.backend,
                    "tasks": evidence,
                },
            )
        except RepairSkillError as exc:
            return ManageResult(False, str(exc), name)
        return ManageResult(True, f"promoted after {len(tasks)} task replays", name)

    def revoke_oracle(self, oracle_sha256: str) -> list[str]:
        """Persistently deny an oracle, then archive dependent live versions.

        The deny record survives archival errors and also covers future promotions.
        """
        if not re.fullmatch("[a-f0-9]{64}", oracle_sha256):
            raise ValueError("expected a lowercase SHA-256 digest")
        removed = []
        with _repair_catalog_lock(self.live_dir) as catalog:
            _record_oracle_revocation(catalog, oracle_sha256)
            for directory in sorted(self.live_dir.iterdir()):
                if (
                    directory.is_symlink()
                    or not directory.is_dir()
                    or directory.name.startswith((".", "_"))
                ):
                    continue
                # Invalid/missing receipts are already refused by the loader;
                # they must not prevent archival of other dependent skills.
                try:
                    fd = os.open(
                        directory.name,
                        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                        dir_fd=catalog,
                    )
                    try:
                        record = json.loads(_read_file(fd, "replays.json", MAX_RECEIPT_BYTES))
                    finally:
                        os.close(fd)
                except (OSError, ValueError, RecursionError):
                    continue
                tasks = record.get("tasks") if isinstance(record, dict) else None
                if not isinstance(tasks, dict) or oracle_sha256 not in tasks.values():
                    continue
                # Keep the version and receipt outside the live catalog.
                revoked = self.live_dir / "_revoked"
                if revoked.is_symlink():
                    raise ValueError("invalid revocation archive")
                revoked.mkdir(exist_ok=True)
                from uuid import uuid4

                directory.rename(revoked / f"{directory.name}-{uuid4().hex}")
                removed.append(directory.name)
        return removed
