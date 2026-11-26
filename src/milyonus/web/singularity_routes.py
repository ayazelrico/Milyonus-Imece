"""FastAPI Web Surface #7 routes for all 10 Singularity Capabilities (PLAN-SINGULARITY S1–S10).

Mounted into `create_app()` in `milyonus.web.app`. Strictly authenticated, CSRF-checked,
rate-limited, and tenant-isolated via `tenant_home(root, principal.tenant_id)`.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field

from milyonus.web.auth import SessionPrincipal
from milyonus.web.runner import tenant_home
from milyonus.web.store import WebStore


class IntentScanIn(BaseModel):
    text: str = Field(min_length=1, max_length=20_000)


class PassportIssueIn(BaseModel):
    agent_name: str = Field(default="milyonus-web-agent", min_length=1, max_length=80)
    constitution_name: str = Field(default="fortress-security")
    ttl_seconds: float = Field(default=86_400.0, ge=60.0, le=2_592_000.0)


class PassportVerifyIn(BaseModel):
    passport: dict[str, Any]
    min_chaos_score: int = Field(default=90, ge=0, le=100)
    require_signature: bool = True


class ShadowOpIn(BaseModel):
    op: str = Field(default="write")  # "write" | "delete" | "mkdir"
    path: str = Field(min_length=1, max_length=240)
    content: str = Field(default="", max_length=200_000)


class ShadowPlanIn(BaseModel):
    operations: list[ShadowOpIn] = Field(min_length=1, max_length=20)
    expected_pre_images: dict[str, str | None] | None = None


class SurgeonIn(BaseModel):
    source: str = Field(min_length=1, max_length=100_000)
    filename: str = Field(default="snippet.py", min_length=1, max_length=80)


class DAGIn(BaseModel):
    name: str = Field(default="imece-dag", min_length=1, max_length=80)
    nodes: list[dict[str, Any]] = Field(min_length=1, max_length=40)


class PrivacyReleaseIn(BaseModel):
    values: list[float] = Field(min_length=1, max_length=2000)
    metric: str = Field(default="mean")
    epsilon: float = Field(default=0.5, gt=0.0, le=5.0)
    lower: float = Field(default=0.0)
    upper: float = Field(default=10_000.0)
    bins: int = Field(default=5, ge=2, le=20)
    scope: str = Field(default="telemetry", min_length=1, max_length=48)


class FuzzIn(BaseModel):
    iterations: int = Field(default=30, ge=10, le=120)
    seed: int = Field(default=42)


class EconomySimIn(BaseModel):
    agents: int = Field(default=250, ge=17, le=100_000)
    rounds: int = Field(default=1, ge=1, le=10)
    max_parallel: int = Field(default=16, ge=1, le=256)
    worker_model: str = Field(default="google/gemini-2.5-flash")
    gate_model: str = Field(default="anthropic/claude-sonnet-4")
    single_agent_pass_prob: float = Field(default=0.55, ge=0.05, le=0.99)


def _tenant_passport_key(home: Path) -> bytes:
    return hashlib.sha256(f"milyonus-passport:{home.resolve()}".encode()).digest()


def mount_singularity_routes(
    app: FastAPI,
    *,
    root: Path,
    store: WebStore,
    current: Callable[..., SessionPrincipal],
) -> None:
    """Attach all S1–S10 Singularity REST routes to the FastAPI app."""

    # --- S1: Deep Behavioral Intent & Subtle Poisoning Shield -----------

    @app.post("/v1/security/intent-scan")
    def security_intent_scan(
        body: IntentScanIn, principal: SessionPrincipal = Depends(current)
    ) -> dict[str, Any]:
        del principal
        from milyonus.security.intent_shield import analyze_intent

        return analyze_intent(body.text).to_dict()

    # --- S2: Cryptographic Agent Passports ------------------------------

    @app.post("/v1/passport/issue")
    def passport_issue(
        body: PassportIssueIn, principal: SessionPrincipal = Depends(current)
    ) -> dict[str, Any]:
        home = tenant_home(root, principal.tenant_id)
        from milyonus.memory.store import MemoryStore
        from milyonus.security.passport import issue_passport

        ms = MemoryStore(home / "state.db")
        try:
            return issue_passport(
                agent_name=body.agent_name,
                constitution_name=body.constitution_name,
                memory_store=ms,
                skills_root=home / "skills",
                ttl_seconds=body.ttl_seconds,
                hmac_secret=_tenant_passport_key(home),
            )
        finally:
            ms.close()

    @app.post("/v1/passport/verify")
    def passport_verify(
        body: PassportVerifyIn, principal: SessionPrincipal = Depends(current)
    ) -> dict[str, Any]:
        home = tenant_home(root, principal.tenant_id)
        from milyonus.security.passport import verify_passport

        return verify_passport(
            body.passport,
            hmac_secret=_tenant_passport_key(home),
            require_signature=body.require_signature,
            min_chaos_score=body.min_chaos_score,
        ).to_dict()

    # --- S3: Speculative Shadow-Fork Dry-Run Engine ---------------------

    @app.post("/v1/shadow/simulate")
    def shadow_simulate(
        body: ShadowPlanIn, principal: SessionPrincipal = Depends(current)
    ) -> dict[str, Any]:
        ws = tenant_home(root, principal.tenant_id) / "workspace"
        from milyonus.core.shadow import ShadowEscapeError, ShadowOperation, simulate_shadow

        ops = [ShadowOperation(o.op, o.path, o.content) for o in body.operations]
        try:
            return simulate_shadow(ws, ops).to_dict()
        except (ShadowEscapeError, ValueError) as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.post("/v1/shadow/apply")
    def shadow_apply(
        body: ShadowPlanIn, principal: SessionPrincipal = Depends(current)
    ) -> dict[str, Any]:
        ws = tenant_home(root, principal.tenant_id) / "workspace"
        from milyonus.core.shadow import ShadowEscapeError, ShadowOperation, commit_shadow

        ops = [ShadowOperation(o.op, o.path, o.content) for o in body.operations]
        try:
            res = commit_shadow(ws, ops, expected_pre_images=body.expected_pre_images)
        except (ShadowEscapeError, ValueError) as exc:
            raise HTTPException(422, str(exc)) from exc
        if not res["committed"]:
            raise HTTPException(409, res["reason"])
        return res

    # --- S4: Temporal Causal Memory Decay Forecast ----------------------

    @app.get("/v1/memory/forecast")
    def memory_forecast(
        days: int = 90, principal: SessionPrincipal = Depends(current)
    ) -> dict[str, Any]:
        from milyonus.memory.forecast import forecast_memory_decay
        from milyonus.memory.store import MemoryStore

        ms = MemoryStore(tenant_home(root, principal.tenant_id) / "state.db")
        try:
            return forecast_memory_decay(ms, horizon_days=max(1, min(days, 365))).to_dict()
        finally:
            ms.close()

    # --- S5: Autonomous AST Self-Patching Code Surgeon ------------------

    @app.post("/v1/surgeon/analyze")
    def surgeon_analyze(
        body: SurgeonIn, principal: SessionPrincipal = Depends(current)
    ) -> dict[str, Any]:
        del principal
        from milyonus.selfmod.surgeon import analyze_and_patch

        return analyze_and_patch(body.source, filename=body.filename).to_dict()

    # --- S6: Cognitive Swarm DAG Workflow Compiler ----------------------

    @app.post("/v1/dag/compile")
    def dag_compile(body: DAGIn, principal: SessionPrincipal = Depends(current)) -> dict[str, Any]:
        del principal
        from milyonus.imece.dag import DAGCompileError, compile_dag

        try:
            return compile_dag(body.name, body.nodes).to_dict()
        except DAGCompileError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.post("/v1/dag/run")
    async def dag_run(
        body: DAGIn, principal: SessionPrincipal = Depends(current)
    ) -> dict[str, Any]:
        if not store.rate_limit("dag:" + principal.user_id, limit=25, window=300):
            raise HTTPException(429, "dag rate limit exceeded")
        from milyonus.imece.dag import DAGCompileError, DAGStore, compile_dag, execute_dag

        try:
            compiled = compile_dag(body.name, body.nodes)
        except DAGCompileError as exc:
            raise HTTPException(422, str(exc)) from exc
        ds = DAGStore(tenant_home(root, principal.tenant_id) / "state.db")
        try:
            return await execute_dag(compiled, store=ds)
        finally:
            ds.close()

    @app.get("/v1/dag/runs")
    def dag_runs(principal: SessionPrincipal = Depends(current)) -> dict[str, Any]:
        from milyonus.imece.dag import DAGStore

        ds = DAGStore(tenant_home(root, principal.tenant_id) / "state.db")
        try:
            return {"runs": ds.list_runs()}
        finally:
            ds.close()

    # --- S7: Differential Privacy Telemetry Vault -----------------------

    @app.get("/v1/privacy/budget")
    def privacy_budget(
        scope: str = "telemetry", principal: SessionPrincipal = Depends(current)
    ) -> dict[str, Any]:
        from milyonus.observability.privacy import PrivacyAccountant

        acc = PrivacyAccountant(tenant_home(root, principal.tenant_id) / "state.db")
        try:
            return acc.budget_status(scope)
        finally:
            acc.close()

    @app.post("/v1/privacy/release")
    def privacy_release(
        body: PrivacyReleaseIn, principal: SessionPrincipal = Depends(current)
    ) -> dict[str, Any]:
        from milyonus.observability.privacy import PrivacyAccountant, PrivacyBudgetExhausted

        acc = PrivacyAccountant(tenant_home(root, principal.tenant_id) / "state.db")
        try:
            return acc.release_metric(
                body.values,
                metric=body.metric,
                epsilon=body.epsilon,
                lower=body.lower,
                upper=body.upper,
                bins=body.bins,
                scope=body.scope,
            ).to_dict()
        except PrivacyBudgetExhausted as exc:
            raise HTTPException(429, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        finally:
            acc.close()

    # --- S8: Enterprise 6-Pillar Compliance Certifier -------------------

    @app.post("/v1/certify/run")
    async def certify_run(principal: SessionPrincipal = Depends(current)) -> dict[str, Any]:
        if not store.rate_limit("certify:" + principal.user_id, limit=10, window=300):
            raise HTTPException(429, "certification rate limit exceeded")
        home = tenant_home(root, principal.tenant_id)
        from milyonus.evaluation.certifier import run_compliance_certification

        return await run_compliance_certification(
            db_path=home / "state.db",
            skills_root=home / "skills",
            include_web_chaos=False,
        )

    @app.get("/v1/certify/history")
    def certify_history(principal: SessionPrincipal = Depends(current)) -> dict[str, Any]:
        from milyonus.evaluation.certifier import CertStore

        cs = CertStore(tenant_home(root, principal.tenant_id) / "state.db")
        try:
            return {"certificates": cs.history()}
        finally:
            cs.close()

    # --- S9: Adversarial Mutation Security Fuzzer -----------------------

    @app.post("/v1/security/fuzz")
    async def security_fuzz(
        body: FuzzIn, principal: SessionPrincipal = Depends(current)
    ) -> dict[str, Any]:
        if not store.rate_limit("fuzz:" + principal.user_id, limit=15, window=300):
            raise HTTPException(429, "fuzzer rate limit exceeded")
        from milyonus.security.fuzzer import run_security_fuzz

        return (await run_security_fuzz(iterations=body.iterations, seed=body.seed)).to_dict()

    # --- S10: Multi-Agent Collective Economy Simulator ------------------

    @app.post("/v1/economy/simulate")
    def economy_simulate(
        body: EconomySimIn, principal: SessionPrincipal = Depends(current)
    ) -> dict[str, Any]:
        del principal
        from milyonus.observability.economy import simulate_collective_economy

        return simulate_collective_economy(
            agents=body.agents,
            rounds=body.rounds,
            max_parallel=body.max_parallel,
            worker_model=body.worker_model,
            gate_model=body.gate_model,
            single_agent_pass_prob=body.single_agent_pass_prob,
        )

    @app.get("/v1/economy/scales")
    def economy_scales(
        max_parallel: int = 16, principal: SessionPrincipal = Depends(current)
    ) -> dict[str, Any]:
        del principal
        from milyonus.observability.economy import compare_scales

        return {"scales": compare_scales(max_parallel=max(1, min(max_parallel, 256)))}
