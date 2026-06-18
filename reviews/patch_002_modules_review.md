# Review Scope

Independent review of patch_002 modules and experiment-design artifacts under the protocol in `/home/xqin5/multiaiagent/第二部实验意见` §10, with additional checks from §9.4. Reviewed:

- `/home/xqin5/multiaiagent/src/ravel_core/mse_router.py`
- `/home/xqin5/multiaiagent/src/ravel_core/reconciliation.py`
- `/home/xqin5/multiaiagent/src/ravel_core/trial_logger.py`
- `/home/xqin5/multiaiagent/src/ravel_core/metrics.py`
- `/home/xqin5/multiaiagent/src/ravel_core/benchmark_adapter.py`
- `/home/xqin5/multiaiagent/src/ravel_core/__init__.py`
- `/home/xqin5/multiaiagent/tests/test_new_modules.py`
- `/home/xqin5/multiaiagent/scripts/task_audit.py`
- `/home/xqin5/multiaiagent/scripts/generate_splits.py`
- `/home/xqin5/multiaiagent/artifacts/task_audit/*`
- `RUNBOOK.md`, `docs/03_EXECUTION_PLAN.md`, `docs/04_PREREGISTRATION.md`, `reports/GO_NO_GO_REPORT.md`, `artifacts/MANIFEST.json`

For dependency context I also inspected `commit_gate.py`, `evidence.py`, and `visibility.py`, because patch_002 correctness depends on EvidenceValid, visibility state, and gate semantics. No source files were modified. This report file is the only project artifact written by this review.

# Requirement Mapping

- Reviewer protocol: read `/home/xqin5/multiaiagent/第二部实验意见` §1.4, §9.1-§9.4, and §10. The protocol requires independent review, actual test execution, mutation-style checks, and severity classification as BLOCKER/MAJOR/MINOR/NIT.
- Proposal requirements: read proposal text extracted from `MultiAiAgentProposal.pdf`, especially RQ1-RQ5, H1-H5, VDL, MSE-Router, two-stage commit gate, ARB ladder, token metrics, safety metrics, and logging/replay requirements.
- MSE-Router: `mse_router.py` implements a small rule-based router and reason codes. It is mostly a local routing helper, not yet a complete proof of minimal sufficiency.
- ARB: `reconciliation.py` implements ladder stages, but current control flow can return `commit` before re-running the gate on updated evidence.
- TrialLogger: `trial_logger.py` creates JSONL events and summaries, but visible field logging is broken and replay evidence is incomplete.
- Metrics: `metrics.py` has correct simple denominator helpers, but `compute_metrics()` copies caller-supplied safety metrics instead of deriving them from auditable raw events.
- BenchmarkAdapter: `benchmark_adapter.py` is a passive hook facade, not an enforced wrapper around tau2 runner/tool execution. It does not prevent high-risk write bypass.
- Task audit/splits: artifacts exist, but inclusion is heuristic and dependency graph artifacts are empty. The documented held-out NO-GO status is appropriate.

# Commands Executed

- `find /home/xqin5/multiaiagent -maxdepth 2 -type f | sort`
- `rg -n "第10节|第十节|reviewer|Reviewer|patch_002|proposal|实验意见|审查" /home/xqin5/multiaiagent`
- `sed -n '120,150p' /home/xqin5/multiaiagent/第二部实验意见`
- `sed -n '780,825p' /home/xqin5/multiaiagent/第二部实验意见`
- `sed -n '828,900p' /home/xqin5/multiaiagent/第二部实验意见`
- `sed -n '900,930p' /home/xqin5/multiaiagent/第二部实验意见`
- `sed -n '360,525p' /home/xqin5/multiaiagent/第二部实验意见`
- `sed -n '540,675p' /home/xqin5/multiaiagent/第二部实验意见`
- `sed -n '675,785p' /home/xqin5/multiaiagent/第二部实验意见`
- `sed -n '930,1068p' /home/xqin5/multiaiagent/第二部实验意见`
- `pdftotext /home/xqin5/multiaiagent/MultiAiAgentProposal.pdf /tmp/multiaiagent_proposal.txt`
- `rg -n "RAVEL|VDL|MSE|Evidence|evidence|ledger|gate|commit|token|paired|benchmark|safety|unsafe|reconcil|version|replay|fresh|conflict|candidate" /tmp/multiaiagent_proposal.txt`
- `sed -n '420,570p' /tmp/multiaiagent_proposal.txt`
- `sed -n '614,675p' /tmp/multiaiagent_proposal.txt`
- `sed -n '668,748p' /tmp/multiaiagent_proposal.txt`
- `sed -n '1110,1185p' /tmp/multiaiagent_proposal.txt`
- `nl -ba` on all scoped source, test, script, doc, report, and manifest files listed in Review Scope.
- `git -C /home/xqin5/multiaiagent status --short`
  - Result: failed because `/home/xqin5/multiaiagent` is not a git repository.
- `git -C /home/xqin5/tau2-bench rev-parse HEAD`
  - Result: `ddc66a777e520373975f15d3abec989cfe2ec371`
