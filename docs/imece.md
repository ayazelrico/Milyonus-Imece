# Milyonus-Imece

> Labor in the imece, speed in IRADE, truth at the independent gates.

```
 HUMAN OVERSIGHT (stop authority, irreversible decisions)
   Kapı 1  independent framing (≥5 cells) → frozen success criteria
   İMECE   recon · experts · plans · production · test runs · integration (swarming)
     ↕     IRADE council: 5 perspectives, multi-dimension scores + veto floors, Kademe 0–4
   Kapı 2  reality: tests (designed apart from builders) · red team · evidence audit · compliance
   Kapı 3  Onay Merci: blind — request + criteria + deliverable + evidence only
 side: process observer (all layers)
```

## Usage

```bash
milyonus imece plan -n 120          # show the distribution, no model calls
milyonus imece seats                # which model sits where + independence warnings
milyonus imece run "<task>" -n 120 -p 8 --max-tokens 2000000
milyonus imece stop                 # human stop: halts before the next phase
```

`-n` is the number of real subagents. 10,000 is the reference distribution; any
size from **17** (every mandatory function keeps ≥1 agent, framing keeps 5) up
scales proportionally. The 5 IRADE members are outside that total.

## Guarantees in code

| Guarantee | Where |
|---|---|
| Independent blocks never lend/borrow agents | `imece/scale.py` `Allocation.borrow` |
| Test design never sees a candidate | `imece/gates.py` `design_tests` takes only the frame |
| Failing candidates never reach IRADE | `orchestrator.py` Kapı 2 filter |
| Average cannot hide a critical flaw | `irade.py` veto floors (mean and per-member hard floor) |
| Disagreement escalates the tier | `irade.py` `_triggers` |
| Random audit of tier 0–1 decisions | `irade.py` `_maybe_audit` |
| Calibration against real outcomes | `irade.py` `Calibrator` (Kapı 3 verdicts) |
| Kapı 3 is blind | `gates.approve` signature: request, criteria, deliverable, evidence |
| Nobody critiques their own work | `orchestrator._cross_critique` (rotation) |
| Workers cannot cause side effects | `agents.safe_registry`: only `safe` tools (+ opt-in `web_fetch`) |
| Irreversible → human | `irade.py` Kademe 4 |

Put council seats and the approval seat on different vendors (`[imece.seats.*]`,
see `docs/config.example.toml`); `milyonus imece seats` warns when they share a model.
