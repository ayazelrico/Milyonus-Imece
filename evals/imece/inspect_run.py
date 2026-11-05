"""Inspect a paused CLI experiment locally without resuming or making model calls."""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter
from contextlib import closing
from pathlib import Path

from evals.imece.protocol import digest, validate_rows


def inspect_run(path: Path) -> dict:
    checkpoint = json.loads(path.read_text(encoding="utf-8"))
    manifest = checkpoint["manifest"]
    protocol = manifest["protocol"]
    if digest(protocol) != manifest["protocol_hash"]:
        raise ValueError("checkpoint protocol hash mismatch")
    rows = validate_rows(checkpoint["runs"], protocol)
    status_counts = Counter(row["status"] for row in rows)
    gate_failure_classes = Counter(
        observation.get("failure_class") or "unknown"
        for row in rows
        for gate in row.get("report", {}).get("gate_reports", [])
        if gate.get("verification", "").startswith("python:")
        for observation in gate.get("test_results", [])
        if observation.get("passed") is False
    )
    completed = {(row["task"], row["repeat"]) for row in rows}
    remaining = [
        (task["id"], repeat)
        for task in protocol["tasks"]
        for repeat in range(protocol["repeats"])
        if (task["id"], repeat) not in completed
    ]
    unresolved = []
    journal_errors = []
    journal_dir = path.with_suffix(".journal")
    if journal_dir.is_symlink():
        raise ValueError("unexpected journal directory symlink")
    for journal in sorted(journal_dir.glob("*.sqlite")):
        if journal.is_symlink() or not journal.is_file():
            raise ValueError("unexpected journal file")
        try:
            with closing(sqlite3.connect(journal.resolve().as_uri() + "?mode=ro", uri=True)) as db:
                if db.execute("SELECT hash FROM identity WHERE id=1").fetchone() is None:
                    raise ValueError("missing run identity")
                for node, phase, state in db.execute(
                    "SELECT id,phase,state FROM nodes WHERE state != 'completed' ORDER BY rowid"
                ):
                    unresolved.append(
                        {"journal": journal.name, "node": node, "phase": phase, "state": state}
                    )
        except (sqlite3.Error, ValueError) as exc:
            journal_errors.append({"journal": journal.name, "error": str(exc)})
    return {
        "checkpoint_state": checkpoint.get("state"),
        "engine": checkpoint["source"],
        "completed_rows": len(completed),
        "status_counts": dict(sorted(status_counts.items())),
        "gate_failure_classes": dict(sorted(gate_failure_classes.items())),
        "verified_successes": sum(
            row["status"] == "accepted" and row["oracle_passed"] for row in rows
        ),
        "budget_rows": sum(row["status"] == "budget" for row in rows),
        "remaining_rows": len(remaining),
        "next_unrecorded": {"task": remaining[0][0], "repeat": remaining[0][1]}
        if remaining
        else None,
        "unresolved_calls": unresolved,
        "journal_errors": journal_errors,
        "journal_scan_complete": not journal_errors,
        "checkpoint_updated_at": checkpoint.get("updated_at"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checkpoint", type=Path)
    args = parser.parse_args()
    result = inspect_run(args.checkpoint)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["journal_scan_complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
