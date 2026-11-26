"""`milyonus memory ...` and `milyonus audit ...` commands.

These are the answer to "who wrote this memory and was it verified?" (PLAN §4.8).
Every command reads the same store the agent uses, so provenance is always one
command away.
"""

from __future__ import annotations

import time

import typer
from rich.console import Console
from rich.table import Table

from milyonus.brand import GLYPH, PALETTE
from milyonus.memory.store import MemoryStore

memory_app = typer.Typer(help="Inspect and manage verified memory.")
audit_app = typer.Typer(help="Verify the audit ledger.")
console = Console()

_TIER_COLOR = {
    "T0": PALETTE["chrome_200"],
    "T1": PALETTE["ok"],
    "T2": PALETTE["cyan_400"],
    "T3": PALETTE["warn"],
    "T4": PALETTE["quarantine"],
}


def _age(ts: float) -> str:
    secs = time.time() - ts
    if secs < 3600:
        return f"{int(secs // 60)}dk"
    if secs < 86400:
        return f"{int(secs // 3600)}sa"
    return f"{int(secs // 86400)}g"


@memory_app.command("list")
def memory_list() -> None:
    """List verified (active) durable memory."""
    store = MemoryStore()
    items = store.active()
    if not items:
        console.print(f"[dim]{GLYPH} durable memory is empty.[/]")
        raise typer.Exit()
    table = Table(title=f"{GLYPH} Durable Memory")
    table.add_column("Tier")
    table.add_column("Content", overflow="fold")
    table.add_column("Source")
    table.add_column("Age")
    table.add_column("id", style="dim")
    for m in items:
        color = _TIER_COLOR.get(m.trust_tier, "white")
        table.add_row(
            f"[{color}]{m.trust_tier}[/]",
            m.content,
            m.provenance.source_kind,
            _age(m.created_at),
            m.id,
        )
    console.print(table)


@memory_app.command("pending")
def memory_pending() -> None:
    """Show candidates pending in quarantine."""
    store = MemoryStore()
    items = store.by_state("pending")
    if not items:
        console.print(f"[dim]{GLYPH} quarantine is empty.[/]")
        raise typer.Exit()
    table = Table(title=f"{GLYPH} Quarantine (pending)")
    table.add_column("Tier")
    table.add_column("Content", overflow="fold")
    table.add_column("Source")
    table.add_column("Confirms")
    table.add_column("id", style="dim")
    for m in items:
        table.add_row(
            m.trust_tier,
            m.content,
            m.provenance.source_kind,
            str(m.confirmations),
            m.id,
        )
    console.print(table)


@memory_app.command("why")
def memory_why(item_id: str) -> None:
    """Show a memory's full provenance chain."""
    store = MemoryStore()
    m = store.get(item_id)
    if m is None:
        console.print(f"[{PALETTE['risk']}]Not found: {item_id}[/]")
        raise typer.Exit(code=1)
    console.print(f"[bold]{GLYPH} {m.id}[/]  [dim]{m.state}[/]")
    console.print(f"  content  : {m.content}")
    console.print(f"  tier     : {m.trust_tier}")
    console.print(f"  source   : {m.provenance.source_kind} {m.provenance.source_uri or ''}")
    console.print(f"  session  : {m.provenance.session_id} / turn {m.provenance.turn_id}")
    console.print(f"  actor    : {m.provenance.actor or '-'}")
    console.print(f"  evidence#: {m.evidence_hash}")
    console.print(f"  verdict  : {m.verdict or '-'}")
    console.print(f"  confirms : {m.confirmations}")
    console.print(
        f"  trust    : {m.trust_score:.2f}  (ceiling {m.trust_ceiling:.2f}, "
        f"reaffirmed {m.reaffirm_count}×)"
    )
    console.print(f"  sensitiv.: {m.sensitivity}")


@memory_app.command("diff")
def memory_diff(since: str = typer.Option("7d", help="e.g. 24h, 7d")) -> None:
    """What was learned/changed within the given window."""
    store = MemoryStore()
    unit = since[-1]
    value = int(since[:-1])
    seconds = value * {"h": 3600, "d": 86400}.get(unit, 86400)
    cutoff = time.time() - seconds
    recent = [m for m in store.active() if m.created_at >= cutoff]
    console.print(f"[bold]{GLYPH} {len(recent)} new memories in the last {since}[/]")
    for m in recent:
        console.print(f"  [{m.trust_tier}] {m.content}  [dim]{m.id}[/]")


