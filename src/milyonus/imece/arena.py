"""Multi-Strategy Arena & Persistent Elo Rating Ledger (PLAN-MOONSHOT M5).

Pits competing strategies, prompts, skills, or models head-to-head on any task:
  1. Executes contenders independently (no cross-contamination),
  2. Evaluates deterministic objective oracle first (correctness always beats rhetoric),
  3. Applies an optional blind judge (anonymized Contender-A / Contender-B) for tie-breaks,
  4. Persists match history & Elo ratings (K=32, base 1500.0) in SQLite.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from milyonus.config.paths import state_db

_SCHEMA = """
CREATE TABLE IF NOT EXISTS arena_ratings (
    contender_id TEXT PRIMARY KEY,
    label        TEXT NOT NULL,
    rating       REAL NOT NULL DEFAULT 1500.0,
    wins         INTEGER NOT NULL DEFAULT 0,
    losses       INTEGER NOT NULL DEFAULT 0,
    draws        INTEGER NOT NULL DEFAULT 0,
    updated_at   REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS arena_matches (
    id           TEXT PRIMARY KEY,
    task         TEXT NOT NULL,
    contender_a  TEXT NOT NULL,
    contender_b  TEXT NOT NULL,
    winner       TEXT NOT NULL,
    reason       TEXT NOT NULL,
    scores_json  TEXT NOT NULL,
    created_at   REAL NOT NULL
);
"""

BASE_ELO = 1500.0
ELO_K = 32.0


def expected_score(ra: float, rb: float) -> float:
    return 1.0 / (1.0 + 10.0 ** ((rb - ra) / 400.0))


def update_elo(ra: float, rb: float, score_a: float, *, k: float = ELO_K) -> tuple[float, float]:
    """Compute updated Elo pair for outcome `score_a` in {1.0, 0.5, 0.0}."""
    ea = expected_score(ra, rb)
    eb = 1.0 - ea
    new_a = round(ra + k * (score_a - ea), 2)
    new_b = round(rb + k * ((1.0 - score_a) - eb), 2)
    return new_a, new_b


@dataclass(slots=True)
class ArenaContender:
    id: str
    label: str
    run_fn: Callable[[str], Awaitable[str]]


@dataclass(slots=True)
class ContenderOutcome:
    contender_id: str
    label: str
    output: str
    oracle_passed: bool | None
    score: float
    duration_ms: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ArenaMatchResult:
    match_id: str
    task: str
    winner: str  # contender_id or "draw"
    reason: str
    outcomes: list[ContenderOutcome] = field(default_factory=list)
    rating_changes: dict[str, dict[str, float]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "match_id": self.match_id,
            "task": self.task,
            "winner": self.winner,
            "reason": self.reason,
            "outcomes": [o.to_dict() for o in self.outcomes],
            "rating_changes": self.rating_changes,
        }


class ArenaStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or state_db()
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def ensure_contender(self, contender_id: str, label: str) -> float:
        with self._lock:
            row = self._conn.execute(
                "SELECT rating FROM arena_ratings WHERE contender_id=?", (contender_id,)
            ).fetchone()
            if row is not None:
                return float(row["rating"])
            now = time.time()
            self._conn.execute(
                "INSERT INTO arena_ratings(contender_id, label, rating, wins, losses, draws, updated_at) "
                "VALUES (?,?,?,0,0,0,?)",
                (contender_id, label, BASE_ELO, now),
            )
            self._conn.commit()
            return BASE_ELO

    def record_match(
        self,
        *,
        task: str,
        contender_a: ArenaContender,
        contender_b: ArenaContender,
        winner: str,
        reason: str,
        scores: dict[str, float],
    ) -> tuple[str, dict[str, dict[str, float]]]:
        mid = f"arena_{uuid.uuid4().hex[:12]}"
        with self._lock:
            ra = self.ensure_contender(contender_a.id, contender_a.label)
            rb = self.ensure_contender(contender_b.id, contender_b.label)
            if winner == contender_a.id:
                score_a = 1.0
                wa, la, da, wb, lb, db = 1, 0, 0, 0, 1, 0
            elif winner == contender_b.id:
                score_a = 0.0
                wa, la, da, wb, lb, db = 0, 1, 0, 1, 0, 0
            else:
                score_a = 0.5
                wa, la, da, wb, lb, db = 0, 0, 1, 0, 0, 1
            new_a, new_b = update_elo(ra, rb, score_a)
            now = time.time()
            self._conn.execute(
                "UPDATE arena_ratings SET label=?, rating=?, wins=wins+?, losses=losses+?, "
                "draws=draws+?, updated_at=? WHERE contender_id=?",
                (contender_a.label, new_a, wa, la, da, now, contender_a.id),
            )
            self._conn.execute(
                "UPDATE arena_ratings SET label=?, rating=?, wins=wins+?, losses=losses+?, "
                "draws=draws+?, updated_at=? WHERE contender_id=?",
                (contender_b.label, new_b, wb, lb, db, now, contender_b.id),
            )
            self._conn.execute(
                "INSERT INTO arena_matches(id, task, contender_a, contender_b, winner, reason, "
                "scores_json, created_at) VALUES (?,?,?,?,?,?,?,?)",
                (
                    mid,
                    task,
                    contender_a.id,
                    contender_b.id,
                    winner,
                    reason,
                    json.dumps(scores, ensure_ascii=False),
                    now,
                ),
            )
            self._conn.commit()
        return mid, {
            contender_a.id: {"before": ra, "after": new_a, "delta": round(new_a - ra, 2)},
            contender_b.id: {"before": rb, "after": new_b, "delta": round(new_b - rb, 2)},
        }

    def leaderboard(self, *, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT contender_id, label, rating, wins, losses, draws, updated_at "
                "FROM arena_ratings ORDER BY rating DESC, wins DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def recent_matches(self, *, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, task, contender_a, contender_b, winner, reason, scores_json, created_at "
                "FROM arena_matches ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["scores"] = json.loads(d.pop("scores_json"))
            out.append(d)
        return out


OracleFn = Callable[[str, str], tuple[bool, float]]
BlindJudgeFn = Callable[[str, str, str], Awaitable[str]]  # returns "A", "B", or "draw"


async def run_arena_match(
    store: ArenaStore,
    task: str,
    contender_a: ArenaContender,
    contender_b: ArenaContender,
    *,
    oracle_fn: OracleFn | None = None,
    judge_fn: BlindJudgeFn | None = None,
) -> ArenaMatchResult:
    """Run a head-to-head match between two contenders and update the Elo ledger."""
    outcomes: list[ContenderOutcome] = []
    for contender in (contender_a, contender_b):
        t0 = time.perf_counter()
        output = await contender.run_fn(task)
        dur = int(round((time.perf_counter() - t0) * 1000))
        if oracle_fn is not None:
            passed, score = oracle_fn(task, output)
        else:
            passed = bool(output.strip())
            score = float(len(output.strip()))
        outcomes.append(
            ContenderOutcome(
                contender_id=contender.id,
                label=contender.label,
                output=output,
                oracle_passed=passed,
                score=score,
                duration_ms=dur,
            )
        )

    oa, ob = outcomes
    winner = "draw"
    reason = "tie"

    # Objective oracle pass always takes precedence over subjective scoring.
    if oa.oracle_passed is True and ob.oracle_passed is False:
        winner = contender_a.id
        reason = "passed objective oracle while opponent failed"
    elif ob.oracle_passed is True and oa.oracle_passed is False:
        winner = contender_b.id
        reason = "passed objective oracle while opponent failed"
    elif oa.score > ob.score:
        winner = contender_a.id
        reason = f"higher objective score ({oa.score:.2f} vs {ob.score:.2f})"
    elif ob.score > oa.score:
        winner = contender_b.id
        reason = f"higher objective score ({ob.score:.2f} vs {oa.score:.2f})"
    elif judge_fn is not None:
        verdict = (await judge_fn(task, oa.output, ob.output)).strip().upper()
        if verdict == "A":
            winner = contender_a.id
            reason = "blind judge selected Contender-A"
        elif verdict == "B":
            winner = contender_b.id
            reason = "blind judge selected Contender-B"
        else:
            winner = "draw"
            reason = "blind judge declared draw"

    mid, changes = store.record_match(
        task=task,
        contender_a=contender_a,
        contender_b=contender_b,
        winner=winner,
        reason=reason,
        scores={contender_a.id: oa.score, contender_b.id: ob.score},
    )
    return ArenaMatchResult(
        match_id=mid,
        task=task,
        winner=winner,
        reason=reason,
        outcomes=outcomes,
        rating_changes=changes,
    )
