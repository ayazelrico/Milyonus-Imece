"""Compare observed task outcomes across Hermes and İmece without a 5X verdict."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from evals.imece.protocol import digest, validate_report


def paired_outcomes(imece: dict, hermes: dict) -> dict:
    if imece.get("source") not in {"codex", "antigravity"} or hermes.get("source") != "hermes":
        raise ValueError("expected an İmece CLI report and a Hermes report")
    left = validate_report(imece)
    right = validate_report(hermes)
    a, b = (r["manifest"]["protocol"] for r in (imece, hermes))
    for key in ("tasks", "scorer_hash", "seed", "repeats"):
        if key not in a or key not in b or a[key] != b[key]:
            raise ValueError(f"incomparable experiment field: {key}")
    for key in ("backend", "platform", "python", "image"):
        if key not in a["runtime"] or a["runtime"][key] != b["runtime"].get(key):
            raise ValueError(f"incomparable scorer environment: {key}")
    if a["limits"]["test_timeout"] != b["limits"]["test_timeout"]:
        raise ValueError("scorer timeouts differ")
    if a["models"].get("pool") != b["models"].get("pool"):
        raise ValueError("generation model identifiers differ")
    indexed = {(r["task"], r["repeat"]): r for r in right}
    counts = Counter()
    for row in left:
        other = indexed[row["task"], row["repeat"]]
        i = row["status"] == "accepted" and row["oracle_passed"]
        h = other["status"] == "accepted" and other["oracle_passed"]
        counts["both" if i and h else "imece_only" if i else "hermes_only" if h else "neither"] += 1
    return {
        "imece_hash": digest(imece),
        "hermes_hash": digest(hermes),
        "paired_trials": len(left),
        "verified_outcomes": {
            k: counts[k] for k in ("both", "imece_only", "hermes_only", "neither")
        },
        "models": {"imece": a["models"], "hermes": b["models"]},
        "generation_limits": {"imece": a["limits"], "hermes": b["limits"]},
        "note": "Descriptive paired outcomes only. CLI resource enforcement, review and acceptance policies differ.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("imece", type=Path)
    parser.add_argument("hermes", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = paired_outcomes(
        json.loads(args.imece.read_text()), json.loads(args.hermes.read_text())
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
        f.write("\n")


if __name__ == "__main__":
    main()