@memory_app.command("revoke")
def memory_revoke(
    source: str = typer.Option(..., "--source", help="Source URI to revoke"),
) -> None:
    """Revoke all memory derived from a source (cascade)."""
    store = MemoryStore()
    revoked = store.revoke_by_source(source)
    console.print(
        f"[{PALETTE['quarantine']}]{GLYPH} revoked {len(revoked)} memories[/] (source: {source})"
    )
    for rid in revoked:
        console.print(f"  - {rid}")


@memory_app.command("search")
def memory_search(query: str) -> None:
    """Search active memory — trust-weighted semantic recall when the embedding
    layer is on, substring otherwise."""
    from milyonus.config.loader import load_config
    from milyonus.memory.semantic import SemanticMemory

    cfg = load_config()
    store = MemoryStore()
    sem = SemanticMemory(store, config=cfg.memory)
    if sem.enabled and sem.embedder is not None:
        recalls = sem.recall(query)
        if recalls:
            console.print(f"[dim]{GLYPH} semantic recall ({sem.embedder.signature})[/]")
            for r in recalls:
                console.print(
                    f"[{r.item.trust_tier}] {r.item.content}  "
                    f"[dim](cos {r.cosine:.2f} · trust {r.trust:.2f} · {r.item.id})[/]"
                )
            return
    q = query.casefold()
    hits = [m for m in store.active() if q in m.content.casefold()]
    if not hits:
        console.print("[dim]no matches[/]")
        raise typer.Exit()
    for m in hits:
        console.print(f"[{m.trust_tier}] {m.content}  [dim]{m.id}[/]")


@memory_app.command("reindex")
def memory_reindex() -> None:
    """(Re)build vector embeddings for all active memory — run after enabling or
    switching the embedder."""
    from milyonus.config.env import load_env
    from milyonus.config.loader import load_config
    from milyonus.memory.semantic import SemanticMemory

    load_env()
    cfg = load_config()
    store = MemoryStore()
    sem = SemanticMemory(store, config=cfg.memory)
    if not sem.enabled or sem.embedder is None:
        console.print(f"[{PALETTE['warn']}]{GLYPH} embedder is 'none' — nothing to index.[/]")
        raise typer.Exit()
    n = sem.reindex()
    console.print(
        f"[{PALETTE['ok']}]{GLYPH} indexed {n} memories[/] [dim]({sem.embedder.signature})[/]"
    )


@audit_app.command("verify")
def audit_verify() -> None:
    """Verify the memory audit ledger's hash chain."""
    store = MemoryStore()
    ok = store.verify_ledger()
    if ok:
        console.print(f"[{PALETTE['ok']}]{GLYPH} audit ledger integrity intact.[/]")
    else:
        console.print(f"[{PALETTE['risk']}]{GLYPH} WARNING: audit ledger tampered![/]")
        raise typer.Exit(code=1)


@audit_app.command("log")
def audit_log(limit: int = 30) -> None:
    """Show recent audit ledger entries."""
    store = MemoryStore()
    entries = store.ledger_entries(limit=limit)
    table = Table(title=f"{GLYPH} Audit Ledger")
    table.add_column("seq")
    table.add_column("action")
    table.add_column("item", style="dim")
    table.add_column("hash", style="dim")
    for e in reversed(entries):
        table.add_row(str(e["seq"]), e["action"], e["item_id"] or "-", e["entry_hash"][:12])
    console.print(table)


@memory_app.command("consolidate")
def memory_consolidate() -> None:
    """Sleep-time consolidation: process pending, expire due, merge
    duplicates, flag contradictions."""
    import asyncio

    from milyonus.config.env import load_env
    from milyonus.config.loader import load_config
    from milyonus.memory.consolidate import consolidate
    from milyonus.memory.pipeline import MemoryPipeline

    load_env()
    cfg = load_config()
    store = MemoryStore()
    pipeline = MemoryPipeline(store, config=cfg.memory)
    report = asyncio.run(consolidate(pipeline))
    console.print(f"[bold {PALETTE['cyan_400']}]{GLYPH} Consolidation[/]")
    console.print(f"  {report.summary()}")
    for a, b in report.contradictions:
        console.print(f"  [{PALETTE['warn']}]contradiction:[/] {a} <-> {b}")


