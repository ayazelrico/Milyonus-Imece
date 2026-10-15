<div align="center">

<img src="assets/brand/milyonus-wordmark.png" width="660" alt="Milyonus"/>

### ✦ Milyonus-Imece — *Labor in the imece. Speed in IRADE. Truth at the gates.*

An open-source **multi-agent collective** built on the Milyonus verified-memory agent.
One command sends a task through **tens to thousands of real subagents**, a
**five-model IRADE council**, and **three independent gates** — so that
*no layer ever has to catch its own errors.*

[![CI](https://github.com/ayazelrico/Milyonus-Imece/actions/workflows/ci.yml/badge.svg)](https://github.com/ayazelrico/Milyonus-Imece/actions)
[![License](https://img.shields.io/badge/license-Apache--2.0-1E4FD8.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.12%2B-35C6F4.svg)](pyproject.toml)
[![Version](https://img.shields.io/badge/version-5.5.0-071233.svg)](CHANGELOG.md)
[![Tests](https://img.shields.io/badge/tests-306%20passing-22C55E.svg)](tests)
[![Imece](https://img.shields.io/badge/imece-experimental-F59E0B.svg)](#status--honest-trial-results)
[![PoisonBench](https://img.shields.io/badge/PoisonBench%20ASR-0%25-22C55E.svg)](docs/benchmarks.md)

</div>

> **Status: experimental.** The İmece-İRADE pipeline is fully implemented and
> covered by 35 dedicated tests (306 in the whole suite), and it has been run
> end-to-end against real models. Those real-model trial runs have **not yet
> produced an accepted deliverable** — they surfaced several real-world bugs that
> are now fixed, and the gates correctly refused a broken deliverable. Read
> [Status & honest trial results](#status--honest-trial-results) before relying on it.

---

## Table of contents

**Milyonus-Imece**

- [The idea in one paragraph](#the-idea-in-one-paragraph)
- [Why functions, not teams](#why-functions-not-teams)
- [Architecture](#architecture)
- [Quick start](#quick-start)
- [Scaling: from 17 to 10,000 subagents](#scaling-from-17-to-10000-subagents)
- [The 16 functions](#the-16-functions)
- [The pipeline, step by step](#the-pipeline-step-by-step)
- [IRADE — the decision council](#irade--the-decision-council)
- [The three independent gates](#the-three-independent-gates)
- [The process observer](#the-process-observer)
- [Human oversight](#human-oversight)
- [Worker safety: what subagents may touch](#worker-safety-what-subagents-may-touch)
- [The seven guarantees, mapped to code](#the-seven-guarantees-mapped-to-code)
- [Configuration reference](#configuration-reference)
- [Choosing models (and the reasoning-model trap)](#choosing-models-and-the-reasoning-model-trap)
- [Cost and budget](#cost-and-budget)
- [The run report](#the-run-report)
- [Status & honest trial results](#status--honest-trial-results)
- [Known limitations and open risks](#known-limitations-and-open-risks)
- [Testing the collective without spending tokens](#testing-the-collective-without-spending-tokens)
- [Code map](#code-map)

**The Milyonus platform underneath**

- [Why Milyonus](#why-milyonus)
- [Talk to it from anywhere](#talk-to-it-from-anywhere)
- [Verified memory — the core idea](#-verified-memory--the-core-idea)
- [Memory as a security boundary](#-memory-as-a-security-boundary)
- [Skills — procedural memory](#-skills--procedural-memory)
- [Security model](#-security-model)
- [Self-modification](#-self-modification)
- [Connecting MCP servers](#-connecting-mcp-servers)
- [Cross-session user model](#-cross-session-user-model)
- [Platform architecture](#platform-architecture)
- [Benchmarks](#benchmarks)
- [CLI reference](#cli-reference)
- [Deployment](#deployment)
- [Development](#development)
- [Roadmap](#roadmap)
- [License &amp; trademark](#license--trademark)

---

# Milyonus-Imece

## The idea in one paragraph

*İmece* is the Anatolian tradition of a whole village working together on one
job. Milyonus-Imece applies it to AI agents: a large pool of subagents does the
**labor** (research, planning, building, running tests, integrating), a small
council of five models called **IRADE** (*will, resolve*) makes the **decisions**
fast, and three **independent gates** guard **correctness**. The three never do
each other's job. The question is challenged independently (Kapı 1), the answer
is built by the imece, decisions are sped up by tiered IRADE, the result is
tested against reality (Kapı 2), and it is approved by someone who never saw the
process (Kapı 3). *Kapı* means *gate*.

## Why functions, not teams

The design starts from one thesis:

> For a collective of 10,000, **teams are not mandatory — the functions they
> perform are.** Teams can merge or close, but if any one of the functions below
> is missing, the system goes blind to a specific kind of error.

Every function carries one of three labels, and the code enforces them:

| Label | Meaning | In code |
|---|---|---|
| 🔴 **Mandatory** | Without it the system cannot produce a trustworthy result | Floor ≥ 1 agent at every scale |
| 🟠 **Conditional** | Needed depending on the problem | Floor 0 (red team is the exception: floor 1, because hard tasks are high-risk) |
| 🟡 **Scale-mandatory** | Optional in a small team, required at 10,000 | Gets agents as the run grows |

The biggest risk on hard problems is not solving the problem badly — it is
solving **the wrong problem**. A wrong framing wastes the labor of every agent
downstream. That is why framing is a gate, outside the imece, and why its
success criteria are frozen before anyone builds anything.

---

## Architecture

```
 HUMAN OVERSIGHT  (stop authority · last word on irreversible decisions)
        │
 ┌──────▼───────┐
 │   KAPI 1     │  Independent framing — ≥5 cells, outside the imece
 └──────┬───────┘
        │  frozen problem + success criteria (also copied to Kapı 3)
 ┌──────▼──────────────────────────────────────────────────────┐
 │  İMECE LABOR POOL  (flexible roles, swarming)                │
 │  recon · domain experts · plans · approach clusters ·        │
 │  production (wire off) · test runs · integration · polish    │
 └──────┬─────────────────────────────▲────────────────────────┘
        │ decision packets             │ decisions
 ┌──────▼─────────────────────────────┴────────────────────────┐
 │  IRADE COUNCIL  (5 models, 5 vendors, 5 fixed perspectives)  │
 │  multi-dimension scores + veto floors · Kademe 0 → 4         │
 └──────┬──────────────────────────────────────────────────────┘
        │ candidate + evidence
 ┌──────▼───────┐
 │   KAPI 2     │  Reality: independently designed tests · red team ·
 │              │  evidence audit · compliance
 └──────┬───────┘
 ┌──────▼───────┐
 │   KAPI 3     │  Onay Merci — blind approval on different models
 └──────┬───────┘
        ▼  deliverable   (a rejection feeds the next round)

 side system: PROCESS OBSERVER — watches every layer, never the answer
```

**The formula:** labor in the imece, speed in IRADE, correctness at the
independent gates. No layer has to catch its own mistakes on its own.

---

## Quick start

```bash
# 1. install uv  (https://astral.sh/uv)
curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. get the code
git clone https://github.com/ayazelrico/Milyonus-Imece.git
cd Milyonus-Imece
uv sync --extra openai --extra anthropic

# 3. add a key (Anthropic, OpenAI, or OpenRouter)
mkdir -p ~/.milyonus
echo 'OPENROUTER_API_KEY=sk-or-...' >> ~/.milyonus/.env && chmod 600 ~/.milyonus/.env

# 4. look before you spend
uv run milyonus imece plan -n 120     # how 120 agents are distributed — no model calls
uv run milyonus imece seats           # which model sits in which seat + independence warnings

# 5. run
uv run milyonus imece run "Design a rate limiter for a public REST API" -n 120 -p 8
```

All imece commands:

```
milyonus imece plan  [-n N]                 show the block distribution (free, no calls)
milyonus imece seats                        seat → model map, independence warnings
milyonus imece run "<task>" [options]       run the full pipeline
    -n, --agents N        total subagents (≥ 17; default from config: 120)
    -p, --parallel P      concurrent subagents (default 8)
    --rounds R            max rounds (default 2)
    --max-tokens T        shared token pool for the whole run (default 2,000,000)
    -y, --yes             skip the cost confirmation
    --out FILE            write the deliverable to a file
milyonus imece stop                         human stop: halt before the next phase
```

Exit codes: `0` accepted by Kapı 3 · `2` not accepted (rejected / stopped /
budget) · `1` configuration error · `130` interrupted.

---

## Scaling: from 17 to 10,000 subagents

**10,000 is a reference number, not a requirement.** You choose the total with
`-n`. Each block receives a share proportional to its weight in the
10,000-agent reference distribution, but never less than its *floor*, so no
🔴 function ever drops to zero. The five IRADE council members sit **outside**
this total.

**The algorithm** (`imece/scale.py`, `allocate`):

1. Give every block its floor (framing 5, production 2, approval 1, every other
   🔴 block 1, red team 1, observer 1). The floors sum to **17** — the smallest
   legal run.
2. Compute each block's ideal share `N × weight / 10,000` and how far it sits
   above its floor.
3. Distribute the remaining agents in proportion to those gaps with the
   **largest-remainder method**, so counts are integers that sum to exactly `N`.

At `N = 10,000` the result reproduces the reference table exactly (this is a
test). Examples:

| Block | Kind | Label | 10,000 | 17 | 24 | 120 | 500 |
|---|---|---|---:|---:|---:|---:|---:|
| İmece production pool | flexible | 🔴 | 4,500 | 2 | 6 | 52 | 225 |
| Domain experts | flexible | 🟠 | 1,000 | 0 | 1 | 12 | 50 |
| Test design | **independent** | 🔴 | 400 | 1 | 1 | 5 | 20 |
| Test execution | flexible | 🔴 | 1,100 | 1 | 2 | 13 | 55 |
| Recon / intelligence | flexible | 🔴 | 700 | 1 | 2 | 8 | 35 |
| Red team | **independent** | 🟠→🔴 | 400 | 1 | 1 | 5 | 20 |
| Plan | flexible | 🔴 | 400 | 1 | 1 | 5 | 20 |
| Command & operations | fixed | 🔴 | 300 | 1 | 1 | 3 | 15 |
| Integration | flexible | 🔴 | 300 | 1 | 1 | 3 | 15 |
| Evidence audit | **independent** | 🔴 | 300 | 1 | 1 | 3 | 15 |
| Framing (Kapı 1) | **independent** | 🔴 | 150 | 5 | 5 | 5 | 8 |
| Compliance (ethics/law/safety) | **independent** | 🟠 | 100 | 0 | 0 | 1 | 5 |
| Polish & delivery | flexible | 🟠 | 100 | 0 | 0 | 1 | 5 |
| Process observer | **independent** | 🟡 | 100 | 1 | 1 | 1 | 5 |
| Onay Merci (Kapı 3) | **independent** | 🔴 | 50 | 1 | 1 | 1 | 3 |
| Human interface | fixed | 🟡 | 50 | 0 | 0 | 1 | 2 |
| Exploration / high-risk research | flexible | 🟠 | 50 | 0 | 0 | 1 | 2 |
| **IRADE council (outside the total)** | — | — | +5 | +5 | +5 | +5 | +5 |

### Three kinds of block

| Kind | Rule |
|---|---|
| **flexible** | The imece pool. Idle agents may temporarily **swarm** into another flexible block (for example, builders moving into test execution once production is done). |
| **independent** | Must stay independent of the producers. **Never lends, never borrows.** Framing, test design, red team, evidence audit, compliance, observer, approval. |
| **fixed** | Neither independent nor pooled: command, human interface. |

Swarming is recorded as a ledger of *loans* on the `Allocation`. Any attempt to
move an agent into or out of an independent block raises `ScaleError` — the rule
lives in code, not in a prompt.

Swarming happens in two places today:

- **Test-execution surge:** in Kapı 2, if there are more candidates than
  test-execution agents, idle builders are borrowed into test execution.
- **Integration bottleneck:** integrity checking borrows idle builders when the
  integration block is too small for the number of candidates being merged.

Loans are released at the end of each phase.

---

## The 16 functions

Each function from the design, what it does, and where it lives:

| # | Function | Label | What the subagents do | Code |
|---|---|---|---|---|
| 1 | Command & operations | 🔴 | Decompose the selected plan into genuinely different **approach clusters** (forced diversity) | `orchestrator._approaches` |
| 2 | Recon | 🔴 | Requirements, current-state inventory, **prior failed attempts**, literature, constraint map, unknowns — every item tagged with its reliability | `orchestrator._recon` |
| 3 | Problem framing | 🔴 | Five lenses re-frame the problem independently; a synthesizer surfaces disagreements and freezes the criteria | `gates.frame` |
| 4 | Analysis & plan | 🔴 | Independent plans with a **pre-mortem**, cost/time/risk, early-failure signals, Plan B; IRADE picks one | `orchestrator._plan` |
| 5 | Domain experts | 🟠 | One brief per discipline named by the framing, translated for other disciplines | `orchestrator._experts` |
| 6 | Production (builders) | 🔴 | Independent candidates, **wire off** (no builder sees another), one approach each, in a fixed format | `orchestrator._produce` |
| 7 | Red team | 🟠→🔴 | Edge cases, overload, misuse, adversarial input, "what if an assumption is false" — each with a reproduction | `gates.reality` |
| 8 | Test / verification | 🔴 | Test **design** (independent, from the frame only) and test **execution** (flexible) | `gates.design_tests`, `gates.reality` |
| 9 | Evidence audit | 🔴 | Sourcing, numeric consistency, hallucination hunt, evidence-quality classification | `gates.reality`, `orchestrator._extra_evidence` |
| 10 | Compliance | 🟠 | Legal limits, ethical impact, privacy, dual use, **flags irreversible actions** | `gates.reality` |
| 11 | Veto-assembly | 🟡 | Realised as the IRADE council with veto floors | `imece/irade.py` |
| 12 | Synthesis / integration | 🔴 | Merge the IRADE-chosen primary with better parts of others; integrity checks; fix pass | `orchestrator._integrate` |
| 13 | Polish & delivery | 🟠 | Simplify, document, add a *Limitations* section — without changing substance | `orchestrator._polish` |
| 14 | Onay Merci (approval) | 🔴 | Blind final approval | `gates.approve` |
| 15 | Process observer | 🟡 | Deterministic monitors + an LLM retrospective on the process | `imece/observer.py` |
| 16 | Backup / redundancy | 🟡 | Built in rather than a team: a failed agent never sinks a phase; failures are counted per block | `agents.Swarm` |

---

## The pipeline, step by step

A run is `Imece.run(task)` in `imece/orchestrator.py`. Every phase boundary is
also a **stop checkpoint** for the human.

**Kapı 1 — independent framing.**
`framing` agents (at least 5) each re-formulate the problem alone, through one
of five lenses: *literal*, *root cause (real problem or symptom?)*, *user
outcome*, *constraints & risk*, *minimal scope*. A synthesizer merges them and is
instructed to **surface every real disagreement instead of hiding it**. The
output is a frozen `Frame`: problem, success criteria, out-of-scope list,
assumption register ("if this one is wrong, everything collapses"), needed
disciplines, and the divergences between cells. The criteria are copied to
Kapı 3 so the process cannot move the goalposts later.

**Recon + domain experts (in parallel).**
Recon agents cycle through six facets: requirements & stakeholders, current-state
inventory, previous failed attempts, literature, constraint map, unknowns. Each
item carries a reliability tag (*measured / observed / expert opinion /
inference*). Experts are assigned round-robin to the disciplines the framing
asked for.

**Planning (IRADE selects).**
Every `plan` agent writes an independent plan with steps, a pre-mortem, a
cost/time/risk estimate, early-failure signals and a Plan B with its switch
condition. Duplicate titles are dropped and the rest (up to `max_options`) go to
IRADE as a high-impact decision. From round 2 onward the planners also see why
the previous round was rejected.

**Approach clusters (command).**
Command agents define up to `max_clusters` (default 9) approach clusters with a
hard rule: no two clusters may share a core idea. If they return fewer than two,
fallback clusters (*direct*, *first-principles*, *conservative*) guarantee
diversity.

**Independent production ∥ independent test design.**
Builders are assigned round-robin to the clusters and work alone: no builder
ever sees another builder's output. Exploration agents ignore the plan on purpose
and propose the most unconventional approach that could still meet the criteria.
**At the same time**, test designers build the test oracle from the frame
alone: what "correct" means, how to check it, edge cases, and at least one test
that catches a solution which only *looks* right.

**Kapı 2 — reality filter.**
Every candidate faces test execution, red team, evidence audit and (if staffed)
compliance. A candidate passes only if its test pass rate is at least
`pass_threshold` **and** it has no critical finding. **A candidate that fails
never reaches IRADE** — reality is the referee, not the council.

**Shortlist.**
Survivors are ranked by pass rate, with one rule: the best candidate of each
approach is admitted first, so the shortlist keeps approach diversity before
it adds a second candidate from any approach.

**Cross-critique by rotation + evolutionary revision.**
Every shortlisted candidate is critiqued by a builder from a **different**
approach — nobody critiques their own work. The author then revises it: fixing
valid criticism and adopting strictly better ideas from another candidate
(crossover).

**IRADE synthesis decision.**
The council chooses the primary basis of the deliverable. Each option carries
its Kapı 2 evidence. If compliance (or any high/critical finding) flagged the
need for human approval, the decision is marked **irreversible** and goes to the
human (Kademe 4). In round 2 and later the decision is treated as *strategic*.

**Integration + system re-test.**
A lead integrator builds the deliverable from the primary and takes parts from
the others only when they are clearly better *and* fit the interfaces.
Integrity checkers — reinforced by idle builders — look for interface
mismatches, contradictions and gaps. If they find any, a fix pass follows. The
integrated deliverable then goes through Kapı 2 **again** at system level,
because parts that are correct one by one often fail when combined.

**Polish → Kapı 3 → accept, or round 2.**
Polish packages the result without changing its substance. Kapı 3 approves or
rejects **blind**. On rejection, the reasons and unmet criteria feed the next
round's planners and builders. The framing and the test oracle are kept: the
question and the definition of "correct" do not drift between rounds.

---

## IRADE — the decision council

### Members

Five members, each locked to one perspective. Each can sit on its own seat
(`council_<perspective>`) and therefore on a **different vendor's model**, to
lower the correlation (ρ) of their errors:

| Seat | Perspective |
|---|---|
| `council_correctness` | Does it actually solve the framed problem, provably? |
| `council_risk` | What can go wrong, who gets hurt, what cannot be undone? |
| `council_user_impact` | Does it serve the person who asked, in practice? |
| `council_cost_speed` | What does it cost in time, money and complexity? |
| `council_devils_advocate` | Argue against the favourite; find why it fails. |

### Scoring: many dimensions, never one number

Every member scores **every option** from 0 to 1 on six dimensions:
`correctness · safety · reversibility · legal · cost · speed`.

### Veto floors

`safety`, `legal` and `reversibility` are veto dimensions. An option is
**vetoed, whatever its total**, if:

- the council's **mean** on any veto dimension is below `veto_floor` (default 0.5), or
- **any single member** scores it below `hard_veto_floor` (default 0.2).

An average must never hide a single critical flaw.

### Kademe — decision tiers

| Kademe | Decision owner | Condition | Target share |
|---|---|---|---|
| **0** | Policy | Reversible, low impact, known kind of decision | ~95% |
| **1** | JEV precedent | Same decision seen before with confidence ≥ 0.8 | ~4% |
| **2** | Fast path: 3 of 5 (correctness, risk, devil's advocate) | High impact; accepted only if they agree and nothing blocks | ~0.9% |
| **3** | Full council of 5 + **extra evidence from Kapı 2** | Strategic, uncertain, or the fast path disagreed | ~0.09% |
| **4** | **Human** | Irreversible, or the full council still cannot agree | ~0.01% |

### Escalation triggers

A decision climbs a tier on any of these:

- **Low confidence** — mean confidence below `0.55`.
- **Disagreement** — the standard deviation of member totals for the winner
  exceeds `spread_threshold` (0.15), or the winner's vote share is below 0.6.
- **Irreversibility** — goes straight to Kademe 4.
- **Novel decision kind** — no precedent; even low-impact decisions start at Kademe 2.
- **Veto** — every option vetoed, or members preferred an option that got vetoed.
- **No quorum** — see the next section.

From Kademe 3 the thresholds are applied 1.5× more strictly before the
decision is handed to the human. Disagreement between models is treated as a
**signal**, not as noise to be averaged away.

### Quorum and abstention

A member whose reply cannot be read, or that does not score every option on
every dimension, **abstains**. It is never counted as zeros. Counting it as
zeros would let one broken reply veto every option — a bug the real trial runs
exposed (see below). The fast path needs 2 readable votes and the full council
needs 3. Without quorum the decision escalates instead of being decided.

### Precedent (JEV)

Every decided `(kind, question)` is stored with its confidence. When the same
decision comes back with confidence ≥ `precedent_confidence` (0.8), the
precedent answers it at Kademe 1 without convening the council.

### Random audit (guarantee #6)

A share of Kademe 0–1 decisions (`audit_rate`, default 5%) is re-run through the
fast-path council. The decision records whether the council `agrees` or chose
something else, so drift in policy and precedent can be measured.

### Calibration

"When they said 80%, how often were they right?" After Kapı 3 rules, every
Kademe ≥ 2 decision of that round is logged as *(stated confidence, accepted?)*
in `~/.milyonus/imece/calibration.jsonl`. Once a 0.1-wide confidence bucket has
at least 5 samples, a stated confidence in that bucket is replaced by the
bucket's real hit rate.

### Goodhart guard

Option text shown to the council is clipped to a fixed length
(`OPTION_CHARS = 1200`) and wrapped in a fixed packet template, so producers
cannot win by padding their decision packet. Scores come from the council, never
from the producer.

---

## The three independent gates

### Kapı 1 — framing (`gates.frame`)

- Each framing cell sees **only the original request** — never another cell's
  framing.
- A synthesizer merges them and records the **divergences** explicitly.
- The success criteria are frozen into an immutable `Frame` (a frozen
  dataclass). The same criteria are what Kapı 3 judges against.

### Kapı 2 — reality (`gates.design_tests`, `gates.reality`)

- **Test design never sees a candidate.** `design_tests` takes only the frame,
  so the oracle cannot be shaped around a solution. Tests are deduplicated and
  capped at 12. If no test can be parsed, the success criteria themselves become
  the tests.
- **Test execution** runs every test against every assigned candidate and
  returns per-test pass/fail.
- **Red team**, **evidence audit** and **compliance** return findings with a
  severity (`low · medium · high · critical`) and a `needs_human` flag.
- `needs_human` is honored only when it comes from **compliance** (whose job it
  is) or from a **high/critical** finding. A low-severity aside from any
  reviewer cannot halt a whole run.
- Work is spread with `assign(n_agents, items)`: more agents than candidates
  means several **independent repeats** per candidate; fewer means each agent
  takes several candidates.
- **Pass rule:** `pass_rate ≥ pass_threshold` and no critical finding.

### Kapı 3 — Onay Merci (`gates.approve`)

Its function signature *is* the guarantee: `approve(request, criteria,
deliverable, evidence, n_agents)`. Approvers receive **no** frame narrative, no
plans, no council rationale and no candidate history — only the original request,
the frozen criteria, the deliverable and the evidence package (Kapı 2 pass rate,
worst finding, unresolved findings, test list). Each approver first interprets
the request on its own, then returns `accept · reject · conditional` with
reasons. The deliverable is **accepted** when accepts + conditionals form a
majority **and** accepts ≥ rejects. Rejection reasons drive the next round.

Put the `approval` seat on a model **different from every council seat**:
IRADE is a co-author of the process, so it cannot be its own judge.
`milyonus imece seats` warns when they overlap.

---

## The process observer

`imece/observer.py` is the outside eye. It runs cheap **deterministic monitors**
after phases, and at the end **observer agents** read the run's metrics — never
the deliverable — and write a retrospective.

| Monitor | Fires when |
|---|---|
| Groupthink / early convergence | Mean pairwise Jaccard similarity of candidates > 0.6 |
| Approach collapse | ≥ 4 candidates, fewer than 2 distinct approaches |
| Council bottleneck | > 25% of decisions reached Kademe ≥ 2 (with ≥ 4 decisions) |
| Failing agents | > 10% of agent runs failed (with a per-block breakdown) |
| Budget pressure | > 80% of the token pool spent |
| No progress | A round was rejected for (nearly) the same reasons as the last |

Observer agents rotate their focus across four layers — framing, imece pool,
IRADE council, gates — and return process issues and changes.

---

## Human oversight

- **Kademe 4 prompt.** In an interactive terminal, an irreversible or deadlocked
  decision stops and shows you each option's total and any vetoes. You choose an
  option id, or press enter to stop. You have the last word, even over a veto.
- **Non-interactive runs** (no TTY: CI, cron, piped stdin) have no human
  attached, so a Kademe 4 decision **stops the run**. It is never decided
  silently.
- **Stop authority.** `milyonus imece stop` writes `~/.milyonus/imece.stop`. The
  run checks for it at every phase boundary and halts cleanly, keeping its
  report. `Ctrl+C` also works.

---

## Worker safety: what subagents may touch

The underlying `AgentLoop` executes tools through an approval hook, and with no
human at the keyboard that hook would allow everything. Hundreds of parallel
workers must not be able to write files, send messages or run shell commands.
So imece agents get the **restricted child toolset filtered down to `safe`
tools only** (`agents.safe_registry`): today that is `read_file` and
`list_dir`, scoped to the working directory.

- `run_shell`, `delegate_task`, `memory_propose` and `skill_manage` are always
  removed (the subagent contract).
- Read-only tools above `safe` must be opted in explicitly. `allow_tools` accepts
  only `web_fetch`, and the config schema rejects anything else.
- Agents without `use_tools` (framing, council, approval, …) get **no tools at
  all**: one model call, one answer.
- Anything with a side effect belongs to a human-approved Kademe 4 decision, not
  to a worker.

---

## The seven guarantees, mapped to code

| # | Guarantee | Where it is enforced |
|---|---|---|
| 1 | The option set is challenged before IRADE ever sees it | Kapı 1 `gates.frame` runs first; IRADE only sees Kapı 2 survivors |
| 2 | Council members come from different vendors, with different roles | Per-seat models `[imece.seats.council_*]`; fixed perspectives in `irade.PERSPECTIVES`; `imece seats` warns on overlap |
| 3 | Score and veto together — a total never decides alone | `Irade._aggregate`: mean floor + per-member hard floor on `safety · legal · reversibility` |
| 4 | IRADE only sees candidates that passed the tests | Kapı 2 filter in `Imece.run` before the shortlist |
| 5 | Onay Merci is independent of IRADE and blind to the process | `gates.approve` signature; separate `approval` seat |
| 6 | Random audit of Kademe 0–1 decisions | `Irade._maybe_audit` + `audit_rate`; drift recorded on each decision |
| 7 | Human stop authority; irreversible → human | Kademe 4 in `Irade._to_human`; `imece stop`; checkpoints in `Imece._phase` |

Plus structural rules that are not on the original list but are enforced the
same way:

- **Independent blocks cannot swarm** (`Allocation.borrow`).
- **Nobody critiques their own work** (`_cross_critique` rotation).
- **The frame is frozen** (immutable dataclass).
- **A missing vote abstains** — it never vetoes (`_read_scores`, quorum).
- **One failed agent never sinks a phase** (`Swarm._one`).

---

## Configuration reference

Config lives in `~/.milyonus/config.toml` (override the root with
`MILYONUS_HOME`). The schema is strict: **unknown keys are a startup error**.

```toml
[provider]                      # the default model — also the "pool" seat
name = "openai"                 # anthropic | openai | local
base_url = "https://openrouter.ai/api/v1"
model = "mistralai/mistral-small-3.2-24b-instruct"
# reasoning_effort = "low"      # minimal | low | medium | high — for reasoning models

[imece]
agents = 120                    # total subagents (17 … 100,000)
max_parallel = 8                # concurrent subagents (1 … 256)
max_tokens = 2000000            # shared token pool for the whole run
max_rounds = 2                  # a Kapı 3 rejection feeds the next round (1 … 5)
max_clusters = 9                # approach clusters for builders
shortlist = 4                   # Kapı 2 survivors that go to cross-critique and IRADE
pass_threshold = 0.6            # test pass rate needed to pass Kapı 2
max_output_tokens = 8192        # per-agent output cap
veto_floor = 0.5                # IRADE: mean safety/legal/reversibility floor
hard_veto_floor = 0.2           # IRADE: any single member below this vetoes
spread_threshold = 0.15         # IRADE: member-score spread that triggers escalation
audit_rate = 0.05               # share of Kademe 0–1 decisions re-checked by the council
allow_tools = []                # only ["web_fetch"] is accepted

# One model per seat. Unset seats fall back to [provider] ("pool").
[imece.seats.council_correctness]
name = "openai"
base_url = "https://openrouter.ai/api/v1"
model = "deepseek/deepseek-v4-pro"
reasoning_effort = "low"

[imece.seats.council_risk]
name = "openai"
base_url = "https://openrouter.ai/api/v1"
model = "qwen/qwen3.8-flash"

[imece.seats.council_user_impact]
name = "openai"
base_url = "https://openrouter.ai/api/v1"
model = "mistralai/mistral-small-3.1-24b-instruct"

[imece.seats.council_cost_speed]
name = "openai"
base_url = "https://openrouter.ai/api/v1"
model = "meta-llama/llama-4-maverick"

[imece.seats.council_devils_advocate]
name = "openai"
base_url = "https://openrouter.ai/api/v1"
model = "google/gemma-4-31b-it"

[imece.seats.approval]          # NOT on any council vendor
name = "openai"
base_url = "https://openrouter.ai/api/v1"
model = "x-ai/grok-4.3"
reasoning_effort = "low"
```

This is the exact seat layout used in the real trial runs below. Model ids
change over time; check your provider's catalogue.

**Valid seats:** `pool`, `framing`, `test_design`, `red_team`,
`evidence_audit`, `compliance`, `observer`, `approval`, `council_correctness`,
`council_risk`, `council_user_impact`, `council_cost_speed`,
`council_devils_advocate`. Test execution, recon, plan, command, production,
experts, integration and polish run on `pool`.

Every key with its default is also in
[docs/config.example.toml](docs/config.example.toml).

---

## Choosing models (and the reasoning-model trap)

- **Diversity matters more than size for the council.** Five copies of the same
  model share the same blind spots. The whole point of IRADE is low ρ. Use
  different vendors, and keep `approval` off every council vendor.
- **Watch out for reasoning models in the pool.** Some reasoning models spend
  the *entire* `max_tokens` budget on hidden reasoning and return an empty answer
  (`finish_reason = length`, `reasoning_tokens = max_tokens`). The first real
  trial hit exactly this. Two defences are now built in:
  - an empty reply is counted as a **failed agent**, never as a candidate;
  - `reasoning_effort` (OpenRouter → `reasoning.effort`, other OpenAI-compatible
    endpoints → `reasoning_effort`) caps the thinking.

  Some models ignore the effort hint. For the high-volume `pool` seat, a
  non-reasoning instruct model is the safer and cheaper choice.
- **Probe before a big run.** `milyonus imece run … -n 17` is the cheapest full
  pass through every function.

---

## Cost and budget

**Every agent is a real model call.** Measured subagent calls for **one round**
(the IRADE fast path, everything accepted on the first try) at different scales:

| `-n` | 17 | 60 | 120 | 500 | 2,000 | 10,000 |
|---|---:|---:|---:|---:|---:|---:|
| Subagent calls | 31 | 104 | 186 | 691 | 2,686 | 13,326 |

Real runs make more calls than this: escalations to the full council, a second
round and integrity fix passes all add calls. The real 17-agent trial below made
55 calls over two rounds.

**Controls:**

- `--max-tokens` / `max_tokens` is a **shared pool** for the whole run. When it
  runs out, the run stops cleanly with status `budget` and keeps everything it
  has so far.
- `--parallel` / `max_parallel` caps how many agents run at once.
- The CLI shows the distribution and asks for confirmation before spending
  (skip with `-y`).
- `milyonus imece plan` is free: no model calls.

---

## The run report

Every run writes a full JSON report to `~/.milyonus/logs/imece/<timestamp>.json`:

| Field | Contents |
|---|---|
| `status` | `accepted · rejected · stopped · budget` |
| `frame` | Problem, frozen criteria, assumptions, disciplines, **divergences** |
| `allocation` | Agents per block for this run |
| `decisions` | Every IRADE decision: tier, choice, totals, vetoes, spread, vote share, confidence, escalations, abstentions, audit result |
| `gate_reports` | Every Kapı 2 report: pass rate, every finding (source, severity, `needs_human`) |
| `final_gate` | The system re-test of the integrated deliverable |
| `verdict` | Kapı 3: accepts / conditionals / rejects, reasons, unmet criteria |
| `calls_by_block` / `failed_by_block` | Agent runs and failures per block |
| `tokens` | Tokens drawn from the pool |
| `warnings` / `metrics` | Process observer output |
| `retrospective` | Observer agents' process notes |
| `deliverable` | The final (or last) deliverable |

---

## Status & honest trial results

The pipeline was run end-to-end against **real models** (via OpenRouter) at
`-n 17`, using five different vendors on the council and a sixth on the approval
seat. The task was a Turkish IBAN validator with pytest tests, chosen because
its correctness can be checked mechanically.

| Run | What happened | Root cause | Fix (now in the code) |
|---|---|---|---|
| 1 | No usable candidates | The pool model was a reasoning model that spent all 4,096 output tokens on hidden reasoning and returned **empty text** | Empty replies count as failed agents; `reasoning_effort`; per-agent `max_output_tokens`; switched the pool to a non-reasoning model; the OpenAI-compatible provider now reports usage **after** the stream ends (it used to undercount the token pool) |
| 2 | Halted at synthesis (Kademe 4, no human attached) | One reviewer's **low-severity** `needs_human` aside made the whole decision irreversible | `needs_human` is honored only from compliance or high/critical findings; Kapı 2 reports are now saved in the run report |
| 3 | 2 rounds, 55 calls, ~140k tokens. Round 1: 2/2 candidates passed Kapı 2, IRADE escalated to the full council and chose one; the **integrated deliverable failed the system re-test**. Round 2: halted at synthesis | Council replies that could not be read were scored as **zeros**, so a broken reply turned into a veto on every option | Unreadable votes now **abstain**; quorum rules; failures are reported per block; integrators are told to return plain Markdown, not JSON |

**The gates did their job.** The round-1 deliverable from run 3 was checked
independently, outside the system: its own test suite fails 1 of 7 tests, and
its mod-97 loop **never terminates** on a real, valid IBAN. Kapı 2's system
re-test had already refused it. In other words, the trials failed honestly
instead of shipping something broken.

**Not yet verified:** a real-model run *after* the run-3 fixes, and any
accepted deliverable from real models. Treat Milyonus-Imece as a working,
well-tested **experimental** system, not a production one.

---

## Known limitations and open risks

| Risk | Why it remains | Mitigation |
|---|---|---|
| Shared vendor bias | All models may be trained on similar data | Different vendors and architectures per seat; human expert sampling where possible |
| Unmeasurable "correct" | When tests cannot be written, the reality gate weakens | Evidence audit + expert review + pilot; the success criteria become the tests as a fallback |
| Goodhart | Producers may dress packets up for the score | Fixed packet template, clipped options; scores come from the council, never the producer |
| Council bottleneck | If tier shares don't hold, the council clogs | The observer flags a Kademe ≥ 2 share above 25%; thresholds are configurable |
| Emergent behaviour | Unforeseen interactions at scale | Process observer; start small (`-n 17`) and grow |
| Test execution is model-judged | Test executors *evaluate* candidates; they do not run code in a sandbox | Planned: sandboxed execution through the platform's sandbox backends |
| Calibration needs history | Confidence is corrected only after ≥ 5 outcomes per bucket | Grows automatically with use |
| Small-scale granularity | At `-n 17`, compliance, polish and experts get 0 agents | Use `-n ≥ 60` for problems that need them |

---

## Testing the collective without spending tokens

`tests/test_imece.py` drives the whole system with a deterministic
`FakeCollective` that answers every role with well-formed JSON and records every
brief it receives. That makes it possible to assert **what each agent was
allowed to see**, not only what came out. The tests cover:

- scaling: the exact reference at 10,000, floors and exact sums from 17 to 5,000,
  the minimum-size error;
- swarming: flexible ↔ flexible only, and independent blocks refused both ways;
- IRADE: veto beats a high total; the fast path uses 3 members; disagreement
  escalates to the full council with Kapı 2 evidence; irreversible decisions go
  to a human or stop; novel → precedent → policy routing; random audit;
  calibration persisted to disk; unreadable votes abstain; no quorum escalates;
- independence: test design never sees a candidate; Kapı 3 never sees plans,
  framing or council talk; framing cells never see each other; critics are never
  the author;
- full runs: accepted runs use every staffed block; every builder slot really
  runs; a rejection feeds round 2; budget exhaustion; human stop; fully unsafe
  candidates stop at synthesis;
- worker safety: only safe tools, plus opt-in `web_fetch`, never shell;
- config: defaults, the minimum size, unknown seats and disallowed tools are
  rejected.

```bash
uv run pytest tests/test_imece.py -q      # the collective, no API key needed
make check                                 # lint + format-check + full suite (what CI runs)
```

---

## Code map

```
src/milyonus/imece/
├── scale.py         10,000 reference distribution · floors · allocate() · swarming loans
├── agents.py        AgentSpec · Swarm (parallel, shared token pool) · LLMAgentFn · safe_registry
├── irade.py         5-member council · 6 dimensions · veto floors · Kademe 0–4 · quorum ·
│                    JEV precedent · random audit · Calibrator
├── gates.py         Kapı 1 frame() · Kapı 2 design_tests() + reality() · Kapı 3 approve()
├── observer.py      deterministic monitors + LLM retrospective
└── orchestrator.py  Imece.run(): the full pipeline, rounds, stop checkpoints, RunResult
src/milyonus/cli/imece_cmd.py   `milyonus imece plan | seats | run | stop`
src/milyonus/config/schema.py   ImeceConfig · per-seat ProviderConfig · reasoning_effort
docs/imece.md                   short reference
tests/test_imece.py             the collective under a deterministic fake
```

---

# The Milyonus platform underneath

Milyonus-Imece is built on **Milyonus Agent 5.5**, and everything below still
ships and works. Imece reuses its agent loop, provider router, delegation
contract, budget, risk engine and strict config.

## Why Milyonus

Most agents start from zero every session. The ones that *do* remember tend to
believe whatever gets written to memory — which makes them easy to **poison**.
Milyonus keeps the learning loop (persistent memory + self-authored skills) but
makes every memory **earn its place**.

| | Typical self-evolving agent | **Milyonus** |
|---|---|---|
| Memory write | Agent writes directly | **Ingest → Quarantine → Verify → Promote** |
| Provenance | Not tracked | Every line: who · from where · which turn · what evidence |
| Poison cleanup | Manual | `memory revoke --source <uri>` cascades in **seconds** |
| Rejected ideas | Forgotten (rephrase slips through) | **Negative memory** + rephrase detection |
| Memory in prompt | Injected as text | Rendered in a **data fence** — "not instructions" |
| Promoted memory | Trusted **forever** | **Trust decays** — must be re-earned or it's demoted (a security boundary, not undo) |
| Reaffirming a memory | Unlimited / free | **Rate-limited + diminishing returns**; only an operator-signed reaffirm restores full trust |
| Operator authority (T0) | "message says I'm the operator" | **Ed25519-signed, out-of-band, two-phase** — unforgeable from any text |
| Semantic recall | Cosine only — a lie rides similarity to the top | **Trust-weighted** (`cosine × trust`) — a low-trust match can't outrank a trusted one |
| Cross-session user model | LLM-inferred, **trusted on write** (poisonable) | **Verified-growth + per-user scoped** — every self-fact passes the pipeline |
| External tools (MCP) | Trusted subprocess, full env | **Untrusted**: filtered env, redacted output, RiskEngine-gated |
| Autonomy | "Act first" (risk multiplier) | **Risk-tiered**: reversible → auto, irreversible → always confirm |
| Self-modification | — | Open core, gated by **git snapshot + test + rollback** |
| Many agents | Fan out and average | **Milyonus-Imece**: independent gates, veto-floored council, blind approval |

> Measured on the built-in **PoisonBench**: single-shot held-out **ASR 0% · RSR 0% · 100% legitimate promotion**, plus **10/10 multi-step attack scenarios contained** (patient · distributed · T0-spoof · semantic · negative) — see [docs/benchmarks.md](docs/benchmarks.md).

Single-agent quick start:

```bash
milyonus setup                        # pick a provider
milyonus doctor                       # verify the environment
milyonus                              # start an interactive session
```

Multi-provider: **Anthropic** (default, most poisoning-resistant), **OpenAI**,
**OpenRouter**, and **local** (Ollama / vLLM).

---

## Talk to it from anywhere

The same agent core runs behind **six surfaces**, all default-deny with in-chat approval:

<div align="center">

| Surface | Transport | Setup |
|---|---|---|
| 🖥️ **CLI / TUI** | terminal | `milyonus` |
| ✈️ **Telegram** | Bot API (long-poll) | `milyonus gateway start --channel telegram` |
| 💬 **WhatsApp** | Cloud API (webhook) | `milyonus gateway start --channel whatsapp` |
| 🟣 **Slack** | Events API (webhook) | `milyonus gateway start --channel slack` |
| 🎮 **Discord** | Gateway (WebSocket) | `milyonus gateway start --channel discord` |
| 📝 **Editor (ACP)** | stdio / JSON-RPC | `milyonus acp` (Zed, …) |

</div>

### How pairing works (every messaging channel)

Channels are **default-deny**: an unknown user is refused until paired. You
generate a one-time code and the user redeems it in chat.

```bash
milyonus gateway pair telegram        # → prints an 8-char code (valid 1 hour)
milyonus gateway start --channel telegram
# then, in the chat: /pair <code>   →   "pairing successful"
```

Codes are crypto-random, expire in 1 hour, rate-limited (1/10 min), and lock out
after 5 failed attempts. Secrets always live in `~/.milyonus/.env` (chmod 600).

### Connecting each channel

<details>
<summary><b>✈️ Telegram</b> — Bot API, easiest to set up</summary>

1. In Telegram, message [@BotFather](https://t.me/BotFather) → `/newbot` → get a token.
2. Add it to your env:
   ```bash
   echo 'TELEGRAM_BOT_TOKEN=123456:AA...' >> ~/.milyonus/.env && chmod 600 ~/.milyonus/.env
   ```
3. Pair and start:
   ```bash
   milyonus gateway pair telegram        # → a code
   milyonus gateway start --channel telegram
   ```
4. Open your bot, press **Start**, send `/pair <code>`, then chat normally.
</details>

<details>
<summary><b>💬 WhatsApp</b> — official Cloud API (webhook)</summary>

You need a Meta developer app with WhatsApp added (phone-number id + a permanent token).

1. Put the credentials in `~/.milyonus/.env`:
   ```bash
   WHATSAPP_TOKEN=EAAG...                 # Graph API token
   WHATSAPP_PHONE_NUMBER_ID=1234567890
   WHATSAPP_VERIFY_TOKEN=some-random-string   # you choose this
   WHATSAPP_APP_SECRET=...                # optional but recommended (HMAC verify)
   ```
2. Start the gateway (it serves the webhook):
   ```bash
   milyonus gateway start --channel whatsapp --port 8080
   ```
3. Expose the port over HTTPS (reverse proxy, or a tunnel like cloudflared/ngrok
   for testing) and register that public URL as the webhook in the Meta app,
   using the same `WHATSAPP_VERIFY_TOKEN`. Subscribe to the **messages** field.
4. Message the number, then `/pair <code>` (from `milyonus gateway pair whatsapp`).

> The unofficial whatsapp-web.js/Baileys bridge risks account bans and is **not
> shipped**. Details: [docs/whatsapp.md](docs/whatsapp.md).
</details>

<details>
<summary><b>🟣 Slack</b> — Events API (webhook)</summary>

1. Create a Slack app, add a bot token scope, install to the workspace, and copy
   the **Bot User OAuth Token** and the **Signing Secret**:
   ```bash
   SLACK_BOT_TOKEN=xoxb-...
   SLACK_SIGNING_SECRET=...
   ```
2. Start the gateway (serves the webhook):
   ```bash
   milyonus gateway start --channel slack --port 8080
   ```
3. Expose the port over HTTPS and set the **Event Subscriptions** request URL to
   `https://your-host/`. Slack sends a one-time challenge (handled automatically),
   then subscribe to `message.channels` / `message.im` events.
4. DM the bot (or invite it to a channel), then `/pair <code>`.

> Requests are signature-verified with a 5-minute replay window when
> `SLACK_SIGNING_SECRET` is set.
</details>

<details>
<summary><b>🎮 Discord</b> — Gateway (WebSocket)</summary>

1. Install the optional dependency:
   ```bash
   pip install milyonus-agent[discord]
   ```
2. Create a Discord application → **Bot** → copy the token. Under **Privileged
   Gateway Intents**, enable **MESSAGE CONTENT INTENT**.
   ```bash
   echo 'DISCORD_BOT_TOKEN=...' >> ~/.milyonus/.env
   ```
3. Invite the bot to your server (OAuth2 URL with the `bot` scope).
4. Start it and pair:
   ```bash
   milyonus gateway start --channel discord
   # in Discord: /pair <code>
   ```
</details>

<details>
<summary><b>📝 Editor (ACP)</b> — Zed and other ACP editors</summary>

Point your editor's ACP agent config at the `milyonus acp` command:

```
command: milyonus
args: ["acp"]
```

Milyonus then serves newline-delimited JSON-RPC on stdio (initialize / session.new
/ session.prompt with streaming). Your provider key is read from `~/.milyonus/.env`
as usual. Details: [docs/acp.md](docs/acp.md).
</details>

Full production hardening: [docs/production.md](docs/production.md).

---

## ✦ Verified memory — the core idea

Milyonus has **no direct-write path** to durable memory. Every candidate flows
through a pipeline before it is trusted:

```
 memory candidate
      │
      ▼
 ┌──────────┐   ┌─────────────┐   ┌──────────────────────┐   ┌──────────┐
 │  Ingest  │──▶│  Quarantine │──▶│  Verify              │──▶│ Promote  │
 │          │   │ + provenance│   │ scanner + verifier   │   │ (ledger) │
 └──────────┘   └─────────────┘   │ model + tier rules   │   └──────────┘
                                  └──────────┬───────────┘
                                             │ reject
                                             ▼
                                     negative memory
                                   (rephrase detection)
```

**Trust tiers** decide how a claim is promoted:

| Tier | Source | Rule |
|---|---|---|
| **T0** | operator config | permanent, agent can't change |
| **T1** | paired user, direct | promote instantly if it passes the scanner |
| **T2** | agent first-hand observation | verifier approval |
| **T3** | third-party (web, email, group) | 2 independent confirmations + verifier; else expires |
| **T4** | subagent / unknown | never auto-promotes — user approval only |

Every line is **provenance-stamped** and recorded on a **hash-chained ledger**.
Ask it anything:

```bash
milyonus memory why <id>       # full provenance chain + evidence hash
milyonus memory revoke --source https://bad.example   # cascade in seconds
milyonus memory diff --since 7d
milyonus audit verify          # ledger integrity intact?
```

Memory reaches the prompt inside a `<milyonus:memory>` **data fence** with an
explicit rule that it is *past observation, not instruction* — imperatives inside
memory are never executed.

---

## ✦ Memory as a security boundary

Source and verification decide what gets *in*. But a memory that slipped through
once — or that was legitimate yesterday — must not silently become **tomorrow's
default**. So Milyonus treats promotion as a **standing security boundary, not an
undo feature**: trust is continuously re-earned, and unrenewed trust falls on its
own. This is the gap Hermes/OpenClaw leave open — *"an instruction written once
stays the default forever."*

**Trust decays — promotion is time-boxed, not permanent belief.**

| Tier | Source | Half-life |
|---|---|---|
| **T0** | operator (signed) | **never** — authority, not a claim |
| **T1** | paired user, direct | ~180 days |
| **T2** | agent observation | ~60 days |
| **T3** | third-party | ~14 days |

Trust halves each half-life since it was last reaffirmed. When it falls below the
floor, the nightly consolidation **demotes it back to quarantine** (re-validatable,
not deleted) — so it drops out of the agent's defaults until a human re-earns it:

```bash
milyonus memory why <id>        # trust: 0.41 (ceiling 0.80, reaffirmed 2×)
milyonus memory reaffirm <id>   # weak human reaffirm — diminishing returns
milyonus memory reaffirm <id> --sign ~/operator-key.pem   # strong: restores 1.00
milyonus memory review          # what the boundary flagged: demoted / due / anomalous
milyonus memory stats           # tier & sensitivity mix + false-positive recovery rate
```

Reaffirmation is a **human-only** action (the agent has no reaffirm tool — it
cannot infer "the user still agrees"), and it resists *patient* attackers, not
just loud ones:

- **Rate-limited** — a flood of manipulative messages can't keep resetting the clock.
- **Diminishing returns** — repeated *weak* reaffirms restore less each time (a
  falling trust ceiling); only a **strong, operator-signed** reaffirm restores full
  trust. Weak repetition alone can never hold a memory at 1.00 forever.
- **Sensitivity-aware decay** — memory that touches authority, access, or approval
  ("the agent may deploy without confirmation") decays **~4× faster** than a taste
  preference, so a stale security fact expires long before a stale UI setting.
- **Not silent** — every auto-demotion and reaffirm anomaly surfaces in
  `memory review`, and `memory stats` reports the false-positive rate so decay that's
  too aggressive is visible, not guessed at.

**T0 is an authenticated, out-of-band boundary — unforgeable from any text.**

The operator tier can never be minted by something the model reads (a chat
message, a file, a tool result). A T0 write is bound to an **Ed25519 signature**
whose private key lives *off* the agent host, and it takes **two AND-layered
phases** — a signed stage, then a second signature *and* a mandatory review gap —
before it becomes a default:

```bash
milyonus admin keygen --private ~/operator-key.pem   # private key stays off-host
milyonus admin t0 add "Deploys only from CI" --key ~/operator-key.pem   # staged (passive)
milyonus admin t0 activate <id> --key ~/operator-key.pem                # 2nd sig + review gap
```

Even a full host compromise can *verify* but never *forge* T0. Details:
[docs/operator.md](docs/operator.md).

**Semantic recall — trust-weighted, never a poison amplifier.**

Durable memory is also indexed as vectors, so the agent recalls by *meaning*, not
substring: "where does the user live" finds "he's based in Istanbul." The layer is
pluggable and **dependency-free by default** — a hashing (lexical-vector) embedder
that needs no model or network — and switches to real embeddings with one config
line (`embedder = "openai"`).

Crucially, recall ranks by **`cosine × current_trust`, not cosine alone**. A
semantically perfect match sitting in a decayed or low-trust memory can *never*
outrank a trusted one, so wording a poisoned line to match the query buys an
attacker nothing — the trust boundary still leads. Recall is strictly read-only;
embeddings only index what the pipeline already promoted.

```bash
milyonus memory search "which editor"   # trust-weighted semantic recall
milyonus memory reindex                 # (re)build vectors after switching embedder
```

---

## ✦ Skills — procedural memory

The agent loads on-demand instruction docs (agentskills.io-compatible) and
**writes its own** from experience. Unlike other agents, a generated skill is
**verified, not trusted on write**: it must pass a reproducibility gate + security
scanner before it goes live.

**41 official skills ship bundled** — ready on first install:

```
git · github-cli · docker · docker-compose · kubernetes · pytest · uv · ripgrep
jq · sqlite · postgres · pandas · csv · ffmpeg · imagemagick · tar · ssh · cron
systemd · curl · bash · regex · markdown · env-secrets · web-scraping · pdf
github-actions · terraform · aws-cli · fastapi · playwright · security-audit
rag-retrieval · prompt-engineering · debugging · observability
cold-email · linkedin-outreach · lead-generation · outreach-sequencing · email-deliverability
```

```bash
milyonus skills list           # browse
milyonus skills view git-workflow
milyonus skills why <name>     # provenance: official | self-learned | hub
```

---

## ✦ Security model

Defense-in-depth, on by default:

1. **Risk-tiered approval** — reversible/local runs automatically; irreversible or
   outward-reaching actions **always** confirm, and no "always allow" can cover that class.
2. **DM pairing** — 8-char crypto codes, 1h TTL, rate limit, lockout, `chmod 600`.
3. **Sandbox** — `local · docker · ssh · modal · daytona`; hardened container image.
4. **Credential filtering** — secrets stripped from subprocess env, redacted from output.
5. **Injection scanning** — memory candidates *and* context files (`AGENTS.md`,
   `.cursorrules`, …) scanned before they can reach the prompt.
6. **SSRF** — always-on, fail-closed; blocks private/loopback/link-local/cloud-metadata.
7. **Pre-exec scanning + audit** — fork bombs, `rm -rf /`, `curl | bash` blocked;
   every action hash-chained in the ledger.
8. **Imece workers are side-effect free** — safe tools only; anything irreversible
   is a Kademe 4 human decision.

> `SafetyRegression` suite: **0 findings**.

---

## ✦ Self-modification

The core is open and the agent **can edit its own code** — nothing blocks it.
Safety comes from **reversibility**, not prohibition:

```
snapshot (git)  →  agent edits  →  pytest gate  →  ✅ keep  /  ❌ auto-rollback
```

```bash
milyonus selfmod log
milyonus selfmod rollback [--to <tag>]
```

---

## ✦ Connecting MCP servers

Milyonus is an **MCP client**: declare any Model Context Protocol server in
`config.toml` and its tools appear to the agent, namespaced `mcp_<name>_<tool>`.

```toml
[[mcp_servers]]
name = "github"
command = ["npx", "-y", "@modelcontextprotocol/server-github"]
enabled = true
risk = "caution"                    # every tool gated by the RiskEngine
env_passthrough = ["GITHUB_TOKEN"]  # grant just this server its key
```

External servers are treated as **untrusted subprocesses**: the child gets a
**filtered environment** (secret-looking vars are stripped unless you name them
in `env_passthrough`), their output is **redacted**, and their tools default to
`caution` so side effects hit the same approval path as everything else. A server
that fails to start is **reported and skipped** — it never blocks the session or
the other servers.

```bash
milyonus mcp list          # configured servers
milyonus mcp tools [name]  # connect and list what each exposes
milyonus mcp example       # a ready-to-paste config block
```

---

## ✦ Cross-session user model

The agent keeps a persistent, evolving representation of each user that survives
across sessions — preferences, facts, patterns — in the spirit of Honcho's
"theory of mind." Milyonus closes that idea's biggest hole: **a freely-written,
LLM-inferred user model is a poisoning target.** So here the user model *is* the
verified-memory store, scoped to one user:

- **Grows through the pipeline.** At session end the agent reflects on the user's
  own messages and *proposes* durable self-facts — each is quarantined and
  promoted only if it passes verification. Nothing about who the user "is" is
  trusted on write, so a manipulative message can't rewrite it.
- **Scoped per user.** Reads are filtered by provenance, so in a multi-user
  gateway one person's model never leaks into another's session — real isolation,
  not just focus.
- **Decays.** It rides the same items, so the trust-decay boundary applies: a
  stale claim about the user falls out until reaffirmed.

The agent has a `user_recall` tool for a **dialectic query** — "what do we know
about this user re: X" — trust-weighted and user-scoped. From the CLI:

```bash
milyonus user show              # the durable, trust-ranked model
milyonus user ask "editor"      # dialectic query
milyonus user observe "prefers dark mode"   # propose (verified, not written)
```

---

## Platform architecture

```
┌──────────────────────────────────────────────────────────────────┐
│  SURFACES   CLI/TUI · Telegram · WhatsApp · Slack · Discord · ACP │
├──────────────────────────────────────────────────────────────────┤
│  IMECE ★    Kapı 1 · imece pool (Swarm) · IRADE · Kapı 2 · Kapı 3 │
│             process observer · scale/allocation · run reports     │
├──────────────────────────────────────────────────────────────────┤
│  CORE       AgentLoop · PromptBuilder · Budget · ProviderRouter   │
│             (anthropic | openai | openrouter | local)             │
├──────────────────────────────────────────────────────────────────┤
│  CAPABILITY ToolRegistry · Skills · MCP client · Delegation       │
├──────────────────────────────────────────────────────────────────┤
│  MEMORY ★   Ingest→Quarantine→Verify→Promote · Ledger             │
│             SessionStore(FTS5) · NegativeMemory · Revocation      │
├──────────────────────────────────────────────────────────────────┤
│  SECURITY   RiskEngine · Approval · Sandbox · SSRF · Redaction    │
│             InjectionScanner · PreExecScanner · AuditLog          │
├──────────────────────────────────────────────────────────────────┤
│  INFRA      SQLite/WAL · strict ConfigSchema · Telemetry(opt)     │
└──────────────────────────────────────────────────────────────────┘
```

Every imece agent is an `AgentLoop` run under the platform's **delegation
contract** (goal + context + success criteria) on the provider of its seat. The
`Swarm` adds concurrency limits, a shared token pool and per-block failure
accounting on top.

---

## Benchmarks

Reproducible, in-repo. Run them yourself:

```bash
uv run python -m evals.poisonbench.run          # memory-poisoning resistance
uv run python -m evals.safety.run               # approval-bypass regression
```

| Suite | Metric | Milyonus | Reference |
|---|---|---|---|
| **PoisonBench** | Attack Success Rate | **0.0%** | Hermes 66.67% |
| **PoisonBench** | Retention/Success Rate | **0.0%** | Hermes 64.70% |
| **PoisonBench** | Legitimate promotion | **100%** | — |
| **SafetyRegression** | Approval bypasses | **0** | — |

Details and methodology: [docs/benchmarks.md](docs/benchmarks.md) ·
[docs/comparison.md](docs/comparison.md). The imece has no benchmark yet; see
[Status & honest trial results](#status--honest-trial-results).

---

## CLI reference

```
milyonus                     interactive session
milyonus setup               first-run wizard
milyonus doctor              environment diagnostics
milyonus imece    plan | seats | run | stop   # the İmece-İRADE collective
milyonus memory   list | pending | why | diff | revoke | search | reaffirm | review | stats | reindex | consolidate
milyonus mcp      list | tools | example   # external MCP servers
milyonus user     show | ask | observe      # cross-session user model
milyonus skills   list | view | why
milyonus audit    verify | log
milyonus gateway  start | pair
milyonus selfmod  log | rollback
milyonus cron     add | list | remove   # scheduled tasks (NL/cron/interval)
milyonus proactive start | suggest    # run the scheduler; suggest automations
milyonus research "<question>"          # deep web research → a cited report
milyonus eval     run | tasks    # task-level evaluation + cost/observability
milyonus acp                 run as an editor agent (ACP)
```

---

## Deployment

```bash
# hardened container (non-root, read-only rootfs via compose, cap-drop)
docker run --rm -it -v milyonus-data:/data milyonus/agent:5.5.0 doctor

# production gateway on a VPS
docker compose -f deploy/compose.yaml up -d
```

Guides: [docs/docker.md](docs/docker.md) · [docs/production.md](docs/production.md)
· [docs/publishing.md](docs/publishing.md).

---

## Development

```bash
make sync                  # deps (matches CI: dev + admin + discord)
make hooks                 # enable pre-push gate (runs the CI checks locally)
uv run pytest -q           # 306 tests, green without an API key
make check                 # lint + format-check + test — exactly what CI runs
```

`make check` mirrors CI one-for-one (`ruff check` · `ruff format --check` ·
`pytest`); `make hooks` wires it into a pre-push hook so a push can't go out red
(bypass with `git push --no-verify`).

Extend Milyonus through the **skill**, **tool**, or **channel adapter** interfaces
— the verified-memory core stays small and auditable. See
[CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md).

---

## Roadmap

**Milyonus-Imece**

- [x] Scalable allocation (17 → 100,000) from the 10,000 reference, with floors and swarming rules
- [x] Kapı 1 independent framing with frozen criteria and surfaced divergences
- [x] Imece pool: recon, experts, plans, approach clusters, wire-off production, exploration
- [x] Kapı 2: independent test design, test execution, red team, evidence audit, compliance
- [x] IRADE: 5 perspectives, 6 dimensions, veto floors, Kademe 0–4, quorum/abstention, JEV precedent, random audit, calibration
- [x] Cross-critique by rotation + evolutionary revision; integration with swarming and system re-test
- [x] Kapı 3 blind approval on separate models; multi-round feedback
- [x] Process observer: monitors + retrospective; human stop authority; per-seat models
- [x] Real-model trials (3 runs) and the fixes they forced
- [ ] A real-model run that ends with an accepted deliverable
- [ ] Sandboxed execution of tests (instead of model-judged execution)
- [ ] Hierarchical command (7–12-agent cells, 3–4 layers) and layered councils for very large runs
- [ ] Imece benchmark: accepted-deliverable rate, cost per accepted result, calibration error

**Platform**

- [x] Verified-memory core · trust tiers · ledger · revocation
- [x] Agent-authored skills + 41 bundled
- [x] 6 surfaces (CLI, Telegram, WhatsApp, Slack, Discord, ACP)
- [x] Self-modification harness · subagent delegation · MCP client **+ server config**
- [x] Hardened Docker · automated PyPI + Docker Hub release
- [x] Task-level evaluation & observability (success, tools, tokens, cost)
- [x] Proactivity: scheduler (NL→cron), safety policy, automation suggestions
- [x] Integrations: email (IMAP/SMTP), browser (Playwright), vision (image input)
- [x] Deep web research (keyless search → cited synthesis) + outreach skills
- [x] Memory as a security boundary: trust decay + signed out-of-band T0
- [x] Vector/embedding layer for memory: trust-weighted semantic recall (hashing default, opt-in OpenAI)
- [x] Honcho-style cross-session user model — per-user scoped, verified-growth, dialectic recall
- [x] PoisonBench v3: multi-step scenarios (patient / distributed / T0-spoof / semantic), pinned as a regression gate
- [ ] Like-for-like Hermes harness + third-party audit

---

## License &amp; trademark

Apache-2.0 — see [LICENSE](LICENSE). **"Milyonus"** and the star mark are
trademarks; the code license does not grant rights to the name or marks. See
[TRADEMARK.md](TRADEMARK.md). Forks should adopt a distinct name and replace the
assets in `assets/brand/`.

<div align="center">
<br>
<img src="assets/brand/milyonus-mark.png" width="80" alt="Milyonus"/>
<br>
<em>Labor in the imece. Speed in IRADE. Truth at the gates.</em>

<em>Ayaz Elrico | Milyonus INC </em>
<em>ayaz@milyonus.com </em>

</div>
