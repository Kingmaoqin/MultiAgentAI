# 03 — Architecture Contract (frozen v1.0)

This is the binding architecture for `src/ravel_mas/`. Conflicts resolve to Proposal then this file (Contract §1).

## A. Components

```
tau2 User Simulator
        │
        ▼
RAVELTeamAgent  (benchmark-facing wrapper; tau2 sees ONE agent)
        │
        ▼
   RAVELTeam (orchestration runtime)
   ├── SupervisorAgent   (LLM)  agent_id="supervisor"
   ├── PolicyAgent       (LLM)  agent_id="policy_agent"
   ├── ToolWorkerAgent   (LLM)  agent_id="tool_worker"
   ├── SemanticVerifierAgent (LLM, optional, advisory) agent_id="semantic_verifier"
   │
   ├── MessageBus            (service — typed A2A messages + event log)
   ├── EvidenceLedger        (service — versioned, append-only)   [reuse ravel_core.evidence]
   ├── MSERouter / ViewBuilder (service — per-agent projections)  [reuse ravel_core.mse_router]
   ├── CommitService         (service — DETERMINISTIC, sole writer) [wraps ravel_core.commit_gate]
   ├── ReconciliationBudget  (service — ARB ladder)                [reuse ravel_core.reconciliation]
   └── RuntimeTrace          (service — per-call/message/commit log)
```

## B. Invariants (must always hold)

1. **Distinct identities.** `supervisor`, `policy_agent`, `tool_worker` are distinct `BaseAgent` instances with distinct `agent_id`, distinct `prompt_hash`, distinct `state`.
2. **No shared history.** `a.state is not b.state` for all agent pairs. Agents never read another agent's raw conversation; they exchange only typed messages + projected views.
3. **Typed messages only.** All inter-agent information flow is a `Message` on the `MessageBus`, logged with `message_id, source_agent_id, target_agent_id, message_type, payload, evidence_ids, logical_time, parent_message_id`.
4. **Dynamic delegation.** The next agent is chosen by Supervisor's structured `Delegate` output, not by hardcoded order. Team enforces only *legal* transitions; it does not pick the target.
5. **Tool allowlists.** Enforced at the team level before tools are exposed to an agent:
   - Supervisor: no business tools.
   - PolicyAgent: policy/read-meta only.
   - ToolWorker: read tools + `propose_candidate_write` (NOT real write tools).
   - CommitService: the only holder of real write tools.
6. **Single write path.** A real write tool executes **iff** CommitService returns an `AllowedCommitToken`. Any write without a valid token raises and aborts (no env change).
7. **Deterministic commit.** CommitService decision is computed by deterministic checks over the Ledger's actual read-set + the worker's declared `referenced_evidence_ids`. LLM verifier is advisory only and cannot authorize.
8. **Agent-specific views.** Supervisor sees headers/change-summaries; Policy sees policy-relevant fields; Worker sees action-required fields; CommitService sees the complete latest read-set. Regimes (FullSync/Delayed/RoleAwareFieldMask/ConflictingView) are realized as differences *between* these views.
9. **Benchmark integrity.** tau2 task objective, policy text, DB init, tool semantics, user goal, official evaluator, ground truth are unmodified.
10. **No hidden CoT.** Only structured plans, short reason codes, typed decisions, and evidence links are persisted (Contract §14).

## C. Legal state transitions (team executes; Supervisor decides target)

```
SUPERVISOR_PLAN
  → Delegate(policy_agent)      → POLICY_DECISION   → back to SUPERVISOR_PLAN
  → Delegate(tool_worker)       → WORKER_RESULT     → back to SUPERVISOR_PLAN
  → RequestReconciliation       → ARB               → back to SUPERVISOR_PLAN
  → AskUser / Finish / Abstain  → terminal for the turn
CandidateWrite (from worker) → CommitService → {commit|reconcile|replan|ask_user|abstain}
```
Supervisor may re-delegate to any agent any number of times; order is data-dependent.

## D. Acceptance (architecture_acceptance.json core fields)

`distinct_internal_llm_agents>=3`, `independent_message_states`, `distinct_system_prompt_hashes`,
`dynamic_delegation_observed`, `typed_agent_messages_observed`, `agent_specific_visibility_observed`,
`worker_real_write_permission==false`, `commit_service_only_write_path`, `stale_write_blocked`,
`conflicting_write_blocked`, `architecture_mutation_tests_passed`, plus both reviews APPROVED.
