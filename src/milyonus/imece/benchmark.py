"""Reproducible İmece benchmark with a held-out, executable final oracle.

Generated gate tests and blind approval are not ground truth: the fixed oracle
below is never placed in an agent briefing. Results separate acceptance from
verified success, and unavailable cost is never reported as zero.
"""

from __future__ import annotations

import json
import math
import random
import time
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from milyonus.imece.agents import AgentFn
from milyonus.imece.execution import PythonExecutor, python_files
from milyonus.imece.journal import AgentJournal
from milyonus.imece.orchestrator import Imece, ImeceSettings
from milyonus.imece.schedule import trial_coordinates


@dataclass(frozen=True)
class BenchmarkTask:
    id: str
    request: str
    oracle: str
    cases: tuple[dict[str, Any], ...] = ()


def trial_identity(task, repeat, settings, run_identity, seed) -> dict:
    """Shared frozen identity for journal dispatch binding and CLI recovery."""
    return {
        "run": run_identity,
        "task": asdict(task),
        "repeat": repeat,
        "settings": asdict(settings),
        "seed": seed,
    }


def _matches(actual: Any, expected: Any) -> bool:
    if isinstance(expected, bool) or isinstance(actual, bool):
        return actual is expected
    if isinstance(expected, list):
        return (
            isinstance(actual, list)
            and len(actual) == len(expected)
            and all(_matches(a, b) for a, b in zip(actual, expected, strict=True))
        )
    if isinstance(expected, dict):
        return (
            isinstance(actual, dict)
            and actual.keys() == expected.keys()
            and all(_matches(actual[k], v) for k, v in expected.items())
        )
    return actual == expected


async def _score_artifact(executor: PythonExecutor, task: BenchmarkTask, deliverable: str):
    files = python_files(deliverable)
    if not task.cases:
        return (
            False,
            "assertion-only oracle cannot certify untrusted candidate code; host cases required",
        )
    # Send inputs only. Untrusted Python can exit(0), shadow imports or inspect
    # the driver, so assertions inside its own interpreter cannot certify success.
    inputs = json.dumps([c["input"] for c in task.cases], allow_nan=False)
    driver = (
        "import json\nfrom solution import solve\n"
        f"values = json.loads({inputs!r})\n"
        "answers = []\nfor value in values:\n"
        " answers.append(json.dumps([solve(value), value], allow_nan=False))\n"
        "print(json.dumps(answers))\n"
    )
    result = await executor.run(files, driver)
    if not result.passed:
        return False, result.output
    if result.output_truncated:
        return False, "sandbox result output was truncated"
    try:
        answers = json.loads(result.output)
        if not isinstance(answers, list) or len(answers) != len(task.cases):
            return False, "incomplete result set"
        for index, (answer, case) in enumerate(zip(answers, task.cases, strict=True)):
            actual = json.loads(answer)
            if not _matches(actual, [case["expected"], case["input"]]):
                return False, f"incorrect result or modified input in case {index}"
    except (ValueError, TypeError, RecursionError):
        return False, "invalid sandbox result encoding"
    return True, ""


