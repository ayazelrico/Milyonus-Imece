"""Publish exactly reviewed content and preserve old versions on failure."""

import asyncio
import hashlib
from pathlib import Path

import pytest

from milyonus.imece.execution import ExecutionResult
from milyonus.skills import manage
from milyonus.skills.manage import SkillManager
from milyonus.skills.model import SkillMeta, parse_skill_md, render_skill_md

BODY = "```python file=solution.py\ndef identity(x): return x\n```"
TASKS = {
    "positive": "from solution import identity; assert identity(1)==1",
    "negative": "from solution import identity; assert identity(-2)==-2",
}


@pytest.fixture
def replay_executor(monkeypatch):
    # Unit tests isolate publication/gate state; this is not sandbox evidence.
    class Executor:
        def __init__(self, **kwargs):
            self.backend = "docker"

        async def run(self, files, script):
            return ExecutionResult(True, "ok", 0, "docker")

    monkeypatch.setattr(manage, "PythonExecutor", Executor)


def stage(manager):
    directory = manager.staging_dir / "sample"
    directory.mkdir(parents=True, exist_ok=True)
    text = render_skill_md(SkillMeta(name="sample", description="d"), BODY)
    (directory / "SKILL.md").write_text(text)
    return text


async def test_create_publishes_reviewed_snapshot_when_staging_changes(tmp_path):
    started, proceed = asyncio.Event(), asyncio.Event()

    async def gate(meta, body):
        started.set()
        await proceed.wait()
        return True

    manager = SkillManager(live_dir=tmp_path / "live", gate=gate)
    task = asyncio.create_task(
        manager.create(SkillMeta(name="sample", description="d"), "reviewed")
    )
    await started.wait()
    staged = manager.staging_dir / "sample" / "SKILL.md"
    staged.write_text(staged.read_text().replace("reviewed", "unreviewed"))
    (staged.parent / "unexpected.txt").write_text("not covered by the gate")
    proceed.set()
    assert (await task).ok
    live = manager.live_dir / "sample"
    assert parse_skill_md((live / "SKILL.md").read_text(), live).body == "reviewed"
    assert not (live / "unexpected.txt").exists()


async def test_gate_cannot_mutate_publication_identity(tmp_path):
    async def gate(meta, body):
        meta.name = "redirected"
        return True

    original = SkillMeta(name="sample", description="d")
    manager = SkillManager(live_dir=tmp_path / "live", gate=gate)
    result = await manager.create(original, "reviewed")
    assert result.ok and result.name == original.name == "sample"
    assert (manager.live_dir / "sample" / "SKILL.md").exists()
    assert not (manager.live_dir / "redirected").exists()


async def test_publication_never_overwrites_an_existing_regular_file(tmp_path):
    async def gate(meta, body):
        return True

    manager = SkillManager(live_dir=tmp_path / "live", gate=gate)
    target = manager.live_dir / "sample"
    target.write_text("unrelated file")
    with pytest.raises(NotADirectoryError):
        await manager.create(SkillMeta(name="sample", description="d"), BODY)
    assert target.read_text() == "unrelated file"
    assert not list(manager.live_dir.glob(".publish-*"))


@pytest.mark.parametrize("repair", [False, True])
@pytest.mark.parametrize("rollback_fails", [False, True])
async def test_failed_publication_restores_or_retains_previous_version(
    tmp_path, monkeypatch, replay_executor, repair, rollback_fails
):
    async def gate(meta, body):
        return True

    manager = SkillManager(live_dir=tmp_path / "live", gate=gate)
    target = manager.live_dir / "sample"
    target.mkdir()
    (target / "SKILL.md").write_text("previous bytes")
    (target / "reference.txt").write_text("previous reference")
    stage(manager)
    rename = Path.rename

    def fail(self, destination):
        if self.name == "new" or (self.name == "previous" and rollback_fails):
            raise OSError("injected rename failure")
        return rename(self, destination)

    monkeypatch.setattr(Path, "rename", fail)
    with pytest.raises(OSError, match="retained at" if rollback_fails else "injected"):
        if repair:
            await manager.promote_repair("sample", TASKS)
        else:
            await manager.create(SkillMeta(name="sample", description="d"), BODY)
    transactions = list(manager.live_dir.glob(".publish-*"))
    if rollback_fails:
        assert not target.exists() and len(transactions) == 1
        previous = transactions[0] / "previous"
    else:
        assert not transactions
        previous = target
    assert (previous / "SKILL.md").read_text() == "previous bytes"
    assert (previous / "reference.txt").read_text() == "previous reference"


@pytest.mark.parametrize(
    "answer", ["false", 1, {"passed": True}, None, RuntimeError("gate unavailable")]
)
async def test_repair_promotion_requires_literal_true(tmp_path, replay_executor, answer):
    async def gate(meta, body):
        if isinstance(answer, Exception):
            raise answer
        return answer

    manager = SkillManager(live_dir=tmp_path / "live", gate=gate)
    text = stage(manager)
    result = await manager.promote_repair("sample", TASKS)
    assert not result.ok and "gate failed" in result.message
    assert not (manager.live_dir / "sample").exists()
    assert (manager.staging_dir / "sample" / "SKILL.md").read_text() == text


async def test_oracle_revocation_during_gate_still_prevents_publication(tmp_path, replay_executor):
    started, proceed = asyncio.Event(), asyncio.Event()

    async def gate(meta, body):
        started.set()
        await proceed.wait()
        return True

    manager = SkillManager(live_dir=tmp_path / "live", gate=gate)
    stage(manager)
    task = asyncio.create_task(manager.promote_repair("sample", TASKS))
    await started.wait()
    manager.revoke_oracle(hashlib.sha256(TASKS["positive"].encode()).hexdigest())
    proceed.set()
    result = await task
    assert not result.ok and "revoked" in result.message
    assert not (manager.live_dir / "sample").exists()
    assert not list(manager.live_dir.glob(".publish-*"))


async def test_successful_repair_publishes_receipt_for_the_reviewed_snapshot(
    tmp_path, replay_executor
):
    from milyonus.skills.repair import load_repair_skill

    async def gate(meta, body):
        staged = manager.staging_dir / "sample" / "SKILL.md"
        staged.write_text(staged.read_text().replace("return x", "return 0"))
        return True

    manager = SkillManager(live_dir=tmp_path / "live", gate=gate)
    text = stage(manager)
    result = await manager.promote_repair("sample", TASKS)
    assert result.ok
    skill = load_repair_skill("sample", live_dir=manager.live_dir)
    assert skill.sha256 == hashlib.sha256(text.encode()).hexdigest()
    assert "return x" in skill.body
