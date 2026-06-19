#!/usr/bin/env bash
# run_missing_experiments.sh — Run all missing experiment conditions.
#
# Missing:
#   Qwen3  retail:  FullSync, FieldMask, ConflictingView
#   Gemma4 retail:  Delayed, FieldMask
#   Gemma4 telecom: baseline + FullSync + Delayed + FieldMask + ConflictingView
#   gpt-oss retail: Delayed, FieldMask
#   gpt-oss telecom: baseline + FullSync + Delayed + FieldMask + ConflictingView
#
# GPU layout:
#   GPU0 → freed (was Gemma4 8006, duplicate)  → will host Qwen3 (port 8190)
#   GPU1+GPU3 → gpt-oss 8192 (TP=2)
#   GPU2 → Gemma4 8005
#
# Usage:
#   nohup bash scripts/run_missing_experiments.sh > results/multimodel/logs/missing_run_$(date +%Y%m%d_%H%M%S).log 2>&1 &

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
TAU2_DIR="$REPO_DIR/worktrees/tau2-clean"
RUNNER="$SCRIPT_DIR/run_ravel_exp.py"

GEMMA4_BASE="http://127.0.0.1:8005/v1"
GEMMA4_MODEL="g4"
GPTOSS_BASE="http://127.0.0.1:8192/v1"
GPTOSS_MODEL="gpt-oss"
QWEN3_BASE="http://127.0.0.1:8190/v1"
QWEN3_MODEL="openai/q"
QWEN3_MODEL_PATH="/home/xqin5/agentsearch/models/Qwen3.6-27B"

GEMMA4_OUT="$REPO_DIR/results/multimodel/gemma4"
GPTOSS_OUT="$REPO_DIR/results/multimodel/gptoss"
QWEN3_OUT="$REPO_DIR/results/ravel_corrected"
LOG_DIR="$REPO_DIR/results/multimodel/logs"

MAX_CONCURRENCY=2
MAX_STEPS=25
TIMEOUT=900

mkdir -p "$LOG_DIR"

log() { echo "[$(date '+%H:%M:%S')] $*"; }

# ─── Step 0: Kill duplicate Gemma4 on port 8006, free GPU0 for Qwen3 ──────────
log "=== Step 0: Free GPU0 by stopping duplicate Gemma4 (port 8006) ==="
GEMMA4_8006_PID=$(ps aux | grep 'vllm serve.*port 8006' | grep -v grep | awk '{print $2}' | head -1)
if [ -n "$GEMMA4_8006_PID" ]; then
    log "Killing Gemma4 port 8006 (PID $GEMMA4_8006_PID)..."
    kill "$GEMMA4_8006_PID" || true
    sleep 5
    log "GPU0 freed."
else
    log "Port 8006 not running, GPU0 may already be free."
fi

# ─── Step 1: Start Qwen3 on GPU0 ──────────────────────────────────────────────
log "=== Step 1: Starting Qwen3 on GPU0 (port 8190) ==="
QWEN3_LOG="$LOG_DIR/qwen3_server_$(date +%Y%m%d_%H%M%S).log"
CUDA_VISIBLE_DEVICES=0 conda run -n p08_skilloverload \
    vllm serve "$QWEN3_MODEL_PATH" \
    --port 8190 \
    --served-model-name q \
    --enable-auto-tool-choice \
    --tool-call-parser hermes \
    --gpu-memory-utilization 0.92 \
    --max-model-len 32768 \
    --max-num-batched-tokens 16384 \
    --trust-remote-code \
    > "$QWEN3_LOG" 2>&1 &
QWEN3_SERVER_PID=$!
log "Qwen3 server starting (PID $QWEN3_SERVER_PID), log: $QWEN3_LOG"

# ─── Step 2: Run Gemma4 missing experiments (port 8005, GPU2) ─────────────────
log "=== Step 2: Gemma4 missing experiments ==="
cd "$TAU2_DIR"

