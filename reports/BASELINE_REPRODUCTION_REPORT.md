# Baseline Reproduction Report

## Completed

One Stage 0 smoke run completed:

| Field | Value |
| --- | --- |
| Domain | `mock` |
| Task | `create_task_1` |
| Agent | `llm_agent_gt` |
| User | `user_simulator` |
| Model endpoint | `openai/q`, `http://127.0.0.1:8200/v1` |
| Seed | 101 |
| Result file | `/home/xqin5/multiaiagent/results/baseline_reproduction/tau2_mock_qwen_smoke/results.json` |
| Reward | 1.0 |
| DB reward | 1.0 |
| Communicate reward | 1.0 |
| Write action check | 1/1 |
| Termination | `USER_STOP` |

## Evidence

- `tau2 check-data` succeeded.
- `tau2 run` completed one mock task.
- Result hash: `057567782234fb31aaa0afe3c0c57fd06041c6787a343d5b02829c3d04c3ce05`.

## Not Yet Reproduced

- Official airline baseline.
- Official retail baseline.
- Official telecom baseline.
- Historical multi-agent baseline parity.
- Token accounting audit for uncached prompt tokens.

## Interrupted Attempts

- `clean_tau2_airline_qwen_smoke`: clean worktree, airline task `32`, Qwen3.6-27B endpoint, seed `20260615`; interrupted after about 8 minutes with `0` completed simulations. This is not a reproduced baseline.

## Domain Smoke Completed

These runs use `max_steps=2` only to verify clean tau2 + live endpoint + official runner/evaluator plumbing. They are not official baseline reproduction runs and should not be used for FSS claims.

| Domain | Task | Result file hash | Termination | Duration |
| --- | --- | --- | --- | ---: |
| airline | `32` | `08fb9eee9d0343c173675019986d27323ae65f140fef93ab85a6c466f82fb0d6` | `max_steps` | 39.43s |
| retail | `0` | `e75e1f90ee6ef7a6d7801424288369691232eb43a66a759e419b00a59f63335a` | `max_steps` | 57.18s |
| telecom | base mms task | `21e85e1d92cd8ec556f585ed32cc8e5c6f93ad1379876a5a92155578f0d038b0` | `max_steps` | 20.03s |

## Problems Found

- `/home/xqin5/tau2-bench` has an uncommitted parser patch and is excluded from formal runs.
- `/home/xqin5/multiaiagent/worktrees/tau2-clean` is the clean formal benchmark root.
- Active endpoints do not match the full Proposal model list.
- LiteLLM cost mapping warns for local `Qwen/Qwen3.6-27B`; cost is not a reliable metric for this smoke.
