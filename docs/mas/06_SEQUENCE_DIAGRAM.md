# 06 — Sequence Diagram (one turn, write path)

```
User Simulator        Supervisor        PolicyAgent      ToolWorker     CommitService(det.)    Ledger
     │  user msg ──────►│                                                                          │
     │            (LLM_CALL supervisor)                                                            │
     │            plan + Delegate(policy_agent) ─ PolicyRequest ─►│                                │
     │                                       (LLM_CALL policy_agent)                               │
     │                 ◄─ PolicyDecision{required_evidence} ──────│                                │
     │            Delegate(tool_worker) ─ EvidenceRequest ───────────────►│                        │
     │                                              (LLM_CALL tool_worker; read tools only)        │
     │                                              read tool ───────────────────────────────────►│ ingest vN
     │                 ◄─ EvidenceResult{evidence_ids} ─────────────────│   (Worker view = vN)     │
     │            [env changes vN→vN+1 in deterministic proof scenario] ──────────────────────────►│
     │            Delegate(tool_worker) ─ EvidenceRequest ───────────────►│                        │
     │                                              propose_candidate_write(v=N) ─ CandidateWrite ─►│
     │                                                                   actual read-set = vN+1     │
     │                                                          (DETERMINISTIC checks vs Ledger) ──►│ latest vN+1
     │                                                          stale detected → ReconciliationRequest
     │                 ◄──────────────── ReconciliationRequest(stage=1) ──────────────│            │
     │            RequestReconciliation → ARB stage ladder (fetch missing/delta/requery)           │
     │                                              selective requery ────────────────────────────►│ vN+1
     │                                              re-propose CandidateWrite(v=N+1) ─────────────►│
     │                                                          checks pass → AllowedCommitToken    │
     │                                                          REAL write tool executes ──────────►│ vN+2
     │  ◄─ assistant msg (Finish) ─────│                                                            │
```

Key points enforced:
- Each `LLM_CALL` carries a distinct `agent_id` and distinct `system prompt hash` (Gate 1).
- Worker view (vN) ≠ Ledger latest (vN+1) ⇒ CommitService blocks stale write (Gate 3).
- Only CommitService holds the real write tool; it fires only with an `AllowedCommitToken` (Contract §B.6).
- ARB escalates in order: missing field → delta → conflict inspect → selective requery → semantic verify → replan → ask/abstain (§5.3).
