import json

import pytest
from evals.imece.dataset import load_tasks
from evals.imece.inspect_run import inspect_run
from evals.imece.protocol import manifest

from milyonus.imece import benchmark
from milyonus.imece.orchestrator import ImeceSettings, RunResult
from milyonus.imece.schedule import trial_coordinates


def test_repeat_major_covers_each_task_before_repeating():
    assert trial_coordinates(["a", "b"], 2, order="repeat-major") == (
        ("a", 0),
        ("b", 0),
        ("a", 1),
        ("b", 1),
    )
    assert trial_coordinates(["a", "b"], 2, order="task-major") == (
        ("a", 0),
        ("a", 1),
        ("b", 0),
        ("b", 1),
    )


@pytest.mark.parametrize(
    "ids,repeats,order",
    [(["a", "a"], 1, "repeat-major"), (["a"], True, "repeat-major"), (["a"], 1, "unknown")],
)
def test_invalid_schedule_is_rejected(ids, repeats, order):
    with pytest.raises(ValueError):
        trial_coordinates(ids, repeats, order=order)


async def test_executor_resumes_missing_trials_in_declared_order(monkeypatch):
    class FakeImece:
        def __init__(self, *args, **kwargs):
            pass

        async def run(self, request):
            return RunResult(status="rejected", request=request)

    async def score(executor, *args):
        executor.processes_started += 1
        executor.metadata_processes_started += 2
        return False, "not executed"

    monkeypatch.setattr(benchmark, "Imece", FakeImece)
    monkeypatch.setattr(benchmark, "_score_artifact", score)
    tasks = load_tasks()[:2]
    completed = [
        {
            "task": tasks[0].id,
            "repeat": 0,
            "status": "rejected",
            "oracle_passed": False,
            "tokens": 1,
            "cost_usd": None,
        }
    ]
    observed = []
    report = await benchmark.run_benchmark(
        None,
        ImeceSettings(verification="python"),
        tasks=tasks,
        repeats=2,
        completed_rows=completed,
        trial_order="repeat-major",
        on_trial=lambda t, r: observed.append((t, r)),
    )
    assert observed == [(tasks[1].id, 0), (tasks[0].id, 1), (tasks[1].id, 1)]
    assert len(report["runs"]) == 4
    for row in report["runs"][1:]:
        metrics = row["report"]["metrics"]
        assert metrics["benchmark_processes_started"] == 1
        assert metrics["benchmark_metadata_processes_started"] == 2


@pytest.mark.parametrize("order,next_position", [("task-major", (0, 1)), ("repeat-major", (1, 0))])
def test_inspector_next_trial_matches_execution_schedule(tmp_path, order, next_position):
    tasks = load_tasks()[:2]
    frozen = manifest(
        tasks=tasks,
        settings=ImeceSettings(),
        models={"pool": "m"},
        runtime={},
        seed=0,
        repeats=2,
        revision="test",
        trial_order=order,
    )
    path = tmp_path / "report.json"
    path.write_text(
        json.dumps(
            {
                "manifest": frozen,
                "source": "codex",
                "state": "partial",
                "runs": [
                    {
                        "task": tasks[0].id,
                        "repeat": 0,
                        "status": "rejected",
                        "oracle_passed": False,
                        "tokens": 1,
                        "cost_usd": None,
                    }
                ],
            }
        )
    )
    result = inspect_run(path)
    i, repeat = next_position
    assert result["next_unrecorded"] == {"task": tasks[i].id, "repeat": repeat}


async def test_hermes_executes_the_order_declared_in_its_manifest(tmp_path, monkeypatch):
    from evals.hermes import adapter

    tasks = load_tasks()[:2]
    requests = []

    async def ask(prompt, **kwargs):
        requests.append(prompt)
        return "artifact"

    async def score(*args):
        return False, "not executed"

    monkeypatch.setattr(adapter, "load_suite", lambda _: tasks)
    monkeypatch.setattr(adapter, "available", lambda: True)
    monkeypatch.setattr(adapter, "_ask_hermes", ask)
    monkeypatch.setattr(adapter, "_score_artifact", score)
    report = await adapter.run_suite(
        out=tmp_path / "hermes.json", model="fake", repeats=2, trial_order="repeat-major"
    )
    assert requests == [tasks[0].request, tasks[1].request] * 2
    assert report["manifest"]["protocol"]["trial_order"] == "repeat-major"
    assert [(r["task"], r["repeat"]) for r in report["runs"]] == list(
        trial_coordinates([t.id for t in tasks], 2, order="repeat-major")
    )
