"""Export local repair examples from failed executable gates in a benchmark report."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from milyonus.security.redact import redact


def archive(report: dict) -> list[dict]:
    # Group diagnostic similarities, not proven common causes. The transcript and
    # private reference oracle never become part of a suggested skill.
    families: dict[tuple[str, str, str | None], dict] = {}
    for row in report["runs"]:
        for gate in row.get("report", {}).get("gate_reports", []):
            if not gate.get("verification", "").startswith("python:"):
                continue
            for observation in gate.get("test_results", []):
                if observation.get("passed") is not False:
                    continue
                output = redact(str(observation.get("output", ""))).strip()
                last_line = output.splitlines()[-1][:500] if output else "No diagnostic output"
                failure_class = observation.get("failure_class")
                key = (gate["verification"], last_line, failure_class)
                family = families.setdefault(
                    key,
                    {
                        "diagnostic": last_line,
                        "backend": key[0],
                        "failure_class": failure_class,
                        "examples": [],
                        "status": "unverified",
                    },
                )
                example = {
                    "task": row["task"],
                    "repeat": row["repeat"],
                    "candidate": gate["candidate_id"],
                    "check": observation["test"],
                    "returncode": observation.get("returncode"),
                    "failure_class": failure_class,
                    "output_truncated": observation.get("output_truncated"),
                    "source": observation.get("source"),
                }
                if example not in family["examples"]:
                    family["examples"].append(example)
    for family in families.values():
        examples = family["examples"]
        family["distinct_tasks"] = len({e["task"] for e in examples})
        family["distinct_trials"] = len({(e["task"], e["repeat"]) for e in examples})
        eligible = family["failure_class"] == "candidate_or_oracle_runtime" and any(
            type(e["returncode"]) is int
            and e["returncode"] == 1
            and e["output_truncated"] is False
            and e["source"] == family["backend"]
            for e in examples
        )
        family["repair_template"] = (
            {
                "status": "draft_requires_operator_review",
                "symptom": family["diagnostic"],
                "steps": [
                    "Preserve the frozen public contract and the original candidate files.",
                    "Reproduce the failed generated check in the recorded isolated environment.",
                    "Determine whether candidate code or the check violates the contract.",
                    "Repair the smallest demonstrated candidate defect; retain unrelated behavior.",
                    "Replay the original check and independent tasks before proposing a skill.",
                ],
                "invalidation": [
                    "Changed or revoked oracle, contract, runtime or execution policy.",
                    "Failure cannot be reproduced or the generated check is incorrect.",
                ],
                "promotion": "staging only; two independent operator-supplied task replays required",
            }
            if eligible
            else None
        )
    return list(families.values())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    raw = args.report.read_bytes()
    report = json.loads(raw)
    payload = {
        "schema_version": 1,
        "report_sha256": hashlib.sha256(raw).hexdigest(),
        "families": archive(report),
        "reproductions": [
            dict(item, task=row["task"], repeat=row["repeat"])
            for row in report["runs"]
            for item in (row.get("report") or {}).get("reproductions", [])
        ],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")


if __name__ == "__main__":
    main()
