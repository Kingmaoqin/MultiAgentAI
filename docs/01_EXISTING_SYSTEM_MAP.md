# 01 Existing System Map

## Official tau2/tau3 Chain

```text
task JSON / split_tasks
→ user simulator (`tau2.user.user_simulator.UserSimulator`)
→ orchestrator (`tau2.orchestrator.Orchestrator`)
→ agent (`llm_agent`, `llm_agent_gt`, or custom)
→ LiteLLM / OpenAI-compatible local vLLM
→ domain tools (`ToolType.READ`, `ToolType.WRITE`, `ToolType.GENERIC`)
→ domain environment and DB
→ official evaluator (`EnvironmentEvaluator`, `CommunicateEvaluator`, diagnostics)
→ `results.json`
→ metrics / analysis scripts
```

## Local Benchmark Version

- Formal repository worktree: `/home/xqin5/multiaiagent/worktrees/tau2-clean`
- Original asset repository: `/home/xqin5/tau2-bench`
- Remote: `https://github.com/sierra-research/tau2-bench.git`
- Formal branch: detached `ddc66a7`
- Original branch: `main`
- Commit: `ddc66a777e520373975f15d3abec989cfe2ec371`
- Formal worktree local changes: none.
- Original asset local changes: `src/tau2/data_model/message.py` has an uncommitted parser patch and is excluded from formal runs.
- Package version: `tau2==1.0.0`
- Python requirement: `>=3.12,<3.14`

## Domains and Task Counts

| Domain | Task File | Count | Splits |
| --- | --- | ---: | --- |
| airline | `data/tau2/domains/airline/tasks.json` | 50 | train 30, test 20, base 50 |
| retail | `data/tau2/domains/retail/tasks.json` | 114 | train 74, test 40, base 114 |
| telecom | `data/tau2/domains/telecom/tasks.json` | 2285 | small 20, train 74, test 40, full 2285, base 114 |

## Tool Write Semantics

Use tau2 decorators, not substring heuristics:

- airline writes include `book_reservation`, `cancel_reservation`, `send_certificate`, `update_reservation_baggages`, `update_reservation_flights`, `update_reservation_passengers`.
- retail writes include `cancel_pending_order`, `exchange_delivered_order_items`, `modify_pending_order_address`, `modify_pending_order_items`, `modify_pending_order_payment`, `modify_user_address`, `return_delivered_order_items`.
- telecom writes include `suspend_line`, `resume_line`, `send_payment_request`, `enable_roaming`, `disable_roaming`, `refuel_data`.

## Historical Visibility Chain

Historical v2/v3 drift scripts implemented:

```text
tau2 task
→ real three-context planner/retriever/executor wrapper
→ observation router (FULL_SYNC / DELAYED_2 / FIELD_MASK / LOSSY_SUMMARY / CONFLICTING_VIEW)
→ evidence ledger
→ VSSC commit gate / reconciliation
→ tau2 environment
→ CSV metrics and reports
```

Known audit issues mean this chain is reusable as code context, not as final evidence.

## Current RAVEL Workspace Chain

```text
Proposal + local asset audit
→ configs under `/home/xqin5/multiaiagent/configs`
→ standalone `ravel_core` unit-tested library
→ future tau2 wrapper integration
→ official tau2 evaluator
→ raw / validated / aggregated results
→ analysis / figures / reports
```
