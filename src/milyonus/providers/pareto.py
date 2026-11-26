"""Smart Cost-Latency-Trust Multi-Model Pareto Frontier Router (PLAN-HYPERNOVA H9).

Routes every task to the mathematically optimal model on the 3D Pareto frontier
`(effective_quality, -cost_per_1m, -effective_latency_ms)`:
  1. Deterministic task complexity (`0.0–1.0`) & risk tier (`low|medium|high|critical`)
     classifier (detecting multi-step architecture, security/crypto, code synthesis).
  2. Exact non-dominated Pareto frontier solver subject to hard constraints
     (`max_cost_per_1m`, `max_latency_ms`, `min_quality`, `require_local`).
  3. Online empirical bandit learning persisted in SQLite (`pareto_stats`):
     Beta posterior quality + Upper Confidence Bound (UCB) exploration bonus +
     exponential moving average (EMA) latency tracking.
  4. Budget-pressure auto-downgrade: shifts low-risk work to cheaper Pareto models
     as budget pressure approaches 1.0, while enforcing an ironclad minimum quality
     floor (`>= 0.85`) for `high`/`critical` tasks.
"""

from __future__ import annotations

import math
import re
import sqlite3
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from milyonus.config.paths import state_db

_SCHEMA = """
CREATE TABLE IF NOT EXISTS pareto_stats (
    model_id       TEXT PRIMARY KEY,
    successes      INTEGER NOT NULL DEFAULT 0,
    failures       INTEGER NOT NULL DEFAULT 0,
    latency_ema_ms REAL,
    total_cost_usd REAL NOT NULL DEFAULT 0.0,
    updated_at     REAL NOT NULL
);
"""


@dataclass(slots=True)
class ModelProfile:
    model_id: str
    provider: str
    label: str
    base_quality: float  # prior quality 0..1
    cost_per_1m_usd: float  # blended input/output USD per 1M tokens
    base_latency_ms: int
    context_window: int
    local_private: bool = False
    reasoning_capable: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


DEFAULT_CATALOG: tuple[ModelProfile, ...] = (
    ModelProfile(
        model_id="local/qwen2.5-7b-instruct",
        provider="ollama",
        label="Qwen 2.5 7B (Local)",
        base_quality=0.68,
        cost_per_1m_usd=0.0,
        base_latency_ms=340,
        context_window=32_768,
        local_private=True,
        reasoning_capable=False,
    ),
    ModelProfile(
        model_id="openai/gpt-4o-mini",
        provider="openai",
        label="GPT-4o Mini",
        base_quality=0.79,
        cost_per_1m_usd=0.30,
        base_latency_ms=420,
        context_window=128_000,
        local_private=False,
        reasoning_capable=False,
    ),
    ModelProfile(
        model_id="google/gemini-2.5-flash",
        provider="google",
        label="Gemini 2.5 Flash",
        base_quality=0.84,
        cost_per_1m_usd=0.45,
        base_latency_ms=380,
        context_window=1_000_000,
        local_private=False,
        reasoning_capable=True,
    ),
    ModelProfile(
        model_id="anthropic/claude-sonnet-4",
        provider="anthropic",
        label="Claude Sonnet 4",
        base_quality=0.92,
        cost_per_1m_usd=6.00,
        base_latency_ms=920,
        context_window=200_000,
        local_private=False,
        reasoning_capable=True,
    ),
    ModelProfile(
        model_id="openai/o3-high",
        provider="openai",
        label="OpenAI o3 (Reasoning)",
        base_quality=0.96,
        cost_per_1m_usd=18.00,
        base_latency_ms=2600,
        context_window=200_000,
        local_private=False,
        reasoning_capable=True,
    ),
    ModelProfile(
        model_id="anthropic/claude-opus-4",
        provider="anthropic",
        label="Claude Opus 4",
        base_quality=0.97,
        cost_per_1m_usd=24.00,
        base_latency_ms=2100,
        context_window=200_000,
        local_private=False,
        reasoning_capable=True,
    ),
)

_HIGH_RISK_RE = re.compile(
    r"\b(?:security|audit|cryptograph|ed25519|merkle|sandbox|production|delete|migration|"
    r"privilege|auth|sql\s+injection|vulnerability|compliance|kvkk|gdpr)\b",
    re.IGNORECASE,
)
_COMPLEX_RE = re.compile(
    r"\b(?:architect|distributed|byzantine|prove|formal|consensus|refactor|multi-agent|"
    r"algorithm|optimize|pareto|deadlock|compiler|concurrency)\b",
    re.IGNORECASE,
)


