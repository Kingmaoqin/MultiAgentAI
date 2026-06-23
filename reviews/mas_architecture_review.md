# MAS Architecture Review — Independent Code Reviewer

- **Commit:** 4958f7c76081a573be49932244dec7507cfc7d78 (branch feature/ravel-mas)
- **Scope:** src/ravel_mas/, tests/test_mas_*.py, artifacts/mas_proof/
- **Method:** verified from source / tests / runtime trace only; author summaries ignored.

## Summary verdict line

The core multi-agent architecture (3 distinct LLM agents, independent state, distinct prompts, dynamic delegation, typed bus messages, agent-specific versioned views, deterministic single-write-path CommitService, real stale/conflict/forged-token blocking, valid mutation tests) is **genuinely implemented and verified** in the Phase 1–4 (FakeModelClient) path. However, the tau2-facing wrapper (`team_agent.py`) — the only path that runs real LLMs and the actual benchmark — is **completely unexercised by any test or trace**, `benchmark_integrity` is self-reported `NOT_VERIFIED`, and the required integration test `tests/test_tau2_team_integration.py` is **missing**. The architecture proofs are sound; the *benchmark faithfulness* claim is unproven.

## Per-check findings

| # | Check | Evidence (file:line) | Verdict | Note |
|---|-------|----------------------|---------|------|
| 1 | ≥3 LLM agents, unique id / distinct prompt_hash / independent state / independent allowlist | agents.py:39-62 (own `AgentState` per instance), builders.py:85-99 (distinct prompts, allowlists), team.py:65-67 (state-isolation assert) | **PASS** | `prompt_hash` = sha256 of distinct prompt text; state is a fresh `AgentState()` per `__init__`. Verified live in acceptance: 3 distinct ids. |
| 2 | Typed messages on a MessageBus with full envelope | messages.py:36-63 (envelope fields incl. message_id, source, target, type, logical_time, parent, evidence_ids), messages.py:96-107 (logged append-only) | **PASS** | `Message.__post_init__` rejects unknown types (messages.py:49-51). Logged into trace as events. |
| 3 | Dynamic delegation from Supervisor LLM output, not hardcoded | team.py:145-220 (target read from `decision["target_agent"]`), test_mas_delegation.py:23-47 (different sup output → different routing; policy_agent absent when not chosen) | **PASS** | Loop dispatches on the LLM's structured `target_agent`. Order is data-dependent. team_agent.py:175-204 mirrors this. |
| 4 | Different agents get different version+fields of SAME object; ConflictingView is real not synthetic | views.py:87-135 (`_version_for` pins worker to `latest-1`, others latest), visibility_proof.py:21-59 (5 real ledger versions, status flips confirmed→cancelled), test_mas_visibility.py:21-29 | **PASS** | Worker view = v4 status="confirmed"; commit view = v5 status="cancelled" — both are **real prior ledger records**, not a "CONFLICT::" string or +1 hack. Underlying `EvidenceLedger.object_version` increments per ingest (evidence.py:164-165). |
| 5 | ToolWorker physically lacks real write tools (allowlist); only deterministic CommitService writes | builders.py:94-99 (`allowed_tools = read + propose_candidate_write`), team_agent.py:84-86 (`_read_tools` excludes write names), commit_service.py:63 (not an LLM), commit_service.py:167-178 (`execute_write` token-gated) | **PASS** | Allowlist is by construction, not prompt. CommitService is a plain class with deterministic checks. |
| 6 | Stale / conflict / forged-token / no-token writes blocked, env unchanged | commit_service.py:113-148 (stale→reconcile, conflict→reconcile), commit_proof.py:75-130, test_mas_commit_isolation.py:30-67 | **PASS** | Verified: stale `committed=False env_cancelled=False`; forged + no-token both raise `WriteIsolationError`; env stays unchanged. |
| 7 | Mutation tests actually flip an invariant; none vacuous | test_mas_mutations.py:23-138 | **PARTIAL PASS** | 7 of 9 mutations genuinely re-run the real check and assert it flips (shared-list, same-id, identical-prompts, leaked-write-tool, fixed-order, disabled-version-check via monkeypatched `verify`, identical-views). **Two are weak** — see Problem A. |
| 8 | tau2 wrapper faithful; never lets worker emit real write; doesn't modify task/policy/evaluator | team_agent.py:131-154 (worker tools = read + propose only), team_agent.py:219-228 (defensive block of write-named tool calls), team_agent.py:251-255 (only wrapper emits real write after commit) | **PARTIAL / UNVERIFIED** | Logic is correct by inspection. But this path is **never executed by any test or trace** (Problem B). `_inner` `LLMAgent` is built with full write tools (team_agent.py:107) yet only used for `get_init_state` (team_agent.py:113-114) — it never generates, so no leak, but it is latent risk. No diff to tau2 task/policy/evaluator found. `benchmark_integrity` remains `NOT_VERIFIED`. |
| 9 | Dead code / duplicate impl / role-string fakery | agents.py (real instances, no role-string agents), reconciliation.py:53-112, team.py:227-256 | **PARTIAL** | No role-string fakery; ledger/logger reused not reimplemented (good). But `SemanticVerifierAgent` and `ReconciliationBudget` are **never invoked in `team.py.run_turn`** (Problem C) — only in the standalone `runtime_proof.py`. ARB in run_turn just records a request and `continue`s (team.py:167-172). |