- `git -C /home/xqin5/tau2-bench status --short`
  - Result: `M src/tau2/data_model/message.py`
- `git -C /home/xqin5/tau2-bench diff --stat`
  - Result: `src/tau2/data_model/message.py | 12 ++++++++++++`
- `PYTHONPATH=/home/xqin5/multiaiagent/src pytest -q`
  - Result: `51 passed in 0.18s`
- Negative mutation check, in memory only: temporarily patched `CommitGate.verify` to always return `commit`, then ran:
  - `tests/test_new_modules.py::TestMutationProbes::test_probe_freshness_bypass_caught`
  - `tests/test_new_modules.py::TestMutationProbes::test_probe_conflict_bypass_caught`
  - Result: both failed as expected, so this specific gate-bypass mutant is caught.
- Visible logging repro:
  - Called `TrialLogger.log_agent_observation(..., visible_fields={"status": "open", "seat": "12A"})`.
  - Result: event JSON contained `"visible_field_keys": []`.
- ARB repro:
  - Missing-field gate decision followed by stage-1 requery returned `final_verdict='commit'` while `final_gate_decision.allowed=False`.
- Adapter bypass repro:
  - Called `VisibilityAdapter.on_executed_write()` without any prior candidate write or gate verdict.
  - Result summary: `n_candidate_writes=0`, `n_executed_writes=1`, `gate_verdicts=[]`, `unsafe_action_rate=1.0`.
- Artifact audit:
  - `find /home/xqin5/multiaiagent/artifacts/task_audit/task_dependency_graphs -maxdepth 1 -type f -print`
  - Result: no dependency graph files.

# Design Findings

The patch is directionally modular, but several modules are passive recorders or helpers while their docstrings imply enforceable experimental guarantees. The most important design gap is that write safety is not made an invariant at the adapter boundary. `VisibilityAdapter` relies on callers to call `on_candidate_write()` and then to respect the returned decision, while `on_executed_write()` accepts any write event independently.

The ARB implementation is not merely incomplete; its control flow can promote a failed gate decision to `commit` based on new evidence IDs before verifying that EvidenceValid now holds. This breaks the proposal's two-stage write guarantee.

The logging design is also insufficient for replay. It stores many hashes and counts, but not enough event payload, visible field lists, candidate arguments, ledger snapshot, or final state detail to reconstruct the trajectory. This conflicts with the protocol's replay and visible-evidence requirements.

# Functional Findings

- BLOCKER: `AdaptiveReconciliationBudget.reconcile()` returns early on `step.verdict == "commit"` at `reconciliation.py:145-148`, before the re-evaluation block at `reconciliation.py:155-167`. Stage 1 can set `verdict="commit"` after fetching a missing field (`reconciliation.py:240-247`), stage 2 can do the same for stale deltas (`reconciliation.py:265-272`), and stage 4 can do the same after requery (`reconciliation.py:314-319`). The repro showed `final_verdict='commit'` with `final_gate_decision.allowed=False`.
- BLOCKER: `VisibilityAdapter.on_executed_write()` at `benchmark_adapter.py:219-237` records executed writes without requiring a matching candidate write, a gate decision, or `decision.allowed`. `high_risk_actions` is configured at `benchmark_adapter.py:80-81` but unused. This violates the "worker cannot directly execute high-risk write" requirement.
- MAJOR: `TrialLogger.log_agent_observation()` loses visible field keys because `list(visible_fields or {}).sort()` returns `None` at `trial_logger.py:135-139`. The minimal repro confirmed logged `visible_field_keys` is always `[]`.
- MAJOR: `TrialLogger.log_candidate_write()` at `trial_logger.py:180-200` omits `candidate["arguments"]` and `claimed_preconditions`; `log_tool_call()` and `log_executed_write()` store output/result hashes only (`trial_logger.py:142-159`, `trial_logger.py:207-222`). The summary stores counts and hashes but no replayable ledger snapshot or full final DB state (`trial_logger.py:251-295`). This is not enough for trajectory replay or post-hoc evidence audit.
- MAJOR: `compute_metrics()` claims safety denominators are derived from summary data (`metrics.py:76-81`) but actually copies `summary["safety_metrics"]` (`metrics.py:83-115`). If the caller supplies wrong safety rates, the function does not detect or recompute them from raw candidate/executed write data.

# Benchmark Integrity

No reviewed `ravel_core` module imports or edits tau2 directly, which is good for avoiding silent benchmark source changes. However, benchmark integrity is still not ready for experiments:

- `/home/xqin5/tau2-bench` is dirty: `src/tau2/data_model/message.py` has a 12-line uncommitted diff. This matches `GO_NO_GO_REPORT.md` B1 and must be resolved before formal runs.
- `benchmark_adapter.py` is not yet a tau2 runner/evaluator wrapper despite the module docstring describing that role. It provides hooks only, so FullSync behavior preservation against an unmodified tau2 run is not actually tested.
- `scripts/task_audit.py` does not implement the required dependency graph analysis. `_count_dependency_layers()` is explicitly heuristic (`task_audit.py:117-131`), and inclusion allows `(has_persistent_write and n_tool_calls >= 3)` to satisfy the 3-layer criterion (`task_audit.py:152-158`). The `task_dependency_graphs/` directory exists but contains no files.

