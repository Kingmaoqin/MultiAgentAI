# 05 — Message Schemas

All inter-agent flow is a typed `Message` on the `MessageBus`. Envelope is common; `payload` is type-specific.

## Envelope (every message)

```json
{
  "message_id": "m-000123",
  "logical_time": 17,
  "source_agent_id": "supervisor",
  "target_agent_id": "policy_agent",
  "message_type": "PolicyRequest",
  "parent_message_id": "m-000119",
  "evidence_ids": ["ev-000004-..."],
  "payload": { }
}
```

## Message types (Contract §2.3)

| Type | source → target | payload |
|---|---|---|
| `TaskAssignment` | team → supervisor | `{user_goal, task_id}` |
| `Delegate` | supervisor → policy_agent / tool_worker | `{target_agent, subgoal, required_objects, evidence_refs, reason_code}` |
| `PolicyRequest` | supervisor → policy_agent | `{action, subgoal, target_objects}` |
| `PolicyDecision` | policy_agent → supervisor | `{action, policy_status, required_evidence[], required_user_confirmations[], policy_checks[], ambiguities[]}` |
| `EvidenceRequest` | supervisor → tool_worker | `{subgoal, required_evidence_schema}` |
| `EvidenceResult` | tool_worker → supervisor | `{gathered_evidence_ids[], missing_fields[], notes}` |
| `CandidateWrite` | tool_worker → commit_service | `{action, arguments, target_objects[], referenced_evidence_ids[], claimed_preconditions[], expected_versions{}}` |
| `ReconciliationRequest` | commit_service → supervisor | `{stage, missing_or_stale[], conflict[]}` |
| `ReplanRequest` | commit_service → supervisor | `{reason, blocking_objects[]}` |
| `AgentResult` | any agent → supervisor | `{status, summary, evidence_ids[]}` |

## Structured agent outputs

**Supervisor delegation** (drives §2.4 dynamic delegation):
```json
{"action":"Delegate","target_agent":"policy_agent","subgoal":"...","required_objects":["reservation:R123"],"evidence_refs":["ev-..."],"reason_code":"policy_check_required"}
```
allowed `action`: `Delegate | RequestReconciliation | AskUser | Finish | Abstain`.

**PolicyDecision required_evidence item:**
```json
{"object_selector":"reservation:{reservation_id}","field":"status","freshness":"latest"}
```

**CandidateWrite** (Contract §4.3): as in the table above, with `claimed_preconditions` and `expected_versions`.

## Logging
Every message is appended to `RuntimeTrace` as an event; `MessageBus` never mutates the Ledger.
Function calls returning Python objects WITHOUT a corresponding bus event do not count as A2A communication (Contract §2.3).
