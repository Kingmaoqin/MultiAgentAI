#!/usr/bin/env bash
# run_mas_safety.sh — Write-safety experiment (overnight, RAVEL's core thesis).
#
# Gemma4, full airline (50) then retail (50), 3 regimes x gate {on,off}.
# Robust: a failed condition is logged and the run continues.
#
# Launch:
#   cd worktrees/tau2-clean
#   nohup bash /home/xqin5/multiaiagent/scripts/run_mas_safety.sh \
#       > /home/xqin5/multiaiagent/results/mas_safety/run.log 2>&1 &

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO="$(dirname "$SCRIPT_DIR")"
RUNNER="$SCRIPT_DIR/run_mas_safety.py"
OUT="$REPO/results/mas_safety/gemma4"
LOG_DIR="$REPO/results/mas_safety/logs"
mkdir -p "$LOG_DIR"

API_BASE="http://127.0.0.1:8005/v1"
MODEL="openai/g4"
MAX_STEPS=20
TIMEOUT=900
CONC=4

# airline first (faster, write-heavy), 50 tasks; then retail, 50 tasks.
declare -A NTASKS=( [airline]=50 [retail]=50 )
DOMAINS=(airline retail)
# FullSync = control (no perturbation); Delayed + ConflictingView = adverse.
REGIMES=(FullSync Delayed ConflictingView)
GATES=(on off)

log() { echo "[$(date '+%m-%d %H:%M:%S')] $*"; }
log "===== MAS WRITE-SAFETY EXPERIMENT START ====="

for D in "${DOMAINS[@]}"; do
  for R in "${REGIMES[@]}"; do
    for G in "${GATES[@]}"; do
      log "RUN $D / $R / gate=$G ..."
      uv run python "$RUNNER" \
        --domain "$D" --regime "$R" --gate "$G" \
        --model-api-base "$API_BASE" --model-name "$MODEL" \
        --output-dir "$OUT" --n-tasks "${NTASKS[$D]}" \
        --max-steps $MAX_STEPS --timeout $TIMEOUT --max-concurrency $CONC \
        > "$LOG_DIR/${D}_${R,,}_gate${G}.log" 2>&1
      if [ $? -eq 0 ]; then
        grep "RESULT" "$LOG_DIR/${D}_${R,,}_gate${G}.log" | tail -1 | while read l; do log "$l"; done
      else
        log "FAILED $D / $R / gate=$G — see log; continuing"
      fi
    done
  done
  log "===== domain $D done ====="
done
log "===== MAS WRITE-SAFETY EXPERIMENT COMPLETE ====="
echo "Aggregate: python3 $SCRIPT_DIR/aggregate_safety.py"
