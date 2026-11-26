"""Multi-Agent Collective Economy & Scale Simulator (PLAN-SINGULARITY S10).

Combines Milyonus's real 16-function İmece allocator (`imece.scale.allocate`) with
Pareto model catalog pricing (`providers.pareto.DEFAULT_CATALOG`) to forecast:
  1. Exact per-block agent allocation across any scale (`17 .. 100,000`),
  2. Estimated token volume and USD spend per collective tier:
     - **Frontier-Only Baseline** (every seat on flagship frontier model),
     - **Pareto Hybrid Collective** (workers on high-efficiency Flash/Mini,
       framing/tests/IRADE/Kapı 3 on Sonnet/Opus) → exact `%` USD savings,
  3. Parallel wall-clock ETA given `max_parallel` concurrency,
  4. Analytical Reliability ROI comparing single-agent pass rate `p` vs
     multi-candidate independent-gate ensemble success probability.

Note: USD figures are transparent catalog estimates (not live invoice billing).
"""

from __future__ import annotations

import math
from typing import Any

from milyonus.imece.scale import MIN_TOTAL, allocate
from milyonus.providers.pareto import DEFAULT_CATALOG

# Average tokens per agent invocation by functional block (conservative estimate).
_BLOCK_TOKENS: dict[str, int] = {
    "framing": 2400,
    "test_design": 2200,
    "test_exec": 1600,
    "red_team": 2400,
    "evidence_audit": 1800,
    "compliance": 1600,
    "approval": 2200,
    "irade": 2000,
    "observer": 1800,
}
_DEFAULT_WORKER_TOKENS = 2800

# High-stakes independent blocks that ALWAYS keep frontier/balanced-high models.
_HIGH_STAKES_BLOCKS = {"framing", "test_design", "red_team", "approval", "irade"}


def _price_map() -> dict[str, tuple[float, int]]:
    return {m.model_id: (m.cost_per_1m_usd, m.base_latency_ms) for m in DEFAULT_CATALOG}


def simulate_collective_economy(
    *,
    agents: int = 100,
    rounds: int = 1,
    max_parallel: int = 12,
    worker_model: str = "google/gemini-2.5-flash",
    gate_model: str = "anthropic/claude-sonnet-4",
    baseline_frontier_model: str = "anthropic/claude-opus-4",
    single_agent_pass_prob: float = 0.55,
) -> dict[str, Any]:
    """Forecast token economy, Pareto hybrid savings, ETA, and reliability ROI."""
    clamped_agents = max(MIN_TOTAL, min(100_000, int(agents)))
    clamped_rounds = max(1, min(10, int(rounds)))
    clamped_parallel = max(1, min(256, int(max_parallel)))
    p_single = max(0.05, min(0.99, float(single_agent_pass_prob)))

    alloc = allocate(clamped_agents)
    prices = _price_map()
    w_price, w_lat = prices.get(worker_model, (0.45, 400))
    g_price, g_lat = prices.get(gate_model, (6.00, 920))
    f_price, f_lat = prices.get(baseline_frontier_model, (24.00, 2100))

    blocks_breakdown: list[dict[str, Any]] = []
    total_tokens = 0
    hybrid_usd = 0.0
    frontier_usd = 0.0
    worker_calls = 0
    gate_calls = 0

    for block, count in sorted(alloc.counts.items()):
        tok_per_call = _BLOCK_TOKENS.get(block, _DEFAULT_WORKER_TOKENS)
        blk_tokens = count * tok_per_call * clamped_rounds
        is_high = block in _HIGH_STAKES_BLOCKS
        unit_price = g_price if is_high else w_price
        blk_hybrid = (blk_tokens / 1_000_000.0) * unit_price
        blk_frontier = (blk_tokens / 1_000_000.0) * f_price
        total_tokens += blk_tokens
        hybrid_usd += blk_hybrid
        frontier_usd += blk_frontier
        if is_high:
            gate_calls += count * clamped_rounds
        else:
            worker_calls += count * clamped_rounds
        blocks_breakdown.append(
            {
                "block": block,
                "agents": count,
                "high_stakes": is_high,
                "model": gate_model if is_high else worker_model,
                "est_tokens": blk_tokens,
                "hybrid_usd": round(blk_hybrid, 5),
                "frontier_usd": round(blk_frontier, 5),
            }
        )

    savings_usd = max(0.0, frontier_usd - hybrid_usd)
    savings_pct = round((savings_usd / frontier_usd) * 100.0, 1) if frontier_usd > 0 else 0.0

    # Parallel wall-clock ETA in seconds (sequential barrier overhead + parallel wave batches).
    w_waves = math.ceil(worker_calls / clamped_parallel)
    g_waves = math.ceil(gate_calls / max(1, min(clamped_parallel, 5)))
    est_eta_s = round((w_waves * w_lat + g_waves * g_lat) / 1000.0 + 1.5 * clamped_rounds, 1)
    frontier_eta_s = round(
        (math.ceil((worker_calls + gate_calls) / clamped_parallel) * f_lat) / 1000.0
        + 1.5 * clamped_rounds,
        1,
    )

    # Analytical multi-candidate ensemble reliability (capped conservatively for correlated errors).
    k_eff = min(5.0, 1.0 + math.log2(max(1.0, clamped_agents / 17.0)))
    collective_pass_prob = round(min(0.995, 1.0 - ((1.0 - p_single) ** k_eff)), 4)

    return {
        "agents": clamped_agents,
        "rounds": clamped_rounds,
        "max_parallel": clamped_parallel,
        "worker_model": worker_model,
        "gate_model": gate_model,
        "baseline_frontier_model": baseline_frontier_model,
        "total_est_tokens": total_tokens,
        "hybrid_cost_usd": round(hybrid_usd, 4),
        "frontier_baseline_usd": round(frontier_usd, 4),
        "savings_usd": round(savings_usd, 4),
        "savings_pct": savings_pct,
        "est_wall_clock_s": est_eta_s,
        "frontier_wall_clock_s": frontier_eta_s,
        "single_agent_pass_prob": p_single,
        "estimated_collective_pass_prob": collective_pass_prob,
        "blocks": blocks_breakdown,
    }


def compare_scales(
    scales: tuple[int, ...] = (17, 50, 250, 1000, 10_000),
    *,
    max_parallel: int = 16,
) -> list[dict[str, Any]]:
    """Compare Pareto hybrid cost, frontier cost, savings, and ETA across reference scales."""
    rows: list[dict[str, Any]] = []
    for n in scales:
        sim = simulate_collective_economy(agents=n, max_parallel=max_parallel)
        rows.append(
            {
                "agents": sim["agents"],
                "total_est_tokens": sim["total_est_tokens"],
                "hybrid_cost_usd": sim["hybrid_cost_usd"],
                "frontier_baseline_usd": sim["frontier_baseline_usd"],
                "savings_pct": sim["savings_pct"],
                "est_wall_clock_s": sim["est_wall_clock_s"],
                "estimated_collective_pass_prob": sim["estimated_collective_pass_prob"],
            }
        )
    return rows
