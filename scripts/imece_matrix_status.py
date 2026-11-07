"""Read paired checkpoint progress without model calls or checkpoint mutation.

Run from the repository with uv run python scripts/imece_matrix_status.py DIR.
Running checkpoints can advance between reads, so output is an observation.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evals.imece.inspect_run import inspect_run  # noqa: E402
from evals.imece.protocol import digest  # noqa: E402


def matrix_status(directory: Path) -> dict:
    reports = {
        arm: json.loads((directory / f"{arm}.json").read_text(encoding="utf-8"))
        for arm in ("baseline", "candidate")
    }
    hashes = [report["manifest"]["protocol_hash"] for report in reports.values()]
    if hashes[0] != hashes[1]:
        raise ValueError("matrix arms have different frozen protocols")
    for report in reports.values():
        if digest(report["manifest"]["protocol"]) != hashes[0]:
            raise ValueError("matrix protocol hash mismatch")
    arms = {arm: inspect_run(directory / f"{arm}.json") for arm in reports}
    completed = sum(arm["completed_rows"] for arm in arms.values())
    remaining = sum(arm["remaining_rows"] for arm in arms.values())
    pairs = [
        {(row["task"], row["repeat"]) for row in report["runs"]} for report in reports.values()
    ]
    return {
        "completed": completed,
        "remaining": remaining,
        "total": completed + remaining,
        "paired_completed": len(pairs[0] & pairs[1]),
        "journal_scan_complete": all(arm["journal_scan_complete"] for arm in arms.values()),
        "arms": arms,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    result = matrix_status(args.directory)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["journal_scan_complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
