"""`milyonus web` — run the browser surface API."""

from __future__ import annotations

from pathlib import Path

import typer

web_app = typer.Typer(help="Browser surface (FastAPI + SSE). Requires [web] extra.")


@web_app.command("start")
def web_start(
    host: str = typer.Option("127.0.0.1", help="Bind host"),
    port: int = typer.Option(8787, help="Bind port"),
    data: str = typer.Option("", help="Web data root (tenants under t/)"),
    reload: bool = typer.Option(False, help="Dev auto-reload"),
) -> None:
    """Start the web API (surface #7)."""
    from milyonus.web import require_web

    require_web()
    import uvicorn

    from milyonus.web.app import create_app

    app = create_app(data_root=Path(data) if data else None)
    uvicorn.run(app, host=host, port=port, reload=reload)
