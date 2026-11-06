"""Calls queued behind a failing or budget-exhausting call must never launch."""

import asyncio
import json

import pytest
from evals.imece import run
from evals.imece.dataset import load_suite

from milyonus.imece.agents import AdmissionDenied, AgentReply, AgentSpec
from milyonus.imece.benchmark import summarize, trial_identity
from milyonus.imece.journal import AgentJournal


@pytest.mark.parametrize("uncertain", [True, False])
async def test_admission_is_rechecked_after_waiting_for_dispatch_slot(
    tmp_path, monkeypatch, uncertain
):
    dispatched = []

    class Adapter:
        def __init__(self, **kwargs):
            pass

        async def __call__(self, spec):
            dispatched.append(spec.context)
            # Let the other journal node enter the dispatch queue.
            await asyncio.sleep(0)
            if uncertain:
                raise OSError("uncertain first call")
            return AgentReply("READY", 1, None, False)

    async def benchmark(fn, settings, **kwargs):
        task = kwargs["tasks"][0]
        journal = AgentJournal(
            kwargs["journal_dir"] / f"{task.id}-0.sqlite",
            fn,
            identity=trial_identity(task, 0, settings, kwargs["run_identity"], kwargs["seed"]),
        )
        try:
            results = await asyncio.gather(
                *(
                    journal(AgentSpec("production", "author", "solve", name, ["correct"]))
                    for name in ("first", "queued")
                ),
                return_exceptions=True,
            )
            assert isinstance(results[1], AdmissionDenied)
            assert journal.db.execute("SELECT count(*) FROM nodes").fetchone()[0] == 1
        finally:
            journal.close()
        row = {
            "task": task.id,
            "repeat": 0,
            "status": "budget",
            "oracle_passed": False,
            "tokens": 0 if uncertain else 1,
            "cost_usd": None,
        }
        kwargs["on_row"](row)
        return {"runs": [row], "summary": summarize([row])}

    monkeypatch.setattr(
        run, "discover_codex", lambda _: {"executable": "fake", "version": "test", "sha256": "test"}
    )
    monkeypatch.setattr(run, "oracle_guard", lambda _: [])
    monkeypatch.setattr(run, "CodexAgentFn", Adapter)
    monkeypatch.setattr(run, "run_benchmark", benchmark)
    config = tmp_path / "config.toml"
    config.write_text("[imece]\nmax_parallel=1\n")
    args = run.make_parser().parse_args(
        [
            "--engine",
            "codex",
            "--model",
            "fake",
            "--suite",
            "core-v2",
            "--task",
            load_suite("core-v2")[0].id,
            "--config",
            str(config),
            "--max-tokens",
            "1",
            "--out",
            str(tmp_path / "run.json"),
        ]
    )
    assert await run.main(args) == 2
    report = json.loads(args.out.read_text())
    assert dispatched == ["first"]
    assert len(report["transcripts"]) == 1
    assert report["accounting"]["unknown_usage_calls"] == int(uncertain)
    assert report["runs"][0]["tokens"] == (None if uncertain else 1)
