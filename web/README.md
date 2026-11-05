# Milyonus Web (surface #7)

Vite + React 19 SPA for the browser product described in `PLAN-WEB.md`.

## Run

```bash
# API
uv sync --extra web --extra dev
uv run milyonus web --host 127.0.0.1 --port 8787

# UI
cd web && npm install && npm run dev
```

Open http://localhost:5173 — magic-link tokens are returned in the API response
when `MILYONUS_WEB_DEV_AUTH=1` (default for local).
