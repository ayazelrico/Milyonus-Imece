# Web API contract (frozen for v1)

Surface #7 — browser product. Companion to [PLAN-WEB.md](../PLAN-WEB.md).
Palette: customer-facing tokens from `design.md` (`#2E6BFF` / `#5CC8FF`).
Tenancy: option **A** — directory per tenant (`MILYONUS_HOME=/data/t/<tenant>`).

## REST

```
POST   /v1/auth/magic-link         {email}            → 202
POST   /v1/auth/verify             {token}            → sets cookie
POST   /v1/auth/logout

GET    /v1/sessions                                   → [{id,title,updated_at,pinned}]
POST   /v1/sessions                {title?}           → {id}
GET    /v1/sessions/{id}                              → {…, messages[]}
PATCH  /v1/sessions/{id}           {title?,pinned?}
DELETE /v1/sessions/{id}
GET    /v1/search?q=                                  → FTS5 hits

POST   /v1/sessions/{id}/messages  {text, attachments[]} → {turn_id}
GET    /v1/sessions/{id}/stream?from=<seq>            → SSE
POST   /v1/sessions/{id}/cancel    {turn_id}

POST   /v1/approvals/{approval_id} {decision}         → decision ∈ allow|deny|allow_session

GET    /v1/memory?state=&q=&page=                     → items + trust + decay
GET    /v1/memory/{id}/why                            → provenance chain
POST   /v1/memory/{id}/reaffirm                       → 429 if rate-limited
POST   /v1/memory/revoke           {source_uri}       → {revoked:[ids]}
GET    /v1/audit/verify                               → {intact: bool, head}

GET    /v1/skills · GET /v1/skills/{name}
GET    /v1/usage?range=                               → tokens, cost, turns
GET    /v1/settings · PUT /v1/settings                → allowlisted fields only
POST   /v1/files                                      → {file_id}
GET    /v1/export                                     → full data export (JSON)
DELETE /v1/account                                    → erasure
```

## SSE events

Every event carries monotonic `seq` per turn and is persisted **before** the
socket write. Reconnect replays from `Last-Event-ID` / `from`.

```
turn.started · text.delta · tool.call · tool.result
approval.required · approval.resolved · memory.proposed
usage · turn.completed · error
```

## Hard rules

- Client cannot set the system prompt.
- Approvals bind to server-held `(tenant, session, turn, call_id)`; timeout → deny.
- T0 memory cannot be staged or activated from the browser.
- Hosted shell defaults off unless `security.sandbox_backend != "local"`.
