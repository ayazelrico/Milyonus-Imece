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
    static_dir: str = typer.Option(
        "", help="Directory containing built SPA assets (defaults to ./web/dist if present)"
    ),
    reload: bool = typer.Option(False, help="Dev auto-reload"),
) -> None:
    """Start the web API (surface #7), optionally serving the built React SPA."""
    from milyonus.web import require_web

    require_web()
    import uvicorn

    from milyonus.web.app import create_app

    resolved_static: Path | None = None
    if static_dir:
        resolved_static = Path(static_dir)
    else:
        for candidate in (Path.cwd() / "web" / "dist", Path(__file__).parents[3] / "web" / "dist"):
            if (candidate / "index.html").is_file():
                resolved_static = candidate
                break

    app = create_app(
        data_root=Path(data) if data else None,
        static_dir=resolved_static,
    )
    uvicorn.run(app, host=host, port=port, reload=reload)
