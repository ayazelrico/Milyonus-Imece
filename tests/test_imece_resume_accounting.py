"""Actual dispatch usage survives a restart even if the logical branch changes."""

import json

import pytest
from evals.imece import run
from evals.imece.dataset import load_suite

from milyonus.imece.agents import AdmissionDenied, AgentReply, AgentSpec
from milyonus.imece.benchmark import summarize, trial_identity
from milyonus.imece.journal import AgentJournal


@pytest.mark.parametrize(
    "budget,same_branch,legacy,expected_tokens,expected_calls",
    [
        (100, False, False, 12, 2),
        (7, False, False, 7, 1),
        (100, True, False, 7, 1),
        (7, True, False, 7, 1),
        (100, False, "reply", None, 1),
        (100, False, "error", None, 1),
    ],
)
async def test_resumed_trial_counts_abandoned_known_branch(
    tmp_path, monkeypatch, budget, same_branch, legacy, expected_tokens, expected_calls
):
    calls = []
    attempts = 0

    class Adapter:
        def __init__(self, **kwargs):
            pass

        async def __call__(self, spec):
            calls.append(spec.context)
            return AgentReply("READY", 7 if len(calls) == 1 else 5, None, False)

    async def benchmark(fn, settings, **kwargs):
        nonlocal attempts
        attempts += 1
        task = kwargs["tasks"][0]
        journal = AgentJournal(
            kwargs["journal_dir"] / f"{task.id}-0.sqlite",
            fn,
            identity=trial_identity(task, 0, settings, kwargs["run_identity"], kwargs["seed"]),
        )
        logical_tokens = 0
        status = "rejected"
        try:
            try:
                reply = await journal(
                    AgentSpec(
                        "production",
                        "author",
                        "solve",
                        f"branch-{1 if same_branch else attempts}",
                        ["correct"],
                    )
                )
                logical_tokens = reply.tokens
            except AdmissionDenied:
                status = "budget"
            if attempts == 1:
                raise RuntimeError("crash after durable reply before row snapshot")
        finally:
            journal.close()
        row = {
            "task": task.id,
            "repeat": 0,
            "status": status,
            "oracle_passed": False,
            "tokens": logical_tokens,
            "cost_usd": None,
            "seconds": 2.0,
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
    task = load_suite("core-v2")[0]
    args = run.make_parser().parse_args(
        [
            "--engine",
            "codex",
            "--model",
            "fake",
            "--suite",
            "core-v2",
            "--task",
            task.id,
            "--out",
            str(tmp_path / "run.json"),
            "--config",
            str(config),
            "--max-tokens",
            str(budget),
        ]
    )
    with pytest.raises(RuntimeError, match="crash after durable reply"):
        await run.main(args)
    if legacy:
        checkpoint = json.loads(args.out.read_text())
        checkpoint["transcripts"] = [
            {
                "spec": entry["spec"],
                **(
                    {"reply": entry["reply"]}
                    if legacy == "reply"
                    else {"error": "historical unknown dispatch"}
                ),
            }
            for entry in checkpoint["transcripts"]
        ]
        args.out.write_text(json.dumps(checkpoint))
    args.resume = True
    assert await run.main(args) == 2
    report = json.loads(args.out.read_text())
    assert len(calls) == len(report["transcripts"]) == expected_calls
    assert report["runs"][0]["tokens"] == expected_tokens
    assert report["summary"]["total_tokens"] == expected_tokens
    assert report["accounting"]["observed_tokens"] == (
        (7 if legacy == "reply" else 0) if legacy else expected_tokens
    )
    assert report["summary"]["observed_tokens"] == report["accounting"]["observed_tokens"]
    assert report["summary"]["unassigned_observed_tokens"] == (7 if legacy == "reply" else 0)
    assert report["summary"]["unassigned_unknown_usage_calls"] == (1 if legacy == "error" else 0)
    assert report["accounting"]["unknown_usage_calls"] == (1 if legacy == "error" else 0)
    assert report["runs"][0]["unknown_usage_calls"] == (1 if legacy == "error" else 0)
    assert report["runs"][0]["usage_attribution_complete"] is (not legacy)
    assert report["runs"][0]["attempt_seconds"] == 2.0
    assert "seconds" not in report["runs"][0]
