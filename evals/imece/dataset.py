"""Versioned offline task suite. Oracle cases are never sent to the agent.

These are constrained Python exercises, not a representative production corpus.
Categories denote the contract being exercised, not external service access.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

from milyonus.imece.benchmark import BenchmarkTask

DATA = Path(__file__).with_name("data") / "core-v1.json"
SUITES = ("core-v1", "core-v2", "core-v3")
JSON_INTERFACE = (
    " Result interface: return JSON-compatible values (null/None, bool, int, finite float, "
    "string, lists, or dictionaries with string keys); tuples may represent arrays. "
    "Do not return Fraction, Decimal, sets, generators, or custom objects. "
    "For mean or division results, use standard Python binary floating-point arithmetic; "
    "exact rational arithmetic is not required. Valid inputs keep floating-point "
    "calculations finite and within the representable range."
)


def load_tasks(path: Path = DATA) -> tuple[BenchmarkTask, ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise ValueError("unsupported task suite schema")
    tasks = []
    seen = set()
    for row in payload["tasks"]:
        if row["id"] in seen or not row["cases"]:
            raise ValueError("duplicate task ID or empty oracle")
        seen.add(row["id"])
        cases = row["cases"]
        oracle = (
            "import json, copy\nfrom solution import solve\n"
            f"cases = json.loads({json.dumps(cases, ensure_ascii=True)!r})\n"
            "for case in cases:\n"
            " value = copy.deepcopy(case['input'])\n"
            " actual = solve(value)\n"
            " assert actual == case['expected'], (case['input'], actual, case['expected'])\n"
            " assert value == case['input'], 'input was mutated'\n"
        )
        tasks.append(
            BenchmarkTask(
                row["id"],
                "Deliver solution.py containing solve(value). "
                + row["contract"]
                + " Do not mutate the input. Inputs follow the stated contract; "
                "no additional validation is required. Standard library only, no external "
                "I/O or deployment. Include a named code fence ```python file=solution.py.",
                oracle,
                tuple(cases),
            )
        )
    return tuple(tasks)


def suite_digest(path: Path = DATA) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_suite(name: str) -> tuple[BenchmarkTask, ...]:
    """v2 adds broken starters; v3 declares the host scorer's JSON/numeric interface.

    Keep v1/v2 requests unchanged: existing frozen reports retain their original
    contracts, including the interface omission discovered in the live v2 matrix.
    """
    tasks = load_tasks()
    if name == "core-v1":
        return tasks
    if name not in SUITES:
        raise ValueError(f"unknown core suite: {name}")
    starters = json.loads(DATA.with_name("core-v2-starters.json").read_text(encoding="utf-8"))
    expected = {t.id for t in tasks if t.id.startswith("fix_")}
    if set(starters) != expected or not all(
        isinstance(s, str) and s.strip() for s in starters.values()
    ):
        raise ValueError("incomplete v2 starter corpus")
    tasks = tuple(
        replace(
            t,
            request=t.request
            + "\n\nRepair this existing implementation:\n```python\n"
            + starters[t.id]
            + "```",
        )
        if t.id in starters
        else t
        for t in tasks
    )
    if name == "core-v3":
        return tuple(replace(t, request=t.request + JSON_INTERFACE) for t in tasks)
    return tasks
