"""Temporal Causal Memory Decay Forecast (PLAN-SINGULARITY S4).

Projects Milyonus's real `memory.trust` half-life decay model forward in time
(`7..365` days) to give operators predictive visibility before critical beliefs
silently auto-demote to quarantine:
  - Exact `days_until_demotion` cliff per active memory item,
  - Cross-referenced with H1's PageRank belief centrality to compute a weighted
    `amnesia_risk_score` (0–100),
  - Multi-point time-series curve (`day`, `avg_trust`, `surviving_active`) for
    CLI tables and Web SVG forecasting charts,
  - Prioritized Reaffirmation Schedule ranked by `centrality × urgency`.

Strictly read-only — NEVER mutates `memory` or `memory_ledger`.
"""

from __future__ import annotations

import math
import time
from dataclasses import asdict, dataclass, field
from typing import Any

from milyonus.config.schema import MemoryConfig
from milyonus.memory.graph import build_epistemic_graph
from milyonus.memory.store import MemoryStore
from milyonus.memory.trust import current_trust, half_life_seconds

_DAY = 86400.0


@dataclass(slots=True)
class ItemForecast:
    id: str
    content: str
    trust_tier: str
    sensitivity: str
    current_trust: float
    projected_trust: float
    days_until_demotion: float | None  # None = T0 immortal
    centrality: float
    priority_score: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class MemoryForecastReport:
    horizon_days: int
    demote_floor: float
    active_now: int
    surviving_at_horizon: int
    at_risk_count: int
    amnesia_risk_score: int  # 0..100
    curve: list[dict[str, Any]] = field(default_factory=list)
    reaffirm_schedule: list[ItemForecast] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "horizon_days": self.horizon_days,
            "demote_floor": self.demote_floor,
            "active_now": self.active_now,
            "surviving_at_horizon": self.surviving_at_horizon,
            "at_risk_count": self.at_risk_count,
            "amnesia_risk_score": self.amnesia_risk_score,
            "curve": self.curve,
            "reaffirm_schedule": [i.to_dict() for i in self.reaffirm_schedule],
        }


def _days_until_floor(
    *,
    tier: str,
    last_reaffirmed_at: float | None,
    ceiling: float,
    sensitivity: str,
    now: float,
    config: MemoryConfig,
) -> float | None:
    hl = half_life_seconds(tier, config, sensitivity)  # type: ignore[arg-type]
    if hl is None:
        return None
    floor = max(0.01, float(config.trust_demote_floor))
    cur = current_trust(
        tier,  # type: ignore[arg-type]
        last_reaffirmed_at,
        now,
        config,
        ceiling=ceiling,
        sensitivity=sensitivity,
    )
    if cur <= floor:
        return 0.0
    # cur * 0.5^(dt / hl) = floor  =>  dt = hl * log2(cur / floor)
    dt_seconds = hl * math.log2(cur / floor)
    return round(max(0.0, dt_seconds / _DAY), 1)


def forecast_memory_decay(
    store: MemoryStore,
    *,
    horizon_days: int = 90,
    config: MemoryConfig | None = None,
    now: float | None = None,
) -> MemoryForecastReport:
    """Project verified memory trust decay across `horizon_days` (strictly read-only)."""
    cfg = config or MemoryConfig()
    horizon = max(1, min(int(horizon_days), 365))
    ts = now if now is not None else time.time()
    active = store.active(limit=500)
    floor = float(cfg.trust_demote_floor)

    graph = build_epistemic_graph(store)
    centrality_map = {n.id: n.centrality for n in graph.nodes if n.kind == "memory"}

    # Build 8 evenly spaced time-series points across [0, horizon].
    sample_days = sorted({0, *{round(horizon * i / 7) for i in range(1, 8)}})
    curve: list[dict[str, Any]] = []
    for d in sample_days:
        future_ts = ts + d * _DAY
        if not active:
            curve.append({"day": d, "avg_trust": 1.0, "surviving_active": 0})
            continue
        scores = [
            current_trust(
                m.trust_tier,
                m.last_reaffirmed_at or m.verified_at or m.created_at,
                future_ts,
                cfg,
                ceiling=m.trust_ceiling,
                sensitivity=m.sensitivity,
            )
            for m in active
        ]
        curve.append(
            {
                "day": d,
                "avg_trust": round(sum(scores) / len(scores), 4),
                "surviving_active": sum(1 for s in scores if s >= floor),
            }
        )

    horizon_ts = ts + horizon * _DAY
    forecasts: list[ItemForecast] = []
    at_risk_weight = 0.0
    total_weight = 0.0

    for m in active:
        anchor = m.last_reaffirmed_at or m.verified_at or m.created_at
        cur = current_trust(
            m.trust_tier, anchor, ts, cfg, ceiling=m.trust_ceiling, sensitivity=m.sensitivity
        )
        proj = current_trust(
            m.trust_tier,
            anchor,
            horizon_ts,
            cfg,
            ceiling=m.trust_ceiling,
            sensitivity=m.sensitivity,
        )
        days_left = _days_until_floor(
            tier=m.trust_tier,
            last_reaffirmed_at=anchor,
            ceiling=m.trust_ceiling,
            sensitivity=m.sensitivity,
            now=ts,
            config=cfg,
        )
        cent = centrality_map.get(m.id, 0.05)
        w = max(0.05, cent)
        total_weight += w
        urgency = 0.0 if days_left is None else max(0.0, 1.0 - min(days_left, horizon) / horizon)
        if proj < floor:
            at_risk_weight += w
        forecasts.append(
            ItemForecast(
                id=m.id,
                content=m.content[:120],
                trust_tier=m.trust_tier,
                sensitivity=m.sensitivity,
                current_trust=round(cur, 3),
                projected_trust=round(proj, 3),
                days_until_demotion=days_left,
                centrality=round(cent, 4),
                priority_score=round(w * (0.3 + urgency), 4),
            )
        )

    forecasts.sort(
        key=lambda f: (
            -f.priority_score,
            f.days_until_demotion if f.days_until_demotion is not None else 99999.0,
        )
    )
    surviving = sum(1 for f in forecasts if f.projected_trust >= floor)
    at_risk = len(forecasts) - surviving
    amnesia = int(round((at_risk_weight / total_weight) * 100)) if total_weight > 0 else 0

    return MemoryForecastReport(
        horizon_days=horizon,
        demote_floor=floor,
        active_now=len(active),
        surviving_at_horizon=surviving,
        at_risk_count=at_risk,
        amnesia_risk_score=max(0, min(100, amnesia)),
        curve=curve,
        reaffirm_schedule=forecasts[:30],
    )
