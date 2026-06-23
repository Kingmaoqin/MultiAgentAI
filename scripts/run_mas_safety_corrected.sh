#!/usr/bin/env bash
# run_mas_safety_corrected.sh — Corrected write-safety experiment (post-audit).
#
# Fixes baked in via run_mas_safety.py:
#   - oracle-based non-circular unsafe_executed (both gates)
#   - real FieldMask masking; per-domain justified decision field
#   - FIXED user-simulator model (Gemma4) across ALL agent conditions
#   - infra-failed trajectories excluded; valid N reported; per-seed conditions
#
# Matrix: 2 agent models x 4 regimes x 2 gates x 3 seeds, airline n=50  = 48 conditions.
# Robust sequential, continues on per-condition failure. Gemma4 first.
#
# Launch:
#   cd worktrees/tau2-clean
#   nohup bash /home/xqin5/multiaiagent/scripts/run_mas_safety_corrected.sh \
#       > /home/xqin5/multiaiagent/results/mas_safety_corrected/run.log 2>&1 &

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO="$(dirname "$SCRIPT_DIR")"
RUNNER="$SCRIPT_DIR/run_mas_safety.py"
LOG_DIR="$REPO/results/mas_safety_corrected/logs"
mkdir -p "$LOG_DIR"

DOMAIN=airline
NTASKS=50
MAX_STEPS=20
TIMEOUT=1200
CONC=4
# FieldMask dropped from the main matrix: in the pilot, masking the decision field
# suppressed agent writes (~0 write events), so it is uninformative for the unsafe-write
# metric. Documented as a limitation; staleness regimes (Delayed/ConflictingView) carry
# the result, with FullSync as the no-perturbation control.
REGIMES=(FullSync Delayed ConflictingView)
GATES=(on off)
SEEDS=(300 301 302)

# FIXED user-simulator model for ALL conditions (removes user-model confound).
USER_BASE="http://127.0.0.1:8005/v1"
USER_MODEL="openai/g4"

# agent model -> "api_base served_model_name out_subdir"
declare -A MODELS=(
  [gemma4]="http://127.0.0.1:8005/v1 openai/g4 gemma4"
  [gptoss]="http://127.0.0.1:8192/v1 openai/gpt-oss gptoss"
)
MODEL_ORDER=(gemma4 gptoss)

log() { echo "[$(date '+%m-%d %H:%M:%S')] $*"; }
log "===== MAS SAFETY CORRECTED START (fixed user=$USER_MODEL) ====="

for M in "${MODEL_ORDER[@]}"; do
  read API_BASE MODEL_NAME SUB <<< "${MODELS[$M]}"
  if ! curl -s --connect-timeout 5 "$API_BASE/models" >/dev/null 2>&1; then
    log "SKIP $M — endpoint $API_BASE not responding"; continue
  fi
  OUT="$REPO/results/mas_safety_corrected/$SUB"
  for R in "${REGIMES[@]}"; do
    for G in "${GATES[@]}"; do
      for S in "${SEEDS[@]}"; do
        log "RUN $M / $R / gate=$G / seed=$S ..."
        uv run python "$RUNNER" \
          --domain "$DOMAIN" --regime "$R" --gate "$G" \
          --model-api-base "$API_BASE" --model-name "$MODEL_NAME" \
          --user-api-base "$USER_BASE" --user-model "$USER_MODEL" \
          --output-dir "$OUT" --n-tasks $NTASKS --seed $S \
          --max-steps $MAX_STEPS --timeout $TIMEOUT --max-concurrency $CONC \
          > "$LOG_DIR/${M}_${R,,}_gate${G}_seed${S}.log" 2>&1
        if [ $? -eq 0 ]; then
          grep "RESULT" "$LOG_DIR/${M}_${R,,}_gate${G}_seed${S}.log" | tail -1 | while read l; do log "$l"; done
        else
          log "FAILED $M / $R / gate=$G / seed=$S — see log; continuing"
        fi
      done
    done
  done
  log "===== agent model $M done ====="
done
log "===== MAS SAFETY CORRECTED COMPLETE ====="