@memory_app.command("reaffirm")
def memory_reaffirm(
    item_id: str,
    sign: str = typer.Option(
        None,
        "--sign",
        help="Path to an operator Ed25519 private key — a signed (strong) "
        "reaffirm restores full trust; without it the reaffirm is weak and its "
        "ceiling drops with repetition (H3).",
    ),
) -> None:
    """Re-earn trust for a memory — an explicit, rate-limited human action.

    Weak (default) reaffirm has diminishing returns; a strong operator-signed
    reaffirm restores 1.00. Reaffirming is a security boundary, not an undo:
    it is rate-limited and never available to the agent itself."""
    import time
    from pathlib import Path

    from milyonus.config.loader import load_config
    from milyonus.memory.store import ReaffirmError
    from milyonus.memory.trust import review_at

    cfg = load_config()
    store = MemoryStore()
    m = store.get(item_id)
    if m is None:
        console.print(f"[{PALETTE['risk']}]not found: {item_id}[/]")
        raise typer.Exit(code=1)

    signal = "weak"
    if sign:
        from milyonus.security.operator import crypto_available, verify
        from milyonus.security.operator import sign as op_sign

        if not crypto_available():
            console.print(
                f"[{PALETTE['risk']}]cryptography not installed (pip: milyonus[admin])[/]"
            )
            raise typer.Exit(code=1)
        try:
            payload = m.content.encode("utf-8")
            sig = op_sign(Path(sign), payload)
            if not verify(payload, sig):
                raise ValueError("signature did not verify against operator public key")
            signal = "strong"
        except Exception as exc:  # noqa: BLE001 - surface to operator
            console.print(f"[{PALETTE['risk']}]signed reaffirm failed:[/] {exc}")
            raise typer.Exit(code=1) from exc

    try:
        ceiling = store.reaffirm(
            item_id,
            review_at=review_at(m.trust_tier, time.time(), cfg.memory),
            min_interval_seconds=cfg.memory.reaffirm_min_interval_hours * 3600,
            signal=signal,
            weak_floor=cfg.memory.weak_reaffirm_floor,
        )
    except ReaffirmError as exc:
        console.print(f"[{PALETTE['warn']}]{GLYPH} rate-limited:[/] {exc}")
        raise typer.Exit(code=1) from exc
    tag = "strong (signed)" if signal == "strong" else "weak"
    console.print(
        f"[{PALETTE['ok']}]{GLYPH} reaffirmed[/] {item_id} — {tag}, trust ceiling {ceiling:.2f}"
    )


@memory_app.command("review")
def memory_review() -> None:
    """What the trust boundary flagged for a human: memory auto-demoted by decay,
    items due for review, and reaffirm anomalies (H4 — quarantine is not silent)."""
    from milyonus.config.loader import load_config

    cfg = load_config()
    store = MemoryStore()
    now = time.time()

    demoted = [
        m
        for m in store.by_state("pending")
        if m.reaffirm_count > 0 or m.last_reaffirmed_at is not None
    ]
    due = [m for m in store.active() if m.review_at is not None and m.review_at <= now]
    anomalous = [m for m in store.active() if m.reaffirm_count >= cfg.memory.reaffirm_anomaly_count]

    if not (demoted or due or anomalous):
        console.print(f"[dim]{GLYPH} nothing needs review — the boundary is quiet.[/]")
        raise typer.Exit()

    if demoted:
        console.print(f"[bold {PALETTE['quarantine']}]{GLYPH} Auto-demoted (trust decayed):[/]")
        for m in demoted:
            console.print(f"  [{m.trust_tier}] {m.content}  [dim]{m.id}[/]")
    if due:
        console.print(f"[bold {PALETTE['warn']}]{GLYPH} Due for review:[/]")
        for m in due:
            console.print(f"  [{m.trust_tier}] {m.content}  [dim]{m.id}[/]")
    if anomalous:
        console.print(
            f"[bold {PALETTE['risk']}]{GLYPH} Reaffirm anomalies "
            f"(≥{cfg.memory.reaffirm_anomaly_count}× — possible patient poisoning):[/]"
        )
        for m in anomalous:
            console.print(f"  [{m.trust_tier}] {m.content}  [dim]({m.reaffirm_count}× · {m.id})[/]")


