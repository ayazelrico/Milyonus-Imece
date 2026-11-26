# Milyonus-Imece — Hypernova Action Plan (10 Breakthrough Capabilities)

> Executable tracker for [PLAN-HYPERNOVA.md](PLAN-HYPERNOVA.md).
> Status: **All milestones H1–H11 completed and verified (2026-11-26).**

---

## Milestone H1 — Sovereign Epistemic Knowledge Graph & Contradiction Engine
- [x] Create `src/milyonus/memory/graph.py`: triple/polarity extraction, belief graph builder, contradiction detector, PageRank belief centrality, downstream blast-radius analyzer, Mermaid & DOT exporters.
- [x] Add CLI commands in `src/milyonus/cli/memory_cmd.py`: `milyonus memory graph`, `milyonus memory conflicts`, `milyonus memory blast-radius`.
- [x] Add tenant-isolated Web endpoints in `src/milyonus/web/app.py`: `GET /v1/memory/graph`, `GET /v1/memory/conflicts`.

## Milestone H2 — Cryptographic Memory Branching (Git for Agent Brains)
- [x] Create `src/milyonus/memory/branch.py`: SQLite `memory_branches` & `memory_branch_items`, snapshot branching, isolated staging (`add`/`revoke`), 3-way conflict-aware cognitive diff, verified pipeline merge.
- [x] Create `src/milyonus/cli/branch_cmd.py` and mount `milyonus branch` (`list`, `create`, `show`, `add`, `diff`, `merge`, `delete`).
- [x] Add tenant-isolated Web endpoints in `src/milyonus/web/app.py`: `GET/POST /v1/memory/branches`, `POST /v1/memory/branches/{name}/items`, `GET /v1/memory/branches/{name}/diff`, `POST /v1/memory/branches/{name}/merge`, `DELETE /v1/memory/branches/{name}`.

## Milestone H3 — Zero-Trust Capability Leases & Canary Kill-Switch
- [x] Create `src/milyonus/security/leases.py`: HMAC-SHA256 signed `milyonus.lease.v1` capability tokens, SQLite lease vault, fail-closed `LeaseEnforcer` (TTL, tool/path/domain allowlists, call cap, irreversible lock), and Honeytoken Canary auto-kill-switch.
- [x] Create `src/milyonus/cli/lease_cmd.py` and mount `milyonus lease` (`mint`, `list`, `verify`, `revoke`, `canary-mint`, `canary-scan`).
- [x] Add tenant-isolated Web endpoints in `src/milyonus/web/app.py`: `GET/POST /v1/leases`, `POST /v1/leases/{lease_id}/verify`, `DELETE /v1/leases/{lease_id}`, `POST /v1/leases/canary`, `POST /v1/leases/canary/scan`.

## Milestone H4 — IRADE Constitutional Policy Engine & Live Veto Simulator
- [x] Create `src/milyonus/imece/constitution.py`: canonical SHA-256 `Constitution`, inviolable `ConstitutionalArticle` rules, 4 audited presets, weighted 6-dimension IRADE judge with veto floors, and side-by-side counterfactual `simulate_constitutions`.
- [x] Create `src/milyonus/cli/constitution_cmd.py` and mount `milyonus constitution` (`presets`, `evaluate`, `simulate`).
- [x] Add Web endpoints in `src/milyonus/web/app.py`: `GET /v1/constitution/presets`, `POST /v1/constitution/evaluate`, `POST /v1/constitution/simulate`.

## Milestone H5 — Swarm DNA & Evolutionary Strategy Genome
- [x] Create `src/milyonus/imece/evolution.py`: `SwarmGenome`, SQLite phylogenetic `EvolutionStore`, seeded tournament selection + elitism + crossover + mutation `EvolutionEngine`, deterministic objective fitness evaluator, and `SkillForgeSpec` champion export.
- [x] Create `src/milyonus/cli/evolve_cmd.py` and mount `milyonus evolve` (`run`, `history`, `champion`).
- [x] Add tenant-isolated Web endpoints in `src/milyonus/web/app.py`: `POST /v1/evolution/run`, `GET /v1/evolution/runs`, `GET /v1/evolution/runs/{run_id}`.

## Milestone H6 — Cryptographic Selective Disclosure Merkle Proofs
- [x] Create `src/milyonus/security/disclosure.py`: binary Merkle authentication path generator (`build_merkle_proof`), `create_disclosure_proof` (`milyonus.disclosure.v1`), and fail-closed offline `verify_disclosure_proof`.
- [x] Extend `src/milyonus/cli/proof_cmd.py` with `milyonus proof disclose` and `milyonus proof verify-disclosure`.
- [x] Add Web endpoints in `src/milyonus/web/app.py`: `POST /v1/proofs/disclose`, `POST /v1/proofs/verify-disclosure`.

