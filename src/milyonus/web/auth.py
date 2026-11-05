"""Cookie session + magic-link auth for the web surface."""

from __future__ import annotations

import hashlib
import hmac
import os
import time
from dataclasses import dataclass

from starlette.requests import Request
from starlette.responses import Response

COOKIE = "milyonus_session"
CSRF_COOKIE = "milyonus_csrf"


@dataclass(slots=True)
class SessionPrincipal:
    user_id: str
    email: str
    tenant_id: str


def _secret() -> bytes:
    raw = os.environ.get("MILYONUS_WEB_SECRET", "").encode()
    if len(raw) < 16:
        # Dev fallback — doctor/tests must set a real secret in production.
        raw = b"milyonus-web-dev-secret-change-me"
    return raw


def sign(payload: str) -> str:
    sig = hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def unsign(token: str, *, max_age_s: float = 60 * 60 * 24 * 14) -> str | None:
    if "." not in token:
        return None
    payload, sig = token.rsplit(".", 1)
    expect = hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expect, sig):
        return None
    try:
        user_id, email, tenant_id, issued = payload.split("|", 3)
        if time.time() - float(issued) > max_age_s:
            return None
    except ValueError:
        return None
    return payload


def mint_cookie(user_id: str, email: str, tenant_id: str) -> str:
    return sign(f"{user_id}|{email}|{tenant_id}|{time.time():.0f}")


def principal_from_cookie(token: str | None) -> SessionPrincipal | None:
    if not token:
        return None
    payload = unsign(token)
    if not payload:
        return None
    user_id, email, tenant_id, _issued = payload.split("|", 3)
    return SessionPrincipal(user_id=user_id, email=email, tenant_id=tenant_id)


def set_session_cookie(response: Response, principal: SessionPrincipal) -> str:
    token = mint_cookie(principal.user_id, principal.email, principal.tenant_id)
    csrf = hashlib.sha256(_secret() + token.encode()).hexdigest()[:32]
    secure = os.environ.get("MILYONUS_WEB_SECURE", "0") == "1"
    response.set_cookie(
        COOKIE,
        token,
        httponly=True,
        secure=secure,
        samesite="lax",
        max_age=60 * 60 * 24 * 14,
        path="/",
    )
    response.set_cookie(
        CSRF_COOKIE,
        csrf,
        httponly=False,
        secure=secure,
        samesite="lax",
        max_age=60 * 60 * 24 * 14,
        path="/",
    )
    return csrf


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")


def require_csrf(request: Request) -> bool:
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return True
    header = request.headers.get("x-csrf-token", "")
    cookie = request.cookies.get(CSRF_COOKIE, "")
    return bool(header) and hmac.compare_digest(header, cookie)


SETTINGS_ALLOWLIST = frozenset(
    {
        "locale",
        "provider.model",
        "provider.verifier_model",
        "ui.quiet_memory",
        "ui.language",
    }
)
