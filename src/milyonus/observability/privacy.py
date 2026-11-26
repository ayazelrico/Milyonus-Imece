"""Differential Privacy Telemetry Vault & Budget Accountant (PLAN-SINGULARITY S7).

Provides genuine mathematical Laplace `(ε)`-Differential Privacy for sharing
aggregate agent telemetry (counts, sums, means, histograms) without leaking any
individual session's prompt length, latency, or cost:

  - Uses OS CSPRNG (`secrets.SystemRandom`) inverse-CDF Laplace sampling:
      `noise = -b * sign(u) * ln(1 - 2 * |u|)` where `b = sensitivity / epsilon`.
  - Clamps all input values strictly to `[lower, upper]` so global sensitivity
    `Δf` is mathematically bounded.
  - Enforces an irrevocable cumulative privacy budget `ε_max` in SQLite
    (`privacy_budgets`, `privacy_releases`), failing closed once exhausted so
    repeated queries cannot average out privacy noise!
"""

from __future__ import annotations

import math
import secrets
import sqlite3
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from milyonus.config.paths import state_db

_CSPRNG = secrets.SystemRandom()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS privacy_budgets (
    scope          TEXT PRIMARY KEY,
    max_epsilon    REAL NOT NULL,
    spent_epsilon  REAL NOT NULL DEFAULT 0.0,
    query_count    INTEGER NOT NULL DEFAULT 0,
    updated_at     REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS privacy_releases (
    release_id     TEXT PRIMARY KEY,
    scope          TEXT NOT NULL,
    metric         TEXT NOT NULL,
    epsilon_used   REAL NOT NULL,
    sensitivity    REAL NOT NULL,
    noise_scale    REAL NOT NULL,
    result_json    TEXT NOT NULL,
    created_at     REAL NOT NULL
);
"""


class PrivacyBudgetExhausted(Exception):
    """Raised fail-closed when a query would exceed the scope's ε_max privacy budget."""


@dataclass(slots=True)
class PrivacyReceipt:
    release_id: str
    scope: str
    metric: str
    value: Any
    epsilon_used: float
    epsilon_spent_total: float
    epsilon_remaining: float
    epsilon_max: float
    sensitivity: float
    noise_scale: float
    ci95_half_width: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def sample_laplace(scale: float) -> float:
    """Draw a zero-mean Laplace(0, scale) sample via CSPRNG inverse CDF."""
    if scale <= 0:
        raise ValueError("Laplace scale must be strictly positive")
    # Uniform in (-0.5, 0.5) avoiding exact -0.5/+0.5 domain endpoints.
    u = _CSPRNG.uniform(-0.499999999999, 0.499999999999)
    sign = -1.0 if u < 0 else 1.0
    return -scale * sign * math.log(1.0 - 2.0 * abs(u))


class PrivacyAccountant:
    """SQLite-persisted `(ε)`-Differential Privacy Accountant & Release Engine."""

    def __init__(self, path: Path | None = None, *, default_max_epsilon: float = 5.0) -> None:
        self.path = path or state_db()
        self.default_max_epsilon = max(0.1, float(default_max_epsilon))
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def budget_status(self, scope: str = "telemetry") -> dict[str, Any]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM privacy_budgets WHERE scope=?", (scope,)
            ).fetchone()
            if row is None:
                now = time.time()
                self._conn.execute(
                    "INSERT INTO privacy_budgets(scope, max_epsilon, spent_epsilon, query_count, updated_at) "
                    "VALUES (?,?,0.0,0,?)",
                    (scope, self.default_max_epsilon, now),
                )
                self._conn.commit()
                return {
                    "scope": scope,
                    "max_epsilon": self.default_max_epsilon,
                    "spent_epsilon": 0.0,
                    "remaining_epsilon": self.default_max_epsilon,
                    "query_count": 0,
                }
            mx = float(row["max_epsilon"])
            sp = float(row["spent_epsilon"])
            return {
                "scope": scope,
                "max_epsilon": round(mx, 4),
                "spent_epsilon": round(sp, 4),
                "remaining_epsilon": round(max(0.0, mx - sp), 4),
                "query_count": int(row["query_count"]),
            }

    def _charge(
        self,
        scope: str,
        epsilon: float,
        *,
        metric: str,
        sensitivity: float,
        value: Any,
    ) -> PrivacyReceipt:
        eps = float(epsilon)
        if eps <= 0 or not math.isfinite(eps):
            raise ValueError("epsilon must be finite and > 0")
        scale = sensitivity / eps
        # 95% confidence interval half-width for Laplace(0, b): b * ln(1 / 0.05) = b * ln(20)
        ci95 = round(scale * math.log(20.0), 4)
        rid = f"dp_{uuid.uuid4().hex[:12]}"

        with self._lock:
            st = self.budget_status(scope)
            mx = float(st["max_epsilon"])
            sp = float(st["spent_epsilon"])
            if sp + eps > mx + 1e-9:
                raise PrivacyBudgetExhausted(
                    f"privacy budget exhausted for '{scope}': requested ε={eps:.3f}, "
                    f"remaining ε={max(0.0, mx - sp):.3f} of ε_max={mx:.3f}"
                )
            new_sp = round(sp + eps, 6)
            now = time.time()
            self._conn.execute(
                "UPDATE privacy_budgets SET spent_epsilon=?, query_count=query_count+1, "
                "updated_at=? WHERE scope=?",
                (new_sp, now, scope),
            )
            import json

            self._conn.execute(
                "INSERT INTO privacy_releases(release_id, scope, metric, epsilon_used, "
                "sensitivity, noise_scale, result_json, created_at) VALUES (?,?,?,?,?,?,?,?)",
                (
                    rid,
                    scope,
                    metric,
                    eps,
                    sensitivity,
                    scale,
                    json.dumps(value, ensure_ascii=False),
                    now,
                ),
            )
            self._conn.commit()
        return PrivacyReceipt(
            release_id=rid,
            scope=scope,
            metric=metric,
            value=value,
            epsilon_used=round(eps, 4),
            epsilon_spent_total=round(new_sp, 4),
            epsilon_remaining=round(max(0.0, mx - new_sp), 4),
            epsilon_max=round(mx, 4),
            sensitivity=round(sensitivity, 4),
            noise_scale=round(scale, 4),
            ci95_half_width=ci95,
        )

    def release_metric(
        self,
        values: list[float],
        *,
        metric: str = "mean",  # "count" | "sum" | "mean" | "histogram"
        epsilon: float = 0.5,
        lower: float = 0.0,
        upper: float = 10_000.0,
        bins: int = 5,
        scope: str = "telemetry",
    ) -> PrivacyReceipt:
        """Compute and release a clamped, Laplace differentially private statistic."""
        if upper <= lower:
            raise ValueError("upper bound must exceed lower bound")
        clamped = [max(lower, min(upper, float(v))) for v in values]
        n = len(clamped)
        span = upper - lower

        if metric == "count":
            sens = 1.0
            noisy = max(0.0, round(n + sample_laplace(sens / epsilon), 2))
            return self._charge(scope, epsilon, metric="count", sensitivity=sens, value=noisy)

        if metric == "sum":
            sens = max(abs(lower), abs(upper))
            noisy = round(sum(clamped) + sample_laplace(sens / epsilon), 3)
            return self._charge(scope, epsilon, metric="sum", sensitivity=sens, value=noisy)

        if metric == "mean":
            if n == 0:
                raise ValueError("cannot compute DP mean of empty dataset")
            sens = span / n
            raw_mean = sum(clamped) / n
            noisy = round(max(lower, min(upper, raw_mean + sample_laplace(sens / epsilon))), 4)
            return self._charge(scope, epsilon, metric="mean", sensitivity=sens, value=noisy)

        if metric == "histogram":
            k = max(2, min(int(bins), 20))
            step = span / k
            counts = [0] * k
            for v in clamped:
                idx = min(k - 1, max(0, int((v - lower) / step)))
                counts[idx] += 1
            # Parallel composition: disjoint bins have global L1 sensitivity = 1.0!
            sens = 1.0
            hist = [
                {
                    "range": f"{round(lower + i * step, 2)}..{round(lower + (i + 1) * step, 2)}",
                    "noisy_count": max(0.0, round(counts[i] + sample_laplace(sens / epsilon), 2)),
                }
                for i in range(k)
            ]
            return self._charge(scope, epsilon, metric="histogram", sensitivity=sens, value=hist)

        raise ValueError(f"unsupported DP metric: {metric}")
