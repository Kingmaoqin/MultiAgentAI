"""One-task runtime proof (Contract §15).

Deterministic end-to-end trajectory (FakeModelClient) exercising the full
architecture: Supervisor plans → delegates policy check → PolicyAgent returns
schema → delegates evidence collection → ToolWorker reads → Ledger stores vN →
environment changes to vN+1 → ToolWorker proposes CandidateWrite using vN →
CommitService detects stale read → ARB selective refresh → safe commit.

Emits:
  artifacts/mas_proof/runtime_trace.jsonl
  artifacts/mas_proof/runtime_trace_readable.md
  artifacts/mas_proof/agent_state_manifest.json
  artifacts/mas_proof/tool_permission_manifest.json
  artifacts/mas_proof/evidence_visibility_manifest.json
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import sys
_SRC = Path(__file__).parent.parent
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from ravel_core.evidence import EvidenceLedger
from .agents import SupervisorAgent, PolicyAgent, ToolWorkerAgent
from .builders import (
    SUPERVISOR_PROMPT, POLICY_PROMPT, WORKER_PROMPT,
    PROPOSE_CANDIDATE_WRITE_TOOL,
)
from .commit_service import CommitService, CandidateWriteMsg
from .messages import MessageBus
from .model_client import FakeModelClient, ModelResponse
from .reconciliation import ReconciliationBudget
from .trace import RuntimeTrace, LLMCallRecord
from .views import ViewBuilder

WRITE_TOOLS = {"cancel_reservation", "book_reservation"}
REQUIRED = {"cancel_reservation": ["status"]}
OBJ = "reservation:R1"


class _Env:
    def __init__(self) -> None:
        self.cancelled = False

    def cancel(self, action: str, args: dict) -> dict:
        self.cancelled = True
        return {"ok": True, "action": action}


def _ingest(ledger: EvidenceLedger, status: str) -> str:
    rec = ledger.ingest(object_id=OBJ, tool_name="get_reservation_details",
                        payload={"reservation_id": "R1", "status": status},
                        source_agent="tool_worker")
    return rec.evidence_id


def run_one_task_proof(out_dir: str = "artifacts/mas_proof") -> dict[str, Any]:
    ledger = EvidenceLedger()
    env = _Env()
    bus = MessageBus()
    trace = RuntimeTrace(trial_id="one-task-proof", task_id="cancel-R1")

    # --- agents (distinct identity/prompt/state) ---
    client = FakeModelClient(scripts={
        "supervisor": [
            ModelResponse(content='{"action":"Delegate","target_agent":"policy_agent",'
                          '"subgoal":"cancel_reservation","required_objects":["reservation:R1"],'
                          '"reason_code":"policy_check_required"}', input_tokens=120, output_tokens=40),
            ModelResponse(content='{"action":"Delegate","target_agent":"tool_worker",'
                          '"subgoal":"read reservation status","required_objects":["reservation:R1"],'
                          '"reason_code":"evidence_collection"}', input_tokens=130, output_tokens=42),
            ModelResponse(content='{"action":"Finish","target_agent":null,"subgoal":"done",'
                          '"required_objects":[],"reason_code":"goal_met"}', input_tokens=80, output_tokens=18),
        ],
        "policy_agent": [
            ModelResponse(content='{"action":"cancel_reservation","policy_status":"conditionally_allowed",'
                          '"required_evidence":[{"object_selector":"reservation:R1","field":"status",'
                          '"freshness":"latest"}],"required_user_confirmations":[],'
                          '"policy_checks":["not_already_cancelled"],"ambiguities":[]}',
                          input_tokens=110, output_tokens=55),
        ],
        "tool_worker": [
            ModelResponse(content="", tool_calls=[{
                "name": "propose_candidate_write",
                "arguments": json.dumps({
                    "action": "cancel_reservation",
                    "arguments": {"reservation_id": "R1"},
                    "target_objects": [OBJ],
                    "referenced_evidence_ids": ["__EV1__"],
                    "expected_versions": {OBJ: 1},   # worker's evidence is v1 (stale)
                })}], input_tokens=140, output_tokens=48),
        ],
    })

    supervisor = SupervisorAgent("supervisor", SUPERVISOR_PROMPT, client, "fake/model", [])
    policy = PolicyAgent("policy_agent", POLICY_PROMPT, client, "fake/model", [])
    worker = ToolWorkerAgent("tool_worker", WORKER_PROMPT, client, "fake/model",
                             ["get_reservation_details", "propose_candidate_write"])

    vb = ViewBuilder(ledger, regime="FullSync")
    svc = CommitService(ledger, write_tools=WRITE_TOOLS,
                        action_required_fields=REQUIRED,
                        real_write_executor=env.cancel)

    def requery(object_id: str) -> None:
        # selective requery: re-read latest true status from env (now 'confirmed' still,
        # but version advances so the worker's stale v1 claim is refreshed to latest)
        _ingest(ledger, "confirmed")
        trace.record_event("tool", {"tool_name": "get_reservation_details",
                                    "agent_id": "tool_worker", "tool_kind": "read_requery",
                                    "object_id": object_id})

    arb = ReconciliationBudget(svc, requery_fn=requery, max_stage=7)

    def rec_call(agent, kind, reason=""):
        r = agent.last_response
        trace.record_llm_call(LLMCallRecord(
            logical_step=trace.step(), agent_id=agent.agent_id, agent_role=agent.role,
            model_name=agent.model_name, system_prompt_hash=agent.prompt_hash,
            context_hash=agent.context_hash(),
            visible_evidence_ids=[r2.evidence_id for r2 in ledger.records],
            visible_object_versions={OBJ: ledger.object_version(OBJ)},
            input_tokens=r.input_tokens if r else 0, output_tokens=r.output_tokens if r else 0,
            output_kind=kind, reason_code=reason))

    def publish(src, tgt, mtype, payload, parent=None):
        m = bus.publish(source_agent_id=src, target_agent_id=tgt, message_type=mtype,
                        payload=payload, parent_message_id=parent)
        trace.record_event("message", m.to_dict())
        return m.message_id

    # === trajectory ===
    publish("team", "supervisor", "TaskAssignment", {"user_goal": "Cancel reservation R1"})

    # 1. Supervisor plans → delegate policy
    d1 = supervisor.decide(user_goal="Cancel reservation R1", task_state="",
                           ledger_headers=vb.headers_for("supervisor"), last_result="(none)")
    rec_call(supervisor, "json", d1.get("reason_code", ""))
    trace.record_event("delegation", {"target_agent": d1["target_agent"], "subgoal": d1["subgoal"]})
    p1 = publish("supervisor", "policy_agent", "PolicyRequest", {"action": d1["subgoal"]})

    # 2. PolicyAgent returns required evidence schema
    pd = policy.decide(action="cancel_reservation", subgoal="cancel",
                       policy_fields=vb.fields_for("policy_agent", [OBJ]))
    rec_call(policy, "json")
    publish("policy_agent", "supervisor", "PolicyDecision", pd, parent=p1)

    # 3. ToolWorker reads → Ledger stores v1 (confirmed)
    ev1 = _ingest(ledger, "confirmed")
    trace.record_event("tool", {"tool_name": "get_reservation_details",
                                "agent_id": "tool_worker", "tool_kind": "read",
                                "object_id": OBJ})

    # 4. Supervisor delegates evidence collection → worker
    d2 = supervisor.decide(user_goal="Cancel reservation R1", task_state="policy_known",
                           ledger_headers=vb.headers_for("supervisor"),
                           last_result=f"policy_status={pd['policy_status']}")
    rec_call(supervisor, "json", d2.get("reason_code", ""))
    trace.record_event("delegation", {"target_agent": d2["target_agent"], "subgoal": d2["subgoal"]})
    p2 = publish("supervisor", "tool_worker", "EvidenceRequest",
                 {"subgoal": d2["subgoal"], "required_evidence_schema": pd["required_evidence"]})

    # 5. environment changes to v2 (deterministic external update) BEFORE worker proposes
    _ingest(ledger, "confirmed")  # v2 — version advances; worker still holds v1
    trace.record_event("env", {"note": f"{OBJ} advanced to v{ledger.object_version(OBJ)} (worker holds v1)"})

    # 6. ToolWorker proposes CandidateWrite using stale v1
    wresp = worker.act(subgoal=d2["subgoal"], worker_view=vb.fields_for("tool_worker", [OBJ]),
                       tools=[PROPOSE_CANDIDATE_WRITE_TOOL])
    rec_call(worker, "tool_call" if wresp.is_tool_call() else "text")
    raw = wresp.tool_calls[0]["arguments"]
    cwd = json.loads(raw) if isinstance(raw, str) else raw
    cwd["referenced_evidence_ids"] = [ev1]
    cw = CandidateWriteMsg(action=cwd["action"], arguments=cwd["arguments"],
                           target_objects=tuple(cwd["target_objects"]),
                           referenced_evidence_ids=tuple(cwd["referenced_evidence_ids"]),
                           expected_versions=cwd["expected_versions"])
    publish("tool_worker", "commit_service", "CandidateWrite", cwd, parent=p2)

    # 7. CommitService detects stale read
    dec = svc.verify(cw)
    trace.record_event("commit", {"action": cw.action, "verdict": dec.verdict,
                                  "reasons": list(dec.reasons), "stale": list(dec.stale),
                                  "committed": dec.allowed})
    assert dec.verdict == "reconcile", f"expected stale→reconcile, got {dec.verdict}"
    publish("commit_service", "supervisor", "ReconciliationRequest",
            {"action": cw.action, "reasons": list(dec.reasons)})

    # 8. ARB selective refresh → safe commit
    rr = arb.reconcile(cw, dec)
    for step in rr.steps:
        trace.record_event("commit", {"action": cw.action, "verdict": step.verdict_after,
                                      "arb_stage": step.stage, "stage_name": step.stage_name,
                                      "trigger": step.trigger})
    trace.record_event("commit", {"action": cw.action, "verdict": rr.final_verdict,
                                  "final": True, "committed": rr.final_verdict == "commit",
                                  "env_cancelled": env.cancelled})

    # 9. Supervisor finishes
    d3 = supervisor.decide(user_goal="Cancel reservation R1", task_state="committed",
                           ledger_headers=vb.headers_for("supervisor"),
                           last_result=f"commit={rr.final_verdict}")
    rec_call(supervisor, "json", d3.get("reason_code", ""))

    # === write artifacts ===
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "runtime_trace.jsonl").write_text(trace.to_jsonl())
    (out / "runtime_trace_readable.md").write_text(trace.to_readable())

    agent_state_manifest = {
        a.agent_id: {
            "agent_id": a.agent_id, "role": a.role, "prompt_hash": a.prompt_hash,
            "n_calls": a.state.n_calls, "input_tokens": a.state.input_tokens,
            "output_tokens": a.state.output_tokens,
            "state_object_id": id(a.state),
        } for a in (supervisor, policy, worker)
    }
    (out / "agent_state_manifest.json").write_text(json.dumps(agent_state_manifest, indent=2))

    tool_perm_manifest = {
        "supervisor": supervisor.allowed_tools,
        "policy_agent": policy.allowed_tools,
        "tool_worker": worker.allowed_tools,
        "commit_service_real_write_tools": sorted(svc.tools),
        "worker_holds_real_write": bool(set(worker.allowed_tools) & WRITE_TOOLS),
    }
    (out / "tool_permission_manifest.json").write_text(json.dumps(tool_perm_manifest, indent=2))

    # evidence_visibility_manifest built from a VALUE-FLIPPING ledger so the
    # executed artifact shows a genuine cross-agent value conflict (not just a
    # version-number difference): worker sees status=confirmed@v4, commit sees
    # status=cancelled@v5.
    conflict_ledger = EvidenceLedger()
    for status in ["confirmed", "confirmed", "confirmed", "confirmed", "cancelled"]:
        conflict_ledger.ingest(object_id=OBJ, tool_name="get_reservation_details",
                               payload={"reservation_id": "R1", "status": status},
                               source_agent="tool_worker")
    vis = ViewBuilder(conflict_ledger, regime="ConflictingView", conflict_objects={OBJ})
    evis_manifest = {
        "_note": "ConflictingView over value-flipping ledger; worker(v4)=confirmed vs commit(v5)=cancelled",
        **{aid: (vis.view_for(aid, OBJ).to_dict() if vis.view_for(aid, OBJ) else None)
           for aid in ["tool_worker", "supervisor", "policy_agent", "commit_service"]},
    }
    (out / "evidence_visibility_manifest.json").write_text(json.dumps(evis_manifest, indent=2))

    return {
        "final_verdict": rr.final_verdict,
        "committed": rr.final_verdict == "commit",
        "env_cancelled": env.cancelled,
        "arb_max_stage": rr.max_stage,
        "distinct_agents": len({c.agent_id for c in trace.llm_calls}),
        "stale_detected": True,
        "n_messages": len(bus.log),
        "artifacts_dir": str(out),
    }


def run_conflict_task_proof(out_dir: str = "artifacts/mas_proof") -> dict[str, Any]:
    """Executed proof where a real VALUE conflict (confirmed→cancelled) is detected
    by CommitService via claimed_preconditions and the system SAFELY ABSTAINS.

    Exercises the conflict branch + ARB stage-3 at runtime (not just version numbers).
    """
    ledger = EvidenceLedger()
    env = _Env()
    trace = RuntimeTrace(trial_id="conflict-proof", task_id="cancel-R1-conflict")

    svc = CommitService(ledger, write_tools=WRITE_TOOLS,
                        action_required_fields=REQUIRED, real_write_executor=env.cancel)

    # worker reads status=confirmed (v1)
    _ingest(ledger, "confirmed")
    # environment flips the value: status=cancelled (v2) — real value change
    _ingest(ledger, "cancelled")
    trace.record_event("env", {"note": f"{OBJ} value flipped confirmed→cancelled at v2"})

    # worker proposes cancel relying on its stale belief status=confirmed
    cw = CandidateWriteMsg(
        action="cancel_reservation", arguments={"reservation_id": "R1"},
        target_objects=(OBJ,),
        referenced_evidence_ids=(ledger.records[0].evidence_id,),
        claimed_preconditions=({"object_id": OBJ, "field": "status",
                                "operator": "equals", "value": "confirmed"},),
        expected_versions={OBJ: 1},
    )
    dec = svc.verify(cw)
    trace.record_event("commit", {"action": cw.action, "verdict": dec.verdict,
                                  "reasons": list(dec.reasons), "conflict": list(dec.conflict)})

    # No requery can make 'cancel a cancelled reservation' valid → ARB exhausts → abstain.
    arb = ReconciliationBudget(svc, requery_fn=lambda o: None, max_stage=7)
    rr = arb.reconcile(cw, dec)
    for step in rr.steps:
        trace.record_event("commit", {"action": cw.action, "verdict": step.verdict_after,
                                      "arb_stage": step.stage, "stage_name": step.stage_name,
                                      "trigger": step.trigger})
    trace.record_event("commit", {"action": cw.action, "verdict": rr.final_verdict,
                                  "final": True, "committed": rr.final_verdict == "commit",
                                  "env_cancelled": env.cancelled})

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "conflict_trace_readable.md").write_text(trace.to_readable())

    return {
        "verdict_initial": dec.verdict,
        "conflict_detected": bool(dec.conflict),
        "conflict_reasons": list(dec.conflict),
        "final_verdict": rr.final_verdict,
        "committed": rr.final_verdict == "commit",
        "env_cancelled": env.cancelled,
        "arb_inspected_conflict_stage": any(s.stage == 3 for s in rr.steps),
    }


def run_delegation_trace_proof(out_dir: str = "artifacts/mas_proof") -> dict[str, Any]:
    """Generate a trace via the LIVE team.run_turn dynamic-delegation loop (not a
    hardcoded sequence), evidencing Contract §2.4 at runtime."""
    from .builders import create_team, PROPOSE_CANDIDATE_WRITE_TOOL
    from .team import TeamConfig
    from .model_client import FakeModelClient, ModelResponse

    def sup(idx, msgs):
        seq = [
            ModelResponse(content='{"action":"Delegate","target_agent":"policy_agent",'
                          '"subgoal":"check cancel policy","required_objects":["reservation:R1"],'
                          '"reason_code":"policy_check_required"}'),
            ModelResponse(content='{"action":"Delegate","target_agent":"tool_worker",'
                          '"subgoal":"read status","required_objects":["reservation:R1"],'
                          '"reason_code":"evidence_collection"}'),
            ModelResponse(content='{"action":"Finish","target_agent":null,"subgoal":"done",'
                          '"required_objects":[],"reason_code":"goal_met"}'),
        ]
        return seq[min(idx, len(seq) - 1)]

    client = FakeModelClient(scripts={
        "supervisor": sup,
        "policy_agent": lambda i, m: ModelResponse(content='{"action":"cancel_reservation",'
            '"policy_status":"conditionally_allowed","required_evidence":[],'
            '"required_user_confirmations":[],"policy_checks":[],"ambiguities":[]}'),
        "tool_worker": lambda i, m: ModelResponse(content="status read complete"),
    })
    team = create_team(model_client=client, model_name="fake/model",
                       read_tools=["get_reservation_details"], write_tools=list(WRITE_TOOLS),
                       config=TeamConfig(trial_id="delegation-trace", task_id="deleg",
                                         max_turns=6), with_verifier=False)
    team.run_turn(user_goal="Cancel reservation R1", worker_tools=[PROPOSE_CANDIDATE_WRITE_TOOL])

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "delegation_trace_readable.md").write_text(team.trace.to_readable())
    deleg = [e for e in team.trace.events if e.kind == "delegation"]
    return {
        "delegation_events": len(deleg),
        "targets": [e.data.get("target_agent") for e in deleg],
        "distinct_agents": len(team.trace.internal_agent_ids),
        "generated_by": "team.run_turn (live dynamic delegation)",
    }


if __name__ == "__main__":
    print(json.dumps({
        "one_task": run_one_task_proof(),
        "conflict": run_conflict_task_proof(),
        "delegation": run_delegation_trace_proof(),
    }, indent=2))
