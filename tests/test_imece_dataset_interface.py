"""The live median failure must become a public interface, not a relaxed scorer."""

import os

import pytest
from evals.imece.data.build_core import TASKS as REFERENCES
from evals.imece.dataset import JSON_INTERFACE, load_suite
from evals.imece.protocol import digest

from milyonus.imece.benchmark import _score_artifact
from milyonus.imece.execution import PythonExecutor


def test_v3_changes_public_contracts_without_changing_hidden_cases():
    old, new = load_suite("core-v2"), load_suite("core-v3")
    assert len(new) == 50
    for before, after in zip(old, new, strict=True):
        assert before.id == after.id
        assert after.request == before.request + JSON_INTERFACE
        assert before.oracle == after.oracle and before.cases == after.cases
        assert digest(before.request) != digest(after.request)
        assert "cases =" not in after.request
    median = next(t for t in old if t.id == "fix_even_median")
    assert digest(median.request) == (
        "5e2860042e00d2a1cfc84fdea0f420831c32e35b5351fb252c1803f031b28dd6"
    )


def test_all_entry_points_accept_v3_and_preparation_defaults_to_it():
    from evals.hermes.adapter import make_parser as hermes_parser
    from evals.imece.prepare_pair import make_parser as pair_parser
    from evals.imece.run import make_parser as run_parser

    assert (
        run_parser().parse_args(["--engine", "codex", "--model", "m", "--suite", "core-v3"]).suite
        == "core-v3"
    )
    pair = pair_parser().parse_args(
        ["--model", "m", "--out-dir", "pair", "--baseline-config", "b", "--candidate-config", "c"]
    )
    assert pair.suite == "core-v3"
    assert (
        hermes_parser()
        .parse_args(["--out", "report.json", "--model", "m", "--suite", "core-v3", "--prepare"])
        .suite
        == "core-v3"
    )


@pytest.mark.skipif(os.environ.get("MILYONUS_TEST_DOCKER") != "1", reason="Docker opt-in")
async def test_real_host_scorer_accepts_numeric_references_and_rejects_fraction():
    executor = PythonExecutor(timeout=10)
    tasks = {task.id: task for task in load_suite("core-v3")}
    for task_id, _, _, body, _ in REFERENCES:
        if task_id not in ("fix_even_median", "weighted_score", "cost_per_success"):
            continue
        code = "def solve(value):\n" + "".join(" " + line + "\n" for line in body.splitlines())
        passed, note = await _score_artifact(
            executor, tasks[task_id], f"```python file=solution.py\n{code}```"
        )
        assert passed, note
    for body, expected_note in (
        (
            "from fractions import Fraction\n"
            "def solve(value):\n"
            " a = sorted(value); n = len(a)\n"
            " return a[n//2] if n%2 else Fraction(a[n//2-1]+a[n//2], 2)\n",
            "Fraction is not JSON serializable",
        ),
        ("def solve(value): return sorted(value)[len(value)//2]\n", "incorrect result"),
    ):
        passed, note = await _score_artifact(
            executor, tasks["fix_even_median"], f"```python file=solution.py\n{body}```"
        )
        assert not passed and expected_note in note
