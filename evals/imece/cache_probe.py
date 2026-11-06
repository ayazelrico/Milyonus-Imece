"""Measure real Docker cache reuse on a declared, synthetic repeated workload.

No model calls or financial claims. A cold cache and an uncached executor see
the same public fixtures. Changes to source, checks and timeout must miss;
unapproved generated checks and failed checks must always execute.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import platform
import re
import tempfile
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from evals.imece.protocol import digest
from evals.imece.run import atomic_write
from milyonus.imece import evidence, execution
from milyonus.imece.execution import PythonExecutor

DEFAULT_IMAGE = "python@sha256:e695ab189fa2d082b1c61c69a6b888a5adeca61ceeccad107b1ed2a125721a9e"
FIXTURES = (
    (
        "stable_unique",
        "def solve(xs):\n    return list(dict.fromkeys(xs))\n",
        "from solution import solve\nassert solve([3,1,3,2,1]) == [3,1,2]\nassert solve([]) == []\n",
    ),
    (
        "group_totals",
        "def solve(rows):\n    out = {}\n    for k,v in rows:\n        out[k] = out.get(k,0)+v\n    return out\n",
        "from solution import solve\nassert solve([('a',2),('b',3),('a',-1)]) == {'a':1,'b':3}\n",
    ),
    (
        "clamp",
        "def solve(x, lo, hi):\n    return min(hi, max(lo, x))\n",
        "from solution import solve\nassert [solve(x,0,4) for x in [-2,2,8]] == [0,2,4]\n",
    ),
)


class TighterExecutor(PythonExecutor):
    """Operator-owned policy mutation: lower the container PID limit."""

    def _argv(self, root: Path, container: str) -> list[str]:
        return [
            "--pids-limit=16" if value == "--pids-limit=32" else value
            for value in super()._argv(root, container)
        ]


async def run_probe(*, image: str = DEFAULT_IMAGE, repeats: int = 5) -> dict:
    if not re.fullmatch(r".+@sha256:[0-9a-f]{64}", image):
        raise ValueError("a digest-pinned Docker image is required")
    if type(repeats) is not int or repeats < 2:
        raise ValueError("at least two repeats are required")
    observations = []

    async def observe(executor, name, files, oracle, *, reused=False, passed=True, trusted=True):
        before = executor.processes_started
        metadata_before = executor.metadata_processes_started
        result = await executor.run(files, oracle, deterministic=trusted)
        delta = executor.processes_started - before
        valid = (
            result.passed is passed
            and result.reused is reused
            and delta == (0 if reused else 1)
            and result.backend == "docker"
            and result.returncode == (0 if passed else 1)
            and result.failure_class == (None if passed else "candidate_or_oracle_runtime")
            and not result.output_truncated
        )
        observations.append(
            {
                "case": name,
                "processes": delta,
                "metadata_processes": executor.metadata_processes_started - metadata_before,
                "expected_reused": reused,
                "expected_passed": passed,
                "valid": valid,
                "result": asdict(result),
            }
        )
        return result

    with tempfile.TemporaryDirectory(prefix="imece-cache-probe-") as directory:
        baseline = PythonExecutor(image=image)
        cached = PythonExecutor(image=image, cache_path=Path(directory) / "evidence.sqlite")
        approved = set()
        for repeat in range(repeats):
            for name, code, oracle in FIXTURES:
                result = await observe(
                    baseline, f"baseline:{name}:{repeat}", {"solution.py": code}, oracle
                )
                if repeat == 0 and result.passed and result.evidence_id:
                    approved.add(result.evidence_id)
        # These public fixtures are declared deterministic by the operator of
        # this probe, never by model output. The cache starts empty.
        cached.approved_evidence = frozenset(approved)
        for repeat in range(repeats):
            for name, code, oracle in FIXTURES:
                await observe(
                    cached,
                    f"cached:{name}:{repeat}",
                    {"solution.py": code},
                    oracle,
                    reused=repeat > 0,
                    trusted=False,
                )
        baseline_processes = baseline.processes_started
        cached_processes = cached.processes_started
        baseline_metadata = baseline.metadata_processes_started
        cached_metadata = cached.metadata_processes_started
        _, code, oracle = FIXTURES[0]
        files = {"solution.py": code}
        for name, changed_files, changed_oracle, timeout in (
            ("source", {"solution.py": code + "\n# changed source identity\n"}, oracle, 10.0),
            ("oracle", files, oracle + "assert solve([7,7]) == [7]\n", 10.0),
            ("timeout", files, oracle, 11.0),
        ):
            changed = PythonExecutor(image=image, timeout=timeout, cache_path=cached.cache_path)
            await observe(changed, f"invalidate:{name}", changed_files, changed_oracle)
            await observe(
                changed, f"reuse-changed:{name}", changed_files, changed_oracle, reused=True
            )
        changed_policy = TighterExecutor(image=image, cache_path=cached.cache_path)
        await observe(changed_policy, "invalidate:policy", files, oracle)
        await observe(changed_policy, "reuse-changed:policy", files, oracle, reused=True)
        unapproved = PythonExecutor(image=image, cache_path=cached.cache_path)
        for repeat in range(2):
            await observe(unapproved, f"unapproved:{repeat}", files, oracle, trusted=False)
            await observe(cached, f"failed:{repeat}", files, "assert False\n", passed=False)

    valid = all(row["valid"] for row in observations)
    reduction = 1 - cached_processes / baseline_processes if valid and baseline_processes else None
    sources = [Path(__file__), Path(execution.__file__), Path(evidence.__file__)]
    return {
        "schema_version": 2,
        "generated_at": datetime.now(UTC).isoformat(),
        "kind": "synthetic-docker-cache-probe",
        "valid": valid,
        "runtime": {
            "image": image,
            "architecture": platform.machine(),
            "python": platform.python_version(),
        },
        "source_hashes": {
            str(p.relative_to(Path(__file__).resolve().parents[2])): hashlib.sha256(
                p.read_bytes()
            ).hexdigest()
            for p in sources
        },
        "workload_hash": digest(FIXTURES),
        "cache_admission": "operator-approved-baseline-evidence",
        "approved_evidence": sorted(approved),
        "repeats": repeats,
        "fixtures": len(FIXTURES),
        "baseline_processes": baseline_processes,
        "cached_processes": cached_processes,
        "baseline_metadata_processes": baseline_metadata,
        "cached_metadata_processes": cached_metadata,
        "baseline_total_cli_processes": baseline_processes + baseline_metadata,
        "cached_total_cli_processes": cached_processes + cached_metadata,
        "total_cli_process_reduction": (
            1 - (cached_processes + cached_metadata) / (baseline_processes + baseline_metadata)
            if valid and baseline_processes + baseline_metadata
            else None
        ),
        "process_reduction_scope": "verification-containers-only",
        "process_reduction": reduction,
        "synthetic_reduction_at_least_60pct": reduction >= 0.6 if reduction is not None else None,
        "invalidation_dimensions": ["source", "oracle", "timeout", "policy"],
        "observations": observations,
        "model_calls": 0,
        "cost_usd": None,
        "accepted_5x": False,
        "limitations": [
            "Constructed repeated work; does not establish production reuse frequency or full-matrix P2/P5 acceptance.",
            "Invalidation probes cover source, oracle, timeout and a tighter PID policy; not every runtime mutation.",
            "No provider calls, fee receipts, speed claim or independent audit attestation.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default=DEFAULT_IMAGE)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    report = asyncio.run(run_probe(image=args.image, repeats=args.repeats))
    atomic_write(args.out, report)
    print(
        json.dumps(
            {
                key: report[key]
                for key in (
                    "valid",
                    "baseline_processes",
                    "cached_processes",
                    "process_reduction",
                    "process_reduction_scope",
                    "total_cli_process_reduction",
                )
            }
        )
    )
    return 0 if report["valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
