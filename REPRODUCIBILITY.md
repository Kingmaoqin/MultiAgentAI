# REPRODUCIBILITY — RAVEL Phase-2

## Environment
- Repo: `/home/xqin5/multiaiagent`, branch `feature/ravel-mas`.
- Python 3.12 (conda env `MDPC`); tau2 via `worktrees/tau2-clean` uv env (commit `ddc66a7`).
- GPUs: 4× A100 80GB (shared; run single-GPU sequential + watchdog).
- Models (local vLLM, OpenAI-compatible):
  - medium `openai/g4` = gemma-4-31B-it @ `http://127.0.0.1:8005/v1` (len 16384)
  - strong `openai/gpt-oss` = gpt-oss-120b @ `http://127.0.0.1:8192/v1` (len 65536)
  - user simulator: FIXED to `openai/g4` across all agent conditions.

## Run unit tests
```bash
conda run -n MDPC python -m pytest tests/ -q      # 148 passed, 1 skipped
```

## Reproduce the smoke (1 task, ~50s)
```bash
cd worktrees/tau2-clean
uv run python /home/xqin5/multiaiagent/scripts/run_mas_safety.py \
  --domain airline --regime FullSync --gate on \
  --model-api-base http://127.0.0.1:8005/v1 --model-name openai/g4 \
  --user-api-base http://127.0.0.1:8005/v1 --user-model openai/g4 \
  --output-dir /tmp/phase2_smoke/gemma4 --n-tasks 1 --max-concurrency 1 \
  --max-steps 25 --timeout 300
```

## Analyze results into the §3.2 trial CSV
```bash
conda run -n MDPC python scripts/analyze_phase2_results.py \
  --results-dir <results_dir_with_*_summary.json> \
  --out artifacts/phase2/tables/main_results.csv
```

## Determinism contract (plan §1.8)
Every experiment pins: task_seed, mutation_seed, user_simulator_seed,
prompt_version, tool_parser, model_checkpoint, serving_config, temperature=0,
max_steps, timeout. All visibility perturbations are produced by deterministic,
seeded wrappers (`ravel_core/conflict_signal.py`, `field_masking.py`) — never by
an LLM.

## Status
- Done: asset audit, smoke, logging/metrics, ActionSchema+non-permissive gate,
  CSI, Evidence-Uptake, DPR, field-masking — all with unit tests.
- HELD for approval: full/expanded experiment matrices, mechanism-decomposition
  runs, statistical analysis, figures (configs in `configs/phase2/`).
