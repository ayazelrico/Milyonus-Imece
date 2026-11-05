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

    async def run(self, files, check):
        self.calls += 1
        output = "AssertionError: wrong answer" if "needed.py" in files else "ModuleNotFoundError"
        return ExecutionResult(
            False, output, 1, "docker", failure_class="candidate_or_oracle_runtime"
        )


async def test_reduction_preserves_failure_and_original_bundle():
    original = bundle()
    result = await reduce_files(original, Executor())
    assert result["removed_files"] == ["unused.py"]
    assert set(result["bundle"]["files"]) == {"solution.py", "needed.py"}
    assert "unused.py" in original["files"]
    assert result["bundle"]["check"] == original["check"]
    assert result["minimality_proven"] is False


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


@pytest.mark.skipif(os.environ.get("MILYONUS_TEST_DOCKER") != "1", reason="Docker opt-in")
async def test_reduction_replays_inside_real_docker():
    value = {
        "files": {
            "solution.py": "from needed import value\nassert value == 4, 'wrong answer'\n",
            "needed.py": "value = 3\n",
            "unused.py": "value = 42\n",
        },
        "check": "import solution\n",
        "backend": "docker",
        "image": "python:3.12-slim",
        "timeout": 10,
    }
    value["digest"] = hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    result = await reduce_files(value, PythonExecutor())
    assert result["removed_files"] == ["unused.py"]
    assert result["diagnostic"] == "AssertionError: wrong answer"
