#!/usr/bin/env bash
# run_multiagent_exp.sh — Run true 4-role multi-agent RAVEL experiments.
#
# Architecture per turn:
#   Supervisor LLM  → sub-goal + risk assessment
#   Policy Agent LLM → required evidence schema
#   Tool Worker LLM  → tool calls (read) or candidate write
#   Commit Verifier LLM → commit / reconcile / abstain (only on writes)
#
# All 4 roles use the same model (same vLLM endpoint, different system prompts).
#
# Usage:
#   nohup bash scripts/run_multiagent_exp.sh > results/multiagent/logs/run_TIMESTAMP.log 2>&1 &

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
TAU2_DIR="$REPO_DIR/worktrees/tau2-clean"
RUNNER="$SCRIPT_DIR/run_ravel_exp.py"

GEMMA4_BASE="http://127.0.0.1:8005/v1"
GEMMA4_MODEL="openai/g4"
GPTOSS_BASE="http://127.0.0.1:8192/v1"
GPTOSS_MODEL="openai/gpt-oss"

OUT_ROOT="$REPO_DIR/results/multiagent"
LOG_DIR="$OUT_ROOT/logs"

# Multi-agent runs need more time per task (3-4 LLM calls per turn vs 1)
MAX_CONCURRENCY=1   # serial to avoid GPU memory pressure
MAX_STEPS=25
TIMEOUT=1800        # 30 min — 3-4x LLM calls per turn

mkdir -p "$LOG_DIR"

log() { echo "[$(date '+%H:%M:%S')] $*"; }

cd "$TAU2_DIR"

# ─── Gemma4: airline × 4 regimes ──────────────────────────────────────────────
log "=== Gemma4 multi-agent airline ==="
for REGIME in FullSync Delayed FieldMask ConflictingView; do
    log "  Gemma4 MA airline $REGIME..."
    uv run python "$RUNNER" \
        --domain airline --split dev \
        --regimes "$REGIME" \
        --agent-type multiagent \
        --max-concurrency $MAX_CONCURRENCY \
        --max-steps $MAX_STEPS \
        --timeout $TIMEOUT \
        --output-dir "$OUT_ROOT/gemma4" \
        --model-api-base "$GEMMA4_BASE" \
        --model-name "$GEMMA4_MODEL" \
        2>&1 | tee "$LOG_DIR/gemma4_airline_ma_${REGIME,,}.log"
    log "  Done: $REGIME"
done

# ─── Gemma4: retail × 4 regimes ───────────────────────────────────────────────
log "=== Gemma4 multi-agent retail ==="
for REGIME in FullSync Delayed FieldMask ConflictingView; do
    log "  Gemma4 MA retail $REGIME..."
    uv run python "$RUNNER" \
        --domain retail --split dev \
        --regimes "$REGIME" \
        --agent-type multiagent \
        --max-concurrency $MAX_CONCURRENCY \
        --max-steps $MAX_STEPS \
        --timeout $TIMEOUT \
        --output-dir "$OUT_ROOT/gemma4" \
        --model-api-base "$GEMMA4_BASE" \
        --model-name "$GEMMA4_MODEL" \
        2>&1 | tee "$LOG_DIR/gemma4_retail_ma_${REGIME,,}.log"
    log "  Done: $REGIME"
done

log "======== Gemma4 multi-agent experiments COMPLETE ========"

# ─── gpt-oss: airline × 4 regimes ─────────────────────────────────────────────
log "=== gpt-oss multi-agent airline ==="
for REGIME in FullSync Delayed FieldMask ConflictingView; do
    log "  gpt-oss MA airline $REGIME..."
    uv run python "$RUNNER" \
        --domain airline --split dev \
        --regimes "$REGIME" \
        --agent-type multiagent \
        --max-concurrency $MAX_CONCURRENCY \
        --max-steps $MAX_STEPS \
        --timeout $TIMEOUT \
        --output-dir "$OUT_ROOT/gptoss" \
        --model-api-base "$GPTOSS_BASE" \
        --model-name "$GPTOSS_MODEL" \
        2>&1 | tee "$LOG_DIR/gptoss_airline_ma_${REGIME,,}.log"
    log "  Done: $REGIME"
done

# ─── gpt-oss: retail × 4 regimes ──────────────────────────────────────────────
log "=== gpt-oss multi-agent retail ==="
for REGIME in FullSync Delayed FieldMask ConflictingView; do
    log "  gpt-oss MA retail $REGIME..."
    uv run python "$RUNNER" \
        --domain retail --split dev \
        --regimes "$REGIME" \
        --agent-type multiagent \
        --max-concurrency $MAX_CONCURRENCY \
        --max-steps $MAX_STEPS \
        --timeout $TIMEOUT \
        --output-dir "$OUT_ROOT/gptoss" \
        --model-api-base "$GPTOSS_BASE" \
        --model-name "$GPTOSS_MODEL" \
        2>&1 | tee "$LOG_DIR/gptoss_retail_ma_${REGIME,,}.log"
    log "  Done: $REGIME"
done

log "======== ALL MULTI-AGENT EXPERIMENTS COMPLETE ========"
log "Results in: $OUT_ROOT"
