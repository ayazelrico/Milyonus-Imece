"""Milyonus-Imece orchestrator: labor in the imece, speed in IRADE, truth at the gates.

  Kapı 1 framing → recon + experts → plans (IRADE picks) → approach clusters
  → independent production (wire off) ∥ independent test design
  → Kapı 2 reality filter → cross-critique by rotation + evolutionary revision
  → IRADE synthesis decision → integration (swarming) → system re-test
  → polish → Kapı 3 blind approval → accepted, or the rejection feeds round 2.

The process observer watches every phase. A human can stop the run between
phases (`should_stop`), and irreversible decisions always wait for the human.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import random
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Literal

from milyonus.config.paths import data_root
from milyonus.imece import gates
from milyonus.imece.agents import (
    AgentFn,
    AgentSpec,
    FatalAgentStateError,
    PoolExhausted,
    Stopped,
    Swarm,
    clip,
    parse_json,
)
from milyonus.imece.execution import NON_BUILDER_FAILURES, PythonExecutor, python_files
from milyonus.imece.irade import (
    Calibrator,
    Decision,
    DecisionRequest,
    HumanFn,
    Irade,
    IradeSettings,
    Option,
)
from milyonus.imece.observer import Observer
from milyonus.imece.scale import Allocation, allocate
from milyonus.skills.repair import RepairSkillError, load_repair_skill

RECON_FACETS = (
    "requirements and stakeholders",
    "current-state inventory: existing code, data, literature, prior work",
    "previous failed attempts — has this been tried, and why did it fail?",
    "domain literature and prior art",
    "constraint map: physical, legal, budget, time",
    "unknowns: what do we not know that we need to know?",
)
FALLBACK_APPROACHES = (
    ("direct", "the most straightforward solution that meets every criterion"),
    ("first-principles", "rebuild the solution from fundamentals, ignoring convention"),
    ("conservative", "the lowest-risk proven approach, even if less elegant"),
)
CANDIDATE_FORMAT = (
    "Use exactly these sections: ## Solution, ## Claims (each checkable), "
    "## How to verify, ## Known weaknesses. "
    "For Python artifacts use fenced blocks with the EXACT opening line "
    "```python file=solution.py (or the requested module path), then the full file, then ```. "
    "Preserve these named fences in every revision and delivery."
)

PLAIN_DELIVERABLE = "Return the deliverable itself as plain Markdown — never wrapped in JSON. For Python files preserve named fences: ```python file=solution.py followed by the full code and a closing fence."


def _explicit_no_change(text: str) -> bool:
    def unique_object(pairs):
        value = dict(pairs)
        if len(value) != len(pairs):
            raise ValueError("duplicate critique fields")
        return value

    try:
        decision = json.loads(text, object_pairs_hook=unique_object)
    except (ValueError, RecursionError):
        return False
    return (
        isinstance(decision, dict)
        and set(decision) == {"revision_needed", "findings"}
        and decision["revision_needed"] is False
        and decision["findings"] == []
    )


Status = Literal["accepted", "rejected", "stopped", "budget"]


@dataclass
class ImeceSettings:
    agents: int = 120
    max_parallel: int = 8
    max_tokens: int = 2_000_000
    max_rounds: int = 2
    max_clusters: int = 9
    max_options: int = 12
    shortlist: int = 4
    pass_threshold: float = 0.6
    verification: Literal["model", "python"] = "model"
    sandbox_backend: Literal["docker", "macos"] = "docker"
    sandbox_image: str = "python:3.12-slim"
    test_timeout: float = 10.0
    agent_timeout: float = 300.0
    cell_size: int = 9
    irade: IradeSettings = field(default_factory=IradeSettings)
    approved_evidence: tuple[str, ...] = ()
    adaptive_production: bool = False
    skip_clean_revision: bool = True
    repair_skill: str | None = None
    repair_skill_sha256: str | None = None

    def __post_init__(self) -> None:
        if self.max_parallel < 1 or self.max_tokens < 1 or self.max_rounds < 1:
            raise ValueError("parallelism, token pool and rounds must be positive")
        if not 7 <= self.cell_size <= 12 or self.max_options < 2:
            raise ValueError("cell_size must be 7..12 and max_options at least 2")
        if self.verification not in ("model", "python") or self.sandbox_backend not in (
            "docker",
            "macos",
        ):
            raise ValueError("unsupported verification mode or sandbox backend")


@dataclass
class Candidate:
    id: str
    approach: str
    author: int
    solution: str


@dataclass
class RunResult:
    status: Status
    request: str
    deliverable: str = ""
    frame: gates.Frame | None = None
    rounds: int = 0
    verdict: gates.Verdict | None = None
    final_gate: gates.GateReport | None = None
    gate_reports: list[gates.GateReport] = field(default_factory=list)
    decisions: list[Decision] = field(default_factory=list)
    allocation: Allocation | None = None
    calls_by_block: dict[str, int] = field(default_factory=dict)
    failed_by_block: dict[str, int] = field(default_factory=dict)
    tokens: int = 0
    unknown_usage_calls: int = 0
    cost_usd: float | None = None
    cost_estimated: bool = True
    warnings: list[str] = field(default_factory=list)
    metrics: dict[str, float] = field(default_factory=dict)
    retrospective: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    reproductions: list[dict] = field(default_factory=list)
    round_outcomes: list[str] = field(default_factory=list)
    production_schedule: list[dict[str, int | str]] = field(default_factory=list)
    applied_repair_skills: list[dict[str, int | str]] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = {
            "status": self.status,
            "request": self.request,
            "deliverable": self.deliverable,
            "rounds": self.rounds,
            "tokens": self.tokens,
            "unknown_usage_calls": self.unknown_usage_calls,
            "cost_usd": self.cost_usd,
            "cost_estimated": self.cost_estimated,
            "calls_by_block": self.calls_by_block,
            "failed_by_block": self.failed_by_block,
            "warnings": self.warnings,
            "metrics": self.metrics,
            "retrospective": self.retrospective,
            "notes": self.notes,
            "production_schedule": self.production_schedule,
            "applied_repair_skills": self.applied_repair_skills,
            "round_outcomes": self.round_outcomes,
            "reproductions": self.reproductions,
            "decisions": [asdict(x) for x in self.decisions],
            "gate_reports": [asdict(g) for g in self.gate_reports],
        }
        if self.frame:
            d["frame"] = asdict(self.frame)
        if self.verdict:
            d["verdict"] = asdict(self.verdict)
        if self.final_gate:
            d["final_gate"] = asdict(self.final_gate)
        if self.allocation:
            d["allocation"] = dict(self.allocation.counts)
        return d


async def _paired(left, right):
    tasks = [asyncio.create_task(left), asyncio.create_task(right)]
    try:
        return await asyncio.gather(*tasks)
    except BaseException:
        for task in tasks:
            task.cancel()
        outcomes = await asyncio.gather(*tasks, return_exceptions=True)
        for outcome in outcomes:
            if isinstance(outcome, FatalAgentStateError):
                raise outcome from None
        raise


class Imece:
    def __init__(
        self,
        agent_fn: AgentFn,
        settings: ImeceSettings | None = None,
        *,
        human: HumanFn | None = None,
        should_stop: Callable[[], bool] | None = None,
        calibrator: Calibrator | None = None,
        on_phase: Callable[[str], None] | None = None,
        capture_reproductions: bool = False,
        rng: random.Random | None = None,
    ):
        self.s = settings or ImeceSettings()
        self.alloc = allocate(self.s.agents)
        self.swarm = Swarm(
            agent_fn,
            max_parallel=self.s.max_parallel,
            max_tokens=self.s.max_tokens,
            agent_timeout=self.s.agent_timeout,
            should_stop=should_stop,
        )
        self.irade = Irade(
            self.swarm,
            settings=self.s.irade,
            human=human,
            evidence=self._extra_evidence,
            calibrator=calibrator,
            rng=rng,
        )
        self.observer = Observer()
        self.executor = (
            PythonExecutor(
                backend=self.s.sandbox_backend,
                cache_path=(data_root() / "evidence" / "python.sqlite")
                if self.s.approved_evidence
                else None,
                approved_evidence=frozenset(self.s.approved_evidence),
                image=self.s.sandbox_image,
                timeout=self.s.test_timeout,
                max_parallel=self.s.max_parallel,
            )
            if self.s.verification == "python"
            else None
        )
        self._should_stop = should_stop or (lambda: False)
        self._reproductions = [] if capture_reproductions else None
        self._on_phase = on_phase or (lambda _p: None)

    # ── helpers ────────────────────────────────────────────────────────────
    def _phase(self, name: str) -> None:
        if self._should_stop():
            raise Stopped(f"stopped by human before: {name}")
        self._on_phase(name)

    def _synthesis_options(
        self, candidates: list[Candidate], reports: dict[str, gates.GateReport]
    ) -> list[Option]:
        if not (self.s.adaptive_production and self.executor):
            return [Option(c.id, c.solution, reports[c.id].evidence()) for c in candidates]
        # Executable candidates have already passed the independent gate. The
        # council sees the frozen contract, actual checks and a bounded code delta.
        sources = [python_files(c.solution) for c in candidates]
        anchor = sources[0]
        options = []
        for c, files in zip(candidates, sources, strict=True):
            report = reports[c.id]
            changed = sorted(
                k for k in anchor.keys() | files.keys() if files.get(k) != anchor.get(k)
            )
            parts = [
                f"Approach: {clip(c.approach, 160)}",
                "Deliverable SHA-256: " + hashlib.sha256(c.solution.encode()).hexdigest(),
            ]
            if not changed:
                parts.append(f"Same named Python files as {candidates[0].id}.")
                if files and c is candidates[0]:
                    name = min(files)
                    parts.append(f"Reference excerpt ({name}):\n" + clip(files[name], 440))
            else:
                parts.append(
                    f"Files differing from {candidates[0].id}: " + clip(", ".join(changed), 220)
                )
                name = next((n for n in changed if n in files), None)
                if name is not None:
                    old = anchor.get(name, "").splitlines()
                    new = files[name].splitlines()
                    offset = next(
                        (i for i, (x, y) in enumerate(zip(old, new, strict=False)) if x != y),
                        min(len(old), len(new)),
                    )
                    parts.append(
                        f"First change in {name}, line {offset + 1}:\n"
                        + clip("\n".join(new[offset : offset + 4]), 440)
                    )
            results = report.test_results
            details = {
                "tests": results,
                "findings": [asdict(f) for f in report.findings],
                "verification": report.verification,
            }
            proof = hashlib.sha256(json.dumps(details, sort_keys=True).encode()).hexdigest()
            checks = ", ".join(str(r["test"]) for r in results if r["passed"])
            options.append(
                Option(
                    c.id,
                    "\n".join(parts),
                    f"Evidence SHA-256: {proof}\n"
                    + report.evidence()
                    + f"\nPassed checks ({len(results)} reported): "
                    + clip(checks, 270),
                )
            )
        return options

    async def _extra_evidence(self, req: DecisionRequest) -> str:
        """Tier-3 IRADE asks Kapı 2's evidence auditors for more on its options."""
        n = min(self.alloc["evidence_audit"], 3)
        options = "\n\n".join(
            f"## {o.id}\n{clip(o.summary, 1500)}\n{clip(o.evidence, 1200)}" for o in req.options
        )
        spec = AgentSpec(
            block="evidence_audit",
            role="evidence auditor (on request of the IRADE council)",
            seat="evidence_audit",
            goal="The council cannot agree. Check the strongest factual claims of each option.",
            context=f"# Decision\n{req.question}\n\n{req.context}\n\n# Options\n{options}",
            success_criteria=["Short bullet list per option: verified / unverified / false."],
        )
        return "\n\n".join(clip(t, 1200) for t in await self.swarm.run([spec] * n))

    def _ctx(self, fr: gates.Frame, *parts: tuple[str, str]) -> str:
        blocks = [fr.brief()]
        blocks += [f"# {title}\n{body}" for title, body in parts if body]
        return "\n\n".join(blocks)

    # ── phases ─────────────────────────────────────────────────────────────
    async def _summarize(self, fr: gates.Frame, notes: list[str], label: str) -> str:
        """Hierarchical command: bounded 7–12 member cells, then parent cells.
        The final partial cell may have fewer members. No independent gate is
        pooled into this tree. Original agent events remain in the run ledger.
        """
        level = 0
        size = self.s.cell_size
        while len(notes) > 1:
            specs = []
            for start in range(0, len(notes), size):
                cell = notes[start : start + size]
                specs.append(
                    AgentSpec(
                        block="command",
                        role=f"{label} cell coordinator level {level}",
                        goal="Summarize every member's useful evidence. Preserve disagreements, source qualifications, risks and minority alternatives; never silently discard a member.",
                        context=self._ctx(
                            fr,
                            (
                                "Cell contributions",
                                "\n\n".join(
                                    f"## Member {start + i + 1}\n{clip(n, 1200)}"
                                    for i, n in enumerate(cell)
                                ),
                            ),
                        ),
                        success_criteria=[
                            "A concise evidence-bearing summary with disagreements and unknowns."
                        ],
                    )
                )
            notes = await self.swarm.run(specs)
            level += 1
        self.observer.metrics[f"{label}_command_layers"] = float(level)
        return "\n\n".join(notes)

    async def _recon(self, fr: gates.Frame) -> str:
        specs = [
            AgentSpec(
                block="recon",
                role=f"recon — {RECON_FACETS[i % len(RECON_FACETS)]}",
                seat="pool",
                goal=(
                    f"Gather intelligence on: {RECON_FACETS[i % len(RECON_FACETS)]}. "
                    "Rate each item's reliability (measured / observed / expert opinion / inference)."
                ),
                context=fr.brief(),
                success_criteria=["A concise bullet list, each item tagged with its reliability."],
                use_tools=True,
            )
            for i in range(self.alloc["recon"])
        ]
        notes = await self.swarm.run(specs)
        return clip(await self._summarize(fr, notes, "recon"), 12000)

    async def _experts(self, fr: gates.Frame) -> str:
        n = self.alloc["domain_experts"]
        if not n:
            return ""
        fields = list(fr.disciplines) or ["the core domain of this problem"]
        specs = [
            AgentSpec(
                block="domain_experts",
                role=f"domain expert — {fields[i % len(fields)]}",
                seat="pool",
                goal=(
                    f"As an expert in {fields[i % len(fields)]}, write the guidance the builders "
                    "must not miss, and translate your field's jargon for other disciplines."
                ),
                context=fr.brief(),
                success_criteria=["At most 10 bullets, most important first."],
            )
            for i in range(n)
        ]
        briefs = await self.swarm.run(specs)
        per_field: dict[str, list[str]] = {}
        for i, b in enumerate(briefs):
            per_field.setdefault(fields[i % len(fields)], []).append(b)
        sections = []
        per_field_budget = max(300, 6000 // max(1, len(per_field)) - 100)
        for index, (name, notes) in enumerate(per_field.items()):
            summary = await self._summarize(fr, notes, f"expert_{index}")
            sections.append(f"## {name}\n{clip(summary, per_field_budget)}")
        return "\n\n".join(sections)

    async def _plan(self, fr: gates.Frame, intel: str, experts: str, feedback: list[str]) -> str:
        schema = {
            "title": "...",
            "steps": ["..."],
            "premortem": ["if this failed, why?"],
            "cost_time_risk": "...",
            "early_failure_signals": ["..."],
            "plan_b": "switch condition and alternative",
        }
        fb = "\n".join(f"- {r}" for r in feedback)
        specs = [
            AgentSpec(
                block="plan",
                role="independent planner",
                seat="pool",
                goal="Write an independent plan to solve the framed problem, with a pre-mortem.",
                context=self._ctx(
                    fr,
                    ("Intelligence", intel),
                    ("Expert guidance", experts),
                    ("Why the last round was rejected", fb),
                ),
                success_criteria=["Reply with one JSON object: " + json.dumps(schema)],
            )
            for _ in range(self.alloc["plan"])
        ]
        plans: list[tuple[str, str]] = []
        seen: set[str] = set()
        for text in await self.swarm.run(specs):
            if not text.strip() or text.startswith("(agent failed"):
                continue
            data = parse_json(text)
            title = str((data or {}).get("title") or text[:60]).strip()
            if title.lower() in seen:
                continue
            seen.add(title.lower())
            plans.append((title, json.dumps(data, ensure_ascii=False) if data else text))
        if not plans:
            raise gates.GateError("No planner produced a usable plan.")
        if len(plans) == 1:
            return plans[0][1]
        decision = await self.irade.decide_layered(
            DecisionRequest(
                kind="plan_selection",
                question="Which plan should the imece execute?",
                options=[Option(f"P{i + 1}", body) for i, (_t, body) in enumerate(plans)],
                context=fr.brief(),
                impact="high",
            ),
            cell_size=min(self.s.cell_size, self.s.max_options),
        )
        if decision.stopped:
            raise Stopped("IRADE could not select a plan: " + "; ".join(decision.escalations))
        return plans[int(decision.choice[1:]) - 1][1]  # type: ignore[index]

    async def _approaches(self, fr: gates.Frame, plan: str) -> list[tuple[str, str]]:
        cap = max(1, min(self.s.max_clusters, self.alloc["production"]))
        specs = [
            AgentSpec(
                block="command",
                role="command — work decomposition",
                seat="pool",
                goal=(
                    f"Define up to {cap} genuinely DIFFERENT approach clusters for the builders. "
                    "Forced diversity: no two clusters may share a core idea."
                ),
                context=self._ctx(fr, ("Selected plan", plan)),
                success_criteria=[
                    'Reply with one JSON object: {"approaches": [{"name": "...", "idea": "..."}]}'
                ],
            )
            for _ in range(self.alloc["command"])
        ]
        found: dict[str, str] = {}
        responses = await self.swarm.run(specs)
        level = 0
        while len(responses) > 1:
            cells = []
            for start in range(0, len(responses), self.s.cell_size):
                group = responses[start : start + self.s.cell_size]
                cells.append(
                    AgentSpec(
                        block="command",
                        role=f"approach coordinator level {level}",
                        goal=f"Merge the approaches proposed by ALL these command cells into at most {cap} distinct core ideas. Preserve useful minority alternatives and remove conceptual duplicates.",
                        context=self._ctx(
                            fr,
                            ("Selected plan", plan),
                            ("Command cell proposals", "\n\n".join(clip(r, 1500) for r in group)),
                        ),
                        success_criteria=[
                            'Reply with one JSON object: {"approaches": [{"name": "...", "idea": "..."}]}'
                        ],
                    )
                )
            responses = await self.swarm.run(cells)
            level += 1
        self.observer.metrics["approach_command_layers"] = float(level)
        for text in responses:
            for a in (parse_json(text) or {}).get("approaches") or []:
                if isinstance(a, dict) and str(a.get("name", "")).strip():
                    found.setdefault(str(a["name"]).strip().lower(), str(a.get("idea", "")))
        for name, idea in FALLBACK_APPROACHES:
            if len(found) >= min(2, cap):
                break
            found.setdefault(name, idea)
        return list(found.items())[:cap]

    @staticmethod
    def _stagnation_fingerprint(
        candidates: list[Candidate],
        tests: list[gates.TestCase],
        reports: dict[str, gates.GateReport],
    ) -> str | None:
        """Identify unchanged executable rejections; incomplete evidence abstains.

        Compare named file contents and observed check outcomes, never builder
        labels or prose. Runtime failure does not establish candidate/oracle blame.
        """
        if not candidates or not tests or len({t.id for t in tests}) != len(tests):
            return None
        for test in tests:
            if not test.python.strip():
                return None
            try:
                compile(test.python, "oracle.py", "exec")
            except (SyntaxError, ValueError):
                return None
        contracts = sorted((t.id, t.check, t.how, t.python) for t in tests)
        observations: set[str] = set()
        for candidate in candidates:
            report = reports.get(candidate.id)
            if (
                report is None
                or report.passed
                or report.verification not in {"python:docker", "python:macos"}
                or len(report.test_results) != len(tests)
            ):
                return None
            try:
                files = python_files(candidate.solution)
            except ValueError:
                return None
            if not files:
                return None
            outcomes = {}
            failed = False
            for row in report.test_results:
                test_id = row.get("test")
                if (
                    not isinstance(test_id, str)
                    or test_id in outcomes
                    or row.get("source") != report.verification
                    or type(row.get("passed")) is not bool
                    or type(row.get("returncode")) is not int
                    or not isinstance(row.get("output"), str)
                    or row.get("output_truncated") is not False
                    or "failure_class" not in row
                ):
                    return None
                if row["passed"]:
                    if row["returncode"] != 0 or row["failure_class"] is not None:
                        return None
                else:
                    # Positive evidence of an executed Python failure only. Unknown
                    # classes, infrastructure, missing artifacts and timeouts abstain.
                    if (
                        row["returncode"] != 1
                        or row["failure_class"] != "candidate_or_oracle_runtime"
                    ):
                        return None
                    failed = True
                outcomes[test_id] = {
                    key: row.get(key)
                    for key in (
                        "passed",
                        "source",
                        "output",
                        "returncode",
                        "failure_class",
                        "evidence_id",
                    )
                }
            if not failed or set(outcomes) != {t.id for t in tests}:
                return None
            observations.add(json.dumps([files, outcomes], sort_keys=True))
        payload = json.dumps([contracts, sorted(observations)], sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()

    @staticmethod
    def _repair_candidate(
        candidates: list[Candidate], reports: dict[str, gates.GateReport]
    ) -> tuple[Candidate, gates.GateReport] | None:
        best = sorted(candidates, key=lambda c: reports[c.id].pass_rate, reverse=True)[:3]
        for candidate in best:
            report = reports[candidate.id]
            if (
                not report.passed
                and len(candidate.solution) <= 16000
                and 0 < report.pass_rate < 1
                and any(
                    r.get("passed") is not True
                    and r.get("returncode") == 1
                    and r.get("failure_class") not in NON_BUILDER_FAILURES
                    for r in report.test_results
                )
                and not report.needs_human()
            ):
                return candidate, report
        return None

    def _production_breadth(
        self,
        fr: gates.Frame,
        approaches: list[tuple[str, str]],
        previous: dict[str, gates.GateReport] | None,
        previous_builders: int,
        repair: tuple[Candidate, gates.GateReport] | None,
    ) -> tuple[int, str]:
        capacity = self.alloc["production"]
        if not self.s.adaptive_production:
            return capacity, "Nonadaptive: configured production allocation."
        if previous is None:
            disagreements = len(set(fr.divergences))
            return min(capacity, len(approaches) + disagreements), (
                f"Initial breadth: {len(approaches)} approaches and {disagreements} "
                "distinct framing disagreements, capped by production allocation."
            )
        if repair:
            candidate, report = repair
            alternatives = sum(name != candidate.approach for name, _ in approaches)
            return min(capacity, 1 + alternatives), (
                f"Near-pass {candidate.id} ({report.pass_rate:.0%} checks passed): "
                f"one targeted repair plus {alternatives} alternative approaches, capped by allocation."
            )

        # Count observations, not candidates or repeated copies of the same failure.
        # Runtime failures describe a failed check; they do not assign blame to code.
        defects: set[str] = set()
        blocked: set[str] = set()
        for report in previous.values():
            if report.passed:
                continue
            for result in report.test_results:
                if result.get("passed") is True:
                    continue
                failure = result.get("failure_class")
                if failure in NON_BUILDER_FAILURES:
                    blocked.add(str(failure))
                    continue
                if not failure and result.get("source") != "model":
                    blocked.add("unknown execution failure")
                    continue
                output = str(result.get("output", "")).strip().splitlines()
                diagnostic = output[-1] if output else ""
                defects.add(
                    f"{result.get('test', '?')} [{failure or 'model'}] {diagnostic}".strip()
                )
            for finding in report.findings:
                if finding.text == "Independent reviewer failed or returned an invalid report.":
                    blocked.add("independent reviewer unavailable or invalid")
                elif finding.source != "execution" and finding.severity in ("high", "critical"):
                    defects.add(f"{finding.source}/{finding.severity}: {finding.text}")
        if defects:
            builders = min(
                capacity,
                max(len(approaches), previous_builders, len(approaches) + len(defects) - 1),
            )
            return builders, (
                f"Previous gate demonstrated {len(defects)} distinct defect observations: "
                + "; ".join(sorted(defects))
                + ". Breadth covers approaches plus distinct defects, capped by allocation."
            )
        reason = "; ".join(sorted(blocked)) or "no demonstrated defects in the latest gate reports"
        return previous_builders, f"Hold previous breadth: {reason}; no evidence for more builders."

    async def _produce(
        self,
        rnd: int,
        fr: gates.Frame,
        plan: str,
        intel: str,
        experts: str,
        approaches: list[tuple[str, str]],
        feedback: list[str],
        repair: tuple[Candidate, gates.GateReport] | None = None,
        builders: int | None = None,
        result: RunResult | None = None,
    ) -> list[Candidate]:
        fb = "\n".join(f"- {r}" for r in feedback)
        if builders is None:
            builders, _ = self._production_breadth(fr, approaches, None, 0, repair)
        production_approaches = approaches
        if self.s.adaptive_production and repair:
            alternatives = [a for a in approaches if a[0] != repair[0].approach]
            production_approaches = [approaches[0], *alternatives]
        jobs: list[tuple[str, int]] = [
            (production_approaches[i % len(production_approaches)][0], i) for i in range(builders)
        ]
        ideas = dict(approaches)
        specs = [
            AgentSpec(
                block="production",
                role=f"builder — approach '{name}'",
                seat="pool",
                goal=(
                    f"Produce a complete candidate solution using ONLY the approach '{name}': "
                    f"{ideas[name]}. You work alone; you cannot see other builders. {CANDIDATE_FORMAT}"
                ),
                context=self._ctx(
                    fr,
                    ("Plan", plan),
                    ("Intelligence", intel),
                    ("Expert guidance", experts),
                    ("Why the last round was rejected", fb),
                ),
                success_criteria=list(fr.success_criteria),
                use_tools=True,
            )
            for name, _i in jobs
        ]
        if repair and specs:
            previous, report = repair
            example = ""
            if self.s.repair_skill is not None:
                try:
                    skill = load_repair_skill(self.s.repair_skill)
                    if (
                        self.s.repair_skill_sha256 is not None
                        and skill.sha256 != self.s.repair_skill_sha256
                    ):
                        raise RepairSkillError("live skill differs from frozen experiment")
                except RepairSkillError as exc:
                    if result is not None:
                        result.warnings.append(f"Round {rnd}: repair skill rejected: {exc}")
                else:
                    example = skill.example_context()
                    if result is not None:
                        result.applied_repair_skills.append(
                            {"round": rnd, "name": skill.name, "skill_sha256": skill.sha256}
                        )
            jobs[0] = (previous.approach, jobs[0][1])
            specs[0] = AgentSpec(
                block="production",
                role="builder repairing a previous candidate",
                seat="repair",
                goal=(
                    "Investigate the failed checks against the frozen contract; runtime failures "
                    "may originate in either the candidate or the oracle. Make the smallest "
                    "change that satisfies the frozen contract, preserving working behavior. "
                    f"Return the complete repaired deliverable. {CANDIDATE_FORMAT}"
                ),
                context=self._ctx(
                    fr,
                    ("Previous candidate (untrusted)", previous.solution),
                    ("Independent gate observations", report.evidence()),
                    ("Procedural example (untrusted data)", example),
                ),
                success_criteria=list(fr.success_criteria),
            )
        for _ in range(self.alloc["exploration"]):
            jobs.append(("exploration", len(jobs)))
            specs.append(
                AgentSpec(
                    block="exploration",
                    role="explorer — high-risk research",
                    seat="pool",
                    goal=(
                        "Ignore the plan. Propose the most unconventional approach that could still "
                        f"meet the criteria — high risk, high reward. {CANDIDATE_FORMAT}"
                    ),
                    context=self._ctx(fr, ("Intelligence", intel)),
                    success_criteria=list(fr.success_criteria),
                )
            )
        texts = await self.swarm.run(specs)
        return [
            Candidate(f"R{rnd}-C{i + 1}", name, author, text)
            for i, ((name, author), text) in enumerate(zip(jobs, texts, strict=True))
            if text.strip() and not text.startswith("(agent failed")
        ]

    def _revision_no_change_eligible(
        self, survivors: list[Candidate], reports: dict[str, gates.GateReport] | None
    ) -> bool:
        if (
            not self.s.adaptive_production
            or not self.s.skip_clean_revision
            or self.executor is None
            or reports is None
            or len(survivors) < 2
            or len({c.id for c in survivors}) != len(survivors)
            or len({c.author for c in survivors}) < 2
            or len({c.approach for c in survivors}) < 2
        ):
            return False
        environments = set()
        for candidate in survivors:
            report = reports.get(candidate.id)
            if (
                report is None
                or report.passed is not True
                or report.findings
                or report.verification != "python:docker"
                or not report.test_results
            ):
                return False
            for check in report.test_results:
                environment = check.get("environment_id")
                if (
                    check.get("passed") is not True
                    or type(check.get("returncode")) is not int
                    or check["returncode"] != 0
                    or check.get("source") != report.verification
                    or check.get("failure_class") is not None
                    or check.get("output_truncated") is not False
                    or not isinstance(environment, str)
                    or len(environment) != 64
                    or any(c not in "0123456789abcdef" for c in environment)
                ):
                    return False
                environments.add(environment)
        return len(environments) == 1

    async def _cross_critique(
        self,
        survivors: list[Candidate],
        fr: gates.Frame | None = None,
        *,
        reports: dict[str, gates.GateReport] | None = None,
        result: RunResult | None = None,
    ) -> list[Candidate]:
        """Role rotation: every candidate is critiqued by a builder from another
        approach (never its author), then its author revises — borrowing from
        the best other survivor (crossover)."""
        no_change_eligible = fr is not None and self._revision_no_change_eligible(
            survivors, reports
        )
        critics = []
        for c in survivors:
            other = next((o for o in survivors if o.approach != c.approach), None)
            donor = next((o for o in survivors if o.id != c.id), None)
            critic_approach = other.approach if other else "a different approach"
            context = self._ctx(fr, ("Candidate", c.solution)) if fr is not None else c.solution
            goal = "Critique this candidate against the frozen contract. Identify concrete within-scope failures; do not invent requirements or demand handling of inputs explicitly excluded by assumptions. Say no issues if none are demonstrable."
            criteria = ["Bullet list of concrete flaws, most serious first."]
            if no_change_eligible:
                context = self._ctx(
                    fr,
                    ("Candidate", c.solution),
                    ("Other candidate for crossover", donor.solution),
                    ("Independent gate observations", reports[c.id].evidence()),
                )
                goal = (
                    "Critique the candidate against the frozen contract and evaluate the other "
                    "candidate for a concrete, strictly better within-scope idea worth adopting. "
                    "Do not invent requirements. Set revision_needed=false only if there are no "
                    "demonstrable flaws AND no justified crossover improvement. Otherwise describe "
                    "the actionable changes in findings. Return only a plain JSON object."
                )
                criteria = ['{"revision_needed": true|false, "findings": ["actionable change"]}']
            critics.append(
                AgentSpec(
                    block="production",
                    role=f"cross-critic from approach '{critic_approach}' (not the author)",
                    seat="pool",
                    goal=goal,
                    context=context,
                    success_criteria=criteria,
                )
            )
        critiques = await self.swarm.run(critics)
        if (
            no_change_eligible
            and len(critiques) == len(survivors)
            and all(_explicit_no_change(text) for text in critiques)
        ):
            count = len(survivors)
            self.observer.metrics["revision_calls_avoided"] = (
                self.observer.metrics.get("revision_calls_avoided", 0) + count
            )
            if result is not None:
                result.notes.append(
                    f"Kept {count} gate-passed candidates unchanged after unanimous explicit "
                    "no-change cross-critiques; independent re-testing remains required."
                )
            return list(survivors)
        revisers = []
        for c, crit in zip(survivors, critiques, strict=True):
            donor = next((o for o in survivors if o.id != c.id), None)
            revisers.append(
                AgentSpec(
                    block="production",
                    role=f"author revising — approach '{c.approach}'",
                    seat="pool",
                    goal=(
                        "Revise your candidate: fix every valid criticism, and adopt any strictly "
                        f"better idea from the other candidate. {CANDIDATE_FORMAT}"
                    ),
                    context=(fr.brief() + "\n\n" if fr is not None else "")
                    + (
                        f"# Your candidate\n{clip(c.solution, 6000)}\n\n# Criticism\n{clip(crit, 2000)}"
                        + (
                            f"\n\n# Another candidate (for crossover)\n{clip(donor.solution, 3000)}"
                            if donor
                            else ""
                        )
                    ),
                    success_criteria=[
                        *(fr.success_criteria if fr is not None else ()),
                        "Preserve the original scope and assumptions. Only adopt criticism that applies to the contract.",
                        "Return the full revised candidate, not a diff.",
                    ],
                )
            )
        revised = await self.swarm.run(revisers)
        return [
            Candidate(
                c.id,
                c.approach,
                c.author,
                r if r.strip() and not r.startswith("(agent failed") else c.solution,
            )
            for c, r in zip(survivors, revised, strict=True)
        ]

    async def _integrate(self, fr: gates.Frame, primary: Candidate, others: list[Candidate]) -> str:
        extra = "\n\n".join(f"## {o.id} ({o.approach})\n{clip(o.solution, 2500)}" for o in others)
        [merged] = await self.swarm.run(
            [
                AgentSpec(
                    block="integration",
                    role="lead integrator",
                    seat="pool",
                    goal=(
                        "Build the final deliverable from the chosen primary candidate. Take a part "
                        "from another candidate only if it is clearly better AND fits the interfaces."
                    ),
                    context=self._ctx(
                        fr,
                        ("Primary (chosen by IRADE)", clip(primary.solution, 8000)),
                        ("Other candidates", extra),
                    ),
                    success_criteria=[
                        *fr.success_criteria,
                        "One coherent deliverable, no seams.",
                        PLAIN_DELIVERABLE,
                    ],
                )
            ]
        )
        if not merged.strip() or merged.startswith("(agent failed"):
            merged = primary.solution
        # Integration bottleneck → swarm idle production agents into integrity checks.
        want = max(2, len(others) + 1)
        if self.alloc.effective("integration") - 1 < want:
            self.alloc.borrow(
                "production",
                "integration",
                want - (self.alloc.effective("integration") - 1),
                "integration bottleneck",
            )
        n_check = max(1, self.alloc.effective("integration") - 1)
        checks = await self.swarm.run(
            [
                AgentSpec(
                    block="integration",
                    role="integrity checker",
                    seat="pool",
                    goal="Do the parts work together? Find interface mismatches, contradictions and gaps.",
                    context=self._ctx(fr, ("Integrated deliverable", clip(merged, 10000))),
                    success_criteria=[
                        'Reply with one JSON object: {"ok": true, "issues": ["..."]}'
                    ],
                )
            ]
            * n_check
        )
        self.alloc.release_loans()
        issues: list[str] = []
        for t in checks:
            for i in (parse_json(t) or {}).get("issues") or []:
                if str(i).strip() and str(i) not in issues:
                    issues.append(str(i))
        if not issues:
            return merged
        [fixed] = await self.swarm.run(
            [
                AgentSpec(
                    block="integration",
                    role="lead integrator — fixing integrity issues",
                    seat="pool",
                    goal=f"Fix every integrity issue listed. Return the full deliverable. {PLAIN_DELIVERABLE}",
                    context=f"# Deliverable\n{clip(merged, 10000)}\n\n# Issues\n"
                    + "\n".join(f"- {i}" for i in issues[:15]),
                    success_criteria=list(fr.success_criteria),
                )
            ]
        )
        return fixed if fixed.strip() and not fixed.startswith("(agent failed") else merged

    async def _polish(self, fr: gates.Frame, deliverable: str) -> str:
        if not self.alloc["polish"]:
            return deliverable
        [out] = await self.swarm.run(
            [
                AgentSpec(
                    block="polish",
                    role="polish and delivery",
                    seat="pool",
                    goal=(
                        "Package the deliverable for its audience: simplify, document, and add a short "
                        "'Limitations' section. Do NOT change its substance or claims."
                    ),
                    context=self._ctx(fr, ("Deliverable", clip(deliverable, 12000))),
                    success_criteria=["Return the full polished deliverable.", PLAIN_DELIVERABLE],
                )
            ]
        )
        return out if out.strip() and not out.startswith("(agent failed") else deliverable

    async def _gate2(
        self, fr: gates.Frame, cands: list[Candidate], tests: list[gates.TestCase], *, full: bool
    ) -> dict[str, gates.GateReport]:
        if full:
            need = len(cands)
            have = self.alloc.effective("test_exec")
            if have < need:  # test-run surge: idle builders swarm into test execution
                self.alloc.borrow("production", "test_exec", need - have, "test execution surge")
        a = self.alloc
        cap = (lambda n: n) if full else (lambda n: min(n, 3))
        try:
            reports = await gates.reality(
                self.swarm,
                fr,
                cands,
                tests,
                test_exec=cap(a.effective("test_exec")),
                red_team=cap(a["red_team"]),
                evidence_audit=cap(a["evidence_audit"]),
                compliance=min(a["compliance"], 1) if not full else a["compliance"],
                pass_threshold=self.s.pass_threshold,
                executor=self.executor,
            )
            if self._reproductions is not None and self.executor is not None:
                from milyonus.imece.reproduction import capture

                capture(self._reproductions, cands, tests, reports, self.executor)
            return reports
        finally:
            self.alloc.release_loans()

    # ── the run ────────────────────────────────────────────────────────────
    async def run(self, request: str) -> RunResult:
        res = RunResult(status="rejected", request=request, allocation=self.alloc)
        prev_reasons: list[str] = []
        try:
            if self.executor is not None and not self.executor.available():
                raise gates.GateError(f"sandbox unavailable: {self.s.sandbox_backend}")
            self._phase("Kapı 1 — independent framing")
            fr = await gates.frame(self.swarm, request, self.alloc["framing"])
            res.frame = fr
            self._phase("Recon + domain experts")
            intel, experts = await _paired(self._recon(fr), self._experts(fr))
            tests: list[gates.TestCase] | None = None
            feedback: list[str] = []
            repair = None
            previous_reports: dict[str, gates.GateReport] | None = None
            previous_candidates: list[Candidate] = []
            previous_rejection_fingerprint: str | None = None
            builders = self.alloc["production"]

            for rnd in range(1, self.s.max_rounds + 1):
                res.rounds = rnd
                res.round_outcomes.append("unfinished")
                log_start = len(self.irade.log)
                self._phase(f"Round {rnd}: planning (IRADE selects)")
                plan = await self._plan(fr, intel, experts, feedback)
                approaches = await self._approaches(fr, plan)
                if self.s.adaptive_production and previous_reports:
                    repair = self._repair_candidate(previous_candidates, previous_reports)
                builders, scheduling_reason = self._production_breadth(
                    fr, approaches, previous_reports, builders, repair
                )
                res.production_schedule.append(
                    {"round": rnd, "builders": builders, "reason": scheduling_reason}
                )
                # Only this round's latest gate may inform the next allocation.
                previous_reports = {}
                previous_candidates = []

                self._phase(f"Round {rnd}: independent production ∥ test design")
                if tests is None:
                    cands, tests = await _paired(
                        self._produce(
                            rnd, fr, plan, intel, experts, approaches, feedback, builders=builders
                        ),
                        gates.design_tests(
                            self.swarm,
                            fr,
                            self.alloc["test_design"],
                            executable=self.executor is not None,
                        ),
                    )
                else:
                    cands = await self._produce(
                        rnd,
                        fr,
                        plan,
                        intel,
                        experts,
                        approaches,
                        feedback,
                        repair,
                        builders,
                        result=res,
                    )
                repair = None
                self.observer.check_candidates(
                    [c.solution for c in cands], [c.approach for c in cands]
                )
                if not cands:
                    previous_rejection_fingerprint = None
                    res.round_outcomes[-1] = "no_candidate"
                    feedback = ["No builder produced a usable candidate."]
                    continue

                self._phase(f"Round {rnd}: Kapı 2 — reality filter")
                reports = await self._gate2(fr, cands, tests, full=True)
                previous_reports, previous_candidates = reports, cands
                res.gate_reports.extend(reports.values())
                passed = sorted(
                    (c for c in cands if reports[c.id].passed),
                    key=lambda c: reports[c.id].pass_rate,
                    reverse=True,
                )
                res.notes.append(
                    f"round {rnd}: {len(passed)}/{len(cands)} candidates passed Kapı 2"
                )
                if not passed:
                    res.round_outcomes[-1] = "production_gate_rejected"
                    if self.s.adaptive_production:
                        # Checks remain frozen across rounds. Rebuilding candidates
                        # cannot make a missing or syntactically invalid check pass.
                        broken_checks = sorted(
                            {
                                str(check["test"])
                                for report in reports.values()
                                for check in report.test_results
                                if check.get("failure_class")
                                in {"oracle_missing", "oracle_syntax_error"}
                            }
                        )
                        if broken_checks:
                            res.notes.append(
                                "Frozen oracle requires correction: " + ", ".join(broken_checks)
                            )
                            break
                        fingerprint = (
                            self._stagnation_fingerprint(cands, tests, reports)
                            if self.s.verification == "python" and self.executor is not None
                            else None
                        )
                        if (
                            fingerprint is not None
                            and fingerprint == previous_rejection_fingerprint
                        ):
                            res.notes.append(
                                "Adaptive production stopped: two consecutive production-gate "
                                "rejections with unchanged candidate Python file content sets, "
                                "frozen runnable check contracts and observed execution outcomes; "
                                f"stagnation SHA-256: {fingerprint}."
                            )
                            break
                        previous_rejection_fingerprint = fingerprint
                    worst = sorted(cands, key=lambda c: reports[c.id].pass_rate, reverse=True)[:3]
                    feedback = [reports[c.id].evidence() for c in worst]
                    repair = self._repair_candidate(cands, reports)
                    continue
                previous_rejection_fingerprint = None
                # Keep approach diversity in the shortlist: best per approach first.
                shortlist: list[Candidate] = []
                for c in passed:
                    if c.approach not in {s.approach for s in shortlist}:
                        shortlist.append(c)
                shortlist += [c for c in passed if c not in shortlist]
                shortlist = shortlist[: self.s.shortlist]

                self._phase(f"Round {rnd}: cross-critique + evolutionary revision")
                revised = await self._cross_critique(shortlist, fr, reports=reports, result=res)
                self._phase(f"Round {rnd}: re-test revised candidates")
                revised_reports = await self._gate2(fr, revised, tests, full=False)
                previous_reports, previous_candidates = revised_reports, revised
                res.gate_reports.extend(revised_reports.values())
                revised = [c for c in revised if revised_reports[c.id].passed]
                reports = revised_reports
                if not revised:
                    res.round_outcomes[-1] = "revision_gate_rejected"
                    feedback = ["All revised candidates failed independent re-testing."] + [
                        r.evidence() for r in revised_reports.values()
                    ]
                    continue

                self._phase(f"Round {rnd}: IRADE synthesis decision")
                decision = await self.irade.decide(
                    DecisionRequest(
                        kind="synthesis",
                        question="Which candidate should be the primary basis of the final deliverable?",
                        options=self._synthesis_options(revised, reports),
                        context=fr.brief(),
                        impact="strategic" if rnd > 1 else "high",
                        reversible=not any(reports[c.id].needs_human() for c in revised),
                    )
                )
                if decision.stopped:
                    raise Stopped(
                        "IRADE halted at synthesis: "
                        + "; ".join(decision.escalations + decision.rationale[-1:])
                    )
                primary = next(c for c in revised if c.id == decision.choice)
                others = sorted(
                    (c for c in revised if c.id != primary.id),
                    key=lambda c: decision.totals.get(c.id, 0.0),
                    reverse=True,
                )

                self._phase(f"Round {rnd}: integration + system re-test")
                deliverable = await self._integrate(fr, primary, others)
                final = Candidate("FINAL", primary.approach, primary.author, deliverable)
                final_rep = (await self._gate2(fr, [final], tests, full=False))["FINAL"]
                previous_reports, previous_candidates = {final.id: final_rep}, [final]
                res.gate_reports.append(final_rep)
                res.final_gate, res.deliverable = final_rep, deliverable
                if not final_rep.passed:
                    res.round_outcomes[-1] = "integration_gate_rejected"
                    feedback = [final_rep.evidence()]
                    res.notes.append(
                        f"round {rnd}: integrated deliverable failed the system re-test"
                    )
                    continue

                self._phase(f"Round {rnd}: polish + Kapı 3 blind approval")
                deliverable = await self._polish(fr, deliverable)
                res.deliverable = deliverable
                if deliverable != final.solution:
                    self._phase(f"Round {rnd}: re-test polished deliverable")
                    final = Candidate(
                        "FINAL-POLISHED", primary.approach, primary.author, deliverable
                    )
                    final_rep = (await self._gate2(fr, [final], tests, full=False))[final.id]
                    previous_reports, previous_candidates = {final.id: final_rep}, [final]
                    res.gate_reports.append(final_rep)
                    res.final_gate = final_rep
                    if not final_rep.passed:
                        res.round_outcomes[-1] = "polish_gate_rejected"
                        feedback = ["Polished deliverable failed re-testing."] + [
                            f.text for f in final_rep.findings[:6]
                        ]
                        continue
                if final_rep.needs_human():
                    self._phase(f"Round {rnd}: human review of final findings")
                    final_decision = await self.irade.decide(
                        DecisionRequest(
                            kind="final_delivery",
                            question="Approve delivery with the flagged irreversible risks?",
                            options=[Option("deliver", deliverable)],
                            context=final_rep.evidence(),
                            reversible=False,
                        )
                    )
                    if final_decision.stopped:
                        raise Stopped("Final deliverable has findings that require human review.")
                evidence = (
                    final_rep.evidence()
                    + "\n\nTests:\n"
                    + "\n".join(f"- {t.id}: {t.check}" for t in tests)
                )
                verdict = await gates.approve(
                    self.swarm,
                    request=request,
                    criteria=fr.success_criteria,
                    deliverable=deliverable,
                    evidence=evidence,
                    n_agents=self.alloc["approval"],
                )
                res.verdict = verdict
                for d in self.irade.log[log_start:]:
                    if d.tier >= 2 and d.choice is not None:
                        self.irade.calibrator.record(d.confidence, verdict.accepted)
                if verdict.accepted:
                    res.round_outcomes[-1] = "accepted"
                    res.status = "accepted"
                    break
                res.round_outcomes[-1] = "approval_rejected"
                reasons = verdict.reasons + verdict.unmet_criteria
                self.observer.check_progress(prev_reasons, reasons)
                prev_reasons = reasons
                feedback = reasons or ["Kapı 3 rejected without a reason."]
        except PoolExhausted as exc:
            res.status = "budget"
            res.notes.append(str(exc))
        except Stopped as exc:
            res.status = "stopped"
            res.notes.append(str(exc))
        except gates.GateError as exc:
            res.status = "rejected"
            res.notes.append(str(exc))

        self.observer.check_decisions(self.irade.tier_counts())
        self.observer.check_swarm(self.swarm)
        res.reproductions = list(self._reproductions or [])
        res.decisions = list(self.irade.log)
        res.warnings.extend(self.observer.warnings)
        res.metrics = dict(self.observer.metrics)
        if self.executor is not None:
            outcomes = [r for gate in res.gate_reports for r in gate.test_results]
            res.metrics["gate_processes_started"] = self.executor.processes_started
            res.metrics["gate_checks_reported"] = len(outcomes)
            res.metrics["gate_checks_reused"] = sum(r.get("reused") is True for r in outcomes)
        if res.status in ("accepted", "rejected") and self.swarm.events and not self._should_stop():
            try:
                summary = {
                    "status": res.status,
                    "rounds": res.rounds,
                    "notes": res.notes,
                    "warnings": res.warnings,
                    "metrics": res.metrics,
                    "tiers": self.irade.tier_counts(),
                    "calls_by_block": self.swarm.calls_by_block(),
                    "divergences": list(res.frame.divergences) if res.frame else [],
                    "rejections": res.verdict.reasons if res.verdict else [],
                }
                res.retrospective = await self.observer.retrospective(
                    self.swarm, self.alloc["observer"], summary
                )
            except Stopped as exc:
                res.status = "stopped"
                res.notes.append(str(exc))
            except PoolExhausted:
                pass
        res.calls_by_block = self.swarm.calls_by_block()
        res.failed_by_block = self.swarm.failed_by_block()
        res.tokens = self.swarm.used_tokens
        events = self.swarm.events
        res.unknown_usage_calls = sum(not e.usage_known for e in events)
        res.cost_usd = (
            round(sum(e.cost_usd or 0.0 for e in events), 6)
            if events and all(e.cost_usd is not None for e in events)
            else None
        )
        res.cost_estimated = res.cost_usd is None or any(e.cost_estimated for e in events)
        return res
