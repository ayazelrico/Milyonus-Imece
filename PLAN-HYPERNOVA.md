# Milyonus-Imece — Hypernova Plan (10 Breakthrough Capabilities)

> Status: **All 10 capabilities (H1–H10) + 16-probe Chaos upgrade implemented and verified in-tree (2026-11-26).**
> Companion action tracker: [PLAN-HYPERNOVA-ACTIONS.md](PLAN-HYPERNOVA-ACTIONS.md).
> Previous milestone plans: [PLAN.md](PLAN.md) · [PLAN-WEB.md](PLAN-WEB.md) · [PLAN-5X.md](PLAN-5X.md) · [PLAN-MOONSHOT.md](PLAN-MOONSHOT.md).
> Owner: @ayazelrico · License: Apache-2.0

---

## 0. Design Thesis

With M1–M5 (Time-Travel Memory, Signed Proof Capsules, Live Web War Room, Adversarial Chaos Autopilot, Skill Forge & Strategy Arena) shipped, Milyonus-Imece already stands alone on verifiable memory and independent multi-agent verification.

**Hypernova (H1–H10)** takes the entire stack into uncharted territory — turning Milyonus-Imece into a **cryptographically governed, self-evolving, branchable, selective-disclosure, federated collective intelligence OS** — while upholding every non-negotiable engineering invariant:

- **Zero fake claims**: Every algorithm, Merkle proof, HMAC/Ed25519 signature, genetic crossover, Pareto frontier, and Byzantine quorum executes real math & real code with deterministic zero-spend verification AND live provider compatibility.
- **Fail-closed security**: Tampered leases, tripped canaries, broken Merkle inclusion paths, forged federation packets, and constitutional violations fail closed by construction.
- **No direct write to active memory**: Even cognitive branch merges flow through the verified pipeline and append to the hash-chained `memory_ledger`.
- **Full-stack parity**: Every capability ships across **Core Python Engine**, **CLI (`milyonus ...`)**, **Tenant-Isolated Web API (`/v1/...`)**, **React SPA Hypernova Command Center**, **Unit/Integration Tests**, and **Chaos Autopilot Probes**.

