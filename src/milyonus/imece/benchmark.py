"""Reproducible İmece benchmark with a held-out, executable final oracle.

Generated gate tests and blind approval are not ground truth: the fixed oracle
below is never placed in an agent briefing. Results separate acceptance from
verified success, and unavailable cost is never reported as zero.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from typing import Any

from milyonus.imece.agents import AgentFn
from milyonus.imece.execution import PythonExecutor, python_files
from milyonus.imece.orchestrator import Imece, ImeceSettings


@dataclass(frozen=True)
class BenchmarkTask:
    id: str
    request: str
    oracle: str


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


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(rows)
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
    return {
        "runs": n,
        "accepted": accepted,
        "verified_successes": verified,
        "accepted_deliverable_rate": accepted / n if n else None,
        "verified_success_rate": verified / n if n else None,
        "false_accepts": sum(r["status"] == "accepted" and not r["oracle_passed"] for r in rows),
        "total_tokens": sum(r["tokens"] for r in rows),
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
    rows = []
    for task in tasks:
        for repeat in range(repeats):
            started = time.monotonic()
            result = await Imece(agent_fn, settings, on_phase=on_phase).run(task.request)
            try:
                oracle = await executor.run(python_files(result.deliverable), task.oracle)
                passed, output = oracle.passed, oracle.output
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
                    "cost_usd": result.cost_usd,
                    "cost_estimated": result.cost_estimated,
                    "confidence": confidence,
                    "report": result.to_dict(),
                }
            )
    return {
        "schema_version": 1,
        "source": source,
        "settings": asdict(settings),
        "summary": summarize(rows),
        "runs": rows,
    }
