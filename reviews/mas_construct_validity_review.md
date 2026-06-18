# RAVEL Multi-Agent — Scientific Auditor Review (Construct Validity)

- **Role**: Independent Scientific Auditor (construct validity), separate from the code reviewer. Did not author this code.
- **Commit**: `4958f7c76081a573be49932244dec7507cfc7d78`
- **Scope**: Whether the runtime measures what the RAVEL proposal claims, and whether it is genuinely multi-agent. NOT code style.
- **Inputs read**: `MultiAiAgentProposal.pdf` (§4 architecture L580-700, §5 experiment design L834-1002), `multiagent构筑要求` (§2, §6, §13-§15), `src/ravel_mas/*`, `artifacts/mas_proof/*`, `tests/test_mas_*.py`.
- **Date**: 2026-06-17

---

## Construct Validity Table

| Construct | Intended definition (Proposal / Contract) | Runtime implementation | Observable evidence (file/artifact) | Verdict |
|-----------|-------------------------------------------|------------------------|-------------------------------------|---------|
| ≥3 real LLM decision entities | Supervisor / Policy / ToolWorker each: unique id, own prompt, own state, own tool allowlist, own LLM call (§2.1) | 3 distinct `BaseAgent` subclasses, each with own `AgentState`, distinct `prompt_hash`, own `_invoke()` → `client.generate(agent_id=...)` | `agents.py`; `runtime_trace_readable.md` shows `LLM_CALL agent=supervisor/policy_agent/tool_worker` with 3 distinct prompt hashes (df1d8afa / 1100090f / b7501bea); `agent_state_manifest.json` distinct `state_object_id` | VALID (architecture) — but driven by `FakeModelClient`, not a real model |
| Independent state | `supervisor.state is not policy.state …` (§2.2) | Each agent constructs its own `AgentState()`; team asserts non-identity at init | `team.py` L65-67 assert; `test_mas_state_isolation.py` | VALID |
| Agent-to-agent typed messages | TaskAssignment/PolicyRequest/PolicyDecision/EvidenceRequest/CandidateWrite/ReconciliationRequest… with ids, source/target, parent (§2.3) | `MessageBus.publish` logs typed messages with parent linkage; recorded in trace | `runtime_trace_readable.md` MESSAGE lines; `messages.py` | VALID |
| Dynamic delegation | Supervisor LLM emits structured `{target_agent, subgoal, …}`; no hardcoded Policy→Worker order (§2.4) | `team.run_turn` reads `decision["target_agent"]` from supervisor output; only legal transitions enforced | `team.py` L145-220; delegation events in trace | VALID in `team.py`. **Caveat**: the shipped one-task trace was produced by `runtime_proof.py`, which **hardcodes** the d1→policy, d2→worker sequence (the loop in `team.py` is not what generated the artifact). |
| VDL / Versioned Evidence Ledger | Append-only, versioned, field-delta, digest, latest-field lookup (Proposal §4.2) | Reuses `ravel_core.evidence.EvidenceLedger`; append-only, per-object version, `changed_fields`, digest | `evidence.py` ingest L134-195 | VALID (reused deterministic component) |
| MSE-Router / per-agent views | Same object → different view per role; e.g. worker v4, supervisor v5 header, commit full (§2.5, Proposal §4.3) | `ViewBuilder.view_for` = version selection (`_version_for`) + role field selection (`_select_fields`) | `agent_views.json`; `views.py` | PARTIAL — role field-masking is real and rule-based; but see ConflictingView row |
| Two-phase commit / gate | Worker proposes only; CommitService is sole writer; validates declared **and** actual read-set; stale/conflict/version checks (§4.5, Proposal §4.4) | `CommitService.verify` checks expected-vs-latest version, required fields, traceability, `conflict_flag`; only it holds `execute_write` + token | `commit_service.py`; trace `COMMIT_SERVICE verdict=reconcile reasons=['stale_read_set']`; `tool_permission_manifest.json` `worker_holds_real_write=false` | VALID for stale path; **conflict path never exercised** (see Q4) |
| ARB (reconciliation ladder) | Strict escalation: missing→delta→conflict→requery→semantic→replan→abstain; no first-failure raw broadcast (§5.3) | `ReconciliationBudget.reconcile` stages 1-7; only stage 4 requeries offending objects | `reconciliation.py`; trace shows requery then commit | VALID (mechanism); only the stale→requery branch demonstrated at runtime |
| FullSync regime | All agents see latest version, role-filtered (not raw transcript) (§6.1) | `_version_for` returns latest for all; field filtering preserved; FullSync commit view == raw latest | `test_mas_visibility.py::test_fullsync_does_not_corrupt_tool_payload` | VALID |
| Delayed regime | Worker pinned d versions back; delivery time / visible version recorded (§6.2) | `_version_for` returns `latest-delay` for tool_worker only | `views.py` L91-92; `test_delayed_regime_pins_worker_to_older_version` | VALID (construct); delivery-time field not separately logged |
| RoleAwareFieldMask | Hide an action-critical field from non-owner by role/dependency, ledger unchanged (§6.3) | `_select_fields` drops `masked_field` from worker view only | `views.py` L119-120; `test_role_aware_field_mask_hides_only_from_worker` | VALID |
| ConflictingView | **Real cross-agent** disagreement: worker sees vN value, supervisor/commit see vN+1 with **different field value**; not synthetic corruption (§6.4) | `_version_for` **pins worker one version back**; the differing *value* exists only if the ledger itself contains a value-flipping vN→vN+1 | `agent_views.json` (worker v4 `status=confirmed` vs commit v5 `status=cancelled`) — REAL. **But** `evidence_visibility_manifest.json` (the actual runtime-trace ledger) shows worker v2 / supervisor v3 **both `status=confirmed`** — version differs, value identical. | **PARTIAL** — valid in the synthetic `visibility_proof` ledger; **NOT demonstrated in the one real runtime trace** |