| # | Capability | One-line Promise | Core Surfaces |
|---|---|---|---|
| **H1** | **Sovereign Epistemic Knowledge Graph & Contradiction Engine** | Project verified memory into a provenance-backed belief graph with automatic contradiction detection, belief PageRank centrality, blast-radius traversal, and Mermaid/DOT/SVG export. | `memory/graph.py` · `milyonus memory graph\|conflicts\|blast-radius` · `/v1/memory/graph\|conflicts` · Web SVG Graph |
| **H2** | **Cryptographic Memory Branching (Git for Agent Brains)** | Fork verified memory into hash-anchored cognitive branches, test hypotheses safely, run 3-way conflict-aware cognitive diffs, and merge back strictly through the trust pipeline. | `memory/branch.py` · `milyonus branch *` · `/v1/memory/branches*` · Web Branch Lab |
| **H3** | **Zero-Trust Capability Leases & Canary Kill-Switch** | Mint HMAC/Ed25519-signed, TTL-bounded, tool/path/domain/call-scoped capability leases plus prompt-injection honeytoken canaries that auto-revoke all leases on exfil. | `security/leases.py` · `milyonus lease *` · `/v1/leases*` · Web Lease Vault |
| **H4** | **IRADE Constitutional Policy Engine & Veto Simulator** | Author hashed/signed governance Constitutions with inviolable hard-veto articles and custom 6-dimension IRADE weight/floor profiles, with live side-by-side counterfactual council simulation. | `imece/constitution.py` · `milyonus constitution *` · `/v1/constitution/*` · Web Policy Workbench |
| **H5** | **Swarm DNA & Evolutionary Strategy Genome** | Evolve agent prompt & collective genomes across generations via tournament selection, elitism, trait crossover, and deterministic fitness oracles — with full SQLite phylogeny. | `imece/evolution.py` · `milyonus evolve *` · `/v1/evolution/*` · Web Evolution Lab |
| **H6** | **Cryptographic Selective Disclosure Merkle Proofs** | Redact proprietary deliverables or PII from `.milyonus-proof.json` while generating genuine Merkle authentication paths proving disclosed gates belong to the exact signed root. | `security/disclosure.py` · `milyonus proof disclose\|verify-disclosure` · `/v1/proofs/disclose\|verify-disclosure` · Web Disclosure Studio |
| **H7** | **Autonomous Self-Healing Skill Immune System** | Seal SHA-256 skill manifests, detect tampering & injection drift, atomically quarantine compromised skills with forensic reports, and auto-heal malformed/leaky `SKILL.md` artifacts. | `skills/immune.py` · `milyonus skills immune *` · `/v1/skills/immune/*` · Web Immune Matrix |
| **H8** | **Flight Recorder: Black-Box Session DVR & Anomaly Detector** | Capture tamper-evident hash-chained execution frames (turns, tools, risk decisions, latency, token spend), auto-detect runaway loops & spikes, and deterministically diff two flights. | `core/flight_recorder.py` · `milyonus flight *` · `/v1/sessions/{id}/flight`, `/v1/flights/*` · Web Flight DVR |
| **H9** | **Multi-Model Cost-Latency-Trust Pareto Frontier Router** | Compute exact mathematical Pareto frontiers over `(quality, -cost, -latency)` with Beta/UCB empirical learning and budget-pressure auto-downgrade that refuses to weaken critical tasks. | `providers/pareto.py` · `milyonus router *` · `/v1/router/*` · Web Pareto Scatter |
| **H10** | **Federated İmece Mesh Protocol (Byzantine Signed Quorum)** | Unite multiple Milyonus nodes via signed `milyonus.mesh.v1` envelopes, nonce anti-replay, Proof-Capsule attestation verification, automatic Byzantine slashing, and reputation-weighted quorum synthesis. | `imece/mesh.py` · `milyonus mesh *` · `/v1/mesh/*` · Web Mesh Topology |

---

## H1. Sovereign Epistemic Knowledge Graph & Contradiction Engine

### Architecture (`src/milyonus/memory/graph.py`)
1. **Belief Graph Builder (`build_epistemic_graph`)**:
   - Reads active/pending/revoked items from `MemoryStore` and constructs typed nodes (`memory`, `source`, `entity`) and directed edges (`derived_from`, `superseded_by`, `sourced_from`, `asserts`, `contradicts`).
   - Deterministic triple extractor parses normalized `(subject, predicate, value, polarity)` assertions (e.g., `deploy region is eu-central-1`, `never use eval`, `always run mypy`, `port = 8080`) with zero external LLM calls.
2. **Contradiction Detector (`detect_contradictions`)**:
   - Spots **polarity inversions** (`always X` vs `never X`, `enable X` vs `disable X`) and **functional value conflicts** (`subject.predicate = A` vs `subject.predicate = B` where `A != B`) across active memories.
   - Scores conflict severity (`high` when involving `T0`/`T1` or security rules, `medium` otherwise) and recommends resolution using higher trust tier & newer verification timestamp.
3. **Centrality & Blast Radius (`blast_radius`, `compute_centrality`)**:
   - Runs iterative damping PageRank over belief dependencies to rank foundational facts.
   - Computes exact BFS downstream blast radius for any item ID or `source_uri`.
4. **Exporters**: `to_mermaid()`, `to_dot()`, and structured JSON (`nodes`, `edges`, `conflicts`, `metrics`) for CLI & Web SVG rendering.

---

## H2. Cryptographic Memory Branching (Git for Agent Brains)

### Architecture (`src/milyonus/memory/branch.py`)
1. **SQLite Schema (`memory_branches`, `memory_branch_items`)**:
   - `memory_branches(name PRIMARY KEY, parent_head, description, created_at, merged_at, branch_hash)`
   - `memory_branch_items(branch_name, item_id, op, content, trust_tier, source_uri, created_at)` where `op` in `{"snapshot", "add", "revoke"}`.
