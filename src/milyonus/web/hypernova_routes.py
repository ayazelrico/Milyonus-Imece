"""FastAPI Web Surface #7 routes for all 10 Hypernova Capabilities (PLAN-HYPERNOVA H1–H10).

Mounted into `create_app()` in `milyonus.web.app`. Every route is strictly:
  - Authenticated via `current` (cookie + CSRF OR Bearer API key),
  - Scoped to `tenant_home(root, principal.tenant_id)` (zero cross-tenant visibility),
  - Rate-limited on compute/mutation operations.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field

from milyonus.web.auth import SessionPrincipal
from milyonus.web.runner import RunnerHub, tenant_home
from milyonus.web.store import WebStore

# --- Request models -----------------------------------------------------


class BranchCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    description: str = Field(default="", max_length=240)


class BranchStageIn(BaseModel):
    op: str = Field(default="add")  # "add" | "revoke"
    content: str = Field(default="", max_length=4000)
    item_id: str | None = None
    trust_tier: str = Field(default="T1")
    source_uri: str | None = None


class BranchMergeIn(BaseModel):
    force: bool = False


class LeaseMintIn(BaseModel):
    subject: str = Field(default="agent", min_length=1, max_length=80)
    tools: list[str] = Field(default_factory=lambda: ["read_file", "list_dir"])
    path_globs: list[str] = Field(default_factory=list)
    domains: list[str] = Field(default_factory=list)
    ttl_seconds: float = Field(default=900.0, ge=5.0, le=86400.0)
    max_calls: int = Field(default=25, ge=1, le=500)
    max_tokens: int = Field(default=32_000, ge=100, le=500_000)
    allow_irreversible: bool = False


class LeaseVerifyIn(BaseModel):
    tool_name: str = Field(min_length=1, max_length=80)
    path: str | None = None
    domain: str | None = None
    irreversible: bool = False
    consume: bool = False
    signature_override: str | None = None


class CanaryMintIn(BaseModel):
    label: str = Field(default="web-boundary", min_length=1, max_length=80)


class CanaryScanIn(BaseModel):
    text: str = Field(min_length=1, max_length=20_000)
    context: str = Field(default="web-scan", max_length=80)


class ConstitutionEvaluateIn(BaseModel):
    preset: str = Field(default="fortress-security")
    text: str = Field(min_length=1, max_length=20_000)


class ConstitutionSimulateIn(BaseModel):
    options: list[dict[str, Any]] = Field(min_length=1, max_length=12)
    names: list[str] | None = None


class EvolutionRunIn(BaseModel):
    task: str = Field(min_length=3, max_length=4000)
    generations: int = Field(default=6, ge=1, le=25)
    population_size: int = Field(default=12, ge=4, le=40)
    seed: int = Field(default=42)


class DisclosureCreateIn(BaseModel):
    bundle: dict[str, Any]
    reveal_kinds: list[str] | None = None
    reveal_indices: list[int] | None = None


class DisclosureVerifyIn(BaseModel):
    disclosure: dict[str, Any]
    require_signature: bool = False


class SkillHealIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    reseal: bool = True


class FlightAnalyzeIn(BaseModel):
    recording: dict[str, Any]


class FlightDiffIn(BaseModel):
    flight_a: dict[str, Any]
    flight_b: dict[str, Any]


class ParetoRouteIn(BaseModel):
    prompt: str = Field(min_length=1, max_length=20_000)
    budget_pressure: float = Field(default=0.0, ge=0.0, le=1.0)
    max_cost_per_1m: float | None = Field(default=None, ge=0.0)
    max_latency_ms: int | None = Field(default=None, ge=50)
    require_local: bool = False


class ParetoOutcomeIn(BaseModel):
    model_id: str = Field(min_length=1, max_length=120)
    success: bool = True
    latency_ms: int = Field(default=500, ge=1, le=120_000)
    cost_usd: float = Field(default=0.001, ge=0.0)


class MeshPeerIn(BaseModel):
    node_id: str | None = Field(default=None, max_length=64)
    label: str = Field(min_length=1, max_length=80)
    role: str = Field(default="worker", max_length=32)
    endpoint: str = Field(default="local://in-process", max_length=160)


class MeshDispatchIn(BaseModel):
    task: str = Field(min_length=2, max_length=8000)
    byzantine_nodes: list[str] = Field(default_factory=list)
    require_proof: bool = True


# --- Route mounting -----------------------------------------------------


def mount_hypernova_routes(
    app: FastAPI,
    *,
    root: Path,
    store: WebStore,
    hub: RunnerHub,
    current: Callable[..., SessionPrincipal],
) -> None:
    """Attach all H1–H10 Hypernova REST routes to the FastAPI application."""

    # --- H1: Sovereign Epistemic Knowledge Graph & Contradictions -------

    @app.get("/v1/memory/graph")
    def memory_graph(
        include_inactive: bool = False,
        principal: SessionPrincipal = Depends(current),
    ) -> dict[str, Any]:
        from milyonus.memory.graph import build_epistemic_graph
        from milyonus.memory.store import MemoryStore

        ms = MemoryStore(tenant_home(root, principal.tenant_id) / "state.db")
        try:
            g = build_epistemic_graph(ms, include_inactive=include_inactive)
            return {**g.to_dict(), "mermaid": g.to_mermaid(), "dot": g.to_dot()}
        finally:
            ms.close()

    @app.get("/v1/memory/conflicts")
    def memory_conflicts(principal: SessionPrincipal = Depends(current)) -> dict[str, Any]:
        from milyonus.memory.graph import build_epistemic_graph
        from milyonus.memory.store import MemoryStore

        ms = MemoryStore(tenant_home(root, principal.tenant_id) / "state.db")
        try:
            g = build_epistemic_graph(ms)
            return {
                "conflicts": [c.to_dict() for c in g.conflicts],
                "count": len(g.conflicts),
            }
        finally:
            ms.close()

    @app.get("/v1/memory/blast-radius")
    def memory_blast_radius(
        origin: str,
        principal: SessionPrincipal = Depends(current),
    ) -> dict[str, Any]:
        from milyonus.memory.graph import blast_radius
        from milyonus.memory.store import MemoryStore

        ms = MemoryStore(tenant_home(root, principal.tenant_id) / "state.db")
        try:
            return blast_radius(ms, origin).to_dict()
        finally:
            ms.close()

    # --- H2: Cryptographic Memory Branching -----------------------------

    @app.get("/v1/memory/branches")
    def list_branches(principal: SessionPrincipal = Depends(current)) -> dict[str, Any]:
        from milyonus.memory.branch import MemoryBranchManager

        mgr = MemoryBranchManager(tenant_home(root, principal.tenant_id) / "state.db")
        try:
            return {"branches": [b.to_dict() for b in mgr.list_branches()]}
        finally:
            mgr.close()

    @app.post("/v1/memory/branches")
    def create_branch(
        body: BranchCreateIn, principal: SessionPrincipal = Depends(current)
    ) -> dict[str, Any]:
        from milyonus.memory.branch import BranchError, MemoryBranchManager
        from milyonus.memory.store import MemoryStore

        db = tenant_home(root, principal.tenant_id) / "state.db"
        ms = MemoryStore(db)
        mgr = MemoryBranchManager(db)
        try:
            return mgr.create_branch(body.name, ms, description=body.description).to_dict()
        except BranchError as exc:
            raise HTTPException(409, str(exc)) from exc
        finally:
            ms.close()
            mgr.close()

    @app.post("/v1/memory/branches/{name:path}/items")
    def stage_branch_item(
        name: str, body: BranchStageIn, principal: SessionPrincipal = Depends(current)
    ) -> dict[str, Any]:
        from typing import Literal

        from milyonus.memory.branch import BranchError, MemoryBranchManager

        db = tenant_home(root, principal.tenant_id) / "state.db"
        mgr = MemoryBranchManager(db)
        try:
            if body.op == "revoke":
                if not body.item_id:
                    raise HTTPException(422, "item_id is required for op='revoke'")
                return mgr.stage_revoke(name, body.item_id)
            tier: Literal["T0", "T1", "T2", "T3", "T4"] = (
                body.trust_tier if body.trust_tier in ("T1", "T2", "T3", "T4") else "T1"  # type: ignore[assignment]
            )
            return mgr.stage_add(name, body.content, trust_tier=tier, source_uri=body.source_uri)
        except BranchError as exc:
            raise HTTPException(404, str(exc)) from exc
        finally:
            mgr.close()

    @app.get("/v1/memory/branches/{name:path}/diff")
    def diff_branch(name: str, principal: SessionPrincipal = Depends(current)) -> dict[str, Any]:
        from milyonus.memory.branch import BranchError, MemoryBranchManager
        from milyonus.memory.store import MemoryStore

        db = tenant_home(root, principal.tenant_id) / "state.db"
        ms = MemoryStore(db)
        mgr = MemoryBranchManager(db)
        try:
            return mgr.diff_branch(name, ms).to_dict()
        except BranchError as exc:
            raise HTTPException(404, str(exc)) from exc
        finally:
            ms.close()
            mgr.close()

    @app.post("/v1/memory/branches/{name:path}/merge")
    async def merge_branch(
        name: str, body: BranchMergeIn, principal: SessionPrincipal = Depends(current)
    ) -> dict[str, Any]:
        from milyonus.memory.branch import BranchError, MemoryBranchManager
        from milyonus.memory.store import MemoryStore

        db = tenant_home(root, principal.tenant_id) / "state.db"

        def _check_exists() -> None:
            mgr_check = MemoryBranchManager(db)
            try:
                mgr_check.get_branch(name)
            finally:
                mgr_check.close()

        try:
            _check_exists()
        except BranchError as exc:
            raise HTTPException(404, str(exc)) from exc

        ms = MemoryStore(db)
        mgr = MemoryBranchManager(db)
        try:
            res = await mgr.merge_branch(name, ms, force=body.force)
            return res.to_dict()
        finally:
            ms.close()
            mgr.close()

    @app.delete("/v1/memory/branches/{name:path}")
    def delete_branch(name: str, principal: SessionPrincipal = Depends(current)) -> dict[str, Any]:
        from milyonus.memory.branch import MemoryBranchManager

        mgr = MemoryBranchManager(tenant_home(root, principal.tenant_id) / "state.db")
        try:
            if not mgr.delete_branch(name):
                raise HTTPException(404, "branch not found")
            return {"deleted": True, "name": name}
        finally:
            mgr.close()

    # --- H3: Zero-Trust Capability Leases & Canary Kill-Switch ----------

    @app.get("/v1/leases")
    def list_leases(
        active_only: bool = False, principal: SessionPrincipal = Depends(current)
    ) -> dict[str, Any]:
        from milyonus.security.leases import LeaseVault

        vault = LeaseVault(tenant_home(root, principal.tenant_id) / "state.db")
        try:
            return {
                "leases": [lr.to_dict() for lr in vault.list_leases(active_only=active_only)],
                "canaries": vault.list_canaries(),
            }
        finally:
            vault.close()

    @app.post("/v1/leases")
    def mint_lease(
        body: LeaseMintIn, principal: SessionPrincipal = Depends(current)
    ) -> dict[str, Any]:
        from milyonus.security.leases import LeaseVault

        vault = LeaseVault(tenant_home(root, principal.tenant_id) / "state.db")
        try:
            return vault.mint(
                subject=body.subject,
                tools=body.tools,
                path_globs=body.path_globs,
                domains=body.domains,
                ttl_seconds=body.ttl_seconds,
                max_calls=body.max_calls,
                max_tokens=body.max_tokens,
                allow_irreversible=body.allow_irreversible,
            ).to_dict()
        finally:
            vault.close()

    @app.post("/v1/leases/{lease_id}/verify")
    def verify_lease(
        lease_id: str, body: LeaseVerifyIn, principal: SessionPrincipal = Depends(current)
    ) -> dict[str, Any]:
        from milyonus.security.leases import LeaseVault

        vault = LeaseVault(tenant_home(root, principal.tenant_id) / "state.db")
        try:
            return vault.verify_and_consume(
                lease_id,
                tool_name=body.tool_name,
                path=body.path,
                domain=body.domain,
                irreversible=body.irreversible,
                consume=body.consume,
                signature_override=body.signature_override,
            ).to_dict()
        finally:
            vault.close()

    @app.delete("/v1/leases/{lease_id}")
    def revoke_lease(
        lease_id: str, principal: SessionPrincipal = Depends(current)
    ) -> dict[str, Any]:
        from milyonus.security.leases import LeaseVault

        vault = LeaseVault(tenant_home(root, principal.tenant_id) / "state.db")
        try:
            if not vault.revoke(lease_id):
                raise HTTPException(404, "lease not found or already revoked")
            return {"revoked": True, "lease_id": lease_id}
        finally:
            vault.close()

    @app.post("/v1/leases/canary")
    def mint_canary(
        body: CanaryMintIn, principal: SessionPrincipal = Depends(current)
    ) -> dict[str, Any]:
        from milyonus.security.leases import LeaseVault

        vault = LeaseVault(tenant_home(root, principal.tenant_id) / "state.db")
        try:
            return vault.mint_canary(label=body.label)
        finally:
            vault.close()

    @app.post("/v1/leases/canary/scan")
    def scan_canary(
        body: CanaryScanIn, principal: SessionPrincipal = Depends(current)
    ) -> dict[str, Any]:
        from milyonus.security.leases import LeaseVault

        vault = LeaseVault(tenant_home(root, principal.tenant_id) / "state.db")
        try:
            return vault.scan_for_canary_leak(body.text, context=body.context).to_dict()
        finally:
            vault.close()

    # --- H4: IRADE Constitutional Policy Engine & Veto Simulator --------

    @app.get("/v1/constitution/presets")
    def constitution_presets(principal: SessionPrincipal = Depends(current)) -> dict[str, Any]:
        del principal
        from milyonus.imece.constitution import builtin_constitutions

        return {"presets": [c.to_dict() for c in builtin_constitutions().values()]}

    @app.post("/v1/constitution/evaluate")
    def constitution_evaluate(
        body: ConstitutionEvaluateIn, principal: SessionPrincipal = Depends(current)
    ) -> dict[str, Any]:
        del principal
        from milyonus.imece.constitution import builtin_constitutions, evaluate_text

        const = builtin_constitutions().get(body.preset)
        if const is None:
            raise HTTPException(404, f"unknown preset: {body.preset}")
        violations = evaluate_text(const, body.text)
        return {
            "preset": const.name,
            "constitution_hash": const.constitution_hash,
            "compliant": len(violations) == 0,
            "violations": [v.to_dict() for v in violations],
        }

    @app.post("/v1/constitution/simulate")
    def constitution_simulate(
        body: ConstitutionSimulateIn, principal: SessionPrincipal = Depends(current)
    ) -> dict[str, Any]:
        del principal
        from milyonus.imece.constitution import simulate_constitutions

        return simulate_constitutions(body.options, names=body.names)

    # --- H5: Swarm DNA & Evolutionary Strategy Genome -------------------

    @app.post("/v1/evolution/run")
    def evolution_run(
        body: EvolutionRunIn, principal: SessionPrincipal = Depends(current)
    ) -> dict[str, Any]:
        if not store.rate_limit("evo:" + principal.user_id, limit=25, window=300):
            raise HTTPException(429, "evolution rate limit exceeded")
        from milyonus.imece.evolution import EvolutionStore, evolve_swarm

        es = EvolutionStore(tenant_home(root, principal.tenant_id) / "state.db")
        try:
            return evolve_swarm(
                body.task,
                generations=body.generations,
                population_size=body.population_size,
                seed=body.seed,
                store=es,
            ).to_dict()
        finally:
            es.close()

    @app.get("/v1/evolution/runs")
    def evolution_runs(principal: SessionPrincipal = Depends(current)) -> dict[str, Any]:
        from milyonus.imece.evolution import EvolutionStore

        es = EvolutionStore(tenant_home(root, principal.tenant_id) / "state.db")
        try:
            return {"runs": es.list_runs()}
        finally:
            es.close()

    @app.get("/v1/evolution/runs/{run_id}")
    def evolution_run_detail(
        run_id: str, principal: SessionPrincipal = Depends(current)
    ) -> dict[str, Any]:
        from milyonus.imece.evolution import EvolutionStore

        es = EvolutionStore(tenant_home(root, principal.tenant_id) / "state.db")
        try:
            run = es.get_run(run_id)
            if run is None:
                raise HTTPException(404, "evolution run not found")
            return run
        finally:
            es.close()

    # --- H6: Cryptographic Selective Disclosure Merkle Proofs -----------

    @app.post("/v1/proofs/disclose")
    def proofs_disclose(
        body: DisclosureCreateIn, principal: SessionPrincipal = Depends(current)
    ) -> dict[str, Any]:
        del principal
        from milyonus.security.disclosure import create_disclosure_proof

        try:
            return create_disclosure_proof(
                body.bundle,
                reveal_kinds=body.reveal_kinds,
                reveal_indices=body.reveal_indices,
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.post("/v1/proofs/verify-disclosure")
    def proofs_verify_disclosure(
        body: DisclosureVerifyIn, principal: SessionPrincipal = Depends(current)
    ) -> dict[str, Any]:
        del principal
        from milyonus.security.disclosure import verify_disclosure_proof

        return verify_disclosure_proof(
            body.disclosure, require_signature=body.require_signature
        ).to_dict()

    # --- H7: Autonomous Self-Healing Skill Immune System ----------------

    @app.get("/v1/skills/immune/scan")
    def skills_immune_scan(principal: SessionPrincipal = Depends(current)) -> dict[str, Any]:
        from milyonus.skills.immune import scan_skills_health

        sdir = tenant_home(root, principal.tenant_id) / "skills"
        sdir.mkdir(mode=0o700, parents=True, exist_ok=True)
        return scan_skills_health(sdir).to_dict()

    @app.post("/v1/skills/immune/seal")
    def skills_immune_seal(principal: SessionPrincipal = Depends(current)) -> dict[str, Any]:
        from milyonus.skills.immune import seal_manifest

        sdir = tenant_home(root, principal.tenant_id) / "skills"
        sdir.mkdir(mode=0o700, parents=True, exist_ok=True)
        return seal_manifest(sdir)

    @app.post("/v1/skills/immune/heal")
    def skills_immune_heal(
        body: SkillHealIn, principal: SessionPrincipal = Depends(current)
    ) -> dict[str, Any]:
        from milyonus.skills.immune import heal_skill

        sdir = tenant_home(root, principal.tenant_id) / "skills"
        res = heal_skill(body.name, root=sdir, reseal=body.reseal)
        if not res.ok:
            raise HTTPException(422, res.message)
        return res.to_dict()

    # --- H8: Flight Recorder: Black-Box Session DVR ---------------------

    @app.get("/v1/sessions/{session_id}/flight")
    def session_flight(
        session_id: str, principal: SessionPrincipal = Depends(current)
    ) -> dict[str, Any]:
        if store.get_session(principal.user_id, session_id) is None:
            raise HTTPException(404, "session not found")
        home = tenant_home(root, principal.tenant_id)
        from milyonus.core.flight_recorder import record_from_session
        from milyonus.core.store import SessionStore
        from milyonus.memory.store import MemoryStore

        ss = SessionStore(home / "state.db")
        ms = MemoryStore(home / "state.db")
        try:
            row = ss.find_session(
                channel="web", user_ref=principal.user_id, title=f"web:{session_id}"
            )
            messages = [dict(m) for m in ss.history(row.id)] if row is not None else []
            tools = store.tool_results_for_session(session_id)
            return record_from_session(session_id, messages, tool_results=tools, memory_store=ms)
        finally:
            ss.close()
            ms.close()

    @app.post("/v1/flights/analyze")
    def flights_analyze(
        body: FlightAnalyzeIn, principal: SessionPrincipal = Depends(current)
    ) -> dict[str, Any]:
        del principal
        from milyonus.core.flight_recorder import detect_anomalies, verify_flight

        intact, errs = verify_flight(body.recording)
        anomalies = detect_anomalies(body.recording)
        return {
            "chain_intact": intact,
            "errors": errs,
            "anomalies": [a.to_dict() for a in anomalies],
            "anomaly_count": len(anomalies),
        }

    @app.post("/v1/flights/diff")
    def flights_diff(
        body: FlightDiffIn, principal: SessionPrincipal = Depends(current)
    ) -> dict[str, Any]:
        del principal
        from milyonus.core.flight_recorder import diff_flights

        return diff_flights(body.flight_a, body.flight_b)

    # --- H9: Multi-Model Cost-Latency-Trust Pareto Frontier Router ------

    @app.get("/v1/router/frontier")
    def router_frontier(
        max_cost_per_1m: float | None = None,
        max_latency_ms: int | None = None,
        require_local: bool = False,
        principal: SessionPrincipal = Depends(current),
    ) -> dict[str, Any]:
        from milyonus.providers.pareto import ParetoRouter

        pr = ParetoRouter(tenant_home(root, principal.tenant_id) / "state.db")
        try:
            frontier = pr.compute_pareto_frontier(
                max_cost_per_1m=max_cost_per_1m,
                max_latency_ms=max_latency_ms,
                require_local=require_local,
            )
            return {"catalog": pr.enriched_catalog(), "frontier": frontier}
        finally:
            pr.close()

    @app.post("/v1/router/route")
    def router_route(
        body: ParetoRouteIn, principal: SessionPrincipal = Depends(current)
    ) -> dict[str, Any]:
        from milyonus.providers.pareto import ParetoRouter

        pr = ParetoRouter(tenant_home(root, principal.tenant_id) / "state.db")
        try:
            return pr.route_task(
                body.prompt,
                budget_pressure=body.budget_pressure,
                max_cost_per_1m=body.max_cost_per_1m,
                max_latency_ms=body.max_latency_ms,
                require_local=body.require_local,
            )
        finally:
            pr.close()

    @app.post("/v1/router/outcome")
    def router_outcome(
        body: ParetoOutcomeIn, principal: SessionPrincipal = Depends(current)
    ) -> dict[str, Any]:
        from milyonus.providers.pareto import ParetoRouter

        pr = ParetoRouter(tenant_home(root, principal.tenant_id) / "state.db")
        try:
            return pr.record_outcome(
                body.model_id,
                success=body.success,
                latency_ms=body.latency_ms,
                cost_usd=body.cost_usd,
            )
        finally:
            pr.close()

    # --- H10: Federated İmece Mesh Protocol -----------------------------

    @app.get("/v1/mesh/peers")
    def mesh_peers(principal: SessionPrincipal = Depends(current)) -> dict[str, Any]:
        from milyonus.imece.mesh import MeshCoordinator, MeshStore

        ms_mesh = MeshStore(tenant_home(root, principal.tenant_id) / "state.db")
        try:
            coord = MeshCoordinator(ms_mesh)
            peers = ms_mesh.list_peers()
            if not peers:
                peers = coord.ensure_default_cluster()
            return {
                "peers": [p.to_dict() for p in peers],
                "recent_dispatches": ms_mesh.recent_dispatches(limit=10),
            }
        finally:
            ms_mesh.close()

    @app.post("/v1/mesh/peers")
    def mesh_register_peer(
        body: MeshPeerIn, principal: SessionPrincipal = Depends(current)
    ) -> dict[str, Any]:
        from milyonus.imece.mesh import MeshStore

        ms_mesh = MeshStore(tenant_home(root, principal.tenant_id) / "state.db")
        try:
            peer, _secret = ms_mesh.register_peer(
                node_id=body.node_id,
                label=body.label,
                role=body.role,
                endpoint=body.endpoint,
            )
            return peer.to_dict()
        finally:
            ms_mesh.close()

    @app.delete("/v1/mesh/peers/{node_id}")
    def mesh_delete_peer(
        node_id: str, principal: SessionPrincipal = Depends(current)
    ) -> dict[str, Any]:
        from milyonus.imece.mesh import MeshStore

        ms_mesh = MeshStore(tenant_home(root, principal.tenant_id) / "state.db")
        try:
            if not ms_mesh.remove_peer(node_id):
                raise HTTPException(404, "mesh peer not found")
            return {"deleted": True, "node_id": node_id}
        finally:
            ms_mesh.close()

    @app.post("/v1/mesh/dispatch")
    async def mesh_dispatch(
        body: MeshDispatchIn, principal: SessionPrincipal = Depends(current)
    ) -> dict[str, Any]:
        if not store.rate_limit("mesh:" + principal.user_id, limit=25, window=300):
            raise HTTPException(429, "mesh dispatch rate limit exceeded")
        from milyonus.imece.mesh import MeshCoordinator, MeshStore

        ms_mesh = MeshStore(tenant_home(root, principal.tenant_id) / "state.db")
        try:
            coord = MeshCoordinator(ms_mesh)
            rep = await coord.dispatch(
                body.task,
                byzantine_nodes=set(body.byzantine_nodes),
                require_proof=body.require_proof,
            )
            return rep.to_dict()
        finally:
            ms_mesh.close()

    # Keep hub reference used cleanly for future async serialization hooks.
    del hub
