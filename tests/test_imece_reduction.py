import hashlib
import json
import os

import pytest
from evals.imece.reduce_reproduction import reduce_files

from milyonus.imece.execution import ExecutionResult, PythonExecutor


def bundle():
    value = {
        "files": {"solution.py": "x=1", "unused.py": "x=2", "needed.py": "x=3"},
        "check": "assert False, 'wrong answer'",
        "backend": "docker",
        "image": "python@sha256:" + "1" * 64,
        "timeout": 10,
        "environment_id": "a" * 64,
    }
    value["digest"] = hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    return value


class Executor:
    backend = "docker"
    image = "python@sha256:" + "1" * 64
    timeout = 10

    def __init__(self):
        self.calls = 0
        self.environment = "a" * 64

    async def environment_fingerprint(self):
        return self.environment

    async def run(self, files, check):
        self.calls += 1
        output = "AssertionError: wrong answer" if "needed.py" in files else "ModuleNotFoundError"
        return ExecutionResult(
            False,
            output,
            1,
            "docker",
            failure_class="candidate_or_oracle_runtime",
            environment_id=self.environment,
        )


async def test_reduction_preserves_failure_and_original_bundle():
    original = bundle()
    result = await reduce_files(original, Executor())
    assert result["removed_files"] == ["unused.py"]
    assert set(result["bundle"]["files"]) == {"solution.py", "needed.py"}
    assert "unused.py" in original["files"]
    assert result["bundle"]["check"] == original["check"]
    assert result["minimality_proven"] is False
    assert result["environment_verified"] is True


async def test_reduction_honors_total_attempt_budget():
    executor = Executor()
    result = await reduce_files(bundle(), executor, max_attempts=2)
    assert executor.calls == result["attempts"] == 2
    assert result["budget_exhausted"] and not result["removed_files"]


async def test_tampered_bundle_never_executes():
    value, executor = bundle(), Executor()
    value["files"]["solution.py"] = "changed"
    with pytest.raises(ValueError, match="digest"):
        await reduce_files(value, executor)
    assert executor.calls == 0


async def test_environment_mismatch_never_executes():
    executor = Executor()
    executor.timeout = 20
    with pytest.raises(ValueError, match="executor differs"):
        await reduce_files(bundle(), executor)
    assert executor.calls == 0


async def test_runtime_mismatch_never_executes_even_with_legacy_opt_in():
    executor = Executor()
    executor.environment = "b" * 64
    with pytest.raises(ValueError, match="runtime differs"):
        await reduce_files(bundle(), executor, allow_unbound_environment=True)
    assert executor.calls == 0


async def test_environment_change_during_replay_aborts_reduction():
    executor = Executor()
    original = executor.run

    async def changed(files, check):
        result = await original(files, check)
        executor.environment = "b" * 64
        return result

    executor.run = changed
    with pytest.raises(ValueError, match="runtime changed"):
        await reduce_files(bundle(), executor)
    assert executor.calls == 2


async def test_legacy_reproduction_requires_explicit_unverified_opt_in():
    value = bundle()
    value.pop("environment_id")
    value.pop("digest")
    value["digest"] = hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    executor = Executor()
    with pytest.raises(ValueError, match="explicit opt-in"):
        await reduce_files(value, executor)
    assert executor.calls == 0
    result = await reduce_files(value, executor, allow_unbound_environment=True)
    assert result["environment_verified"] is False


async def test_malformed_bound_environment_cannot_be_downgraded_to_legacy():
    value = bundle()
    value["environment_id"] = None
    value.pop("digest")
    value["digest"] = hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    executor = Executor()
    with pytest.raises(ValueError, match="invalid reproduction environment"):
        await reduce_files(value, executor, allow_unbound_environment=True)
    assert executor.calls == 0


@pytest.mark.skipif(os.environ.get("MILYONUS_TEST_DOCKER") != "1", reason="Docker opt-in")
async def test_reduction_replays_inside_real_docker():
    from evals.imece.cache_probe import DEFAULT_IMAGE

    from milyonus.imece.agents import Swarm
    from milyonus.imece.gates import Frame, reality
    from milyonus.imece.gates import TestCase as Case
    from milyonus.imece.orchestrator import Candidate
    from milyonus.imece.reproduction import capture

    executor = PythonExecutor(image=DEFAULT_IMAGE)
    files = {
        "solution.py": "from needed import value\nassert value == 4, 'wrong answer'\n",
        "needed.py": "value = 3\n",
        "unused.py": "value = 42\n",
    }
    candidate = Candidate(
        "C1",
        "baseline",
        0,
        "\n".join(f"```python file={name}\n{code}```\n" for name, code in files.items()),
    )

    async def no_model_calls(spec):
        raise AssertionError("this integration test must not call a model")

    checks = [Case("T1", "expected value", python="import solution\n")]
    reports = await reality(
        Swarm(no_model_calls),
        Frame("r", "p", ("expected value",)),
        [candidate],
        checks,
        test_exec=0,
        red_team=0,
        evidence_audit=0,
        compliance=0,
        pass_threshold=1,
        executor=executor,
    )
    examples = []
    capture(examples, [candidate], checks, reports, executor)
    assert len(examples) == 1
    value = examples[0]
    assert value["environment_id"] == reports["C1"].test_results[0]["environment_id"]
    assert value["environment_id"] == await executor.environment_fingerprint()
    result = await reduce_files(value, executor)
    assert result["removed_files"] == ["unused.py"]
    assert result["diagnostic"] == "AssertionError: wrong answer"
    assert result["environment_verified"] is True
