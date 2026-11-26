# Milyonus-Imece — Moonshot Plan (5 Breakthrough Capabilities)

> Status: **All 5 capabilities (M1–M5) implemented and verified in-tree (2026-11-26).**
> Companion action tracker: [PLAN-MOONSHOT-ACTIONS.md](PLAN-MOONSHOT-ACTIONS.md).
> Core foundation plans: [PLAN.md](PLAN.md) · [PLAN-WEB.md](PLAN-WEB.md) · [PLAN-5X.md](PLAN-5X.md).
> Owner: @ayazelrico · License: Apache-2.0

---

## 0. Design Thesis

Milyonus-Imece already differentiates itself on **verified, decaying, revocable memory** and **independent multi-agent gates (İmece + IRADE + Kapı 1–3)**. The next five capabilities push that moat from "safer agent" to a **verifiable, time-travelable, self-hardening collective engineering platform** — without introducing fake claims, weakening fail-closed boundaries, or adding fragile third-party bloat:

| # | Capability | One-line Promise | Core Surfaces |
|---|---|---|---|
| **M1** | **Memory Time-Travel & Counterfactual Replay** | Scrub backward through the hash-chained memory ledger to inspect what the agent believed at any sequence/timestamp, diff two epochs, or simulate revoking a source before touching live state. | `memory/timetravel.py` · `milyonus memory timeline\|timetravel\|diff\|counterfactual` · `/v1/memory/timeline\|snapshot\|diff\|counterfactual` · Web `TrustRail` Scrubber |
| **M2** | **Signed Evidence Bundles (`.milyonus-proof.json`)** | Export any İmece run or chat session as an offline-auditable cryptographic Proof Capsule (deliverable digests, gate results, tool outputs, memory ledger head, Merkle root, optional Ed25519 signature). | `security/proof.py` · `milyonus proof create\|verify` · `/v1/sessions/{id}/proof` · `/v1/proofs/verify` · Web Proof Export |
| **M3** | **Live İmece War Room on Web Surface #7** | Launch and monitor multi-agent İmece collectives directly in the browser with real-time SSE phase telemetry (`Kapı 1 → 2 → 3`), scale allocation preview, interactive Emergency Stop, and Proof Capsule export. | `web/imece_hub.py` · `web/store.py` · `/v1/imece/runs*` · Web `WarRoomModal.tsx` |
| **M4** | **Adversarial Chaos & Red-Team Autopilot** | Continuously attack Milyonus's own injection scanner, risk engine, memory pipeline, skill scanner, oracle guard, and web tenant boundaries across 6 vectors to emit a quantified 0–100 Immunity Scorecard. | `security/chaos.py` · `milyonus chaos run` · `POST /v1/security/chaos` · Web Shield Check |
| **M5** | **Skill Forge & Multi-Strategy Arena** | Synthesize scanned, assertion-verified `SKILL.md` artifacts from solved sessions, and pit strategies/models head-to-head with executable oracle scoring and an SQLite Elo rating ledger. | `skills/forge.py` · `imece/arena.py` · `milyonus skills forge` · `milyonus arena` · `/v1/sessions/{id}/forge-skill` · `/v1/arena/*` |

---

## M1. Memory Time-Travel & Counterfactual Replay

### Problem
Once an agent accumulates weeks of memory, debugging *"Why did the agent believe X last Tuesday?"* or *"What happens to my agent's knowledge if I revoke untrusted feed Y?"* requires reconstructing historical state without breaking append-only auditability.

### Architecture (`src/milyonus/memory/timetravel.py`)
1. **Hash-verified ledger replay (`reconstruct_at`)**:
   - Reads `memory_ledger` ordered by `seq ASC` up to `seq` or `at_timestamp` while independently recomputing `entry_hash` (`SHA-256(prev_hash|seq|ts|action|item_id|detail)`), setting `chain_intact: bool`.
   - Applies state transitions deterministically (`propose` → `pending`, `promote` → `active`, `reject` → `rejected`, `revoke` → `revoked`, `demote` → `pending`, `expire` → `expired`, `supersede` → `superseded`, `stage_t0` → `t0_staged`, `erase` → `erased`).
   - Returns `MemorySnapshotAt(seq, timestamp, chain_intact, ledger_head, items, active_count, pending_count, rendered_snapshot)` where `rendered_snapshot` uses the exact same `<milyonus:memory>` formatter as live turns.
2. **Epoch diffing (`diff_snapshots`)**:
   - Compares any two sequences `(seq_a, seq_b)` and returns `MemoryDiff(from_seq, to_seq, added, removed, state_changed, unchanged_count)`.
