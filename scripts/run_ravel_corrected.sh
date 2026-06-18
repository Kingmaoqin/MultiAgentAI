#!/usr/bin/env bash
# run_ravel_corrected.sh — Sequential RAVEL experiment re-run with fixed CommitGate.
#
# CRITICAL FIX applied before this run:
#   CommitGate(schemas={}) now returns verdict="commit" (permissive) not "abstain".
#   Previous runs all got 0.0 because every write was silently blocked.
#
# Run ONE domain at a time (no GPU contention).
# Baseline uses llm_agent_gt; RAVEL uses llm_agent (no GT hints).
#
# Usage:
#   bash scripts/run_ravel_corrected.sh          # all domains
#   bash scripts/run_ravel_corrected.sh airline  # single domain
#   bash scripts/run_ravel_corrected.sh retail telecom

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
TAU2_DIR="$REPO_DIR/worktrees/tau2-clean"
RESULTS_ROOT="$REPO_DIR/results/ravel_corrected"
LOG_DIR="$RESULTS_ROOT/logs"
RUNNER="$SCRIPT_DIR/run_ravel_exp.py"

# Run settings — generous limits, sequential
MAX_CONCURRENCY=2    # 2 tasks in parallel per domain run (GPU is free when sequential)
MAX_STEPS=25         # 25 steps per task
TIMEOUT=900          # 15 minutes per task (soft timeout)
REGIMES="FullSync Delayed FieldMask ConflictingView"

DOMAINS=("airline" "retail" "telecom")
if [[ $# -gt 0 ]]; then
    DOMAINS=("$@")
fi

mkdir -p "$LOG_DIR"

cd "$TAU2_DIR"

echo "==========================================="
echo " RAVEL Corrected Experiment Run"
echo " Domains: ${DOMAINS[*]}"
echo " Regimes: $REGIMES"
echo " Max steps: $MAX_STEPS  Timeout: ${TIMEOUT}s"
echo " Results: $RESULTS_ROOT"
echo "==========================================="

for DOMAIN in "${DOMAINS[@]}"; do
    echo ""
    echo "--- Domain: $DOMAIN ---"

    # 1. RAVEL regimes
    for REGIME in $REGIMES; do
        echo "  Running RAVEL-$REGIME [$DOMAIN]..."
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
        # Show quick summary
        grep "Result:" "$LOG" 2>/dev/null || echo "    (no result line yet)"
    done

    echo "  Domain $DOMAIN done."
done

echo ""
echo "==========================================="
echo " All corrected RAVEL runs complete."
echo " Results in: $RESULTS_ROOT"
echo " Run: python3 scripts/analyze_results.py to compare"
echo "==========================================="
