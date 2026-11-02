"""Self-modification harness (PLAN §9, ADR-004/005).

The agent may edit its own code and skills — nothing blocks it. Safety comes from
reversibility, not prohibition:

  1. snapshot()  — commit the working tree to a milyonus/auto branch, tagged,
                   before a change, so there is always a point to return to.
  2. (agent edits files with normal tools)
  3. test_gate() — run `pytest -q` (+ optional doctor). Red => auto rollback.
  4. rollback()  — restore a previous snapshot with one call.

This lives behind a git repo. If the workspace is not a git repo, snapshots are
disabled and the harness reports that clearly rather than silently doing nothing.
"""

from __future__ import annotations

import asyncio
import json
import re
import subprocess
import time
import uuid
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

_AUTO_BRANCH = "milyonus/auto"


@dataclass(slots=True)
class SnapshotResult:
    ok: bool
    ref: str
    message: str


@dataclass(slots=True)
class GateResult:
    passed: bool
    output: str


class SelfModHarness:
    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root.resolve()

    def _git(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", *args],
            cwd=str(self.repo_root),
            capture_output=True,
            text=True,
            check=False,
        )

    @property
    def pending_file(self) -> Path:
        return self.repo_root / ".milyonus-selfmod-pending.json"

    def pending(self) -> dict | None:
        if not self.pending_file.exists() and not self.pending_file.is_symlink():
            return None
        if self.pending_file.is_symlink():
            return {"snapshot": "", "error": "invalid self-modification marker"}
        try:
            value = json.loads(self.pending_file.read_text(encoding="utf-8"))
            if (
                isinstance(value, dict)
                and isinstance(value.get("snapshot"), str)
                and re.fullmatch(r"[0-9a-f]{40,64}", value["snapshot"])
            ):
                return value
        except (ValueError, OSError):
            pass
        return {"snapshot": "", "error": "invalid self-modification marker"}

    def accept_pending(self) -> None:
        self.pending_file.unlink(missing_ok=True)

    def is_git_repo(self) -> bool:
        return self._git("rev-parse", "--is-inside-work-tree").returncode == 0

    def snapshot(self, label: str) -> SnapshotResult:
        """Commit the current tree as a restore point. Returns the commit ref."""
        if not self.is_git_repo():
            return SnapshotResult(False, "", "not a git repo — snapshots disabled")
        added = self._git("add", "-A")
        if added.returncode:
            return SnapshotResult(False, "", "git add failed: " + added.stderr.strip())
        stamp = time.strftime("%Y%m%d-%H%M%S")
        tag = f"milyonus-auto-{stamp}-{uuid.uuid4().hex[:8]}"
        committed = self._git(
            "commit",
            "-m",
            f"[selfmod snapshot] {label}",
            "--allow-empty",
            "--no-verify",
        )
        if committed.returncode:
            return SnapshotResult(False, "", "snapshot commit failed: " + committed.stderr.strip())
        rev = self._git("rev-parse", "HEAD").stdout.strip()
        tagged = self._git("tag", tag)
        if tagged.returncode:
            return SnapshotResult(False, "", "snapshot tag failed: " + tagged.stderr.strip())
        return SnapshotResult(True, rev, f"snapshot {tag} @ {rev[:10]}")

    async def test_gate(self, *, run_doctor: bool = False) -> GateResult:
        """Run the test suite. Passing is the gate for keeping a self-edit."""
        proc = await asyncio.create_subprocess_exec(
            "uv",
            "run",
            "pytest",
            "-q",
            cwd=str(self.repo_root),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        out, _ = await proc.communicate()
        text = out.decode("utf-8", "replace")
        passed = proc.returncode == 0
        if passed and run_doctor:
            d = await asyncio.create_subprocess_exec(
                "uv",
                "run",
                "milyonus",
                "doctor",
                cwd=str(self.repo_root),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            dout, _ = await d.communicate()
            text += "\n" + dout.decode("utf-8", "replace")
            passed = d.returncode == 0
        return GateResult(passed, text[-4000:])

    def rollback(self, ref: str = "HEAD~1") -> str:
        """Hard-reset the working tree to a prior snapshot."""
        if not self.is_git_repo():
            return "not a git repo — cannot roll back"
        verified = self._git("rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}")
        sha = verified.stdout.strip()
        if verified.returncode or not re.fullmatch(r"[0-9a-f]{40,64}", sha):
            return "invalid rollback commit"
        res = self._git("reset", "--hard", sha)
        return res.stdout.strip() or res.stderr.strip() or f"rolled back: {ref}"

    def log(self, *, limit: int = 20) -> list[str]:
        """List recent self-modification snapshots."""
        res = self._git("log", "--oneline", f"-{limit}", "--grep=selfmod snapshot")
        return [ln for ln in res.stdout.splitlines() if ln.strip()]

    async def apply_change(
        self, label: str, mutate, *, run_doctor: bool = False, changed_paths: tuple[Path, ...] = ()
    ) -> tuple[bool, str]:
        """Snapshot, run `mutate` (an async callable that edits files), gate on
        tests, auto-rollback if red. Returns (kept, message)."""
        prior_pending = self.pending() if changed_paths else None
        if prior_pending and prior_pending.get("error"):
            return (False, "unsafe self-modification marker")
        snap = self.snapshot(label)
        if not snap.ok:
            return (False, snap.message)
        if changed_paths and self.pending_file.is_symlink():
            return (False, "unsafe self-modification marker")

        def stage_declared_paths():
            for path in changed_paths:
                relative = path.resolve().relative_to(self.repo_root)
                result = self._git("add", "--", str(relative))
                if result.returncode:
                    raise RuntimeError("could not stage self-modification for rollback")

        try:
            await mutate()
            stage_declared_paths()
        except Exception as exc:  # noqa: BLE001 - report and roll back
            # Index declared new files so reset removes them as well as
            # restoring tracked files. No blanket `git clean` of user data.
            with suppress(RuntimeError, ValueError):
                stage_declared_paths()
            self.rollback(snap.ref)
            return (False, f"change errored, rolled back: {exc}")
        try:
            gate = await self.test_gate(run_doctor=run_doctor)
        except asyncio.CancelledError:
            self.rollback(snap.ref)
            raise
        except Exception as exc:
            self.rollback(snap.ref)
            return (False, f"test gate errored — rolled back: {type(exc).__name__}")
        if not gate.passed:
            self.rollback(snap.ref)
            tail = gate.output.strip().splitlines()[-3:]
            return (False, "test gate red — rolled back:\n" + "\n".join(tail))
        if changed_paths:
            self.pending_file.write_text(
                json.dumps(
                    {
                        "snapshot": prior_pending["snapshot"] if prior_pending else snap.ref,
                        "label": label,
                        "paths": sorted(
                            set((prior_pending or {}).get("paths", []))
                            | {str(p.relative_to(self.repo_root)) for p in changed_paths}
                        ),
                    }
                ),
                encoding="utf-8",
            )
        return (True, f"change accepted ({label})")
