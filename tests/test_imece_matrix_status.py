import json

import pytest
from evals.imece.protocol import digest
from scripts.imece_matrix_status import matrix_status


def checkpoints(directory):
    protocol = {"tasks": [{"id": "median"}], "repeats": 1}
    report = {
        "manifest": {"protocol": protocol, "protocol_hash": digest(protocol)},
        "source": "codex",
        "state": "partial",
        "runs": [{"task": "median", "repeat": 0, "status": "accepted", "oracle_passed": True}],
    }
    for arm in ("baseline", "candidate"):
        report["runs"][0]["oracle_passed"] = arm == "baseline"
        (directory / f"{arm}.json").write_text(json.dumps(report))


def test_status_exposes_false_acceptance_separately_from_completed_rows(tmp_path):
    checkpoints(tmp_path)
    result = matrix_status(tmp_path)
    assert result["completed"] == 2 and result["remaining"] == 0
    assert result["paired_completed"] == 1
    assert result["arms"]["baseline"]["false_acceptances"] == []
    assert result["arms"]["candidate"]["verified_successes"] == 0
    assert result["arms"]["candidate"]["false_acceptances"] == [{"task": "median", "repeat": 0}]


def test_status_rejects_different_protocols(tmp_path):
    checkpoints(tmp_path)
    path = tmp_path / "candidate.json"
    report = json.loads(path.read_text())
    report["manifest"]["protocol"]["repeats"] = 2
    report["manifest"]["protocol_hash"] = digest(report["manifest"]["protocol"])
    path.write_text(json.dumps(report))
    with pytest.raises(ValueError, match="different frozen protocols"):
        matrix_status(tmp_path)
