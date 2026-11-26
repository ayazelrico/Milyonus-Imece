"""Sovereign Epistemic Knowledge Graph & Contradiction Engine (PLAN-HYPERNOVA H1).

Projects verified memory items from `MemoryStore` into a provenance-backed directed
belief graph with:
  1. Deterministic semantic triple & polarity extraction (zero LLM cost),
  2. Automatic contradiction detection across active memories (polarity inversion
     and functional key-value conflicts) with trust-tier resolution recommendations,
  3. Iterative PageRank-style belief centrality ranking foundational memories,
  4. Downstream blast-radius traversal for any memory ID or source URI,
  5. Mermaid, Graphviz DOT, and structured JSON topology exporters.
"""

from __future__ import annotations

import hashlib
import re
from collections import deque
from dataclasses import asdict, dataclass, field
from typing import Any

from milyonus.memory.store import MemoryStore

_TIER_RANK: dict[str, int] = {"T0": 0, "T1": 1, "T2": 2, "T3": 3, "T4": 4}

# Matches directive polarity statements: "always use X", "never deploy Y", "must enable Z"
_POLARITY_RE = re.compile(
    r"\b(?P<pol>always|never|must not|must|do not|don't|forbid|forbidden|allow|disallow|enable|disable|use|avoid)\b"
    r"\s+(?P<target>[a-z0-9][a-z0-9_\-./: ]{1,60})",
    re.IGNORECASE,
)

# Matches functional key-value assertions: "deploy region is eu-central-1", "default port = 8080"
_KV_RE = re.compile(
    r"^(?:the\s+|our\s+|my\s+|default\s+|preferred\s+|primary\s+)?"
    r"(?P<subj>[a-z][a-z0-9_\- ]{1,36}?)\s*"
    r"(?P<pred>is|are|equals|=|:|uses|runs on|targets|set to)\s+"
    r"(?P<val>[a-z0-9_.\-/:@+ ]{1,64})",
    re.IGNORECASE,
)

_POSITIVE_POL = {"always", "must", "allow", "enable", "use"}
_NEGATIVE_POL = {
    "never",
    "must not",
    "do not",
    "don't",
    "forbid",
    "forbidden",
    "disallow",
    "disable",
    "avoid",
}
_STOP_TAILS = re.compile(r"[.,;!?]+.*$")


@dataclass(slots=True)
class ExtractedAssertion:
    subject: str
    predicate: str
    value: str
    polarity: str  # "positive" | "negative" | "assign"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class GraphNode:
    id: str
    kind: str  # "memory" | "source" | "entity"
    label: str
    trust_tier: str | None = None
    state: str | None = None
    centrality: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class GraphEdge:
    source: str
    target: str
    relation: str  # "derived_from" | "superseded_by" | "sourced_from" | "asserts" | "contradicts"
    weight: float = 1.0
    label: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class BeliefConflict:
    id: str
    kind: str  # "polarity_inversion" | "value_conflict"
    severity: str  # "high" | "medium"
    subject: str
    item_a: dict[str, Any]
    item_b: dict[str, Any]
    explanation: str
    recommended_winner: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class BlastRadiusReport:
    origin: str
    origin_kind: str  # "memory_id" | "source_uri"
    affected_ids: list[str]
    max_depth: int
    layers: dict[int, list[str]]
    affected_contents: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class EpistemicGraph:
    nodes: list[GraphNode] = field(default_factory=list)
    edges: list[GraphEdge] = field(default_factory=list)
    conflicts: list[BeliefConflict] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes": [n.to_dict() for n in self.nodes],
            "edges": [e.to_dict() for e in self.edges],
            "conflicts": [c.to_dict() for c in self.conflicts],
            "metrics": self.metrics,
        }

    def to_mermaid(self) -> str:
        lines = ["graph LR"]
        for n in self.nodes:
            safe_id = _safe_ident(n.id)
            label = n.label.replace('"', "'").replace("\n", " ")[:48]
            if n.kind == "source":
                lines.append(f'  {safe_id}[("{label}")]')
            elif n.kind == "entity":
                lines.append(f'  {safe_id}(("{label}"))')
            else:
                tier = n.trust_tier or "T?"
                lines.append(f'  {safe_id}["[{tier}] {label}"]')
        for e in self.edges:
            s = _safe_ident(e.source)
            t = _safe_ident(e.target)
            arrow = "-.->" if e.relation == "contradicts" else "-->"
            lbl = e.label or e.relation
            lines.append(f"  {s} {arrow}|{lbl}| {t}")
        return "\n".join(lines)

    def to_dot(self) -> str:
        lines = ["digraph MilyonusEpistemicGraph {", "  rankdir=LR;"]
        for n in self.nodes:
            safe_id = _safe_ident(n.id)
            label = n.label.replace('"', '\\"').replace("\n", " ")[:56]
            shape = "cylinder" if n.kind == "source" else "ellipse" if n.kind == "entity" else "box"
            lines.append(f'  {safe_id} [shape={shape}, label="{label}"];')
        for e in self.edges:
            s = _safe_ident(e.source)
            t = _safe_ident(e.target)
            style = " style=dashed color=red" if e.relation == "contradicts" else ""
            lbl = (e.label or e.relation).replace('"', '\\"')
            lines.append(f'  {s} -> {t} [label="{lbl}"{style}];')
        lines.append("}")
        return "\n".join(lines)