## Concrete problems found

### Problem A — Two mutation tests are vacuous (do not exercise the production guard)
`test_mas_mutations.py:117-124` (`test_mutation_bypassing_commit_service_changes_env_without_token`) simply calls `env.cancel(...)` directly and asserts `env.cancelled is True`. It proves a raw dict can be mutated — it never touches `CommitService`, so it cannot fail if the write-path guard were removed. Likewise `test_mutation_disabling_version_check_admits_stale_write` (test_mas_mutations.py:90-114) monkeypatches `svc.verify` to a hand-written always-commit stub; it tests the stub, not that the real version check is load-bearing.
**Why it matters:** Contract §11 requires each mutation to flip a *real* architecture invariant. These two assert tautologies and would still pass if the corresponding production guard were deleted.
**Suggested fix:** For bypass: assert that `CommitService.execute_write(cw, token=None)` raises and `env.cancelled is False` (the guard), then show that *removing* the token check (a real monkeypatch of `execute_write`) lets env change. For version-check: monkeypatch only the stale-detection branch inside the real `verify` (e.g., force `expected==latest`) rather than replacing the whole method, so the test depends on the real code path.

### Problem B — The tau2 wrapper (`team_agent.py`) is entirely unverified
`grep` shows no test, script, or trace references `RAVELTeamAgent` / `create_ravel_team_agent` (only a docstring mention in tau2_client.py:4). Every passing test and every artifact in `artifacts/mas_proof/` is produced by the FakeModelClient path (`builders.py`, `runtime_proof.py`), which is a *separate* hand-scripted trajectory and does **not** import `team_agent.py`. The deliverable `tests/test_tau2_team_integration.py` (Contract §19) is missing.
**Why it matters:** All write-isolation, delegation, and visibility guarantees that the paper would rely on must hold on the *real* tau2 path. None of that path is currently demonstrated. The runtime trace at artifacts/mas_proof/runtime_trace_readable.md is a deterministic fake scenario, not a tau2 run.
**Suggested fix:** Add `tests/test_tau2_team_integration.py` that drives `RAVELTeamAgent.generate_next_message` with stubbed `tau2_generate` returning (a) a read tool call, (b) a `propose_candidate_write`, (c) a forced real-write-name tool call — asserting respectively: read reaches tau2, candidate routes through CommitService, and the write-named call is blocked (team_agent.py:219-222). Until then, do not claim benchmark faithfulness.

### Problem C — SemanticVerifier and ARB are not wired into the main team loop
`RAVELTeam.run_turn` never calls `self.semantic_verifier` and never instantiates `ReconciliationBudget`; on `RequestReconciliation` it only logs and `continue`s (team.py:167-172). The full ARB ladder (stale→requery→commit) is exercised *only* in the standalone `runtime_proof.py:118,195`. So the acceptance flag `arb_selective_requery_observed` reflects the proof script, not the orchestration runtime the wrapper uses.
**Why it matters:** Contract §3/§5.3 place ARB and the optional verifier in the live path. As-is they are interface-complete but not integrated into `team.py` / `team_agent.py`.
**Suggested fix:** Invoke `ReconciliationBudget.reconcile` from `_route_to_commit_service` (team.py:227) and from `team_agent._verify_candidate` (team_agent.py:231) on a non-commit verdict, instead of only emitting a ReconciliationRequest message.

### Minor
- `DOMAIN_WRITE_TOOLS` (ravel_core/ravel_agent.py:76-81) has only airline/retail/telecom — **no `banking`** entry. Per MEMORY the study spans airline/banking/telecom/retail; a banking task would yield an empty write-tool set, so `_read_tools` would include real banking writes and the worker could emit them. Confirm banking is out of scope for the MAS path or add its write set before any banking run.
- `team_agent.py:107` constructs `_inner = LLMAgent(tools=tools, ...)` with the full (write-capable) tool list. It is currently only used for `get_init_state`, so no leak — but it is a foot-gun; prefer constructing it without write tools or document why.