# Gemma4 retail: Delayed
log "  Gemma4 retail Delayed..."
uv run python "$RUNNER" \
    --domain retail --split dev \
    --regimes Delayed \
    --agent-type ravel \
    --max-concurrency $MAX_CONCURRENCY --max-steps $MAX_STEPS --timeout $TIMEOUT \
    --output-dir "$GEMMA4_OUT" \
    --model-api-base "$GEMMA4_BASE" --model-name "$GEMMA4_MODEL" \
    > "$LOG_DIR/gemma4_retail_delayed.log" 2>&1
log "  Gemma4 retail Delayed done."

# Gemma4 retail: FieldMask
log "  Gemma4 retail FieldMask..."
uv run python "$RUNNER" \
    --domain retail --split dev \
    --regimes FieldMask \
    --agent-type ravel \
    --max-concurrency $MAX_CONCURRENCY --max-steps $MAX_STEPS --timeout $TIMEOUT \
    --output-dir "$GEMMA4_OUT" \
    --model-api-base "$GEMMA4_BASE" --model-name "$GEMMA4_MODEL" \
    > "$LOG_DIR/gemma4_retail_fieldmask.log" 2>&1
log "  Gemma4 retail FieldMask done."

# Gemma4 telecom: baseline
log "  Gemma4 telecom baseline..."
uv run python "$RUNNER" \
    --domain telecom --split dev \
    --agent-type baseline \
    --max-concurrency $MAX_CONCURRENCY --max-steps $MAX_STEPS --timeout $TIMEOUT \
    --output-dir "$GEMMA4_OUT" \
    --model-api-base "$GEMMA4_BASE" --model-name "$GEMMA4_MODEL" \
    > "$LOG_DIR/gemma4_telecom_baseline.log" 2>&1
log "  Gemma4 telecom baseline done."

# Gemma4 telecom: all RAVEL regimes
for REGIME in FullSync Delayed FieldMask ConflictingView; do
    log "  Gemma4 telecom $REGIME..."
    uv run python "$RUNNER" \
        --domain telecom --split dev \
        --regimes "$REGIME" \
        --agent-type ravel \
        --max-concurrency $MAX_CONCURRENCY --max-steps $MAX_STEPS --timeout $TIMEOUT \
        --output-dir "$GEMMA4_OUT" \
        --model-api-base "$GEMMA4_BASE" --model-name "$GEMMA4_MODEL" \
        > "$LOG_DIR/gemma4_telecom_${REGIME,,}.log" 2>&1
    log "  Gemma4 telecom $REGIME done."
done

log "=== Gemma4 experiments complete ==="

# ─── Step 3: Run gpt-oss missing experiments (port 8192, GPU1+GPU3) ──────────
log "=== Step 3: gpt-oss missing experiments ==="

# gpt-oss retail: Delayed
log "  gpt-oss retail Delayed..."
uv run python "$RUNNER" \
    --domain retail --split dev \
    --regimes Delayed \
    --agent-type ravel \
    --max-concurrency $MAX_CONCURRENCY --max-steps $MAX_STEPS --timeout $TIMEOUT \
    --output-dir "$GPTOSS_OUT" \
    --model-api-base "$GPTOSS_BASE" --model-name "$GPTOSS_MODEL" \
    > "$LOG_DIR/gptoss_retail_delayed.log" 2>&1
log "  gpt-oss retail Delayed done."

# gpt-oss retail: FieldMask
log "  gpt-oss retail FieldMask..."
uv run python "$RUNNER" \
    --domain retail --split dev \
    --regimes FieldMask \
    --agent-type ravel \
    --max-concurrency $MAX_CONCURRENCY --max-steps $MAX_STEPS --timeout $TIMEOUT \
    --output-dir "$GPTOSS_OUT" \
    --model-api-base "$GPTOSS_BASE" --model-name "$GPTOSS_MODEL" \
    > "$LOG_DIR/gptoss_retail_fieldmask.log" 2>&1
log "  gpt-oss retail FieldMask done."

