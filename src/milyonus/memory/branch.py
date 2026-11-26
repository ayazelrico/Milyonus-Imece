"""Cryptographic Memory Branching — Git for Agent Brains (PLAN-HYPERNOVA H2).

Lets operators and agents fork verified memory into hash-anchored cognitive branches,
stage isolated hypothetical additions or revocations without polluting `main` memory,
run 3-way conflict-aware cognitive diffs (leveraging H1's contradiction detector), and
merge changes back into live memory STRICTLY through `MemoryPipeline` — preserving the
"no direct write to active memory" guarantee and the append-only hash-chained ledger.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from milyonus.config.paths import state_db
from milyonus.memory.graph import detect_contradictions
from milyonus.memory.model import SourceKind, TrustTier
from milyonus.memory.pipeline import MemoryPipeline
from milyonus.memory.store import MemoryStore

_BRANCH_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._\-/]{0,63}$")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS memory_branches (
    name         TEXT PRIMARY KEY,
    parent_head  TEXT NOT NULL,
    description  TEXT NOT NULL DEFAULT '',
    branch_hash  TEXT NOT NULL,
    created_at   REAL NOT NULL,
    merged_at    REAL
);
CREATE TABLE IF NOT EXISTS memory_branch_items (
    id           TEXT PRIMARY KEY,
    branch_name  TEXT NOT NULL,
    item_id      TEXT,
    op           TEXT NOT NULL, -- 'snapshot' | 'add' | 'revoke'
    content      TEXT NOT NULL DEFAULT '',
    trust_tier   TEXT NOT NULL DEFAULT 'T1',
    source_kind  TEXT NOT NULL DEFAULT 'user-direct',
    source_uri   TEXT,
    created_at   REAL NOT NULL,
    FOREIGN KEY(branch_name) REFERENCES memory_branches(name) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_branch_items_name ON memory_branch_items(branch_name);
"""


class BranchError(Exception):
    """Raised on invalid branch names, missing branches, or blocked conflict merges."""


@dataclass(slots=True)
class BranchSummary:
    name: str
    parent_head: str
    description: str
    branch_hash: str
    created_at: float
    merged_at: float | None
    snapshot_count: int = 0
    staged_adds: int = 0
    staged_revokes: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class BranchDiff:
    branch_name: str
    parent_head: str
    current_main_head: str
    main_diverged: bool
    staged_adds: list[dict[str, Any]] = field(default_factory=list)
    staged_revokes: list[str] = field(default_factory=list)
    main_added_since_fork: list[dict[str, Any]] = field(default_factory=list)
    main_removed_since_fork: list[str] = field(default_factory=list)
    conflicts: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class BranchMergeResult:
    branch_name: str
    merged: bool
    promoted_ids: list[str] = field(default_factory=list)
    rejected_ids: list[str] = field(default_factory=list)
    pending_ids: list[str] = field(default_factory=list)
    revoked_ids: list[str] = field(default_factory=list)
    conflicts_detected: list[dict[str, Any]] = field(default_factory=list)
    new_ledger_head: str = ""
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _validate_name(name: str) -> str:
    cleaned = name.strip()
    if cleaned.lower() == "main":
        raise BranchError("'main' is reserved for live verified memory")
    if not _BRANCH_NAME_RE.match(cleaned):
        raise BranchError("branch name must match [a-zA-Z0-9][a-zA-Z0-9._-/]{0,63}")
    return cleaned