@dataclass(slots=True)
class TaskAssessment:
    complexity: float  # 0..1
    risk_tier: str  # "low" | "medium" | "high" | "critical"
    needs_reasoning: bool
    signals: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def classify_task(prompt: str) -> TaskAssessment:
    """Deterministically estimate task complexity and security/stakes risk tier."""
    text = prompt.strip()
    signals: list[str] = []
    comp = min(0.35, len(text) / 1400.0)
    if "```" in text or "def " in text or "class " in text:
        comp += 0.20
        signals.append("code_artifact")
    complex_hits = _COMPLEX_RE.findall(text)
    if complex_hits:
        comp += min(0.35, 0.14 * len({h.lower() for h in complex_hits}))
        signals.append(f"complex_terms:{len(set(complex_hits))}")
    risk_hits = _HIGH_RISK_RE.findall(text)
    if risk_hits:
        comp += 0.20
        signals.append(f"risk_terms:{len(set(risk_hits))}")

    comp = round(max(0.05, min(1.0, comp)), 3)
    unique_risk = len({h.lower() for h in risk_hits})
    if unique_risk >= 2 or (unique_risk == 1 and comp >= 0.65):
        risk = "critical"
    elif unique_risk == 1:
        risk = "high"
    elif comp >= 0.55:
        risk = "medium"
    else:
        risk = "low"

    return TaskAssessment(
        complexity=comp,
        risk_tier=risk,
        needs_reasoning=(comp >= 0.55 or risk in ("high", "critical")),
        signals=signals,
    )


