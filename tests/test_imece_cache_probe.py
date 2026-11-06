"""Real processes, persisted cache reads and mutated verification identities."""

import os

import pytest
from evals.imece.cache_probe import DEFAULT_IMAGE, run_probe


@pytest.mark.skipif(os.environ.get("MILYONUS_TEST_DOCKER") != "1", reason="Docker opt-in")
async def test_real_docker_cache_probe_preserves_results_and_invalidates_changes():
    report = await run_probe(image=DEFAULT_IMAGE, repeats=3)
    assert report["valid"], [r for r in report["observations"] if not r["valid"]]
    assert report["baseline_processes"] == 9
    assert report["cached_processes"] == 3
    assert report["synthetic_reduction_at_least_60pct"] is True
    assert report["accepted_5x"] is False
    by_case = {row["case"]: row["result"] for row in report["observations"]}
    initial = by_case["cached:stable_unique:0"]["evidence_id"]
    for dimension in report["invalidation_dimensions"]:
        changed = by_case[f"invalidate:{dimension}"]
        reused = by_case[f"reuse-changed:{dimension}"]
        assert changed["evidence_id"] != initial
        assert changed["evidence_id"] == reused["evidence_id"]
        assert changed["reused"] is False and reused["reused"] is True
    for repeat in range(2):
        assert by_case[f"unapproved:{repeat}"]["reused"] is False
        assert by_case[f"failed:{repeat}"]["reused"] is False
