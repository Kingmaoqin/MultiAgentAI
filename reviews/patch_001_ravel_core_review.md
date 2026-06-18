# Review Scope

Final re-review of patch 001 after latest fixes. Reviewed files:

- `/home/xqin5/multiaiagent/src/ravel_core/evidence.py`
- `/home/xqin5/multiaiagent/src/ravel_core/visibility.py`
- `/home/xqin5/multiaiagent/src/ravel_core/commit_gate.py`
- `/home/xqin5/multiaiagent/src/ravel_core/__init__.py`
- `/home/xqin5/multiaiagent/tests/test_ravel_core.py`
- `docs/`, `configs/`, and `reports/` for consistency with implementation and experiment-status claims

No source code was modified. This report file is the only updated artifact.

# Requirement Mapping

- Versioned Evidence Ledger: implemented by `EvidenceLedger` with object versions, logical clock, canonical payloads, field flattening, and `latest_field` lookup.
- Append-only / immutable ledger records: improved by recursively freezing field values with `MappingProxyType` and tuples in `evidence.py`.
- Visibility middleware: implemented by `VisibilityPolicy` for `FullSync`, `Delayed`, `FieldMask`, and `ConflictingView`; prompt-facing views now receive thawed copies.
- Schema-scoped commit gate: implemented by `CommitGate.verify`, looping over `schema.required_fields` rather than all ledger fields.
- tau2 benchmark semantics: no `tau2` imports appear in `ravel_core`; no tau2 source files are modified by this patch.
- Historical VSSC failure avoidance:
  - Global-field gate checks: avoided in the gate loop.
  - Substring write classification: no substring classifier in this patch; schemas are explicit.
  - SAR/CWR denominator collapse: no SAR/CWR metric code in this patch.
  - Ledger mutation by perturbed views: fixed in the re-reviewed implementation.

# Commands Executed

- `cd /home/xqin5/multiaiagent && PYTHONPATH=/home/xqin5/multiaiagent/src pytest -q`
  - Final re-review result: `16 passed in 0.15s`
- `PYTHONPATH=/home/xqin5/multiaiagent/src python -m compileall /home/xqin5/multiaiagent/src/ravel_core`
  - Result: passed; output was `Listing '/home/xqin5/multiaiagent/src/ravel_core'...`
- `nl -ba src/ravel_core/evidence.py`
- `nl -ba src/ravel_core/visibility.py`
- `nl -ba src/ravel_core/commit_gate.py`
- `nl -ba src/ravel_core/__init__.py`
- `nl -ba tests/test_ravel_core.py`
- `rg -n "tau2|tau3|sierra|ToolType|substring|SAR|CWR|denominator" src/ravel_core tests/test_ravel_core.py docs configs reports`
- `rg -n "RAVEL|complete|completed|final|NO-GO|mock smoke|held-out|experiment|validated" docs configs reports`
- Latest-change inspection:
  - `VisibleEvidenceState.from_views` now documents order-independent highest-version-wins behavior with evidence ID pairing.
  - `test_commit_gate_detects_missing_required_evidence` now directly covers missing required evidence.
- Re-ran previous mutable projection aliasing repro:
  - `PYTHONPATH=/home/xqin5/multiaiagent/src python -c 'from ravel_core import EvidenceLedger, VisibilityPolicy; ledger=EvidenceLedger(); r=ledger.ingest(object_id="o", tool_name="t", payload={"empty": []}, source_agent="a"); v=VisibilityPolicy("FullSync").project(r, agent_id="b", event_index=r.logical_clock); v.visible_fields["empty"].append("mutated"); print(r.field_values["empty"], v.visible_fields["empty"])'`
  - Result: `() ['mutated']`
