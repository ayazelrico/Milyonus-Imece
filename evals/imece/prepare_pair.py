"""Prepare a Codex baseline/candidate pair locally; never dispatch model calls."""

from __future__ import annotations

import argparse
import asyncio
import ctypes
import errno
import json
import os
import sys
import tempfile
from pathlib import Path


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--engine", choices=("codex",), default="codex")
    parser.add_argument("--model", required=True, help="explicit CLI model for every seat")
    parser.add_argument("--seat-model", action="append", default=[], metavar="SEAT=MODEL")
    parser.add_argument("--declared-budget-usd")
    parser.add_argument("--failure-families", type=Path)
    parser.add_argument("--agents", type=int, default=17)
    parser.add_argument("--max-tokens", type=int, default=250_000)
    parser.add_argument("--candidate-compact-cli-instructions", action="store_true")
    parser.add_argument("--out-dir", required=True, type=Path, help="must not already exist")
    parser.add_argument("--baseline-config", required=True, type=Path)
    parser.add_argument("--candidate-config", required=True, type=Path)
    parser.add_argument("--suite", choices=("smoke", "core-v1", "core-v2"), default="core-v2")
    parser.add_argument("--task", action="append", help="same explicit task subset for both arms")
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument(
        "--trial-order", choices=("task-major", "repeat-major"), default="repeat-major"
    )
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--backend", choices=("docker", "macos"), default="docker")
    parser.add_argument("--image")
    parser.add_argument("--max-cli-calls", type=int)
    parser.add_argument("--executable", help="local Codex executable for help/version validation")
    return parser


def rename_exclusive(source: Path, destination: Path) -> None:
    """Publish once, atomically refusing even an empty concurrent destination."""
    libc = ctypes.CDLL(None, use_errno=True)
    if sys.platform == "darwin":
        rename = libc.renamex_np
        rename.argtypes = (ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint)
        arguments = (os.fsencode(source), os.fsencode(destination), 0x00000004)  # RENAME_EXCL
    elif sys.platform == "linux":
        rename = libc.renameat2
        rename.argtypes = (
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        )
        arguments = (-100, os.fsencode(source), -100, os.fsencode(destination), 1)
    else:
        raise OSError(errno.ENOTSUP, "exclusive directory rename unsupported")
    rename.restype = ctypes.c_int
    if rename(*arguments) != 0:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code), str(destination))


def validate_prepared(report: dict) -> None:
    # validate_report requires completed trials; preparation requires the opposite.
    from evals.imece.protocol import digest, validate_rows

    frozen = report["manifest"]
    protocol = frozen["protocol"]
    if frozen["protocol_hash"] != digest(protocol):
        raise ValueError("prepared protocol hash mismatch")
    if (
        report.get("state") != "prepared"
        or report.get("source") != "codex"
        or report.get("engine") != "codex"
        or protocol["runtime"]["engine"] != "codex"
        or report.get("runs") != []
        or report.get("transcripts") != []
        or report.get("accounting", {}).get("cli_calls_reserved") != 0
        or report.get("ledger") is not None
        or report.get("models") != protocol["models"]
    ):
        raise ValueError("expected an empty, prepared Codex report with no calls")
    validate_rows(report["runs"], protocol)
    for field in ("revision", "implementation_hash"):
        if not isinstance(frozen.get(field), str) or not frozen[field]:
            raise ValueError(f"missing implementation identity: {field}")


