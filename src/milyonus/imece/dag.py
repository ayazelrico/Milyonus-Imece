"""Cognitive Swarm DAG Workflow Compiler & Parallel Executor (PLAN-SINGULARITY S6).

Compiles declarative multi-agent workflows into Directed Acyclic Graphs (DAGs):
  1. Strict validation: duplicate ID rejection, missing dependency rejection,
     and Kahn topological cycle detection (fail-closed on cycles).
  2. Wave Scheduling + Critical-Path Method (CPM): partitions nodes into parallel
     execution waves and computes exact critical path latency & token budget.
  3. Concurrent Async Execution (`execute_dag`): runs wave siblings in parallel
     via `asyncio.gather` with dependency failure propagation (`skip_dependents`).
  4. Persistent SQLite run history (`dag_runs`) + Mermaid flowchart export.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
import time
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from milyonus.config.paths import state_db

_SCHEMA = """
CREATE TABLE IF NOT EXISTS dag_runs (
    run_id        TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    status        TEXT NOT NULL,
    node_count    INTEGER NOT NULL,
    wave_count    INTEGER NOT NULL,
    duration_ms   INTEGER NOT NULL,
    report_json   TEXT NOT NULL,
    created_at    REAL NOT NULL
);
"""


class DAGCompileError(Exception):
    """Raised when a workflow DAG contains cycles, duplicate IDs, or dangling deps."""


@dataclass(slots=True)
class DAGNode:
    id: str
    label: str
    role: str = "worker"
    depends_on: list[str] = field(default_factory=list)
    est_ms: int = 400
    est_tokens: int = 800

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class CompiledDAG:
    name: str
    nodes: dict[str, DAGNode]
    waves: list[list[str]]
    critical_path: list[str]
    critical_path_ms: int
    total_est_tokens: int
    mermaid: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "nodes": [n.to_dict() for n in self.nodes.values()],
            "waves": self.waves,
            "critical_path": self.critical_path,
            "critical_path_ms": self.critical_path_ms,
            "total_est_tokens": self.total_est_tokens,
            "mermaid": self.mermaid,
        }


def compile_dag(name: str, raw_nodes: Sequence[DAGNode | dict[str, Any]]) -> CompiledDAG:
    """Validate acyclicity, compute topological waves, CPM critical path, and Mermaid."""
    if not raw_nodes:
        raise DAGCompileError("workflow DAG must contain at least one node")
    nodes: dict[str, DAGNode] = {}
    for rn in raw_nodes:
        n = (
            rn
            if isinstance(rn, DAGNode)
            else DAGNode(
                id=str(rn["id"]).strip(),
                label=str(rn.get("label") or rn["id"]).strip(),
                role=str(rn.get("role") or "worker").strip(),
                depends_on=[str(d).strip() for d in (rn.get("depends_on") or []) if str(d).strip()],
                est_ms=max(1, int(rn.get("est_ms") or 400)),
                est_tokens=max(1, int(rn.get("est_tokens") or 800)),
            )
        )
        if not n.id:
            raise DAGCompileError("node id cannot be empty")
        if n.id in nodes:
            raise DAGCompileError(f"duplicate node id: {n.id}")
        nodes[n.id] = n

    indegree: dict[str, int] = dict.fromkeys(nodes, 0)
    children: dict[str, list[str]] = {nid: [] for nid in nodes}
    for nid, n in nodes.items():
        for dep in n.depends_on:
            if dep == nid:
                raise DAGCompileError(f"self-dependency cycle on node '{nid}'")
            if dep not in nodes:
                raise DAGCompileError(f"node '{nid}' depends on unknown node '{dep}'")
            indegree[nid] += 1
            children[dep].append(nid)

    # Kahn's topological wave scheduling.
    waves: list[list[str]] = []
    ready = sorted(nid for nid, deg in indegree.items() if deg == 0)
    visited = 0
    while ready:
        waves.append(ready)
        visited += len(ready)
        nxt: list[str] = []
        for cur in ready:
            for ch in children[cur]:
                indegree[ch] -= 1
                if indegree[ch] == 0:
                    nxt.append(ch)
        ready = sorted(nxt)

    if visited != len(nodes):
        raise DAGCompileError("cycle detected in workflow DAG (fail-closed)")

    # Critical Path Method (longest weighted path by est_ms).
    earliest_finish: dict[str, int] = {}
    pred_best: dict[str, str | None] = {}
    for wave in waves:
        for nid in wave:
            n = nodes[nid]
            if not n.depends_on:
                earliest_finish[nid] = n.est_ms
                pred_best[nid] = None
            else:
                best_dep = max(n.depends_on, key=lambda d: earliest_finish[d])
                earliest_finish[nid] = earliest_finish[best_dep] + n.est_ms
                pred_best[nid] = best_dep

    end_node = max(earliest_finish, key=lambda nid: earliest_finish[nid])
    crit_ms = earliest_finish[end_node]
    crit_path: list[str] = []
    cur_n: str | None = end_node
    while cur_n is not None:
        crit_path.append(cur_n)
        cur_n = pred_best[cur_n]
    crit_path.reverse()

    # Mermaid flowchart export.
    lines = ["flowchart LR"]
    for nid, n in nodes.items():
        safe_lbl = n.label.replace('"', "'")[:48]
        lines.append(f'  {nid}["{safe_lbl} ({n.role})"]')
    for nid, n in nodes.items():
        for dep in n.depends_on:
            lines.append(f"  {dep} --> {nid}")

    return CompiledDAG(
        name=name.strip() or "imece-dag",
        nodes=nodes,
        waves=waves,
        critical_path=crit_path,
        critical_path_ms=crit_ms,
        total_est_tokens=sum(n.est_tokens for n in nodes.values()),
        mermaid="\n".join(lines),
    )


NodeHandler = Callable[[DAGNode, dict[str, str]], Awaitable[str]]


async def _default_node_handler(node: DAGNode, upstream: dict[str, str]) -> str:
    return f"[{node.role}] completed '{node.label}' (inputs={len(upstream)})"


class DAGStore:
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

    def save_run(self, report: dict[str, Any]) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO dag_runs(run_id, name, status, node_count, wave_count, "
                "duration_ms, report_json, created_at) VALUES (?,?,?,?,?,?,?,?)",
                (
                    report["run_id"],
                    report["name"],
                    report["status"],
                    report["node_count"],
                    report["wave_count"],
                    report["duration_ms"],
                    json.dumps(report, ensure_ascii=False),
                    time.time(),
                ),
            )
            self._conn.commit()

    def list_runs(self, *, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT run_id, name, status, node_count, wave_count, duration_ms, created_at "
                "FROM dag_runs ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]


async def execute_dag(
    compiled: CompiledDAG,
    *,
    handler: NodeHandler | None = None,
    store: DAGStore | None = None,
) -> dict[str, Any]:
    """Execute a compiled DAG wave-by-wave concurrently with dependency failure gating."""
    fn = handler or _default_node_handler
    t0 = time.perf_counter()
    run_id = f"dag_{uuid.uuid4().hex[:12]}"
    outputs: dict[str, str] = {}
    statuses: dict[str, str] = {}
    node_traces: list[dict[str, Any]] = []

    for wave_idx, wave in enumerate(compiled.waves):

        async def _run_one(nid: str, w_idx: int = wave_idx) -> dict[str, Any]:
            node = compiled.nodes[nid]
            failed_deps = [d for d in node.depends_on if statuses.get(d) != "completed"]
            if failed_deps:
                statuses[nid] = "skipped"
                return {
                    "id": nid,
                    "wave": w_idx,
                    "status": "skipped",
                    "output": f"skipped due to failed/skipped deps: {', '.join(failed_deps)}",
                    "duration_ms": 0,
                }
            nt0 = time.perf_counter()
            try:
                upstream = {d: outputs[d] for d in node.depends_on}
                out = await fn(node, upstream)
                outputs[nid] = out
                statuses[nid] = "completed"
                return {
                    "id": nid,
                    "wave": w_idx,
                    "status": "completed",
                    "output": out,
                    "duration_ms": int(round((time.perf_counter() - nt0) * 1000)),
                }
            except Exception as exc:  # noqa: BLE001 - isolate node failure
                statuses[nid] = "failed"
                return {
                    "id": nid,
                    "wave": w_idx,
                    "status": "failed",
                    "output": str(exc),
                    "duration_ms": int(round((time.perf_counter() - nt0) * 1000)),
                }

        wave_results = await asyncio.gather(*(_run_one(nid) for nid in wave))
        node_traces.extend(wave_results)

    failed_cnt = sum(1 for s in statuses.values() if s == "failed")
    skipped_cnt = sum(1 for s in statuses.values() if s == "skipped")
    overall = "completed" if failed_cnt == 0 else "partial_failure"
    report = {
        "run_id": run_id,
        "name": compiled.name,
        "status": overall,
        "node_count": len(compiled.nodes),
        "wave_count": len(compiled.waves),
        "completed_count": sum(1 for s in statuses.values() if s == "completed"),
        "failed_count": failed_cnt,
        "skipped_count": skipped_cnt,
        "duration_ms": int(round((time.perf_counter() - t0) * 1000)),
        "compiled": compiled.to_dict(),
        "traces": node_traces,
    }
    if store is not None:
        store.save_run(report)
    return report
