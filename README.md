# RAVEL: Risk-Adaptive Visibility and Evidence Ledger

**Multi-agent system experiment repository** — empirical evaluation of observation-regime effects on task completion, write safety, and token efficiency in tau2-bench service domains.

> **Status (2026-06-17):** All planned experiments complete. Core findings in `reports/EXPERIMENT_REPORT_20260615.md` (1690 lines). Completeness audit vs. Proposal: `docs/audit_completeness.md`.

---

## What Is RAVEL

RAVEL augments a standard LLM agent with four components that control *what the agent can see, how writes are guarded, and how token budget is allocated*:

| Component | Role | Source |
|-----------|------|--------|
| **VDL** — Versioned Data Ledger | Append-only evidence store; tracks tool results with version, delta, and conflict flags | `src/ravel_core/evidence.py` |
| **MSE-Router** — Minimal Sufficient Evidence | Projects raw evidence into one of four visibility regimes before showing to the agent | `src/ravel_core/mse_router.py` |
| **CommitGate** | Two-phase commit: `propose → validate → commit/abstain` for high-risk writes | `src/ravel_core/commit_gate.py` |
| **ARB** — Adaptive Reconciliation Budget | Escalation ladder that adds evidence steps only when the gate blocks | `src/ravel_core/reconciliation.py` |

### Four Observation Regimes

| Regime | What the agent sees |
|--------|---------------------|
| **FullSync** | All evidence, current version — no restriction |
| **Delayed** | All fields, but lagged by d=1 interaction turn |
| **FieldMask** | Current version, but 30% of fields masked |
| **ConflictingView** | Agent receives conflicting observations from two simulated data sources |

---

## Quick Results

All experiments use tau2-bench dev split. Full per-task breakdown in `reports/EXPERIMENT_REPORT_20260615.md` §15.

### Airline Domain (10 tasks)

| Model | Baseline | FullSync | Delayed | FieldMask | ConflictingView |
|-------|---------|---------|---------|-----------|-----------------|
| Qwen3-27B | — | **3/10** (30%) | 1/10 (10%) | 0/10 | **4/10** (40%) ⭐ |
| Gemma4-31B | **4/10** (40%) | 3/10 (30%) | 1/10 (10%) | 0/10 | 3/10 (30%) |
| gpt-oss-120b | 1/10 (10%) | 1/10 (10%) | 1/10 (10%) | 0/10 | **2/10** (20%) |

### Retail Domain (14 tasks)

| Model | Baseline | FullSync | ConflictingView |
|-------|---------|---------|-----------------|
| Gemma4-31B | 2/14 (14%) | 3/14 (21%) | **4/14** (29%) |
| gpt-oss-120b | **5/14** (36%) | 1/14 (7%) ⚠️ | 3/14 (21%) |

### Telecom Domain (14 tasks)

All RAVEL regimes: **0/14 (0%)** — structurally blocked by `max_steps=25`. See §6.3 for analysis.

### Key Findings

1. **ConflictingView is consistently the best RAVEL regime** — counterintuitive but reproducible across 3 models and 2 domains
2. **RAVEL helps Gemma4 in retail** (BL 2→FS 3→CV 4, monotone) but slightly hurts in airline (4→3)
3. **RAVEL strongly hurts gpt-oss in retail** (5→1, −80%): structural conflict between reasoning-model architecture and RAVEL's multi-step evidence requirements
4. **FieldMask 30% = universal failure**: 30% field masking breaks all tested architectures
5. **Scale ≠ RAVEL performance**: gpt-oss (120B) underperforms Gemma4 (31B) on airline by 2.2×; gpt-oss avg task duration is 2.2× shorter, and failing tasks are 36% faster than passing ones (fast-wrong-commit pattern)

---

## Repository Structure