# gpt-oss telecom: baseline
log "  gpt-oss telecom baseline..."
uv run python "$RUNNER" \
    --domain telecom --split dev \
    --agent-type baseline \
    --max-concurrency $MAX_CONCURRENCY --max-steps $MAX_STEPS --timeout $TIMEOUT \
    --output-dir "$GPTOSS_OUT" \
    --model-api-base "$GPTOSS_BASE" --model-name "$GPTOSS_MODEL" \
    > "$LOG_DIR/gptoss_telecom_baseline.log" 2>&1
log "  gpt-oss telecom baseline done."

# gpt-oss telecom: all RAVEL regimes
for REGIME in FullSync Delayed FieldMask ConflictingView; do
    log "  gpt-oss telecom $REGIME..."
    uv run python "$RUNNER" \
        --domain telecom --split dev \
        --regimes "$REGIME" \
        --agent-type ravel \
        --max-concurrency $MAX_CONCURRENCY --max-steps $MAX_STEPS --timeout $TIMEOUT \
        --output-dir "$GPTOSS_OUT" \
        --model-api-base "$GPTOSS_BASE" --model-name "$GPTOSS_MODEL" \
        > "$LOG_DIR/gptoss_telecom_${REGIME,,}.log" 2>&1
    log "  gpt-oss telecom $REGIME done."
done

log "=== gpt-oss experiments complete ==="

# ─── Step 4: Wait for Qwen3 server, then run Qwen3 missing retail ─────────────
log "=== Step 4: Waiting for Qwen3 server to be ready (port 8190) ==="
MAX_WAIT=300
WAITED=0
until curl -s --connect-timeout 3 http://127.0.0.1:8190/v1/models > /dev/null 2>&1; do
    sleep 10
    WAITED=$((WAITED + 10))
    if [ $WAITED -ge $MAX_WAIT ]; then
        log "ERROR: Qwen3 server did not start within ${MAX_WAIT}s. Check $QWEN3_LOG"
        exit 1
    fi
    log "  Still waiting for Qwen3... (${WAITED}s)"
done
log "Qwen3 server ready."

# Qwen3 retail: FullSync
log "  Qwen3 retail FullSync..."
uv run python "$RUNNER" \
    --domain retail --split dev \
    --regimes FullSync \
    --agent-type ravel \
    --max-concurrency $MAX_CONCURRENCY --max-steps $MAX_STEPS --timeout $TIMEOUT \
    --output-dir "$QWEN3_OUT" \
    --model-api-base "$QWEN3_BASE" --model-name "$QWEN3_MODEL" \
    > "$LOG_DIR/qwen3_retail_fullsync.log" 2>&1
log "  Qwen3 retail FullSync done."

# Qwen3 retail: FieldMask
log "  Qwen3 retail FieldMask..."
uv run python "$RUNNER" \
    --domain retail --split dev \
    --regimes FieldMask \
    --agent-type ravel \
    --max-concurrency $MAX_CONCURRENCY --max-steps $MAX_STEPS --timeout $TIMEOUT \
    --output-dir "$QWEN3_OUT" \
    --model-api-base "$QWEN3_BASE" --model-name "$QWEN3_MODEL" \
    > "$LOG_DIR/qwen3_retail_fieldmask.log" 2>&1
log "  Qwen3 retail FieldMask done."

# Qwen3 retail: ConflictingView
log "  Qwen3 retail ConflictingView..."
uv run python "$RUNNER" \
    --domain retail --split dev \
    --regimes ConflictingView \
    --agent-type ravel \
    --max-concurrency $MAX_CONCURRENCY --max-steps $MAX_STEPS --timeout $TIMEOUT \
    --output-dir "$QWEN3_OUT" \
    --model-api-base "$QWEN3_BASE" --model-name "$QWEN3_MODEL" \
    > "$LOG_DIR/qwen3_retail_conflictingview.log" 2>&1
log "  Qwen3 retail ConflictingView done."

log "=== ALL MISSING EXPERIMENTS COMPLETE ==="
log "Results in:"
log "  Gemma4: $GEMMA4_OUT"
log "  gpt-oss: $GPTOSS_OUT"
log "  Qwen3:  $QWEN3_OUT"
