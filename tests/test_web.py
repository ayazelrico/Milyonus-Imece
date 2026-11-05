"""Web surface: auth, tenancy isolation, sessions, approvals."""

from __future__ import annotations

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from milyonus.memory.model import Provenance
from milyonus.memory.store import MemoryStore
from milyonus.web.app import create_app
from milyonus.web.auth import SETTINGS_ALLOWLIST
from milyonus.web.runner import tenant_home


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MILYONUS_WEB_DEV_AUTH", "1")
    monkeypatch.setenv("MILYONUS_WEB_SECRET", "test-secret-key-32bytes-minimum!!")
    app = create_app(data_root=tmp_path / "webdata")
    with TestClient(app) as c:
        yield c, tmp_path / "webdata"


def _login(client: TestClient, email: str = "a@example.com") -> None:
    r = client.post("/v1/auth/magic-link", json={"email": email})
    assert r.status_code == 202
    token = r.json()["token"]
    r = client.post("/v1/auth/verify", json={"token": token})
    assert r.status_code == 200
    csrf = client.cookies.get("milyonus_csrf")
    client.headers["x-csrf-token"] = csrf


def test_upload_limits_and_tenant_scope(client):
    c, _ = client
    _login(c)
    uploaded = c.post("/v1/attachments", content=b"project notes")
    assert uploaded.status_code == 200
    aid = uploaded.json()["id"]
    assert c.post("/v1/attachments", content=b"\xff").status_code == 415
    assert c.post("/v1/attachments", content=b"x" * 1_000_001).status_code == 413
    _login(c, "other@example.com")
    sid = c.post("/v1/sessions", json={}).json()["id"]
    assert c.post(f"/v1/sessions/{sid}/messages", json={"text": "read", "attachments": [aid]}).status_code == 404


