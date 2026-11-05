"""Compare frozen reports without model calls: python -m evals.imece.compare BASE CAND."""

import argparse
import json
from pathlib import Path

from evals.imece.protocol import compare


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("baseline", type=Path)
    p.add_argument("candidate", type=Path)
    p.add_argument("--audit", type=Path)
    p.add_argument("--baseline-receipts", type=Path)
    p.add_argument("--candidate-receipts", type=Path)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    result = compare(
        json.loads(args.baseline.read_text()),
        json.loads(args.candidate.read_text()),
        audit=json.loads(args.audit.read_text()) if args.audit else None,
        baseline_receipts=json.loads(args.baseline_receipts.read_text())
        if args.baseline_receipts
        else None,
        candidate_receipts=json.loads(args.candidate_receipts.read_text())
        if args.candidate_receipts
        else None,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return 0 if result["accepted_5x"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
