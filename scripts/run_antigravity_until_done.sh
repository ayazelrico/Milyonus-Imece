#!/usr/bin/env bash
# Poll Antigravity quota and run İmece evals until checkpoints complete.
# Stages: lean clamp (5 agents) → smoke×1 → core-v1×1 → core-v1×5
# Usage: scripts/run_antigravity_until_done.sh [model]
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
MODEL="${1:-gemini-3.8-flash-high}"
AGY="${AGY_BIN:-$(command -v agy)}"
POLL_S="${POLL_S:-180}"
LOG="experiments/antigravity-watch.log"
export PATH="$HOME/.local/bin:$PATH"
export PYTHONUNBUFFERED=1

log() { echo "$(date -u +%FT%TZ) $*" | tee -a "$LOG"; }

probe() {
  local out
  out="$("$AGY" --print "Reply with exactly: pong" --output-format json \
    --model "$MODEL" --mode plan --sandbox --disable-slash-commands \
    --print-timeout 60s 2>/dev/null | tail -1)" || return 1
  echo "$out" | python3 -c 'import sys,json; d=json.loads(sys.stdin.read()); raise SystemExit(0 if d.get("status")=="SUCCESS" else 1)'
}

prepare() {
  local out="$1" suite="$2" repeats="$3" agents="$4"
  shift 4
  local tasks=()
  if (($#)); then
    local t
    for t in "$@"; do tasks+=(--task "$t"); done
  fi
  rm -f "$out" "${out%.json}.lock"
  local stem="${out%.json}"
  stem="${stem#experiments/}"
  rm -rf "experiments/${stem}.journal" "experiments/${stem}.calls"
  uv run python -m evals.imece.run \
    --engine antigravity \
    --model "$MODEL" \
    --executable "$AGY" \
    --config docs/imece-antigravity.toml \
    --backend macos \
    --suite "$suite" \
    --repeats "$repeats" \
    --agents "$agents" \
    "${tasks[@]}" \
    --prepare \
    --out "$out"
}

resume() {
  local out="$1" suite="$2" repeats="$3" agents="$4"
  shift 4
  local tasks=()
  if (($#)); then
    local t
    for t in "$@"; do tasks+=(--task "$t"); done
  fi
  uv run python -m evals.imece.run \
    --engine antigravity \
    --model "$MODEL" \
    --executable "$AGY" \
    --config docs/imece-antigravity.toml \
    --backend macos \
    --suite "$suite" \
    --repeats "$repeats" \
    --agents "$agents" \
    "${tasks[@]}" \
    --resume \
    --out "$out"
}

is_complete() {
  local out="$1"
  [[ -f "$out" ]] || return 1
  python3 -c "import json,sys; d=json.load(open(sys.argv[1])); raise SystemExit(0 if d.get('state')=='complete' else 1)" "$out"
}

run_stage() {
  local name="$1" out="$2" suite="$3" repeats="$4" agents="$5"
  shift 5
  if is_complete "$out"; then
    log "stage $name already complete"
    return 0
  fi
  while true; do
    if ! probe; then
      log "quota unavailable; sleep ${POLL_S}s (waiting for stage $name)"
      sleep "$POLL_S"
      continue
    fi
    log "quota ok — stage $name"
    if [[ ! -f "$out" ]] || [[ "$(python3 -c "import json;print(len(json.load(open('$out')).get('runs',[])))")" == "0" && "$(python3 -c "import json;print(json.load(open('$out')).get('state',''))")" != "prepared" && "$(python3 -c "import json;print(json.load(open('$out')).get('state',''))")" != "partial" && "$(python3 -c "import json;print(json.load(open('$out')).get('state',''))")" != "running" ]]; then
      # Fresh prepare when missing; if interrupted with unknown calls and zero rows, reset.
      if [[ -f "$out" ]]; then
        local runs state
        runs=$(python3 -c "import json;print(len(json.load(open('$out')).get('runs',[])))")
        state=$(python3 -c "import json;print(json.load(open('$out')).get('state',''))")
        if [[ "$runs" == "0" && "$state" != "prepared" ]]; then
          log "resetting interrupted $name"
          prepare "$out" "$suite" "$repeats" "$agents" "$@" | tee -a "$LOG"
        fi
      else
        prepare "$out" "$suite" "$repeats" "$agents" "$@" | tee -a "$LOG"
      fi
    fi
    if [[ ! -f "$out" ]]; then
      prepare "$out" "$suite" "$repeats" "$agents" "$@" | tee -a "$LOG"
    fi
    set +e
    resume "$out" "$suite" "$repeats" "$agents" "$@" 2>&1 | tee -a "$LOG"
    code=${PIPESTATUS[0]}
    set -e
    log "stage $name resume exit=$code"
    if is_complete "$out"; then
      log "stage $name COMPLETE"
      return 0
    fi
    # If unknown calls poisoned a zero-row trial, reset next loop.
    if [[ -f "$out" ]]; then
      runs=$(python3 -c "import json;print(len(json.load(open('$out')).get('runs',[])))")
      if [[ "$runs" == "0" ]]; then
        log "no rows yet for $name; will reset on next quota window"
        rm -f "$out"
        rm -rf "experiments/${out#experiments/}" "experiments/$(basename "${out%.json}").journal" "experiments/$(basename "${out%.json}").calls"
      fi
    fi
    sleep "$POLL_S"
  done
}

mkdir -p experiments
log "watcher start model=$MODEL"

run_stage lean experiments/antigravity-lean.json smoke 1 5 clamp
run_stage smoke experiments/antigravity-smoke-v2.json smoke 1 5
run_stage core1 experiments/antigravity-core-v1-r1.json core-v1 1 5
run_stage core5 experiments/antigravity-core-v1-r5.json core-v1 5 5

log "ALL STAGES DONE"
exit 0
