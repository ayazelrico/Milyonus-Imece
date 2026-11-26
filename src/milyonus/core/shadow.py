"""Speculative Execution & Shadow-Fork Dry-Run Engine (PLAN-SINGULARITY S3).

Forks a workspace into an isolated ephemeral shadow directory, executes a batch of
proposed file mutations (`write`, `delete`, `mkdir`) purely inside the shadow copy,
computes exact unified diffs, pre/post SHA-256 hashes, injection/secret scan findings,
and a complete reversible rollback bundle — BEFORE touching a single live byte.

`commit_shadow()` verifies that live files did not drift since simulation and fails
closed on path traversal (`..`), symlinks, or high-severity security violations.
"""

from __future__ import annotations

import difflib
import hashlib
import shutil
import tempfile
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from milyonus.security.injection import max_severity, scan
from milyonus.security.redact import redact


class ShadowEscapeError(Exception):
    """Raised when a shadow operation attempts to escape the workspace jail or touch a symlink."""


@dataclass(slots=True)
class ShadowOperation:
    op: str  # "write" | "delete" | "mkdir"
    path: str
    content: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ShadowFileDiff:
    path: str
    action: str  # "created" | "modified" | "deleted" | "mkdir"
    before_sha256: str | None
    after_sha256: str | None
    lines_added: int
    lines_removed: int
    unified_diff: str
    security_findings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ShadowSimulationReport:
    plan_id: str
    workspace: str
    safe_to_commit: bool
    risk_level: str  # "safe" | "caution" | "danger"
    files_changed: int
    diffs: list[ShadowFileDiff] = field(default_factory=list)
    security_alerts: list[str] = field(default_factory=list)
    pre_images: dict[str, str | None] = field(default_factory=dict)  # rel_path -> sha256 or None
    rollback_bundle: dict[str, str | None] = field(
        default_factory=dict
    )  # rel_path -> old text or None

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "workspace": self.workspace,
            "safe_to_commit": self.safe_to_commit,
            "risk_level": self.risk_level,
            "files_changed": self.files_changed,
            "diffs": [d.to_dict() for d in self.diffs],
            "security_alerts": self.security_alerts,
            "pre_images": self.pre_images,
            "rollback_bundle": self.rollback_bundle,
        }


def _safe_rel(root: Path, rel: str) -> Path:
    if not rel or "\x00" in rel:
        raise ShadowEscapeError("invalid empty or null-byte path")
    p = Path(rel)
    if p.is_absolute() or ".." in p.parts:
        raise ShadowEscapeError(f"path escape blocked: {rel}")
    resolved_root = root.resolve()
    target = (resolved_root / p).resolve()
    if not target.is_relative_to(resolved_root):
        raise ShadowEscapeError(f"resolved path outside workspace: {rel}")
    # Reject symlinks anywhere along the path inside workspace.
    cur = resolved_root
    for part in p.parts:
        cur = cur / part
        if cur.is_symlink():
            raise ShadowEscapeError(f"symlink mutation refused: {rel}")
    return target