- Re-ran previous out-of-order traceability repro:
  - `PYTHONPATH=/home/xqin5/multiaiagent/src python -c 'from ravel_core import *; ledger=EvidenceLedger(); old=ledger.ingest(object_id="reservation:R1", tool_name="get", payload={"status":"open","reservation_id":"R1"}, source_agent="a"); new=ledger.ingest(object_id="reservation:R1", tool_name="get", payload={"status":"cancelled","reservation_id":"R1"}, source_agent="a"); views=[VisibilityPolicy("FullSync").project(new, agent_id="x", event_index=2), VisibilityPolicy("FullSync").project(old, agent_id="x", event_index=2)]; state=VisibleEvidenceState.from_views(views); gate=CommitGate({"cancel": ActionSchema("cancel", (RequiredEvidence("reservation:R1","status"), RequiredEvidence("reservation:R1","reservation_id")))}); cand=CandidateWrite("cancel", {}, ("reservation:R1",), (old.evidence_id,)); d=gate.verify(cand, ledger=ledger, visible_state=state); print(state.versions[("reservation:R1","status")], state.evidence_ids[("reservation:R1","status")], old.evidence_id, new.evidence_id, d.verdict, d.reasons)'`
  - Result: `2 ev-000002-20cf5659082d ev-000001-37bfadc47018 ev-000002-20cf5659082d replan ('untraceable_required_evidence',)`
- Additional frozen empty-mapping regression probe:
  - Result: first ingest `changed_fields == ('empty',)`, second identical ingest `changed_fields == ()`
- Additional missing-evidence branch probe:
  - Result: `reconcile ('missing_required_evidence',)` with the expected `RequiredEvidence` in `missing_fields`

# Design Findings

The patch remains minimal and standalone. The separation between ledger storage, visibility projection, and gate verification is still appropriate for a pre-integration core library.

The two previous design concerns are resolved:

- `evidence.py` now freezes ledger field values recursively before storage and stores the top-level field mapping as a `MappingProxyType`.
- `visibility.py` now thaws prompt-facing field values before returning views, so prompt-visible mutations do not alias back into authoritative ledger state.
- `commit_gate.py` now keeps visible-state version and evidence ID paired by updating evidence IDs only when a newer version is accepted and ignoring older out-of-order views.
- `commit_gate.py` now documents that `VisibleEvidenceState.from_views` is order-independent for the same object field and keeps evidence IDs paired with the winning version.

# Functional Findings

No blocking functional issues found in the re-review.

Previously blocking issue 1, ledger/view aliasing, is fixed. The exact repro now leaves the ledger value as `()` while the prompt-facing view mutates independently to `['mutated']`.

Previously major issue 2, out-of-order visible-state traceability mismatch, is fixed. The exact repro now keeps the version-2 evidence ID paired with version 2 and returns `replan` with `untraceable_required_evidence` when the candidate references only stale evidence.

The gate remains schema-scoped: it checks only `ActionSchema.required_fields`, not all visible or ledger fields.

# Benchmark Integrity

No tau2 source is imported by `src/ravel_core`. The docs continue to state that tau2 integration is future wrapper work and that tau2 itself should not be modified for RAVEL.

I could not use git metadata for patch-boundary verification because `/home/xqin5/multiaiagent` is not a git repository, but the reviewed source files themselves do not alter tau2 benchmark semantics.

# Statistical/Experimental Integrity

No statistical or experimental result code is introduced in this patch. There is still no SAR/CWR denominator logic, aggregation logic, or held-out result analysis in the reviewed core files.

The docs and reports remain appropriately cautious: full RAVEL experiments are marked `NO-GO`, the completed baseline is limited to one mock smoke run, and official domain baselines/token accounting remain not verified.

# Test Quality

The expanded tests now cover the critical invariants that failed the prior review:

- mutable projection values cannot mutate ledger field values
- record field mappings reject direct mutation
- out-of-order views keep version and evidence ID paired
- stale-only evidence references now produce an untraceable/replan decision in that regression path

The suite also continues to cover deterministic canonicalization, field flattening, versioning, changed fields, all four visibility regimes, schema-scoped gate behavior, stale evidence, conflicting evidence, and empty traceability.

The previous missing-required-evidence test gap is now closed by `test_commit_gate_detects_missing_required_evidence`.

# Complexity and Unnecessary Code

The code remains compact. `CandidateWrite.claimed_preconditions`, `ActionSchema.policy_checks`, and some metadata fields are still unused placeholders, but they do not add meaningful complexity or risk at this stage.

# Documentation

Documentation does not overclaim full RAVEL completion or final experiment completion. It clearly distinguishes:

- local core/unit work from future tau2 wrapper integration
- mock smoke baseline from official domain baseline reproduction
- preregistration/planning from validated held-out results

# Blocking Issues

None.

# Non-blocking Issues

None.

# Verdict

APPROVED
