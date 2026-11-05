"""Durable admission ledger for provider calls.

Reservations are held until a complete usage-bearing stream is received.
Interrupted/missing-usage calls retain their entire reservation as unknown;
reopening the database cannot silently refund or retry them. USD is an upper
bound at caller-supplied token prices, not a promise about provider invoices.
"""

from __future__ import annotations

import json
import math
import sqlite3
import uuid
from collections.abc import AsyncIterator
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path

from milyonus.imece.agents import AdmissionDenied, PoolExhausted
from milyonus.providers.base import CompletionRequest, Provider, StreamEvent


class ReservationLedger:
    def __init__(self, path: Path, *, max_tokens: int, max_usd: float):
        if max_tokens < 1 or not math.isfinite(max_usd) or max_usd <= 0:
            raise ValueError("positive finite token and dollar budgets required")
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, isolation_level=None)
        self.db.execute("PRAGMA busy_timeout=5000")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS limits (id INTEGER PRIMARY KEY CHECK(id=1), tokens INTEGER, usd TEXT);
            CREATE TABLE IF NOT EXISTS calls (
                id TEXT PRIMARY KEY, model TEXT NOT NULL, state TEXT NOT NULL,
                reserved_tokens INTEGER NOT NULL, reserved_usd TEXT NOT NULL,
                tokens INTEGER, usd TEXT
            );
        """)
        limit = (max_tokens, str(Decimal(str(max_usd))))
        self.db.execute("INSERT OR IGNORE INTO limits VALUES (1,?,?)", limit)
        if self.db.execute("SELECT tokens,usd FROM limits WHERE id=1").fetchone() != limit:
            raise ValueError("persisted budget differs; use a new experiment ledger")
        self.max_tokens, self.max_usd = max_tokens, Decimal(str(max_usd))

    def close(self) -> None:
        self.db.close()

    def summary(self) -> dict:
        rows = self.db.execute(
            "SELECT state,reserved_tokens,reserved_usd,tokens,usd FROM calls"
        ).fetchall()
        tokens = sum(r[3] if r[0] == "known" else r[1] for r in rows)
        usd = sum((Decimal(r[4] if r[0] == "known" else r[2]) for r in rows), Decimal(0))
        return {
            "calls": len(rows),
            "committed_tokens": tokens,
            "committed_usd": float(usd),
            "unknown_calls": sum(r[0] in ("unknown", "pending", "overrun") for r in rows),
            "overruns": sum(r[0] == "overrun" for r in rows),
        }

    def reserve(self, model: str, tokens: int, usd: Decimal) -> str:
        if type(tokens) is not int or tokens < 1 or not usd.is_finite() or usd < 0:
            raise ValueError("invalid reservation")
        self.db.execute("BEGIN IMMEDIATE")
        try:
            rows = self.db.execute(
                "SELECT state,reserved_tokens,reserved_usd,tokens,usd FROM calls"
            ).fetchall()
            used_tokens = sum(r[3] if r[0] == "known" else r[1] for r in rows)
            used_usd = sum((Decimal(r[4] if r[0] == "known" else r[2]) for r in rows), Decimal(0))
            # Unknown invoices require reconciliation before any further spend.
            if any(r[0] in ("unknown", "overrun") for r in rows):
                raise AdmissionDenied("unresolved provider charge; experiment paused")
            if used_tokens + tokens > self.max_tokens or used_usd + usd > self.max_usd:
                raise AdmissionDenied("reservation would exceed experiment budget")
            call_id = uuid.uuid4().hex
            self.db.execute(
                "INSERT INTO calls VALUES (?,?, 'pending',?,?,NULL,NULL)",
                (call_id, model, tokens, str(usd)),
            )
            self.db.execute("COMMIT")
            return call_id
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def unknown(self, call_id: str) -> None:
        self.db.execute(
            "UPDATE calls SET state='unknown' WHERE id=? AND state='pending'", (call_id,)
        )

    def recover(self) -> None:
        """Call once before resuming, never while other owners are running."""
        self.db.execute("UPDATE calls SET state='unknown' WHERE state='pending'")

    def settle(self, call_id: str, tokens: int, usd: Decimal) -> None:
        row = self.db.execute(
            "SELECT reserved_tokens,reserved_usd,state FROM calls WHERE id=?", (call_id,)
        ).fetchone()
        if row is None or row[2] != "pending":
            raise ValueError("reservation is absent or already settled")
        if type(tokens) is not int or tokens < 0 or not usd.is_finite() or usd < 0:
            self.unknown(call_id)
            raise ValueError("invalid provider usage")
        state = "overrun" if tokens > row[0] or usd > Decimal(row[1]) else "known"
        # Publish settled usage and any excess liability in a single write. The
        # pending predicate prevents a late response from overwriting recovery.
        updated = self.db.execute(
            "UPDATE calls SET state=?,tokens=?,usd=?,reserved_tokens=?,reserved_usd=? "
            "WHERE id=? AND state='pending'",
            (state, tokens, str(usd), max(tokens, row[0]), str(max(usd, Decimal(row[1]))), call_id),
        )
        if updated.rowcount != 1:
            raise ValueError("reservation no longer pending")
        if state == "overrun":
            raise PoolExhausted("provider exceeded reservation bound; experiment paused")


class MeteredProvider:
    """Reserve every actual request, including tool continuations.

    Text-only upper bound: serialized UTF-8 bytes plus 4096 protocol tokens.
    A provider must honor max_output_tokens. Unsupported images are refused.
    Usage exceeding the bound halts spending and remains visible as an overrun.
    """

    def __init__(
        self,
        provider: Provider,
        ledger: ReservationLedger,
        *,
        input_per_m: float,
        output_per_m: float,
    ):
        if any(not math.isfinite(p) or p < 0 for p in (input_per_m, output_per_m)):
            raise ValueError("explicit nonnegative finite model prices required")
        self.provider, self.ledger = provider, ledger
        self.name, self.model = provider.name, provider.model
        self.input_price, self.output_price = Decimal(str(input_per_m)), Decimal(str(output_per_m))

    def _cost(self, inp: int, out: int) -> Decimal:
        return (inp * self.input_price + out * self.output_price) / 1_000_000

    async def stream(self, request: CompletionRequest) -> AsyncIterator[StreamEvent]:
        if any(m.images for m in request.messages):
            raise ValueError("strict experiment ledger supports text requests only")
        if request.max_output_tokens < 1:
            raise ValueError("positive output limit required")
        inp = len(json.dumps(asdict(request), ensure_ascii=False).encode()) + 4096
        out = request.max_output_tokens
        call_id = self.ledger.reserve(self.model, inp + out, self._cost(inp, out))
        usage = None
        done = False
        try:
            async for event in self.provider.stream(request):
                if event.kind == "usage":
                    usage = event.usage
                if event.kind == "done":
                    done = True
                yield event
            if not done or usage is None:
                self.ledger.unknown(call_id)
                raise PoolExhausted("missing complete usage; charge remains unknown")
            if any(
                isinstance(n, bool) or not isinstance(n, int) or n < 0
                for n in (usage.input_tokens, usage.output_tokens)
            ):
                raise ValueError("invalid usage counters")
            self.ledger.settle(
                call_id,
                usage.input_tokens + usage.output_tokens,
                self._cost(usage.input_tokens, usage.output_tokens),
            )
        except BaseException:
            self.ledger.unknown(call_id)
            raise