2. **Operations (`MemoryBranchManager`)**:
   - `create_branch(name, description)`: snapshots current active items + `store.ledger_head()` into a content-addressed `branch_hash`.
   - `stage_add(name, content, trust_tier, source_uri)` & `stage_revoke(name, item_id)`: isolates hypotheses on the branch without touching `memory` or `memory_ledger`.
   - `diff_branch(name)`: computes 3-way diff against live `main` memory (`added`, `revoked`, `main_diverged`, `conflicts` via H1 contradiction detector).
   - `merge_branch(name, *, pipeline=None, force=False)`: refuses merge on unresolved contradictions unless `force=True`; routes every added item through `MemoryPipeline` (preserving no-direct-write invariant!) and revokes flagged items through `MemoryStore.revoke()`.

---

## H3. Zero-Trust Capability Leases & Canary Kill-Switch

### Architecture (`src/milyonus/security/leases.py`)
1. **Signed Capability Leases (`CapabilityLease`, `LeaseStore`)**:
   - Schema `milyonus.lease.v1` with `lease_id`, `subject`, `tools`, `path_globs`, `domains`, `max_calls`, `calls_used`, `max_tokens`, `allow_irreversible` (hard-locked `False` unless explicitly authorized with short TTL), `issued_at`, `expires_at`, `revoked_at`, and HMAC-SHA256 signature (keyed by per-vault 256-bit secret persisted at `0o600`).
2. **Zero-Trust Enforcement (`verify_and_consume`)**:
   - Constant-time HMAC verification (`hmac.compare_digest`), expiry check, revocation check, tool allowlist check, fnmatch path jail check, domain allowlist check, irreversible guard, and atomic `calls_used` increment. Fails closed on every violation.
3. **Prompt-Injection Canary Kill-Switch (`mint_canary`, `scan_for_canary_leak`)**:
   - Mints unique cryptographically random honeytokens (`mil_canary_<24hex>`) stored hashed in `lease_canaries`.
   - Scanning any outbound message/tool argument that contains an active canary immediately trips the kill-switch: **revokes ALL active leases in the vault** and logs a forensic `CanaryTripReport`.

---

## H4. IRADE Constitutional Policy Engine & Veto Simulator

### Architecture (`src/milyonus/imece/constitution.py`)
1. **Declarative Constitution Model (`Constitution`, `ConstitutionalArticle`)**:
   - Deterministic canonical SHA-256 `constitution_hash` covering `name`, `version`, `weights` (6 IRADE dimensions normalized to sum 1.0), `veto_floors`, `hard_veto_floor`, `escalate_tier4_below_safety`, and ordered `articles` (pattern/keyword/predicate hard-veto laws).
   - Ships with 4 audited presets: `balanced-default`, `fortress-security`, `finops-strict`, `rapid-research`.
2. **Article Evaluation (`evaluate_text`, `evaluate_decision`)**:
   - Evaluates any candidate option summary/evidence or tool payload against all articles, emitting structured `ArticleViolation` records and computing weighted IRADE totals + veto floor enforcement.
3. **Counterfactual Multi-Profile Simulator (`simulate_constitutions`)**:
   - Takes a scenario (options + 6-dimension member scores) and simulates all selected Constitutions side-by-side — surfacing where verdicts flip, which options get vetoed, and when Tier 4 human escalation triggers.

---

## H5. Swarm DNA & Evolutionary Strategy Genome

### Architecture (`src/milyonus/imece/evolution.py`)
1. **Structured Genome (`SwarmGenome`)**:
   - Genes: `system_style`, `temperature`, `verification_bias`, `decomposition_depth`, `red_team_intensity`, `scale_agents`, `traits` (curated pool of verifiable engineering directives).
   - Content-addressed `genome_id` + `parent_ids` + `generation` + `mutations`.