TASKS = (
    BenchmarkTask(
        "clamp",
        "Deliver solution.py containing clamp(value, low, high). All inputs are integers. "
        "Return low when value<low, high when value>high, otherwise value. "
        "Raise ValueError when low>high. Standard library only; no I/O, network, services "
        "or third party dependencies. Include a brief explanation and named code fence "
        "```python file=solution.py. This is a purely local coding exercise; no deployment.",
        "from solution import clamp\n"
        "for low in range(-4,5):\n"
        " for high in range(low,5):\n"
        "  for value in range(-8,9):\n"
        "   assert clamp(value,low,high)==max(low,min(value,high))\n"
        "try:\n clamp(0,2,1)\nexcept ValueError:\n pass\nelse:\n raise AssertionError('reversed bounds accepted')\n",
    ),
    BenchmarkTask(
        "merge_intervals",
        "Deliver solution.py with merge_intervals(intervals). Input is a list of integer "
        "(start,end) pairs with start<=end. Return a sorted list of tuples with overlapping "
        "or touching intervals merged. Empty input returns []. Do not mutate input. "
        "Standard library only, no I/O or deployment. Include a brief explanation and "
        "a named code fence ```python file=solution.py.",
        "from solution import merge_intervals\n"
        "assert merge_intervals([])==[]\n"
        "assert merge_intervals([(1,3),(3,7),(9,10)])==[(1,7),(9,10)]\n"
        "assert merge_intervals([(5,5),(1,9),(2,3)])==[(1,9)]\n"
        "assert merge_intervals([(-7,-3),(-4,0),(2,2)])==[(-7,0),(2,2)]\n"
        "a=[(8,9),(1,4),(2,6)]; saved=list(a)\n"
        "assert merge_intervals(a)==[(1,6),(8,9)]\nassert a==saved\n",
    ),
    BenchmarkTask(
        "iban_tr",
        "Deliver solution.py with is_valid_tr_iban(value). Return bool; accept only strings. "
        "Remove ASCII spaces, uppercase ASCII letters, then require TR followed by exactly "
        "24 ASCII digits (26 total chars). Apply ISO 13616 mod97: move first4 chars to end, "
        "convert A..Z to 10..35, remainder must equal1. Reject malformed inputs and nonstrings "
        "without raising. Do not impose extra bank-code/reserved-digit rules. Use a "
        "terminating streaming remainder algorithm. Standard library only, no network/I/O. "
        "Include explanation and named code fence ```python file=solution.py.",
        "from solution import is_valid_tr_iban as valid\n"
        "assert valid('TR330006100519786457841326') is True\n"
        "assert valid('tr33 0006 1005 1978 6457 8413 26') is True\n"
        "assert valid('TR330006100519786457841327') is False\n"
        "for v in [None,3,[],{},'', 'DE89370400440532013000','TR３３０００６１００５１９７８６４５７８４１３２６']:\n"
        " assert valid(v) is False\n"
        "for n in range(20):\n"
        " bban=str(n*123456789).zfill(22)\n"
        " check=98-int(bban+'292700')%97\n"
        " iban='TR'+str(check).zfill(2)+bban\n"
        " assert valid(iban) is True\n",
    ),
)


