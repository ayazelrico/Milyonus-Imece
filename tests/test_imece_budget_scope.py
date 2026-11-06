"""Local trial exhaustion must not halt a known, bounded multi-task experiment."""

import json
from contextlib import suppress

import pytest
from evals.imece import run
from evals.imece.dataset import load_suite

from milyonus.imece.agents import AgentReply, AgentSpec
from milyonus.imece.benchmark import summarize, trial_identity
from milyonus.imece.journal import AgentJournal


@pytest.mark.parametrize(
    "limit,fail,status,expected",
    [
        (10, False, "budget", 2),
        (1, False, "budget", 1),
        (10, True, "budget", 1),
        (10, True, "rejected", 1),
    ],
)
async def test_budget_scope_at_settled_trial_boundary(
    tmp_path, monkeypatch, limit, fail, status, expected
):
    dispatched = []

    class Adapter:
        def __init__(self, **kwargs):
            pass

        async def __call__(self, spec):
            dispatched.append(spec.context)
            if fail:
                raise OSError("simulated uncertain dispatch")
            return AgentReply("READY", 1, None, False)

    async def benchmark(fn, settings, **kwargs):
        rows = list(kwargs.get("completed_rows") or [])
        completed = {(r["task"], r["repeat"]) for r in rows}
        for task in kwargs["tasks"]:
            if (task.id, 0) in completed:
                continue
            if kwargs["should_stop"]():
                break
            journal = AgentJournal(
                kwargs["journal_dir"] / f"{task.id}-0.sqlite",
                fn,
                identity=trial_identity(task, 0, settings, kwargs["run_identity"], kwargs["seed"]),
            )
            try:
                with suppress(OSError):
                    await journal(AgentSpec("production", "author", "solve", task.id, ["correct"]))
            finally:
                journal.close()
            row = {
                "task": task.id,
                "repeat": 0,
                "status": status,
                "oracle_passed": False,
                "tokens": 0 if fail else 1,
                "cost_usd": None,
            }
            rows.append(row)
            kwargs["on_row"](row)
        return {"runs": rows, "summary": summarize(rows)}

    monkeypatch.setattr(
        run, "discover_codex", lambda _: {"executable": "fake", "version": "test", "sha256": "test"}
    )
    monkeypatch.setattr(run, "oracle_guard", lambda _: [])
    monkeypatch.setattr(run, "CodexAgentFn", Adapter)
    monkeypatch.setattr(run, "run_benchmark", benchmark)
    config = tmp_path / "config.toml"
    config.write_text("[imece]\nmax_parallel=1\n")
    tasks = load_suite("core-v2")[:2]
    argv = [
        "--engine",
        "codex",
        "--model",
        "fake",
        "--suite",
        "core-v2",
        "--out",
        str(tmp_path / "run.json"),
        "--config",
        str(config),
        "--max-cli-calls",
        str(limit),
    ]
    for task in tasks:
        argv += ["--task", task.id]
    args = run.make_parser().parse_args(argv)
    assert await run.main(args) == 2
    report = json.loads(args.out.read_text())
    assert len(report["runs"]) == len(dispatched) == expected
    assert len(report["transcripts"]) == expected
    assert report["state"] == ("complete" if expected == 2 else "partial")
    assert report["transcripts"][-1]["state"] == ("unknown" if fail else "completed")
    if fail:
        assert report["runs"][-1]["tokens"] is None
        args.resume = True
        # Restarting alone must not silently dispatch beyond unknown usage.
        assert await run.main(args) == 2
        assert len(dispatched) == 1
        stopped = json.loads(args.out.read_text())
        assert stopped["runs"] == report["runs"]
        assert stopped["transcripts"] == report["transcripts"]
        # Explicit continuation permits the next task, never the uncertain one.
        args.continue_after_uncertain_trial = True
        assert await run.main(args) == 2
        continued = json.loads(args.out.read_text())
        assert dispatched == [t.id for t in tasks]
        assert len(continued["runs"]) == 2
        assert continued["transcripts"][0] == report["transcripts"][0]
