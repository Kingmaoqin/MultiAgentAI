# 03 Execution Plan

## Completed

- Read proposal and execution prompt.
- Scanned local tau2/tau3 benchmark assets and historical drift experiments.
- Validated current tau2 data directory.
- Queried active local vLLM endpoints.
- Ran one low-cost `mock/create_task_1` baseline smoke with local Qwen endpoint; reward 1.0.

## Stage 0: Freeze Inputs

1. Preserve hashes for proposal, prompt, task data, policies, DBs, and current benchmark commit.
2. Record tau2 dirty diff and decide whether to run official baselines on patched or clean tau2.
3. Freeze local model endpoint table. Current active endpoints do not match all Proposal models.

## Stage 1: Baseline Reproduction

1. Run one smoke task per domain using official tau2 runner and local endpoint.
2. Run small paired baseline on airline and retail before telecom.
3. Record parser failures separately from reasoning failures.
4. Save raw `results.json` under `results/baseline_reproduction/`.

## Stage 2: RAVEL Adapter

1. Integrate `ravel_core` with tau2 through wrapper/middleware.
2. Log each agent-visible evidence ID, field list, version, and payload projection.
3. Ensure `FullSync` wrapper is behavior-preserving when no mutation is injected.
4. Use tau2 tool metadata for write classification.

## Stage 3: Task Audit

Produce:

```text
artifacts/task_audit/all_tasks.csv
artifacts/task_audit/included_tasks.csv
artifacts/task_audit/excluded_tasks.csv
artifacts/task_audit/task_dependency_graphs/
```

Inclusion must be based on tool dependencies, write exposure, and baseline solvability, not task text length.

## Stage 4: Controlled Experiments

Order:

1. CPU/unit tests.
2. Single-task smoke.
3. Paired pilot.
4. Airline/retail core methods.
5. Telecom only after baseline capability is verified.
6. Cross-model matrix only after active endpoints match frozen model list.

