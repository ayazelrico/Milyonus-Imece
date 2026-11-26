"""Sleep-time memory consolidation (PLAN §4.7).

A background pass that runs when the agent is idle or on a cron schedule. It does
the housekeeping that keeps verified memory healthy without adding latency to a
live turn:

  - process pending quarantine items (verify + promote/reject),
  - expire due third-party claims,
  - drop exact-duplicate active memories (keep the highest-trust one),
  - flag contradictory pairs for review.

Everything it does is ledgered by the store, so `milyonus audit log` shows what
changed overnight. This is the "learns while it sleeps" behavior, made safe by
the same pipeline that gates live writes.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from milyonus.memory.negative import jaccard
from milyonus.memory.pipeline import MemoryPipeline
from milyonus.memory.trust import current_trust

_TIER_RANK = {"T0": 0, "T1": 1, "T2": 2, "T3": 3, "T4": 4}


@dataclass(slots=True)
class ConsolidationReport:
    processed: dict[str, int] = field(default_factory=dict)
    expired: int = 0
    deduped: int = 0
    demoted: int = 0
    contradictions: list[tuple[str, str]] = field(default_factory=list)

    def summary(self) -> str:
        p = self.processed
        return (
            f"processed: {p.get('active', 0)} active / {p.get('rejected', 0)} rejected / "
            f"{p.get('pending', 0)} pending · expired: {self.expired} · "
            f"deduped: {self.deduped} · demoted: {self.demoted} · "
            f"contradictions: {len(self.contradictions)}"
        )


def _has_negation(text: str) -> bool:
    low = text.lower()
    return any(w in low for w in (" değil", " yok", " not ", " no ", "n't"))


async def consolidate(
    pipeline: MemoryPipeline,
    *,
    contradiction_threshold: float = 0.9,
    semantic_dedup_threshold: float = 0.92,
) -> ConsolidationReport:
    store = pipeline.store
    report = ConsolidationReport()

    # 1. Work through the quarantine.
    report.processed = await pipeline.process_pending()

    # 2. Expire due third-party claims.
    report.expired = len(store.expire_due())

    # 2b. Trust decay — promotion is a security boundary, not permanent belief.
    # Recompute each active memory's trust; demote below the floor back to
    # quarantine (re-validatable) so unrenewed trust falls on its own.
    now = time.time()
    for m in store.active():
        score = current_trust(
            m.trust_tier,
            m.last_reaffirmed_at,
            now,
            pipeline.config,
            ceiling=m.trust_ceiling,
            sensitivity=m.sensitivity,
        )
        store.update_trust_score(m.id, score)
        if score < pipeline.config.trust_demote_floor:
            store.demote_to_quarantine(
                m.id, reason=f"trust decayed to {score:.2f} — needs reconfirmation"
            )
            report.demoted += 1

    # 3. Dedupe exact-content active memories (keep highest trust).
    active = store.active()
    by_content: dict[str, list] = {}
    for m in active:
        by_content.setdefault(m.content.strip(), []).append(m)
    for _content, group in by_content.items():
        if len(group) < 2:
            continue
        group.sort(key=lambda m: _TIER_RANK.get(m.trust_tier, 9))
        for dup in group[1:]:
            store.mark_rejected(dup.id, reason="duplicate memory merged")
            report.deduped += 1

    # 3b. Dedupe semantic near-duplicates when the embedding layer is enabled
    #     (same polarity, keeping the highest-trust tier).
    sem = getattr(pipeline, "semantic", None)
    embedder = getattr(sem, "embedder", None) if sem is not None else None
    if embedder is not None:
        from milyonus.memory.vector import cosine

        candidates = sorted(
            store.active(),
            key=lambda m: (_TIER_RANK.get(m.trust_tier, 9), m.created_at),
        )
        if len(candidates) >= 2:
            try:
                vecs = embedder.embed([m.content for m in candidates])
            except Exception:  # noqa: BLE001 - degrade cleanly
                vecs = []
            dropped: set[str] = set()
            for i, a in enumerate(candidates):
                if a.id in dropped or i >= len(vecs):
                    continue
                for j in range(i + 1, len(candidates)):
                    b = candidates[j]
                    if b.id in dropped or j >= len(vecs):
                        continue
                    if _has_negation(a.content) != _has_negation(b.content):
                        continue
                    if cosine(vecs[i], vecs[j]) >= semantic_dedup_threshold:
                        store.mark_rejected(b.id, reason=f"semantic duplicate of {a.id} merged")
                        dropped.add(b.id)
                        report.deduped += 1

    # 4. Flag likely contradictions (very similar content, opposite polarity is
    #    hard to detect lexically, so we surface high-similarity distinct pairs
    #    for human review rather than auto-acting).
    remaining = store.active()
    for i, a in enumerate(remaining):
        for b in remaining[i + 1 :]:
            if a.content == b.content:
                continue
            if (
                _has_negation(a.content) != _has_negation(b.content)
                and jaccard(a.content, b.content) >= contradiction_threshold
            ):
                report.contradictions.append((a.id, b.id))

    return report