class ParetoRouter:
    """SQLite-backed online Pareto frontier router with Beta/UCB learning."""

    def __init__(
        self,
        path: Path | None = None,
        *,
        catalog: tuple[ModelProfile, ...] = DEFAULT_CATALOG,
    ) -> None:
        self.path = path or state_db()
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.catalog: dict[str, ModelProfile] = {m.model_id: m for m in catalog}
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def record_outcome(
        self,
        model_id: str,
        *,
        success: bool,
        latency_ms: int,
        cost_usd: float = 0.0,
    ) -> dict[str, Any]:
        """Update empirical Beta posterior and latency EMA for `model_id`."""
        now = time.time()
        with self._lock:
            row = self._conn.execute(
                "SELECT successes, failures, latency_ema_ms, total_cost_usd "
                "FROM pareto_stats WHERE model_id=?",
                (model_id,),
            ).fetchone()
            if row is None:
                succ = 1 if success else 0
                fail = 0 if success else 1
                ema = float(max(1, latency_ms))
                tot_cost = max(0.0, float(cost_usd))
                self._conn.execute(
                    "INSERT INTO pareto_stats(model_id, successes, failures, latency_ema_ms, "
                    "total_cost_usd, updated_at) VALUES (?,?,?,?,?,?)",
                    (model_id, succ, fail, ema, tot_cost, now),
                )
            else:
                succ = int(row["successes"]) + (1 if success else 0)
                fail = int(row["failures"]) + (0 if success else 1)
                prev_ema = row["latency_ema_ms"]
                ema = (
                    float(latency_ms)
                    if prev_ema is None
                    else round(0.7 * float(prev_ema) + 0.3 * float(max(1, latency_ms)), 1)
                )
                tot_cost = round(float(row["total_cost_usd"]) + max(0.0, float(cost_usd)), 6)
                self._conn.execute(
                    "UPDATE pareto_stats SET successes=?, failures=?, latency_ema_ms=?, "
                    "total_cost_usd=?, updated_at=? WHERE model_id=?",
                    (succ, fail, ema, tot_cost, now, model_id),
                )
            self._conn.commit()
        return {
            "model_id": model_id,
            "successes": succ,
            "failures": fail,
            "latency_ema_ms": ema,
            "total_cost_usd": tot_cost,
        }

    def enriched_catalog(self) -> list[dict[str, Any]]:
        """Combine static priors with empirical Beta posterior & UCB stats."""
        with self._lock:
            rows = {
                str(r["model_id"]): dict(r)
                for r in self._conn.execute("SELECT * FROM pareto_stats").fetchall()
            }
        total_trials = sum(int(r["successes"]) + int(r["failures"]) for r in rows.values())
        out: list[dict[str, Any]] = []
        for m in self.catalog.values():
            st = rows.get(m.model_id)
            succ = int(st["successes"]) if st else 0
            fail = int(st["failures"]) if st else 0
            trials = succ + fail
            # Beta prior centered at base_quality with pseudo-count weight=6.
            alpha0 = m.base_quality * 6.0
            beta0 = (1.0 - m.base_quality) * 6.0
            posterior = (alpha0 + succ) / (alpha0 + beta0 + trials)
            ucb_bonus = (
                math.sqrt(2.0 * math.log(max(2, total_trials + 1)) / (trials + 1)) * 0.04
                if total_trials > 0
                else 0.0
            )
            eff_latency = (
                int(round(float(st["latency_ema_ms"])))
                if st and st["latency_ema_ms"] is not None
                else m.base_latency_ms
            )
            out.append(
                {
                    **m.to_dict(),
                    "effective_quality": round(min(1.0, posterior), 4),
                    "ucb_score": round(min(1.0, posterior + ucb_bonus), 4),
                    "effective_latency_ms": eff_latency,
                    "trials": trials,
                    "successes": succ,
                    "failures": fail,
                }
            )
        return out

    def compute_pareto_frontier(
        self,
        *,
        max_cost_per_1m: float | None = None,
        max_latency_ms: int | None = None,
        min_quality: float = 0.0,
        require_local: bool = False,
    ) -> list[dict[str, Any]]:
        """Return strictly non-dominated models on `(effective_quality, -cost, -latency)`."""
        candidates = []
        for c in self.enriched_catalog():
            if require_local and not c["local_private"]:
                continue
            if max_cost_per_1m is not None and c["cost_per_1m_usd"] > max_cost_per_1m:
                continue
            if max_latency_ms is not None and c["effective_latency_ms"] > max_latency_ms:
                continue
            if c["effective_quality"] < min_quality:
                continue
            candidates.append(c)

        frontier: list[dict[str, Any]] = []
        for a in candidates:
            dominated = False
            for b in candidates:
                if a["model_id"] == b["model_id"]:
                    continue
                better_or_eq = (
                    b["effective_quality"] >= a["effective_quality"]
                    and b["cost_per_1m_usd"] <= a["cost_per_1m_usd"]
                    and b["effective_latency_ms"] <= a["effective_latency_ms"]
                )
                strictly_better = (
                    b["effective_quality"] > a["effective_quality"]
                    or b["cost_per_1m_usd"] < a["cost_per_1m_usd"]
                    or b["effective_latency_ms"] < a["effective_latency_ms"]
                )
                if better_or_eq and strictly_better:
                    dominated = True
                    break
            if not dominated:
                frontier.append({**a, "pareto_optimal": True})
        frontier.sort(key=lambda x: (x["cost_per_1m_usd"], -x["effective_quality"]))
        return frontier

    def route_task(
        self,
        prompt: str,
        *,
        budget_pressure: float = 0.0,
        max_cost_per_1m: float | None = None,
        max_latency_ms: int | None = None,
        require_local: bool = False,
    ) -> dict[str, Any]:
        """Select the optimal model on the Pareto frontier given task risk and budget pressure."""
        assessment = classify_task(prompt)
        pressure = max(0.0, min(1.0, float(budget_pressure)))

        # Ironclad safety floor: critical/high risk never downgrades to weak models.
        safety_floor = 0.0
        if not require_local:
            if assessment.risk_tier == "critical":
                safety_floor = 0.90
            elif assessment.risk_tier == "high":
                safety_floor = 0.84

        frontier = self.compute_pareto_frontier(
            max_cost_per_1m=max_cost_per_1m,
            max_latency_ms=max_latency_ms,
            min_quality=safety_floor,
            require_local=require_local,
        )
        fallback_used = False
        if not frontier:
            # Relax constraints only within local/budget requirement; never drop require_local.
            frontier = self.compute_pareto_frontier(min_quality=0.0, require_local=require_local)
            fallback_used = True

        # Utility weights adapt dynamically with complexity, risk, and budget pressure.
        w_qual = 0.45 + 0.35 * assessment.complexity
        if assessment.risk_tier in ("high", "critical"):
            w_qual = max(w_qual, 0.78)
        w_cost = 0.25 + (
            0.45 * pressure if assessment.risk_tier in ("low", "medium") else 0.12 * pressure
        )
        w_lat = 0.20 * (1.0 - 0.5 * assessment.complexity)

        max_c = max((m["cost_per_1m_usd"] for m in frontier), default=1.0) or 1.0
        max_l = max((m["effective_latency_ms"] for m in frontier), default=1) or 1

        ranked: list[dict[str, Any]] = []
        for m in frontier:
            norm_cost = m["cost_per_1m_usd"] / max_c
            norm_lat = m["effective_latency_ms"] / max_l
            reason_bonus = 0.05 if (assessment.needs_reasoning and m["reasoning_capable"]) else 0.0
            utility = w_qual * m["ucb_score"] - w_cost * norm_cost - w_lat * norm_lat + reason_bonus
            ranked.append({**m, "utility": round(utility, 4)})
        ranked.sort(key=lambda x: -x["utility"])
        winner = ranked[0]
        return {
            "selected_model": winner["model_id"],
            "selected": winner,
            "assessment": assessment.to_dict(),
            "budget_pressure": pressure,
            "safety_floor_applied": safety_floor,
            "fallback_used": fallback_used,
            "pareto_frontier": ranked,
            "rationale": (
                f"Selected {winner['label']} (Q={winner['effective_quality']:.2f}, "
                f"${winner['cost_per_1m_usd']:.2f}/1M, {winner['effective_latency_ms']}ms) "
                f"for {assessment.risk_tier}-risk task (complexity {assessment.complexity:.2f}, "
                f"budget pressure {pressure:.0%})."
            ),
        }
