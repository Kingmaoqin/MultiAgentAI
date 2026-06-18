# 00 Asset Inventory

## Scope

Scanned `/home/xqin5/multiaiagent`, `/home/xqin5/tau2-bench`, and focused historical assets under `/home/xqin5/reactproject/*tau*` and `/home/xqin5/reactproject/banking`. Large caches and unrelated JSON trajectories under `/home/xqin5` were not exhaustively indexed.

| Asset | Path/Endpoint | Version/Commit | Status | Reusable | Evidence |
| ----- | ------------- | -------------- | ------ | -------- | -------- |
| RAVEL proposal | `/home/xqin5/multiaiagent/MultiAiAgentProposal.pdf` | sha256 `2d01ea22d5d9e78ba1a57aba6a1a90571ab63ac11b3e1eb8762653ef3a2162cd` | FOUND | Yes | PDF text read with `pdftotext`; defines RQ1-RQ5, H1-H5, VDL/MSE/gate/ARB |
| Execution prompt | `/home/xqin5/multiaiagent/第二部实验意见` | sha256 `6e87ebd7e63793ce7c32b89160279c3cceec968dea22771ce42baa6234067e45` | FOUND | Yes | Requires asset inventory before core coding |
| tau2/tau3 benchmark, formal root | `/home/xqin5/multiaiagent/worktrees/tau2-clean` | git `ddc66a777e520373975f15d3abec989cfe2ec371`, detached worktree | CLEAN | Yes, primary | Formal task audit and formal runs use this root |
| tau2/tau3 benchmark, original asset | `/home/xqin5/tau2-bench` | git `ddc66a777e520373975f15d3abec989cfe2ec371`, no tag at HEAD | DIRTY | Reference only | README identifies tau3-bench with airline/retail/telecom/banking_knowledge |
| tau2 local patch | `/home/xqin5/tau2-bench/src/tau2/data_model/message.py` | uncommitted diff | NOT CLEAN | Maybe | Adds string argument parser using `json.loads`/`ast.literal_eval`; affects tool-call parsing |
| tau2 data | `/home/xqin5/multiaiagent/worktrees/tau2-clean/data/tau2/domains` | hashes in `artifacts/MANIFEST.json` | FOUND | Yes | airline 50 tasks, retail 114, telecom full 2285/base 114 |
| tau2 runner/evaluator | `/home/xqin5/multiaiagent/worktrees/tau2-clean/src/tau2/runner`, `/home/xqin5/multiaiagent/worktrees/tau2-clean/src/tau2/evaluator` | same commit | FOUND | Yes | Official `tau2 run`, `run_single_task`, final-state evaluator |
| tau2 AgentBeats wrapper | `/home/xqin5/reactproject/tau2-agentbeats` | git `1714c52119594900ad6e4579b6cd5de186c45410`; untracked `logs/` | FOUND | Optional | A2A green agent around tau2 |
| Historical drift v2 | `/home/xqin5/reactproject/tau3_shared_state_drift_v2` | not a git repo | FOUND | Partially | Contains `run_v2.py`, metrics, figures, logs, config snapshots |
| Historical v2 audit | `/home/xqin5/reactproject/tau3_shared_state_drift_v2/summaries/CODE_AUDIT_REPORT.md` | file snapshot | FOUND | Yes, as negative guidance | Identifies global-field gate and write-classification flaws |
| Historical v3 patch | `/home/xqin5/reactproject/tau3_shared_state_drift_v2/scripts/run_v3.py` | file snapshot | FOUND | Partially | Relevance-scoped gate and per-domain write whitelist over v2 |
| Stage1_4 fullsync assets | `/home/xqin5/reactproject/tau3_shared_state_drift_stage1_4_agent_user_boundary_fullsync` | not a git repo | FOUND | Partially | Endpoint status, configs, metrics, smoke report |
| gpt-oss multidom historical results | `/home/xqin5/reactproject/tau3_gptoss120b_multidom` | not a git repo | FOUND | Evidence only | Metrics and preliminary reports, but not current active endpoint |
| GLM multidom historical results | `/home/xqin5/reactproject/tau3_glm45air_multidom` | not a git repo | FOUND | Evidence only | Metrics and preliminary reports, but not current active endpoint |
| Upgrade scout | `/home/xqin5/reactproject/tau3_upgrade_scout` | not a git repo | FOUND | Scaffold/evidence only | README says smoke only; Track F metric audit not run |
| Banking package | `/home/xqin5/reactproject/banking` | not audited as repo | FOUND | Optional | Scripts and logs for tau3 banking experiments |
| Active vLLM endpoint | `http://127.0.0.1:8200/v1/models` | served model `Qwen/Qwen3.6-27B`, `q`, `gpt-q` | ACTIVE | Yes for smoke | Used for mock baseline |
| Active vLLM endpoint | `http://127.0.0.1:8190/v1/models` | served model `q` | ACTIVE | Yes | Same Qwen3.6-27B root |
| Active vLLM endpoint | `http://127.0.0.1:8005/v1/models` | served model `g4` | ACTIVE | Maybe | Gemma-4-31B-it, not in Proposal |
| Stage 0 mock baseline | `/home/xqin5/multiaiagent/results/baseline_reproduction/tau2_mock_qwen_smoke/results.json` | sha256 `057567782234fb31aaa0afe3c0c57fd06041c6787a343d5b02829c3d04c3ce05` | COMPLETE | Yes, smoke only | `mock/create_task_1`, reward 1.0 |

## Not Found / Not Verified

- No active `/v1/models` endpoint for `gpt-oss-120b`, `Qwen3-32B`, `GLM-4.5-Air`, or `Llama-3.3-70B-Instruct`.
- No clean top-level Git repository at `/home/xqin5` or `/home/xqin5/multiaiagent`.
- No full RAVEL implementation found locally.
- No validated held-out RAVEL experiment results found.
