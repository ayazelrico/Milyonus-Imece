"""Milyonus web surface (#7) — FastAPI + SSE, optional `[web]` extra."""

from __future__ import annotations


def require_web() -> None:
    try:
        import fastapi  # noqa: F401
        import uvicorn  # noqa: F401
    except ImportError as exc:  # pragma: no cover - import guard
        raise SystemExit(
            "Web surface requires: pip install 'milyonus-agent[web]' "
            "(fastapi, uvicorn, python-multipart, itsdangerous)"
        ) from exc
