"""Persistent phase DAG and exactly identified agent-call replay.

Completed replies are replayed only within the same frozen run identity. An
interrupted call is not retried automatically: its invoice may be unknown.
No journal contents are exposed as tools or mounted inside artifact sandboxes.
"""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from collections import Counter
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict
from pathlib import Path

from milyonus.imece.agents import (
    AdmissionDenied,
    AgentFn,
    AgentReply,
    AgentSpec,
    FatalAgentStateError,
    PoolExhausted,
)

current_journal_call: ContextVar[dict | None] = ContextVar("imece_journal_call", default=None)


@contextmanager
def _journal_state(operation: str):
    try:
        yield
    except (sqlite3.Error, OSError, ValueError, TypeError, OverflowError, RecursionError) as exc:
        raise FatalAgentStateError(f"agent journal {operation}: {exc}") from exc


def fingerprint(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode()
    ).hexdigest()


def validated_reply(payload: dict, output_hash: str) -> AgentReply:
    """Validate persisted data before constructing an otherwise unchecked dataclass."""
    if (
        not isinstance(payload, dict)
        or set(payload) != {"text", "tokens", "cost_usd", "cost_estimated"}
        or not isinstance(payload["text"], str)
        or type(payload["tokens"]) is not int
        or payload["tokens"] < 0
        or type(payload["cost_estimated"]) is not bool
    ):
        raise ValueError("invalid completed agent reply")
    cost = payload["cost_usd"]
    if cost is not None and (type(cost) not in (int, float) or cost < 0 or not math.isfinite(cost)):
        raise ValueError("invalid completed agent reply cost")
    if fingerprint(payload) != output_hash:
        raise ValueError("journal output hash mismatch")
    return AgentReply(**payload)


@_journal_state("reconciliation")
def reconcile_completed_calls(path: Path, *, identity: dict, calls: list[dict]) -> None:
    """Promote only exactly bound durable replies; never infer a call from its spec."""
    key = fingerprint(identity)
    with sqlite3.connect(path) as db:
        if db.execute("SELECT hash FROM identity WHERE id=1").fetchone() != (key,):
            raise ValueError("journal run identity changed")
        seen = set()
        for entry in calls:
            binding = entry.get("journal")
            if binding is None:
                continue  # Legacy transcripts cannot resolve an unfinished node.
            if (
                not isinstance(binding, dict)
                or set(binding) != {"identity_hash", "node_id", "spec_hash", "task", "repeat"}
                or binding["identity_hash"] != key
                or binding["task"] != identity["task"]["id"]
                or type(binding["repeat"]) is not int
                or binding["repeat"] != identity["repeat"]
                or binding["task"] != entry.get("task")
                or binding["repeat"] != entry.get("repeat")
                or binding["spec_hash"] != fingerprint(entry.get("spec"))
                or not isinstance(binding["node_id"], str)
                or entry.get("state") not in ("running", "unknown", "completed")
            ):
                raise ValueError("CLI call journal binding mismatch")
            node = binding["node_id"]
            if node in seen:
                raise ValueError("multiple CLI calls bound to one journal node")
            seen.add(node)
            row = db.execute(
                "SELECT input_hash,state,reply,output_hash FROM nodes WHERE id=?", (node,)
            ).fetchone()
            if row is None or row[0] != binding["spec_hash"]:
                raise ValueError("CLI call journal node/spec mismatch")
            if row[1] not in ("running", "unknown", "completed") or (
                row[1] != "completed" and row[2:] != (None, None)
            ):
                raise ValueError("invalid unfinished journal node")
            if entry.get("state") != "completed":
                if row[1] == "completed" or "reply" in entry or "output_hash" in entry:
                    raise ValueError("uncertain CLI call contradicts journal completion")
                continue
            if "error" in entry:
                raise ValueError("completed CLI call contains an error")
            reply = validated_reply(entry.get("reply"), entry.get("output_hash"))
            if row[1] == "completed":
                validated_reply(json.loads(row[2]), row[3])
                if row[3] != entry["output_hash"] or json.loads(row[2]) != asdict(reply):
                    raise ValueError("CLI reply contradicts completed journal node")
            elif row[1] in ("running", "unknown") and row[2:] == (None, None):
                db.execute(
                    "UPDATE nodes SET state='completed',reply=?,output_hash=? WHERE id=?",
                    (json.dumps(asdict(reply)), entry["output_hash"], node),
                )
            else:
                raise ValueError("CLI reply contradicts unfinished journal node")


