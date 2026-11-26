"""IRADE Constitutional Policy Engine & Live Veto Simulator (PLAN-HYPERNOVA H4).

Allows teams and operators to codify cryptographically hashed organizational
Constitutions (`milyonus.constitution.v1`) that govern IRADE council decisions:
  1. Inviolable Articles — regex/predicate hard-veto laws evaluated over candidate
     proposals, tool calls, or synthesis deliverables.
  2. Custom 6-Dimension IRADE Weights & Veto Floors — tune priorities across
     `(correctness, safety, reversibility, legal, cost, speed)` without ever
     averaging away a violated veto floor.
  3. Live Multi-Constitution Counterfactual Simulator — compare how different
     governance profiles (`balanced-default`, `fortress-security`, `finops-strict`,
     `rapid-research`, or custom policies) change winners, vetoes, and Tier 4
     human escalations side-by-side.
"""

from __future__ import annotations

import hashlib
import json
import re
import statistics
from dataclasses import asdict, dataclass, field
from typing import Any

from milyonus.imece.irade import DIMENSIONS, VETO_DIMENSIONS


@dataclass(slots=True)
class ConstitutionalArticle:
    id: str
    title: str
    pattern: str
    severity: str = "veto"  # "veto" | "escalate_human" | "warn"
    rationale: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ArticleViolation:
    article_id: str
    title: str
    severity: str
    matched_text: str
    rationale: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class Constitution:
    name: str
    version: str
    description: str
    weights: dict[str, float]
    veto_floors: dict[str, float]
    hard_veto_floor: float = 0.25
    escalate_tier4_below_safety: float = 0.65
    articles: list[ConstitutionalArticle] = field(default_factory=list)
    constitution_hash: str = ""

    def __post_init__(self) -> None:
        # Normalize weights over the 6 canonical IRADE dimensions.
        total = sum(max(0.0, float(self.weights.get(d, 0.0))) for d in DIMENSIONS)
        if total <= 0:
            self.weights = dict.fromkeys(DIMENSIONS, round(1.0 / len(DIMENSIONS), 4))
        else:
            self.weights = {
                d: round(max(0.0, float(self.weights.get(d, 0.0))) / total, 4) for d in DIMENSIONS
            }
        if not self.constitution_hash:
            self.constitution_hash = compute_constitution_hash(self)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "milyonus.constitution.v1",
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "weights": self.weights,
            "veto_floors": self.veto_floors,
            "hard_veto_floor": self.hard_veto_floor,
            "escalate_tier4_below_safety": self.escalate_tier4_below_safety,
            "articles": [a.to_dict() for a in self.articles],
            "constitution_hash": self.constitution_hash,
        }


