"""Memory Time-Travel & Counterfactual Replay (PLAN-MOONSHOT M1).

Replays the append-only, hash-chained `memory_ledger` from genesis to reconstruct
the exact memory state and `<milyonus:memory>` snapshot that existed at any ledger
sequence number or Unix timestamp — strictly read-only, with per-entry SHA-256
chain verification.

Also supports epoch-to-epoch diffing and zero-mutation counterfactual revocation
simulation ("What would the agent remember if we had never trusted source_uri?").
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any

from milyonus.memory.store import _GENESIS, MemoryStore


@dataclass(slots=True)
class TimelinePoint:
    seq: int
    ts: float
    action: str
    item_id: str | None
    detail: dict[str, Any]
    entry_hash: str
    prev_hash: str
    valid_link: bool
    preview: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ReconstructedItem:
    id: str
    content: str
    trust_tier: str
    state: str
    trust_ceiling: float = 1.0
    reaffirm_count: int = 0
    source_uri: str | None = None
    derived_from: str | None = None
    last_seq: int = 0
    last_action: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class MemorySnapshotAt:
    seq: int
    timestamp: float | None
    chain_intact: bool
    ledger_head: str
    items: list[ReconstructedItem] = field(default_factory=list)
    active_count: int = 0
    pending_count: int = 0
    revoked_count: int = 0
    rendered_snapshot: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "seq": self.seq,
            "timestamp": self.timestamp,
            "chain_intact": self.chain_intact,
            "ledger_head": self.ledger_head,
            "active_count": self.active_count,
            "pending_count": self.pending_count,
            "revoked_count": self.revoked_count,
            "rendered_snapshot": self.rendered_snapshot,
            "items": [i.to_dict() for i in self.items],
        }


@dataclass(slots=True)
class MemoryDiff:
    from_seq: int
    to_seq: int
    added: list[dict[str, Any]] = field(default_factory=list)
    removed: list[dict[str, Any]] = field(default_factory=list)
    state_changed: list[dict[str, Any]] = field(default_factory=list)
    unchanged_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class CounterfactualReport:
    source_uri: str
    affected_ids: list[str]
    direct_count: int
    derived_count: int
    before_active_count: int
    after_active_count: int
    removed_contents: list[str]
    tokens_freed_estimate: int
    rendered_before: str
    rendered_after: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _render_active(items: list[ReconstructedItem], *, char_cap: int = 2400) -> str:
    """Render reconstructed active memory in the live `<milyonus:memory>` format."""
    active = [i for i in items if i.state == "active" and i.content]
    if not active:
        return ""
    tier_order = {"T0": 0, "T1": 1, "T2": 2, "T3": 3, "T4": 4}
    active.sort(key=lambda x: (tier_order.get(x.trust_tier, 9), x.id))
    lines = ["<milyonus:memory>"]
    used = len(lines[0]) + len("</milyonus:memory>") + 2
    for item in active:
        line = f"- [{item.trust_tier}] {item.content}"
        if used + len(line) + 1 > char_cap:
            break
        lines.append(line)
        used += len(line) + 1
    lines.append("</milyonus:memory>")
    return "\n".join(lines)


def _load_item_metadata(store: MemoryStore) -> dict[str, dict[str, Any]]:
    rows = store._conn.execute(  # noqa: SLF001 - internal read-only lookup
        "SELECT id, content, trust_tier, source_uri, derived_from FROM memory"
    ).fetchall()
    return {
        str(r["id"]): {
            "content": str(r["content"] or ""),
            "trust_tier": str(r["trust_tier"]),
            "source_uri": r["source_uri"],
            "derived_from": r["derived_from"],
        }
        for r in rows
    }


def _verify_and_read_ledger(
    store: MemoryStore,
    *,
    max_seq: int | None = None,
    at_timestamp: float | None = None,
) -> tuple[list[TimelinePoint], bool, str]:
    rows = store._conn.execute(  # noqa: SLF001 - internal read-only replay
        "SELECT seq, prev_hash, entry_hash, action, item_id, detail, created_at "
        "FROM memory_ledger ORDER BY seq ASC"
    ).fetchall()
    meta = _load_item_metadata(store)
    prev = _GENESIS
    intact = True
    points: list[TimelinePoint] = []
    for row in rows:
        seq = int(row["seq"])
        ts = float(row["created_at"])
        if max_seq is not None and seq > max_seq:
            break
        if at_timestamp is not None and ts > at_timestamp:
            break
        detail = json.loads(row["detail"]) if row["detail"] else {}
        body = json.dumps(
            {
                "action": row["action"],
                "item_id": row["item_id"],
                "detail": detail,
                "ts": ts,
            },
            sort_keys=True,
            ensure_ascii=False,
        )
        expected = hashlib.sha256((prev + body).encode("utf-8")).hexdigest()
        link_ok = row["prev_hash"] == prev and row["entry_hash"] == expected
        if not link_ok:
            intact = False
        prev = str(row["entry_hash"])
        iid = str(row["item_id"]) if row["item_id"] is not None else None
        preview = meta[iid]["content"][:80] if iid and iid in meta else ""
        points.append(
            TimelinePoint(
                seq=seq,
                ts=ts,
                action=str(row["action"]),
                item_id=iid,
                detail=detail,
                entry_hash=str(row["entry_hash"]),
                prev_hash=str(row["prev_hash"]),
                valid_link=link_ok,
                preview=preview,
            )
        )
    return points, intact, prev


def checkpoint_timeline(store: MemoryStore, *, limit: int = 200) -> list[TimelinePoint]:
    """Return the hash-verified ledger timeline (oldest -> newest, capped to last `limit`)."""
    points, _intact, _head = _verify_and_read_ledger(store)
    return points[-limit:] if limit > 0 else points


def reconstruct_at(
    store: MemoryStore,
    *,
    seq: int | None = None,
    at_timestamp: float | None = None,
) -> MemorySnapshotAt:
    """Reconstruct memory state at ledger sequence `seq` or timestamp `at_timestamp`."""
    points, intact, head = _verify_and_read_ledger(store, max_seq=seq, at_timestamp=at_timestamp)
    meta = _load_item_metadata(store)
    items: dict[str, ReconstructedItem] = {}

    for pt in points:
        action = pt.action
        iid = pt.item_id
        if action == "erase":
            for it in items.values():
                it.state = "erased"
                it.content = ""
                it.last_seq = pt.seq
                it.last_action = action
            continue
        if iid is None:
            continue
        m = meta.get(iid, {})
        if iid not in items:
            items[iid] = ReconstructedItem(
                id=iid,
                content=str(m.get("content", "")),
                trust_tier=str(pt.detail.get("tier") or m.get("trust_tier") or "T2"),
                state="pending",
                source_uri=m.get("source_uri"),
                derived_from=m.get("derived_from"),
                last_seq=pt.seq,
                last_action=action,
            )
        cur = items[iid]
        cur.last_seq = pt.seq
        cur.last_action = action
        if action in ("ingest", "propose"):
            cur.state = "pending"
            if "tier" in pt.detail:
                cur.trust_tier = str(pt.detail["tier"])
        elif action == "t0_stage":
            cur.trust_tier = "T0"
            cur.state = "t0_staged"
        elif action in ("promote", "t0_activate"):
            cur.state = "active"
            cur.trust_ceiling = 1.0
        elif action == "reject":
            cur.state = "rejected"
        elif action == "revoke":
            cur.state = "revoked"
        elif action == "demote":
            cur.state = "pending"
        elif action == "expire":
            cur.state = "expired"
        elif action == "supersede":
            cur.state = "superseded"
        elif action == "reaffirm":
            if "ceiling" in pt.detail:
                cur.trust_ceiling = float(pt.detail["ceiling"])
            if "count" in pt.detail:
                cur.reaffirm_count = int(pt.detail["count"])

    ordered = sorted(items.values(), key=lambda x: (x.last_seq, x.id))
    last_seq = points[-1].seq if points else 0
    last_ts = points[-1].ts if points else None
    return MemorySnapshotAt(
        seq=last_seq,
        timestamp=last_ts,
        chain_intact=intact,
        ledger_head=head,
        items=ordered,
        active_count=sum(1 for i in ordered if i.state == "active"),
        pending_count=sum(1 for i in ordered if i.state == "pending"),
        revoked_count=sum(1 for i in ordered if i.state == "revoked"),
        rendered_snapshot=_render_active(ordered),
    )


def diff_snapshots(store: MemoryStore, from_seq: int, to_seq: int) -> MemoryDiff:
    """Compare two ledger epochs (`from_seq` -> `to_seq`) without mutating state."""
    a = reconstruct_at(store, seq=from_seq)
    b = reconstruct_at(store, seq=to_seq)
    map_a = {i.id: i for i in a.items}
    map_b = {i.id: i for i in b.items}
    added: list[dict[str, Any]] = []
    removed: list[dict[str, Any]] = []
    changed: list[dict[str, Any]] = []
    unchanged = 0

    for iid, ib in map_b.items():
        if iid not in map_a:
            added.append(ib.to_dict())
        else:
            ia = map_a[iid]
            if (
                ia.state != ib.state
                or ia.trust_tier != ib.trust_tier
                or abs(ia.trust_ceiling - ib.trust_ceiling) > 1e-6
            ):
                changed.append(
                    {
                        "id": iid,
                        "content": ib.content or ia.content,
                        "from_state": ia.state,
                        "to_state": ib.state,
                        "from_tier": ia.trust_tier,
                        "to_tier": ib.trust_tier,
                        "from_ceiling": ia.trust_ceiling,
                        "to_ceiling": ib.trust_ceiling,
                    }
                )
            else:
                unchanged += 1

    for iid, ia in map_a.items():
        if iid not in map_b:
            removed.append(ia.to_dict())

    return MemoryDiff(
        from_seq=a.seq,
        to_seq=b.seq,
        added=added,
        removed=removed,
        state_changed=changed,
        unchanged_count=unchanged,
    )


def counterfactual_revoke(store: MemoryStore, source_uri: str) -> CounterfactualReport:
    """Simulate revoking `source_uri` (including transitive `derived_from` items)
    without mutating a single row in `memory` or `memory_ledger`."""
    affected = store.preview_revoke_by_source(source_uri)
    affected_set = set(affected)
    current = reconstruct_at(store)

    direct_rows = store._conn.execute(  # noqa: SLF001 - internal read-only lookup
        "SELECT DISTINCT m.id FROM memory m LEFT JOIN memory_confirmations c ON c.item_id=m.id "
        "WHERE (m.source_uri=? OR c.source_uri=?) AND m.state IN ('active','pending')",
        (source_uri, source_uri),
    ).fetchall()
    direct_ids = {str(r["id"]) for r in direct_rows} & affected_set
    derived_count = len(affected_set - direct_ids)

    after_items = [
        ReconstructedItem(
            id=i.id,
            content=i.content,
            trust_tier=i.trust_tier,
            state="revoked" if i.id in affected_set else i.state,
            trust_ceiling=i.trust_ceiling,
            reaffirm_count=i.reaffirm_count,
            source_uri=i.source_uri,
            derived_from=i.derived_from,
            last_seq=i.last_seq,
            last_action=i.last_action,
        )
        for i in current.items
    ]
    removed_contents = [i.content for i in current.items if i.id in affected_set and i.content]
    rendered_before = _render_active(current.items)
    rendered_after = _render_active(after_items)
    freed_chars = max(0, len(rendered_before) - len(rendered_after))

    return CounterfactualReport(
        source_uri=source_uri,
        affected_ids=affected,
        direct_count=len(direct_ids),
        derived_count=derived_count,
        before_active_count=sum(1 for i in current.items if i.state == "active"),
        after_active_count=sum(1 for i in after_items if i.state == "active"),
        removed_contents=removed_contents,
        tokens_freed_estimate=freed_chars // 4,
        rendered_before=rendered_before,
        rendered_after=rendered_after,
    )