## Milestone H7 — Autonomous Self-Healing Skill Immune System
- [x] Create `src/milyonus/skills/immune.py`: SHA-256 `.immune-manifest.json` sealing, drift/injection/frontmatter/secret health scanner, atomic `.quarantine/` isolation with incident report, and fail-closed auto-healer.
- [x] Extend `src/milyonus/cli/skills_cmd.py` with `milyonus skills immune-scan`, `immune-seal`, `immune-quarantine`, `immune-heal`.
- [x] Add tenant-isolated Web endpoints in `src/milyonus/web/app.py`: `GET /v1/skills/immune/scan`, `POST /v1/skills/immune/seal`, `POST /v1/skills/immune/heal`.

## Milestone H8 — Flight Recorder: Black-Box Session DVR & Anomaly Detector
- [x] Create `src/milyonus/core/flight_recorder.py`: hash-chained `milyonus.flight.v1` frame envelope, `verify_flight`, `record_from_session`, automated `detect_anomalies` (tool loops, latency spikes, failure bursts, empty turns), and deterministic `diff_flights`.
- [x] Create `src/milyonus/cli/flight_cmd.py` and mount `milyonus flight` (`inspect`, `anomalies`, `diff`).
- [x] Add tenant-isolated Web endpoints in `src/milyonus/web/app.py`: `GET /v1/sessions/{session_id}/flight`, `POST /v1/flights/analyze`, `POST /v1/flights/diff`.

## Milestone H9 — Multi-Model Cost-Latency-Trust Pareto Frontier Router
- [x] Create `src/milyonus/providers/pareto.py`: SQLite bandit telemetry store (`ParetoRouter`), task complexity & risk classifier, exact 3D Pareto frontier solver `(quality, -cost, -latency)`, Beta/UCB scoring, and budget-pressure auto-downgrade with critical safety floor.
- [x] Create `src/milyonus/cli/router_cmd.py` and mount `milyonus router` (`catalog`, `frontier`, `route`, `record`).
- [x] Add tenant-isolated Web endpoints in `src/milyonus/web/app.py`: `GET /v1/router/frontier`, `POST /v1/router/route`, `POST /v1/router/outcome`.

## Milestone H10 — Federated İmece Mesh Protocol (Byzantine Signed Quorum)
- [x] Create `src/milyonus/imece/mesh.py`: signed `milyonus.mesh.v1` envelopes, nonce anti-replay window, SQLite `MeshStore` peer registry, `MeshCoordinator` multi-node dispatch with signature + Proof-Capsule verification, Byzantine reputation slashing, and weighted quorum consensus.
- [x] Create `src/milyonus/cli/mesh_cmd.py` and mount `milyonus mesh` (`peers`, `register`, `dispatch`, `verify-packet`).
- [x] Add tenant-isolated Web endpoints in `src/milyonus/web/app.py`: `GET/POST /v1/mesh/peers`, `DELETE /v1/mesh/peers/{node_id}`, `POST /v1/mesh/dispatch`.

## Milestone H11 — Chaos Autopilot Upgrade, Hypernova Web Command Center, Tests, Docs & Merge
- [x] Upgrade `src/milyonus/security/chaos.py` to **16 probes / 8 vectors** (adding `leases` + `federation` probes: forged lease, canary kill-switch, tampered Merkle disclosure, forged Byzantine mesh packet).
- [x] Build lazy-loaded `web/src/components/HypernovaModal.tsx` (all 10 interactive labs + SVG Graph / Evolution Curve / Pareto Scatter / Mesh Topology) and wire launcher into `Sidebar.tsx`, `store.ts`, and `App.tsx`.
- [x] Create comprehensive test suites:
  - `tests/test_hypernova_core.py` (all 10 core engines + CLI commands + 16/16 Chaos Autopilot).
  - `tests/test_hypernova_web.py` (all 10 Web API families + tenant isolation + fail-closed checks).
- [x] Update `docs/web-api.md`, `CHANGELOG.md`, `README.md`, and mark all checkboxes complete in `PLAN-HYPERNOVA-ACTIONS.md` & `PLAN-HYPERNOVA.md`.
- [x] Run full verification gate (`ruff`, `mypy`, `evals.safety.run`, `milyonus chaos run --min-score 100`, `MILYONUS_TEST_DOCKER=1 uv run pytest -q`, `web/` `npm ci && npm run build`, `uv build`).
- [x] Commit cleanly on `feat/hypernova-ten-capabilities`, push to `origin`, open PR, confirm GitHub Actions CI passes green, and merge into `main`.
