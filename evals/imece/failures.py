"""Export local repair examples from failed executable gates in a benchmark report."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from milyonus.security.redact import redact


def archive(report: dict) -> list[dict]:
    # Group the same frozen check across distinct trials. The full transcript and
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
                }
                if example not in family["examples"]:
                    family["examples"].append(example)
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