## Final Verdict

**CHANGES_REQUIRED**

Rationale: The Phase 1–4 architecture is real and well-tested — this is not role-string fakery, the views/conflict/commit guards are genuine. But Contract completion (§18) requires the *benchmark* path to be demonstrated and `benchmark_integrity` verified. The sole real-LLM/tau2 path (`team_agent.py`) has zero test or trace coverage, its required integration test is missing, two mutation tests are vacuous (§11 violation), and ARB/verifier are not integrated into the live loop. These are core-architecture verification gaps, so per Contract §12 the verdict must be CHANGES_REQUIRED. The acceptance manifest correctly reports `overall_status="PASS_ARCHITECTURE_PENDING_REVIEW"` and `code_review="NOT_RUN"`, so no false completion is asserted.

---

## Round 2 — Independent re-review of the 4 fixes

- **Commit:** `4675cd5b5d8f212e4e051307ad6b6a53d3463b53` (verified via `git rev-parse HEAD`)
- **Method:** verified from source + executed tests + runtime artifacts only; author summaries ignored. Each fix was mentally reverted to confirm a test would catch it.

### Runtime evidence executed
- `python3 -m pytest tests/test_mas_*.py -q` → **37 passed**.
- `cd worktrees/tau2-clean && uv run python -m pytest .../test_tau2_team_integration.py -q` → **4 passed**.
- `python3 scripts/mas_acceptance.py` → manifest `overall_status="PASS_ARCHITECTURE_PENDING_REVIEW"`, with new core flags `runtime_value_conflict_detected=true`, `dynamic_delegation_live_trace=true`, `arb_selective_requery_observed=true`, `architecture_mutation_tests_passed=true`. `commit_sha` matches the reviewed commit. `benchmark_integrity="NOT_VERIFIED"` (expected — real-model tau2 pilot is gated; not a failure per Round-2 instructions).

### Issue 1 — tau2 wrapper untested + missing integration test → **RESOLVED**
- `tests/test_tau2_team_integration.py` now exists and runs under the tau2 uv env (4 passing). It exercises the three write-isolation guarantees:
  - `test_worker_toollist_excludes_real_write_tools` (lines 41-46): worker `_read_tools` excludes `cancel_reservation`/`book_reservation`, includes the read tool.
  - `test_rejected_candidate_emits_no_real_write` (49-66): ledger status=`cancelled`, worker claims `confirmed` → CommitService verdict=reconcile → `out.tool_calls` empty → **no real write reaches tau2**.
  - `test_accepted_candidate_emits_real_write` (69-83): ledger status=`confirmed`, no conflict → commit → emits exactly one real `cancel_reservation` ToolCall.
- `team_agent.py:_verify_candidate` (lines 238-273): the `CandidateWriteMsg` is built from the **worker's declared** `claimed_preconditions`/`expected_versions` (`args.get(...)`, lines 251-256), NOT from current ledger latest. The real write ToolCall is emitted only when `decision.allowed and action in self._write_tool_names` (line 262).
- **Adversarial revert:** if line 254/255 were changed to override the claim with current latest (`self._ledger.latest_field(...)`), the conflict in `test_rejected_candidate_emits_no_real_write` would disappear → commit → a real `cancel_reservation` ToolCall would be emitted → the assertion `len(out.tool_calls)==0` **fails**. The test is load-bearing, not vacuous.

### Issue 2 — two vacuous mutation tests → **RESOLVED**
- `test_mutation_disabling_version_check_admits_stale_write` (test_mas_mutations.py:90-112) and `test_mutation_disabling_conflict_check_admits_value_conflict` (115-138) now toggle the **real production guards** `CommitService.enforce_version_check` / `enforce_conflict_check` (defined commit_service.py:73-74, 83-84; gating lines 119, 124, 136) and call the **real** `svc.submit()` (real `verify()` + `execute_write()` with `env.cancel` executor from `make_service`, commit_proof.py:52-57). Each test asserts the baseline (guard ON → not committed, `env.cancelled is False`) AND the mutation (guard OFF → committed, `env.cancelled is True`). They depend on the real code path; deleting the guard would make the baseline branch fail.
- The previously raw-`env.cancel` tautology test has been replaced by `test_mutation_bypassing_commit_token_is_refused_by_real_guard` (141-156), which calls the real `svc.execute_write` with both `None` and a forged token, expects `WriteIsolationError`, and asserts `env.cancelled is False`. This exercises the real token guard (commit_service.py:193-197).
- **Adversarial revert:** removing line 119's check → stale write commits even with guard ON → the baseline `assert dec_on.verdict != "commit"` fails. Removing the value-conflict block (132-149) → conflict baseline fails. Removing the token check (193) → `pytest.raises(WriteIsolationError)` fails. All three catch the revert.