@memory_app.command("stats")
def memory_stats() -> None:
    """Trust-boundary health: tier mix, sensitivity mix, and the false-positive
    recovery rate — how often auto-demoted memory gets reaffirmed back (H4)."""
    from milyonus.config.loader import load_config

    cfg = load_config()
    store = MemoryStore()
    active = store.active()
    pending = store.by_state("pending")

    tiers: dict[str, int] = {}
    sensitive = 0
    for m in active:
        tiers[m.trust_tier] = tiers.get(m.trust_tier, 0) + 1
        if m.sensitivity == "sensitive":
            sensitive += 1

    # Demotions and reaffirm-recoveries from the ledger → false-positive rate.
    demotions = recoveries = 0
    for e in store.ledger_entries(limit=10000):
        if e["action"] == "demote":
            demotions += 1
        elif e["action"] == "reaffirm":
            recoveries += 1
    fp_rate = (recoveries / demotions) if demotions else 0.0

    console.print(f"[bold {PALETTE['cyan_400']}]{GLYPH} Memory trust health[/]")
    console.print(f"  active     : {len(active)} ({sensitive} sensitive)")
    console.print(f"  quarantine : {len(pending)}")
    console.print("  tiers      : " + ", ".join(f"{k}={v}" for k, v in sorted(tiers.items())))
    console.print(f"  demotions  : {demotions}  ·  reaffirm-recoveries: {recoveries}")
    color = PALETTE["risk"] if fp_rate >= cfg.memory.false_positive_warn_rate else PALETTE["ok"]
    console.print(f"  FP recovery: [{color}]{fp_rate:.0%}[/]  (reaffirmed-back / demoted)")
    if fp_rate >= cfg.memory.false_positive_warn_rate:
        console.print(
            f"  [{PALETTE['warn']}]↑ high recovery rate — decay may be too aggressive; "
            "consider raising review windows.[/]"
        )


@memory_app.command("timeline")
def memory_timeline(
    limit: int = typer.Option(30, "--limit", help="Max checkpoints to show"),
) -> None:
    """List hash-verified memory ledger checkpoints for time-travel (M1)."""
    from milyonus.memory.timetravel import checkpoint_timeline

    store = MemoryStore()
    try:
        pts = checkpoint_timeline(store, limit=limit)
    finally:
        store.close()
    if not pts:
        console.print(f"[dim]{GLYPH} ledger is empty.[/]")
        return
    table = Table(title=f"{GLYPH} Memory Time-Travel Timeline")
    table.add_column("seq")
    table.add_column("action", style=f"bold {PALETTE['cyan_400']}")
    table.add_column("item", style="dim")
    table.add_column("preview")
    table.add_column("chain")
    for p in pts:
        mark = f"[{PALETTE['ok']}]✓[/]" if p.valid_link else f"[{PALETTE['risk']}]✗[/]"
        table.add_row(str(p.seq), p.action, p.item_id or "-", p.preview[:50], mark)
    console.print(table)


@memory_app.command("timetravel")
def memory_timetravel(
    seq: int | None = typer.Option(None, "--seq", help="Reconstruct state up to ledger sequence N"),
    at: float | None = typer.Option(None, "--at", help="Reconstruct state at Unix timestamp"),
) -> None:
    """Reconstruct exact memory state and `<milyonus:memory>` snapshot at any historical point (M1)."""
    from milyonus.memory.timetravel import reconstruct_at

    store = MemoryStore()
    try:
        snap = reconstruct_at(store, seq=seq, at_timestamp=at)
    finally:
        store.close()
    status = (
        f"[{PALETTE['ok']}]intact[/]" if snap.chain_intact else f"[{PALETTE['risk']}]TAMPERED[/]"
    )
    console.print(
        f"[bold {PALETTE['cyan_400']}]{GLYPH} Snapshot @ seq #{snap.seq}[/] "
        f"· active={snap.active_count} · pending={snap.pending_count} "
        f"· revoked={snap.revoked_count} · chain={status}"
    )
    if snap.rendered_snapshot:
        console.print(snap.rendered_snapshot, markup=False)
    else:
        console.print("[dim](no active memory at this checkpoint)[/]")