def compute_constitution_hash(c: Constitution) -> str:
    payload = {
        "name": c.name,
        "version": c.version,
        "weights": c.weights,
        "veto_floors": c.veto_floors,
        "hard_veto_floor": c.hard_veto_floor,
        "escalate_tier4_below_safety": c.escalate_tier4_below_safety,
        "articles": [a.to_dict() for a in c.articles],
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


_CORE_ARTICLES: list[ConstitutionalArticle] = [
    ConstitutionalArticle(
        id="ART-01",
        title="No Unsandboxed Remote Code Pipe",
        pattern=r"\b(?:curl|wget)\b[^|\n]{0,120}\|\s*(?:sh|bash|zsh|python)\b",
        severity="veto",
        rationale="Piping remote network output directly into an interpreter violates supply-chain integrity.",
    ),
    ConstitutionalArticle(
        id="ART-02",
        title="No Bulk PII or Credential Export",
        pattern=r"\b(?:export|dump|upload|exfiltrate|email)\b[^.\n]{0,80}\b(?:ssn|passport|private[_\s-]?key|\.env|passwords?|credit\s*card)\b",
        severity="veto",
        rationale="Unredacted sensitive personal or secret material must never leave trust boundaries.",
    ),
    ConstitutionalArticle(
        id="ART-03",
        title="Irreversible Production Mutation Requires Human Tier 4",
        pattern=r"\b(?:drop\s+table|truncate\s+table|rm\s+-rf|force\s+push|delete\s+production)\b",
        severity="escalate_human",
        rationale="Destructive or irreversible production mutations must escalate to Kademe 4 human sign-off.",
    ),
    ConstitutionalArticle(
        id="ART-04",
        title="No Safety Gate Bypass",
        pattern=r"\b(?:skip|disable|bypass)\b[^.\n]{0,48}\b(?:sandbox|verification|approval|gate|audit|tests?)\b",
        severity="veto",
        rationale="Independent verification gates (Kapı 1–3) and approvals are non-negotiable.",
    ),
]


def builtin_constitutions() -> dict[str, Constitution]:
    """Return the 4 audited built-in Milyonus Constitutions."""
    presets = [
        Constitution(
            name="balanced-default",
            version="1.0.0",
            description="Balanced IRADE defaults: strong correctness + safety with practical speed.",
            weights={
                "correctness": 0.28,
                "safety": 0.22,
                "reversibility": 0.16,
                "legal": 0.14,
                "cost": 0.10,
                "speed": 0.10,
            },
            veto_floors={"safety": 0.50, "legal": 0.50, "reversibility": 0.45},
            hard_veto_floor=0.20,
            escalate_tier4_below_safety=0.60,
            articles=list(_CORE_ARTICLES),
        ),
        Constitution(
            name="fortress-security",
            version="1.0.0",
            description="Zero-compromise defense-in-depth for regulated & production security workloads.",
            weights={
                "correctness": 0.22,
                "safety": 0.34,
                "reversibility": 0.20,
                "legal": 0.16,
                "cost": 0.04,
                "speed": 0.04,
            },
            veto_floors={"safety": 0.75, "legal": 0.70, "reversibility": 0.65},
            hard_veto_floor=0.45,
            escalate_tier4_below_safety=0.80,
            articles=[
                *_CORE_ARTICLES,
                ConstitutionalArticle(
                    id="ART-05",
                    title="No Unpinned External Dependencies",
                    pattern=r"\b(?:pip\s+install|npm\s+install)\b[^.\n]{0,60}@latest\b",
                    severity="veto",
                    rationale="Fortress policy requires pinned dependency hashes/versions.",
                ),
            ],
        ),
        Constitution(
            name="finops-strict",
            version="1.0.0",
            description="Cost-disciplined engineering governance emphasizing token & infra ROI.",
            weights={
                "correctness": 0.24,
                "safety": 0.18,
                "reversibility": 0.12,
                "legal": 0.12,
                "cost": 0.24,
                "speed": 0.10,
            },
            veto_floors={"safety": 0.50, "legal": 0.50, "reversibility": 0.40, "cost": 0.50},
            hard_veto_floor=0.25,
            escalate_tier4_below_safety=0.60,
            articles=list(_CORE_ARTICLES),
        ),
        Constitution(
            name="rapid-research",
            version="1.0.0",
            description="High-velocity exploratory prototyping inside isolated sandboxes.",
            weights={
                "correctness": 0.26,
                "safety": 0.16,
                "reversibility": 0.12,
                "legal": 0.10,
                "cost": 0.12,
                "speed": 0.24,
            },
            veto_floors={"safety": 0.45, "legal": 0.45, "reversibility": 0.35},
            hard_veto_floor=0.20,
            escalate_tier4_below_safety=0.50,
            articles=list(_CORE_ARTICLES),
        ),
    ]
    return {c.name: c for c in presets}


def evaluate_text(constitution: Constitution, text: str) -> list[ArticleViolation]:
    """Evaluate text against all Constitutional Articles."""
    violations: list[ArticleViolation] = []
    for art in constitution.articles:
        try:
            m = re.search(art.pattern, text, re.IGNORECASE)
        except re.error:
            continue
        if m:
            violations.append(
                ArticleViolation(
                    article_id=art.id,
                    title=art.title,
                    severity=art.severity,
                    matched_text=m.group(0)[:120],
                    rationale=art.rationale,
                )
            )
    return violations


@dataclass(slots=True)
class ConstitutionalVerdict:
    constitution_name: str
    constitution_hash: str
    winner: str | None
    tier: int
    weighted_scores: dict[str, float]
    vetoed: dict[str, list[str]]
    article_violations: dict[str, list[dict[str, Any]]]
    escalations: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def evaluate_options(
    constitution: Constitution,
    options: list[dict[str, Any]],
) -> ConstitutionalVerdict:
    """Evaluate candidate options (each with `id`, `text`, and `scores: dict[dim, float]`) under a Constitution."""
    weighted: dict[str, float] = {}
    vetoed: dict[str, list[str]] = {}
    all_violations: dict[str, list[dict[str, Any]]] = {}
    escalations: list[str] = []

    for opt in options:
        oid = str(opt["id"])
        text = str(opt.get("text") or opt.get("summary") or "")
        scores = opt.get("scores") or {}
        dim_vals = {d: max(0.0, min(1.0, float(scores.get(d, 0.5)))) for d in DIMENSIONS}
        total = sum(dim_vals[d] * constitution.weights[d] for d in DIMENSIONS)
        weighted[oid] = round(total, 4)

        reasons: list[str] = []
        for dim, floor in constitution.veto_floors.items():
            if dim in dim_vals and dim_vals[dim] < floor:
                reasons.append(f"floor:{dim} ({dim_vals[dim]:.2f} < {floor:.2f})")
        for dim in VETO_DIMENSIONS:
            if dim_vals[dim] < constitution.hard_veto_floor:
                tag = f"hard_veto:{dim} ({dim_vals[dim]:.2f} < {constitution.hard_veto_floor:.2f})"
                if tag not in reasons:
                    reasons.append(tag)

        violations = evaluate_text(constitution, text)
        if violations:
            all_violations[oid] = [v.to_dict() for v in violations]
            for v in violations:
                if v.severity == "veto":
                    reasons.append(f"article:{v.article_id}")
                elif v.severity == "escalate_human":
                    escalations.append(f"{oid} triggered {v.article_id} ({v.title})")

        if reasons:
            vetoed[oid] = reasons

    eligible = [str(o["id"]) for o in options if str(o["id"]) not in vetoed]
    winner = max(eligible, key=lambda oid: weighted[oid]) if eligible else None
    tier = 2

    if winner is None:
        tier = 4
        escalations.append("every option vetoed by constitution")
    else:
        win_opt = next(o for o in options if str(o["id"]) == winner)
        win_safety = float((win_opt.get("scores") or {}).get("safety", 0.5))
        if win_safety < constitution.escalate_tier4_below_safety:
            tier = 4
            escalations.append(
                f"winning option safety {win_safety:.2f} below Tier 4 threshold "
                f"{constitution.escalate_tier4_below_safety:.2f}"
            )
        elif escalations:
            tier = 4
        elif len(weighted) > 1:
            spread = statistics.pstdev(weighted.values())
            if spread < 0.03:
                tier = 3
                escalations.append("near-tie across options — escalated to full IRADE council")

    return ConstitutionalVerdict(
        constitution_name=constitution.name,
        constitution_hash=constitution.constitution_hash,
        winner=winner,
        tier=tier,
        weighted_scores=weighted,
        vetoed=vetoed,
        article_violations=all_violations,
        escalations=list(dict.fromkeys(escalations)),
    )


def simulate_constitutions(
    options: list[dict[str, Any]],
    *,
    names: list[str] | None = None,
    custom_constitutions: list[Constitution] | None = None,
) -> dict[str, Any]:
    """Run a side-by-side counterfactual simulation across multiple Constitutions."""
    presets = builtin_constitutions()
    selected: list[Constitution] = []
    for n in names or list(presets.keys()):
        if n in presets:
            selected.append(presets[n])
    if custom_constitutions:
        selected.extend(custom_constitutions)
    if not selected:
        selected = list(presets.values())

    verdicts = [evaluate_options(c, options) for c in selected]
    unique_winners = {v.winner for v in verdicts}
    return {
        "option_count": len(options),
        "constitutions_tested": [c.name for c in selected],
        "consensus": len(unique_winners) == 1,
        "divergent_winners": sorted(str(w) for w in unique_winners),
        "verdicts": [v.to_dict() for v in verdicts],
    }
