# RUNBOOK

Complete reproduction commands from a clean checkout.  Run in this order.

## 1. Environment Setup

```bash
# tau2 benchmark environment for formal runs (clean detached worktree)
cd /home/xqin5/multiaiagent/worktrees/tau2-clean
uv run tau2 check-data

# ravel_core development environment (no extra deps needed — stdlib only)
cd /home/xqin5/multiaiagent
PYTHONPATH=/home/xqin5/multiaiagent/src python -c "import ravel_core; print('OK')"
```

## 2. Benchmark Validation

```bash
cd /home/xqin5/multiaiagent/worktrees/tau2-clean
uv run tau2 check-data
# Record commit hash (freeze benchmark version):
git rev-parse HEAD
git status --short  # must be empty for formal runs

# Original asset note:
# /home/xqin5/tau2-bench remains dirty with a local message.py parser patch.
# Do not use it for formal benchmark claims unless explicitly running a
# patched-benchmark sensitivity check.
```

## 3. Model Endpoint Validation

```bash
# Check all active endpoints
curl -s http://127.0.0.1:8005/v1/models | python3 -m json.tool
curl -s http://127.0.0.1:8190/v1/models | python3 -m json.tool
curl -s http://127.0.0.1:8200/v1/models | python3 -m json.tool

# Record GPU inventory
nvidia-smi
```

## 4. Unit + Integration Tests

```bash
cd /home/xqin5/multiaiagent
PYTHONPATH=/home/xqin5/multiaiagent/src pytest tests/ -q
# Expected: 58 passed
```

## 5. Task Audit (§3.2)

```bash
cd /home/xqin5/multiaiagent
PYTHONPATH=src python scripts/task_audit.py \
    --tau2-root /home/xqin5/multiaiagent/worktrees/tau2-clean \
    --output-dir artifacts/task_audit \
    --domains airline retail telecom
# Output: artifacts/task_audit/{all_tasks,included_tasks,excluded_tasks}.csv
```

## 6. Generate Task Splits (§3.3)

```bash
PYTHONPATH=src python scripts/generate_splits.py \
    --included-csv artifacts/task_audit/included_tasks.csv \
    --output-dir artifacts/task_audit \
    --seed 20260615
# Output: artifacts/task_audit/splits_{dev,pilot,held_out}.csv
# IMPORTANT: freeze splits before any experiment; do not regenerate after pilot
```

## 7. Stage 0 Smoke Baseline

```bash
cd /home/xqin5/multiaiagent/worktrees/tau2-clean

# Mock domain smoke (already complete — results in results/baseline_reproduction/tau2_mock_qwen_smoke)
uv run tau2 run --domain mock --task-ids create_task_1 --num-trials 1 \
  --agent llm_agent_gt --agent-llm openai/q \
  --agent-llm-args '{"temperature":0.0,"api_base":"http://127.0.0.1:8200/v1","api_key":"EMPTY"}' \
  --user user_simulator --user-llm openai/q \
  --user-llm-args '{"temperature":0.0,"api_base":"http://127.0.0.1:8200/v1","api_key":"EMPTY"}' \
  --max-concurrency 1 --max-steps 12 --timeout 180 --seed 101 \
  --save-to /home/xqin5/multiaiagent/results/baseline_reproduction/tau2_mock_qwen_smoke \
  --log-level INFO

# Per-domain smoke (run after endpoint/model confirmed).
# 2026-06-15 note: airline task 32 on Qwen3.6-27B was interrupted after
# ~8 minutes with zero completed simulations; this is NOT a reproduced baseline.
# Replace DOMAIN with airline, retail, or telecom
# Replace TASK_ID with a dev-set task from splits_dev.csv
uv run tau2 run --domain DOMAIN --task-ids TASK_ID --num-trials 1 \
  --agent llm_agent_gt --agent-llm openai/q \
  --agent-llm-args '{"temperature":0.0,"api_base":"http://127.0.0.1:8200/v1","api_key":"EMPTY"}' \
  --user user_simulator --user-llm openai/q \
  --user-llm-args '{"temperature":0.0,"api_base":"http://127.0.0.1:8200/v1","api_key":"EMPTY"}' \
  --max-concurrency 1 --max-steps 30 --timeout 300 --seed 101 \
  --save-to /home/xqin5/multiaiagent/results/baseline_reproduction/tau2_DOMAIN_smoke
```

## 8. Pilot (Small Paired Run)

**GATE:** patch_002 must be APPROVED by independent reviewer before pilot.

```bash
# Pilot: 10 paired tasks per domain, FullSync + one perturbation regime,
# dev set only, one model, 1 repetition.
# Exact command to be finalised after baseline smoke and reviewer approval.
```

## 9. Core Experiment (Stage A + B)

**GATES (all must pass):**
- GO/NO-GO checklist fully PASS
- Held-out split frozen
- patch_002 reviewer APPROVED
- Airline expansion rule documented and approved
- No held-out leakage (dev/pilot results must not influence method config)

## 10. Ablation (Stage C)

Run on dev/pilot set only (NOT held-out):
`No-MSE`, `No-Delta`, `No-Provenance`, `No-Gate`, `No-Selective-Requery`,
`Fixed-Low-Budget`, `Fixed-Normal-Budget`, `Fixed-High-Budget`, `Oracle-Schema`, `No-Version-Check`.

## 11. Result Validation

```bash
# After experiments complete, validate before any analysis:
# (script to be implemented when raw results exist)
# Checks: duplicate trials, missing tasks, config mismatch,
#         invalid token count, parser failure, missing final state
```

## 12. Statistical Analysis

```bash
# Paired bootstrap and mixed-effects models (analysis scripts to be added)
python analysis/paired_bootstrap.py \
    --results-dir results/validated \
    --output-dir analysis/outputs

python analysis/mixed_effects.py \
    --results-dir results/validated \
    --output-dir analysis/outputs
```

## 13. Figure Generation

```bash
# (Plotting scripts to be added after analysis outputs exist)
python scripts/plot_token_safety_pareto.py --input analysis/outputs/ --output figures/
python scripts/plot_trajectory_divergence.py --input analysis/outputs/ --output figures/
python scripts/plot_reconciliation_waterfall.py --input analysis/outputs/ --output figures/
python scripts/plot_ablation.py --input analysis/outputs/ --output figures/
```

## 14. Final Report

```bash
# Verify MANIFEST.json is current
PYTHONPATH=src python scripts/update_manifest.py

# Assemble report manually:
#   reports/FINAL_EXPERIMENT_REPORT.md  (20 required sections per §19)
#   reports/CLAIM_EVIDENCE_LEDGER.md    (each claim linked to result file)
```

## Key File Hashes (Snapshot 2026-06-15)

See `artifacts/MANIFEST.json` for current hashes of all key files including
benchmark commit, task data hashes, and config hashes.
