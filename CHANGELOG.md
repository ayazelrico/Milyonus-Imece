# Changelog

All notable changes to Milyonus Agent are documented here.
The format follows Keep a Changelog; versions follow the Milyonus model line.

## [Unreleased] — Milyonus-Imece (experimental)

### Plans closed in code — 2026-11-03
- Shell sandbox backends: `ssh`, `modal`, and `daytona` alongside local/docker;
  missing credentials fail closed with no host-shell fallback.
- Hermes like-for-like adapter: `python -m evals.hermes.adapter` (prepare/run)
  against the frozen 50-task suite for `evals.imece.compare`.
- Web surface #7: `milyonus web start`, `src/milyonus/web/` (auth, SSE turns,
  approvals, memory/audit APIs, tenant dirs) and `web/` Vite SPA (chat, tool
  timeline, approval cards, trust rail). Docs: `docs/web-api.md`, ADR-0010/0011.
- PLAN-5X measurement ground and adapters are in-tree; measured 5X acceptance
  still requires paid baseline runs + independent audit attestation.

### Completion and hardening — 2026-11-02
- Real isolated Python tests (Docker and macOS development backend), exact test
  accounting, fail-closed reviewers, re-testing revised/polished artifacts and
  strict explicit-majority approval.
- Bounded command cells, layered councils and bounded worker scheduling; gate
  evidence remains visible when option text is clipped.
- `imece benchmark` with a withheld reference oracle and separate acceptance,
  verified success, tokens, price estimates and calibration metrics.
- First accepted real-model `clamp` result, independently reference-checked;
  failed and stopped trials retained alongside it. The system remains experimental.
- Default-deny core approvals, hard RiskEngine enforcement, ACP permissions and
  cancellation, Docker shell wiring, source-bound memory corroboration and
  independent model verification shared by CLI/gateway/ACP.
- Real skill replay gate; self-edit snapshot/test/doctor/rollback wiring and
  explicit startup acknowledgement of tested core changes.
- Evidence and remaining limits: `docs/completion.md`; next plan: `PLAN-5X.md`.

### Added — the İmece-İRADE collective (`milyonus imece`)
- `imece/scale.py`: the 10,000-agent reference distribution scaled to any size
  (17 … 100,000) with per-block floors and largest-remainder allocation;
  flexible / independent / fixed blocks; swarming loans between flexible blocks only.
- `imece/agents.py`: `Swarm` — concurrent subagents (`max_parallel`) on one shared
  token pool; one failed agent never sinks a phase; empty replies count as failures;
  workers get `safe` tools only (opt-in `web_fetch`).
- `imece/gates.py`: Kapı 1 independent framing with frozen criteria and surfaced
  divergences; Kapı 2 independent test design + execution, red team, evidence
  audit, compliance; Kapı 3 blind approval.
- `imece/irade.py`: 5-perspective council, 6 scoring dimensions, veto floors on
  safety/legal/reversibility, Kademe 0–4 routing, quorum and abstention, JEV
  precedent, random audit of low tiers, confidence calibration from Kapı 3 outcomes.
- `imece/observer.py`: groupthink, approach collapse, council bottleneck, agent
  failures, budget pressure and no-progress monitors, plus an LLM retrospective.
- `imece/orchestrator.py`: the full multi-round pipeline with human stop checkpoints
  and a JSON run report.
- CLI: `milyonus imece plan | seats | run | stop`; `[imece]` config section with
  per-seat models.

### Fixed (found by real-model trial runs)
- OpenAI-compatible provider reported token usage before the usage chunk arrived,
  undercounting budgets; usage is now emitted after the stream ends.
- New `provider.reasoning_effort` so reasoning models cannot spend the entire
  output budget on hidden reasoning and return an empty answer.

## [5.5.0] — 2026-08-26

First public release of the Milyonus Agent 5.5 line.

### Core
- Provider-agnostic agent loop (streaming, interruptible, budgeted) with
  Anthropic (default), OpenAI, OpenRouter, and local (Ollama/vLLM) backends.
- SQLite (WAL + FTS5) session store; interactive terminal UI.

### Verified memory (the differentiator)
- Ingest → Quarantine → Verify → Promote pipeline; no direct-write path.
- Trust tiers T0–T4, provenance on every line, hash-chained audit ledger,
  cascade revocation, negative memory + rephrase detection.
- Separate verifier model; sleep-time consolidation.
- PoisonBench: 0% ASR / 0% RSR on a 45-case corpus.

### Skills
- Agent-authored skills gated by a reproducibility check + security scanner.
- 26 official bundled skills (agentskills.io-compatible,
  `milyonusagentskill` namespace).

### Security
- Risk-tiered approval; always-on SSRF; credential redaction; pre-exec command
  scanning; context-file injection scanning; DM pairing with lockout.

### Channels
- Telegram, WhatsApp (Cloud API), Slack (Events API), Discord (Gateway).
- Shared gateway core with default-deny, in-chat approval, auto-reconnect.

### Extension
- Self-modification harness (git snapshot + test gate + rollback), subagent
  delegation with a context contract, minimal MCP client.

### Deploy
- Hardened Docker image, compose, installer, systemd unit.
