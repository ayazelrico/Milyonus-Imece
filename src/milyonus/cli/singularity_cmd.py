"""Singularity CLI apps (PLAN-SINGULARITY S1–S3, S5–S10).

Mounts: `shield`, `passport`, `shadow`, `surgeon`, `dag`, `privacy`, `certify`, `fuzz`, `economy`.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from milyonus.brand import GLYPH, PALETTE

console = Console()

# --- S1: Deep Behavioral Intent Shield ----------------------------------

shield_app = typer.Typer(
    help="Analyze subtle behavioral poisoning, persona hijacks & covert exfil (S1)."
)


@shield_app.command("scan")
def shield_scan(
    text: str = typer.Argument(..., help="Text to inspect for subtle poisoning"),
) -> None:
    """Run 4-axis EN/TR subtle behavioral intent threat analysis."""
    from milyonus.security.intent_shield import analyze_intent

    rep = analyze_intent(text)
    color = PALETTE["ok"] if rep.verdict == "allow" else PALETTE["risk"]
    console.print(
        f"[{color}]{GLYPH} Intent Shield: {rep.verdict.upper()}[/] "
        f"(risk={rep.risk_score:.2f} · axes={','.join(rep.axes_triggered) or 'none'})"
    )
    for s in rep.signals:
        console.print(f"  - [{s.axis}/{s.rule}] {s.excerpt}")
    if rep.verdict != "allow":
        raise typer.Exit(1)


# --- S2: Cryptographic Agent Passports ----------------------------------

passport_app = typer.Typer(help="Issue and offline-verify cryptographic Agent Passports (S2).")


@passport_app.command("issue")
def passport_issue(
    agent_name: str = typer.Option("milyonus-agent", "--name", "-n"),
    constitution: str = typer.Option("fortress-security", "--constitution", "-c"),
    out: str = typer.Option("agent.milyonus-passport.json", "--out", "-o"),
    sign_key: str | None = typer.Option(None, "--sign"),
) -> None:
    """Issue a hashed (and optionally Ed25519-signed) Agent Passport."""
    from milyonus.memory.store import MemoryStore
    from milyonus.security.passport import issue_passport

    ms = MemoryStore()
    try:
        p = issue_passport(
            agent_name=agent_name,
            constitution_name=constitution,
            memory_store=ms,
            sign_key=Path(sign_key) if sign_key else None,
        )
    finally:
        ms.close()
    Path(out).write_text(json.dumps(p, indent=2, ensure_ascii=False), encoding="utf-8")
    console.print(
        f"[{PALETTE['ok']}]{GLYPH} Passport issued[/] → {out} "
        f"[dim]({p['did']} · badge={p['trust_badge']})[/]"
    )


@passport_app.command("verify")
def passport_verify(
    path: str = typer.Argument(..., help="Path to `.milyonus-passport.json`"),
    min_chaos: int = typer.Option(90, "--min-chaos"),
    require_signature: bool = typer.Option(False, "--require-signature"),
) -> None:
    """Offline fail-closed verification of an Agent Passport."""
    from milyonus.security.passport import verify_passport

    data = json.loads(Path(path).read_text(encoding="utf-8"))
    res = verify_passport(data, min_chaos_score=min_chaos, require_signature=require_signature)
    if res.valid:
        console.print(
            f"[{PALETTE['ok']}]{GLYPH} PASSPORT VALID[/] "
            f"({res.did} · badge={res.trust_badge} · {res.checks_passed} checks)"
        )
    else:
        console.print(f"[{PALETTE['risk']}]{GLYPH} PASSPORT INVALID[/]")
        for e in res.errors:
            console.print(f"  - {e}")
        raise typer.Exit(1)


# --- S3: Speculative Shadow-Fork Engine ---------------------------------

shadow_app = typer.Typer(
    help="Speculatively execute workspace mutations in an isolated shadow fork (S3)."
)


@shadow_app.command("preview")
def shadow_preview(
    workspace: str = typer.Argument(..., help="Target workspace directory"),
    rel_path: str = typer.Option(..., "--file", "-f", help="Relative file path inside workspace"),
    content: str = typer.Option(..., "--content", "-c", help="Proposed file content"),
) -> None:
    """Preview unified diff & security scan in a shadow fork without touching live files."""
    from milyonus.core.shadow import ShadowOperation, simulate_shadow

    rep = simulate_shadow(Path(workspace), [ShadowOperation("write", rel_path, content)])
    color = PALETTE["ok"] if rep.safe_to_commit else PALETTE["risk"]
    console.print(
        f"[{color}]{GLYPH} Shadow {rep.plan_id}[/] · risk={rep.risk_level} · "
        f"safe_to_commit={rep.safe_to_commit} · files={rep.files_changed}"
    )
    for d in rep.diffs:
        if d.unified_diff:
            console.print(d.unified_diff, markup=False)
    if not rep.safe_to_commit:
        raise typer.Exit(1)


# --- S5: Autonomous AST Self-Patching Code Surgeon ----------------------

surgeon_app = typer.Typer(
    help="AST-scan Python files and synthesize verified security/reliability patches (S5)."
)


@surgeon_app.command("scan")
def surgeon_scan(
    target_file: str = typer.Argument(..., help="Python file to inspect"),
    show_diff: bool = typer.Option(True, "--diff/--no-diff"),
) -> None:
    """AST-scan a Python file and print health grade + verified micro-patch diff."""
    from milyonus.selfmod.surgeon import analyze_and_patch

    p = Path(target_file)
    if not p.is_file():
        console.print(f"[{PALETTE['risk']}]file not found: {p}[/]")
        raise typer.Exit(1)
    rep = analyze_and_patch(p.read_text(encoding="utf-8"), filename=p.name)
    color = PALETTE["ok"] if rep.health_score >= 90 else PALETTE["warn"]
    console.print(
        f"[bold {color}]{GLYPH} Code Surgeon: {rep.health_score}/100 ({rep.grade})[/] "
        f"· {len(rep.findings)} finding(s) · patch_ast_ok={rep.patch_ast_verified}"
    )
    for f in rep.findings:
        console.print(f"  L{f.line} [{f.severity}] {f.rule_id}: {f.message}")
    if show_diff and rep.unified_diff:
        console.print(rep.unified_diff, markup=False)


# --- S6: Cognitive Swarm DAG Workflow Compiler --------------------------

dag_app = typer.Typer(help="Compile and execute parallel multi-agent DAG workflows (S6).")


@dag_app.command("run")
def dag_run(
    name: str = typer.Option("imece-pipeline", "--name", "-n"),
) -> None:
    """Compile and execute the reference 5-node Kapı 1→İmece→Kapı 2→Kapı 3 parallel DAG."""
    from milyonus.imece.dag import DAGStore, compile_dag, execute_dag

    nodes = [
        {
            "id": "kapi1_frame",
            "label": "Kapı 1 Framing",
            "role": "framing",
            "depends_on": [],
            "est_ms": 300,
        },
        {
            "id": "build_a",
            "label": "Approach A Builder",
            "role": "worker",
            "depends_on": ["kapi1_frame"],
            "est_ms": 600,
        },
        {
            "id": "build_b",
            "label": "Approach B Builder",
            "role": "worker",
            "depends_on": ["kapi1_frame"],
            "est_ms": 500,
        },
        {
            "id": "kapi2_verify",
            "label": "Kapı 2 Reality Gate",
            "role": "verifier",
            "depends_on": ["build_a", "build_b"],
            "est_ms": 400,
        },
        {
            "id": "kapi3_approve",
            "label": "Kapı 3 Blind Approval",
            "role": "approval",
            "depends_on": ["kapi2_verify"],
            "est_ms": 250,
        },
    ]
    compiled = compile_dag(name, nodes)
    st = DAGStore()
    try:
        rep = asyncio.run(execute_dag(compiled, store=st))
    finally:
        st.close()
    console.print(
        f"[{PALETTE['ok']}]{GLYPH} DAG {rep['run_id']}[/] · status={rep['status']} · "
        f"waves={rep['wave_count']} · critical_path={' → '.join(compiled.critical_path)} "
        f"({compiled.critical_path_ms}ms)"
    )


# --- S7: Differential Privacy Telemetry Vault ---------------------------

privacy_app = typer.Typer(
    help="Laplace (ε)-Differential Privacy telemetry vault & budget accountant (S7)."
)


@privacy_app.command("status")
def privacy_status(scope: str = typer.Option("telemetry", "--scope")) -> None:
    """Show remaining ε privacy budget for a telemetry scope."""
    from milyonus.observability.privacy import PrivacyAccountant

    acc = PrivacyAccountant()
    try:
        st = acc.budget_status(scope)
    finally:
        acc.close()
    console.print(
        f"[bold {PALETTE['cyan_400']}]{GLYPH} DP Budget ({st['scope']})[/]: "
        f"spent ε={st['spent_epsilon']} / max ε={st['max_epsilon']} "
        f"(remaining ε={st['remaining_epsilon']} · {st['query_count']} queries)"
    )


@privacy_app.command("release")
def privacy_release(
    values: str = typer.Argument(..., help="Comma-separated numeric values"),
    metric: str = typer.Option("mean", "--metric", "-m"),
    epsilon: float = typer.Option(0.5, "--epsilon", "-e"),
    scope: str = typer.Option("telemetry", "--scope"),
) -> None:
    """Release a Laplace differentially private aggregate and debit the privacy budget."""
    from milyonus.observability.privacy import PrivacyAccountant, PrivacyBudgetExhausted

    nums = [float(x.strip()) for x in values.split(",") if x.strip()]
    acc = PrivacyAccountant()
    try:
        rec = acc.release_metric(nums, metric=metric, epsilon=epsilon, scope=scope)
    except PrivacyBudgetExhausted as exc:
        console.print(f"[{PALETTE['risk']}]{exc}[/]")
        raise typer.Exit(1) from exc
    finally:
        acc.close()
    console.print(
        f"[{PALETTE['ok']}]{GLYPH} DP {rec.metric}[/] = {rec.value} "
        f"[dim](±{rec.ci95_half_width} 95% CI · ε_rem={rec.epsilon_remaining})[/]"
    )


# --- S8: Enterprise 6-Pillar Compliance Certifier -----------------------

certify_app = typer.Typer(help="Run 6-pillar enterprise compliance certification audit (S8).")


@certify_app.command("run")
def certify_run(
    out: str | None = typer.Option(None, "--out", "-o", help="Optional `.milyonus-cert.json` path"),
    min_score: int = typer.Option(90, "--min-score"),
) -> None:
    """Audit all 6 defense/integrity pillars and issue a readiness certificate."""
    from milyonus.evaluation.certifier import run_compliance_certification

    cert = asyncio.run(run_compliance_certification())
    if out:
        Path(out).write_text(json.dumps(cert, indent=2, ensure_ascii=False), encoding="utf-8")
    color = PALETTE["ok"] if cert["overall_score"] >= min_score else PALETTE["risk"]
    console.print(
        f"[bold {color}]{GLYPH} Readiness Certificate {cert['cert_id']}: "
        f"{cert['overall_score']}/100 ({cert['tier']})[/] · sha256={cert['cert_sha256'][:12]}…"
    )
    for p in cert["pillars"]:
        mark = "✓" if p["passed"] else "✗"
        console.print(f"  {mark} {p['pillar']:22s} {p['score']:3d}/100 — {p['detail']}")
    if cert["overall_score"] < min_score:
        raise typer.Exit(1)


# --- S9: Adversarial Mutation Security Fuzzer ---------------------------

fuzz_app = typer.Typer(help="Run seeded mutation fuzzing across Milyonus security guards (S9).")


@fuzz_app.command("run")
def fuzz_run(
    iterations: int = typer.Option(50, "--iterations", "-n", min=10, max=250),
    seed: int = typer.Option(42, "--seed"),
) -> None:
    """Fuzz SSRF, preexec, path jail, zero-width injection, and intent shield."""
    from milyonus.security.fuzzer import run_security_fuzz

    rep = asyncio.run(run_security_fuzz(iterations=iterations, seed=seed))
    color = PALETTE["ok"] if rep.bypass_count == 0 else PALETTE["risk"]
    console.print(
        f"[bold {color}]{GLYPH} Security Fuzz[/]: {rep.blocked_cases}/{rep.total_cases} blocked "
        f"({rep.block_rate:.1%}) · {rep.bypass_count} bypasses · {rep.duration_ms}ms"
    )
    if rep.bypass_count > 0:
        for b in rep.bypasses[:5]:
            console.print(f"  [{PALETTE['risk']}]BYPASS[/] [{b.family}] {b.payload_preview}")
        raise typer.Exit(1)


# --- S10: Multi-Agent Collective Economy Simulator ----------------------

economy_app = typer.Typer(
    help="Simulate İmece token economy, Pareto savings & ETA across scales (S10)."
)


@economy_app.command("scales")
def economy_scales(parallel: int = typer.Option(16, "--parallel", "-p")) -> None:
    """Compare Pareto hybrid vs frontier-only collective costs from 17 to 10,000 agents."""
    from milyonus.observability.economy import compare_scales

    rows = compare_scales(max_parallel=parallel)
    table = Table(title=f"{GLYPH} İmece Collective Economy Forecast (parallel={parallel})")
    table.add_column("Agents", style=f"bold {PALETTE['cyan_400']}")
    table.add_column("Est. Tokens")
    table.add_column("Pareto Hybrid")
    table.add_column("Frontier Baseline")
    table.add_column("Savings")
    table.add_column("Est. ETA")
    table.add_column("Est. Pass P")
    for r in rows:
        table.add_row(
            f"{r['agents']:,}",
            f"{r['total_est_tokens']:,}",
            f"${r['hybrid_cost_usd']:.2f}",
            f"${r['frontier_baseline_usd']:.2f}",
            f"{r['savings_pct']:.1f}%",
            f"{r['est_wall_clock_s']:.1f}s",
            f"{r['estimated_collective_pass_prob']:.1%}",
        )
    console.print(table)
