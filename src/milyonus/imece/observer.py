"""Süreç Gözlemcisi — the outside eye on every layer.

Cheap deterministic monitors run after each phase (groupthink, approach
collapse, council bottleneck, failing agents, budget pressure, a round that made
no progress). At the end, observer agents read the run's metrics — never the
deliverable itself — and write a retrospective: what went wrong in the process.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, field

from milyonus.imece.agents import AgentSpec, Swarm, parse_json

_WORD = re.compile(r"\w+", re.UNICODE)


def _tokens(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if len(w) > 3}


def similarity(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def mean_pairwise_similarity(texts: Sequence[str], *, sample: int = 40) -> float:
    texts = list(texts)[:sample]
    pairs = [(i, j) for i in range(len(texts)) for j in range(i + 1, len(texts))]
    if not pairs:
        return 0.0
    return sum(similarity(texts[i], texts[j]) for i, j in pairs) / len(pairs)


@dataclass
class Observer:
    groupthink_threshold: float = 0.6
    council_share_warn: float = 0.25
    warnings: list[str] = field(default_factory=list)
    metrics: dict[str, float] = field(default_factory=dict)

    def warn(self, msg: str) -> None:
        if msg not in self.warnings:
            self.warnings.append(msg)

    def check_candidates(self, solutions: Sequence[str], approaches: Sequence[str]) -> None:
        sim = mean_pairwise_similarity(solutions)
        self.metrics["candidate_similarity"] = round(sim, 3)
        if len(solutions) > 1 and sim > self.groupthink_threshold:
            self.warn(f"groupthink / early convergence: candidates are {sim:.0%} alike")
        distinct = len(set(approaches))
        self.metrics["distinct_approaches"] = distinct
        if len(approaches) >= 4 and distinct < 2:
            self.warn("approach collapse: every builder used the same approach")

    def check_decisions(self, tier_counts: dict[int, int]) -> None:
        total = sum(tier_counts.values())
        if not total:
            return
        council = sum(n for t, n in tier_counts.items() if t >= 2)
        share = council / total
        self.metrics["council_share"] = round(share, 3)
        if total >= 4 and share > self.council_share_warn:
            self.warn(f"council bottleneck risk: {share:.0%} of decisions reached tier ≥2")

    def check_swarm(self, swarm: Swarm) -> None:
        if not swarm.events:
            return
        failed = sum(1 for e in swarm.events if not e.ok)
        rate = failed / len(swarm.events)
        self.metrics["agent_failure_rate"] = round(rate, 3)
        if rate > 0.1:
            self.warn(f"{rate:.0%} of agent runs failed — check providers/keys")
        pressure = swarm.used_tokens / swarm.max_tokens if swarm.max_tokens else 0.0
        self.metrics["budget_pressure"] = round(pressure, 3)
        if pressure > 0.8:
            self.warn(f"token pool {pressure:.0%} spent")

    def check_progress(self, previous_reasons: Sequence[str], reasons: Sequence[str]) -> None:
        if previous_reasons and reasons:
            sim = similarity(" ".join(previous_reasons), " ".join(reasons))
            if sim > 0.5:
                self.warn("no progress: this round was rejected for the same reasons as the last")

    async def retrospective(self, swarm: Swarm, n_agents: int, report: dict) -> list[str]:
        if n_agents <= 0:
            return []
        layers = ("framing", "imece pool", "IRADE council", "gates")
        specs = [
            AgentSpec(
                block="observer",
                role=f"process observer — {layers[i % len(layers)]}",
                seat="observer",
                goal=(
                    f"Look at this run's process metrics with a focus on the {layers[i % len(layers)]} "
                    "layer. What went wrong in the PROCESS (not the answer), and what should change?"
                ),
                context="# Run metrics\n"
                + json.dumps(report, ensure_ascii=False, default=str)[:8000],
                success_criteria=[
                    'Reply with one JSON object: {"issues": ["..."], "changes": ["..."]}'
                ],
            )
            for i in range(n_agents)
        ]
        notes: list[str] = []
        for text in await swarm.run(specs):
            data = parse_json(text) or {}
            for key in ("issues", "changes"):
                for item in data.get(key) or []:
                    s = str(item).strip()
                    if s and s not in notes:
                        notes.append(s)
        return notes[:20]