@memory_app.command("epoch-diff")
def memory_epoch_diff(from_seq: int, to_seq: int) -> None:
    """Compare reconstructed memory between two ledger sequence numbers (M1)."""
    from milyonus.memory.timetravel import diff_snapshots

    store = MemoryStore()
    try:
        diff = diff_snapshots(store, from_seq, to_seq)
    finally:
        store.close()
    console.print(
        f"[bold {PALETTE['cyan_400']}]{GLYPH} Diff seq #{diff.from_seq} → #{diff.to_seq}[/] "
        f"· +{len(diff.added)} added · -{len(diff.removed)} removed · "
        f"~{len(diff.state_changed)} changed · {diff.unchanged_count} unchanged"
    )
    for item in diff.added:
        console.print(
            f"  [{PALETTE['ok']}]+[/] [{item['trust_tier']}/{item['state']}] {item['content']}"
        )
    for ch in diff.state_changed:
        console.print(
            f"  [{PALETTE['warn']}]~[/] {ch['id']}: {ch['from_state']} → {ch['to_state']} "
            f"({ch['content'][:60]})"
        )


@memory_app.command("counterfactual")
def memory_counterfactual(source_uri: str) -> None:
    """Simulate revoking `source_uri` without mutating live memory (M1)."""
    from milyonus.memory.timetravel import counterfactual_revoke

    store = MemoryStore()
    try:
        rep = counterfactual_revoke(store, source_uri)
    finally:
        store.close()
    console.print(
        f"[bold {PALETTE['cyan_400']}]{GLYPH} Counterfactual revoke[/] {rep.source_uri}\n"
        f"  affected : {len(rep.affected_ids)} ({rep.direct_count} direct, {rep.derived_count} derived)\n"
        f"  active   : {rep.before_active_count} → {rep.after_active_count} "
        f"(~{rep.tokens_freed_estimate} tokens freed)"
    )


@memory_app.command("graph")
def memory_graph(
    fmt: str = typer.Option(
        "mermaid", "--format", "-f", help="Output format: mermaid | dot | json"
    ),
    include_inactive: bool = typer.Option(False, "--all", help="Include revoked/rejected nodes"),
) -> None:
    """Export the Sovereign Epistemic Knowledge Graph from verified memory (H1)."""
    import json

    from milyonus.memory.graph import build_epistemic_graph

    store = MemoryStore()
    try:
        g = build_epistemic_graph(store, include_inactive=include_inactive)
    finally:
        store.close()
    if fmt == "json":
        console.print(json.dumps(g.to_dict(), indent=2, ensure_ascii=False), markup=False)
    elif fmt == "dot":
        console.print(g.to_dot(), markup=False)
    else:
        console.print(g.to_mermaid(), markup=False)


@memory_app.command("conflicts")
def memory_conflicts() -> None:
    """Detect active belief contradictions and trust-tier conflict resolutions (H1)."""
    from milyonus.memory.graph import build_epistemic_graph

    store = MemoryStore()
    try:
        g = build_epistemic_graph(store)
    finally:
        store.close()
    if not g.conflicts:
        console.print(f"[{PALETTE['ok']}]{GLYPH} 0 epistemic contradictions detected.[/]")
        return
    table = Table(title=f"{GLYPH} Epistemic Contradictions ({len(g.conflicts)})")
    table.add_column("Severity")
    table.add_column("Kind")
    table.add_column("Subject")
    table.add_column("Explanation")
    table.add_column("Winner")
    for c in g.conflicts:
        color = PALETTE["risk"] if c.severity == "high" else PALETTE["warn"]
        table.add_row(
            f"[{color}]{c.severity}[/]",
            c.kind,
            c.subject,
            c.explanation,
            c.recommended_winner,
        )
    console.print(table)


@memory_app.command("blast-radius")
def memory_blast_radius(origin: str) -> None:
    """Compute downstream belief blast radius for a memory ID or source URI (H1)."""
    from milyonus.memory.graph import blast_radius

    store = MemoryStore()
    try:
        rep = blast_radius(store, origin)
    finally:
        store.close()
    console.print(
        f"[bold {PALETTE['cyan_400']}]{GLYPH} Blast radius[/] ({rep.origin_kind}: {rep.origin})\n"
        f"  affected : {len(rep.affected_ids)} item(s) · max depth {rep.max_depth}"
    )
    for depth, ids in rep.layers.items():
        console.print(f"  depth {depth}: {', '.join(ids)}")