def _distribution(values: list[int | float | None]) -> dict[str, Any]:
    known = sorted(v for v in values if type(v) in (int, float) and math.isfinite(v) and v >= 0)
    complete = bool(values) and len(known) == len(values)

    def percentile(fraction):
        if not complete:
            return None
        position = fraction * (len(known) - 1)
        lo = int(position)
        hi = min(lo + 1, len(known) - 1)
        return known[lo] + (known[hi] - known[lo]) * (position - lo)

    return {
        "known_runs": len(known),
        "unknown_runs": len(values) - len(known),
        "min": known[0] if complete else None,
        "median": percentile(0.5),
        "p95": percentile(0.95),
        "max": known[-1] if complete else None,
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    unknown_usage = sum(r.get("unknown_usage_calls", 0) for r in rows)
    accepted = sum(r["status"] == "accepted" for r in rows)
    verified = sum(r["status"] == "accepted" and r["oracle_passed"] for r in rows)
    costs_known = bool(rows) and all(r.get("cost_usd") is not None for r in rows)
    cost = sum(r["cost_usd"] for r in rows) if costs_known else None
    # Calibration unit is one run: mean synthesis confidence vs held-out success.
    # No double-counting correlated decisions as independent observations.
    buckets: dict[int, list[tuple[float, bool]]] = {}
    for r in rows:
        if r.get("confidence") is not None:
            confidence = r["confidence"]
            buckets.setdefault(min(9, int(confidence * 10)), []).append(
                (confidence, r["status"] == "accepted" and r["oracle_passed"])
            )
    samples = sum(len(b) for b in buckets.values())
    ece = (
        sum(
            abs(sum(c for c, _ in b) / len(b) - sum(ok for _, ok in b) / len(b)) * len(b) / samples
            for b in buckets.values()
        )
        if samples
        else None
    )
    total_tokens = (
        sum(r["tokens"] for r in rows)
        if n and not unknown_usage and all(r.get("tokens") is not None for r in rows)
        else None
    )
    return {
        "runs": n,
        "status_counts": dict(sorted(Counter(r["status"] for r in rows).items())),
        "distributions": {
            "seconds": _distribution([r.get("seconds", r.get("elapsed_s")) for r in rows]),
            "tokens": _distribution(
                [r.get("tokens") if not r.get("unknown_usage_calls") else None for r in rows]
            ),
            "cost_usd": _distribution([r.get("cost_usd") for r in rows]),
        },
        "gate_failure_classes": dict(
            sorted(
                Counter(
                    check.get("failure_class") or "unknown"
                    for r in rows
                    for gate in (r.get("report") or {}).get("gate_reports", [])
                    if gate.get("verification", "").startswith("python:")
                    for check in gate.get("test_results", [])
                    if check.get("passed") is False
                ).items()
            )
        ),
        "accepted": accepted,
        "verified_successes": verified,
        "accepted_deliverable_rate": accepted / n if n else None,
        "verified_success_rate": verified / n if n else None,
        "false_accepts": sum(r["status"] == "accepted" and not r["oracle_passed"] for r in rows),
        "total_tokens": total_tokens,
        "tokens_per_verified_success": total_tokens / verified
        if total_tokens is not None and verified
        else None,
        "observed_tokens": sum(r.get("observed_tokens", r.get("tokens")) or 0 for r in rows),
        "unknown_token_runs": sum(
            r.get("tokens") is None or bool(r.get("unknown_usage_calls")) for r in rows
        ),
        "cost_usd": cost,
        "cost_estimated": any(r.get("cost_estimated", True) for r in rows),
        "cost_per_accepted_usd": cost / accepted if cost is not None and accepted else None,
        "cost_per_verified_success_usd": cost / verified if cost is not None and verified else None,
        "calibration_ece": ece,
        "calibration_samples": samples,
    }


async def run_benchmark(
    agent_fn: AgentFn,
    settings: ImeceSettings,
    *,
    tasks: tuple[BenchmarkTask, ...] = TASKS,
    repeats: int = 1,
    source: str = "unspecified",
    on_phase=None,
    seed: int = 0,
    on_row=None,
    on_trial=None,
    can_begin_trial=None,
    capture_reproductions: bool = False,
    should_stop=None,
    completed_rows=None,
    journal_dir: Path | None = None,
    run_identity: dict | None = None,
    trial_order: str = "task-major",
) -> dict[str, Any]:
    if settings.verification != "python":
        raise ValueError("benchmark requires verification='python'")
    if repeats < 1:
        raise ValueError("repeats must be positive")
    executor = PythonExecutor(
        backend=settings.sandbox_backend,
        image=settings.sandbox_image,
        timeout=settings.test_timeout,
    )
    rows = list(completed_rows or [])
    completed = {(r["task"], r["repeat"]) for r in rows}
    by_id = {task.id: task for task in tasks}
    for task_id, repeat in trial_coordinates([t.id for t in tasks], repeats, order=trial_order):
        task = by_id[task_id]
        if (task.id, repeat) in completed:
            continue
        if should_stop and should_stop():
            break
        if can_begin_trial and not can_begin_trial(task.id, repeat):
            continue
        if on_trial:
            on_trial(task.id, repeat)
        started = time.monotonic()
        journal = (
            AgentJournal(
                journal_dir / f"{task.id}-{repeat}.sqlite",
                agent_fn,
                identity=trial_identity(task, repeat, settings, run_identity, seed),
            )
            if journal_dir
            else None
        )

        def phase(name, journal=journal):
            if journal:
                journal.phase(name)
            if on_phase:
                on_phase(name)

        try:
            result = await Imece(
                journal or agent_fn,
                settings,
                on_phase=phase,
                should_stop=should_stop,
                capture_reproductions=capture_reproductions,
                rng=random.Random(f"{seed}:{task.id}:{repeat}"),
            ).run(task.request)
        finally:
            if journal:
                journal.close()
        try:
            passed, output = await _score_artifact(executor, task, result.deliverable)
        except ValueError as exc:
            passed, output = False, str(exc)
        confidence = next(
            (
                d.confidence
                for d in reversed(result.decisions)
                if d.request_kind == "synthesis" and d.choice is not None
            ),
            None,
        )
        rows.append(
            {
                "task": task.id,
                "repeat": repeat,
                "status": result.status,
                "oracle_passed": passed,
                "oracle_output": output,
                "seconds": round(time.monotonic() - started, 3),
                "tokens": result.tokens,
                "unknown_usage_calls": result.unknown_usage_calls,
                "cost_usd": result.cost_usd,
                "cost_estimated": result.cost_estimated,
                "confidence": confidence,
                "report": result.to_dict(),
            }
        )
        if on_row:
            on_row(rows[-1])
    return {
        "schema_version": 1,
        "source": source,
        "settings": asdict(settings),
        "summary": summarize(rows),
        "runs": rows,
    }
