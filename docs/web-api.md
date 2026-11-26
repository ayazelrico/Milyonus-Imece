# Web API contract (v1)

Surface #7 — browser product. Companion to [PLAN-WEB.md](../PLAN-WEB.md).
Palette: customer-facing tokens from `design.md` (`#2E6BFF` / `#5CC8FF`).
Tenancy: option **A** — directory per tenant (`<web_data>/t/<tenant>`).

## Security headers & auth

- Cookie session (`httpOnly; SameSite=Lax`, `Secure` when `MILYONUS_WEB_SECURE=1`) + double-submit `x-csrf-token` on mutating calls, OR `Authorization: Bearer mil_...` scoped API key (SHA-256 hashed at rest, revocable).
- Every response sets `Content-Security-Policy`, `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, and `Strict-Transport-Security` when `MILYONUS_WEB_SECURE=1`.

## REST

```
GET    /healthz                                       → {ok: true}
GET    /metrics                                       → Prometheus text metrics (incl. prefix cache & circuit breaker)
GET    /{spa_route}                                   → built SPA assets + index.html fallback when `--static-dir` / `web/dist` present

POST   /v1/auth/magic-link         {email}            → 202
POST   /v1/auth/verify             {token}            → sets cookie
POST   /v1/auth/logout

GET    /v1/sessions                                   → [{id,title,updated_at,pinned,parent_id}]
POST   /v1/sessions                {title?,parent_id?,fork_before_message_id?} → {id,parent_id}
GET    /v1/sessions/{id}                              → {…, parent_id, messages[], feedback{}, active_turn_id, pending_approvals[]}
PATCH  /v1/sessions/{id}           {title?,pinned?}
DELETE /v1/sessions/{id}
GET    /v1/search?q=                                  → FTS5 hits

POST   /v1/sessions/{id}/messages   {text, attachments[], tools_enabled?} → {turn_id}
POST   /v1/sessions/{id}/regenerate                       → {turn_id}
POST   /v1/messages/{id}/feedback   {session_id, rating, note?} → rating ∈ up|down
GET    /v1/sessions/{id}/stream?turn_id=&from_seq=        → SSE
POST   /v1/sessions/{id}/cancel     {turn_id}
GET    /v1/turns/{turn_id}/tool-results/{call_id}         → full persisted tool output

POST   /v1/approvals/{approval_id} {decision}         → decision ∈ allow|deny|allow_session

GET    /v1/memory?state=&q=&page=                     → items + trust_score + decay metadata
GET    /v1/memory/{id}/why                            → provenance chain + verdict + evidence_hash
POST   /v1/memory/{id}/reaffirm                       → 429 if rate-limited
POST   /v1/memory/revoke-preview   {source_uri}       → non-destructive cascade preview
POST   /v1/memory/revoke           {source_uri}       → {revoked:[ids]}
GET    /v1/audit/verify                               → {intact: bool, head: sha256}

GET    /v1/skills · GET /v1/skills/{name}
GET    /v1/project-instructions · PUT /v1/project-instructions
GET    /v1/usage                                      → tokens_used, cost_usd, turns, period
GET    /v1/settings · PUT /v1/settings                → allowlisted fields only
GET    /v1/api-keys · POST /v1/api-keys · DELETE /v1/api-keys/{id}
POST   /v1/attachments · POST /v1/files               → text / PDF / PNG / JPEG / WEBP (quota enforced)
GET    /v1/attachments · DELETE /v1/attachments/{id}
GET    /v1/export                                     → full JSON export (sessions + messages + memory + feedback + provenance + audit)
DELETE /v1/account                                    → ADR-0011 erasure (tombstones memory, preserves ledger chain)

# Moonshot M1–M5 endpoints (PLAN-MOONSHOT.md)
GET    /v1/memory/timeline                            → hash-verified ledger checkpoints
GET    /v1/memory/snapshot?seq=&at=                   → reconstructed historical memory snapshot
GET    /v1/memory/diff?from_seq=&to_seq=              → epoch-to-epoch memory diff
POST   /v1/memory/counterfactual   {source_uri}       → zero-mutation counterfactual revocation report

