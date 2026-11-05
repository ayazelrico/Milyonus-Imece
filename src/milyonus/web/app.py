"""FastAPI application for the Milyonus web surface."""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from milyonus.web.auth import (
    SETTINGS_ALLOWLIST,
    SessionPrincipal,
    clear_session_cookie,
    principal_from_cookie,
    require_csrf,
    set_session_cookie,
)
from milyonus.web.runner import RunnerHub, tenant_home
from milyonus.web.store import WebStore

COOKIE = "milyonus_session"


class MagicLinkIn(BaseModel):
    email: str = Field(min_length=3, max_length=320, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class VerifyIn(BaseModel):
    token: str


class SessionIn(BaseModel):
    title: str | None = None


class SessionPatch(BaseModel):
    title: str | None = None
    pinned: bool | None = None


class MessageIn(BaseModel):
    text: str = Field(min_length=1, max_length=100_000)
    attachments: list[str] = Field(default_factory=list)


class CancelIn(BaseModel):
    turn_id: str


class ApprovalIn(BaseModel):
    decision: str


class RevokeIn(BaseModel):
    source_uri: str


class SettingsIn(BaseModel):
    values: dict[str, str | bool | int | float]


def create_app(*, data_root: Path | None = None) -> FastAPI:
    root = data_root or Path(
        os.environ.get("MILYONUS_WEB_DATA", str(Path.home() / ".milyonus" / "web"))
    )
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if os.environ.get("MILYONUS_WEB_DEV_AUTH", "0") != "1":
        if len(os.environ.get("MILYONUS_WEB_SECRET", "")) < 32:
            raise RuntimeError("Production requires MILYONUS_WEB_SECRET with at least 32 characters")
        if os.environ.get("MILYONUS_WEB_SECURE") != "1":
            raise RuntimeError("Production requires MILYONUS_WEB_SECURE=1")
    store = WebStore(root / "web.db")
    # Shared hub uses a placeholder home; per-request runs switch MILYONUS_HOME.
    hub = RunnerHub(store, home=root)

    app = FastAPI(title="Milyonus Web", version="5.5.0")
    origins = [
        o.strip()
        for o in os.environ.get(
            "MILYONUS_WEB_CORS", "http://localhost:5173,http://127.0.0.1:5173"
        ).split(",")
        if o.strip()
    ]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.store = store
    app.state.hub = hub
    app.state.data_root = root

    def current(request: Request) -> SessionPrincipal:
        principal = principal_from_cookie(request.cookies.get(COOKIE))
        if principal is None:
            raise HTTPException(401, "not authenticated")
        user = store.get_user(principal.user_id)
        if (
            user is None
            or user.status != "active"
            or user.email != principal.email
            or principal.tenant_id != principal.user_id
        ):
            raise HTTPException(401, "session is no longer valid")
        if not require_csrf(request):
            raise HTTPException(403, "csrf")
        return principal

    @app.get("/healthz")
    def healthz() -> dict:
        return {"ok": True}

    @app.post("/v1/auth/magic-link", status_code=202)
    def magic_link(body: MagicLinkIn) -> dict:
        if not store.rate_limit("login:" + body.email.lower(), limit=5, window=3600):
            raise HTTPException(429, "too many login requests")
        token = store.create_magic_token(body.email)
        # Dev/local: return token so curl works without a mailer.
        # Production should mail it and omit the token field.
        expose = os.environ.get("MILYONUS_WEB_DEV_AUTH", "0") == "1"
        if not expose:
            from milyonus.web.mailer import send_login

            try:
                send_login(body.email, token)
            except (OSError, KeyError, ValueError):
                raise HTTPException(503, "email delivery unavailable") from None
        return {"accepted": True, "token": token if expose else None}

    @app.post("/v1/auth/verify")
    def verify(body: VerifyIn, response: Response) -> dict:
        email = store.consume_magic_token(body.token)
        if email is None:
            raise HTTPException(400, "invalid or expired token")
        user = store.upsert_user(email)
        tenant_id = user.id  # option A: 1 user = 1 tenant
        tenant_home(root, tenant_id)
        principal = SessionPrincipal(user_id=user.id, email=user.email, tenant_id=tenant_id)
        set_session_cookie(response, principal)
        return {"user_id": user.id, "email": user.email, "tenant_id": tenant_id}

    @app.post("/v1/auth/logout")
    def logout(response: Response) -> dict:
        clear_session_cookie(response)
        return {"ok": True}

    @app.get("/v1/sessions")
    def list_sessions(principal: SessionPrincipal = Depends(current)) -> list:
        return store.list_sessions(principal.user_id)

    @app.post("/v1/sessions")
    def create_session(body: SessionIn, principal: SessionPrincipal = Depends(current)) -> dict:
        sid = store.create_session(principal.user_id, title=body.title)
        return {"id": sid}

    @app.get("/v1/sessions/{session_id}")
    def get_session(session_id: str, principal: SessionPrincipal = Depends(current)) -> dict:
        meta = store.get_session(principal.user_id, session_id)
        if meta is None:
            raise HTTPException(404, "session not found")
        home = tenant_home(root, principal.tenant_id)
        from milyonus.core.store import SessionStore

        ss = SessionStore(home / "state.db")
        messages = []
        row = ss.find_session(
            channel="web", user_ref=principal.user_id, title=f"web:{session_id}"
        )
        if row is not None:
            for m in ss.history(row.id):
                messages.append(
                    {
                        "id": m["id"],
                        "role": m["role"],
                        "content": m["content"],
                        "created_at": m["created_at"],
                    }
                )
        ss.close()
        return {
            "id": session_id,
            "title": meta["title"],
            "pinned": bool(meta["pinned"]),
            "updated_at": meta["updated_at"],
            "messages": messages,
        }

    @app.patch("/v1/sessions/{session_id}")
    def patch_session(
        session_id: str,
        body: SessionPatch,
        principal: SessionPrincipal = Depends(current),
    ) -> dict:
        ok = store.patch_session(
            principal.user_id, session_id, title=body.title, pinned=body.pinned
        )
        if not ok:
            raise HTTPException(404, "session not found")
        return {"ok": True}

    @app.delete("/v1/sessions/{session_id}")
    def delete_session(session_id: str, principal: SessionPrincipal = Depends(current)) -> dict:
        if not store.delete_session(principal.user_id, session_id):
            raise HTTPException(404, "session not found")
        return {"ok": True}

    @app.get("/v1/search")
    def search(q: str, principal: SessionPrincipal = Depends(current)) -> list:
        home = tenant_home(root, principal.tenant_id)
        from milyonus.core.store import SessionStore

        ss = SessionStore(home / "state.db")
        try:
            hits = []
            for r in ss.search(q):
                core = ss.get_session(r["session_id"])
                if core is None or not (core.title or "").startswith("web:"):
                    continue
                web_id = core.title[4:]
                if store.get_session(principal.user_id, web_id) is None:
                    continue
                hits.append(
                    {
                        "session_id": web_id,
                        "message_id": r["message_id"],
                        "role": r["role"],
                        "snippet": r["snippet"],
                    }
                )
            return hits
        finally:
            ss.close()

    @app.post("/v1/attachments")
    async def upload(request: Request, principal: SessionPrincipal = Depends(current)) -> dict:
        from milyonus.security.injection import max_severity, scan
        from milyonus.security.redact import redact

        if not store.rate_limit("upload:" + principal.user_id, limit=30, window=3600):
            raise HTTPException(429, "upload limit exceeded")
        data = bytearray()
        async for chunk in request.stream():
            if len(data) + len(chunk) > 1_000_000:
                raise HTTPException(413, "maximum upload is 1 MB")
            data.extend(chunk)
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            raise HTTPException(415, "only UTF-8 text is supported") from None
        if "\x00" in text or max_severity(scan(text)) == "high":
            raise HTTPException(422, "unsafe attachment")
        folder = tenant_home(root, principal.tenant_id) / "attachments"
        folder.mkdir(mode=0o700, exist_ok=True)
        aid = uuid.uuid4().hex
        path = folder / aid
        path.write_text(redact(text), encoding="utf-8")
        path.chmod(0o600)
        return {"id": aid, "bytes": len(data)}

    @app.post("/v1/sessions/{session_id}/messages")
    async def post_message(
        session_id: str,
        body: MessageIn,
        principal: SessionPrincipal = Depends(current),
    ) -> dict:
        if store.get_session(principal.user_id, session_id) is None:
            raise HTTPException(404, "session not found")
        home = tenant_home(root, principal.tenant_id)
        workspace = home / "workspace"
        if not store.rate_limit("message:" + principal.user_id, limit=30, window=60):
            raise HTTPException(429, "message rate exceeded")
        from milyonus.web.context import attachment_context

        if len(body.attachments) > 4:
            raise HTTPException(422, "maximum four attachments")
        files = []
        for aid in dict.fromkeys(body.attachments):
            if len(aid) != 32 or any(c not in "0123456789abcdef" for c in aid):
                raise HTTPException(404, "attachment not found")
            path = home / "attachments" / aid
            if not path.is_file():
                raise HTTPException(404, "attachment not found")
            files.append((aid, path.read_text("utf-8")))
        context = attachment_context(files, body.text)
        workspace.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            turn_id = await hub.start_turn(
                user_id=principal.user_id,
                session_id=session_id,
                text=body.text + ("\n" + context if context else ""),
                workspace=workspace,
                home=home,
            )
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc
        return {"turn_id": turn_id}

    @app.get("/v1/sessions/{session_id}/stream")
    async def stream(
        session_id: str,
        request: Request,
        from_seq: int = 0,
        turn_id: str | None = None,
        principal: SessionPrincipal = Depends(current),
    ) -> StreamingResponse:
        if store.get_session(principal.user_id, session_id) is None:
            raise HTTPException(404, "session not found")
        selected_turn = turn_id or store.latest_turn(session_id)
        if selected_turn is None or not store.turn_belongs_to(selected_turn, session_id):
            raise HTTPException(404, "turn not found")
        last = request.headers.get("last-event-id")
        start = int(last) + 1 if last and last.isdigit() else max(0, from_seq)

        async def gen() -> AsyncIterator[str]:
            cursor = start
            while True:
                if await request.is_disconnected():
                    break
                events = store.events_from(selected_turn, cursor)
                for ev in events:
                    cursor = ev["seq"] + 1
                    data = json.dumps(ev, ensure_ascii=False)
                    yield f"id: {ev['seq']}\nevent: {ev['type']}\ndata: {data}\n\n"
                    if ev["type"] == "turn.completed":
                        return
                await asyncio.sleep(0.15)

        return StreamingResponse(gen(), media_type="text/event-stream")

    @app.post("/v1/sessions/{session_id}/cancel")
    async def cancel(
        session_id: str,
        body: CancelIn,
        principal: SessionPrincipal = Depends(current),
    ) -> dict:
        if store.get_session(principal.user_id, session_id) is None:
            raise HTTPException(404, "session not found")
        handle = hub.get(body.turn_id)
        if handle is not None and handle.session_id != session_id:
            raise HTTPException(404, "turn not found")
        ok = await hub.cancel(body.turn_id)
        return {"cancelled": ok}

    @app.post("/v1/approvals/{approval_id}")
    async def decide_approval(
        approval_id: str,
        body: ApprovalIn,
        principal: SessionPrincipal = Depends(current),
    ) -> dict:
        if body.decision not in ("allow", "deny", "allow_session"):
            raise HTTPException(400, "invalid decision")
        row = store.get_approval(approval_id)
        if row is None or store.approval_owner(approval_id) != principal.user_id:
            raise HTTPException(404, "approval not found")
        ok = await hub.resolve_approval(approval_id, body.decision, principal.user_id)
        if not ok:
            raise HTTPException(409, "approval not pending or irreversible allow_session")
        return {"ok": True, "decision": body.decision}

    @app.get("/v1/memory")
    def list_memory(
        state: str | None = None,
        q: str | None = None,
        page: int = 1,
        principal: SessionPrincipal = Depends(current),
    ) -> dict:
        home = tenant_home(root, principal.tenant_id)
        from milyonus.memory.store import MemoryStore

        allowed = {
            "pending",
            "active",
            "rejected",
            "revoked",
            "expired",
            "superseded",
            "t0_staged",
        }
        ms = MemoryStore(home / "state.db")
        items = []
        if state:
            if state not in allowed:
                raise HTTPException(400, "invalid state")
            rows = list(ms.by_state(state))  # type: ignore[arg-type]
        else:
            rows = list(ms.by_state("active")) + list(ms.by_state("pending"))  # type: ignore[arg-type]
        for item in rows:
            if q and q.lower() not in (item.content or "").lower():
                continue
            items.append(
                {
                    "id": item.id,
                    "content": item.content,
                    "state": item.state,
                    "trust_tier": item.trust_tier,
                    "source_uri": item.provenance.source_uri if item.provenance else None,
                }
            )
        ms.close()
        start = max(0, (page - 1) * 50)
        return {"items": items[start : start + 50], "page": page}

    @app.get("/v1/memory/{item_id}/why")
    def memory_why(item_id: str, principal: SessionPrincipal = Depends(current)) -> dict:
        home = tenant_home(root, principal.tenant_id)
        from milyonus.memory.store import MemoryStore

        ms = MemoryStore(home / "state.db")
        item = ms.get(item_id)
        if item is None:
            raise HTTPException(404, "not found")
        payload = {
            "id": item.id,
            "content": item.content,
            "state": item.state,
            "trust_tier": item.trust_tier,
            "provenance": {
                "source_kind": item.provenance.source_kind,
                "source_uri": item.provenance.source_uri,
                "session_id": item.provenance.session_id,
                "turn_id": item.provenance.turn_id,
                "actor": item.provenance.actor,
            },
            "evidence_hash": item.evidence_hash,
        }
        ms.close()
        return payload

    @app.post("/v1/memory/{item_id}/reaffirm")
    def reaffirm(item_id: str, principal: SessionPrincipal = Depends(current)) -> dict:
        from milyonus.memory.store import MemoryStore, ReaffirmError

        ms = MemoryStore(tenant_home(root, principal.tenant_id) / "state.db")
        try:
            item = ms.get(item_id)
            if item is None:
                raise HTTPException(404, "not found")
            if item.state != "active":
                raise HTTPException(409, "only active memory can be reaffirmed")
            try:
                ceiling = ms.reaffirm(item_id, min_interval_seconds=3600)
            except ReaffirmError as exc:
                raise HTTPException(429, str(exc)) from exc
            return {"ok": True, "trust_ceiling": ceiling}
        finally:
            ms.close()

    @app.post("/v1/memory/revoke-preview")
    def revoke_preview(body: RevokeIn, principal: SessionPrincipal = Depends(current)) -> dict:
        from milyonus.memory.store import MemoryStore

        ms = MemoryStore(tenant_home(root, principal.tenant_id) / "state.db")
        try:
            ids = ms.preview_revoke_by_source(body.source_uri)
            return {"affected": ids, "count": len(ids)}
        finally:
            ms.close()

    @app.post("/v1/memory/revoke")
    def revoke(body: RevokeIn, principal: SessionPrincipal = Depends(current)) -> dict:
        home = tenant_home(root, principal.tenant_id)
        from milyonus.memory.store import MemoryStore

        ms = MemoryStore(home / "state.db")
        revoked = ms.revoke_by_source(body.source_uri)
        ms.close()
        return {"revoked": revoked}

    @app.get("/v1/audit/verify")
    def audit_verify(principal: SessionPrincipal = Depends(current)) -> dict:
        home = tenant_home(root, principal.tenant_id)
        from milyonus.memory.store import MemoryStore

        ms = MemoryStore(home / "state.db")
        intact = ms.verify_ledger()
        ms.close()
        return {"intact": intact, "head": None}

    @app.get("/v1/skills")
    def skills(principal: SessionPrincipal = Depends(current)) -> list:
        del principal
        from milyonus.skills.engine import SkillEngine

        return SkillEngine().list_level0()

    @app.get("/v1/skills/{name}")
    def skill_view(name: str, principal: SessionPrincipal = Depends(current)) -> dict:
        del principal
        from milyonus.skills.engine import SkillEngine

        body = SkillEngine().view(name)
        if body.startswith("skill not found:"):
            raise HTTPException(404, "skill not found")
        return {"name": name, "body": body}

    @app.get("/v1/usage")
    def usage(principal: SessionPrincipal = Depends(current)) -> dict:
        return store.usage(principal.tenant_id)

    @app.get("/v1/settings")
    def get_settings(principal: SessionPrincipal = Depends(current)) -> dict:
        return store.get_settings(principal.user_id)

    @app.put("/v1/settings")
    def put_settings(body: SettingsIn, principal: SessionPrincipal = Depends(current)) -> dict:
        cleaned = {k: v for k, v in body.values.items() if k in SETTINGS_ALLOWLIST}
        current_vals = store.get_settings(principal.user_id)
        current_vals.update(cleaned)
        store.put_settings(principal.user_id, current_vals)
        return current_vals

    @app.get("/v1/export")
    def export(principal: SessionPrincipal = Depends(current)) -> dict:
        return {
            "user_id": principal.user_id,
            "email": principal.email,
            "sessions": store.list_sessions(principal.user_id),
            "settings": store.get_settings(principal.user_id),
            "usage": store.usage(principal.tenant_id),
        }

    @app.delete("/v1/account")
    def delete_account(response: Response, principal: SessionPrincipal = Depends(current)) -> dict:
        store.erase_user(principal.user_id)
        clear_session_cookie(response)
        return {"erased": True}

    return app