2. **Evolutionary Engine (`EvolutionEngine` + `EvolutionStore`)**:
   - Deterministic seeded PRNG (`random.Random(seed)`), tournament selection (`k=3`), top-2 elitism, uniform crossover of genes & trait sets, bounded numeric/categorical mutation.
   - Objective multi-criteria fitness function scoring correctness, safety adherence, verification rigor, conciseness, and token efficiency (supports both custom async/sync oracles and built-in deterministic task evaluator).
   - Persists runs & generation curves in SQLite (`evolution_runs`, `evolution_genomes`) and supports exporting the champion genome directly into a `SkillForgeSpec`!

---

## H6. Cryptographic Selective Disclosure Merkle Proofs

### Architecture (`src/milyonus/security/disclosure.py`)
1. **Binary Merkle Inclusion Proof Builder (`build_merkle_proof`, `create_disclosure_proof`)**:
   - Builds the exact same sorted-leaf binary SHA-256 Merkle tree as `security/proof.py` (`merkle_root`), recording sibling hashes & `left|right` orientation along the path from each disclosed leaf up to the root.
   - Emits `milyonus.disclosure.v1` containing ONLY the selected `disclosed_claims` (each paired with its `merkle_path`), `blinded_count`, `total_claims`, `merkle_root`, `subject_id`, `memory_anchor`, and optional `source_bundle_sha256` / `signature`.
2. **Offline Fail-Closed Verifier (`verify_disclosure_proof`)**:
   - Recomputes each disclosed claim's canonical leaf SHA-256, walks its Merkle authentication path step-by-step to verify it equals `merkle_root`, rejects duplicate/forged paths, and optionally verifies the Ed25519 signature over `source_bundle_sha256` — guaranteeing zero leakage of blinded claims!

---

## H7. Autonomous Self-Healing Skill Immune System

### Architecture (`src/milyonus/skills/immune.py`)
1. **Baseline Manifest Sealing (`seal_manifest`)**:
   - Computes SHA-256 digests over every installed `SKILL.md` in `skills_dir` and writes `.immune-manifest.json` (`0o600`).
2. **Immune Audit (`scan_skills_health`)**:
   - Classifies every skill as `healthy`, `warn`, `tampered`, or `compromised`:
     - Hash drift vs sealed manifest,
     - `skills.scanner.scan_skill` findings (`danger` → `compromised`),
     - Frontmatter/schema validation & embedded secret leak check (`security.redact`),
     - Duplicate trigger/name collision detection.
3. **Quarantine & Auto-Heal (`quarantine_skill`, `heal_skill`)**:
   - Atomically moves compromised skills to `<skills_dir>/.quarantine/<name>-<ts>/` with a JSON incident dossier.
   - Auto-heal repairs missing/broken YAML frontmatter, redacts accidental secret literals, strips unsafe patterns when cleanable (refusing fail-closed if irreversible RCE remains), re-scans to confirm 0 `danger` findings, and updates the manifest digest.

---

## H8. Flight Recorder: Black-Box Session DVR & Anomaly Detector

### Architecture (`src/milyonus/core/flight_recorder.py`)
1. **Hash-Chained Flight Envelope (`FlightRecording`, `FlightFrame`)**:
   - Schema `milyonus.flight.v1`: every frame carries monotonic `seq`, `ts`, `kind`, `label`, redacted `data`, `tokens_delta`, `latency_ms`, `prev_hash`, `frame_hash` (`SHA-256`), plus `verify_flight()` tamper detection.
   - `record_from_session(session_id, messages, tool_results, memory_store)` constructs a complete black-box DVR from live Web/CLI session stores.
2. **Automated Anomaly Detector (`detect_anomalies`)**:
   - Flags: `tool_loop` (≥3 identical consecutive tool calls), `latency_spike` (frame latency > 3× median and ≥500ms), `tool_failure_burst`, `security_block`, `empty_assistant_turn`, and `chain_tamper`.
3. **Flight Diff (`diff_flights`)**:
   - Compares two recordings frame-by-frame to identify `first_divergence_seq`, delta tokens, delta latency, and added/changed tool invocations.

---

## H9. Multi-Model Cost-Latency-Trust Pareto Frontier Router

