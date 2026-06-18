#!/usr/bin/env bash
# run_remaining_regimes.sh — Fill missing RAVEL regimes for airline and retail.
# Context:
#   - Airline FullSync: COMPLETE (10/10) — skip
#   - Retail FullSync: INCOMPLETE (6/14) — resume from checkpoint
#   - Both domains need Delayed, FieldMask, ConflictingView
#   - Telecom: handled by wait_and_rerun.sh (all 4 regimes)
#
# Skip logic: check if results.json has >= N_EXPECTED tasks (not just if file exists)

set -euo pipefail

WAIT_PID="${1:-}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
TAU2_DIR="$REPO_DIR/worktrees/tau2-clean"
RESULTS_ROOT="$REPO_DIR/results/ravel_corrected"
LOG_DIR="$RESULTS_ROOT/logs"
RUNNER="$SCRIPT_DIR/run_ravel_exp.py"

MAX_CONCURRENCY=2
MAX_STEPS=25
TIMEOUT=900

LOG_FILE="$RESULTS_ROOT/remaining_regimes.log"

log() { echo "$(date): $*" | tee -a "$LOG_FILE"; }

n_tasks_in_file() {
    # Returns number of simulation entries in results.json (0 if file missing or invalid)
    python3 -c "
import json, sys
try:
    d = json.load(open('$1'))
    print(len(d.get('simulations', [])))
except Exception:
    print(0)
" 2>/dev/null || echo 0
}

is_complete() {
    # is_complete <domain> <regime> <n_expected>
    local domain="$1" regime="$2" n_exp="$3"
    local f="$RESULTS_ROOT/$domain/ravel_${regime,,}/results.json"
    local n
    n=$(n_tasks_in_file "$f")
    if [[ "$n" -ge "$n_exp" ]]; then
        return 0  # complete
    fi
    return 1  # incomplete
}

# Wait for main run (wait_and_rerun.sh) to finish
if [[ -n "$WAIT_PID" ]]; then
    log "Waiting for PID $WAIT_PID (wait_and_rerun.sh) to finish..."
    while kill -0 "$WAIT_PID" 2>/dev/null; do
        sleep 60
    done
    log "PID $WAIT_PID finished. Starting missing/incomplete regimes..."
fi

mkdir -p "$LOG_DIR"
cd "$TAU2_DIR"

# Domain-specific regime lists
# Airline: FullSync is complete (10/10), only need Delayed/FieldMask/ConflictingView
# Retail: FullSync is incomplete (6/14), need FullSync + Delayed/FieldMask/ConflictingView
declare -A DOMAIN_REGIMES
DOMAIN_REGIMES["airline"]="Delayed FieldMask ConflictingView"
DOMAIN_REGIMES["retail"]="FullSync Delayed FieldMask ConflictingView"

declare -A N_EXPECTED
N_EXPECTED["airline"]=10
N_EXPECTED["retail"]=14

log "=== Starting missing/incomplete RAVEL regimes ==="

for DOMAIN in airline retail; do
    REGIMES="${DOMAIN_REGIMES[$DOMAIN]}"
    N_EXP="${N_EXPECTED[$DOMAIN]}"
    log "--- Domain: $DOMAIN (regimes: $REGIMES) ---"

    for REGIME in $REGIMES; do
        if is_complete "$DOMAIN" "$REGIME" "$N_EXP"; then
            n=$(n_tasks_in_file "$RESULTS_ROOT/$DOMAIN/ravel_${REGIME,,}/results.json")
            log "  SKIP: $REGIME [$DOMAIN] already complete ($n/$N_EXP tasks)"
            continue
        fi
        n=$(n_tasks_in_file "$RESULTS_ROOT/$DOMAIN/ravel_${REGIME,,}/results.json")
        log "  Running RAVEL-$REGIME [$DOMAIN] (current: $n/$N_EXP, will resume from checkpoint)..."
        LOG="$LOG_DIR/${DOMAIN}_ravel_${REGIME,,}.log"
        uv run python "$RUNNER" \
            --domain "$DOMAIN" \
            --split dev \
            --regimes "$REGIME" \
            --agent-type ravel \
            --max-concurrency "$MAX_CONCURRENCY" \
            --max-steps "$MAX_STEPS" \
            --timeout "$TIMEOUT" \
            --output-dir "$RESULTS_ROOT" \
            > "$LOG" 2>&1
        log "  Finished $REGIME [$DOMAIN]"
    done

    log "  Domain $DOMAIN: all required regimes done."
done

log "=== All missing regimes complete. Running final analysis... ==="
PYTHONPATH="$REPO_DIR/src" python3 "$SCRIPT_DIR/analyze_results.py" --corrected \
    >> "$RESULTS_ROOT/analysis.txt" 2>&1
log "=== Analysis saved to $RESULTS_ROOT/analysis.txt ==="