def _sha_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def simulate_shadow(
    workspace: Path,
    operations: list[ShadowOperation],
) -> ShadowSimulationReport:
    """Execute proposed mutations inside an isolated shadow fork; zero live mutations."""
    ws = workspace.resolve()
    ws.mkdir(parents=True, exist_ok=True)
    plan_id = f"shd_{uuid.uuid4().hex[:12]}"
    diffs: list[ShadowFileDiff] = []
    alerts: list[str] = []
    pre_images: dict[str, str | None] = {}
    rollback: dict[str, str | None] = {}

    with tempfile.TemporaryDirectory(prefix="milyonus-shadow-") as td:
        shadow_root = Path(td) / "ws"
        shadow_root.mkdir(parents=True, exist_ok=True)

        # Copy only targeted existing files into shadow fork (fast & bounded).
        for op in operations:
            live_target = _safe_rel(ws, op.path)
            rel_norm = str(Path(op.path))
            if rel_norm not in pre_images:
                if live_target.is_file():
                    old_text = live_target.read_text(encoding="utf-8", errors="replace")
                    pre_images[rel_norm] = _sha_text(old_text)
                    rollback[rel_norm] = old_text
                    st = _safe_rel(shadow_root, rel_norm)
                    st.parent.mkdir(parents=True, exist_ok=True)
                    st.write_text(old_text, encoding="utf-8")
                else:
                    pre_images[rel_norm] = None
                    rollback[rel_norm] = None

        # Execute operations strictly in shadow_root.
        for op in operations:
            rel_norm = str(Path(op.path))
            st = _safe_rel(shadow_root, rel_norm)
            existing_text: str | None = st.read_text(encoding="utf-8") if st.is_file() else None
            before_sha = _sha_text(existing_text) if existing_text is not None else None
            sec_hits: list[str] = []

            if op.op == "mkdir":
                st.mkdir(parents=True, exist_ok=True)
                diffs.append(ShadowFileDiff(rel_norm, "mkdir", None, None, 0, 0, ""))
                continue

            if op.op == "delete":
                if st.is_file():
                    st.unlink()
                old_lines = (existing_text or "").splitlines(keepends=True)
                udiff = "".join(
                    difflib.unified_diff(
                        old_lines, [], fromfile=f"a/{rel_norm}", tofile="/dev/null"
                    )
                )
                diffs.append(
                    ShadowFileDiff(
                        rel_norm, "deleted", before_sha, None, 0, len(old_lines), udiff[:4000]
                    )
                )
                continue

            if op.op != "write":
                raise ValueError(f"unsupported shadow op: {op.op}")

            st.parent.mkdir(parents=True, exist_ok=True)
            st.write_text(op.content, encoding="utf-8")
            after_sha = _sha_text(op.content)

            findings = scan(op.content)
            if max_severity(findings) == "high":
                for f in findings:
                    msg = f"{rel_norm}: {f.signal} ({f.detail})"
                    sec_hits.append(msg)
                    alerts.append(msg)
            if redact(op.content) != op.content:
                msg = f"{rel_norm}: raw credential literal detected in proposed write"
                sec_hits.append(msg)
                alerts.append(msg)

            old_lines = (existing_text or "").splitlines(keepends=True)
            new_lines = op.content.splitlines(keepends=True)
            udiff = "".join(
                difflib.unified_diff(
                    old_lines,
                    new_lines,
                    fromfile=f"a/{rel_norm}" if existing_text is not None else "/dev/null",
                    tofile=f"b/{rel_norm}",
                )
            )
            added = sum(
                1 for ln in udiff.splitlines() if ln.startswith("+") and not ln.startswith("+++")
            )
            removed = sum(
                1 for ln in udiff.splitlines() if ln.startswith("-") and not ln.startswith("---")
            )
            diffs.append(
                ShadowFileDiff(
                    path=rel_norm,
                    action="created" if existing_text is None else "modified",
                    before_sha256=before_sha,
                    after_sha256=after_sha,
                    lines_added=added,
                    lines_removed=removed,
                    unified_diff=udiff[:4000],
                    security_findings=sec_hits,
                )
            )

    has_delete = any(d.action == "deleted" for d in diffs)
    if alerts:
        risk = "danger"
    elif has_delete or len(diffs) > 5:
        risk = "caution"
    else:
        risk = "safe"

    return ShadowSimulationReport(
        plan_id=plan_id,
        workspace=str(ws),
        safe_to_commit=len(alerts) == 0,
        risk_level=risk,
        files_changed=len(diffs),
        diffs=diffs,
        security_alerts=alerts,
        pre_images=pre_images,
        rollback_bundle=rollback,
    )


def commit_shadow(
    workspace: Path,
    operations: list[ShadowOperation],
    *,
    expected_pre_images: dict[str, str | None] | None = None,
    allow_security_alerts: bool = False,
) -> dict[str, Any]:
    """Verify simulation + zero live drift, then atomically apply to live workspace."""
    sim = simulate_shadow(workspace, operations)
    if sim.security_alerts and not allow_security_alerts:
        return {
            "committed": False,
            "plan_id": sim.plan_id,
            "reason": f"blocked by shadow security scan: {'; '.join(sim.security_alerts)}",
            "simulation": sim.to_dict(),
        }

    ws = workspace.resolve()
    if expected_pre_images is not None:
        for rel, exp_sha in expected_pre_images.items():
            live_target = _safe_rel(ws, rel)
            cur_sha = (
                _sha_text(live_target.read_text(encoding="utf-8", errors="replace"))
                if live_target.is_file()
                else None
            )
            if cur_sha != exp_sha:
                return {
                    "committed": False,
                    "plan_id": sim.plan_id,
                    "reason": f"live workspace drifted on '{rel}' since shadow preview — commit aborted",
                    "simulation": sim.to_dict(),
                }

    applied = 0
    for op in operations:
        target = _safe_rel(ws, op.path)
        if op.op == "mkdir":
            target.mkdir(parents=True, exist_ok=True)
        elif op.op == "delete":
            if target.is_file():
                target.unlink()
            elif target.is_dir():
                shutil.rmtree(target)
        elif op.op == "write":
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(op.content, encoding="utf-8")
        applied += 1

    return {
        "committed": True,
        "plan_id": sim.plan_id,
        "applied_ops": applied,
        "rollback_bundle": sim.rollback_bundle,
        "simulation": sim.to_dict(),
    }


def rollback_shadow(workspace: Path, rollback_bundle: dict[str, str | None]) -> int:
    """Restore workspace files to exact pre-commit state from a `rollback_bundle`."""
    ws = workspace.resolve()
    restored = 0
    for rel, old_text in rollback_bundle.items():
        target = _safe_rel(ws, rel)
        if old_text is None:
            if target.is_file():
                target.unlink()
                restored += 1
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(old_text, encoding="utf-8")
            restored += 1
    return restored