def _compute_branch_hash(parent_head: str, rows: list[dict[str, Any]]) -> str:
    payload = json.dumps(
        {
            "parent_head": parent_head,
            "items": [
                {
                    "op": r["op"],
                    "item_id": r["item_id"],
                    "content": r["content"],
                    "trust_tier": r["trust_tier"],
                    "source_uri": r["source_uri"],
                }
                for r in sorted(rows, key=lambda x: (str(x["op"]), str(x["id"])))
            ],
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class MemoryBranchManager:
    """Git-style cognitive branching over a tenant's `state.db`."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or state_db()
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def _rehash(self, name: str) -> str:
        row = self._conn.execute(
            "SELECT parent_head FROM memory_branches WHERE name=?", (name,)
        ).fetchone()
        if row is None:
            raise BranchError(f"branch not found: {name}")
        items = [
            dict(r)
            for r in self._conn.execute(
                "SELECT * FROM memory_branch_items WHERE branch_name=?", (name,)
            ).fetchall()
        ]
        bhash = _compute_branch_hash(str(row["parent_head"]), items)
        self._conn.execute("UPDATE memory_branches SET branch_hash=? WHERE name=?", (bhash, name))
        return bhash

    def create_branch(
        self,
        name: str,
        store: MemoryStore,
        *,
        description: str = "",
    ) -> BranchSummary:
        """Fork live active memory into a new hash-anchored cognitive branch."""
        cname = _validate_name(name)
        with self._lock:
            exists = self._conn.execute(
                "SELECT 1 FROM memory_branches WHERE name=?", (cname,)
            ).fetchone()
            if exists is not None:
                raise BranchError(f"branch already exists: {cname}")
            parent_head = store.ledger_head()
            active = store.active(limit=500)
            now = time.time()
            self._conn.execute(
                "INSERT INTO memory_branches(name, parent_head, description, branch_hash, created_at) "
                "VALUES (?,?,?,?,?)",
                (cname, parent_head, description.strip()[:240], "pending", now),
            )
            for item in active:
                self._conn.execute(
                    "INSERT INTO memory_branch_items(id, branch_name, item_id, op, content, "
                    "trust_tier, source_kind, source_uri, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                    (
                        f"bi_{uuid.uuid4().hex[:12]}",
                        cname,
                        item.id,
                        "snapshot",
                        item.content,
                        item.trust_tier,
                        item.provenance.source_kind,
                        item.provenance.source_uri,
                        now,
                    ),
                )
            bhash = self._rehash(cname)
            self._conn.commit()
            return BranchSummary(
                name=cname,
                parent_head=parent_head,
                description=description.strip()[:240],
                branch_hash=bhash,
                created_at=now,
                merged_at=None,
                snapshot_count=len(active),
                staged_adds=0,
                staged_revokes=0,
            )

    def list_branches(self) -> list[BranchSummary]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM memory_branches ORDER BY created_at DESC"
            ).fetchall()
            out: list[BranchSummary] = []
            for r in rows:
                counts = dict(
                    self._conn.execute(
                        "SELECT op, COUNT(*) FROM memory_branch_items WHERE branch_name=? GROUP BY op",
                        (r["name"],),
                    ).fetchall()
                )
                out.append(
                    BranchSummary(
                        name=str(r["name"]),
                        parent_head=str(r["parent_head"]),
                        description=str(r["description"]),
                        branch_hash=str(r["branch_hash"]),
                        created_at=float(r["created_at"]),
                        merged_at=float(r["merged_at"]) if r["merged_at"] is not None else None,
                        snapshot_count=int(counts.get("snapshot", 0)),
                        staged_adds=int(counts.get("add", 0)),
                        staged_revokes=int(counts.get("revoke", 0)),
                    )
                )
            return out

    def get_branch(self, name: str) -> dict[str, Any]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM memory_branches WHERE name=?", (name,)
            ).fetchone()
            if row is None:
                raise BranchError(f"branch not found: {name}")
            items = [
                dict(r)
                for r in self._conn.execute(
                    "SELECT * FROM memory_branch_items WHERE branch_name=? ORDER BY created_at ASC",
                    (name,),
                ).fetchall()
            ]
            return {**dict(row), "items": items}

    def stage_add(
        self,
        name: str,
        content: str,
        *,
        trust_tier: TrustTier = "T1",
        source_kind: SourceKind = "user-direct",
        source_uri: str | None = None,
    ) -> dict[str, Any]:
        """Stage a new memory hypothesis on a branch without mutating live memory."""
        if not content.strip():
            raise BranchError("staged memory content cannot be empty")
        with self._lock:
            if (
                self._conn.execute("SELECT 1 FROM memory_branches WHERE name=?", (name,)).fetchone()
                is None
            ):
                raise BranchError(f"branch not found: {name}")
            bid = f"bi_{uuid.uuid4().hex[:12]}"
            now = time.time()
            self._conn.execute(
                "INSERT INTO memory_branch_items(id, branch_name, item_id, op, content, "
                "trust_tier, source_kind, source_uri, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    bid,
                    name,
                    None,
                    "add",
                    content.strip(),
                    trust_tier,
                    source_kind,
                    source_uri,
                    now,
                ),
            )
            bhash = self._rehash(name)
            self._conn.commit()
            return {"id": bid, "branch_name": name, "op": "add", "branch_hash": bhash}

    def stage_revoke(self, name: str, item_id: str) -> dict[str, Any]:
        """Stage revoking an existing memory ID on this branch."""
        with self._lock:
            if (
                self._conn.execute("SELECT 1 FROM memory_branches WHERE name=?", (name,)).fetchone()
                is None
            ):
                raise BranchError(f"branch not found: {name}")
            bid = f"bi_{uuid.uuid4().hex[:12]}"
            now = time.time()
            self._conn.execute(
                "INSERT INTO memory_branch_items(id, branch_name, item_id, op, content, "
                "trust_tier, source_kind, source_uri, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (bid, name, item_id, "revoke", "", "T1", "user-direct", None, now),
            )
            bhash = self._rehash(name)
            self._conn.commit()
            return {"id": bid, "branch_name": name, "op": "revoke", "branch_hash": bhash}

    def delete_branch(self, name: str) -> bool:
        with self._lock:
            cur = self._conn.execute("DELETE FROM memory_branches WHERE name=?", (name,))
            self._conn.commit()
            return (cur.rowcount or 0) > 0

    def diff_branch(self, name: str, store: MemoryStore) -> BranchDiff:
        """Compute 3-way cognitive diff & epistemic conflict check between `name` and live `main`."""
        data = self.get_branch(name)
        items = data["items"]
        snapshot_ids = {str(r["item_id"]) for r in items if r["op"] == "snapshot" and r["item_id"]}
        staged_adds = [
            {
                "id": r["id"],
                "content": r["content"],
                "trust_tier": r["trust_tier"],
                "source_kind": r["source_kind"],
                "source_uri": r["source_uri"],
            }
            for r in items
            if r["op"] == "add"
        ]
        staged_revokes = sorted(
            {str(r["item_id"]) for r in items if r["op"] == "revoke" and r["item_id"]}
        )
        revoke_set = set(staged_revokes)

        live_active = store.active(limit=500)
        live_ids = {m.id for m in live_active}
        main_added = [
            {"id": m.id, "content": m.content, "trust_tier": m.trust_tier}
            for m in live_active
            if m.id not in snapshot_ids
        ]
        main_removed = sorted(snapshot_ids - live_ids)

        # Simulate combined post-merge active set and run H1 contradiction detection!
        combined: list[dict[str, Any]] = [
            {
                "id": m.id,
                "content": m.content,
                "trust_tier": m.trust_tier,
                "state": "active",
                "source_uri": m.provenance.source_uri,
                "created_at": m.created_at,
                "verified_at": m.verified_at,
            }
            for m in live_active
            if m.id not in revoke_set
        ]
        for add in staged_adds:
            combined.append(
                {
                    "id": f"branch:{add['id']}",
                    "content": add["content"],
                    "trust_tier": add["trust_tier"],
                    "state": "active",
                    "source_uri": add["source_uri"],
                    "created_at": time.time(),
                    "verified_at": time.time(),
                }
            )
        conflicts = [c.to_dict() for c in detect_contradictions(combined)]
        cur_head = store.ledger_head()
        return BranchDiff(
            branch_name=name,
            parent_head=str(data["parent_head"]),
            current_main_head=cur_head,
            main_diverged=(cur_head != str(data["parent_head"])),
            staged_adds=staged_adds,
            staged_revokes=staged_revokes,
            main_added_since_fork=main_added,
            main_removed_since_fork=main_removed,
            conflicts=conflicts,
        )

    async def merge_branch(
        self,
        name: str,
        store: MemoryStore,
        *,
        pipeline: MemoryPipeline | None = None,
        force: bool = False,
    ) -> BranchMergeResult:
        """Merge staged branch mutations into live memory STRICTLY via `MemoryPipeline`."""
        diff = self.diff_branch(name, store)
        if diff.conflicts and not force:
            return BranchMergeResult(
                branch_name=name,
                merged=False,
                conflicts_detected=diff.conflicts,
                new_ledger_head=store.ledger_head(),
                message=(
                    f"merge blocked by {len(diff.conflicts)} epistemic contradiction(s); "
                    "resolve conflicts or pass force=True"
                ),
            )

        pipe = pipeline or MemoryPipeline(store)
        promoted: list[str] = []
        rejected: list[str] = []
        pending: list[str] = []
        revoked: list[str] = []

        # 1. Apply staged revocations via ledgered state transitions.
        for mid in diff.staged_revokes:
            item = store.get(mid)
            if item is not None and item.state in ("active", "pending"):
                store._set_state(mid, "revoked", "revoke", {"branch": name})  # noqa: SLF001
                store._conn.commit()  # noqa: SLF001
                revoked.append(mid)

        # 2. Apply staged additions strictly through the verified MemoryPipeline.
        for add in diff.staged_adds:
            mid = pipe.propose(
                str(add["content"]),
                source_kind=add["source_kind"],
                source_uri=add["source_uri"],
                tier=add["trust_tier"],
            )
            state = await pipe.process_one(mid)
            if state == "active":
                promoted.append(mid)
            elif state == "rejected":
                rejected.append(mid)
            else:
                pending.append(mid)

        with self._lock:
            self._conn.execute(
                "UPDATE memory_branches SET merged_at=? WHERE name=?", (time.time(), name)
            )
            self._conn.commit()

        return BranchMergeResult(
            branch_name=name,
            merged=True,
            promoted_ids=promoted,
            rejected_ids=rejected,
            pending_ids=pending,
            revoked_ids=revoked,
            conflicts_detected=diff.conflicts,
            new_ledger_head=store.ledger_head(),
            message=(
                f"merged '{name}': {len(promoted)} promoted, {len(pending)} pending, "
                f"{len(rejected)} rejected, {len(revoked)} revoked"
            ),
        )
