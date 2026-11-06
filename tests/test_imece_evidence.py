"""Exercise cache admission and invalidation through the executor boundary."""

import hashlib
import json
import sqlite3
from copy import deepcopy
from dataclasses import replace

import pytest

from milyonus.imece.execution import ExecutionResult, PythonExecutor


@pytest.fixture(autouse=True)
def runtime_identity(monkeypatch):
    identity = {
        "image": {"id": "test-image", "os": "linux", "architecture": "arm64"},
        "daemon": {
            "id": "test-daemon",
            "architecture": "a",
            "os": "linux",
            "kernel": "1",
            "version": "1",
            "security": ["seccomp"],
        },
    }

    async def inspect(self):
        return deepcopy(identity)

    monkeypatch.setattr(PythonExecutor, "_docker_identity", inspect)
    return identity


@pytest.mark.parametrize(
    "change",
    [
        "files",
        "oracle",
        "image",
        "timeout",
        "daemon",
        "resolved_image",
        "architecture",
        "policy",
        "image_os",
        "image_architecture",
        "daemon_os",
        "kernel",
        "version",
        "security",
        "executor",
        "host_architecture",
    ],
)
async def test_changed_contract_or_runtime_executes_again(
    tmp_path, monkeypatch, runtime_identity, change
):
    calls = []

    async def execute(self, files, oracle):
        calls.append((files.copy(), oracle, self.image, self.timeout))
        return ExecutionResult(True, "ok", 0, "docker")

    monkeypatch.setattr(PythonExecutor, "_execute", execute)
    executor = PythonExecutor(
        image="python@sha256:" + "1" * 64, cache_path=tmp_path / "evidence.sqlite"
    )
    files, oracle = {"solution.py": "x = 1\n"}, "assert True"
    first = await executor.run(files, oracle, deterministic=True)
    cached = await executor.run(files, oracle, deterministic=True)
    assert cached.reused and cached.evidence_id == first.evidence_id
    if change == "files":
        files = {"solution.py": "x = 2\n"}
    elif change == "oracle":
        oracle = "assert 1 == 1"
    elif change == "image":
        executor.image = "python@sha256:" + "2" * 64
    elif change == "timeout":
        executor.timeout += 1
    elif change == "daemon":
        runtime_identity["daemon"]["id"] = "different-daemon"
    elif change == "resolved_image":
        runtime_identity["image"]["id"] = "different-selected-image"
    elif change == "architecture":
        runtime_identity["daemon"]["architecture"] = "b"
    elif change in ("image_os", "image_architecture"):
        runtime_identity["image"][change.removeprefix("image_")] = "changed"
    elif change in ("daemon_os", "kernel", "version"):
        runtime_identity["daemon"][change.removeprefix("daemon_")] = "changed"
    elif change == "security":
        runtime_identity["daemon"]["security"].append("changed")
    elif change == "executor":
        executor._policy_hash = "changed-executor-source"
    elif change == "host_architecture":
        monkeypatch.setattr("milyonus.imece.execution.platform.machine", lambda: "changed-host")
    else:
        original = executor._argv
        monkeypatch.setattr(
            executor,
            "_argv",
            lambda *args: [
                "--pids-limit=16" if value == "--pids-limit=32" else value
                for value in original(*args)
            ],
        )
    changed = await executor.run(files, oracle, deterministic=True)
    assert not changed.reused and changed.evidence_id != first.evidence_id
    assert len(calls) == 2


async def test_missing_runtime_metadata_cannot_reuse_a_warm_verdict(tmp_path, monkeypatch):
    calls = 0

    async def execute(self, files, oracle):
        nonlocal calls
        calls += 1
        return ExecutionResult(True, "ok", 0, "docker")

    monkeypatch.setattr(PythonExecutor, "_execute", execute)
    executor = PythonExecutor(
        image="python@sha256:" + "1" * 64, cache_path=tmp_path / "cache.sqlite"
    )
    first = await executor.run({"solution.py": "x=1"}, "assert True", deterministic=True)
    assert first.evidence_id

    async def unavailable(self):
        return None

    monkeypatch.setattr(PythonExecutor, "_docker_identity", unavailable)
    result = await executor.run({"solution.py": "x=1"}, "assert True", deterministic=True)
    assert result.passed and not result.reused and result.evidence_id is None
    assert calls == 2


async def test_generated_check_cannot_reuse_trusted_cache_without_permission(tmp_path, monkeypatch):
    calls = 0

    async def execute(self, files, oracle):
        nonlocal calls
        calls += 1
        return ExecutionResult(True, "ok", 0, "docker")

    monkeypatch.setattr(PythonExecutor, "_execute", execute)
    executor = PythonExecutor(
        image="python@sha256:" + "1" * 64, cache_path=tmp_path / "evidence.sqlite"
    )
    files, oracle = {"solution.py": "x = 1\n"}, "assert True"
    trusted = await executor.run(files, oracle, deterministic=True)
    generated = await executor.run(files, oracle)
    assert not generated.reused and calls == 2
    executor.approved_evidence = frozenset({trusted.evidence_id})
    assert (await executor.run(files, oracle)).reused
    assert calls == 2


async def test_failed_execution_is_never_reused(tmp_path, monkeypatch):
    calls = 0

    async def execute(self, files, oracle):
        nonlocal calls
        calls += 1
        return replace(
            ExecutionResult(False, "AssertionError", 1, "docker"),
            failure_class="candidate_or_oracle_runtime",
        )

    monkeypatch.setattr(PythonExecutor, "_execute", execute)
    executor = PythonExecutor(
        image="python@sha256:" + "1" * 64, cache_path=tmp_path / "evidence.sqlite"
    )
    for _ in range(2):
        assert not (
            await executor.run({"solution.py": "x=1"}, "assert False", deterministic=True)
        ).reused
    assert calls == 2


async def test_cached_environment_must_match_the_current_runtime(tmp_path, monkeypatch):
    calls = 0

    async def execute(self, files, oracle):
        nonlocal calls
        calls += 1
        return ExecutionResult(True, "ok", 0, "docker")

    monkeypatch.setattr(PythonExecutor, "_execute", execute)
    executor = PythonExecutor(
        image="python@sha256:" + "1" * 64, cache_path=tmp_path / "cache.sqlite"
    )
    files, check = {"solution.py": "x=1"}, "assert True"
    first = await executor.run(files, check, deterministic=True)
    with sqlite3.connect(executor.cache_path) as db:
        payload = json.loads(db.execute("SELECT result FROM evidence").fetchone()[0])
        payload["environment_id"] = "b" * 64
        value = json.dumps(payload, sort_keys=True)
        db.execute(
            "UPDATE evidence SET result=?,checksum=?",
            (value, hashlib.sha256(value.encode()).hexdigest()),
        )
    result = await executor.run(files, check, deterministic=True)
    assert not result.reused and result.environment_id == first.environment_id
    assert result.evidence_id == first.evidence_id and calls == 2