3. **Counterfactual revocation simulation (`counterfactual_revoke`)**:
   - Uses `MemoryStore.preview_revoke_by_source(source_uri)` (which follows transitive `derived_from` lineage) to compute a zero-mutation `CounterfactualReport`:
     - `source_uri`, `affected_ids`, `direct_count`, `derived_count`, `before_active_count`, `after_active_count`, `removed_contents`, `tokens_freed_estimate`.
4. **Timeline index (`checkpoint_timeline`)**:
   - Summarizes ledger entries into compact navigable checkpoints (`seq`, `ts`, `action`, `item_id`, `detail`, `hash_prefix`) for CLI tables and the Web Time-Travel Scrubber.

### Security Invariants
- Strictly **read-only**: time-travel, diff, and counterfactual simulation NEVER mutate `memory` or `memory_ledger`.
- Chain verification runs on every reconstruction; tampered ledgers surface `chain_intact=False` explicitly.
- Web endpoints are scoped strictly to the authenticated tenant's isolated `state.db`.

---

## M2. Signed Evidence Bundles (`.milyonus-proof.json`)

### Problem
Autonomous agent outputs are difficult to audit after the fact: screenshots and logs can be edited, and there is no cryptographic link between a delivered artifact, its test results, and the memory ledger state that influenced the run.

### Architecture (`src/milyonus/security/proof.py`)
1. **Canonical deterministic payload (`ProofBundle`)**:
   - `schema_version = "milyonus.proof.v1"`
   - `kind`: `"imece_run"` | `"web_session"`
   - `created_at`, `subject_id`, `summary`
   - `claims`: list of structured, hash-addressed evidence records (`deliverable_files`, `gate_reports`, `messages`, `tool_results`) where each record carries `sha256` over canonical JSON (`sort_keys=True, separators=(",", ":")`).
   - `memory_anchor`: `{ledger_head, ledger_intact, active_count}` linking the output to the exact memory state.
   - `merkle_root`: binary SHA-256 Merkle tree root over sorted leaf hashes (deterministic, tamper-evident to a single bit).
   - `bundle_sha256`: canonical SHA-256 of the unsigned envelope.
   - `signature`: optional `{algorithm: "ed25519", signature_b64, pubkey_fingerprint}` using existing `milyonus.security.operator`.
2. **Offline verification (`verify_proof`)**:
   - Recomputes every leaf hash, the Merkle root, and `bundle_sha256`.
   - If signed (or `require_signature=True`), verifies Ed25519 signature against installed/explicit `operator.pub` (fail-closed if key missing or invalid).
   - Returns `ProofVerification(valid, checks_passed, errors, signed, signature_valid, merkle_root)`.

### Security Invariants
- Redacts secret patterns (`security.redact`) from messages/tool outputs before embedding in web session proofs.
- Verification fails closed on schema mismatch, leaf hash mismatch, Merkle root mismatch, or bad signature.

---

## M3. Live İmece War Room on Web Surface #7

### Problem
`milyonus imece` (multi-agent collective + IRADE council + Kapı 1–3 gates) is currently CLI-only, leaving Web Surface #7 limited to single-agent chat turns.

### Architecture (`src/milyonus/web/imece_hub.py` + `web/src/components/WarRoomModal.tsx`)
1. **Durable per-tenant runs in `WebStore`**:
   - New tables: `imece_runs(id, user_id, task, agents, verification, mode, state, current_phase, report_json, error, created_at, ended_at)` and `imece_events(run_id, seq, type, payload_json, created_at)`.
   - All reads/writes protected by `WebStore._lock` and strictly scoped to `user_id`.
2. **Live execution hub (`ImeceRunHub`)**:
   - Launches `Imece(...).run(task)` in an isolated asyncio background task per run.
   - Wires `on_phase` → appends monotonic `imece.phase` SSE events (`seq`, `phase`, `elapsed_s`) before streaming.
   - Wires `should_stop` → checks per-run `threading.Event` triggered via `POST /v1/imece/runs/{run_id}/stop` (cleanly raising `Stopped` between phases!).
   - Supports `dry_run=True` (deterministic local multi-agent collective simulator using real `Imece` orchestrator + `scale.allocate` + `Kapı 1–3` pipeline with zero API spend!) AND `dry_run=False` (live configured provider seats).
   - Automatically builds a verifiable `ProofBundle` upon completion (`GET /v1/imece/runs/{run_id}/proof`).
3. **Web SPA War Room (`WarRoomModal.tsx`)**:
   - Live 12-phase progress pipeline, scale allocation breakdown (`17`..`10,000`), live SSE phase event feed, interactive **Emergency Stop** button, final deliverable & Kapı 3 verdict inspector, and one-click Proof Capsule download.

### Security Invariants
- Strict tenant isolation: another user receives `404` for any `run_id` they do not own.
- Rate-limited run creation; bounded concurrency per tenant; `dry_run` never leaks secrets or touches host filesystem.

---

## M4. Adversarial Chaos & Red-Team Autopilot