---

## Answers to the 6 mandatory questions (Contract §13)

### 1. What is the actual manipulated independent variable at runtime? Visibility BETWEEN agents, or one agent's mutated observation?

It is implemented **between agents**, not by mutating a single shared observation — which is the correct direction. The mechanism is `ViewBuilder.view_for(agent_id, object_id)`, which derives each agent's view from a shared ledger via two knobs: a per-agent **version pin** (`_version_for`) and a per-role **field filter** (`_select_fields`). There is no code path that edits one agent's `messages` to inject a regime; the regimes are differences in projection across agents. This satisfies Contract §6's "必须在真实 Agent 间实现，而不是修改同一个 Agent 的单条 observation."

**However**, the IV as realized is primarily **version freshness + field masking**, not value-level disagreement. For Delayed/FieldMask/FullSync that is exactly the intended construct. For **ConflictingView the IV degenerates to "which version number each agent is pinned to"**; whether that pinning produces an actual *value* conflict depends entirely on whether the experiment harness ingested a value-flipping version into the ledger. `ViewBuilder` itself never creates a conflict — it only selects an older version that may or may not differ in value.

### 2. Is the measured system genuinely multi-agent (≥3 real LLM decision entities) per the runtime trace — not class names?

**Architecturally yes, empirically not yet.** The trace shows three distinct `agent_id`s issuing their own LLM calls with three distinct system-prompt hashes, independent state objects, independent token accounting, and an allowlist that denies the worker any real write tool. This clears the "not just class names / role strings" bar in Contract §2.1. The user simulator is correctly excluded (`test_mas_user_simulator_*`, `internal_agent_ids` ≥3 without `user_simulator`).

The decisive caveat: every LLM call in the shipped trace is served by **`FakeModelClient`** with hardcoded scripted JSON (`runtime_proof.py` L69-98). So the trace proves the *plumbing* for three independent agents, not that three independent *models* actually made decisions. Per Contract §1, "实际 LLM 调用" is the standard of proof; the real-model path (`OpenAIModelClient`) exists but has not been exercised. This is acceptable for an **architecture proof** (Contract §9/§15 explicitly permit fake responses pre-tau2) but cannot back a multi-agent empirical claim.

