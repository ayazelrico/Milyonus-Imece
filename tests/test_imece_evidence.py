"""Exercise cache admission and invalidation through the executor boundary."""

from dataclasses import replace

import pytest

from milyonus.imece.execution import ExecutionResult, PythonExecutor


@pytest.mark.parametrize("change", ["files", "oracle", "image", "timeout"])
async def test_changed_contract_or_runtime_executes_again(tmp_path, monkeypatch, change):
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
    else:
        executor.timeout += 1
    changed = await executor.run(files, oracle, deterministic=True)
    assert not changed.reused and changed.evidence_id != first.evidence_id
    assert len(calls) == 2


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
