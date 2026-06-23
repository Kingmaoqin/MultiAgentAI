#!/usr/bin/env bash
# run_missing_gemma4_gptoss.sh — Run missing Gemma4 and gpt-oss conditions.
#
# Missing (no Qwen3 needed):
#   Gemma4 retail:  Delayed, FieldMask
#   Gemma4 telecom: baseline + FullSync + Delayed + FieldMask + ConflictingView
#   gpt-oss retail: Delayed, FieldMask
#   gpt-oss telecom: baseline + FullSync + Delayed + FieldMask + ConflictingView
#
# GPU: Gemma4→GPU2(8005), gpt-oss→GPU1+GPU3(8192). Sequential to avoid contention.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
TAU2_DIR="$REPO_DIR/worktrees/tau2-clean"
RUNNER="$SCRIPT_DIR/run_ravel_exp.py"

GEMMA4_BASE="http://127.0.0.1:8005/v1"
GEMMA4_MODEL="openai/g4"
GPTOSS_BASE="http://127.0.0.1:8192/v1"
GPTOSS_MODEL="openai/gpt-oss"

GEMMA4_OUT="$REPO_DIR/results/multimodel/gemma4"
GPTOSS_OUT="$REPO_DIR/results/multimodel/gptoss"
LOG_DIR="$REPO_DIR/results/multimodel/logs"

MAX_CONCURRENCY=2
MAX_STEPS=25
TIMEOUT=900

mkdir -p "$LOG_DIR"

log() { echo "[$(date '+%H:%M:%S')] $*"; }

cd "$TAU2_DIR"

# ─── Gemma4 retail: Delayed ───────────────────────────────────────────────────
log "=== Gemma4 retail Delayed ==="
uv run python "$RUNNER" \
    --domain retail --split dev \
    --regimes Delayed \
    --agent-type ravel \
    --max-concurrency $MAX_CONCURRENCY --max-steps $MAX_STEPS --timeout $TIMEOUT \
    --output-dir "$GEMMA4_OUT" \
    --model-api-base "$GEMMA4_BASE" --model-name "$GEMMA4_MODEL" \
    2>&1 | tee "$LOG_DIR/gemma4_retail_delayed.log"
log "=== Gemma4 retail Delayed DONE ==="

# ─── Gemma4 retail: FieldMask ─────────────────────────────────────────────────
log "=== Gemma4 retail FieldMask ==="
uv run python "$RUNNER" \
    --domain retail --split dev \
    --regimes FieldMask \
    --agent-type ravel \
    --max-concurrency $MAX_CONCURRENCY --max-steps $MAX_STEPS --timeout $TIMEOUT \
    --output-dir "$GEMMA4_OUT" \
    --model-api-base "$GEMMA4_BASE" --model-name "$GEMMA4_MODEL" \
    2>&1 | tee "$LOG_DIR/gemma4_retail_fieldmask.log"
log "=== Gemma4 retail FieldMask DONE ==="

# ─── Gemma4 telecom: baseline ─────────────────────────────────────────────────
log "=== Gemma4 telecom baseline ==="
uv run python "$RUNNER" \
    --domain telecom --split dev \
    --agent-type baseline \
    --max-concurrency $MAX_CONCURRENCY --max-steps $MAX_STEPS --timeout $TIMEOUT \
    --output-dir "$GEMMA4_OUT" \
    --model-api-base "$GEMMA4_BASE" --model-name "$GEMMA4_MODEL" \
    2>&1 | tee "$LOG_DIR/gemma4_telecom_baseline.log"
log "=== Gemma4 telecom baseline DONE ==="

# ─── Gemma4 telecom: all RAVEL regimes ───────────────────────────────────────
for REGIME in FullSync Delayed FieldMask ConflictingView; do
    log "=== Gemma4 telecom $REGIME ==="
    uv run python "$RUNNER" \
        --domain telecom --split dev \
        --regimes "$REGIME" \
        --agent-type ravel \
        --max-concurrency $MAX_CONCURRENCY --max-steps $MAX_STEPS --timeout $TIMEOUT \
        --output-dir "$GEMMA4_OUT" \
        --model-api-base "$GEMMA4_BASE" --model-name "$GEMMA4_MODEL" \
        2>&1 | tee "$LOG_DIR/gemma4_telecom_${REGIME,,}.log"
    log "=== Gemma4 telecom $REGIME DONE ==="
done

log "======== ALL GEMMA4 MISSING EXPERIMENTS COMPLETE ========"

# ─── gpt-oss retail: Delayed ──────────────────────────────────────────────────
log "=== gpt-oss retail Delayed ==="
uv run python "$RUNNER" \
    --domain retail --split dev \
    --regimes Delayed \
    --agent-type ravel \
    --max-concurrency $MAX_CONCURRENCY --max-steps $MAX_STEPS --timeout $TIMEOUT \
    --output-dir "$GPTOSS_OUT" \
    --model-api-base "$GPTOSS_BASE" --model-name "$GPTOSS_MODEL" \
    2>&1 | tee "$LOG_DIR/gptoss_retail_delayed.log"
log "=== gpt-oss retail Delayed DONE ==="

# ─── gpt-oss retail: FieldMask ────────────────────────────────────────────────
log "=== gpt-oss retail FieldMask ==="
uv run python "$RUNNER" \
    --domain retail --split dev \
    --regimes FieldMask \
    --agent-type ravel \
    --max-concurrency $MAX_CONCURRENCY --max-steps $MAX_STEPS --timeout $TIMEOUT \
    --output-dir "$GPTOSS_OUT" \
    --model-api-base "$GPTOSS_BASE" --model-name "$GPTOSS_MODEL" \
    2>&1 | tee "$LOG_DIR/gptoss_retail_fieldmask.log"
log "=== gpt-oss retail FieldMask DONE ==="

# ─── gpt-oss telecom: baseline ────────────────────────────────────────────────
log "=== gpt-oss telecom baseline ==="
uv run python "$RUNNER" \
    --domain telecom --split dev \
    --agent-type baseline \
    --max-concurrency $MAX_CONCURRENCY --max-steps $MAX_STEPS --timeout $TIMEOUT \
    --output-dir "$GPTOSS_OUT" \
    --model-api-base "$GPTOSS_BASE" --model-name "$GPTOSS_MODEL" \
    2>&1 | tee "$LOG_DIR/gptoss_telecom_baseline.log"
log "=== gpt-oss telecom baseline DONE ==="

# ─── gpt-oss telecom: all RAVEL regimes ──────────────────────────────────────
for REGIME in FullSync Delayed FieldMask ConflictingView; do
    log "=== gpt-oss telecom $REGIME ==="
    uv run python "$RUNNER" \
        --domain telecom --split dev \
        --regimes "$REGIME" \
        --agent-type ravel \
        --max-concurrency $MAX_CONCURRENCY --max-steps $MAX_STEPS --timeout $TIMEOUT \
        --output-dir "$GPTOSS_OUT" \
        --model-api-base "$GPTOSS_BASE" --model-name "$GPTOSS_MODEL" \
        2>&1 | tee "$LOG_DIR/gptoss_telecom_${REGIME,,}.log"
    log "=== gpt-oss telecom $REGIME DONE ==="
done

log "======== ALL gpt-oss MISSING EXPERIMENTS COMPLETE ========"
log "Next: run Qwen3 retail missing (FullSync/FieldMask/ConflictingView)"
log "  Requires: kill port 8006 Gemma4, then start Qwen3 on GPU0 port 8190"