async def main(args) -> int:
    if not args.model.strip() or args.repeats < 1:
        raise ValueError("explicit nonempty model and positive repeats required")
    if args.max_cli_calls is not None and args.max_cli_calls < 1:
        raise ValueError("--max-cli-calls must be positive")
    # Resolve the parent only: resolving the final component would follow a symlink.
    output = args.out_dir.expanduser().absolute()
    output = output.parent.resolve() / output.name
    if os.path.lexists(output):
        raise FileExistsError(f"output directory already exists: {output}")
    for config in (args.baseline_config, args.candidate_config):
        if not config.is_file():
            raise ValueError(f"configuration must be an existing file: {config}")

    # Use the runner's parser and preparation branch rather than duplicating its
    # settings/model mapping, task selection, runtime discovery or report writer.
    from evals.imece import run
    from evals.imece.protocol import describe_treatments, digest

    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{output.name}.prepare-", dir=output.parent) as tmp:
        staging = Path(tmp) / "pair"
        staging.mkdir()
        reports = {}
        for role, config in (
            ("baseline", args.baseline_config),
            ("candidate", args.candidate_config),
        ):
            argv = [
                "--prepare",
                "--engine",
                "codex",
                "--model",
                args.model,
                "--config",
                str(config),
                "--out",
                str(staging / f"{role}.json"),
                "--suite",
                args.suite,
                "--repeats",
                str(args.repeats),
                "--seed",
                str(args.seed),
                "--backend",
                args.backend,
            ]
            for flag, value in (
                ("--image", args.image),
                ("--max-cli-calls", args.max_cli_calls),
                ("--executable", args.executable),
                ("--declared-budget-usd", args.declared_budget_usd),
                ("--failure-families", args.failure_families),
                ("--agents", args.agents),
                ("--max-tokens", args.max_tokens),
                ("--trial-order", args.trial_order),
            ):
                if value is not None:
                    argv.extend((flag, str(value)))
            for override in args.seat_model:
                argv.extend(("--seat-model", override))
            for task in args.task or []:
                argv.extend(("--task", task))
            if role == "candidate" and args.candidate_compact_cli_instructions:
                argv.append("--compact-cli-instructions")
            prepared_args = run.make_parser().parse_args(argv)
            if await run.main(prepared_args) != 0:
                raise ValueError(f"{role} preparation failed")
            report = json.loads(prepared_args.out.read_text(encoding="utf-8"))
            validate_prepared(report)
            reports[role] = report

        baseline, candidate = (reports[role]["manifest"] for role in ("baseline", "candidate"))
        if (
            baseline["protocol_hash"] != candidate["protocol_hash"]
            or baseline["protocol"] != candidate["protocol"]
        ):
            raise ValueError("baseline and candidate protocols differ")
        differences = {
            key: {
                "baseline": baseline["settings"].get(key),
                "candidate": candidate["settings"].get(key),
            }
            for key in sorted(baseline["settings"].keys() | candidate["settings"].keys())
            if baseline["settings"].get(key) != candidate["settings"].get(key)
        }
        prompt_difference = baseline["cli_prompt_treatment"] != candidate["cli_prompt_treatment"]
        if not differences and not prompt_difference:
            raise ValueError("baseline and candidate settings are identical")
        adaptive_pair = (
            baseline["settings"]["adaptive_production"] is False
            and candidate["settings"]["adaptive_production"] is True
        )
        same_adaptive = (
            baseline["settings"]["adaptive_production"]
            == candidate["settings"]["adaptive_production"]
        )
        if not adaptive_pair and not (same_adaptive and prompt_difference):
            raise ValueError(
                "expected adaptive false/true pair or an explicit CLI prompt treatment"
            )
        if any(baseline[key] != candidate[key] for key in ("revision", "implementation_hash")):
            raise ValueError("implementation changed during pair preparation")
        pair = {
            "schema_version": 1,
            "state": "prepared",
            "engine": "codex",
            "protocol_hash": baseline["protocol_hash"],
            "settings_differences": differences,
            "treatments": describe_treatments(baseline, candidate),
            "cli_prompt_treatments": {
                role: report["manifest"]["cli_prompt_treatment"] for role, report in reports.items()
            },
            "reports": {
                role: {
                    "path": f"{role}.json",
                    "report_hash": digest(report),
                    "protocol_hash": report["manifest"]["protocol_hash"],
                    "revision": report["manifest"]["revision"],
                    "implementation_hash": report["manifest"]["implementation_hash"],
                }
                for role, report in reports.items()
            },
            "model_calls": 0,
            "result": None,
            "note": "Preparation only; no trials executed, no measured gain or 5X result.",
        }
        run.atomic_write(staging / "pair.json", pair)
        rename_exclusive(staging, output)
    print(f"settings differences: {json.dumps(differences, sort_keys=True)}")
    print(f"prepared pair: {output}; no model calls; no measured result")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(make_parser().parse_args())))
