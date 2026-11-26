# Milyonus-Imece — Moonshot Action Plan

> Executable tracker for [PLAN-MOONSHOT.md](PLAN-MOONSHOT.md).
> Status: **All milestones M1–M6 completed and verified (2026-11-26).**

---

## Milestone M1 — Memory Time-Travel & Counterfactual Replay
- [x] Create `src/milyonus/memory/timetravel.py`: `MemorySnapshotAt`, `MemoryDiff`, `CounterfactualReport`, `TimelinePoint`, `checkpoint_timeline`, `reconstruct_at`, `diff_snapshots`, `counterfactual_revoke`.
- [x] Add CLI commands in `src/milyonus/cli/memory_cmd.py`: `milyonus memory timeline`, `milyonus memory timetravel`, `milyonus memory epoch-diff`, `milyonus memory counterfactual`.
- [x] Add tenant-isolated Web endpoints in `src/milyonus/web/app.py`:
  - `GET /v1/memory/timeline`
  - `GET /v1/memory/snapshot?seq=`
  - `GET /v1/memory/diff?from_seq=&to_seq=`
  - `POST /v1/memory/counterfactual`
- [x] Add interactive Time-Travel Scrubber & Counterfactual simulator UI to `web/src/components/TrustRail.tsx`.

## Milestone M2 — Signed Evidence Bundles (`.milyonus-proof.json`)
- [x] Create `src/milyonus/security/proof.py`: canonical SHA-256 leaf digests, Merkle tree root, `build_imece_proof`, `build_session_proof`, optional Ed25519 signing via `security/operator.py`, and fail-closed offline `verify_proof`.
- [x] Create `src/milyonus/cli/proof_cmd.py` and mount `milyonus proof` in `src/milyonus/cli/app.py` (`create-from-imece`, `verify`).
- [x] Add Web endpoints in `src/milyonus/web/app.py`:
  - `GET /v1/sessions/{session_id}/proof`
  - `POST /v1/proofs/verify`
- [x] Add one-click Proof Capsule export & Merkle root feedback in `web/src/components/TrustRail.tsx`.

## Milestone M3 — Live İmece War Room on Web Surface #7
- [x] Extend `src/milyonus/web/store.py` with `imece_runs` & `imece_events` tables and thread-safe CRUD + `erase_user` cleanup.
- [x] Create `src/milyonus/web/imece_hub.py`: `ImeceRunHub` driving real `Imece` orchestrator (live seats or zero-spend deterministic `dry_run` collective), live SSE `imece.phase` events, interactive `should_stop` emergency stop, and Proof Capsule generation.
- [x] Add Web endpoints in `src/milyonus/web/app.py`:
  - `GET /v1/imece/runs`
  - `POST /v1/imece/runs`
  - `GET /v1/imece/runs/{run_id}`
  - `GET /v1/imece/runs/{run_id}/stream` (SSE with `from_seq` replay)
  - `POST /v1/imece/runs/{run_id}/stop`
  - `GET /v1/imece/runs/{run_id}/proof`
- [x] Create `web/src/components/WarRoomModal.tsx` and wire launcher button into `web/src/components/Sidebar.tsx` and `web/src/App.tsx`.

## Milestone M4 — Adversarial Chaos & Red-Team Autopilot
- [x] Create `src/milyonus/security/chaos.py`: 12 isolated adversarial probes across 6 vectors (`injection`, `risk`, `memory`, `t0`, `skills`, `isolation`), Immunity Score (0–100), letter grade (`A+`–`F`), JSON report serializer.
- [x] Create `src/milyonus/cli/chaos_cmd.py` and mount `milyonus chaos` in `src/milyonus/cli/app.py` (`milyonus chaos run [--min-score 100] [--json-out]`).
- [x] Add rate-limited `POST /v1/security/chaos` endpoint in `src/milyonus/web/app.py` and Shield Check UI in `web/src/components/SettingsModal.tsx`.
- [x] Add `chaos` target to `Makefile` and integrate `milyonus chaos run --min-score 100` into `.github/workflows/ci.yml`.

## Milestone M5 — Skill Forge & Multi-Strategy Arena
- [x] Create `src/milyonus/skills/forge.py`: `SkillForgeSpec`, `ForgeResult`, `forge_skill` (scanner + AST assertion verification + provenance), `extract_skill_draft_from_messages`.
- [x] Add `milyonus skills forge` command in `src/milyonus/cli/skills_cmd.py`.
- [x] Create `src/milyonus/imece/arena.py`: SQLite `ArenaStore` (Elo ratings + match ledger), `ArenaContender`, `run_arena_match` (deterministic oracle + blind tie-break judging).
- [x] Create `src/milyonus/cli/arena_cmd.py` and mount `milyonus arena` in `src/milyonus/cli/app.py` (`run`, `leaderboard`).
- [x] Add Web endpoints in `src/milyonus/web/app.py`:
  - `POST /v1/sessions/{session_id}/forge-skill`
  - `GET /v1/arena/leaderboard`
  - `POST /v1/arena/match`
- [x] Wire "Forge Skill" action into `web/src/components/TrustRail.tsx` and Strategy Arena view into `web/src/components/WarRoomModal.tsx`.

## Milestone M6 — Tests, Docs, CI Verification, PR & Merge
- [x] Create comprehensive test suites:
  - `tests/test_moonshot_core.py` (M1 Time-Travel, M2 Signed Proof Bundles, M4 Chaos 100/100, M5 Skill Forge & Elo Arena, CLI commands).
  - `tests/test_moonshot_web.py` (M1–M5 Web REST + SSE + War Room live stream & stop + tenant isolation).
- [x] Update `docs/web-api.md`, `CHANGELOG.md`, `README.md`, and mark all checkboxes complete in `PLAN-MOONSHOT-ACTIONS.md`.
- [x] Run full verification gate (`ruff`, `mypy`, `evals.safety.run`, `milyonus chaos run --min-score 100`, `MILYONUS_TEST_DOCKER=1 uv run pytest -q`, `web/` `npm ci && npm run build`, `uv build`).
- [x] Commit in structured commits on feature branch, push to `origin`, open PR, confirm GitHub Actions CI passes green, and merge into `main`.
