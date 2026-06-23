#!/usr/bin/env bash
# run_mas_safety_v2.sh — Cross-model + FieldMask + token-cost extension.
#
# Both models (Gemma4, gpt-oss) x 4 regimes (FullSync, Delayed, RoleAwareFieldMask,
# ConflictingView) x gate {on,off}, airline domain (50 tasks). Fresh runs so token
# data is consistent. Robust sequential; continues on per-condition failure.
#
# Launch:
#   cd worktrees/tau2-clean
#   nohup bash /home/xqin5/multiaiagent/scripts/run_mas_safety_v2.sh \
#       > /home/xqin5/multiaiagent/results/mas_safety_v2/run.log 2>&1 &

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO="$(dirname "$SCRIPT_DIR")"
RUNNER="$SCRIPT_DIR/run_mas_safety.py"
LOG_DIR="$REPO/results/mas_safety_v2/logs"
mkdir -p "$LOG_DIR"

DOMAIN=airline
NTASKS=50
MAX_STEPS=20
TIMEOUT=1200
CONC=4
REGIMES=(FullSync Delayed RoleAwareFieldMask ConflictingView)
GATES=(on off)

# model -> "api_base served_model_name out_subdir"
declare -A MODELS=(
  [gemma4]="http://127.0.0.1:8005/v1 openai/g4 gemma4"
  [gptoss]="http://127.0.0.1:8192/v1 openai/gpt-oss gptoss"
)
MODEL_ORDER=(gemma4 gptoss)

log() { echo "[$(date '+%m-%d %H:%M:%S')] $*"; }
log "===== MAS SAFETY v2 (cross-model + FieldMask + tokens) START ====="

for M in "${MODEL_ORDER[@]}"; do
  read API_BASE MODEL_NAME SUB <<< "${MODELS[$M]}"
  if ! curl -s --connect-timeout 5 "$API_BASE/models" >/dev/null 2>&1; then
    log "SKIP $M — endpoint $API_BASE not responding"; continue
  fi
  OUT="$REPO/results/mas_safety_v2/$SUB"
  for R in "${REGIMES[@]}"; do
    for G in "${GATES[@]}"; do
      log "RUN $M / $DOMAIN / $R / gate=$G ..."
      uv run python "$RUNNER" \
        --domain "$DOMAIN" --regime "$R" --gate "$G" \
        --model-api-base "$API_BASE" --model-name "$MODEL_NAME" \
        --output-dir "$OUT" --n-tasks $NTASKS \
        --max-steps $MAX_STEPS --timeout $TIMEOUT --max-concurrency $CONC \
        > "$LOG_DIR/${M}_${R,,}_gate${G}.log" 2>&1
      if [ $? -eq 0 ]; then
        grep "RESULT" "$LOG_DIR/${M}_${R,,}_gate${G}.log" | tail -1 | while read l; do log "$l"; done
      else
        log "FAILED $M / $R / gate=$G — see log; continuing"
      fi
    done
  done
  log "===== model $M done ====="
done
log "===== MAS SAFETY v2 COMPLETE ====="