```
.
├── src/ravel_core/               # Core RAVEL runtime (no tau2 dependency for unit tests)
│   ├── evidence.py               # Versioned Data Ledger (VDL) — §4.2
│   ├── visibility.py             # VisibilityPolicy, EvidenceView — §3.2, §5.3
│   ├── commit_gate.py            # Schema-scoped CommitGate — §4.4
│   ├── mse_router.py             # Minimal Sufficient Evidence router — §4.3
│   ├── reconciliation.py         # Adaptive Reconciliation Budget (ARB) — §4.5
│   ├── trial_logger.py           # Per-trial structured event log — §17
│   ├── metrics.py                # FSS, UAR, CWR, TokensUncached evaluators — §6, §14
│   ├── benchmark_adapter.py      # tau2 wrapper (no tau2 edits required) — §1.3
│   └── ravel_agent.py            # tau2-compatible half-duplex RAVEL agent — §5
│
├── scripts/
│   ├── run_ravel_exp.py          # Main experiment runner
│   ├── run_ravel_corrected.sh    # Sequential regime runner (avoids GPU contention)
│   ├── analyze_results.py        # Aggregate summaries and bootstrap CI
│   └── task_audit.py             # Write-tool classification and dependency graph
│
├── configs/
│   ├── experiment_matrix.yaml    # Pre-registered design (domains × regimes × models)
│   ├── model_endpoints.json      # vLLM server endpoints snapshot
│   └── benchmark_versions.json   # Frozen benchmark commit hashes
│
├── artifacts/task_audit/
│   ├── split_manifest.json       # Dev/pilot/held-out split provenance (seed 20260615)
│   ├── splits_dev.csv            # Dev split: 10 airline + 14 retail + 14 telecom tasks
│   ├── splits_pilot.csv
│   └── splits_held_out.csv
│
├── results/
│   ├── main_trials.csv           # Machine-readable per-trial results (294 rows)
│   ├── config_manifest.json      # Model endpoints, hardware, known biases
│   ├── ravel_corrected/          # Qwen3 corrected results (post-CommitGate-bug-fix)
│   │   ├── airline/{fullsync,delayed,fieldmask,conflictingview}/exp_summary.json
│   │   ├── retail/...
│   │   └── telecom/...
│   └── multimodel/               # Gemma4 + gpt-oss results
│       ├── gemma4/{airline,retail}/{baseline,fullsync,...}/exp_summary.json
│       └── gptoss/{airline,retail}/{baseline,fullsync,...}/exp_summary.json
│
├── reports/
│   └── EXPERIMENT_REPORT_20260615.md   # Full experiment report (1690 lines)
│
├── docs/
│   └── audit_completeness.md           # Completeness audit vs. Proposal
│
├── tests/
│   ├── test_ravel_core.py        # Unit tests for core modules (56 tests)
│   └── test_new_modules.py
│
├── RUNBOOK.md                    # Step-by-step reproduction guide
└── ENVIRONMENT.md                # Hardware and software environment spec
```

---

## Installation

RAVEL core has no external dependencies beyond Python stdlib — unit tests run without tau2.

```bash
git clone git@github.com:Kingmaoqin/MultiAgentAI.git
cd MultiAgentAI
python -m pytest tests/ -v
```

To run actual experiments (requires tau2-bench worktree + vLLM):

```bash
conda activate p08_skilloverload

# Baseline
python scripts/run_ravel_exp.py \
    --domain airline --split dev \
    --agent-type baseline \
    --max-steps 25 --timeout 900 --max-concurrency 2 \
    --output-dir results/myrun \
    --model-api-base http://127.0.0.1:8005/v1 \
    --model-name gemma4/gemma-4-31b-it

# RAVEL FullSync
python scripts/run_ravel_exp.py \
    --domain airline --split dev \
    --agent-type ravel --observation-regime fullsync \
    --max-steps 25 --timeout 900 --max-concurrency 2 \
    --output-dir results/myrun \
    --model-api-base http://127.0.0.1:8005/v1 \
    --model-name gemma4/gemma-4-31b-it
```

---

## Hardware Requirements

