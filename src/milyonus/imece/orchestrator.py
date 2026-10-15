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
import json
import random
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Literal

from milyonus.imece import gates
from milyonus.imece.agents import AgentFn, AgentSpec, PoolExhausted, Swarm, clip, parse_json
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
    "## How to verify, ## Known weaknesses."
)

PLAIN_DELIVERABLE = "Return the deliverable itself as plain Markdown (code in fenced blocks) — never wrapped in JSON."

Status = Literal["accepted", "rejected", "stopped", "budget"]


@dataclass
class ImeceSettings:
    agents: int = 120
    max_parallel: int = 8
    max_tokens: int = 2_000_000
    max_rounds: int = 2
    max_clusters: int = 9
    max_options: int = 6
    shortlist: int = 4
    pass_threshold: float = 0.6
    irade: IradeSettings = field(default_factory=IradeSettings)


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
    warnings: list[str] = field(default_factory=list)
    metrics: dict[str, float] = field(default_factory=dict)
    retrospective: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = {
            "status": self.status,
            "request": self.request,
            "deliverable": self.deliverable,
            "rounds": self.rounds,
            "tokens": self.tokens,
            "calls_by_block": self.calls_by_block,
            "failed_by_block": self.failed_by_block,
            "warnings": self.warnings,
            "metrics": self.metrics,
            "retrospective": self.retrospective,
            "notes": self.notes,
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


class Stopped(Exception):
    """A human (or a stop file) halted the run between phases."""


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
        rng: random.Random | None = None,
    ):
        self.s = settings or ImeceSettings()
        self.alloc = allocate(self.s.agents)
        self.swarm = Swarm(agent_fn, max_parallel=self.s.max_parallel, max_tokens=self.s.max_tokens)
        self.irade = Irade(
            self.swarm,
            settings=self.s.irade,
            human=human,
            evidence=self._extra_evidence,
            calibrator=calibrator,
            rng=rng,
        )
        self.observer = Observer()
        self._should_stop = should_stop or (lambda: False)
        self._on_phase = on_phase or (lambda _p: None)

    # ── helpers ────────────────────────────────────────────────────────────
    def _phase(self, name: str) -> None:
        if self._should_stop():
            raise Stopped(f"stopped by human before: {name}")
        self._on_phase(name)

    async def _extra_evidence(self, req: DecisionRequest) -> str:
        """Tier-3 IRADE asks Kapı 2's evidence auditors for more on its options."""
        n = min(self.alloc["evidence_audit"], 3)
        options = "\n\n".join(f"## {o.id}\n{clip(o.summary, 1500)}" for o in req.options)
        spec = AgentSpec(
            block="evidence_audit",
            role="evidence auditor (on request of the IRADE council)",
            seat="evidence_audit",
            goal="The council cannot agree. Check the strongest factual claims of each option.",
            context=f"# Decision\n{req.question}\n\n# Options\n{options}",
            success_criteria=["Short bullet list per option: verified / unverified / false."],
        )
        return "\n\n".join(clip(t, 1200) for t in await self.swarm.run([spec] * n))

    def _ctx(self, fr: gates.Frame, *parts: tuple[str, str]) -> str:
        blocks = [fr.brief()]
        blocks += [f"# {title}\n{body}" for title, body in parts if body]
        return "\n\n".join(blocks)

    # ── phases ─────────────────────────────────────────────────────────────
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
        return clip("\n\n".join(clip(n, 800) for n in notes), 8000)

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
        return clip(
            "\n\n".join(
                f"## {f}\n" + "\n".join(clip(b, 700) for b in bs[:2]) for f, bs in per_field.items()
            ),
            6000,
        )

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
            data = parse_json(text)
            title = str((data or {}).get("title") or text[:60]).strip()
            if title.lower() in seen:
                continue
            seen.add(title.lower())
            plans.append((title, json.dumps(data, ensure_ascii=False) if data else text))
        plans = plans[: self.s.max_options]
        if len(plans) == 1:
            return plans[0][1]
        decision = await self.irade.decide(
            DecisionRequest(
                kind="plan_selection",
                question="Which plan should the imece execute?",
                options=[Option(f"P{i + 1}", body) for i, (_t, body) in enumerate(plans)],
                context=fr.brief(),
                impact="high",
            )
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
        for text in await self.swarm.run(specs):
            for a in (parse_json(text) or {}).get("approaches") or []:
                if isinstance(a, dict) and str(a.get("name", "")).strip():
                    found.setdefault(str(a["name"]).strip().lower(), str(a.get("idea", "")))
        for name, idea in FALLBACK_APPROACHES:
            if len(found) >= min(2, cap):
                break
            found.setdefault(name, idea)
        return list(found.items())[:cap]

    async def _produce(
        self,
        rnd: int,
        fr: gates.Frame,
        plan: str,
        intel: str,
        experts: str,
        approaches: list[tuple[str, str]],
        feedback: list[str],
    ) -> list[Candidate]:
        fb = "\n".join(f"- {r}" for r in feedback)
        jobs: list[tuple[str, int]] = [
            (approaches[i % len(approaches)][0], i) for i in range(self.alloc["production"])
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

    async def _cross_critique(self, survivors: list[Candidate]) -> list[Candidate]:
        """Role rotation: every candidate is critiqued by a builder from another
        approach (never its author), then its author revises — borrowing from
        the best other survivor (crossover)."""
        critics = []
        for c in survivors:
            other = next((o for o in survivors if o.approach != c.approach), None)
            critic_approach = other.approach if other else "a different approach"
            critics.append(
                AgentSpec(
                    block="production",
                    role=f"cross-critic from approach '{critic_approach}' (not the author)",
                    seat="pool",
                    goal="Critique this candidate hard: what is wrong, missing or weaker than it claims?",
                    context=clip(c.solution, 6000),
                    success_criteria=["Bullet list of concrete flaws, most serious first."],
                )
            )
        critiques = await self.swarm.run(critics)
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
                    context=(
                        f"# Your candidate\n{clip(c.solution, 6000)}\n\n# Criticism\n{clip(crit, 2000)}"
                        + (
                            f"\n\n# Another candidate (for crossover)\n{clip(donor.solution, 3000)}"
                            if donor
                            else ""
                        )
                    ),
                    success_criteria=["Return the full revised candidate, not a diff."],
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
            return await gates.reality(
                self.swarm,
                fr,
                cands,
                tests,
                test_exec=cap(a.effective("test_exec")),
                red_team=cap(a["red_team"]),
                evidence_audit=cap(a["evidence_audit"]),
                compliance=min(a["compliance"], 1) if not full else a["compliance"],
                pass_threshold=self.s.pass_threshold,
            )
        finally:
            self.alloc.release_loans()

    # ── the run ────────────────────────────────────────────────────────────
    async def run(self, request: str) -> RunResult:
        res = RunResult(status="rejected", request=request, allocation=self.alloc)
        prev_reasons: list[str] = []
        try:
            self._phase("Kapı 1 — independent framing")
            fr = await gates.frame(self.swarm, request, self.alloc["framing"])
            res.frame = fr
            self._phase("Recon + domain experts")
            intel, experts = await asyncio.gather(self._recon(fr), self._experts(fr))
            tests: list[gates.TestCase] | None = None
            feedback: list[str] = []

            for rnd in range(1, self.s.max_rounds + 1):
                res.rounds = rnd
                log_start = len(self.irade.log)
                self._phase(f"Round {rnd}: planning (IRADE selects)")
                plan = await self._plan(fr, intel, experts, feedback)
                approaches = await self._approaches(fr, plan)

                self._phase(f"Round {rnd}: independent production ∥ test design")
                if tests is None:
                    cands, tests = await asyncio.gather(
                        self._produce(rnd, fr, plan, intel, experts, approaches, feedback),
                        gates.design_tests(self.swarm, fr, self.alloc["test_design"]),
                    )
                else:
                    cands = await self._produce(rnd, fr, plan, intel, experts, approaches, feedback)
                self.observer.check_candidates(
                    [c.solution for c in cands], [c.approach for c in cands]
                )
                if not cands:
                    feedback = ["No builder produced a usable candidate."]
                    continue

                self._phase(f"Round {rnd}: Kapı 2 — reality filter")
                reports = await self._gate2(fr, cands, tests, full=True)
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
                    worst = sorted(cands, key=lambda c: reports[c.id].pass_rate, reverse=True)[:3]
                    feedback = [f.text for c in worst for f in reports[c.id].findings[:3]] or [
                        "No candidate passed the tests."
                    ]
                    continue
                # Keep approach diversity in the shortlist: best per approach first.
                shortlist: list[Candidate] = []
                for c in passed:
                    if c.approach not in {s.approach for s in shortlist}:
                        shortlist.append(c)
                shortlist += [c for c in passed if c not in shortlist]
                shortlist = shortlist[: self.s.shortlist]

                self._phase(f"Round {rnd}: cross-critique + evolutionary revision")
                revised = await self._cross_critique(shortlist)

                self._phase(f"Round {rnd}: IRADE synthesis decision")
                decision = await self.irade.decide(
                    DecisionRequest(
                        kind="synthesis",
                        question="Which candidate should be the primary basis of the final deliverable?",
                        options=[
                            Option(c.id, f"{c.solution}\n\n[Kapı 2] {reports[c.id].evidence()}")
                            for c in revised
                        ],
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
                res.final_gate, res.deliverable = final_rep, deliverable
                if not final_rep.passed:
                    feedback = [f.text for f in final_rep.findings[:6]] or [
                        "Integrated deliverable failed the tests."
                    ]
                    res.notes.append(
                        f"round {rnd}: integrated deliverable failed the system re-test"
                    )
                    continue

                self._phase(f"Round {rnd}: polish + Kapı 3 blind approval")
                deliverable = await self._polish(fr, deliverable)
                res.deliverable = deliverable
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
                    res.status = "accepted"
                    break
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

        self.observer.check_decisions(self.irade.tier_counts())
        self.observer.check_swarm(self.swarm)
        res.decisions = list(self.irade.log)
        res.warnings = list(self.observer.warnings)
        res.metrics = dict(self.observer.metrics)
        if res.status != "budget":
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
            except PoolExhausted:
                pass
        res.calls_by_block = self.swarm.calls_by_block()
        res.failed_by_block = self.swarm.failed_by_block()
        res.tokens = self.swarm.used_tokens
        return res
