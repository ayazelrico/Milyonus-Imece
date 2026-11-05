"""Regression coverage for the independent CLI review findings."""

import json
from dataclasses import replace

import pytest
from evals.imece.dataset import load_tasks
from evals.imece.protocol import manifest, validate_report

from milyonus.imece.benchmark import BenchmarkTask, _score_artifact
from milyonus.imece.codex import DISABLED_CODE_MODE_NOTICE, CodexError, parse_codex_jsonl
from milyonus.imece.orchestrator import ImeceSettings


def frozen(settings=None):
    return manifest(
        tasks=load_tasks(),
        settings=settings or ImeceSettings(),
        models={"pool": "m"},
        runtime={"engine": "codex"},
        seed=0,
        repeats=1,
        revision="test",
    )


def test_cli_cannot_use_fabricated_provider_ledger():
    report = {
        "manifest": frozen(),
        "source": "codex",
        "runs": [],
        "ledger": {"unknown_calls": 0, "overruns": 0},
    }
    with pytest.raises(ValueError, match="provider ledger"):
        validate_report(report)


@pytest.mark.parametrize(
    "change", [{"agent_timeout": 1}, {"max_parallel": 1}, {"pass_threshold": 0.9}]
)
def test_execution_confounders_change_shared_protocol(change):
    assert frozen()["protocol_hash"] != frozen(replace(ImeceSettings(), **change))["protocol_hash"]


def test_predeclared_adaptive_treatment_can_share_execution_protocol():
    assert (
        frozen()["protocol_hash"]
        == frozen(ImeceSettings(adaptive_production=True))["protocol_hash"]
    )


async def test_assertion_only_oracle_cannot_certify_early_exit():
    class Executor:
        async def run(self, *args):
            pytest.fail("uncertified assertion-only task must not be executed")

    passed, note = await _score_artifact(
        Executor(),
        BenchmarkTask("x", "x", "assert False"),
        "```python file=solution.py\nimport os; os._exit(0)\n```",
    )
    assert not passed and "host cases required" in note


def events(notice, *, after_start=False):
    warning = {"type": "item.completed", "item": {"type": "error", "message": notice}}
    start = {"type": "turn.started"}
    return b"\n".join(
        json.dumps(e).encode()
        for e in [
            *([start, warning] if after_start else [warning, start]),
            {"type": "item.completed", "item": {"type": "agent_message", "text": "READY"}},
            {
                "type": "turn.completed",
                "usage": {"input_tokens": 3, "output_tokens": 1, "cached_input_tokens": 0},
            },
        ]
    )


def test_known_disabled_host_startup_notice_is_not_tool_execution():
    assert parse_codex_jsonl(events(DISABLED_CODE_MODE_NOTICE)).text == "READY"


@pytest.mark.parametrize(
    "notice,after_start", [("quota exhausted", False), (DISABLED_CODE_MODE_NOTICE, True)]
)
def test_other_or_in_turn_error_items_still_fail_closed(notice, after_start):
    with pytest.raises(CodexError):
        parse_codex_jsonl(events(notice, after_start=after_start))


@pytest.mark.parametrize("source", ["codex", "antigravity"])
def test_engine_less_cli_source_cannot_smuggle_provider_ledger(source):
    value = frozen()
    del value["protocol"]["runtime"]["engine"]
    from evals.imece.protocol import digest

    value["protocol_hash"] = digest(value["protocol"])
    report = {
        "manifest": value,
        "source": source,
        "runs": [
            {
                "task": t["id"],
                "repeat": 0,
                "status": "accepted",
                "oracle_passed": True,
                "tokens": 1,
                "cost_usd": 1,
                "cost_estimated": False,
            }
            for t in value["protocol"]["tasks"]
        ],
        "ledger": {"unknown_calls": 0, "overruns": 0},
    }
    with pytest.raises(ValueError, match="provider ledger"):
        validate_report(report)
