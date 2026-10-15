"""ULTRA-APPLY-IRADE: the council that speeds decisions up without owning truth.

Five members, each locked to one perspective and (ideally) each on a different
vendor's model, so their errors are less correlated. Every member scores every
option on six dimensions — never a single number. Safety, legal and
reversibility are veto floors: an option below a floor is out whatever its
total, because an average must not hide a single critical flaw.

Decisions are routed by tier (Kademe):
  0  policy           reversible, low impact            -> no council
  1  precedent (JEV)  same decision seen before, high confidence
  2  fast path        3 of 5 members; accepted only if they agree and nobody vetoes
  3  full council     all 5, plus extra evidence from Kapı 2
  4  human            irreversible, or the council cannot agree
Escalation triggers: low confidence, disagreement, irreversibility, no precedent
(novel decision kind), veto. A random sample of tier 0–1 decisions is re-run
through the council to measure drift (guarantee #6).
"""

from __future__ import annotations

import json
import random
import statistics
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from milyonus.imece.agents import AgentSpec, Swarm, clip, parse_json

DIMENSIONS = ("correctness", "safety", "reversibility", "legal", "cost", "speed")
VETO_DIMENSIONS = ("safety", "legal", "reversibility")

PERSPECTIVES: dict[str, str] = {
    "correctness": "Doğruluk: does it actually solve the framed problem, provably?",
    "risk": "Güvenlik/risk: what can go wrong, who gets hurt, what cannot be undone?",
    "user_impact": "Kullanıcı/etki: does it serve the person who asked, in practice?",
    "cost_speed": "Maliyet/hız: what does it cost in time, money and complexity?",
    "devils_advocate": "Şeytanın avukatı: argue against the favourite; find why it fails.",
}
FAST_PATH = ("correctness", "risk", "devils_advocate")

Impact = Literal["low", "high", "strategic"]

# Fixed packet template (Goodhart guard): option text is clipped to a fixed
# length so a producer cannot win by padding its packet.
OPTION_CHARS = 1200


@dataclass(slots=True)
class Option:
    id: str
    summary: str


@dataclass(slots=True)
class DecisionRequest:
    kind: str  # e.g. "plan_selection", "synthesis"
    question: str
    options: list[Option]
    context: str = ""
    impact: Impact = "high"
    reversible: bool = True


@dataclass(slots=True)
class MemberVote:
    perspective: str
    scores: dict[str, dict[str, float]]  # option id -> dimension -> 0..1
    choice: str | None
    confidence: float
    rationale: str


@dataclass
class Decision:
    request_kind: str
    choice: str | None
    tier: int
    totals: dict[str, float] = field(default_factory=dict)
    vetoed: dict[str, list[str]] = field(default_factory=dict)  # option -> failed dims
    spread: float = 0.0
    vote_share: float = 1.0
    confidence: float = 1.0
    escalations: list[str] = field(default_factory=list)
    rationale: list[str] = field(default_factory=list)
    audit: str | None = None
    # Members whose reply could not be read. They abstain — a missing vote is
    # never scored as 0, or one broken reply could veto every option.
    abstained: list[str] = field(default_factory=list)
    quorum_failed: bool = False

    @property
    def stopped(self) -> bool:
        return self.choice is None


@dataclass
class IradeSettings:
    veto_floor: float = 0.5
    hard_veto_floor: float = 0.2
    spread_threshold: float = 0.15
    min_vote_share: float = 0.6
    min_confidence: float = 0.55
    audit_rate: float = 0.05
    precedent_confidence: float = 0.8


HumanFn = Callable[[DecisionRequest, Decision], Awaitable[str | None]]
EvidenceFn = Callable[[DecisionRequest], Awaitable[str]]


class Calibrator:
    """Tracks stated confidence against real outcomes (Kapı 3 verdicts).

    With enough samples in a 0.1-wide bucket, a stated confidence is replaced
    by the empirical hit-rate of that bucket — "when they said 80%, how often
    were they right?".
    """

    MIN_SAMPLES = 5

    def __init__(self, path: Path | None = None):
        self.path = path
        self.records: list[tuple[float, bool]] = []
        if path and path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                try:
                    row = json.loads(line)
                    self.records.append((float(row["confidence"]), bool(row["correct"])))
                except (ValueError, KeyError, TypeError):
                    continue

    @staticmethod
    def _bucket(c: float) -> int:
        return min(9, max(0, int(c * 10)))

    def adjust(self, confidence: float) -> float:
        b = self._bucket(confidence)
        hits = [ok for c, ok in self.records if self._bucket(c) == b]
        if len(hits) < self.MIN_SAMPLES:
            return confidence
        return sum(hits) / len(hits)

    def record(self, confidence: float, correct: bool) -> None:
        self.records.append((confidence, correct))
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"confidence": confidence, "correct": correct}) + "\n")