GET    /v1/sessions/{id}/proof                        → verifiable `.milyonus-proof.json` capsule
POST   /v1/proofs/verify           {bundle}           → offline Merkle + Ed25519 capsule verifier

GET    /v1/imece/runs · POST /v1/imece/runs           → launch/list Live İmece War Room runs
GET    /v1/imece/runs/{id} · /stream · /proof         → run detail, SSE phase stream, proof capsule
POST   /v1/imece/runs/{id}/stop                       → emergency stop between collective phases

POST   /v1/security/chaos                             → isolated 10-vector (20-probe) Adversarial Chaos Scorecard
POST   /v1/sessions/{id}/forge-skill {name, ...}      → distill, scan, and publish a verified SKILL.md
GET    /v1/arena/leaderboard · POST /v1/arena/match   → head-to-head Strategy Arena + Elo leaderboard

# Hypernova H1–H10 endpoints (PLAN-HYPERNOVA.md)
GET    /v1/memory/graph · /conflicts · /blast-radius  → H1 Epistemic Knowledge Graph, contradictions & blast radius
GET/POST /v1/memory/branches · /{name:path}/items|diff|merge|DELETE → H2 Git-style cognitive memory branching
GET/POST /v1/leases · /{id}/verify · DELETE /{id}     → H3 Signed Capability Leases
POST   /v1/leases/canary · /canary/scan               → H3 Honeytoken Canary global lease kill-switch
GET    /v1/constitution/presets · POST /evaluate|/simulate → H4 IRADE Constitutional Policy Engine & Veto Simulator
POST   /v1/evolution/run · GET /runs · /runs/{id}     → H5 Swarm DNA genetic evolution & phylogeny
POST   /v1/proofs/disclose · /verify-disclosure       → H6 Cryptographic Selective Disclosure Merkle proofs
GET    /v1/skills/immune/scan · POST /seal|/heal      → H7 Autonomous Self-Healing Skill Immune System
GET    /v1/sessions/{id}/flight · POST /v1/flights/analyze|diff → H8 Black-Box Flight Recorder DVR & anomaly detector
GET    /v1/router/frontier · POST /route|/outcome     → H9 Cost-Latency-Trust Pareto Frontier Router & Beta/UCB bandit
GET/POST /v1/mesh/peers · DELETE /{id} · POST /dispatch → H10 Federated İmece Mesh Byzantine signed quorum

# Singularity S1–S10 endpoints (PLAN-SINGULARITY.md)
POST   /v1/security/intent-scan    {text}             → S1 4-axis EN/TR subtle behavioral poisoning shield
POST   /v1/passport/issue · /verify                   → S2 Signed Agent Passports (`milyonus.passport.v1`)
POST   /v1/shadow/simulate · /apply                   → S3 Jailed speculative shadow-fork dry-run & drift-checked commit
GET    /v1/memory/forecast?days=                      → S4 Temporal trust decay forecast & amnesia risk score
POST   /v1/surgeon/analyze         {source, filename} → S5 AST self-patching Code Surgeon
POST   /v1/dag/compile · /run · GET /v1/dag/runs      → S6 Parallel DAG workflow compiler (Kahn + CPM)
GET    /v1/privacy/budget · POST /v1/privacy/release  → S7 Laplace (ε)-Differential Privacy vault & accountant
POST   /v1/certify/run · GET /v1/certify/history      → S8 Enterprise 6-pillar Compliance Certifier
POST   /v1/security/fuzz           {iterations, seed} → S9 Seeded adversarial mutation security fuzzer
POST   /v1/economy/simulate · GET /v1/economy/scales  → S10 Multi-agent collective economy & Pareto savings simulator
```

## SSE events

Every event carries monotonic `seq` per turn and is persisted **before** the
socket write. Reconnect replays from `Last-Event-ID` / `from_seq`.

```
turn.started · text.delta · tool.call · tool.result
approval.required · approval.resolved · memory.proposed
context.sources · context.compacted · usage (+prefix_cache_hit) · turn.completed · error
```

## Hard rules

- Client cannot set the system prompt.
- Approvals bind to server-held `(tenant, session, turn, call_id)`; timeout → deny; `allow_session` refused for irreversible actions.
- T0 memory cannot be staged or activated from the browser.
- Hosted shell defaults off unless `security.sandbox_backend != "local"`.
