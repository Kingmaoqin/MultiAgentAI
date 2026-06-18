# Go/No-Go Report (Updated 2026-06-15)

## Current Decision

`NO-GO` for held-out evaluation experiments.

`GO` for local module development, pilot smoke, and per-domain dev-set baseline runs.

## Gate Checklist

| Gate | Status | Evidence |
| ---- | ------ | -------- |
| Asset inventory complete | PASS | `docs/00_ASSET_INVENTORY.md` — real local scan; 4 active endpoints found |
| Benchmark version frozen | PASS | Formal root is clean worktree `/home/xqin5/multiaiagent/worktrees/tau2-clean` at tau2 commit `ddc66a7`; original `/home/xqin5/tau2-bench` dirty patch is excluded from formal runs |
| Task split frozen | PARTIAL | CSV splits regenerated from clean worktree (`artifacts/task_audit/`); airline has 15 included tasks but 0 held-out — see blocker #3 |
| Preregistration complete | PASS | `docs/04_PREREGISTRATION.md` — RQ1-5, H1-H5, statistical plan, anomaly handling |
| Baseline reproducible | PASS | All three domains reproduced: airline reward=1.0 (297s, 5 actions), retail reward=1.0 (218s, 5 actions), telecom reward=1.0 (86s, 2 write actions); model=Qwen3.6-27B (port 8190); results saved under `results/baseline_reproduction/` |
| Official evaluator normal | PASS | DB-match verifier passed for all three domains; telecom ENV_ASSERTION (assert_mobile_data_status + assert_internet_speed=excellent) both met |
| Environment reset normal | NOT VERIFIED | Requires repeated runs with database reset audit |
| Perturbation invariant tests pass | PASS | 9/9 invariant tests in `tests/test_new_modules.py` pass |
| Ledger/gate/reconciliation tests pass | PASS | 58 total tests pass |
| Token accounting audit | NOT VERIFIED | TokenRecord logging implemented; requires real model run to validate uncached count |
| Reviewer approved ravel_core patch_001 | PASS | `reviews/patch_001_ravel_core_review.md` — APPROVED |
| Reviewer approved new modules (patch_002) | CHANGES REQUIRED | First review found 3 blockers; author fixes applied and awaiting re-review |
| Pilot parser failure check | NOT VERIFIED | Only one mock smoke run complete |
| Compute budget feasible | UNKNOWN | Active models: Qwen3.6-27B, Gemma-4-31B; Proposal models not confirmed |

## Approved Code

| Patch | Files | Tests | Verdict |
|-------|-------|-------|---------|
| patch_001_ravel_core | evidence.py, visibility.py, commit_gate.py | 16 unit tests | APPROVED |
| patch_002_modules | mse_router.py, reconciliation.py, trial_logger.py, metrics.py, benchmark_adapter.py | 42 new tests (58 total) | CHANGES REQUIRED; second-review fixes pending re-review |

## Blocking Issues Before Held-Out Experiments

### B1: Tau2 parser patch (benchmark integrity, §1.3) — RESOLVED FOR FORMAL ROOT
The original asset repo `/home/xqin5/tau2-bench` remains dirty in
`src/tau2/data_model/message.py`. Formal benchmark runs now use the clean
detached worktree `/home/xqin5/multiaiagent/worktrees/tau2-clean` at commit
`ddc66a777e520373975f15d3abec989cfe2ec371`. The dirty repo may only be used
for an explicitly labeled patched-parser sensitivity check.

### B2: Proposal model endpoints not confirmed
Active endpoints serve `Qwen3.6-27B` and `Gemma-4-31B`.
Proposal specifies `gpt-oss-120b`, `Qwen3-32B`, `GLM-4.5-Air`, `Llama-3.3-70B-Instruct`.
Cannot claim cross-model results without confirmed Proposal model set.

### B3: Airline task gap
Only 15 airline tasks satisfy the current write/dependency inclusion criteria
after fixing write-tool detection from tau2 `ToolType.WRITE` decorators.
Held-out airline split is still 0. Must choose expansion rule (refusal tasks /
seed repetition / annotation) and document before airline held-out claims.

### B4: Patch_002 modules not yet approved
Independent review found blockers in ARB commit control, adapter write-gate
enforcement, and replay logging. Author fixes have been applied; re-review is
required before pilot experiment.

### B5: Per-domain baseline reproduced — RESOLVED (2026-06-15)
All three domains passed with Qwen3.6-27B (port 8190):
- Airline task 32: reward=1.0, DB=1.0, 5 actions (3R+2W), 297s, user_stop
- Retail task 0: reward=1.0, DB=1.0, NL_ASSERTION=1.0, 5 actions (4R+1W), 218s, user_stop
- Telecom task `[mobile_data_issue]airplane_mode_on|user_abroad_roaming_enabled_off`: reward=1.0, DB=1.0, ENV_ASSERTION=1.0, 2W actions, 86s, user_stop
Results in `results/baseline_reproduction/{airline,retail,telecom}_smoke/results.json`.

## GO Items (can proceed)

- All unit + integration + invariant tests: `pytest tests/ -q` → 58 passed
- Dev-set smoke runs with any available model (for schema/log debugging only)
- Independent review of patch_002
- Clean tau2 formal root is available
- Airline expansion rule documentation