### Issue 3 — ARB not in the live loop → **RESOLVED**
- `team.py:run_turn` now calls `self._route_to_commit_service(c)` for every candidate write (line 217) — ARB/commit is in the live loop, not a separate script.
- `_route_to_commit_service` (231-277): runs `commit_service.verify(cw)`; on `allowed` executes the write **only** via `commit_service.execute_write(cw, decision.token)` (line 258); on reconcile/replan publishes the typed message AND calls `self.reconciliation_budget.reconcile(cw, decision)` (line 267), recording every ARB stage. It is no longer log-only.
- `ReconciliationBudget.reconcile` (reconciliation.py:74-112) performs real selective requery at stage 4 (calls `requery_fn` on offending objects, line 83-87) and re-verifies against the real CommitService each stage; commits via `execute_write` when the refreshed candidate passes (line 106).
- Minor (non-blocking): the *delegation-trace* live proof (`run_delegation_trace_proof`) has the worker return plain text, so that particular live trace does not itself drive a candidate through ARB; the commit+ARB path is exercised by `run_one_task_proof`/`run_conflict_task_proof` and by `_route_to_commit_service` being wired into `run_turn`. The live wiring is present and reachable; recommend (not required) one live-loop test that pushes a candidate write through `run_turn` into the ARB ladder to close the coverage gap end-to-end.

### Issue 4 — value-conflict detection dead → **RESOLVED**
- `commit_service.py:verify` lines 132-149: for each `claimed_precondition`, compares the worker's claimed value against `ledger.latest_field(oid, fld)` (real latest), and appends to `conflict` when `latest_val != claimed` (equals op). Gated by the real `enforce_conflict_check` flag.
- Executed proof: `run_conflict_task_proof` ingests status=`confirmed`(v1) then `cancelled`(v2), worker proposes cancel with `claimed value="confirmed"`. `artifacts/mas_proof/conflict_trace_readable.md` shows `verdict=reconcile reasons=['stale_read_set', 'unresolved_conflict']` then the ARB ladder running to a safe `abstain` — a genuine cross-agent value conflict (confirmed→cancelled), not a `CONFLICT::` string or +1 hack. Acceptance flag `runtime_value_conflict_detected=true` is derived from this executed run (`mas_acceptance.py:95-97`).

### New regressions / new vacuous tests
- None found. Collected 37 mas tests + 4 tau2 tests; each maps to a contract requirement and is non-vacuous. The acceptance manifest is generated from executed proofs (`scripts/mas_acceptance.py`), not hand-written; `commit_sha` is read from git. No modification to tau2 task/policy/evaluator was observed in the wrapper path.
- Carried-over minor (still open, non-blocking): `team_agent.py:114` builds `self._inner = LLMAgent(tools=tools, ...)` with the full write-capable tool list; it is used only for `get_init_state` (line 121) and never generates, so no leak — but remains a foot-gun. `DOMAIN_WRITE_TOOLS` banking-domain coverage should be confirmed before any banking run (the wrapper now **fails closed** — raises if a domain has no registry, team_agent.py:84-90 — which removes the earlier leak risk for unknown domains).

### §18 completion checklist (honest status)
- [x] ≥3 independent LLM agents in one trace · [x] independent state · [x] distinct system prompts · [x] independent tool allowlist · [x] real typed A2A messages · [x] dynamic delegation (live `run_turn`) · [x] worker cannot call real write tools · [x] CommitService sole write path · [x] agent-specific views proven in trace · [x] stale/conflict caught by CommitService (incl. value-level) · [x] ARB triggers real selective requery/replan (now in live loop) · [x] architecture mutation tests all valid · [x] **Code Reviewer APPROVED (this Round 2)** · [ ] Scientific Auditor APPROVED (separate deliverable, NOT this review) · [x] one-task runtime proof complete · [~] benchmark semantics unchanged: unmodified by inspection; `benchmark_integrity=NOT_VERIFIED` because the gated real-model tau2 pilot has not run (expected and acceptable per Contract §16).

### Final Verdict

**APPROVED**

All 4 Round-1 issues are genuinely fixed and the fixes are guarded by non-vacuous tests that fail on reversion. The remaining open items (Scientific Auditor sign-off, real-model tau2 pilot / `benchmark_integrity`) are out of scope for this architecture review and are correctly gated, not faked. The acceptance manifest asserts no false completion (`PASS_ARCHITECTURE_PENDING_REVIEW`, `code_review="NOT_RUN"` until this review is recorded).