def _read_scores(raw: object, ids: list[str]) -> dict[str, dict[str, float]] | None:
    """A vote counts only if it scores every option on every dimension."""
    if not isinstance(raw, dict):
        return None
    out: dict[str, dict[str, float]] = {}
    for oid in ids:
        row = raw.get(oid)
        if not isinstance(row, dict):
            return None
        try:
            out[oid] = {dim: max(0.0, min(1.0, float(row[dim]))) for dim in DIMENSIONS}
        except (KeyError, TypeError, ValueError):
            return None
    return out


def _clamp(v: object) -> float:
    try:
        return max(0.0, min(1.0, float(v)))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


class Irade:
    def __init__(
        self,
        swarm: Swarm,
        *,
        settings: IradeSettings | None = None,
        human: HumanFn | None = None,
        evidence: EvidenceFn | None = None,
        calibrator: Calibrator | None = None,
        rng: random.Random | None = None,
    ):
        self.swarm = swarm
        self.s = settings or IradeSettings()
        self.human = human
        self.evidence = evidence
        self.calibrator = calibrator or Calibrator()
        self.rng = rng or random.Random()
        self.precedents: dict[tuple[str, str], tuple[str, float]] = {}
        self.log: list[Decision] = []

    # ── routing ────────────────────────────────────────────────────────────
    def initial_tier(self, req: DecisionRequest) -> tuple[int, list[str]]:
        reasons: list[str] = []
        if not req.reversible:
            return 4, ["irreversible"]
        if req.impact == "strategic":
            return 3, ["strategic"]
        if req.impact == "high":
            return 2, ["high impact"]
        prec = self.precedents.get(self._precedent_key(req))
        if prec and prec[1] >= self.s.precedent_confidence:
            return 1, ["precedent"]
        if prec is None and req.kind not in {k for k, _ in self.precedents}:
            reasons.append("novel decision kind")
            return 2, reasons
        return 0, ["policy"]

    @staticmethod
    def _precedent_key(req: DecisionRequest) -> tuple[str, str]:
        return (req.kind, " ".join(req.question.lower().split()))

    async def decide(self, req: DecisionRequest) -> Decision:
        if not req.options:
            d = Decision(req.kind, None, 0, escalations=["no options"])
            self.log.append(d)
            return d
        tier, why = self.initial_tier(req)

        if tier == 0:
            d = Decision(req.kind, req.options[0].id, 0, rationale=["policy default"])
            await self._maybe_audit(req, d)
        elif tier == 1:
            choice, conf = self.precedents[self._precedent_key(req)]
            if choice in {o.id for o in req.options}:
                d = Decision(req.kind, choice, 1, confidence=conf, rationale=["JEV precedent"])
                await self._maybe_audit(req, d)
            else:
                d = await self._council(req, FAST_PATH, tier=2)
                d.escalations.append("precedent option missing")
        else:
            if tier == 2:
                d = await self._council(req, FAST_PATH, tier=2)
                triggers = self._triggers(d)
                if triggers:
                    d = await self._full(req)
                    d.escalations = [*why, *triggers]
            else:  # 3 and 4 both start with the full council + extra evidence
                d = await self._full(req)
                d.escalations = list(why)
            if d.tier == 3:
                strict = self._triggers(d, strict=True)
                if strict or tier == 4:
                    d = await self._to_human(req, d, strict)
        if d.tier < 4 and not d.escalations:
            d.escalations = why
        if d.choice is not None:
            self.precedents[self._precedent_key(req)] = (d.choice, d.confidence)
        self.log.append(d)
        return d

    def _triggers(self, d: Decision, *, strict: bool = False) -> list[str]:
        k = 1.5 if strict else 1.0
        out: list[str] = []
        if d.quorum_failed:
            out.append(f"council quorum not met ({len(d.abstained)} abstained)")
        elif d.choice is None:
            out.append("every option vetoed")
        if d.spread > self.s.spread_threshold * k:
            out.append(f"score spread {d.spread:.2f}")
        if d.vote_share < self.s.min_vote_share / k:
            out.append(f"vote share {d.vote_share:.2f}")
        if d.confidence < self.s.min_confidence / k:
            out.append(f"low confidence {d.confidence:.2f}")
        return out

    async def _full(self, req: DecisionRequest) -> Decision:
        extra = ""
        if self.evidence is not None:
            extra = await self.evidence(req)
        full_req = DecisionRequest(
            req.kind,
            req.question,
            req.options,
            context=(req.context + ("\n\n# Extra evidence (Kapı 2)\n" + extra if extra else "")),
            impact=req.impact,
            reversible=req.reversible,
        )
        return await self._council(full_req, tuple(PERSPECTIVES), tier=3)

    async def _to_human(self, req: DecisionRequest, d: Decision, why: list[str]) -> Decision:
        d.tier = 4
        d.escalations.extend(why)
        if self.human is None:
            d.rationale.append("human decision required but no human is attached — stopped")
            d.choice = None
            return d
        picked = await self.human(req, d)
        if picked not in {o.id for o in req.options}:
            d.rationale.append("human stopped the decision")
            d.choice = None
        else:
            d.rationale.append(f"human chose {picked}")
            d.choice = picked
        return d

    async def _maybe_audit(self, req: DecisionRequest, d: Decision) -> None:
        if len(req.options) < 2 or self.rng.random() >= self.s.audit_rate:
            return
        check = await self._council(req, FAST_PATH, tier=2)
        d.audit = "agrees" if check.choice == d.choice else f"council chose {check.choice}"

    # ── the council itself ─────────────────────────────────────────────────
    def _spec(self, req: DecisionRequest, perspective: str) -> AgentSpec:
        options = "\n\n".join(
            f"## Option {o.id}\n{clip(o.summary, OPTION_CHARS)}" for o in req.options
        )
        schema = {
            "scores": {o.id: dict.fromkeys(DIMENSIONS, "0..1") for o in req.options[:1]},
            "choice": "option id",
            "confidence": "0..1",
            "rationale": "one paragraph",
        }
        return AgentSpec(
            block="irade",
            role=f"IRADE council member — {perspective}",
            seat=f"council:{perspective}",
            goal=(
                f"{req.question}\n\nScore EVERY option on every dimension from 0 (worst) to 1 "
                f"(best), strictly from your perspective: {PERSPECTIVES[perspective]} "
                "For 'reversibility', 1 means fully reversible. Then pick one option."
            ),
            context=f"{req.context}\n\n# Options\n{options}",
            success_criteria=[
                "Reply with one JSON object shaped like: " + json.dumps(schema, ensure_ascii=False),
                "Score all options, not only your favourite.",
            ],
            forbidden=["Do not invent options.", "Do not average away a critical flaw."],
        )

    async def _council(
        self, req: DecisionRequest, members: tuple[str, ...], *, tier: int
    ) -> Decision:
        replies = await self.swarm.run([self._spec(req, p) for p in members])
        ids = [o.id for o in req.options]
        votes: list[MemberVote] = []
        abstained: list[str] = []
        for perspective, text in zip(members, replies, strict=True):
            data = parse_json(text) or {}
            raw = data.get("scores") if isinstance(data.get("scores"), dict) else {}
            scores = _read_scores(raw, ids)
            if scores is None:
                abstained.append(perspective)
                continue
            choice = data.get("choice") if data.get("choice") in ids else None
            votes.append(
                MemberVote(
                    perspective,
                    scores,
                    choice,
                    _clamp(data.get("confidence", 0.0)),
                    str(data.get("rationale", ""))[:500],
                )
            )
        quorum = 2 if len(members) <= 3 else 3
        if len(votes) < quorum:
            return Decision(
                request_kind=req.kind,
                choice=None,
                tier=tier,
                abstained=abstained,
                quorum_failed=True,
                confidence=0.0,
                vote_share=0.0,
                rationale=[f"only {len(votes)}/{len(members)} readable votes"],
            )
        d = self._aggregate(req, votes, tier)
        d.abstained = abstained
        return d

    def _aggregate(self, req: DecisionRequest, votes: list[MemberVote], tier: int) -> Decision:
        ids = [o.id for o in req.options]
        totals: dict[str, float] = {}
        vetoed: dict[str, list[str]] = {}
        member_totals: dict[str, list[float]] = {}
        for oid in ids:
            per_dim = {
                dim: statistics.fmean(v.scores[oid][dim] for v in votes) for dim in DIMENSIONS
            }
            totals[oid] = statistics.fmean(per_dim.values())
            failed = [
                dim
                for dim in VETO_DIMENSIONS
                if per_dim[dim] < self.s.veto_floor
                or any(v.scores[oid][dim] < self.s.hard_veto_floor for v in votes)
            ]
            if failed:
                vetoed[oid] = failed
            member_totals[oid] = [statistics.fmean(v.scores[oid].values()) for v in votes]

        eligible = [oid for oid in ids if oid not in vetoed]
        choice = max(eligible, key=lambda o: totals[o]) if eligible else None
        spread = statistics.pstdev(member_totals[choice]) if choice and len(votes) > 1 else 0.0
        vote_share = (
            sum(1 for v in votes if v.choice == choice) / len(votes) if choice and votes else 0.0
        )
        raw_conf = statistics.fmean(v.confidence for v in votes) if votes else 0.0
        return Decision(
            request_kind=req.kind,
            choice=choice,
            tier=tier,
            totals=totals,
            vetoed=vetoed,
            spread=spread,
            vote_share=vote_share,
            confidence=self.calibrator.adjust(raw_conf),
            rationale=[f"{v.perspective}: {v.rationale}" for v in votes if v.rationale],
        )

    def tier_counts(self) -> dict[int, int]:
        out = dict.fromkeys(range(5), 0)
        for d in self.log:
            out[d.tier] += 1
        return out