### 3. Does the main method align with the Proposal constructs (VDL ledger, MSE-router views, two-phase commit, ARB)?

Yes, structurally. VDL = reused `EvidenceLedger` (append-only, versioned, field-delta, digest). MSE-router = `ViewBuilder` rule-based role∩subgoal field selection (matches Proposal Eq. 13's rule-based first stage). Two-phase commit = `CommitService` propose→validate→commit with worker-declared **and** ledger-actual read-set, sole write token. ARB = `ReconciliationBudget` strict 7-stage ladder. All four modules are present and wired in `runtime_proof.py`. The one substantive divergence from §2.4/Proposal §4.1: the **shipped artifact** was generated by the hardcoded `runtime_proof.py` script, not by the dynamic `team.run_turn` loop — so "dynamic delegation" is proven by `team.py` + tests, but the inspectable runtime trace itself is a fixed Supervisor→Policy→Worker sequence.

### 4. Are FullSync / Delayed / RoleAwareFieldMask / ConflictingView each VALID? Is ConflictingView a real cross-agent version disagreement or a synthetic corruption?

- **FullSync — VALID.** Commit view equals raw latest field set (semantic identity test passes); role filtering preserved, no raw-transcript leak.
- **Delayed — VALID.** Worker pinned `latest-delay`; clean construct.
- **RoleAwareFieldMask — VALID.** Named action-critical field dropped from the worker view only, ledger untouched.
- **ConflictingView — PARTIAL / the central concern.**
  - It is **not** a banned synthetic corruption: there is no `"CONFLICT::"` string injection, no mechanical `+1`, no single-agent observation edit. The mechanism is version pinning (`views.py` L93-96: worker → `latest-1`).
  - In the **synthetic `visibility_proof` ledger** it *does* produce a genuine cross-agent value disagreement, because `build_conflicting_ledger` (`visibility_proof.py` L24-30) deliberately ingests v4 `status=confirmed` and v5 `status=cancelled`. Evidence: `agent_views.json` — `tool_worker.version=4 status=confirmed` vs `commit_service.version=5 status=cancelled`. This matches Contract §6.4's required pattern ("Worker sees status=confirmed v4 / Supervisor sees status=cancelled v5"). VALID **here**.
  - But in the **one real end-to-end runtime trace** the disagreement collapses to version-number-only. `runtime_proof.py` ingests `status="confirmed"` at *every* version (L113 requery and L154/L169 both pass `"confirmed"`), so `evidence_visibility_manifest.json` shows worker v2 / supervisor v3 / commit v3 **all `status=confirmed`**. At runtime there is **no value conflict** — this is operationally a Delayed/stale read relabeled as ConflictingView. The CommitService rejects it via `stale_read_set` (expected v1 ≠ latest v2), never via a conflict.
  - Corroborating gap: `conflict_flag` defaults `False` and is **never set True** on any ledger ingest in any proof path (`evidence.py` L143; grep confirms no caller passes it). Therefore `CommitService.verify`'s `conflict` branch (`commit_service.py` L119) and ARB stage-3 "inspect_conflicting_versions" are **dead at runtime** — they are covered only by the construction of `agent_views.json`, never by an executed trajectory.

  **Verdict: ConflictingView is a VALID construct in the visibility unit-proof but is NOT yet demonstrated as a real cross-agent value conflict inside an executed runtime trajectory.** The two artifacts (`agent_views.json` vs `evidence_visibility_manifest.json`) come from two different ledgers, and only the non-executed one carries the conflict.

### 5. Confounds that would undermine a causal claim about visibility?

The architecture itself controls the headline confounds the Proposal worries about (§5.4, L985: same task seed, same model checkpoint, same prompts, deterministic middleware-driven perturbation, no extra LLM generating the perturbation). Specific points:

- **No extra-LLM confound for perturbation** — regimes are produced by `ViewBuilder` (deterministic), not by an LLM rewriting evidence. Good; this is exactly the Proposal's requirement.
- **Variable LLM-call count across regimes is a real confound risk.** ARB only escalates when a verdict is non-commit, and the number of escalation rounds (hence extra agent calls / tokens) differs by regime. That is a *legitimate dependent variable*, but it must be reported per the Proposal's plan (L1141 reports LLM calls / ledger fetch / raw fetch) and not conflated into the utility comparison. Not yet a defect, but flag for analysis.
- **Prompt-content confound is controlled**: per-agent prompts are fixed (`builders.py`), distinct by design (the IV is the *view text* injected, not the system prompt).
- **Domain-agnostic field heuristic is a mild internal-validity risk.** `POLICY_FIELDS` / `ACTION_FIELDS` (`views.py` L56-57) are hardcoded English field-name sets; under real tau2 domains a field could be mis-routed, contaminating which agent sees what. Contract notes this is "refined per-domain in Phase 5" — must be pinned per domain before any causal claim.
- **No private CoT leakage** — only structured outputs/reason codes are stored, satisfying §14.

### 6. Can the current trace support a publishable claim, or only an architecture-proof claim?

**Architecture-proof only.** The single trajectory uses a deterministic `FakeModelClient`; no real tau2 trajectory and no real model decision has been run. It correctly demonstrates: three independent agent identities, typed messaging, dynamic-delegation *capability*, write-path isolation, stale-read rejection, and ARB requery→commit. It does **not** demonstrate: (a) any real-LLM behavior, (b) a real cross-agent value conflict inside an executed run, (c) the conflict-detection / conflict-reconciliation code paths firing at runtime, (d) tau2 benchmark integrity (acceptance JSON itself reports `benchmark_integrity: NOT_VERIFIED`). Per Contract §16 a pilot is gated on Code-Review APPROVED + Auditor APPROVED + verified write isolation + unchanged evaluator; the empirical RQ1 visibility-causality claim is out of reach from this trace alone.

---

## Final Verdict

**CHANGES_REQUIRED**

Rationale: Contract §13 mandates that a single FAIL on a core construct blocks formal experiments. The ConflictingView construct — one of the four named visibility regimes and the most discriminating one for the write-safety claim — is **PARTIAL**: it is only a genuine cross-agent *value* conflict in a synthetic unit-proof ledger (`agent_views.json`), while the one executed runtime trajectory (`evidence_visibility_manifest.json`) carries a version-number-only difference with identical `status=confirmed`, and the conflict-detection paths (`conflict_flag`, CommitService conflict branch, ARB stage-3) are never exercised at runtime. The system as *traced* manipulates freshness/field-masking, not value-level cross-agent disagreement.

This is a construct-validity defect, not a code-style nit: as shipped, the runtime trace cannot distinguish ConflictingView from Delayed.

### Most important construct-validity concern (single line)
**ConflictingView is real only in the non-executed `visibility_proof` ledger; the one actual runtime trace ingests `status=confirmed` at every version, so its "conflict" is version-number-only (operationally a stale/Delayed read), and the conflict-detection code paths (`conflict_flag` / CommitService conflict branch / ARB stage-3) never fire.**

### Required changes before formal experiments
1. Produce a real executed one-task trajectory in which the worker's view and the supervisor/commit view disagree on an actual **field value** (e.g. ingest a true `confirmed → cancelled` version inside `runtime_proof.py`, not all-`confirmed`), so `evidence_visibility_manifest.json` shows divergent values and the CommitService rejects on **conflict**, not (only) stale-version.
2. Exercise `conflict_flag=True` ingestion at least once so `CommitService.verify` conflict branch and ARB stage-3 ("inspect_conflicting_versions") are demonstrably hit in a trace.
3. Re-run the inspectable trajectory through the **dynamic** `team.run_turn` loop (not the hardcoded `runtime_proof.py` sequence) so the trace itself evidences §2.4 dynamic delegation.
4. Run at least one trajectory on `OpenAIModelClient` (real model) before any multi-agent empirical claim; the `FakeModelClient` trace backs only the architecture proof.
5. Pin `POLICY_FIELDS` / `ACTION_FIELDS` per tau2 domain before causal analysis to avoid field-routing confounds.

*No source files were modified by this review.*

---

## Round 2 — Re-audit of CHANGES_REQUIRED fixes

- **Role**: Independent Scientific Auditor (round 2), separate from the code reviewer; did not author this code.
- **Commit audited**: `4675cd5b5d8f212e4e051307ad6b6a53d3463b53` (verified via `git log -1`; acceptance JSON `commit_sha` matches).
- **Method**: re-ran `python3 scripts/mas_acceptance.py`; read new artifacts (`conflict_trace_readable.md`, `delegation_trace_readable.md`, `evidence_visibility_manifest.json`); independently re-executed `run_conflict_task_proof` and `run_delegation_trace_proof`; traced source in `commit_service.py`, `reconciliation.py`, `team.py`, `agents.py`, `views.py`, `runtime_proof.py`. No source files modified.
- **Date**: 2026-06-17

### Updated construct-validity verdicts (rows changed from Round 1)

| Construct | Round 1 verdict | Round 2 verdict | What changed |
|-----------|-----------------|-----------------|--------------|
| Dynamic delegation | VALID-in-code, artifact hardcoded | **VALID (now traced)** | `delegation_trace_readable.md` is now produced by the live `team.run_turn` loop, which routes on `decision["target_agent"]` parsed from the supervisor's LLM output (`team.py` L148-224, `agents.py` L112-117). 3 delegation events, target not hardcoded. |
| Two-phase commit / conflict branch | VALID stale; conflict branch dead | **VALID (conflict branch now exercised)** | `CommitService.verify` now performs a **value-level** check: each `claimed_precondition` is compared to `ledger.latest_field` (`commit_service.py` L132-149). The executed `run_conflict_task_proof` hits it (`conflict_reasons=['reservation:R1.status:claimed=confirmed!=latest=cancelled']`). Independent of `conflict_flag`. |
| ARB stage-3 (`inspect_conflicting_versions`) | dead at runtime | **VALID (reached)** | Re-executing the conflict proof returns `arb_inspected_conflict_stage: true`; ladder runs 1→7 and, because no requery can make "cancel an already-cancelled reservation" valid, exhausts to **abstain** (`conflict_trace_readable.md` final line). |
| ConflictingView | PARTIAL (real only in non-executed ledger; runtime all-`confirmed`) | **VALID (real value disagreement; see caveat on manifest provenance)** | `evidence_visibility_manifest.json` is now built over a value-flipping ledger (`confirmed×4 → cancelled@v5`), giving worker v4=`confirmed` vs policy/commit v5=`cancelled`. No string-injection / mechanical mutation; pure version selection (`views.py` L93-96) over a genuinely flipping ledger. |

### Answers to the 4 re-check points

**1. Does an EXECUTED runtime trace now show a REAL value conflict detected by CommitService, with ARB stage-3 reached? — YES.**
`run_conflict_task_proof` is an executed trajectory (I re-ran it independently). The worker proposes `cancel_reservation` relying on `claimed_preconditions: status==confirmed`; the environment flipped the ledger value to `cancelled@v2` first. `CommitService.verify` detects the **value** mismatch at `commit_service.py` L137-149 (`latest_field` returns `cancelled`, `holds=False`), yielding `reasons` containing `unresolved_conflict` with the literal value pair `claimed=confirmed!=latest=cancelled`. This is a true cross-agent value conflict (worker's relied-upon value ≠ latest world state), NOT a version-number difference. ARB then runs the full ladder; `arb_inspected_conflict_stage: true` confirms stage-3 (`inspect_conflicting_versions`) is reached, and because the conflict is unrepairable the system **abstains** (`committed=false`, `env_cancelled=false`). The prior "dead conflict branch + dead ARB stage-3" finding is resolved.

**2. Is `evidence_visibility_manifest.json` now a genuine value disagreement, not just version numbers? — YES (value), with one provenance caveat.**
The manifest now derives from a value-flipping ledger (`runtime_proof.py` L239-250): worker(v4)=`status=confirmed`, policy/commit(v5)=`status=cancelled`. That is a real value-level disagreement and clears the Round-1 "all-`confirmed`, version-only" defect. **Caveat (bounded, not blocking):** this manifest is built from a *separately constructed* `conflict_ledger` + `ViewBuilder`, not from the ledger the agents actually consumed inside `run_one_task_proof`. So it is a faithful demonstration of the ConflictingView *projection* over a real value-flip, but it is a constructed visibility manifest rather than the agents' as-consumed views during that specific executed turn. The value-conflict that is exercised *inside an executed decision path* is the CommitService one in point 1 — which is the substantive guarantee.

**3. Is dynamic delegation evidenced by a LIVE `team.run_turn` trace, not a hardcoded sequence? — YES.**
`delegation_trace_readable.md` is generated by `run_delegation_trace_proof`, which calls `team.run_turn` (`runtime_proof.py` L349-357). In `team.py` L148-224 the loop calls `supervisor.decide(...)`, parses the structured JSON, and routes purely on `decision["target_agent"]` / `action`; targets are not hardcoded and the loop terminates on a supervisor-emitted `Finish`. `SupervisorAgent.decide` (`agents.py` L112-117) parses the model output, so a different model response would change routing. Re-execution gives `generated_by: "team.run_turn (live dynamic delegation)"`, `delegation_events: 3`, `targets: [policy_agent, tool_worker, terminal]`. The Round-1 "artifact came from a hardcoded `runtime_proof` sequence" finding is resolved for the delegation artifact.

**4. Honest statement of what the evidence DOES and does NOT support.**
*Supports (architecture proof):* (a) three independent LLM agent identities with distinct prompt hashes, independent state objects, independent token accounting, worker denied any real write tool; (b) typed agent-to-agent messaging with parent linkage; (c) dynamic delegation driven by parsed supervisor output, traced through the live loop; (d) write-path isolation (CommitService sole writer, single-use token, `WriteIsolationError` guard); (e) **a real cross-agent value conflict** (`confirmed` vs `cancelled`) detected deterministically by CommitService and safely **abstained** after the ARB ladder including stage-3; (f) ConflictingView as a real value-divergent projection.
*Does NOT support:* every model call is still `FakeModelClient` with scripted responses — so the control-flow plumbing is genuine but no *real model* has made any decision. No real-model τ2 trajectory has been run; `benchmark_integrity` remains `NOT_VERIFIED`; `code_review` and `construct_validity_review` are `NOT_RUN` in the acceptance JSON. The dynamism is real at the routing level but the routing *content* is deterministic, so this cannot back any empirical multi-agent or RQ1 visibility-causality claim. **This limitation is clearly bounded** by the contract (fake responses permitted pre-τ2; pilot gated on reviews + verified write isolation) and is explicitly self-disclosed in the acceptance JSON and the `overall_status: PASS_ARCHITECTURE_PENDING_REVIEW`.

### Final Verdict

**APPROVED** (for the architecture-proof scope; real-model pilot remains correctly gated).

All four Round-1 required changes are now backed by executed artifacts and source, not just the unit-proof ledger: the conflict branch and ARB stage-3 fire on a genuine `confirmed→cancelled` value conflict and the system abstains; the visibility manifest carries a real value disagreement; the delegation trace is produced by the live dynamic `team.run_turn` loop. The remaining gap (no real model has run) is a scope boundary the contract permits and the acceptance JSON self-reports, not a construct-validity defect in the shipped architecture.

**Most important remaining construct-validity caveat (single line):** every decision is still served by `FakeModelClient` with scripted JSON, so the system proves the multi-agent *mechanism* (independent identities, value-conflict detection, dynamic routing, write isolation) but NOT real-model *behavior* — no empirical or RQ1 visibility-causality claim is supported until at least one real-model (`OpenAIModelClient`) τ2 trajectory is run under the gated pilot.

*No source files were modified by this Round 2 review.*
