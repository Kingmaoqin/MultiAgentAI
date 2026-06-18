# 04 Preregistration

## Research Questions

- RQ1: With task, tools, environment state, model, prompt, decoding, and topology fixed, does evidence visibility alone change trajectory, final state, and write safety?
- RQ2: Does RAVEL reduce uncached prompt tokens relative to MAS-FullSync while preserving Final State Success within a 2 percentage point non-inferiority margin?
- RQ3: Do ledger and commit gate reduce stale, conflicting, and unsupported writes without relying on no-op behavior?
- RQ4: Does adaptive reconciliation outperform fixed low/normal/high budgets?
- RQ5: Do effects reproduce across models, domains, and perturbation strengths?

## Frozen Hypotheses

- H1: Delayed, FieldMask, and ConflictingView increase trajectory divergence and reduce evidence validity on high-risk writes relative to FullSync.
- H2: RAVEL reduces uncached prompt tokens by at least 20% relative to MAS-FullSync, with FSS drop no greater than 2 percentage points.
- H3: Under delayed/conflicting regimes, RAVEL lowers Unsafe Action Rate and Conflicting Write Rate relative to FullSync, ledger-only, and commit-gate-only.
- H4: Safety is not explained by overblocking; Overblock Rate <= 12%, and Recovery >= 50% for initially invalid trials.
- H5: Removing MSE routing, VDL, gate, or adaptive reconciliation worsens at least one primary token/write-safety/recovery endpoint.

## Primary Endpoints

- Final State Success
- Uncached Prompt Tokens
- EvidenceValidRate
- Unsafe Action Rate
- Conflicting Write Rate
- Overblock Rate
- Recovery Rate

## Secondary Endpoints

Total tokens, output tokens, LLM calls, tool calls, latency, retries, raw fetches, ledger fetches, reconciliation steps, trajectory edit distance, time-to-divergence, tool selection accuracy, argument accuracy, dependency/order satisfaction, and policy violations.

## Success Thresholds

| Metric | Threshold |
| --- | ---: |
| FSS non-inferiority margin | 2 percentage points |
| Uncached token reduction | >= 20% |
| EvidenceValidRate | >= 95% |
| CWCR | >= 80% |
| Recovery | >= 50% |
| Overblock | <= 12% |

## Statistical Plan

- Paired task-level comparison.
- Task-clustered bootstrap with 95% CI.
- Mixed-effects logistic models for binary endpoints.
- Gamma/log-normal or count models for token/latency/call counts.
- Fixed effects: method, regime, model, domain, and preregistered interactions.
- Random effects: task seed and scenario template.
- Holm correction for primary hypotheses.
- Benjamini-Hochberg FDR for exploratory analyses.
- Report absolute differences, relative differences, odds ratios, and confidence intervals.

## Sample Plan

Proposal target: airline 100 paired tasks, retail 100 paired tasks, telecom 60 paired tasks, at least 3 repetitions per core combination.

**Actual local task inventory (from task_audit.py, 2026-06-15):**

| Domain | Total | Included (writes) | Dev | Pilot | Held-out |
|--------|-------|-------------------|-----|-------|----------|
| Airline | 50 | 15 | 10 | 5 | 0 |
| Retail | 114 | 70 | 14 | 14 | 42 |
| Telecom | 2285 | 2179 | 14 | 14 | 2151 |

**Airline gap (BLOCKING for held-out claims):** After correcting write-tool detection to use tau2 `ToolType.WRITE` decorators, only 15 airline tasks satisfy the current RAVEL inclusion criteria. The proposal target of 100 paired tasks cannot be met without:
1. Expanding definition to include refusal tasks (tests gate on negative path), OR
2. Using seed-based trial repetition with the same task IDs treated as repeated trials, OR
3. Human annotation of additional tasks from the remaining 35 excluded airline tasks.
Resolution must be documented in GO/NO-GO before held-out runs.

## Task Split Freeze

Split manifest: `artifacts/task_audit/split_manifest.json`
Split seed: 20260615
Source hash: recorded in manifest.

**Cross-contamination prevention:**
- Dev set ONLY for schema/log/prompt debugging.
- Pilot set: power analysis + smoke only.
- Held-out: frozen until all method configs finalized.
- No changes to held-out split after first held-out run.

## Anomaly Handling Plan

- Parser failures (tool_call not parsed): log as `error`, count separately, do NOT attribute to visibility.
- OOM during model serving: retry once with sequential scheduling; if persists, halt and report.
- All retries logged with retry count and original error.
- Outlier trimming: NONE. All trials reported. Report without-outlier sensitivity in appendix.
- Missing final state: trial excluded from FSS; counted in parser failure rate.
- If official evaluator errors: halt that domain's held-out run; report blocker.
