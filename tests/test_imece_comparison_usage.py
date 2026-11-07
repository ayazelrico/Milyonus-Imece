"""A frozen comparison reconciles every trial with the durable dispatch log."""

from dataclasses import asdict

import pytest
from evals.imece.dataset import load_suite
from evals.imece.protocol import compare, manifest

from milyonus.imece.agents import AgentReply, AgentSpec
from milyonus.imece.journal import fingerprint
from milyonus.imece.orchestrator import ImeceSettings


def report(*, unknown=False):
    task = load_suite("core-v2")[0]
    frozen = manifest(
        tasks=(task,),
        settings=ImeceSettings(),
        models={"pool": "fixed"},
        runtime={
            "engine": "codex",
            "backend": "docker",
            "image": "python@sha256:" + "1" * 64,
            "verification_environment_id": "2" * 64,
        },
        repeats=1,
        seed=0,
        revision="test",
    )
    spec = asdict(AgentSpec("production", "builder", "solve", "context", ["correct"]))
    reply = asdict(AgentReply("response", 50))
    call = {
        "call_id": "3" * 32,
        "sequence": 0,
        "task": task.id,
        "repeat": 0,
        "journal": {
            "identity_hash": "4" * 64,
            "node_id": "5" * 64,
            "spec_hash": fingerprint(spec),
            "task": task.id,
            "repeat": 0,
        },
        "spec": spec,
        "model": "fixed",
        "state": "completed",
        "reply": reply,
        "output_hash": fingerprint(reply),
    }
    calls = [call]
    if unknown:
        pending = {k: v for k, v in call.items() if k not in ("reply", "output_hash")}
        pending.update(
            call_id="6" * 32,
            sequence=1,
            state="unknown",
            journal=call["journal"] | {"node_id": "7" * 64},
        )
        calls.append(pending)
    return {
        "manifest": frozen,
        "state": "complete",
        "source": "codex",
        "transcripts": calls,
        "runs": [
            {
                "task": task.id,
                "repeat": 0,
                "status": "accepted",
                "oracle_passed": True,
                "tokens": None if unknown else 50,
                "observed_tokens": 50,
                "unknown_usage_calls": int(unknown),
                "usage_attribution_complete": True,
                "cost_usd": None,
            }
        ],
    }


def test_known_and_unknown_usage_are_reconciled_without_treating_unknown_as_zero():
    outcome = compare(report(), report(unknown=True))
    assert outcome["baseline"]["total_tokens"] == 50
    assert outcome["candidate"]["total_tokens"] is None
    assert outcome["candidate"]["observed_tokens"] == 50
    assert outcome["phase_efficiency"]["candidate_to_baseline_tokens_per_verified_success"] is None


@pytest.mark.parametrize(
    "tamper",
    [
        "row_total",
        "observed_total",
        "unknown_count",
        "reply",
        "duplicate",
        "running",
        "inline_cost",
        "missing_calls",
    ],
)
def test_inconsistent_report_cannot_produce_comparison(tamper):
    candidate = report(unknown=tamper in {"unknown_count", "running"})
    row = candidate["runs"][0]
    calls = candidate["transcripts"]
    if tamper == "row_total":
        row["tokens"] = 1
    elif tamper == "observed_total":
        row["observed_tokens"] = 1
    elif tamper == "unknown_count":
        row["unknown_usage_calls"] = 0
    elif tamper == "reply":
        calls[0]["reply"]["tokens"] = 1
    elif tamper == "duplicate":
        calls.append(calls[0] | {"sequence": 1})
    elif tamper == "running":
        calls[1]["state"] = "running"
    elif tamper == "inline_cost":
        row["cost_usd"] = 1
    else:
        calls.clear()
        row.update(tokens=0, observed_tokens=0)
    with pytest.raises(ValueError):
        compare(report(), candidate)
