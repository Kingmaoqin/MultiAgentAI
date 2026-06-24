# CODE_REVIEW_REQUEST — RAVEL Phase-2 (code + smoke stage)

**Branch**: `feature/ravel-mas` ｜ **Date**: 2026-06-24
**Scope reviewed here**: Phase-2 *code + unit tests + smoke only*. No full
experiment matrices have been run (held for approval). Test suite: **148 passed,
1 skipped** (`conda run -n MDPC python -m pytest tests/`).

Per plan §10, each core module below lists: files, expected behavior, risks.
Please review independently.

---

## 1. Canonical event logging + metrics
**Files**: `src/ravel_core/event_logger.py`, `src/ravel_core/metrics.py` (extended),
`scripts/analyze_phase2_results.py`, `tests/test_phase2_logging_metrics.py`.
**Expected**: one canonical JSONL event schema (§3.1); `validate_event` enforces
header + vocab + rejects chain-of-thought keys; `normalize_mas_trace` maps legacy
`RuntimeTrace` rows into it; trajectory + token metrics (§3.2) return None on zero
denominator; analyzer writes per-trial CSV with `NA` for undefined.
**Risks to check**:
- `normalize_mas_trace` heuristics (`kind`→`event_type`, agent_id→role) may
  mislabel some legacy rows; verify the mapping table matches `ravel_mas/trace.py`.
- `normalize_args` id-abstraction could over-merge (two different non-id values
  that happen to be all-digits) — review the heuristic.
- trajectory metrics need the MAS runtime to emit canonical `tool_call`/`commit`
  rows (NOT done yet); today trajectory cols are empty for MAS runs (token cols OK).

## 2. ActionSchema + non-permissive CommitGate
**Files**: `src/ravel_core/commit_gate.py`, `src/ravel_core/action_schemas.py`,
`src/ravel_core/{ravel_agent,multi_agent_orchestrator}.py` (callers updated),
`tests/test_phase2_action_schema_gate.py`.
**Expected**: `permissive` is explicit, defaults False; unschemaed high-risk write
→ `abstain` + `schema_missing=True` (fail-closed; counted, never dropped); real
schema catches missing/stale/conflicting/untraceable evidence. Airline+retail main
high-risk write tools have schemas.
**Risks to check**:
- Behavior change: anyone who relied on empty-schemas==permissive now gets abstain.
  Only `ravel_agent` / `multi_agent_orchestrator` legacy paths were updated to pass
  `permissive=True`; **verify no other caller** depends on the old default.
- ActionSchema `required_fields` use abstract `object_ref` until a target id is
  resolved at gate time (`build_action_schemas(target_object_id=...)`). Confirm the
  runtime resolves the real object id before calling `verify`.
- Policy checks are currently declarative strings (not yet programmatically
  enforced) — do not claim policy enforcement until wired.

## 3. RAVEL-CSI (Conflict-as-Signal)
**Files**: `src/ravel_core/conflict_signal.py`, tests in
`tests/test_phase2_new_algorithms.py`.
**Expected**: deterministic typed `ConflictSignal` from version state; 4 variants
all surface the reliable current value and **never a fake value**; wrong-value
perturbation deliberately excluded (probe only).
**Risks to check**:
- `CONFIRMED_CONFLICT` vs `STALE_VIEW` distinction relies on `seen_value` being
  passed; if callers omit it, confirmed conflicts collapse to stale_view.
- The `assert` in NoWrongValue rendering is a guard, not user-facing validation.

## 4. Evidence Uptake + Dependency-Preserving Router
**Files**: `src/ravel_core/evidence_uptake.py`, `src/ravel_core/dependency_router.py`,
`src/ravel_core/field_masking.py`, tests in `tests/test_phase2_new_algorithms.py`,
`tests/test_phase2_field_masking.py`.
**Expected**: per-action argument→evidence attribution + §7.1 uptake rates (None on
zero denom); DPR classifies fields by downstream dependency (must/should/compress/
drop) from the schema registry; field-masking regimes are deterministic & seeded.
**Risks to check**:
- Uptake attribution matches an argument value to evidence by **value equality**
  (`_match_value`); collisions (two fields with same value) could mis-attribute —
  review whether key-aware matching is needed before the uptake experiment.
- DPR `routing_token_savings` is a char-length proxy, not true tokenizer counts.
- `MaskActionCriticalOnly` deletes must_keep fields by design (a stress probe);
  ensure it is never used as a "method", only as a diagnostic regime.

---

## Not yet implemented (next code steps, before experiments)
1. Runtime emission of canonical `tool_call`/`commit` events from `ravel_mas`.
2. Unified runner for `single_agent_react` vs MAS methods (§8.3 methods 1–3).
3. Wiring CSI / DPR / field-masking regimes + non-permissive gate into the live
   MAS turn loop (currently library-level, unit-tested in isolation).
4. Telecom fixes (max_steps 50/60, forced timeout) before any telecom run (§5.4).
