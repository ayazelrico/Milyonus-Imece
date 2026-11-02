"""The three independent gates. None of them draws agents from the imece pool.

Kapı 1 — framing:  independent cells re-formulate the problem; the success
                   criteria are fixed here and frozen for Kapı 3.
Kapı 2 — reality:  tests (designed apart from the builders), red team, evidence
                   audit and compliance. A candidate that fails never reaches IRADE.
Kapı 3 — approval: sees ONLY the original request, the frozen criteria, the
                   deliverable and the evidence package — never the process.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from milyonus.imece.agents import AgentSpec, Swarm, clip, parse_json
from milyonus.imece.execution import PythonExecutor, python_files


class GateError(ValueError):
    """There was not enough valid independent evidence to proceed."""


FRAMING_LENSES = (
    "literal: what exactly was asked",
    "root cause: is this the real problem or a symptom of one?",
    "user outcome: what would make the requester's situation actually better",
    "constraints and risk: physical, legal, budget, time, irreversible effects",
    "minimal scope: the smallest problem whose solution would satisfy the request",
)
SEVERITIES = ("low", "medium", "high", "critical")


def assign[T](n_agents: int, items: Sequence[T]) -> list[list[T]]:
    """Spread items over agents. More agents than items -> several agents per
    item (independent repeats); fewer -> each agent takes several items."""
    if not items or n_agents <= 0:
        return []
    if n_agents >= len(items):
        return [[items[i % len(items)]] for i in range(n_agents)]
    groups: list[list[T]] = [[] for _ in range(n_agents)]
    for i, item in enumerate(items):
        groups[i % n_agents].append(item)
    return groups


def _str_list(v: Any, limit: int = 12) -> list[str]:
    if not isinstance(v, list):
        return []
    return [str(x).strip() for x in v if str(x).strip()][:limit]


# ── Kapı 1 ─────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Frame:
    request: str
    problem: str
    success_criteria: tuple[str, ...]
    out_of_scope: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    disciplines: tuple[str, ...] = ()
    divergences: tuple[str, ...] = ()

    def brief(self) -> str:
        parts = [f"# Original request\n{self.request}", f"# Framed problem\n{self.problem}"]
        parts.append(
            "# Success criteria (frozen)\n" + "\n".join(f"- {c}" for c in self.success_criteria)
        )
        if self.out_of_scope:
            parts.append("# Out of scope\n" + "\n".join(f"- {c}" for c in self.out_of_scope))
        if self.assumptions:
            parts.append(
                "# Assumptions (if one is wrong, everything may collapse)\n"
                + "\n".join(f"- {c}" for c in self.assumptions)
            )
        return "\n\n".join(parts)


_FRAME_SCHEMA = {
    "problem": "one paragraph re-formulation",
    "success_criteria": ["measurable criterion"],
    "out_of_scope": ["..."],
    "assumptions": ["..."],
    "disciplines": ["expertise needed"],
}


async def frame(swarm: Swarm, request: str, n_agents: int) -> Frame:
    specs = [
        AgentSpec(
            block="framing",
            role=f"framing cell {i % len(FRAMING_LENSES) + 1}",
            seat="framing",
            goal=(
                "Re-formulate this problem independently through your lens: "
                f"{FRAMING_LENSES[i % len(FRAMING_LENSES)]}. Define how success will be measured."
            ),
            context=f"# Request\n{request}",
            success_criteria=["Reply with one JSON object: " + json.dumps(_FRAME_SCHEMA)],
            forbidden=["Do not solve the problem — only frame it."],
        )
        for i in range(n_agents)
    ]
    frames = [parse_json(t) for t in await swarm.run(specs)]
    frames = [f for f in frames if f]
    if len(frames) <= n_agents / 2:
        raise GateError("framing quorum not met")
    listing = "\n\n".join(
        f"## Cell {i + 1}\n{json.dumps(f, ensure_ascii=False)}" for i, f in enumerate(frames)
    )
    synth_schema = {
        **_FRAME_SCHEMA,
        "divergences": ["where the cells disagreed and why it matters"],
    }
    [synth_text] = await swarm.run(
        [
            AgentSpec(
                block="framing",
                role="framing synthesizer",
                seat="framing",
                goal=(
                    "Merge the independent framings into one. Surface every real disagreement "
                    "between cells instead of hiding it. Success criteria must be checkable."
                ),
                context=f"# Request\n{request}\n\n# Independent framings\n{listing or '(none parsed)'}",
                success_criteria=["Reply with one JSON object: " + json.dumps(synth_schema)],
            )
        ]
    )
    data = parse_json(synth_text) or (frames[0] if frames else {})
    criteria = tuple(_str_list(data.get("success_criteria"))) or (
        "The deliverable directly and completely answers the original request.",
    )
    return Frame(
        request=request,
        problem=str(data.get("problem") or request),
        success_criteria=criteria,
        out_of_scope=tuple(_str_list(data.get("out_of_scope"))),
        assumptions=tuple(_str_list(data.get("assumptions"))),
        disciplines=tuple(_str_list(data.get("disciplines"), 8)),
        divergences=tuple(_str_list(data.get("divergences"))),
    )


# ── Kapı 2 ─────────────────────────────────────────────────────────────────
@dataclass(slots=True)
class TestCase:
    id: str
    check: str
    how: str = ""
    python: str = ""


@dataclass
class Finding:
    source: str  # red_team / evidence_audit / compliance / test
    severity: str
    text: str
    needs_human: bool = False


@dataclass
class GateReport:
    candidate_id: str
    pass_rate: float = 0.0
    findings: list[Finding] = field(default_factory=list)
    passed: bool = False
    verification: str = "model"
    test_results: list[dict[str, Any]] = field(default_factory=list)

    def worst(self) -> str:
        ranks = [SEVERITIES.index(f.severity) for f in self.findings if f.severity in SEVERITIES]
        return SEVERITIES[max(ranks)] if ranks else "none"

    def needs_human(self) -> bool:
        """Irreversibility flags count from the compliance block (whose job it
        is) or from a high/critical finding — not from any low-severity aside."""
        return any(
            f.needs_human and (f.source == "compliance" or f.severity in ("high", "critical"))
            for f in self.findings
        )

    def evidence(self) -> str:
        lines = [
            f"verification: {self.verification}",
            f"test pass rate: {self.pass_rate:.0%}",
            f"worst finding: {self.worst()}",
        ]
        lines += [f"- [{f.source}/{f.severity}] {clip(f.text, 300)}" for f in self.findings[:12]]
        lines += [
            f"- FAILED {r['test']}: {clip(str(r.get('output', '')), 1200)}"
            for r in self.test_results
            if not r["passed"]
        ]
        return "\n".join(lines)


async def design_tests(
    swarm: Swarm, fr: Frame, n_agents: int, *, cap: int = 12, executable: bool = False
) -> list[TestCase]:
    """Test oracle design. Runs from the frame alone — it never sees a candidate."""
    specs = [
        AgentSpec(
            block="test_design",
            role="test designer",
            seat="test_design",
            goal=(
                "Design tests that decide whether ANY solution meets the success criteria. "
                "Say what 'correct' means and how to check it — include edge cases and at least "
                "one test that would catch a solution that only looks right."
                + (
                    " Each test MUST include a standalone Python script in the 'python' field: "
                    "use assertions and the standard library only, import the requested API from solution. "
                    "Do not implement the solution, catch assertion failures, or use pytest. "
                    "Each script is executed separately in an isolated interpreter."
                    if executable
                    else ""
                )
            ),
            context=fr.brief(),
            success_criteria=[
                'Reply with one JSON object: {"tests": [{"check": "...", "how": "...", "python": "script (if requested)"}]}'
            ],
        )
        for _ in range(n_agents)
    ]
    seen: set[str] = set()
    tests: list[TestCase] = []
    for text in await swarm.run(specs):
        for t in (parse_json(text) or {}).get("tests") or []:
            if not isinstance(t, dict):
                continue
            check = str(t.get("check", "")).strip()
            key = check.lower()
            if check and key not in seen:
                seen.add(key)
                tests.append(
                    TestCase(
                        f"T{len(tests) + 1}",
                        check,
                        str(t.get("how", "")),
                        str(t.get("python") or ""),
                    )
                )
    if not tests:
        tests = [TestCase(f"C{i + 1}", c) for i, c in enumerate(fr.success_criteria)]
    return tests[:cap]


def _candidate_block(cands: Sequence[Any]) -> str:
    return "\n\n".join(f"## Candidate {c.id}\n{c.solution}" for c in cands)


async def reality(
    swarm: Swarm,
    fr: Frame,
    candidates: Sequence[Any],
    tests: Sequence[TestCase],
    *,
    test_exec: int,
    red_team: int,
    evidence_audit: int,
    compliance: int,
    pass_threshold: float,
    executor: PythonExecutor | None = None,
) -> dict[str, GateReport]:
    """Run Kapı 2 on candidates (objects with `.id` and `.solution`)."""
    reports = {c.id: GateReport(c.id) for c in candidates}
    test_list = "\n".join(f"- {t.id}: {t.check} ({t.how})" for t in tests)
    specs: list[AgentSpec] = []
    kinds: list[str] = []
    groups: list[list[Any]] = []

    for group in assign(test_exec if executor is None else 0, list(candidates)):
        kinds.append("test")
        groups.append(group)
        specs.append(
            AgentSpec(
                block="test_exec",
                role="test executor",
                seat="pool",
                goal="Run every test against every candidate below and record pass/fail honestly.",
                context=f"{fr.brief()}\n\n# Tests\n{test_list}\n\n# Candidates\n{_candidate_block(group)}",
                success_criteria=[
                    'Reply with one JSON object: {"results": [{"candidate": "id", '
                    '"test": "T1", "pass": true, "note": "..."}]}'
                ],
                use_tools=True,
            )
        )
    for block, n, goal in (
        (
            "red_team",
            red_team,
            "Attack these candidates: edge cases, overload, misuse, adversarial input, and "
            "'what if an assumption is false'. Every finding needs a reproduction. "
            "Distinguish contract failures from hypothetical assumption violations: "
            "out-of-scope inputs or excluded assumptions are informational (low), never critical. "
            "Critical means a demonstrated violation of a frozen success criterion within the stated input domain. "
            "Do not invent requirements, report correct behavior as a flaw, or demand extra validation. "
            "Return an empty findings list when there is no actual defect.",
        ),
        (
            "evidence_audit",
            evidence_audit,
            "Audit every claim: is it sourced, are numbers consistent, is anything hallucinated "
            "or statistically invalid? Classify evidence quality. "
            "Report defects only; verified claims do not need findings. "
            "Return an empty findings list when claims are supported.",
        ),
        (
            "compliance",
            compliance,
            "Check legal limits, ethical impact, privacy, dual-use misuse, and flag any "
            "irreversible action or decision that needs human approval.",
        ),
    ):
        for group in assign(n, list(candidates)):
            kinds.append(block)
            groups.append(group)
            specs.append(
                AgentSpec(
                    block=block,
                    role=block.replace("_", " "),
                    seat=block,
                    goal=goal,
                    context=f"{fr.brief()}\n\n# Candidates\n{_candidate_block(group)}",
                    success_criteria=[
                        'Reply with one JSON object: {"findings": [{"candidate": "id", '
                        '"severity": "low|medium|high|critical", "text": "...", '
                        '"needs_human": false}]}'
                        " Use exact candidate IDs from the briefing; at most 3 findings per candidate, each text under 500 characters. "
                        'No Markdown fences or prose outside the JSON. Valid clean report: {"findings": []}. '
                        "Do not include test code blocks inside text; give a concise reproduction and the violated criterion."
                    ],
                )
            )

    results = await swarm.run(specs)
    tallies: dict[str, list[bool]] = {c.id: [] for c in candidates}
    for kind, text, group in zip(kinds, results, groups, strict=True):
        data = parse_json(text)
        expected_ids = {c.id for c in group}
        if kind == "test":
            rows = data.get("results", []) if data else []
            seen: dict[tuple[str, str], list[bool]] = {}
            for r in rows if isinstance(rows, list) else []:
                if (
                    isinstance(r, dict)
                    and isinstance(r.get("candidate"), str)
                    and isinstance(r.get("test"), str)
                ):
                    key = (r["candidate"], r["test"])
                    seen.setdefault(key, []).append(r.get("pass") is True)
            # Missing, duplicate, string/number booleans cannot raise pass rate.
            for cid in expected_ids:
                for t in tests:
                    votes = seen.get((cid, t.id), [])
                    ok = len(votes) == 1 and votes[0]
                    tallies[cid].append(ok)
                    reports[cid].test_results.append(
                        {"test": t.id, "passed": ok, "source": "model"}
                    )
            continue
        findings = data.get("findings") if data else None
        valid = isinstance(findings, list) and all(
            isinstance(f, dict)
            and isinstance(f.get("candidate"), str)
            and f["candidate"] in expected_ids
            and f.get("severity") in SEVERITIES
            and isinstance(f.get("text"), str)
            and bool(f["text"].strip())
            and isinstance(f.get("needs_human", False), bool)
            for f in findings
        )
        if not valid:
            for cid in expected_ids:
                reports[cid].findings.append(
                    Finding(
                        kind,
                        "critical",
                        "Independent reviewer failed or returned an invalid report.",
                    )
                )
            continue
        for f in findings:
            if f["candidate"] not in expected_ids:
                continue
            sev = str(f.get("severity", "low")).lower()
            reports[f["candidate"]].findings.append(
                Finding(
                    source=kind,
                    severity=sev if sev in SEVERITIES else "low",
                    text=str(f.get("text", "")),
                    needs_human=bool(f.get("needs_human")),
                )
            )
    if executor is not None:

        async def execute(c: Any) -> None:
            rep = reports[c.id]
            rep.verification = f"python:{executor.backend}"
            try:
                files = python_files(c.solution)
            except ValueError as exc:
                rep.findings.append(Finding("execution", "critical", str(exc)))
                files = {}
            for t in tests:
                outcome = await executor.run(files, t.python)
                tallies[c.id].append(outcome.passed)
                rep.test_results.append(
                    {
                        "test": t.id,
                        "passed": outcome.passed,
                        "source": rep.verification,
                        "output": outcome.output[:2000],
                        "returncode": outcome.returncode,
                    }
                )

        await asyncio.gather(*(execute(c) for c in candidates))
    for cid, rep in reports.items():
        votes = tallies[cid]
        rep.pass_rate = sum(votes) / len(votes) if votes else 0.0
        rep.passed = (
            bool(tests)
            and bool(votes)
            and rep.pass_rate >= pass_threshold
            and rep.worst() != "critical"
        )
        if executor is not None:
            # Executable correctness is all-or-nothing; the model threshold
            # must not permit a known failing Python test.
            rep.passed = rep.passed and all(votes)
    return reports


# ── Kapı 3 ─────────────────────────────────────────────────────────────────
@dataclass
class Verdict:
    accepted: bool
    accepts: int
    rejects: int
    conditional: int
    reasons: list[str] = field(default_factory=list)
    unmet_criteria: list[str] = field(default_factory=list)


async def approve(
    swarm: Swarm,
    *,
    request: str,
    criteria: Sequence[str],
    deliverable: str,
    evidence: str,
    n_agents: int,
) -> Verdict:
    """Blind approval. The signature is the guarantee: no frame narrative, no
    plans, no council rationale — only request, criteria, deliverable, evidence."""
    crit = "\n".join(f"- {c}" for c in criteria)
    spec = AgentSpec(
        block="approval",
        role="Onay Merci (blind final approver)",
        seat="approval",
        goal=(
            "Decide whether this deliverable satisfies the original request. First interpret "
            "the request yourself, then judge strictly against the criteria and the evidence. "
            "If you reject, say exactly why."
        ),
        context=(
            f"# Original request\n{request}\n\n# Acceptance criteria\n{crit}\n\n"
            f"# Deliverable\n{clip(deliverable, 12000)}\n\n# Evidence package\n{evidence}"
        ),
        success_criteria=[
            'Reply with one JSON object: {"verdict": "accept|reject|conditional", '
            '"reasons": ["..."], "unmet_criteria": ["..."]}'
        ],
        forbidden=["Do not give credit for effort — only for the result."],
    )
    replies = await swarm.run([spec] * n_agents)
    v = Verdict(False, 0, 0, 0)
    for text in replies:
        data = parse_json(text) or {}
        verdict = str(data.get("verdict", "reject")).lower()
        if verdict == "accept":
            v.accepts += 1
        elif verdict == "conditional":
            v.conditional += 1
        else:
            v.rejects += 1
        if verdict != "accept":
            v.reasons += _str_list(data.get("reasons"), 5)
            v.unmet_criteria += _str_list(data.get("unmet_criteria"), 5)
    v.accepted = v.accepts > n_agents / 2
    return v