def _safe_ident(raw: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_]", "_", raw)
    if not cleaned or cleaned[0].isdigit():
        cleaned = "n_" + cleaned
    return cleaned[:40]


def _norm(text: str) -> str:
    cleaned = _STOP_TAILS.sub("", text).strip().lower()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned


def extract_assertions(content: str) -> list[ExtractedAssertion]:
    """Deterministically extract structured subject/predicate/polarity assertions."""
    out: list[ExtractedAssertion] = []
    seen: set[tuple[str, str, str, str]] = set()
    for sentence in re.split(r"[.;\n]+", content):
        sent = sentence.strip()
        if not sent:
            continue
        for m in _POLARITY_RE.finditer(sent):
            pol_word = m.group("pol").lower()
            target = _norm(m.group("target"))
            # Trim leading auxiliary verbs like "use" after always/never.
            target = re.sub(
                r"^(?:use|using|run|running|deploy|deploying|enable|enabling)\s+", "", target
            )
            if len(target) < 2:
                continue
            pol = "positive" if pol_word in _POSITIVE_POL else "negative"
            key = (target, "directive", pol, pol)
            if key not in seen:
                seen.add(key)
                out.append(
                    ExtractedAssertion(
                        subject=target, predicate="directive", value=pol, polarity=pol
                    )
                )
        kv = _KV_RE.match(sent)
        if kv:
            subj = _norm(kv.group("subj"))
            val = _norm(kv.group("val"))
            if len(subj) >= 2 and len(val) >= 1 and subj != val:
                key = (subj, "value", val, "assign")
                if key not in seen:
                    seen.add(key)
                    out.append(
                        ExtractedAssertion(
                            subject=subj, predicate="value", value=val, polarity="assign"
                        )
                    )
    return out


def _pick_winner(a: dict[str, Any], b: dict[str, Any]) -> str:
    rank_a = _TIER_RANK.get(str(a.get("trust_tier", "T4")), 9)
    rank_b = _TIER_RANK.get(str(b.get("trust_tier", "T4")), 9)
    if rank_a != rank_b:
        return str(a["id"]) if rank_a < rank_b else str(b["id"])
    ts_a = float(a.get("verified_at") or a.get("created_at") or 0.0)
    ts_b = float(b.get("verified_at") or b.get("created_at") or 0.0)
    return str(a["id"]) if ts_a >= ts_b else str(b["id"])