| Quantization | GPU Compute Req. | A100 (8.0) | H100 (9.0) |
|---|---|---|---|
| BF16 dense | ≥ 7.0 | ✅ | ✅ |
| FP8 compressed-tensors | ≥ 8.0 | ✅ | ✅ |
| MXFP4 / Marlin FP4 (gpt-oss) | ≥ 8.0 (emulated) | ✅ | ✅ |
| nvfp4 / w4a4 ModelOpt | **≥ 8.9** | ❌ | ✅ |

> Nemotron-3-Super-120B and command-a-plus-w4a4 require H100/Ada Lovelace and cannot run on A100.

---

## Data Files

### `results/main_trials.csv` (294 rows)

| Column | Description |
|--------|-------------|
| `model` | Qwen3.6-27B / Gemma4-31B / gpt-oss-120b |
| `domain` | airline / retail / telecom |
| `regime` | FullSync / Delayed / FieldMask / ConflictingView |
| `method` | Baseline / RAVEL |
| `task_id` | tau2-bench task ID |
| `reward` | 0.0 or 1.0 (final-state success) |
| `termination` | USER_STOP / MAX_STEPS / TIMEOUT / INFRASTRUCTURE_ERROR |
| `duration_sec` | Wall-clock seconds |
| `timeout_s` | 480 (Qwen3 baseline) or 900 (all others) |
| `max_steps` | 25 (all experiments) |

### `results/config_manifest.json`

Model endpoint snapshot, hardware spec, vLLM version, known biases, experiment parameters.

---

## Known Biases

| Issue | Affected Results | Severity |
|-------|-----------------|---------|
| **CommitGate empty-schema bug** | All first-round RAVEL results | Critical — discarded, rerun |
| **GPU contention** | Qwen3 round-1 baseline vs. RAVEL (5 vs 38 concurrent) | High |
| **Qwen3 CoT leakage** | ~63% of user_simulator messages contaminated | Medium |
| **GT hint mismatch** | Retail baseline uses `llm_agent_gt`; RAVEL uses `llm_agent` | High |
| **gpt-oss retail contamination** | First baseline batch (9/14 infra_error) | Critical — discarded, rerun |
| **Gemma4 litellm timeout** | Tasks 39/109/111 all conditions (permanent IE) | Medium |
| **Telecom max_steps=25** | All telecom RAVEL results (100% MAX_STEPS) | High — cannot attribute 0% to visibility |
| **tau2 cooperative timeout** | Streaming LLM calls > timeout do not cancel | Medium |

---

## Completeness Audit

See `docs/audit_completeness.md` for a structured comparison of Proposal requirements vs. current evidence.

| Proposal Claim | Status | Strength |
|----------------|--------|---------|
| RQ1: Visibility causally affects outcomes | **Partially confirmed** | Medium |
| RQ2: RAVEL reduces TokensUncached | **Not tested** | None |
| RQ3: CommitGate reduces unsafe writes | **Not tested** | None |
| RQ4: ARB outperforms fixed budgets | **Not tested** | None |
| RQ5: Cross-model/domain robustness | **Partially confirmed** | Medium-weak |

---

## Next Steps

Priority-ordered follow-up experiments (see `reports/EXPERIMENT_REPORT_20260615.md` §15.10):

**A.** `max_steps=50` experiment — unlock telecom and retail hard tasks  
**B.** Telecom multi-model (Gemma4 + gpt-oss, max_steps=60)  
**C.** FieldMask gradient: test 5% / 10% / 20% masking rates  
**D.** litellm timeout fix — recover Gemma4 tasks 39/109/111  
**E.** Export per-turn conversation logs — needed for gpt-oss "fast-commit" mechanism analysis  
**F.** Token accounting — collect `TokensUncached` to test H2  
**G.** Write-event log export — collect gate/ledger events to test H3/H4  

---

## Citation

```bibtex
@misc{qin2026ravel,
  title  = {RAVEL: Risk-Adaptive Visibility and Evidence Ledger for Multi-Agent Task Completion},
  author = {Qin, Xinyu},
  year   = {2026},
  note   = {\url{https://github.com/Kingmaoqin/MultiAgentAI}}
}
```

---

## Contact

**Xinyu Qin** — xqin9@uic.edu
