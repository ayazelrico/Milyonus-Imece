"""Hermes adapter for the frozen İmece task suite.

Runs the same public contracts through an external Hermes-compatible CLI
(`HERMES_CMD`, default `hermes`) so results can be scored with the same
withheld oracle. Cross-engine observations do not satisfy the same-engine 5X gate.

This does not ship Hermes. Without a CLI on PATH, `prepare` still emits a
protocol-compatible report skeleton and `run` fails closed.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import platform
import shlex
import shutil
import signal
import tempfile
import time
from pathlib import Path

from evals.imece.dataset import load_suite
from evals.imece.protocol import digest, manifest
from milyonus.imece.antigravity import _read_bounded_stream
from milyonus.imece.benchmark import _score_artifact
from milyonus.imece.codex import oracle_guard
from milyonus.imece.execution import PythonExecutor
from milyonus.imece.orchestrator import ImeceSettings
from milyonus.imece.schedule import trial_coordinates


def hermes_cmd() -> list[str]:
    raw = os.environ.get("HERMES_CMD", "hermes").strip()
    return shlex.split(raw) if raw else ["hermes"]


def available() -> bool:
    cmd = hermes_cmd()
    return bool(cmd) and shutil.which(cmd[0]) is not None


async def _ask_hermes(prompt: str, *, model: str, timeout: float) -> str:
    cmd = hermes_cmd() + ["run", "--model", model, "--prompt", prompt]
    guard = oracle_guard((Path(__file__).resolve().parents[2],))
    with tempfile.TemporaryDirectory(prefix="imece-hermes-") as cwd:
        proc = await asyncio.create_subprocess_exec(
            *guard,
            *cmd,
            cwd=cwd,
            start_new_session=True,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            async with asyncio.timeout(timeout):
                assert proc.stdout is not None
                out = await _read_bounded_stream(proc.stdout, 4 * 1024 * 1024)
                if await proc.wait() != 0:
                    return ""
                return bytes(out).decode("utf-8", "replace")
        except TimeoutError:
            return ""
        finally:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(proc.pid, signal.SIGKILL)
            await proc.wait()


def build_manifest(
    *,
    seed: int,
    repeats: int,
    model: str,
    revision: str,
    suite: str = "core-v1",
    sandbox_backend: str = "macos",
    test_timeout: float = 10.0,
    image: str = "python:3.12-slim",
    trial_order: str = "task-major",
) -> dict:
    tasks = load_suite(suite)
    settings = ImeceSettings(
        max_tokens=50_000,
        max_rounds=1,
        test_timeout=test_timeout,
        sandbox_backend=sandbox_backend,
        sandbox_image=image,
        verification="python",
    )
    return manifest(
        tasks=tasks,
        settings=settings,
        models={
            "pool": model,
            "approval": model,
            "council:correctness": model,
            "council:risk": model,
            "council:user_impact": model,
            "council:cost_speed": model,
            "council:devils_advocate": model,
        },
        runtime={
            "engine": "hermes",
            "backend": sandbox_backend,
            "image": image,
            "platform": platform.platform(),
            "python": platform.python_version(),
            "generator_timeout_seconds": 180,
            "generator_token_limit_enforced": False,
            "suite": suite,
            "adapter": "evals.hermes.adapter",
        },
        seed=seed,
        repeats=repeats,
        revision=revision,
        trial_order=trial_order,
    )


async def run_suite(
    *,
    out: Path,
    model: str,
    seed: int = 0,
    repeats: int = 5,
    revision: str = "hermes-adapter",
    prepare_only: bool = False,
    suite: str = "core-v1",
    sandbox_backend: str = "macos",
    test_timeout: float = 10.0,
    trial_order: str = "task-major",
) -> dict:
    tasks = load_suite(suite)
    image = os.environ.get("MILYONUS_HERMES_IMAGE", "python:3.12-slim")
    frozen = build_manifest(
        seed=seed,
        repeats=repeats,
        model=model,
        revision=revision,
        sandbox_backend=sandbox_backend,
        image=image,
        suite=suite,
        test_timeout=test_timeout,
        trial_order=trial_order,
    )
    report: dict = {
        "manifest": frozen,
        "source": "hermes",
        "adapter": "hermes",
        "independence_warnings": [
            "Hermes adapter uses a single model identity for all seats; "
            "not evidence of multi-provider council independence."
        ],
        "ledger": None,
        "runs": [],
    }
    if prepare_only or not available():
        report["prepare"] = {
            "available": available(),
            "cmd": hermes_cmd(),
            "note": "No model calls made. Install/configure Hermes and re-run without --prepare.",
        }
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2) + "\n")
        return report

    executor = PythonExecutor(backend=sandbox_backend, image=image, timeout=test_timeout)  # type: ignore[arg-type]
    by_id = {task.id: task for task in tasks}
    for task_id, repeat in trial_coordinates([t.id for t in tasks], repeats, order=trial_order):
        task = by_id[task_id]
        started = time.monotonic()
        artifact = await _ask_hermes(task.request, model=model, timeout=180)
        try:
            passed, _output = await _score_artifact(executor, task, artifact)
        except ValueError as exc:
            passed, _output = False, str(exc)
        report["runs"].append(
            {
                "task": task.id,
                "repeat": repeat,
                "status": "accepted" if artifact.strip() else "error",
                "oracle_passed": bool(passed),
                "oracle_output": _output,
                "tokens": None,
                "cost_usd": None,
                "confidence": None,
                "elapsed_s": round(time.monotonic() - started, 3),
            }
        )
    report["report_hash"] = digest(report)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + "\n")
    return report


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--model", required=True)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--repeats", type=int, default=5)
    p.add_argument("--trial-order", choices=("task-major", "repeat-major"), default="repeat-major")
    p.add_argument("--revision", default="hermes-adapter")
    p.add_argument("--suite", choices=("core-v1", "core-v2"), default="core-v1")
    p.add_argument("--prepare", action="store_true")
    p.add_argument("--test-timeout", type=float, default=10.0)
    p.add_argument("--sandbox-backend", default="macos", choices=("docker", "macos"))
    args = p.parse_args()
    report = asyncio.run(
        run_suite(
            out=args.out,
            model=args.model,
            seed=args.seed,
            repeats=args.repeats,
            trial_order=args.trial_order,
            revision=args.revision,
            prepare_only=args.prepare,
            sandbox_backend=args.sandbox_backend,
            suite=args.suite,
            test_timeout=args.test_timeout,
        )
    )
    print(
        json.dumps(
            {"runs": len(report.get("runs", [])), "prepare": report.get("prepare")},
            indent=2,
        )
    )
    return 0 if args.prepare or available() else 2


if __name__ == "__main__":
    raise SystemExit(main())