def detect_contradictions(items: list[dict[str, Any]]) -> list[BeliefConflict]:
    """Detect direct polarity inversions & functional value conflicts among active memories."""
    active = [it for it in items if it.get("state") == "active" and it.get("content")]
    by_polarity: dict[str, list[tuple[dict[str, Any], ExtractedAssertion]]] = {}
    by_kv: dict[str, list[tuple[dict[str, Any], ExtractedAssertion]]] = {}

    for it in active:
        for a in extract_assertions(str(it["content"])):
            if a.predicate == "directive":
                by_polarity.setdefault(a.subject, []).append((it, a))
            elif a.predicate == "value":
                by_kv.setdefault(a.subject, []).append((it, a))

    conflicts: list[BeliefConflict] = []
    seen_pairs: set[tuple[str, str, str]] = set()

    def _add(
        kind: str, subj: str, ia: dict[str, Any], ib: dict[str, Any], explanation: str
    ) -> None:
        id1, id2 = sorted((str(ia["id"]), str(ib["id"])))
        if id1 == id2 or (kind, id1, id2) in seen_pairs:
            return
        seen_pairs.add((kind, id1, id2))
        high = ia.get("trust_tier") in ("T0", "T1") or ib.get("trust_tier") in ("T0", "T1")
        cid = "conf_" + hashlib.sha256(f"{kind}:{subj}:{id1}:{id2}".encode()).hexdigest()[:10]
        conflicts.append(
            BeliefConflict(
                id=cid,
                kind=kind,
                severity="high" if high else "medium",
                subject=subj,
                item_a={
                    "id": ia["id"],
                    "trust_tier": ia["trust_tier"],
                    "content": ia["content"],
                    "source_uri": ia.get("source_uri"),
                },
                item_b={
                    "id": ib["id"],
                    "trust_tier": ib["trust_tier"],
                    "content": ib["content"],
                    "source_uri": ib.get("source_uri"),
                },
                explanation=explanation,
                recommended_winner=_pick_winner(ia, ib),
            )
        )

    for subj, entries in by_polarity.items():
        pos = [it for it, a in entries if a.polarity == "positive"]
        neg = [it for it, a in entries if a.polarity == "negative"]
        for p_item in pos:
            for n_item in neg:
                _add(
                    "polarity_inversion",
                    subj,
                    p_item,
                    n_item,
                    f"Opposite directives on '{subj}': positive ({p_item['id']}) vs negative ({n_item['id']}).",
                )

    for subj, entries in by_kv.items():
        for i in range(len(entries)):
            ia, aa = entries[i]
            for j in range(i + 1, len(entries)):
                ib, ab = entries[j]
                if aa.value != ab.value:
                    _add(
                        "value_conflict",
                        subj,
                        ia,
                        ib,
                        f"Conflicting values for '{subj}': '{aa.value}' ({ia['id']}) vs '{ab.value}' ({ib['id']}).",
                    )

    return conflicts


def compute_centrality(
    node_ids: list[str],
    edges: list[GraphEdge],
    *,
    damping: float = 0.85,
    iterations: int = 20,
) -> dict[str, float]:
    """Compute iterative PageRank belief centrality across graph nodes."""
    n = len(node_ids)
    if n == 0:
        return {}
    ranks = dict.fromkeys(node_ids, 1.0 / n)
    outgoing: dict[str, list[str]] = {nid: [] for nid in node_ids}
    incoming: dict[str, list[str]] = {nid: [] for nid in node_ids}
    node_set = set(node_ids)
    for e in edges:
        if e.source in node_set and e.target in node_set:
            outgoing[e.source].append(e.target)
            incoming[e.target].append(e.source)

    base = (1.0 - damping) / n
    for _ in range(iterations):
        nxt: dict[str, float] = {}
        dangling_sum = sum(ranks[nid] for nid in node_ids if not outgoing[nid])
        for nid in node_ids:
            in_sum = sum(ranks[src] / len(outgoing[src]) for src in incoming[nid] if outgoing[src])
            nxt[nid] = base + damping * (in_sum + dangling_sum / n)
        ranks = nxt
    return {k: round(v, 4) for k, v in ranks.items()}


def _load_memory_rows(
    store: MemoryStore, *, include_inactive: bool = False
) -> list[dict[str, Any]]:
    if include_inactive:
        rows = store._conn.execute(  # noqa: SLF001 - read-only graph projection
            "SELECT id, content, trust_tier, state, source_kind, source_uri, "
            "derived_from, superseded_by, trust_score, created_at, verified_at "
            "FROM memory WHERE state != 'erased' ORDER BY created_at ASC"
        ).fetchall()
    else:
        rows = store._conn.execute(  # noqa: SLF001 - read-only graph projection
            "SELECT id, content, trust_tier, state, source_kind, source_uri, "
            "derived_from, superseded_by, trust_score, created_at, verified_at "
            "FROM memory WHERE state IN ('active', 'pending', 't0_staged') ORDER BY created_at ASC"
        ).fetchall()
    return [dict(r) for r in rows]


