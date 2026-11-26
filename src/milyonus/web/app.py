"""FastAPI application for the Milyonus web surface (PLAN-WEB §5–§11)."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import time
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
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
DEFAULT_ATTACHMENT_QUOTA = 25 * 1024 * 1024  # 25 MiB per tenant


class MagicLinkIn(BaseModel):
    email: str = Field(min_length=3, max_length=320, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class VerifyIn(BaseModel):
    token: str


class SessionIn(BaseModel):
    title: str | None = None
    parent_id: str | None = None
    fork_before_message_id: str | None = None


class SessionPatch(BaseModel):
    title: str | None = None
    pinned: bool | None = None


class MessageIn(BaseModel):
    text: str = Field(min_length=1, max_length=100_000)
    attachments: list[str] = Field(default_factory=list)
    tools_enabled: bool = True


class FeedbackIn(BaseModel):
    session_id: str
    rating: str
    note: str = Field(default="", max_length=500)


class CancelIn(BaseModel):
    turn_id: str


class ApprovalIn(BaseModel):
    decision: str


class RevokeIn(BaseModel):
    source_uri: str


class SettingsIn(BaseModel):
    values: dict[str, str | bool | int | float]


class ApiKeyIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class ProjectInstructionsIn(BaseModel):
    content: str = Field(max_length=32_000)


class ProofVerifyIn(BaseModel):
    bundle: dict
    require_signature: bool = False


class ImeceRunIn(BaseModel):
    task: str = Field(min_length=3, max_length=20_000)
    agents: int = Field(default=17, ge=17, le=10_000)
    verification: str = Field(default="model")
    dry_run: bool = True


class ForgeSkillIn(BaseModel):
    name: str = Field(min_length=2, max_length=64)
    description: str = Field(default="", max_length=300)
    publish: bool = True


class ArenaMatchIn(BaseModel):
    task: str = Field(min_length=2, max_length=4000)
    contender_a: str = Field(default="direct", min_length=1, max_length=64)
    contender_b: str = Field(default="structured", min_length=1, max_length=64)
    expect_substring: str | None = None
    dry_run: bool = True


def create_app(*, data_root: Path | None = None, static_dir: Path | None = None) -> FastAPI:
    from milyonus.web.imece_hub import ImeceRunHub

    root = data_root or Path(
        os.environ.get("MILYONUS_WEB_DATA", str(Path.home() / ".milyonus" / "web"))
    )
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if os.environ.get("MILYONUS_WEB_DEV_AUTH", "0") != "1":
        if len(os.environ.get("MILYONUS_WEB_SECRET", "")) < 32:
            raise RuntimeError(
                "Production requires MILYONUS_WEB_SECRET with at least 32 characters"
            )
        if os.environ.get("MILYONUS_WEB_SECURE") != "1":
            raise RuntimeError("Production requires MILYONUS_WEB_SECURE=1")
    store = WebStore(root / "web.db")
    # Per-request runs pass an explicit tenant `home` directory (no process-wide env mutation).
    hub = RunnerHub(store, home=root)
    imece_hub = ImeceRunHub(store)

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

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'",
        )
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        if os.environ.get("MILYONUS_WEB_SECURE") == "1":
            response.headers.setdefault(
                "Strict-Transport-Security",
                "max-age=63072000; includeSubDomains",
            )
        return response

    app.state.store = store
    app.state.hub = hub
    app.state.imece_hub = imece_hub
    app.state.data_root = root

    def current(request: Request) -> SessionPrincipal:
        # Support scoped API key authentication alongside cookie sessions (PLAN-WEB §8.1).
        auth_header = request.headers.get("authorization", "")
        if auth_header.lower().startswith("bearer "):
            raw_key = auth_header[7:].strip()
            user = store.verify_api_key(raw_key)
            if user is None:
                raise HTTPException(401, "invalid or revoked api key")
            return SessionPrincipal(user_id=user.id, email=user.email, tenant_id=user.id)

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

    @app.get("/metrics", response_class=PlainTextResponse)
    def metrics() -> str:
        """Prometheus-compatible operational metrics (PLAN-WEB W8)."""
        snap = store.metrics_snapshot()
        cache = hub.prefix_cache_stats()
        lines = [
            "# HELP milyonus_active_users Active web users",
            "# TYPE milyonus_active_users gauge",
            f"milyonus_active_users {snap['active_users']}",
            "# HELP milyonus_active_sessions Active non-archived sessions",
            "# TYPE milyonus_active_sessions gauge",
            f"milyonus_active_sessions {snap['active_sessions']}",
            "# HELP milyonus_turns_total Total web turns created",
            "# TYPE milyonus_turns_total counter",
            f"milyonus_turns_total {snap['turns_total']}",
            "# HELP milyonus_turns_running Currently executing web turns",
            "# TYPE milyonus_turns_running gauge",
            f"milyonus_turns_running {snap['turns_running']}",
            "# HELP milyonus_approvals_pending Pending tool approvals",
            "# TYPE milyonus_approvals_pending gauge",
            f"milyonus_approvals_pending {snap['approvals_pending']}",
            "# HELP milyonus_tokens_used_total Cumulative tokens billed across tenants",
            "# TYPE milyonus_tokens_used_total counter",
            f"milyonus_tokens_used_total {snap['tokens_used_total']}",
            "# HELP milyonus_prefix_cache_hits_total Stable system-prompt prefix cache hits",
            "# TYPE milyonus_prefix_cache_hits_total counter",
            f"milyonus_prefix_cache_hits_total {cache['hits']}",
            "# HELP milyonus_prefix_cache_misses_total System-prompt prefix cache misses",
            "# TYPE milyonus_prefix_cache_misses_total counter",
            f"milyonus_prefix_cache_misses_total {cache['misses']}",
            "# HELP milyonus_circuit_breaker_open Open provider circuit breakers",
            "# TYPE milyonus_circuit_breaker_open gauge",
            f"milyonus_circuit_breaker_open {cache['circuit_breaker_open']}",
        ]
        return "\n".join(lines) + "\n"

    @app.post("/v1/auth/magic-link", status_code=202)
    def magic_link(body: MagicLinkIn) -> dict:
        if not store.rate_limit("login:" + body.email.lower(), limit=5, window=3600):
            raise HTTPException(429, "too many login requests")
        token = store.create_magic_token(body.email)
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
        parent_id: str | None = None
        if body.parent_id:
            if store.get_session(principal.user_id, body.parent_id) is None:
                raise HTTPException(404, "parent session not found")
            parent_id = body.parent_id
        sid = store.create_session(principal.user_id, title=body.title, parent_id=parent_id)
        if parent_id and body.fork_before_message_id is not None:
            from milyonus.core.store import SessionStore

            home = tenant_home(root, principal.tenant_id)
            ss = SessionStore(home / "state.db")
            try:
                parent_row = ss.find_session(
                    channel="web", user_ref=principal.user_id, title=f"web:{parent_id}"
                )
                if parent_row is not None:
                    child_core_id = ss.create_session(
                        "web", user_ref=principal.user_id, title=f"web:{sid}"
                    )
                    for m in ss.history(parent_row.id):
                        if str(m["id"]) == body.fork_before_message_id:
                            break
                        ss.append_message(
                            child_core_id,
                            turn=int(m["turn"]),
                            role=str(m["role"]),
                            content=str(m["content"] or ""),
                        )
            finally:
                ss.close()
        return {"id": sid, "parent_id": parent_id}

    @app.get("/v1/sessions/{session_id}")
    def get_session(session_id: str, principal: SessionPrincipal = Depends(current)) -> dict:
        meta = store.get_session(principal.user_id, session_id)
        if meta is None:
            raise HTTPException(404, "session not found")
        home = tenant_home(root, principal.tenant_id)
        from milyonus.core.store import SessionStore

        ss = SessionStore(home / "state.db")
        messages = []
        row = ss.find_session(channel="web", user_ref=principal.user_id, title=f"web:{session_id}")
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
        active_turn_id = store.active_turn(session_id)
        pending_approvals = (
            store.pending_approvals_for_turn(active_turn_id) if active_turn_id else []
        )
        fb = {
            str(item["message_id"]): item["rating"]
            for item in store.list_feedback(principal.user_id, session_id=session_id)
        }
        return {
            "id": session_id,
            "title": meta["title"],
            "pinned": bool(meta["pinned"]),
            "parent_id": meta.get("parent_id"),
            "updated_at": meta["updated_at"],
            "messages": messages,
            "active_turn_id": active_turn_id,
            "pending_approvals": pending_approvals,
            "feedback": fb,
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
                title = core.title if core is not None else None
                if not title or not title.startswith("web:"):
                    continue
                web_id = title[4:]
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

    async def _handle_upload(request: Request, principal: SessionPrincipal) -> dict:
        from milyonus.security.injection import max_severity, scan
        from milyonus.security.redact import redact
        from milyonus.web.context import detect_image_mime, extract_pdf_text

        if not store.rate_limit("upload:" + principal.user_id, limit=30, window=3600):
            raise HTTPException(429, "upload limit exceeded")

        ct = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
        max_bytes = 5_000_000 if ct.startswith("image/") or ct == "application/pdf" else 1_000_000
        data = bytearray()
        async for chunk in request.stream():
            if len(data) + len(chunk) > max_bytes:
                limit_mb = max_bytes // 1_000_000
                raise HTTPException(413, f"maximum upload is {limit_mb} MB")
            data.extend(chunk)
        raw = bytes(data)

        quota = int(os.environ.get("MILYONUS_WEB_ATTACHMENT_QUOTA_BYTES", DEFAULT_ATTACHMENT_QUOTA))
        if store.attachment_bytes_used(principal.tenant_id) + len(raw) > quota:
            raise HTTPException(413, "tenant attachment storage quota exceeded")

        filename = (request.headers.get("x-filename") or "upload").strip()[:120] or "upload"
        filename = "".join(c if c.isalnum() or c in "._-" else "_" for c in filename)

        folder = tenant_home(root, principal.tenant_id) / "attachments"
        folder.mkdir(mode=0o700, exist_ok=True)
        aid = uuid.uuid4().hex
        digest = hashlib.sha256(raw).hexdigest()

        img_mime = detect_image_mime(raw) if ct.startswith("image/") else None
        if img_mime is not None:
            ext = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}[img_mime]
            ws = tenant_home(root, principal.tenant_id) / "workspace" / ".uploads"
            ws.mkdir(mode=0o700, parents=True, exist_ok=True)
            img_path = ws / f"{aid}{ext}"
            img_path.write_bytes(raw)
            img_path.chmod(0o600)
            note = f"[Image attachment: {filename} ({img_mime}, {len(raw)} bytes) saved at .uploads/{aid}{ext}. Use read_image if needed.]"
            path = folder / aid
            path.write_text(note, encoding="utf-8")
            path.chmod(0o600)
            store.record_attachment(
                attachment_id=aid,
                tenant_id=principal.tenant_id,
                filename=filename,
                mime=img_mime,
                size_bytes=len(raw),
                sha256=digest,
                path=str(img_path),
            )
            return {"id": aid, "file_id": aid, "bytes": len(raw), "mime": img_mime}

        if ct == "application/pdf" or raw.startswith(b"%PDF-"):
            try:
                text = extract_pdf_text(raw)
            except ValueError:
                raise HTTPException(415, "invalid PDF attachment") from None
            if max_severity(scan(text)) == "high":
                raise HTTPException(422, "unsafe attachment")
            if not text:
                text = f"[PDF attachment: {filename} ({len(raw)} bytes) contained no extractable text.]"
            path = folder / aid
            path.write_text(redact(text), encoding="utf-8")
            path.chmod(0o600)
            store.record_attachment(
                attachment_id=aid,
                tenant_id=principal.tenant_id,
                filename=filename,
                mime="application/pdf",
                size_bytes=len(raw),
                sha256=digest,
                path=str(path),
            )
            return {"id": aid, "file_id": aid, "bytes": len(raw), "mime": "application/pdf"}

        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            raise HTTPException(
                415, "only UTF-8 text, PDF, or PNG/JPEG/WEBP images are supported"
            ) from None
        if "\x00" in text or max_severity(scan(text)) == "high":
            raise HTTPException(422, "unsafe attachment")
        path = folder / aid
        path.write_text(redact(text), encoding="utf-8")
        path.chmod(0o600)
        store.record_attachment(
            attachment_id=aid,
            tenant_id=principal.tenant_id,
            filename=filename,
            mime=ct or "text/plain",
            size_bytes=len(raw),
            sha256=digest,
            path=str(path),
        )
        return {"id": aid, "file_id": aid, "bytes": len(raw), "mime": ct or "text/plain"}

    @app.post("/v1/attachments")
    async def upload(request: Request, principal: SessionPrincipal = Depends(current)) -> dict:
        return await _handle_upload(request, principal)

    @app.post("/v1/files")
    async def upload_file_alias(
        request: Request, principal: SessionPrincipal = Depends(current)
    ) -> dict:
        return await _handle_upload(request, principal)

    @app.get("/v1/attachments")
    def list_attachments(principal: SessionPrincipal = Depends(current)) -> dict:
        quota = int(os.environ.get("MILYONUS_WEB_ATTACHMENT_QUOTA_BYTES", DEFAULT_ATTACHMENT_QUOTA))
        return {
            "items": store.list_attachments(principal.tenant_id),
            "bytes_used": store.attachment_bytes_used(principal.tenant_id),
            "quota_bytes": quota,
        }

    @app.delete("/v1/attachments/{attachment_id}")
    def delete_attachment(
        attachment_id: str, principal: SessionPrincipal = Depends(current)
    ) -> dict:
        row = store.delete_attachment(principal.tenant_id, attachment_id)
        if row is None:
            raise HTTPException(404, "attachment not found")
        home = tenant_home(root, principal.tenant_id)
        for p in (home / "attachments" / attachment_id, Path(row["path"])):
            if p.exists() and p.is_file() and home.resolve() in p.resolve().parents:
                p.unlink(missing_ok=True)
        return {"deleted": True}

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
                tools_enabled=body.tools_enabled,
            )
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc
        return {"turn_id": turn_id}

    @app.post("/v1/messages/{message_id}/feedback")
    def message_feedback(
        message_id: str,
        body: FeedbackIn,
        principal: SessionPrincipal = Depends(current),
    ) -> dict:
        """Record thumbs up/down feedback for a message (PLAN-WEB §2.1)."""
        if body.rating not in ("up", "down"):
            raise HTTPException(400, "rating must be 'up' or 'down'")
        if store.get_session(principal.user_id, body.session_id) is None:
            raise HTTPException(404, "session not found")
        return store.save_feedback(
            user_id=principal.user_id,
            session_id=body.session_id,
            message_id=message_id,
            rating=body.rating,
            note=body.note,
        )

    @app.post("/v1/sessions/{session_id}/regenerate")
    async def regenerate(
        session_id: str,
        principal: SessionPrincipal = Depends(current),
    ) -> dict:
        """Re-run the latest user turn in a session (PLAN-WEB §2.1)."""
        if store.get_session(principal.user_id, session_id) is None:
            raise HTTPException(404, "session not found")
        if not store.rate_limit("message:" + principal.user_id, limit=30, window=60):
            raise HTTPException(429, "message rate exceeded")
        home = tenant_home(root, principal.tenant_id)
        workspace = home / "workspace"
        workspace.mkdir(mode=0o700, parents=True, exist_ok=True)
        from milyonus.core.store import SessionStore

        ss = SessionStore(home / "state.db")
        try:
            row = ss.find_session(
                channel="web", user_ref=principal.user_id, title=f"web:{session_id}"
            )
            if row is None:
                raise HTTPException(404, "no messages to regenerate")
            ss.pop_last_assistant(row.id)
            hist = ss.history(row.id)
            last_user = next((m["content"] for m in reversed(hist) if m["role"] == "user"), None)
            if not last_user:
                raise HTTPException(404, "no user turn to regenerate")
        finally:
            ss.close()
        try:
            turn_id = await hub.start_turn(
                user_id=principal.user_id,
                session_id=session_id,
                text=last_user,
                workspace=workspace,
                home=home,
                append_user=False,
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

    @app.get("/v1/turns/{turn_id}/tool-results/{call_id}")
    def get_tool_result(
        turn_id: str, call_id: str, principal: SessionPrincipal = Depends(current)
    ) -> dict:
        if store.turn_owner(turn_id) != principal.user_id:
            raise HTTPException(404, "tool result not found")
        res = store.get_tool_result(turn_id, call_id)
        if res is None:
            raise HTTPException(404, "tool result not found")
        return res

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
        from milyonus.config.schema import MemoryConfig
        from milyonus.memory.store import MemoryStore
        from milyonus.memory.trust import current_trust

        allowed = {
            "pending",
            "active",
            "rejected",
            "revoked",
            "expired",
            "superseded",
            "t0_staged",
            "erased",
        }
        cfg = MemoryConfig()
        now = time.time()
        ms = MemoryStore(home / "state.db")
        try:
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
                trust = current_trust(
                    item.trust_tier,
                    item.last_reaffirmed_at or item.verified_at or item.created_at,
                    now,
                    cfg,
                    ceiling=item.trust_ceiling,
                    sensitivity=item.sensitivity,
                )
                items.append(
                    {
                        "id": item.id,
                        "content": item.content,
                        "state": item.state,
                        "trust_tier": item.trust_tier,
                        "trust_score": round(trust, 3),
                        "trust_ceiling": item.trust_ceiling,
                        "review_at": item.review_at,
                        "reaffirm_count": item.reaffirm_count,
                        "sensitivity": item.sensitivity,
                        "source_uri": item.provenance.source_uri if item.provenance else None,
                    }
                )
        finally:
            ms.close()
        start = max(0, (page - 1) * 50)
        return {"items": items[start : start + 50], "page": page}

    @app.get("/v1/memory/{item_id}/why")
    def memory_why(item_id: str, principal: SessionPrincipal = Depends(current)) -> dict:
        home = tenant_home(root, principal.tenant_id)
        from milyonus.memory.store import MemoryStore

        ms = MemoryStore(home / "state.db")
        try:
            item = ms.get(item_id)
            if item is None:
                raise HTTPException(404, "not found")
            return {
                "id": item.id,
                "content": item.content,
                "state": item.state,
                "trust_tier": item.trust_tier,
                "verdict": item.verdict,
                "confirmations": item.confirmations,
                "sensitivity": item.sensitivity,
                "reaffirm_count": item.reaffirm_count,
                "review_at": item.review_at,
                "provenance": {
                    "source_kind": item.provenance.source_kind,
                    "source_uri": item.provenance.source_uri,
                    "session_id": item.provenance.session_id,
                    "turn_id": item.provenance.turn_id,
                    "actor": item.provenance.actor,
                },
                "evidence_hash": item.evidence_hash,
            }
        finally:
            ms.close()

    @app.post("/v1/memory/{item_id}/reaffirm")
    async def reaffirm(item_id: str, principal: SessionPrincipal = Depends(current)) -> dict:
        from milyonus.memory.store import MemoryStore, ReaffirmError

        def _do() -> float:
            ms = MemoryStore(tenant_home(root, principal.tenant_id) / "state.db")
            try:
                item = ms.get(item_id)
                if item is None:
                    raise HTTPException(404, "not found")
                if item.state != "active":
                    raise HTTPException(409, "only active memory can be reaffirmed")
                try:
                    return ms.reaffirm(item_id, min_interval_seconds=3600)
                except ReaffirmError as exc:
                    raise HTTPException(429, str(exc)) from exc
            finally:
                ms.close()

        ceiling = await hub.memory_writer.submit(_do)
        return {"ok": True, "trust_ceiling": ceiling}

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
    async def revoke(body: RevokeIn, principal: SessionPrincipal = Depends(current)) -> dict:
        home = tenant_home(root, principal.tenant_id)
        from milyonus.memory.store import MemoryStore

        def _do() -> list[str]:
            ms = MemoryStore(home / "state.db")
            try:
                return ms.revoke_by_source(body.source_uri)
            finally:
                ms.close()

        revoked = await hub.memory_writer.submit(_do)
        return {"revoked": revoked}

    @app.get("/v1/audit/verify")
    def audit_verify(principal: SessionPrincipal = Depends(current)) -> dict:
        home = tenant_home(root, principal.tenant_id)
        from milyonus.memory.store import MemoryStore

        ms = MemoryStore(home / "state.db")
        try:
            intact = ms.verify_ledger()
            head = ms.ledger_head()
            return {"intact": intact, "head": head}
        finally:
            ms.close()

    @app.get("/v1/skills")
    def skills(principal: SessionPrincipal = Depends(current)) -> list:
        from milyonus.skills.engine import SkillEngine

        home = tenant_home(root, principal.tenant_id)
        return SkillEngine.for_tenant(home / "skills").list_level0()

    @app.get("/v1/skills/{name}")
    def skill_view(name: str, principal: SessionPrincipal = Depends(current)) -> dict:
        from milyonus.skills.engine import SkillEngine

        home = tenant_home(root, principal.tenant_id)
        body = SkillEngine.for_tenant(home / "skills").view(name)
        if body.startswith("skill not found:"):
            raise HTTPException(404, "skill not found")
        return {"name": name, "body": body}

    @app.get("/v1/project-instructions")
    def get_project_instructions(principal: SessionPrincipal = Depends(current)) -> dict:
        """Read tenant `.milyonusrules` project instructions (PLAN-WEB W6)."""
        home = tenant_home(root, principal.tenant_id)
        path = home / "workspace" / ".milyonusrules"
        content = path.read_text("utf-8") if path.is_file() and not path.is_symlink() else ""
        return {"filename": ".milyonusrules", "content": content}

    @app.put("/v1/project-instructions")
    def put_project_instructions(
        body: ProjectInstructionsIn, principal: SessionPrincipal = Depends(current)
    ) -> dict:
        """Save tenant `.milyonusrules` after injection scanning and redaction."""
        from milyonus.security.injection import max_severity, scan
        from milyonus.security.redact import redact

        findings = scan(body.content)
        if max_severity(findings) == "high":
            raise HTTPException(
                422,
                "project instructions blocked by injection scanner: "
                + ", ".join(f.signal for f in findings),
            )
        ws = tenant_home(root, principal.tenant_id) / "workspace"
        ws.mkdir(mode=0o700, parents=True, exist_ok=True)
        path = ws / ".milyonusrules"
        if path.is_symlink():
            raise HTTPException(400, "invalid instruction file path")
        cleaned = redact(body.content)
        path.write_text(cleaned, encoding="utf-8")
        path.chmod(0o600)
        return {
            "filename": ".milyonusrules",
            "content": cleaned,
            "findings": [f.signal for f in findings],
        }

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

    @app.get("/v1/api-keys")
    def list_api_keys(principal: SessionPrincipal = Depends(current)) -> list:
        return store.list_api_keys(principal.tenant_id)

    @app.post("/v1/api-keys")
    def create_api_key(body: ApiKeyIn, principal: SessionPrincipal = Depends(current)) -> dict:
        key_id, raw_key, prefix = store.create_api_key(principal.tenant_id, body.name)
        return {"id": key_id, "name": body.name, "prefix": prefix, "key": raw_key}

    @app.delete("/v1/api-keys/{key_id}")
    def revoke_api_key(key_id: str, principal: SessionPrincipal = Depends(current)) -> dict:
        if not store.revoke_api_key(principal.tenant_id, key_id):
            raise HTTPException(404, "api key not found")
        return {"revoked": True}

    @app.get("/v1/export")
    def export(principal: SessionPrincipal = Depends(current)) -> dict:
        """Full KVKK/GDPR JSON data export including sessions, messages, memory & provenance (ADR-0011)."""
        home = tenant_home(root, principal.tenant_id)
        from milyonus.core.store import SessionStore
        from milyonus.memory.store import MemoryStore

        sessions_out = []
        ss = SessionStore(home / "state.db")
        try:
            for meta in store.list_sessions(principal.user_id):
                row = ss.find_session(
                    channel="web", user_ref=principal.user_id, title=f"web:{meta['id']}"
                )
                msgs = (
                    [
                        {
                            "id": m["id"],
                            "role": m["role"],
                            "content": m["content"],
                            "created_at": m["created_at"],
                        }
                        for m in ss.history(row.id)
                    ]
                    if row is not None
                    else []
                )
                sessions_out.append({**meta, "messages": msgs})
        finally:
            ss.close()

        memories_out = []
        ms = MemoryStore(home / "state.db")
        try:
            for st in (
                "active",
                "pending",
                "rejected",
                "revoked",
                "expired",
                "superseded",
                "t0_staged",
                "erased",
            ):
                for item in ms.by_state(st):  # type: ignore[arg-type]
                    memories_out.append(
                        {
                            "id": item.id,
                            "content": item.content,
                            "state": item.state,
                            "trust_tier": item.trust_tier,
                            "evidence_hash": item.evidence_hash,
                            "created_at": item.created_at,
                            "provenance": {
                                "source_kind": item.provenance.source_kind,
                                "source_uri": item.provenance.source_uri,
                                "session_id": item.provenance.session_id,
                                "turn_id": item.provenance.turn_id,
                                "actor": item.provenance.actor,
                            },
                        }
                    )
            audit_intact = ms.verify_ledger()
            ledger_head = ms.ledger_head()
        finally:
            ms.close()

        return {
            "user_id": principal.user_id,
            "email": principal.email,
            "sessions": sessions_out,
            "memory": memories_out,
            "feedback": store.list_feedback(principal.user_id),
            "audit": {"intact": audit_intact, "head": ledger_head},
            "settings": store.get_settings(principal.user_id),
            "usage": store.usage(principal.tenant_id),
        }

    @app.delete("/v1/account")
    async def delete_account(
        response: Response, principal: SessionPrincipal = Depends(current)
    ) -> dict:
        """Irreversible account erasure: tombstones memory preserving ledger hash chain (ADR-0011)."""
        import sqlite3

        home = tenant_home(root, principal.tenant_id)
        from milyonus.core.store import SessionStore
        from milyonus.memory.store import MemoryStore

        _EXTRA_TENANT_TABLES = (
            "arena_ratings",
            "arena_matches",
            "mesh_peers",
            "mesh_dispatches",
            "pareto_stats",
            "evolution_runs",
            "evolution_genomes",
            "memory_branch_items",
            "memory_branches",
            "capability_leases",
            "lease_canaries",
            "compliance_certs",
            "dag_runs",
            "privacy_budgets",
            "privacy_releases",
            "memory_vector",
        )

        def _erase_tenant_state() -> tuple[int, int, int]:
            db_path = home / "state.db"
            ms = MemoryStore(db_path)
            try:
                tombstoned = ms.erase_all()
            finally:
                ms.close()
            ss = SessionStore(db_path)
            try:
                deleted_msgs = ss.erase_all()
            finally:
                ss.close()
            purged_extra = 0
            conn = sqlite3.connect(str(db_path))
            try:
                existing = {
                    str(r[0])
                    for r in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    ).fetchall()
                }
                for tbl in _EXTRA_TENANT_TABLES:
                    if tbl in existing:
                        cur = conn.execute(f"DELETE FROM {tbl}")
                        purged_extra += max(0, cur.rowcount)
                conn.commit()
            finally:
                conn.close()
            return tombstoned, deleted_msgs, purged_extra

        tombstoned, deleted_msgs, purged_extra = await hub.memory_writer.submit(_erase_tenant_state)
        for subdir in ("attachments", "workspace", "skills"):
            target = home / subdir
            if target.exists() and not target.is_symlink():
                shutil.rmtree(target, ignore_errors=True)
        lease_key = home / ".lease_hmac.key"
        if lease_key.is_file() and not lease_key.is_symlink():
            lease_key.unlink(missing_ok=True)
        store.erase_user(principal.user_id)
        clear_session_cookie(response)
        return {
            "erased": True,
            "tombstoned_memories": tombstoned,
            "deleted_messages": deleted_msgs,
            "purged_auxiliary_records": purged_extra,
        }

    # --- M1: Memory Time-Travel & Counterfactual Replay -----------------

    @app.get("/v1/memory/timeline")
    def memory_timeline(limit: int = 200, principal: SessionPrincipal = Depends(current)) -> dict:
        from milyonus.memory.store import MemoryStore
        from milyonus.memory.timetravel import checkpoint_timeline

        ms = MemoryStore(tenant_home(root, principal.tenant_id) / "state.db")
        try:
            pts = checkpoint_timeline(ms, limit=max(1, min(limit, 500)))
            return {"checkpoints": [p.to_dict() for p in pts], "intact": ms.verify_ledger()}
        finally:
            ms.close()

    @app.get("/v1/memory/snapshot")
    def memory_snapshot(
        seq: int | None = None,
        at: float | None = None,
        principal: SessionPrincipal = Depends(current),
    ) -> dict:
        from milyonus.memory.store import MemoryStore
        from milyonus.memory.timetravel import reconstruct_at

        ms = MemoryStore(tenant_home(root, principal.tenant_id) / "state.db")
        try:
            return reconstruct_at(ms, seq=seq, at_timestamp=at).to_dict()
        finally:
            ms.close()

    @app.get("/v1/memory/diff")
    def memory_diff(
        from_seq: int,
        to_seq: int,
        principal: SessionPrincipal = Depends(current),
    ) -> dict:
        from milyonus.memory.store import MemoryStore
        from milyonus.memory.timetravel import diff_snapshots

        ms = MemoryStore(tenant_home(root, principal.tenant_id) / "state.db")
        try:
            return diff_snapshots(ms, from_seq, to_seq).to_dict()
        finally:
            ms.close()

    @app.post("/v1/memory/counterfactual")
    def memory_counterfactual(
        body: RevokeIn, principal: SessionPrincipal = Depends(current)
    ) -> dict:
        from milyonus.memory.store import MemoryStore
        from milyonus.memory.timetravel import counterfactual_revoke

        ms = MemoryStore(tenant_home(root, principal.tenant_id) / "state.db")
        try:
            return counterfactual_revoke(ms, body.source_uri).to_dict()
        finally:
            ms.close()

    # --- M2: Signed Evidence Bundles (`.milyonus-proof.json`) -----------

    @app.get("/v1/sessions/{session_id}/proof")
    def session_proof(session_id: str, principal: SessionPrincipal = Depends(current)) -> dict:
        if store.get_session(principal.user_id, session_id) is None:
            raise HTTPException(404, "session not found")
        home = tenant_home(root, principal.tenant_id)
        from milyonus.core.store import SessionStore
        from milyonus.memory.store import MemoryStore
        from milyonus.security.proof import build_session_proof

        ss = SessionStore(home / "state.db")
        ms = MemoryStore(home / "state.db")
        try:
            row = ss.find_session(
                channel="web", user_ref=principal.user_id, title=f"web:{session_id}"
            )
            messages = [dict(m) for m in ss.history(row.id)] if row is not None else []
            tools = store.tool_results_for_session(session_id)
            return build_session_proof(
                session_id,
                messages,
                tool_results=tools,
                memory_store=ms,
            )
        finally:
            ss.close()
            ms.close()

    @app.post("/v1/proofs/verify")
    def verify_proof_endpoint(
        body: ProofVerifyIn, principal: SessionPrincipal = Depends(current)
    ) -> dict:
        del principal
        from milyonus.security.proof import verify_proof

        return verify_proof(body.bundle, require_signature=body.require_signature).to_dict()

    # --- M3: Live İmece War Room ----------------------------------------

    @app.get("/v1/imece/runs")
    def list_imece_runs(principal: SessionPrincipal = Depends(current)) -> list:
        return store.list_imece_runs(principal.user_id)

    @app.post("/v1/imece/runs")
    async def create_imece_run(
        body: ImeceRunIn, principal: SessionPrincipal = Depends(current)
    ) -> dict:
        if not store.rate_limit("imece:" + principal.user_id, limit=15, window=300):
            raise HTTPException(429, "imece rate limit exceeded")
        from typing import Literal

        verif: Literal["model", "python"] = "python" if body.verification == "python" else "model"
        home = tenant_home(root, principal.tenant_id)
        return await imece_hub.start_run(
            user_id=principal.user_id,
            task=body.task,
            agents=body.agents,
            verification=verif,
            dry_run=body.dry_run,
            home=home,
        )

    @app.get("/v1/imece/runs/{run_id}")
    def get_imece_run(run_id: str, principal: SessionPrincipal = Depends(current)) -> dict:
        run = store.get_imece_run(principal.user_id, run_id)
        if run is None:
            raise HTTPException(404, "imece run not found")
        return run

    @app.get("/v1/imece/runs/{run_id}/stream")
    async def stream_imece_run(
        run_id: str,
        request: Request,
        from_seq: int = 0,
        principal: SessionPrincipal = Depends(current),
    ) -> StreamingResponse:
        if store.get_imece_run(principal.user_id, run_id) is None:
            raise HTTPException(404, "imece run not found")
        last = request.headers.get("last-event-id")
        start = int(last) + 1 if last and last.isdigit() else max(0, from_seq)

        async def gen() -> AsyncIterator[str]:
            cursor = start
            while True:
                if await request.is_disconnected():
                    break
                events = store.imece_events_from(run_id, cursor)
                for ev in events:
                    cursor = ev["seq"] + 1
                    data = json.dumps(ev, ensure_ascii=False)
                    yield f"id: {ev['seq']}\nevent: {ev['type']}\ndata: {data}\n\n"
                    if ev["type"] in ("imece.completed", "imece.stopped", "imece.error"):
                        return
                run_now = store.get_imece_run(principal.user_id, run_id)
                if (
                    run_now is None or run_now["state"] in ("completed", "stopped", "error")
                ) and not store.imece_events_from(run_id, cursor):
                    return
                await asyncio.sleep(0.1)

        return StreamingResponse(gen(), media_type="text/event-stream")

    @app.post("/v1/imece/runs/{run_id}/stop")
    def stop_imece_run(run_id: str, principal: SessionPrincipal = Depends(current)) -> dict:
        if store.get_imece_run(principal.user_id, run_id) is None:
            raise HTTPException(404, "imece run not found")
        stopped = imece_hub.request_stop(run_id)
        return {"stop_requested": stopped}

    @app.get("/v1/imece/runs/{run_id}/proof")
    def get_imece_run_proof(run_id: str, principal: SessionPrincipal = Depends(current)) -> dict:
        run = store.get_imece_run(principal.user_id, run_id)
        if run is None or not run.get("report") or not run["report"].get("proof"):
            raise HTTPException(404, "proof not available yet")
        return run["report"]["proof"]

    # --- M4: Adversarial Chaos & Red-Team Autopilot ---------------------

    @app.post("/v1/security/chaos")
    async def run_security_chaos(principal: SessionPrincipal = Depends(current)) -> dict:
        if not store.rate_limit("chaos:" + principal.user_id, limit=10, window=300):
            raise HTTPException(429, "chaos audit rate limit exceeded")
        from milyonus.security.chaos import run_chaos_suite

        report = await run_chaos_suite(include_web=False)
        return report.to_dict()

    # --- M5: Skill Forge & Multi-Strategy Arena -------------------------

    @app.post("/v1/sessions/{session_id}/forge-skill")
    async def forge_session_skill(
        session_id: str,
        body: ForgeSkillIn,
        principal: SessionPrincipal = Depends(current),
    ) -> dict:
        if store.get_session(principal.user_id, session_id) is None:
            raise HTTPException(404, "session not found")
        home = tenant_home(root, principal.tenant_id)
        from milyonus.core.store import SessionStore
        from milyonus.skills.forge import extract_skill_draft_from_messages, forge_skill

        ss = SessionStore(home / "state.db")
        try:
            row = ss.find_session(
                channel="web", user_ref=principal.user_id, title=f"web:{session_id}"
            )
            messages = [dict(m) for m in ss.history(row.id)] if row is not None else []
        finally:
            ss.close()
        if not messages:
            raise HTTPException(400, "session has no messages to forge into a skill")
        spec = extract_skill_draft_from_messages(
            messages,
            name=body.name,
            description=body.description,
            session_id=session_id,
        )
        res = await forge_skill(spec, live_dir=home / "skills", publish=body.publish)
        if not res.ok:
            raise HTTPException(422, res.message)
        return res.to_dict()

    @app.get("/v1/arena/leaderboard")
    def arena_leaderboard(principal: SessionPrincipal = Depends(current)) -> dict:
        from milyonus.imece.arena import ArenaStore

        store_a = ArenaStore(tenant_home(root, principal.tenant_id) / "state.db")
        try:
            return {
                "leaderboard": store_a.leaderboard(),
                "recent_matches": store_a.recent_matches(limit=10),
            }
        finally:
            store_a.close()

    @app.post("/v1/arena/match")
    async def arena_match(
        body: ArenaMatchIn, principal: SessionPrincipal = Depends(current)
    ) -> dict:
        if not store.rate_limit("arena:" + principal.user_id, limit=20, window=300):
            raise HTTPException(429, "arena rate limit exceeded")
        from milyonus.imece.arena import ArenaContender, ArenaStore, run_arena_match

        home = tenant_home(root, principal.tenant_id)
        if body.dry_run:

            async def _sim_a(t: str) -> str:
                return f"[{body.contender_a}] direct response for: {t}"

            async def _sim_b(t: str) -> str:
                return f"[{body.contender_b}] structured step-by-step verified solution for: {t}"

            ca = ArenaContender(body.contender_a, body.contender_a, _sim_a)
            cb = ArenaContender(body.contender_b, body.contender_b, _sim_b)
        else:
            from milyonus.config.loader import load_config
            from milyonus.providers.base import CompletionRequest, Message
            from milyonus.providers.router import build_provider

            cfg = load_config(home / "config.toml")
            prov = build_provider(cfg.provider)

            def _make_fn(style: str):
                async def _fn(t: str) -> str:
                    out: list[str] = []
                    req = CompletionRequest(
                        system=f"Follow strategy '{style}'. Be concise, accurate, and verifiable.",
                        messages=[Message(role="user", content=t)],
                        max_output_tokens=cfg.provider.max_output_tokens,
                    )
                    async for ev in prov.stream(req):
                        if ev.kind == "text":
                            out.append(ev.delta)
                    return "".join(out)

                return _fn

            ca = ArenaContender(body.contender_a, body.contender_a, _make_fn(body.contender_a))
            cb = ArenaContender(body.contender_b, body.contender_b, _make_fn(body.contender_b))

        oracle = None
        if body.expect_substring is not None:
            needle = body.expect_substring

            def _oracle(_t: str, out: str) -> tuple[bool, float]:
                ok = needle in out
                return ok, 1.0 if ok else 0.0

            oracle = _oracle

        store_a = ArenaStore(home / "state.db")
        try:
            res = await run_arena_match(store_a, body.task, ca, cb, oracle_fn=oracle)
            return res.to_dict()
        finally:
            store_a.close()

    # --- Hypernova H1–H10 & Singularity S1–S10 Capabilities -------------
    from milyonus.web.hypernova_routes import mount_hypernova_routes
    from milyonus.web.singularity_routes import mount_singularity_routes

    mount_hypernova_routes(app, root=root, store=store, hub=hub, current=current)
    mount_singularity_routes(app, root=root, store=store, current=current)

    if static_dir is not None:
        resolved_root = static_dir.resolve()
        index_html = resolved_root / "index.html"
        if index_html.is_file():

            @app.get("/{full_path:path}", include_in_schema=False)
            def serve_spa(full_path: str) -> FileResponse:
                if full_path.startswith("v1/") or full_path in ("v1", "healthz", "metrics"):
                    raise HTTPException(404, "not found")
                if full_path:
                    candidate = (resolved_root / full_path).resolve()
                    if (
                        candidate.is_relative_to(resolved_root)
                        and candidate.is_file()
                        and not candidate.is_symlink()
                    ):
                        return FileResponse(candidate)
                return FileResponse(index_html)

    return app
