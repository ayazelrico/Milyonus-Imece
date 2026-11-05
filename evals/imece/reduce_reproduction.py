"""Reduce captured file sets using bounded isolated replays; never call a model."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path

from milyonus.imece.execution import PythonExecutor


def diagnostic(result):
    if (
        result.passed
        or result.returncode != 1
        or result.failure_class != "candidate_or_oracle_runtime"
        or result.output_truncated
        or not result.output.strip()
    ):
        return None
    return result.output.strip().splitlines()[-1]


async def reduce_files(bundle: dict, executor, *, max_attempts: int = 32) -> dict:
    """Keep the check and solution.py fixed; discard only dispensable extra files.

    Matching the last diagnostic is an observation, not proof of the same cause.
    A bounded greedy reduction does not establish global minimality.
    """
    if type(max_attempts) is not int or not 2 <= max_attempts <= 128:
        raise ValueError("max attempts must be 2..128")
    fields = ("files", "check", "backend", "image", "timeout")
    if not isinstance(bundle, dict) or not all(k in bundle for k in fields):
        raise ValueError("missing reproduction contract")
    contract = {k: bundle[k] for k in fields}
    raw = json.dumps(contract, sort_keys=True, ensure_ascii=False)
    if hashlib.sha256(raw.encode()).hexdigest() != bundle.get("digest"):
        raise ValueError("reproduction digest mismatch")
    files, check = contract["files"], contract["check"]
    if (
        not isinstance(files, dict)
        or not files
        or len(files) > 32
        or not all(isinstance(k, str) and isinstance(v, str) for k, v in files.items())
        or not isinstance(check, str)
        or len(raw.encode()) > 32768
    ):
        raise ValueError("invalid or oversized reproduction")
    if any(getattr(executor, k) != contract[k] for k in ("backend", "image", "timeout")):
        raise ValueError("executor differs from recorded reproduction")
    files = dict(files)
    first = diagnostic(await executor.run(files, check))
    attempts = 1
    if first is None or diagnostic(await executor.run(files, check)) != first:
        raise ValueError("failure did not reproduce twice with a stable diagnostic")
    attempts += 1
    removed = []
    exhausted = False
    while True:
        changed = False
        for name in sorted(files):
            if name == "solution.py" or len(files) == 1:
                continue
            if attempts >= max_attempts:
                exhausted = True
                break
            trial = {k: v for k, v in files.items() if k != name}
            result = await executor.run(trial, check)
            attempts += 1
            if diagnostic(result) == first:
                files = trial
                removed.append(name)
                changed = True
                break
        if exhausted or not changed:
            break
    reduced = dict(contract, files=files)
    reduced["digest"] = hashlib.sha256(
        json.dumps(reduced, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    return {
        "source_digest": bundle["digest"],
        "bundle": reduced,
        "attempts": attempts,
        "removed_files": removed,
        "budget_exhausted": exhausted,
        "diagnostic": first,
        "status": "file_reduced" if removed else "unchanged",
        "minimality_proven": False,
    }


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path, help="one captured reproduction object")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--max-attempts", type=int, default=32)
    args = parser.parse_args()
    if args.out.exists():
        raise FileExistsError(args.out)
    bundle = json.loads(args.bundle.read_text())
    executor = PythonExecutor(
        backend=bundle["backend"], image=bundle["image"], timeout=bundle["timeout"]
    )
    if executor.backend not in ("docker", "macos") or not executor.available():
        raise ValueError("recorded isolated backend unavailable")
    result = await reduce_files(bundle, executor, max_attempts=args.max_attempts)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")


if __name__ == "__main__":
    asyncio.run(main())
