"""Compare measured process counts only for identical verification workloads."""

import pytest
from evals.imece.efficiency import paired_efficiency


def row(task, *, cached, metadata, identity="same"):
    metrics = {"gate_processes_started": 1 if cached else 2}
    if metadata is not None:
        metrics["gate_metadata_processes_started"] = metadata
    return {
        "task": task,
        "repeat": 0,
        "report": {
            "metrics": metrics,
            "gate_reports": [
                {
                    "test_results": [
                        {"evidence_id": identity, "reused": False},
                        {"evidence_id": identity, "reused": cached},
                    ]
                }
            ],
        },
    }


def test_total_includes_metadata_but_excludes_different_workloads():
    baseline = [
        row("matched", cached=False, metadata=4),
        row("different", cached=False, metadata=100),
    ]
    candidate = [
        row("matched", cached=True, metadata=4),
        row("different", cached=True, metadata=100, identity="changed"),
    ]
    summary = {"tokens_per_verified_success": None}
    result = paired_efficiency(baseline, candidate, summary, summary)
    assert result["gate_trials_with_identical_workload"] == 1
    assert result["matched_gate_trials_with_metadata_counts"] == 1
    assert result["matched_baseline_total_gate_processes"] == 6
    assert result["matched_candidate_total_gate_processes"] == 5
    assert result["matched_process_reduction"] == 0.5
    assert result["matched_total_gate_process_reduction"] == pytest.approx(1 / 6)


@pytest.mark.parametrize("missing", [None, -1, True])
def test_partial_or_invalid_metadata_keeps_total_unknown(missing):
    baseline = [row("new", cached=False, metadata=4), row("legacy", cached=False, metadata=4)]
    candidate = [row("new", cached=True, metadata=4), row("legacy", cached=True, metadata=missing)]
    summary = {"tokens_per_verified_success": None}
    result = paired_efficiency(baseline, candidate, summary, summary)
    assert result["gate_trials_with_identical_workload"] == 2
    assert result["matched_gate_trials_with_metadata_counts"] == 1
    assert result["matched_process_reduction"] == 0.5
    assert result["matched_candidate_total_gate_processes"] is None
    assert result["matched_total_gate_process_reduction"] is None
