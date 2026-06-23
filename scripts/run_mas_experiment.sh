#!/usr/bin/env bash
# run_mas_experiment.sh — Full multi-agent RAVEL experiment (overnight).
#
# Architecture APPROVED (architecture_acceptance.json: PASS). Runs RAVELTeamAgent
# across the dev split: 2 models x 2 domains x 4 regimes, sequentially (no GPU
# contention). Robust: a failed condition is logged and the run continues.
#
# Launch:
#   cd worktrees/tau2-clean
#   nohup bash /home/xqin5/multiaiagent/scripts/run_mas_experiment.sh \
#       > results/mas_experiment/run.log 2>&1 &

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO="$(dirname "$SCRIPT_DIR")"
TAU2="$REPO/worktrees/tau2-clean"
RUNNER="$SCRIPT_DIR/run_mas_full.py"
OUT="$REPO/results/mas_experiment"
LOG_DIR="$OUT/logs"
mkdir -p "$LOG_DIR"

MAX_STEPS=30
TIMEOUT=1800

log() { echo "[$(date '+%m-%d %H:%M:%S')] $*"; }

cd "$TAU2"

# Gemma4 first (faster, more reliable), then gpt-oss.
declare -A MODELS=(
  [gemma4]="http://127.0.0.1:8005/v1 openai/g4"
  [gptoss]="http://127.0.0.1:8192/v1 openai/gpt-oss"
)
MODEL_ORDER=(gemma4 gptoss)
DOMAINS=(airline retail)
REGIMES=(FullSync Delayed FieldMask ConflictingView)

log "===== MAS FULL EXPERIMENT START ====="
for M in "${MODEL_ORDER[@]}"; do
  read API_BASE MODEL_NAME <<< "${MODELS[$M]}"
  # health check
  if ! curl -s --connect-timeout 5 "$API_BASE/models" >/dev/null 2>&1; then
    log "SKIP model $M — endpoint $API_BASE not responding"
    continue
  fi
  for D in "${DOMAINS[@]}"; do
    for R in "${REGIMES[@]}"; do
      log "RUN $M / $D / $R ..."
      uv run python "$RUNNER" \
        --domain "$D" --regime "$R" \
        --model-api-base "$API_BASE" --model-name "$MODEL_NAME" \
        --output-dir "$OUT/$M" \
        --max-steps $MAX_STEPS --timeout $TIMEOUT --max-concurrency 1 \
        > "$LOG_DIR/${M}_${D}_${R,,}.log" 2>&1
      rc=$?
      if [ $rc -eq 0 ]; then
        grep "RESULT" "$LOG_DIR/${M}_${D}_${R,,}.log" | tail -1 | while read line; do log "$line"; done
      else
        log "FAILED $M / $D / $R (exit $rc) — see $LOG_DIR/${M}_${D}_${R,,}.log; continuing"
      fi
    done
  done
  log "===== model $M done ====="
done
log "===== MAS FULL EXPERIMENT COMPLETE ====="
echo "Aggregate with: python3 $SCRIPT_DIR/aggregate_mas_results.py"