# Statistical/Experimental Integrity

The preregistration and GO/NO-GO documents are appropriately cautious: held-out evaluation is `NO-GO`, airline held-out has 0 tasks in the current split, baseline reproduction is partial, token accounting audit is not verified, and patch_002 review is pending.

The current code does not yet enforce paired design. `RAVELRunConfig` stores seeds and method/regime metadata, and `generate_splits.py` produces deterministic splits, but there is no runner-level check that two conditions share the same task, seed, database initial state, mutation, model checkpoint, prompt, tool implementation, and decoding. This is acceptable for a module scaffold only if not used for causal claims.

The task audit artifacts should not be used as final inclusion evidence because they are based on reference action counts and heuristics rather than dependency DAGs, historical trajectories, official reference trajectories, and baseline solvability.

# Test Quality

The required full test command passes, but the suite is not strong enough for patch approval:

- `tests/test_new_modules.py::TestAdaptiveReconciliation::test_missing_field_resolved_by_requery` allows `commit` or `abstain` and does not assert that a final commit has a fresh allowed gate decision (`tests/test_new_modules.py:219-222`). This misses the ARB blocker found above.
- `TestInvariants.test_inv5_gate_block_enforced` acknowledges that the no-gate path is "not testable at this layer" (`tests/test_new_modules.py:431-450`). The adapter bypass repro shows this gap is real.
- `TestMutationProbes` mostly performs normal positive assertions, not actual monkeypatch-based mutation testing (`tests/test_new_modules.py:665-737`). The token probe deliberately logs the same token record twice and asserts the doubled value is expected (`tests/test_new_modules.py:725-737`), so it does not catch a token double-counting implementation bug.
- No test checks that `TrialLogger` records actual visible field keys. A one-line repro catches this.
- No test checks that `on_executed_write()` requires a prior candidate/gate decision.
- No test runs tau2 through the adapter to show FullSync does not alter official reward.

# Complexity and Unnecessary Code

The code is not large, but several fields and abstractions create a false sense of completeness:

- `high_risk_actions` in `RAVELRunConfig` is unused.
- `max_reconciliation_stage` is stored in `RAVELRunConfig` but not wired to any ARB instance in `VisibilityAdapter`.
- `MSERouter` is constructed in `VisibilityAdapter` but not used by the adapter hooks.
- `SafetyMetricsAccumulator.record_blocked_candidate()` increments `_blocked_candidates` unconditionally; this is correct only if the caller passes blocked candidates only, but its docstring says "blocked or allowed" (`metrics.py:161-168`).

# Documentation

The higher-level docs mostly avoid overclaiming: `GO_NO_GO_REPORT.md` marks held-out evaluation as NO-GO and patch_002 as pending. `RUNBOOK.md` gates pilot/core experiments on patch_002 approval. These statements are consistent with this review.

However, module docstrings overstate implementation status:

- `benchmark_adapter.py` says it connects tau2's official runner/evaluator to RAVEL, but the implementation does not wrap or call tau2.
- `trial_logger.py` says it records all required fields for replay, but it omits visible field keys due to a bug and stores hashes/counts rather than replayable event state.
- `tests/test_new_modules.py` claims §9.4 mutation probes, but most probes are ordinary assertions and do not mutate implementation logic.

# Blocking Issues

1. BLOCKER: ARB can return `commit` without a fresh successful gate verification. This violates EvidenceValid and the two-stage commit requirement. See `reconciliation.py:145-167`, `reconciliation.py:240-247`, and the ARB repro in Commands Executed.
2. BLOCKER: The benchmark adapter does not enforce candidate-write -> gate -> executed-write ordering. A high-risk write can be recorded without any candidate or gate verdict. See `benchmark_adapter.py:180-237` and the adapter bypass repro.
3. BLOCKER: The current logger output is not replayable enough for the protocol's replay requirement and loses the actual visible field list. See `trial_logger.py:135-139`, `trial_logger.py:180-222`, and `trial_logger.py:251-295`.

# Non-blocking Issues

1. MAJOR: Task audit inclusion is heuristic and lacks generated dependency graph artifacts, so the task audit cannot yet justify the experimental sample.
2. MAJOR: Safety metrics are copied from caller-supplied summaries rather than recomputed from auditable candidate/executed write records.
3. MAJOR: Tests pass but miss the ARB commit-with-failed-gate bug, adapter write bypass, visible-field logging bug, and real tau2 FullSync preservation.
4. MINOR: `/home/xqin5/multiaiagent` has no git metadata, so patch-boundary provenance cannot be checked with `git diff` inside this project directory.
5. MINOR: Manifest hashes are truncated/algorithm-ambiguous for several entries; acceptable for a local snapshot, but not enough as final artifact provenance.

# Verdict

CHANGES_REQUIRED
