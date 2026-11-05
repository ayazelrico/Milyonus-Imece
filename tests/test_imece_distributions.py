import pytest

from milyonus.imece.benchmark import summarize


def row(**changes):
    return dict(
        {
            "status": "accepted",
            "oracle_passed": True,
            "seconds": 1,
            "tokens": 10,
            "cost_usd": 1,
            "cost_estimated": False,
        },
        **changes,
    )


def test_distribution_keeps_failures_and_interpolates_percentiles():
    result = summarize([row(), row(seconds=3, tokens=30, cost_usd=9, status="rejected")])
    seconds = result["distributions"]["seconds"]
    assert seconds["median"] == 2 and seconds["p95"] == pytest.approx(2.9)
    assert result["distributions"]["tokens"]["max"] == 30
    assert result["distributions"]["cost_usd"]["max"] == 9
    assert result["status_counts"] == {"accepted": 1, "rejected": 1}


def test_missing_cost_never_yields_a_partial_population_percentile():
    result = summarize([row(), row(cost_usd=None, unknown_usage_calls=1)])
    cost = result["distributions"]["cost_usd"]
    assert cost["known_runs"] == cost["unknown_runs"] == 1
    assert cost["median"] is None and cost["p95"] is None
    assert result["distributions"]["tokens"]["p95"] is None


def test_empty_distribution_does_not_invent_zero_cost_or_latency():
    result = summarize([])
    assert all(d["median"] is None for d in result["distributions"].values())


def test_execution_failure_counts_do_not_mix_in_model_judgment():
    result = summarize(
        [
            row(
                report={
                    "gate_reports": [
                        {
                            "verification": "python:docker",
                            "test_results": [
                                {"passed": False, "failure_class": "timeout"},
                                {"passed": False},
                                {"passed": True},
                            ],
                        },
                        {"verification": "model", "test_results": [{"passed": False}]},
                    ]
                }
            )
        ]
    )
    assert result["gate_failure_classes"] == {"timeout": 1, "unknown": 1}