### Problem
Regressions in security boundaries happen silently when changes land across prompts, tools, memory, skills, or web APIs. Static unit tests rarely give operators a single live immunity scorecard across all defense layers.

### Architecture (`src/milyonus/security/chaos.py`)
Runs **12 deterministic, isolated adversarial probes** across **6 attack vectors** in ephemeral temporary directories (zero mutation of user data):
1. **Injection Smuggling (`injection`)**: hidden instruction override + credential leak payload blocked by `security.injection.scan`.
2. **Risk & Irreversibility Escalation (`risk`)**: destructive shell (`rm -rf /`), outbound email/exfil, and attempting `allow_session` on irreversible action blocked by `RiskEngine`.
3. **Memory Poisoning & Patient Flood (`memory`)**: rephrase of rejected attack caught by negative memory; rapid reaffirm flood rate-limited by H2; weak reaffirm ceiling capped by H3.
4. **T0 Cryptographic Boundary (`t0`)**: text-origin T0 spoof denied; forged/corrupted Ed25519 signature rejected fail-closed.
5. **Skill Supply-Chain & Path Escape (`skills`)**: `curl | bash` skill blocked even with `force=True`; path traversal `../../etc/passwd` blocked in skill hub & filesystem jail.
6. **Oracle & Multi-Tenant Isolation (`isolation`)**: `oracle_guard` fails closed without OS sandbox; `WebStore` / FastAPI rejects cross-tenant session & approval access and sets strict CSP headers.

Outputs `ChaosReport(immunity_score: int, grade: str, passed: int, total: int, vectors: dict, probes: list[ChaosProbeResult], duration_ms: int)`.

### Security Invariants
- Never touches real `~/.milyonus` user state — every probe uses isolated `tempfile.TemporaryDirectory`.
- Exit code `1` from `milyonus chaos run --min-score 100` if any probe fails, making it CI-ready.

---

## M5. Skill Forge & Multi-Strategy Arena

### Problem
1. Valuable procedures discovered during chat/coding sessions vanish when the thread ends unless manually hand-authored into a verified `SKILL.md`.
2. Users choosing between strategies, system prompt variants, or models have no structured, blind, oracle-verified arena with persistent Elo ratings.

### Architecture
1. **Skill Forge (`src/milyonus/skills/forge.py`)**:
   - `SkillForgeSpec(name, description, body, tags, category, source_session_id, verification_tests)`.
   - `forge_skill(spec, *, live_dir, verify_python=True) -> ForgeResult`:
     - Validates skill frontmatter & scans body via `skills.scanner.scan_skill` (blocks `danger` unconditionally).
     - When Python files + executable test scripts are provided, enforces AST assertion checks AND executes positive + negative-control verification (reusing `skills/manage.py` rigor).
     - Stages & publishes into `live_dir` with `provenance="forged"` and returns `skill_path`, `digest`, `scan_findings`, and `verified: bool`.
   - `extract_skill_draft_from_messages(messages, *, name, description) -> SkillForgeSpec`: deterministically distills a clean, redacted, reusable `SKILL.md` procedure from a solved conversation transcript (also wired into `POST /v1/sessions/{session_id}/forge-skill`).
2. **Multi-Strategy Arena (`src/milyonus/imece/arena.py`)**:
   - `ArenaStore(path)` in SQLite (`arena_ratings`, `arena_matches`) implementing standard Elo (`K=32`, starting rating `1500.0`).
   - `ArenaContender(id, label, run_fn)` + `run_arena_match(store, task, contenders, *, oracle_fn=None, judge_fn=None) -> ArenaMatchResult`:
     - Runs contenders independently on the same task.
     - Evaluates each output against deterministic `oracle_fn` (objective correctness first!) and optional blind `judge_fn` (anonymized `Contender-A`/`Contender-B` tie-breaker).
     - Updates Elo ratings atomically in SQLite and records full match provenance & winner rationale.
   - CLI: `milyonus arena run` and `milyonus arena leaderboard`.
   - Web API: `GET /v1/arena/leaderboard`, `POST /v1/arena/match`.

---

## Verification & Delivery Gate

All 5 features must pass before merge:
- `uv run ruff check src tests evals` & `uv run ruff format --check src tests evals` — **0 errors**
- `uv run mypy src/milyonus` — **0 errors**
- `uv run python -m evals.safety.run` — **0 findings**
- `uv run milyonus chaos run --min-score 100` — **100/100 (A+)**
- `MILYONUS_TEST_DOCKER=1 uv run pytest -q` — **100% pass (all existing + new Moonshot tests)**
- `web/` `npm ci && npm run build` — **0 TS errors, 0 >500 kB chunk warnings**
- GitHub Actions CI (`test` + `web-build`) — **100% green**, PR created and merged into `main`.
