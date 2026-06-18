"""RAVELTeam — orchestration runtime for the multi-agent system.

Phase 1 scope (Contract §9): dynamic delegation loop across Supervisor /
PolicyAgent / ToolWorker, typed messages on the bus, per-agent independent
state, and a full runtime trace. Ledger / ViewBuilder / CommitService are
injected (optional in Phase 1, required from Phase 2/3).

The Supervisor's structured output selects the next agent. The team only
enforces *legal* transitions; it never hardcodes the target (Contract §2.4).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from .agents import (
    PolicyAgent,
    SemanticVerifierAgent,
    SupervisorAgent,
    ToolWorkerAgent,
)
from .messages import MessageBus
from .model_client import ModelResponse
from .trace import LLMCallRecord, RuntimeTrace


@dataclass
class TeamConfig:
    trial_id: str = "trial-0"
    task_id: str = "task-0"
    max_turns: int = 12
    regime: str = "FullSync"


class RAVELTeam:
    """Holds the agents and services; runs the delegation loop."""

    def __init__(
        self,
        *,
        supervisor: SupervisorAgent,
        policy_agent: PolicyAgent,
        tool_worker: ToolWorkerAgent,
        config: TeamConfig,
        semantic_verifier: Optional[SemanticVerifierAgent] = None,
        ledger: Any = None,
        view_builder: Any = None,
        commit_service: Any = None,
        bus: Optional[MessageBus] = None,
        trace: Optional[RuntimeTrace] = None,
    ) -> None:
        self.supervisor = supervisor
        self.policy_agent = policy_agent
        self.tool_worker = tool_worker
        self.semantic_verifier = semantic_verifier
        self.config = config
        self.ledger = ledger
        self.view_builder = view_builder
        self.commit_service = commit_service
        self.bus = bus or MessageBus()
        self.trace = trace or RuntimeTrace(config.trial_id, config.task_id)

        # State-isolation invariant check (Contract §2.2) — fail fast.
        assert self.supervisor.state is not self.policy_agent.state
        assert self.supervisor.state is not self.tool_worker.state
        assert self.policy_agent.state is not self.tool_worker.state

    # ------------------------------------------------------------------
    # Trace helper
    # ------------------------------------------------------------------

    def _record_call(self, agent, output_kind: str, reason_code: str = "",
                     visible_ev: list[str] | None = None,
                     visible_ver: dict[str, int] | None = None) -> None:
        resp: ModelResponse = agent.last_response
        self.trace.record_llm_call(LLMCallRecord(
            logical_step=self.trace.step(),
            agent_id=agent.agent_id,
            agent_role=agent.role,
            model_name=agent.model_name,
            system_prompt_hash=agent.prompt_hash,
            context_hash=agent.context_hash(),
            visible_evidence_ids=visible_ev or [],
            visible_object_versions=visible_ver or {},
            input_tokens=resp.input_tokens if resp else 0,
            output_tokens=resp.output_tokens if resp else 0,
            output_kind=output_kind,
            reason_code=reason_code,
        ))

    def _publish(self, source: str, target: str, mtype: str,
                 payload: dict, evidence_ids: tuple[str, ...] = (),
                 parent: str | None = None) -> str:
        msg = self.bus.publish(
            source_agent_id=source, target_agent_id=target,
            message_type=mtype, payload=payload,
            evidence_ids=evidence_ids, parent_message_id=parent,
        )
        self.trace.record_event("message", msg.to_dict())
        return msg.message_id

    # ------------------------------------------------------------------
    # Views (Phase 2 wires real ViewBuilder; Phase 1 uses simple summaries)
    # ------------------------------------------------------------------

    def _ledger_headers(self) -> str:
        if self.view_builder is not None:
            return self.view_builder.headers_for("supervisor")
        if self.ledger is not None:
            from .views import simple_ledger_headers
            return simple_ledger_headers(self.ledger)
        return "(no ledger)"

    def _policy_fields(self, required_objects: list[str]) -> str:
        if self.view_builder is not None:
            return self.view_builder.fields_for("policy_agent", required_objects)
        return "(no policy view)"

    def _worker_view(self, required_objects: list[str]) -> str:
        if self.view_builder is not None:
            return self.view_builder.fields_for("tool_worker", required_objects)
        return "(no worker view)"

    # ------------------------------------------------------------------
    # Main delegation loop
    # ------------------------------------------------------------------

    def run_turn(self, *, user_goal: str, task_state: str = "",
                 worker_tools: list[dict] | None = None) -> dict[str, Any]:
        """Run one user-turn: Supervisor drives dynamic delegation until it
        emits a terminal action (Finish/AskUser/Abstain) or max_turns hit.

        Returns a dict describing the terminal decision + any candidate writes.
        """
        # team → supervisor assignment
        self._publish("team", "supervisor", "TaskAssignment",
                      {"user_goal": user_goal, "task_id": self.config.task_id})

        last_result = "(none)"
        candidate_writes: list[dict] = []
        policy_decision: dict | None = None

        for _ in range(self.config.max_turns):
            decision = self.supervisor.decide(
                user_goal=user_goal, task_state=task_state,
                ledger_headers=self._ledger_headers(), last_result=last_result,
            )
            self._record_call(self.supervisor, "json",
                              reason_code=decision.get("reason_code", ""))

            action = decision.get("action", "AskUser")
            target = decision.get("target_agent")
            subgoal = decision.get("subgoal", "")
            req_objs = decision.get("required_objects", []) or []

            if action in ("Finish", "AskUser", "Abstain"):
                self.trace.record_event("delegation", {
                    "target_agent": "terminal", "action": action, "subgoal": subgoal,
                })
                return {
                    "action": action, "subgoal": subgoal,
                    "candidate_writes": candidate_writes,
                    "policy_decision": policy_decision,
                }

            if action == "RequestReconciliation":
                # ARB wiring is Phase 4; record the request for now.
                self._publish("supervisor", "commit_service", "ReconciliationRequest",
                              {"subgoal": subgoal})
                last_result = "reconciliation_requested"
                continue

            # action == Delegate
            self.trace.record_event("delegation", {
                "target_agent": target, "subgoal": subgoal,
                "reason_code": decision.get("reason_code", ""),
            })

            if target == "policy_agent":
                parent = self._publish("supervisor", "policy_agent", "PolicyRequest",
                                       {"action": subgoal, "subgoal": subgoal,
                                        "target_objects": req_objs})
                pd = self.policy_agent.decide(
                    action=subgoal, subgoal=subgoal,
                    policy_fields=self._policy_fields(req_objs),
                )
                self._record_call(self.policy_agent, "json")
                policy_decision = pd
                self._publish("policy_agent", "supervisor", "PolicyDecision",
                              pd, parent=parent)
                last_result = f"policy_status={pd.get('policy_status')}"

            elif target == "tool_worker":
                parent = self._publish("supervisor", "tool_worker", "EvidenceRequest",
                                       {"subgoal": subgoal,
                                        "required_evidence_schema":
                                            (policy_decision or {}).get("required_evidence", [])})
                resp = self.tool_worker.act(
                    subgoal=subgoal, worker_view=self._worker_view(req_objs),
                    tools=worker_tools or [],
                )
                kind = "tool_call" if resp.is_tool_call() else "text"
                self._record_call(self.tool_worker, kind)

                # Candidate writes are proposals only; CommitService handles them (Phase 3)
                cw = self._extract_candidate_writes(resp)
                if cw:
                    for c in cw:
                        self._publish("tool_worker", "commit_service", "CandidateWrite", c,
                                      parent=parent)
                        candidate_writes.append(c)
                        self._route_to_commit_service(c)
                    last_result = f"proposed {len(cw)} candidate write(s)"
                else:
                    self._publish("tool_worker", "supervisor", "EvidenceResult",
                                  {"summary": resp.content[:200]}, parent=parent)
                    last_result = "evidence_gathered"
            else:
                last_result = f"illegal_target:{target}"

        return {
            "action": "MaxTurns", "candidate_writes": candidate_writes,
            "policy_decision": policy_decision,
        }

    def _route_to_commit_service(self, candidate: dict) -> None:
        """Submit a candidate write to the deterministic CommitService (if wired).

        The team itself NEVER executes writes; only CommitService can. The result
        (commit/reconcile/replan) is recorded in the trace.
        """
        if self.commit_service is None:
            return
        from .commit_service import CandidateWriteMsg
        cw = CandidateWriteMsg(
            action=candidate.get("action", ""),
            arguments=candidate.get("arguments", {}) or {},
            target_objects=tuple(candidate.get("target_objects", []) or ()),
            referenced_evidence_ids=tuple(candidate.get("referenced_evidence_ids", []) or ()),
            expected_versions=candidate.get("expected_versions", {}) or {},
        )
        decision, result = self.commit_service.submit(cw)
        self.trace.record_event("commit", {
            "action": cw.action,
            "verdict": decision.verdict,
            "reasons": list(decision.reasons),
            "stale": list(decision.stale),
            "conflict": list(decision.conflict),
            "committed": decision.allowed,
        })
        if decision.verdict in ("reconcile", "replan"):
            self._publish("commit_service", "supervisor",
                          "ReconciliationRequest" if decision.verdict == "reconcile"
                          else "ReplanRequest",
                          {"action": cw.action, "reasons": list(decision.reasons)})

    @staticmethod
    def _extract_candidate_writes(resp: ModelResponse) -> list[dict]:
        """Pull propose_candidate_write tool calls out of a worker response."""
        out = []
        for tc in resp.tool_calls:
            if tc.get("name") == "propose_candidate_write":
                args = tc.get("arguments")
                if isinstance(args, str):
                    from .model_client import parse_json_response
                    args = parse_json_response(args, default={})
                out.append(args or {})
        return out