def build_epistemic_graph(
    store: MemoryStore,
    *,
    include_inactive: bool = False,
) -> EpistemicGraph:
    """Build the full Epistemic Knowledge Graph & Contradiction report from `MemoryStore`."""
    rows = _load_memory_rows(store, include_inactive=include_inactive)
    nodes: dict[str, GraphNode] = {}
    edges: list[GraphEdge] = []
    mem_ids = {str(r["id"]) for r in rows}

    for r in rows:
        mid = str(r["id"])
        content = str(r.get("content") or "")
        assertions = extract_assertions(content)
        nodes[mid] = GraphNode(
            id=mid,
            kind="memory",
            label=content[:64] or mid,
            trust_tier=str(r["trust_tier"]),
            state=str(r["state"]),
            metadata={
                "source_kind": r.get("source_kind"),
                "source_uri": r.get("source_uri"),
                "trust_score": round(float(r.get("trust_score") or 1.0), 3),
                "assertions": [a.to_dict() for a in assertions],
            },
        )
        src_uri = r.get("source_uri")
        if src_uri:
            sid = "src:" + hashlib.sha256(str(src_uri).encode()).hexdigest()[:10]
            if sid not in nodes:
                nodes[sid] = GraphNode(
                    id=sid,
                    kind="source",
                    label=str(src_uri)[:64],
                    metadata={"uri": str(src_uri)},
                )
            edges.append(GraphEdge(source=mid, target=sid, relation="sourced_from"))

        derived = r.get("derived_from")
        if derived and str(derived) in mem_ids:
            edges.append(GraphEdge(source=mid, target=str(derived), relation="derived_from"))

        sup = r.get("superseded_by")
        if sup and str(sup) in mem_ids:
            edges.append(GraphEdge(source=mid, target=str(sup), relation="superseded_by"))

        for a in assertions:
            eid = "ent:" + hashlib.sha256(a.subject.encode()).hexdigest()[:10]
            if eid not in nodes:
                nodes[eid] = GraphNode(
                    id=eid,
                    kind="entity",
                    label=a.subject[:48],
                    metadata={"subject": a.subject},
                )
            edges.append(
                GraphEdge(
                    source=mid,
                    target=eid,
                    relation="asserts",
                    label=f"{a.predicate}:{a.value[:20]}",
                )
            )

    conflicts = detect_contradictions(rows)
    for c in conflicts:
        edges.append(
            GraphEdge(
                source=str(c.item_a["id"]),
                target=str(c.item_b["id"]),
                relation="contradicts",
                weight=2.0 if c.severity == "high" else 1.5,
                label=c.kind,
            )
        )

    centrality = compute_centrality(list(nodes.keys()), edges)
    for nid, rank in centrality.items():
        nodes[nid].centrality = rank

    ordered_nodes = sorted(nodes.values(), key=lambda x: (-x.centrality, x.kind, x.id))
    active_count = sum(1 for r in rows if r["state"] == "active")
    return EpistemicGraph(
        nodes=ordered_nodes,
        edges=edges,
        conflicts=conflicts,
        metrics={
            "node_count": len(ordered_nodes),
            "memory_nodes": sum(1 for n in ordered_nodes if n.kind == "memory"),
            "entity_nodes": sum(1 for n in ordered_nodes if n.kind == "entity"),
            "source_nodes": sum(1 for n in ordered_nodes if n.kind == "source"),
            "edge_count": len(edges),
            "active_memories": active_count,
            "conflict_count": len(conflicts),
            "high_severity_conflicts": sum(1 for c in conflicts if c.severity == "high"),
            "top_foundational_id": ordered_nodes[0].id if ordered_nodes else None,
        },
    )


def blast_radius(store: MemoryStore, origin: str) -> BlastRadiusReport:
    """Compute exact BFS downstream blast radius for a memory ID or source URI."""
    rows = _load_memory_rows(store, include_inactive=False)
    by_id = {str(r["id"]): r for r in rows}
    children: dict[str, list[str]] = {}
    for r in rows:
        parent = r.get("derived_from")
        if parent:
            children.setdefault(str(parent), []).append(str(r["id"]))

    if origin in by_id:
        origin_kind = "memory_id"
        seeds = [origin]
    else:
        origin_kind = "source_uri"
        seeds = [str(r["id"]) for r in rows if r.get("source_uri") == origin]

    visited: dict[str, int] = {}
    q: deque[tuple[str, int]] = deque((s, 0) for s in seeds)
    for s in seeds:
        visited[s] = 0

    while q:
        cur, depth = q.popleft()
        for ch in children.get(cur, []):
            if ch not in visited:
                visited[ch] = depth + 1
                q.append((ch, depth + 1))

    layers: dict[int, list[str]] = {}
    for mid, d in sorted(visited.items(), key=lambda kv: (kv[1], kv[0])):
        layers.setdefault(d, []).append(mid)

    affected_ids = sorted(visited.keys())
    return BlastRadiusReport(
        origin=origin,
        origin_kind=origin_kind,
        affected_ids=affected_ids,
        max_depth=max(layers.keys()) if layers else 0,
        layers=layers,
        affected_contents=[str(by_id[mid]["content"]) for mid in affected_ids if mid in by_id],
    )