def test_rate_limit_concurrent_load(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    from milyonus.web.store import WebStore

    store = WebStore(tmp_path / "load.db")
    try:
        with ThreadPoolExecutor(max_workers=16) as pool:
            results = list(pool.map(lambda _: store.rate_limit("tenant-a", limit=30, window=60), range(200)))
        assert sum(results) == 30
        assert store.rate_limit("tenant-b", limit=30, window=60)
    finally:
        store.close()


def test_auth_session_and_settings_allowlist(client):
    c, _root = client
    _login(c)
    r = c.post("/v1/sessions", json={"title": "hello"})
    assert r.status_code == 200
    sid = r.json()["id"]
    r = c.get("/v1/sessions")
    assert any(s["id"] == sid for s in r.json())
    # Security keys must be rejected silently (not applied).
    r = c.put(
        "/v1/settings",
        json={"values": {"locale": "tr", "security.sandbox_backend": "local"}},
    )
    assert r.status_code == 200
    body = r.json()
    assert body.get("locale") == "tr"
    assert "security.sandbox_backend" not in body
    assert "locale" in SETTINGS_ALLOWLIST


def test_tenant_memory_isolation(client, monkeypatch):
    c, root = client
    _login(c, "alice@example.com")
    # Plant memory in Alice's tenant home.
    alice_id = c.get("/v1/export").json()["user_id"]
    home_a = tenant_home(root, alice_id)
    monkeypatch.setenv("MILYONUS_HOME", str(home_a))
    ms = MemoryStore()
    mid = ms.insert_candidate(
        "alice secret fact",
        trust_tier="T1",
        provenance=Provenance(source_kind="user-direct", actor="alice"),
    )
    ms.mark_active(mid, verdict="test", confirmations=1)
    ms.close()

    # Login as Bob on a fresh client jar.
    c2 = TestClient(c.app)
    c2.headers.clear()
    r = c2.post("/v1/auth/magic-link", json={"email": "bob@example.com"})
    token = r.json()["token"]
    r = c2.post("/v1/auth/verify", json={"token": token})
    assert r.status_code == 200
    c2.headers["x-csrf-token"] = c2.cookies.get("milyonus_csrf")
    mem = c2.get("/v1/memory")
    assert mem.status_code == 200
    contents = [i["content"] for i in mem.json()["items"]]
    assert "alice secret fact" not in contents


def test_approval_single_use_and_irreversible_session_denied(client):
    c, _root = client
    _login(c)
    store = c.app.state.store
    sid = c.post("/v1/sessions", json={}).json()["id"]
    turn = store.create_turn(sid)
    aid = store.create_approval(
        turn_id=turn,
        call_id="c1",
        tool="run_shell",
        args={"command": "rm -rf /"},
        risk="danger",
        reason="irreversible",
        irreversible=True,
    )
    c.headers["x-csrf-token"] = c.cookies.get("milyonus_csrf")
    r = c.post(f"/v1/approvals/{aid}", json={"decision": "allow_session"})
    assert r.status_code == 409
    r = c.post(f"/v1/approvals/{aid}", json={"decision": "deny"})
    assert r.status_code == 200
    r = c.post(f"/v1/approvals/{aid}", json={"decision": "deny"})
    assert r.status_code == 409


def test_healthz(client):
    c, _ = client
    assert c.get("/healthz").json()["ok"] is True


def test_other_user_cannot_decide_approval(client):
    c, _ = client
    _login(c, "alice@example.com")
    store = c.app.state.store
    sid = c.post("/v1/sessions", json={}).json()["id"]
    aid = store.create_approval(
        turn_id=store.create_turn(sid),
        call_id="private",
        tool="write_file",
        args={},
        risk="caution",
        reason="private action",
        irreversible=False,
    )
    _login(c, "bob@example.com")
    assert c.post(f"/v1/approvals/{aid}", json={"decision": "allow"}).status_code == 404
    assert store.get_approval(aid)["state"] == "pending"


def test_reaffirm_and_preview_are_real_and_tenant_scoped(client):
    c, root = client
    _login(c)
    uid = c.get("/v1/export").json()["user_id"]
    ms = MemoryStore(tenant_home(root, uid) / "state.db")
    source = "https://example.com/source"
    parent = ms.insert_candidate(
        "parent",
        trust_tier="T1",
        provenance=Provenance(source_kind="user-direct", source_uri=source),
    )
    ms.mark_active(parent, verdict="test", confirmations=1)
    child = ms.insert_candidate(
        "derived",
        trust_tier="T2",
        provenance=Provenance(source_kind="agent-observed"),
        derived_from=parent,
    )
    assert c.post("/v1/memory/missing/reaffirm").status_code == 404
    assert c.post(f"/v1/memory/{child}/reaffirm").status_code == 409
    assert c.post(f"/v1/memory/{parent}/reaffirm").status_code == 200
    assert ms.get(parent).reaffirm_count == 1
    assert c.post(f"/v1/memory/{parent}/reaffirm").status_code == 429
    preview = c.post("/v1/memory/revoke-preview", json={"source_uri": source})
    assert set(preview.json()["affected"]) == {parent, child}
    assert ms.get(parent).state == "active"
    assert ms.get(child).state == "pending"
    assert ms.verify_ledger()
    revoked = c.post("/v1/memory/revoke", json={"source_uri": source})
    assert set(revoked.json()["revoked"]) == {parent, child}
    assert ms.verify_ledger()
    ms.close()


def test_memory_requests_do_not_change_process_home(client, monkeypatch, tmp_path):
    import os

    c, _ = client
    _login(c)
    monkeypatch.setenv("MILYONUS_HOME", str(tmp_path / "unrelated"))
    for path in ("/v1/memory", "/v1/audit/verify", "/v1/search?q=hello"):
        assert c.get(path).status_code == 200
        assert os.environ["MILYONUS_HOME"] == str(tmp_path / "unrelated")


def test_cancel_checks_turn_session(client):
    from milyonus.web.runner import TurnHandle

    c, _ = client
    _login(c)
    sid = c.post("/v1/sessions", json={}).json()["id"]
    c.app.state.hub._turns["foreign"] = TurnHandle("foreign", "other-session")
    assert c.post(f"/v1/sessions/{sid}/cancel", json={"turn_id": "foreign"}).status_code == 404


def test_sse_resume_does_not_repeat_last_event(client):
    c, _ = client
    _login(c)
    sid = c.post("/v1/sessions", json={}).json()["id"]
    store = c.app.state.store
    turn = store.create_turn(sid)
    store.append_event(turn, 1, "text.delta", {"text": "already delivered"})
    store.append_event(turn, 2, "turn.completed", {"turn_id": turn})
    response = c.get(f"/v1/sessions/{sid}/stream", headers={"Last-Event-ID": "1"})
    assert response.status_code == 200
    assert "already delivered" not in response.text
    assert "event: turn.completed" in response.text


def test_sse_pins_requested_turn_and_rejects_foreign_turn(client):
    c, _ = client
    _login(c)
    sid = c.post("/v1/sessions", json={}).json()["id"]
    other = c.post("/v1/sessions", json={}).json()["id"]
    store = c.app.state.store
    first = store.create_turn(sid)
    store.append_event(first, 1, "text.delta", {"text": "first response"})
    store.append_event(first, 2, "turn.completed", {})
    second = store.create_turn(sid)
    store.append_event(second, 1, "text.delta", {"text": "second response"})
    store.append_event(second, 2, "turn.completed", {})
    response = c.get(f"/v1/sessions/{sid}/stream?turn_id={first}")
    assert response.status_code == 200
    assert "first response" in response.text
    assert "second response" not in response.text
    assert c.get(f"/v1/sessions/{other}/stream?turn_id={first}").status_code == 404
    assert c.get(f"/v1/sessions/{sid}/stream?turn_id=missing").status_code == 404
    assert c.get(f"/v1/sessions/{other}/stream").status_code == 404
    _login(c, "foreign@example.com")
    assert c.get(f"/v1/sessions/{sid}/stream?turn_id={first}").status_code == 404


def test_search_returns_web_ids_and_hides_deleted_sessions(client):
    from milyonus.core.store import SessionStore

    c, root = client
    _login(c)
    uid = c.get("/v1/export").json()["user_id"]
    sid = c.post("/v1/sessions", json={}).json()["id"]
    ss = SessionStore(tenant_home(root, uid) / "state.db")
    core_id = ss.create_session("web", user_ref=uid, title=f"web:{sid}")
    ss.append_message(core_id, turn=1, role="user", content="findme unique message")
    hits = c.get("/v1/search?q=findme").json()
    assert len(hits) == 1
    assert hits[0]["session_id"] == sid
    c.delete(f"/v1/sessions/{sid}")
    assert c.get("/v1/search?q=findme").json() == []
    ss.close()


def test_erased_account_cookie_cannot_be_reused(client):
    c, _ = client
    _login(c)
    token = c.cookies.get("milyonus_session")
    uid = c.get("/v1/export").json()["user_id"]
    c.app.state.store.erase_user(uid)
    response = c.get("/v1/export", headers={"Cookie": f"milyonus_session={token}"})
    assert response.status_code == 401