### Architecture (`src/milyonus/providers/pareto.py`)
1. **Model Telemetry Catalog & SQLite Bandit Store (`ParetoRouter`)**:
   - Pre-seeded with realistic reference profiles across tiers (local small, fast cloud, balanced flagship, deep reasoning frontier) + custom model registration.
   - Persists per-model empirical `(successes, failures, latency_ema_ms, cost_total_usd)` in SQLite `pareto_stats`.
2. **Exact Pareto Frontier (`compute_pareto_frontier`)**:
   - Filters models meeting hard constraints (`max_cost_per_1m`, `max_latency_ms`, `min_quality`, `require_local`), then eliminates strictly dominated points on `(effective_quality, -cost_per_1m, -effective_latency_ms)`.
3. **Complexity- & Budget-Aware Routing (`route_task`)**:
   - Classifies task complexity `0.0–1.0` and risk tier (`low|medium|high|critical`) deterministically.
   - Combines Beta posterior quality + UCB exploration bonus + budget pressure penalty — auto-downgrading low-risk work under high budget pressure while enforcing a strict quality floor (`>=0.85`) for `high`/`critical` security tasks!

---

## H10. Federated İmece Mesh Protocol (Byzantine Signed Quorum)

### Architecture (`src/milyonus/imece/mesh.py`)
1. **Protocol & Signed Packets (`MeshPacket`, `sign_packet`, `verify_packet`)**:
   - Schema `milyonus.mesh.v1` with `packet_id`, `kind`, `sender_id`, `nonce`, `timestamp`, `payload`, `payload_sha256`, and HMAC-SHA256 / Ed25519 signature.
   - Anti-replay cache rejects reused nonces and stale timestamps (`>300s` skew).
2. **Peer Registry & Byzantine Slashing (`MeshStore`, `MeshCoordinator`)**:
   - Persists peers (`node_id`, `role`, `endpoint`, `shared_secret_hash`, `reputation`, `slashed_count`, `verified_tasks`) and dispatch logs in SQLite.
   - Dispatches tasks across active peers (local deterministic worker handlers or pluggable async transport), verifies every returned packet signature AND optional attached `.milyonus-proof.json` Merkle root (`verify_proof`).
   - Any forged signature, tampered payload hash, invalid proof capsule, or nonce replay triggers **fail-closed rejection + automatic Byzantine reputation slash** (`-0.35` per offense; quarantined below `0.25`).
   - Synthesizes final consensus answer via reputation-weighted quorum vote!

---

## H11. Chaos Autopilot Upgrade, Tests, Web Command Center & CI Gate

1. **Chaos Autopilot Upgrade (`security/chaos.py`)**:
   - Expands from **12 probes / 6 vectors** → **16 probes / 8 vectors** by adding:
     - `leases`: forged Capability Lease signature rejection + Honeytoken Canary global kill-switch auto-revocation.
     - `federation`: tampered Selective Disclosure Merkle path rejection + Byzantine forged Mesh Packet rejection & slashing.
2. **Hypernova Command Center (`web/src/components/HypernovaModal.tsx`)**:
   - Lazy-loaded (`React.lazy`) 10-module tabbed command center accessible from the Sidebar (`✦ Hypernova Lab`), styled seamlessly in Milyonus dark-glass + brand cyan/blue tokens, with custom inline SVG visualizations (Epistemic Knowledge Graph, Swarm DNA Fitness Curve, Pareto Frontier Scatter Plot, Federated Mesh Topology) and zero >500 kB Vite chunks.
3. **Verification & Merge Gate**:
   - `uv run ruff check src tests evals` & `uv run ruff format --check src tests evals` — **0 errors**
   - `uv run mypy src/milyonus` — **0 errors**
   - `uv run python -m evals.safety.run` — **0 findings**
   - `uv run milyonus chaos run --min-score 100` — **100/100 (16/16 · A+)**
   - `MILYONUS_TEST_DOCKER=1 uv run pytest -q` — **100% pass**
   - `cd web && npm ci && npm run build` — **0 TS errors, all chunks <500 kB**
   - `uv build` — clean wheel + sdist
   - GitHub Actions CI (`test` + `web-build`) — **100% green**, PR merged into `main`.
