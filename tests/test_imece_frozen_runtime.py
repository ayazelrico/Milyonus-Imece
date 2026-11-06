"""A changed Docker runtime cannot resume a checkpoint or execute a frozen check."""

import json

import pytest
from evals.imece import run

from milyonus.imece.execution import PythonExecutor, VerificationEnvironmentChanged

IMAGE = "python@sha256:" + "1" * 64


async def test_checkpoint_binds_docker_runtime_before_adapter_construction(tmp_path, monkeypatch):
    observed = "a" * 64

    async def fingerprint(self):
        return observed

    def forbidden(**kwargs):
        pytest.fail("runtime mismatch must be rejected before adapter construction")

    monkeypatch.setattr(PythonExecutor, "environment_fingerprint", fingerprint)
    monkeypatch.setattr(run, "CodexAgentFn", forbidden)
    monkeypatch.setattr(run, "oracle_guard", lambda _: [])
    monkeypatch.setattr(
        run, "discover_codex", lambda _: {"executable": "fake", "version": "test", "sha256": "test"}
    )
    out = tmp_path / "report.json"
    argv = ["--engine", "codex", "--model", "fake", "--image", IMAGE, "--out", str(out)]
    assert await run.main(run.make_parser().parse_args([*argv, "--prepare"])) == 0
    saved = out.read_bytes()
    assert (
        json.loads(saved)["manifest"]["protocol"]["runtime"]["verification_environment_id"]
        == observed
    )
    observed = "b" * 64
    with pytest.raises(ValueError, match="resume manifest differs"):
        await run.main(run.make_parser().parse_args([*argv, "--resume"]))
    assert out.read_bytes() == saved
    observed = None
    with pytest.raises(ValueError, match="cannot freeze Docker verification environment"):
        await run.main(run.make_parser().parse_args([*argv, "--resume"]))
    assert out.read_bytes() == saved


@pytest.mark.parametrize("observed", [{"daemon": "different"}, None])
async def test_runtime_drift_fails_before_execution_or_cache_lookup(
    monkeypatch, tmp_path, observed
):
    executor = PythonExecutor(
        image=IMAGE,
        cache_path=tmp_path / "cache.sqlite",
        expected_environment_id=PythonExecutor._environment_digest({"daemon": "original"}),
    )

    async def environment(self):
        return observed

    async def forbidden(*args):
        pytest.fail("a changed runtime must not execute")

    monkeypatch.setattr(PythonExecutor, "verification_environment", environment)
    monkeypatch.setattr(PythonExecutor, "_execute", forbidden)
    with pytest.raises(VerificationEnvironmentChanged, match="differs from the frozen run"):
        await executor.run({"solution.py": "x=1"}, "assert True", deterministic=True)
    assert not executor.cache_path.exists()
