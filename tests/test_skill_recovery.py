"""Abrupt process exits leave journals recoverable without publishing candidates."""

import json
import shutil
import subprocess
import sys

import pytest
from typer.testing import CliRunner

from milyonus.cli.skills_cmd import skills_app
from milyonus.skills.manage import SkillManager
from milyonus.skills.model import SkillMeta, parse_skill_md
from milyonus.skills.publication import recover_publications

_CRASH = r"""
import asyncio, hashlib, json, os, sys
from pathlib import Path
from milyonus.skills.manage import SkillManager
from milyonus.skills.model import SkillMeta
root = Path(sys.argv[1])
async def gate(meta, body): return True
manager = SkillManager(live_dir=root, gate=gate)
meta = SkillMeta(name="sample", description="d")
if sys.argv[2] != "initial":
    asyncio.run(manager.create(meta, "old reviewed body"))
    (root / "sample" / "reference.txt").write_text("preserved reference")
    if sys.argv[2] == "receipt":
        text = (root / "sample" / "SKILL.md").read_bytes()
        (root / "sample" / "replays.json").write_text(json.dumps({
            "skill_sha256": hashlib.sha256(text).hexdigest(), "backend": "docker",
            "tasks": {"a": "1"*64, "b": "2"*64}}))
original = Path.rename
def crash(self, target):
    if self.name == "new":
        if sys.argv[2] == "after": original(self, target)
        os._exit(73)
    return original(self, target)
Path.rename = crash
asyncio.run(manager.create(meta, "new reviewed body"))
"""


def crash_publication(tmp_path, phase="before"):
    root = tmp_path / "skills"
    result = subprocess.run(
        [sys.executable, "-c", _CRASH, str(root), phase], capture_output=True, text=True, timeout=10
    )
    assert result.returncode == 73, result.stderr
    return root


def live_body(root):
    path = root / "sample"
    return parse_skill_md((path / "SKILL.md").read_text(), path).body


def test_abrupt_exit_preview_restore_and_idempotence(tmp_path):
    root = crash_publication(tmp_path)
    rows = recover_publications(root)
    assert len(rows) == 1 and rows[0]["status"] == "recoverable"
    assert not rows[0]["restored"] and not (root / "sample").exists()
    restored = recover_publications(root, apply=True)
    assert restored[0]["status"] == "restored" and restored[0]["restored"]
    assert live_body(root) == "old reviewed body"
    assert (root / "sample" / "reference.txt").read_text() == "preserved reference"
    assert (root / rows[0]["transaction"] / "new" / "SKILL.md").exists()
    again = recover_publications(root, apply=True)
    assert again[0]["status"] == "live_present" and not again[0]["restored"]


@pytest.mark.parametrize("tree", ["new", "previous"])
def test_changed_tree_is_never_restored(tmp_path, tree):
    root = crash_publication(tmp_path)
    transaction = next(root.glob(".publish-*"))
    (transaction / tree / "SKILL.md").write_text("changed after the crash")
    rows = recover_publications(root, apply=True)
    assert rows[0]["status"] == "unrecognized" and "hash mismatch" in rows[0]["error"]
    assert not (root / "sample").exists()


def test_recovery_never_overwrites_new_live_version(tmp_path):
    root = crash_publication(tmp_path)

    async def gate(meta, body):
        return True

    import asyncio

    manager = SkillManager(live_dir=root, gate=gate)
    assert asyncio.run(
        manager.create(SkillMeta(name="sample", description="d"), "later version")
    ).ok
    rows = recover_publications(root, apply=True)
    assert rows[0]["status"] == "live_present"
    assert live_body(root) == "later version"


def test_multiple_backups_for_missing_skill_are_ambiguous(tmp_path):
    root = crash_publication(tmp_path)
    transaction = next(root.glob(".publish-*"))
    shutil.copytree(transaction, root / ".publish-duplicate")
    rows = recover_publications(root, apply=True)
    assert len(rows) == 2 and all(row["status"] == "ambiguous" for row in rows)
    assert not (root / "sample").exists()


def test_revoked_receipt_cannot_be_resurrected(tmp_path):
    root = crash_publication(tmp_path, "receipt")
    SkillManager(live_dir=root).revoke_oracle("1" * 64)
    rows = recover_publications(root, apply=True)
    assert rows[0]["status"] == "unrecognized" and "revoked" in rows[0]["error"]
    assert not (root / "sample").exists()


@pytest.mark.parametrize(
    "phase,status,body",
    [("initial", "no_previous", None), ("after", "live_present", "new reviewed body")],
)
def test_candidate_is_never_published_or_rolled_back_implicitly(tmp_path, phase, status, body):
    root = crash_publication(tmp_path, phase)
    rows = recover_publications(root, apply=True)
    assert rows[0]["status"] == status and not rows[0]["restored"]
    assert (live_body(root) if body else None) == body
    if body is None:
        assert not (root / "sample").exists()


def test_legacy_and_symlink_transactions_are_preserved(tmp_path):
    root = tmp_path / "skills"
    (root / ".publish-legacy" / "previous").mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "publication.json").write_text("untrusted")
    (root / ".publish-link").symlink_to(outside, target_is_directory=True)
    rows = recover_publications(root, apply=True)
    assert all(row["status"] == "unrecognized" and not row["restored"] for row in rows)
    assert (outside / "publication.json").read_text() == "untrusted"
    assert (root / ".publish-legacy" / "previous").exists()


def test_recovery_cli_requires_apply_for_changes(tmp_path, monkeypatch):
    root = crash_publication(tmp_path)
    monkeypatch.setenv("MILYONUS_HOME", str(tmp_path))
    runner = CliRunner()
    preview = runner.invoke(skills_app, ["recover-publications"])
    assert preview.exit_code == 0, preview.output
    assert json.loads(preview.stdout)[0]["status"] == "recoverable"
    assert not (root / "sample").exists()
    applied = runner.invoke(skills_app, ["recover-publications", "--apply"])
    assert applied.exit_code == 0, applied.output
    assert json.loads(applied.stdout)[0]["status"] == "restored"
    assert live_body(root) == "old reviewed body"


@pytest.mark.parametrize("failure", ["rename", "fsync"])
def test_partial_recovery_reports_actual_state_and_keeps_journal(tmp_path, monkeypatch, failure):
    from milyonus.skills import publication

    root = crash_publication(tmp_path)

    def fail(*args, **kwargs):
        raise OSError("injected recovery failure")

    with monkeypatch.context() as changed:
        changed.setattr(publication.os, failure, fail)
        rows = recover_publications(root, apply=True)
    assert rows[0]["status"] == "recovery_failed"
    assert rows[0]["restored"] is (failure == "fsync")
    transaction = root / rows[0]["transaction"]
    assert (transaction / "publication.json").exists()
    assert (transaction / "new").exists()
    if failure == "fsync":
        assert live_body(root) == "old reviewed body"
    else:
        assert not (root / "sample").exists()
        assert (transaction / "previous").exists()
        assert recover_publications(root, apply=True)[0]["restored"] is True
