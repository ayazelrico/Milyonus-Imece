"""Per-tenant SQLite for web users, turns, events, approvals, quotas."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    created_at REAL NOT NULL,
    locale TEXT NOT NULL DEFAULT 'en',
    status TEXT NOT NULL DEFAULT 'active'
);
CREATE TABLE IF NOT EXISTS rate_limits (
    key TEXT PRIMARY KEY,
    started REAL NOT NULL,
    count INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS magic_tokens (
    token TEXT PRIMARY KEY,
    email TEXT NOT NULL,
    created_at REAL NOT NULL,
    used_at REAL
);
CREATE TABLE IF NOT EXISTS sessions_meta (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    title TEXT,
    pinned INTEGER NOT NULL DEFAULT 0,
    archived_at REAL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS turns (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    user_msg_id TEXT,
    state TEXT NOT NULL,
    started_at REAL NOT NULL,
    ended_at REAL,
    stop_reason TEXT
);
CREATE TABLE IF NOT EXISTS turn_events (
    turn_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at REAL NOT NULL,
    PRIMARY KEY (turn_id, seq)
);
CREATE TABLE IF NOT EXISTS approvals (
    id TEXT PRIMARY KEY,
    turn_id TEXT NOT NULL,
    call_id TEXT NOT NULL,
    tool TEXT NOT NULL,
    args_json TEXT NOT NULL,
    risk TEXT NOT NULL,
    reason TEXT NOT NULL,
    irreversible INTEGER NOT NULL DEFAULT 0,
    state TEXT NOT NULL,
    decision TEXT,
    decided_by TEXT,
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS quotas (
    tenant_id TEXT PRIMARY KEY,
    period TEXT NOT NULL,
    tokens_used INTEGER NOT NULL DEFAULT 0,
    cost_usd REAL NOT NULL DEFAULT 0,
    turns INTEGER NOT NULL DEFAULT 0,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
    user_id TEXT PRIMARY KEY,
    json TEXT NOT NULL
);
"""


def _now() -> float:
    return time.time()


@dataclass(slots=True)
class WebUser:
    id: str
    email: str
    locale: str
    status: str


class WebStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.RLock()
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            try:
                yield self._conn
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    def rate_limit(self, key: str, *, limit: int, window: float) -> bool:
        with self._tx() as c:
            row = c.execute("SELECT started, count FROM rate_limits WHERE key=?", (key,)).fetchone()
            now = _now()
            if row is None or now - row["started"] >= window:
                c.execute("INSERT OR REPLACE INTO rate_limits VALUES (?, ?, 1)", (key, now))
                return True
            if row["count"] >= limit:
                return False
            c.execute("UPDATE rate_limits SET count=count+1 WHERE key=?", (key,))
            return True

    def create_magic_token(self, email: str) -> str:
        token = uuid.uuid4().hex
        with self._tx() as c:
            c.execute(
                "INSERT INTO magic_tokens(token, email, created_at) VALUES (?,?,?)",
                (token, email.lower().strip(), _now()),
            )
        return token

    def consume_magic_token(self, token: str, *, ttl_s: float = 3600) -> str | None:
        with self._tx() as c:
            row = c.execute(
                "SELECT email, created_at, used_at FROM magic_tokens WHERE token=?",
                (token,),
            ).fetchone()
            if row is None or row["used_at"] is not None:
                return None
            if _now() - float(row["created_at"]) > ttl_s:
                return None
            c.execute("UPDATE magic_tokens SET used_at=? WHERE token=?", (_now(), token))
            return str(row["email"])

    def upsert_user(self, email: str) -> WebUser:
        email = email.lower().strip()
        with self._tx() as c:
            row = c.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
            if row:
                return WebUser(row["id"], row["email"], row["locale"], row["status"])
            uid = "u_" + uuid.uuid4().hex[:12]
            c.execute(
                "INSERT INTO users(id, email, created_at) VALUES (?,?,?)",
                (uid, email, _now()),
            )
            return WebUser(uid, email, "en", "active")

    def get_user(self, user_id: str) -> WebUser | None:
        row = self._conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        if not row:
            return None
        return WebUser(row["id"], row["email"], row["locale"], row["status"])

    def list_sessions(self, user_id: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT id, title, updated_at, pinned FROM sessions_meta "
            "WHERE user_id=? AND archived_at IS NULL ORDER BY pinned DESC, updated_at DESC",
            (user_id,),
        ).fetchall()
        return [
            {
                "id": r["id"],
                "title": r["title"],
                "updated_at": r["updated_at"],
                "pinned": bool(r["pinned"]),
            }
            for r in rows
        ]

    def create_session(self, user_id: str, *, title: str | None = None) -> str:
        sid = "s_" + uuid.uuid4().hex[:12]
        ts = _now()
        with self._tx() as c:
            c.execute(
                "INSERT INTO sessions_meta(id, user_id, title, created_at, updated_at) "
                "VALUES (?,?,?,?,?)",
                (sid, user_id, title, ts, ts),
            )
        return sid

    def get_session(self, user_id: str, session_id: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM sessions_meta WHERE id=? AND user_id=? AND archived_at IS NULL",
            (session_id, user_id),
        ).fetchone()
        if not row:
            return None
        return dict(row)

    def patch_session(
        self,
        user_id: str,
        session_id: str,
        *,
        title: str | None = None,
        pinned: bool | None = None,
    ) -> bool:
        meta = self.get_session(user_id, session_id)
        if not meta:
            return False
        with self._tx() as c:
            if title is not None:
                c.execute(
                    "UPDATE sessions_meta SET title=?, updated_at=? WHERE id=?",
                    (title, _now(), session_id),
                )
            if pinned is not None:
                c.execute(
                    "UPDATE sessions_meta SET pinned=?, updated_at=? WHERE id=?",
                    (1 if pinned else 0, _now(), session_id),
                )
        return True

    def delete_session(self, user_id: str, session_id: str) -> bool:
        with self._tx() as c:
            cur = c.execute(
                "UPDATE sessions_meta SET archived_at=?, updated_at=? "
                "WHERE id=? AND user_id=? AND archived_at IS NULL",
                (_now(), _now(), session_id, user_id),
            )
            return cur.rowcount > 0

    def create_turn(self, session_id: str) -> str:
        tid = "t_" + uuid.uuid4().hex[:12]
        with self._tx() as c:
            c.execute(
                "INSERT INTO turns(id, session_id, state, started_at) VALUES (?,?,?,?)",
                (tid, session_id, "running", _now()),
            )
        return tid

    def finish_turn(self, turn_id: str, *, stop_reason: str) -> None:
        with self._tx() as c:
            c.execute(
                "UPDATE turns SET state=?, ended_at=?, stop_reason=? WHERE id=?",
                ("completed", _now(), stop_reason, turn_id),
            )

    def append_event(self, turn_id: str, seq: int, typ: str, payload: dict) -> dict:
        event = {"seq": seq, "type": typ, **payload}
        with self._tx() as c:
            c.execute(
                "INSERT INTO turn_events(turn_id, seq, type, payload_json, created_at) "
                "VALUES (?,?,?,?,?)",
                (turn_id, seq, typ, json.dumps(payload, ensure_ascii=False), _now()),
            )
        return event

    def events_from(self, turn_id: str, from_seq: int = 0) -> list[dict]:
        rows = self._conn.execute(
            "SELECT seq, type, payload_json FROM turn_events "
            "WHERE turn_id=? AND seq>=? ORDER BY seq",
            (turn_id, from_seq),
        ).fetchall()
        out = []
        for r in rows:
            payload = json.loads(r["payload_json"])
            out.append({"seq": r["seq"], "type": r["type"], **payload})
        return out

    def turn_belongs_to(self, turn_id: str, session_id: str) -> bool:
        return self._conn.execute(
            "SELECT 1 FROM turns WHERE id=? AND session_id=?",
            (turn_id, session_id),
        ).fetchone() is not None

    def latest_turn(self, session_id: str) -> str | None:
        row = self._conn.execute(
            "SELECT id FROM turns WHERE session_id=? ORDER BY started_at DESC LIMIT 1",
            (session_id,),
        ).fetchone()
        return None if row is None else str(row["id"])

    def create_approval(
        self,
        *,
        turn_id: str,
        call_id: str,
        tool: str,
        args: dict,
        risk: str,
        reason: str,
        irreversible: bool,
        ttl_s: float = 300,
    ) -> str:
        aid = "a_" + uuid.uuid4().hex[:12]
        now = _now()
        with self._tx() as c:
            c.execute(
                "INSERT INTO approvals(id, turn_id, call_id, tool, args_json, risk, reason, "
                "irreversible, state, created_at, expires_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    aid,
                    turn_id,
                    call_id,
                    tool,
                    json.dumps(args, ensure_ascii=False),
                    risk,
                    reason,
                    1 if irreversible else 0,
                    "pending",
                    now,
                    now + ttl_s,
                ),
            )
        return aid

    def get_approval(self, approval_id: str) -> dict | None:
        row = self._conn.execute("SELECT * FROM approvals WHERE id=?", (approval_id,)).fetchone()
        return None if row is None else dict(row)

    def approval_owner(self, approval_id: str) -> str | None:
        row = self._conn.execute(
            "SELECT s.user_id FROM approvals a JOIN turns t ON t.id=a.turn_id "
            "JOIN sessions_meta s ON s.id=t.session_id WHERE a.id=?",
            (approval_id,),
        ).fetchone()
        return None if row is None else str(row[0])

    def resolve_approval(self, approval_id: str, *, decision: str, by: str) -> dict | None:
        with self._tx() as c:
            row = c.execute("SELECT * FROM approvals WHERE id=?", (approval_id,)).fetchone()
            if row is None or row["state"] != "pending":
                return None
            if _now() > float(row["expires_at"]):
                c.execute(
                    "UPDATE approvals SET state=?, decision=? WHERE id=?",
                    ("expired", "deny", approval_id),
                )
                return None
            if decision == "allow_session" and int(row["irreversible"]):
                return None
            c.execute(
                "UPDATE approvals SET state=?, decision=?, decided_by=? WHERE id=?",
                ("resolved", decision, by, approval_id),
            )
            return dict(c.execute("SELECT * FROM approvals WHERE id=?", (approval_id,)).fetchone())

    def expire_stale_approvals(self) -> int:
        with self._tx() as c:
            cur = c.execute(
                "UPDATE approvals SET state='expired', decision='deny' "
                "WHERE state='pending' AND expires_at < ?",
                (_now(),),
            )
            return cur.rowcount

    def get_settings(self, user_id: str) -> dict:
        row = self._conn.execute("SELECT json FROM settings WHERE user_id=?", (user_id,)).fetchone()
        return json.loads(row["json"]) if row else {}

    def put_settings(self, user_id: str, data: dict) -> None:
        with self._tx() as c:
            c.execute(
                "INSERT INTO settings(user_id, json) VALUES (?,?) "
                "ON CONFLICT(user_id) DO UPDATE SET json=excluded.json",
                (user_id, json.dumps(data, ensure_ascii=False)),
            )

    def reserve_quota(
        self, tenant_id: str, *, tokens: int, cost: float,
        token_limit: int, cost_limit: float,
    ) -> str:
        """Charge an upper bound before dispatch; crashes keep the charge.

        BEGIN IMMEDIATE also serializes independent worker connections.
        The returned period prevents a late refund crediting a new month.
        """
        import math

        if tokens < 0 or not math.isfinite(cost) or cost < 0:
            raise ValueError("invalid quota reservation")
        period = time.strftime("%Y-%m")
        with self._tx() as c:
            c.execute("BEGIN IMMEDIATE")
            c.execute(
                "INSERT OR IGNORE INTO quotas VALUES (?, ?, 0, 0, 0, ?)",
                (tenant_id, period, _now()),
            )
            c.execute(
                "UPDATE quotas SET period=?, tokens_used=0, cost_usd=0, turns=0 "
                "WHERE tenant_id=? AND period<>?", (period, tenant_id, period),
            )
            row = c.execute("SELECT * FROM quotas WHERE tenant_id=?", (tenant_id,)).fetchone()
            if row["tokens_used"] + tokens > token_limit:
                raise RuntimeError("monthly token quota exceeded")
            if cost_limit > 0 and row["cost_usd"] + cost > cost_limit:
                raise RuntimeError("monthly cost quota exceeded")
            c.execute(
                "UPDATE quotas SET tokens_used=tokens_used+?, cost_usd=cost_usd+?, "
                "updated_at=? WHERE tenant_id=?", (tokens, cost, _now(), tenant_id),
            )
        return period

    def refund_quota(self, tenant_id: str, *, period: str, tokens: int, cost: float) -> None:
        """Internal settlement; only refund the reservation's original period."""
        with self._tx() as c:
            c.execute(
                "UPDATE quotas SET tokens_used=MAX(0, tokens_used-?), "
                "cost_usd=MAX(0, cost_usd-?), updated_at=? WHERE tenant_id=? AND period=?",
                (tokens, cost, _now(), tenant_id, period),
            )

    def bump_quota(
        self, tenant_id: str, *, tokens: int = 0, cost: float = 0, turns: int = 0
    ) -> None:
        period = time.strftime("%Y-%m")
        with self._tx() as c:
            row = c.execute("SELECT * FROM quotas WHERE tenant_id=?", (tenant_id,)).fetchone()
            if row is None:
                c.execute(
                    "INSERT INTO quotas(tenant_id, period, tokens_used, cost_usd, turns, updated_at) "
                    "VALUES (?,?,?,?,?,?)",
                    (tenant_id, period, tokens, cost, turns, _now()),
                )
            elif row["period"] != period:
                c.execute(
                    "UPDATE quotas SET tokens_used=?, cost_usd=?, turns=?, updated_at=?, period=? WHERE tenant_id=?",
                    (tokens, cost, turns, _now(), period, tenant_id),
                )
            else:
                c.execute(
                    "UPDATE quotas SET tokens_used=tokens_used+?, cost_usd=cost_usd+?, "
                    "turns=turns+?, updated_at=?, period=? WHERE tenant_id=?",
                    (tokens, cost, turns, _now(), period, tenant_id),
                )

    def usage(self, tenant_id: str) -> dict:
        row = self._conn.execute("SELECT * FROM quotas WHERE tenant_id=?", (tenant_id,)).fetchone()
        if not row or row["period"] != time.strftime("%Y-%m"):
            return {"tokens_used": 0, "cost_usd": 0.0, "turns": 0, "period": time.strftime("%Y-%m")}
        return {
            "tokens_used": row["tokens_used"],
            "cost_usd": row["cost_usd"],
            "turns": row["turns"],
            "period": row["period"],
        }

    def erase_user(self, user_id: str) -> None:
        with self._tx() as c:
            c.execute(
                "UPDATE users SET status='erased', email=? WHERE id=?",
                (f"erased:{user_id}", user_id),
            )
            c.execute(
                "UPDATE sessions_meta SET archived_at=?, title=NULL WHERE user_id=?",
                (_now(), user_id),
            )
            c.execute("DELETE FROM settings WHERE user_id=?", (user_id,))