class AgentJournal:
    @_journal_state("initialization")
    def __init__(self, path: Path, agent_fn: AgentFn, *, identity: dict):
        path.parent.mkdir(parents=True, exist_ok=True)
        # Only the process that creates the file may bind a new identity.
        try:
            with path.open("xb"):
                pass
        except FileExistsError:
            created = False
        else:
            created = True
        self.db = sqlite3.connect(
            path.absolute().as_uri() + "?mode=rw", uri=True, isolation_level=None
        )
        try:
            self.db.execute("BEGIN IMMEDIATE")
            self._initialize(identity, created=created)
            self.db.execute("COMMIT")
        except BaseException:
            if self.db.in_transaction:
                self.db.execute("ROLLBACK")
            self.db.close()
            raise
        self.fn = agent_fn
        self.identity = identity
        self.identity_hash = fingerprint(identity)
        self.counts = Counter()
        self.phase_counts = Counter()
        self.current_phase = "start:0"
        self.parents = []
        self.parent_hash = fingerprint([])
        self.frontier = []
        self.replayed = 0

    def _initialize(self, identity: dict, *, created: bool) -> None:
        """Publish schema, version and identity together, or none of them."""
        key = fingerprint(identity)
        if created:
            # executescript implicitly commits an open transaction.
            self.db.execute("CREATE TABLE identity (id INTEGER PRIMARY KEY CHECK(id=1), hash TEXT)")
            self.db.execute("""
                CREATE TABLE nodes (
                    id TEXT PRIMARY KEY, phase TEXT NOT NULL, input_hash TEXT NOT NULL,
                    parents TEXT NOT NULL, state TEXT NOT NULL, reply TEXT, output_hash TEXT
                )
            """)
            self.db.execute(
                "CREATE TABLE phase_inputs (hash TEXT PRIMARY KEY, parents TEXT NOT NULL)"
            )
            self.db.execute("INSERT INTO identity VALUES (1,?)", (key,))
            self.db.execute("INSERT INTO phase_inputs VALUES (?, '[]')", (fingerprint([]),))
            self.db.execute("PRAGMA user_version=2")
        elif self.db.execute(
            "SELECT count(*) FROM sqlite_master WHERE type='table' AND name IN ('identity','nodes')"
        ).fetchone() != (2,):
            raise ValueError("existing agent journal is missing its identity or nodes table")

        self.version = self.db.execute("PRAGMA user_version").fetchone()[0]
        if self.version not in (0, 2):
            raise ValueError("unsupported agent journal version")
        if self.db.execute("SELECT hash FROM identity WHERE id=1").fetchone() != (key,):
            raise ValueError("journal run identity changed; cannot reuse previous evidence")
        if self.version == 2 and not created:
            self._ensure_phase_input(fingerprint([]))

    def _ensure_phase_input(self, parent_hash: str, *, new_parents: list | None = None) -> None:
        row = self.db.execute(
            "SELECT parents FROM phase_inputs WHERE hash=?", (parent_hash,)
        ).fetchone()
        if row is None:
            # An existing node's reference must already have a shared parent record.
            if (
                new_parents is None
                or self.db.execute(
                    "SELECT 1 FROM nodes WHERE parents=? LIMIT 1", (json.dumps(parent_hash),)
                ).fetchone()
            ):
                raise ValueError("journal phase input is missing")
            inserted = self.db.execute(
                "INSERT OR IGNORE INTO phase_inputs VALUES (?,?)",
                (parent_hash, json.dumps(new_parents)),
            )
            if inserted.rowcount == 0:
                self._ensure_phase_input(parent_hash)
        elif not isinstance(row[0], str) or fingerprint(json.loads(row[0])) != parent_hash:
            raise ValueError("journal phase input hash mismatch")

    @_journal_state("close")
    def close(self):
        self.db.close()

    @_journal_state("phase input")
    def phase(self, name: str):
        parents = sorted(self.frontier) if self.frontier or self.version == 0 else self.parents
        if self.version == 2:
            parent_hash = fingerprint(parents)
            self._ensure_phase_input(parent_hash, new_parents=parents)
            self.parent_hash = parent_hash
        self.parents = parents
        self.frontier = []
        occurrence = self.phase_counts[name]
        self.phase_counts[name] += 1
        self.current_phase = f"{name}:{occurrence}"

    @_journal_state("node lookup or reservation")
    def _reserve(self, spec: AgentSpec) -> tuple[str, str, AgentReply | None]:
        inp = fingerprint(asdict(spec))
        occurrence = self.counts[(self.current_phase, inp)]
        self.counts[(self.current_phase, inp)] += 1
        # Older journals used the complete parent list in every node. Preserve
        # those IDs on replay. New journals share a single parent record per phase.
        parent_identity = self.parents if self.version == 0 else self.parent_hash
        node = fingerprint([self.current_phase, inp, occurrence, parent_identity])
        parent_json = json.dumps(parent_identity)
        if self.version == 0:
            self.frontier.append(node)
        row = self.db.execute(
            "SELECT phase,input_hash,parents,state,reply,output_hash FROM nodes WHERE id=?", (node,)
        ).fetchone()
        if row is not None:
            phase, input_hash, parents, state, payload, output_hash = row
            if self.version == 0 and isinstance(parents, str):
                parents_match = json.loads(parents) == parent_identity
            else:
                # Use the same JSON encoding as the shared-reference lookup.
                parents_match = parents == parent_json
            if (phase, input_hash) != (self.current_phase, inp) or not parents_match:
                raise ValueError("journal node metadata mismatch")
            if state != "completed":
                if state not in ("running", "unknown") or (payload, output_hash) != (None, None):
                    raise ValueError("invalid unfinished journal node")
                raise PoolExhausted(
                    "unfinished journal call requires charge reconciliation; no automatic retry"
                )
            reply = validated_reply(json.loads(payload), output_hash)
            if self.version == 2:
                self.frontier.append((node, output_hash))
            self.replayed += 1
            return node, inp, reply
        self.db.execute(
            "INSERT INTO nodes VALUES (?,?,?,?,?,NULL,NULL)",
            (node, self.current_phase, inp, parent_json, "running"),
        )
        return node, inp, None

    async def __call__(self, spec: AgentSpec) -> AgentReply:
        node, inp, reply = self._reserve(spec)
        if reply is not None:
            return reply
        token = current_journal_call.set(
            {
                "identity_hash": self.identity_hash,
                "node_id": node,
                "spec_hash": inp,
                "task": (
                    self.identity["task"].get("id")
                    if isinstance(self.identity.get("task"), dict)
                    else None
                ),
                "repeat": self.identity.get("repeat"),
            }
        )
        try:
            reply = await self.fn(spec)
        except AdmissionDenied:
            # No external operation took place: there is no unknown charge.
            with _journal_state("reservation removal"):
                changed = self.db.execute(
                    "DELETE FROM nodes WHERE id=? AND state='running'", (node,)
                )
                if changed.rowcount != 1:
                    raise ValueError(
                        "journal reservation is missing or no longer running"
                    ) from None
            raise
        except BaseException:
            with _journal_state("interruption write"):
                changed = self.db.execute(
                    "UPDATE nodes SET state='unknown' WHERE id=? AND state='running'", (node,)
                )
                if changed.rowcount != 1:
                    raise ValueError(
                        "journal interrupted node is missing or no longer running"
                    ) from None
            if self.version == 2:
                self.frontier.append((node, "unknown"))
            raise
        finally:
            current_journal_call.reset(token)
        with _journal_state("completion write"):
            payload = asdict(reply)
            output_hash = fingerprint(payload)
            validated_reply(payload, output_hash)
            changed = self.db.execute(
                "UPDATE nodes SET state='completed',reply=?,output_hash=? "
                "WHERE id=? AND state='running'",
                (json.dumps(payload), output_hash, node),
            )
            if changed.rowcount != 1:
                raise ValueError("journal completed node is missing or no longer running")
        if self.version == 2:
            self.frontier.append((node, output_hash))
        return reply
