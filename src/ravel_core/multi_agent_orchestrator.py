"""True 4-role multi-agent RAVEL orchestrator.

Implements the orchestrator-supervisor topology from the Proposal §5.1:

    tau2 user simulator
            ↕
    MultiAgentOrchestrator  (tau2 sees this as one "agent")
    ├── Supervisor LLM      → plan JSON            (1 LLM call/turn)
    ├── Policy Agent LLM    → evidence schema JSON  (1 LLM call/turn)
    ├── Tool Worker LLM     → tool calls / text     (1 LLM call/turn)
    └── Commit Verifier LLM → commit verdict JSON   (1 LLM call if write proposed)
            ↓
    tau2 tools / environment

All four roles use the same base model (same endpoint, different system prompts).
Only the Commit Verifier can authorize write tool execution.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any

from .agent_prompts import (
    COMMIT_VERIFIER_SYSTEM_PROMPT,
    DOMAIN_POLICY_HINTS,
    POLICY_AGENT_SYSTEM_PROMPT,
    SUPERVISOR_SYSTEM_PROMPT,
    TOOL_WORKER_SYSTEM_PROMPT,
)
from .commit_gate import (
    ActionSchema,
    CandidateWrite,
    CommitGate,
    RequiredEvidence,
    VisibleEvidenceState,
)
from .evidence import EvidenceLedger
from .metrics import SafetyMetricsAccumulator
from .reconciliation import AdaptiveReconciliationBudget
from .ravel_agent import (
    DOMAIN_WRITE_TOOLS,
    RAVELEvent,
    RAVELTrialSummary,
    _extract_object_id,
    _mask_fields,
    _parse_payload,
    _reconstruct_tool_message,
)
from .visibility import EvidenceView, VisibilityPolicy

try:
    from tau2.agent.base_agent import HalfDuplexAgent, ValidAgentInputMessage
    from tau2.agent.llm_agent import LLMAgent, LLMAgentState
    from tau2.data_model.message import (
        AssistantMessage,
        MultiToolMessage,
        SystemMessage,
        ToolCall,
        ToolMessage,
        UserMessage,
    )
    from tau2.environment.tool import Tool
    from tau2.utils.llm_utils import generate
    _TAU2_AVAILABLE = True
except ImportError:
    _TAU2_AVAILABLE = False
    HalfDuplexAgent = object


# ---------------------------------------------------------------------------
# JSON parsing helper
# ---------------------------------------------------------------------------

def _parse_json_safe(text: str, default: dict) -> dict:
    """Extract and parse a JSON object from LLM text output."""
    if not text:
        return default
    # Try direct parse first
    try:
        return json.loads(text.strip())
    except (json.JSONDecodeError, ValueError):
        pass
    # Extract JSON block from markdown or surrounding text
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        try:
            return json.loads(m.group(0))
        except (json.JSONDecodeError, ValueError):
            pass
    return default


def _summarize_ledger(ledger: EvidenceLedger, max_entries: int = 10) -> str:
    """Produce a compact ledger summary for injection into agent context."""
    records = list(ledger.records)[-max_entries:]
    if not records:
        return "(no evidence gathered yet)"
    lines = []
    for r in records:
        fv = r.field_values if isinstance(r.field_values, dict) else {}
        fields_preview = ", ".join(list(fv.keys())[:5]) if fv else ", ".join(list(r.changed_fields)[:5])
        lines.append(
            f"  [{r.evidence_id[:8]}] {r.object_id} v{r.version} "
            f"via {r.tool_name}: [{fields_preview}]"
        )
    return "\n".join(lines)


def _build_candidate_write_summary(
    fn: str, args: dict, ev_ids: list[str]
) -> str:
    return json.dumps({
        "action": fn,
        "arguments": args,
        "referenced_evidence_ids": ev_ids,
    }, indent=2, default=str)


# ---------------------------------------------------------------------------
# MultiAgentOrchestrator
# ---------------------------------------------------------------------------

class MultiAgentOrchestrator(HalfDuplexAgent):
    """Four-role multi-agent orchestrator implementing the Proposal architecture.

    Each call to generate_next_message() makes 3-4 sequential LLM calls:
      1. Supervisor  → sub-goal + risk assessment
      2. Policy Agent → evidence schema
      3. Tool Worker  → tool call or candidate write (using read + write tools)
      4. Commit Verifier (only if Tool Worker proposed a write) → commit verdict
    """

    def __init__(
        self,
        tools: "list[Tool]",
        domain_policy: str,
        llm: str,
        llm_args: dict | None = None,
        regime: str = "FullSync",
        delay: int = 1,
        mask_fraction: float = 0.3,
        write_tools: "frozenset[str] | None" = None,
        gate_enabled: bool = True,
        arb_max_stage: int = 6,
        task_id: str = "unknown",
        domain: str = "unknown",
        seed: int = 42,
    ) -> None:
        super().__init__(tools=tools, domain_policy=domain_policy)
        self._domain = domain
        self._regime = regime
        self._delay = delay
        self._mask_fraction = mask_fraction
        self._gate_enabled = gate_enabled
        self._task_id = task_id
        self._seed = seed
        self._write_tool_names: frozenset[str] = (
            write_tools if write_tools is not None
            else DOMAIN_WRITE_TOOLS.get(domain, frozenset())
        )
        self._llm = llm
        self._llm_args = dict(llm_args or {})

        # All tools kept so Tool Worker can call read and propose writes
        self._all_tools = tools

        # RAVEL infrastructure (same as RAVELAgent)
        self._ledger = EvidenceLedger()
        self._vpol = VisibilityPolicy(
            regime=regime, delay=delay, seed=seed, mask_fields=set()
        )
        self._gate = CommitGate(schemas={}, permissive=True)  # legacy path; see ravel_agent
        self._arb = AdaptiveReconciliationBudget(
            gate=self._gate, ledger=self._ledger, max_stage=arb_max_stage
        )
        self._safety = SafetyMetricsAccumulator()

        # Per-trial state
        self._step = 0
        self._accumulated_ev_ids: list[str] = []
        self._all_ev_ids: list[str] = []
        self._all_views: list[EvidenceView] = []
        self._delayed_buffer: list[tuple[dict, str, str]] = []
        self._events: list[RAVELEvent] = []
        self._total_raw_fields = 0
        self._total_visible_fields = 0

        # Supervisor plan persists across turns (global state)
        self._supervisor_plan: dict = {
            "sub_goal": "understand user request",
            "risk_level": "low",
            "requires_write": False,
            "target_action": None,
            "required_evidence_objects": [],
            "reasoning": "Initial state",
        }
        # Policy schema from last Policy Agent call
        self._policy_schema: dict = {"required_fields": [], "policy_constraints": []}

        # Inner LLMAgent for get_init_state compatibility
        self._inner = LLMAgent(
            tools=tools,
            domain_policy=domain_policy,
            llm=llm,
            llm_args=dict(llm_args or {}),
        )

    # ------------------------------------------------------------------
    # HalfDuplexAgent interface
    # ------------------------------------------------------------------

    def get_init_state(self, message_history=None):
        return self._inner.get_init_state(message_history)

    def generate_next_message(
        self,
        message: "ValidAgentInputMessage",
        state: "LLMAgentState",
    ) -> "tuple[AssistantMessage, LLMAgentState]":
        self._step += 1

        # 1. Apply observation regime to incoming tool results
        filtered = self._apply_regime(message)
        if isinstance(filtered, MultiToolMessage):
            state.messages.extend(filtered.tool_messages)
        else:
            state.messages.append(filtered)

        all_msgs = state.system_messages + state.messages

        # 2. Supervisor: analyze conversation → update global plan
        self._supervisor_plan = self._call_supervisor(all_msgs)
        self._events.append(RAVELEvent(
            step=self._step, event_type="supervisor",
            extra={"plan": self._supervisor_plan},
        ))

        # 3. Policy Agent: determine required evidence schema
        self._policy_schema = self._call_policy_agent(self._supervisor_plan)
        self._events.append(RAVELEvent(
            step=self._step, event_type="policy_agent",
            extra={"schema": self._policy_schema},
        ))

        # 4. Tool Worker: execute with full tool access, result intercepted
        ledger_summary = _summarize_ledger(self._ledger)
        worker_msg = self._call_tool_worker(all_msgs, self._supervisor_plan, ledger_summary)

        # 5. Commit Verifier: validate if Tool Worker proposed a write
        if self._gate_enabled and worker_msg.is_tool_call():
            worker_msg = self._verifier_gate(worker_msg)

        state.messages.append(worker_msg)
        return worker_msg, state

    # ------------------------------------------------------------------
    # Role 1: Supervisor
    # ------------------------------------------------------------------

    def _call_supervisor(self, conversation: list) -> dict:
        """Supervisor LLM call: decompose task → sub-goal + delegation plan."""
        sys_prompt = SUPERVISOR_SYSTEM_PROMPT.format(domain=self._domain)
        # Build concise context: last assistant + user messages only
        context_lines = []
        for m in conversation[-12:]:
            role = getattr(m, "role", "")
            if role in ("user", "assistant"):
                content = getattr(m, "content", "") or ""
                if content:
                    context_lines.append(f"{role.upper()}: {content[:300]}")
        context = "\n".join(context_lines) or "(conversation start)"

        msgs = [
            SystemMessage(role="system", content=sys_prompt),
            UserMessage(
                role="user",
                content=(
                    f"Current conversation context:\n{context}\n\n"
                    f"Previous plan: {json.dumps(self._supervisor_plan)}\n\n"
                    "Provide an updated delegation plan as JSON."
                ),
            ),
        ]
        try:
            result = generate(
                model=self._llm,
                tools=[],
                messages=msgs,
                call_name="supervisor",
                **self._llm_args,
            )
            return _parse_json_safe(
                result.content or "",
                default=self._supervisor_plan,
            )
        except Exception:
            return self._supervisor_plan

    # ------------------------------------------------------------------
    # Role 2: Policy Agent
    # ------------------------------------------------------------------

    def _call_policy_agent(self, plan: dict) -> dict:
        """Policy Agent LLM call: sub-goal + domain → required evidence schema."""
        domain_hint = DOMAIN_POLICY_HINTS.get(self._domain, "")
        sys_prompt = POLICY_AGENT_SYSTEM_PROMPT.format(
            domain=self._domain, domain_policy_hint=domain_hint
        )
        action = plan.get("target_action") or plan.get("sub_goal", "unknown")

        msgs = [
            SystemMessage(role="system", content=sys_prompt),
            UserMessage(
                role="user",
                content=(
                    f"Planned action: {action}\n"
                    f"Sub-goal: {plan.get('sub_goal', 'unknown')}\n"
                    f"Risk level: {plan.get('risk_level', 'unknown')}\n"
                    "Provide the required evidence schema as JSON."
                ),
            ),
        ]
        try:
            result = generate(
                model=self._llm,
                tools=[],
                messages=msgs,
                call_name="policy_agent",
                **self._llm_args,
            )
            return _parse_json_safe(
                result.content or "",
                default={"required_fields": [], "policy_constraints": []},
            )
        except Exception:
            return {"required_fields": [], "policy_constraints": []}

    # ------------------------------------------------------------------
    # Role 3: Tool Worker
    # ------------------------------------------------------------------

    def _call_tool_worker(
        self,
        conversation: list,
        plan: dict,
        ledger_summary: str,
    ) -> "AssistantMessage":
        """Tool Worker LLM call: execute tools or propose candidate write."""
        worker_sys = TOOL_WORKER_SYSTEM_PROMPT.format(
            domain=self._domain,
            supervisor_plan=json.dumps(plan, indent=2),
            ledger_summary=ledger_summary,
        )
        # Replace the original system message with Tool Worker system prompt
        worker_msgs = [
            SystemMessage(role="system", content=worker_sys)
        ] + [m for m in conversation if getattr(m, "role", "") != "system"]

        result = generate(
            model=self._llm,
            tools=self._all_tools,
            messages=worker_msgs,
            call_name="tool_worker",
            **self._llm_args,
        )
        self._events.append(RAVELEvent(
            step=self._step, event_type="tool_worker",
            extra={"is_tool_call": result.is_tool_call()},
        ))
        return result

    # ------------------------------------------------------------------
    # Role 4: Commit Verifier
    # ------------------------------------------------------------------

    def _call_commit_verifier(
        self,
        fn: str,
        args: dict,
        target_objects: tuple[str, ...],
    ) -> dict:
        """Commit Verifier LLM call: independently validate proposed write."""
        candidate_summary = _build_candidate_write_summary(
            fn, args, self._accumulated_ev_ids
        )
        ledger_evidence = _summarize_ledger(self._ledger)
        sys_prompt = COMMIT_VERIFIER_SYSTEM_PROMPT.format(
            domain=self._domain,
            candidate_write=candidate_summary,
            policy_schema=json.dumps(self._policy_schema, indent=2),
            ledger_evidence=ledger_evidence,
        )
        msgs = [
            SystemMessage(role="system", content=sys_prompt),
            UserMessage(
                role="user",
                content=(
                    "Evaluate the proposed write. "
                    "Respond only with the JSON verdict object."
                ),
            ),
        ]
        try:
            result = generate(
                model=self._llm,
                tools=[],
                messages=msgs,
                call_name="commit_verifier",
                **self._llm_args,
            )
            verdict = _parse_json_safe(
                result.content or "",
                default={"verdict": "abstain", "reasons": ["parse_error"], "confidence": 0.0},
            )
        except Exception as exc:
            verdict = {"verdict": "abstain", "reasons": [f"verifier_error:{exc}"], "confidence": 0.0}

        self._events.append(RAVELEvent(
            step=self._step, event_type="commit_verifier",
            tool_name=fn,
            gate_verdict=verdict.get("verdict", "abstain"),
            extra={"verifier_output": verdict},
        ))
        return verdict

    # ------------------------------------------------------------------
    # Verifier-gated write interception
    # ------------------------------------------------------------------

    def _verifier_gate(self, msg: "AssistantMessage") -> "AssistantMessage":
        """Intercept write tool calls; route through Commit Verifier LLM."""
        checked_calls: "list[ToolCall]" = []

        for tc in msg.tool_calls:
            fn = tc.function.name if hasattr(tc, "function") else getattr(tc, "name", "")
            if fn not in self._write_tool_names:
                # Read tool — pass through unchanged
                checked_calls.append(tc)
                continue

            # Parse write arguments
            try:
                args = (
                    json.loads(tc.function.arguments)
                    if isinstance(tc.function.arguments, str)
                    else dict(tc.function.arguments)
                )
            except Exception:
                args = {}

            target_objects = tuple(
                f"{fn}:{v}" for k, v in args.items() if k.endswith("_id") and v
            ) or (fn,)

            # --- Commit Verifier LLM call ---
            verifier_result = self._call_commit_verifier(fn, args, target_objects)
            verdict = verifier_result.get("verdict", "abstain")

            self._events.append(RAVELEvent(
                step=self._step, event_type="gate_check",
                tool_name=fn, gate_verdict=verdict,
                extra={"target_objects": list(target_objects)},
            ))

            if verdict == "commit":
                # Verifier authorized the write
                self._events.append(RAVELEvent(
                    step=self._step, event_type="gate_pass", tool_name=fn,
                    extra={"authorized_by": "commit_verifier_llm"}
                ))
                self._safety.record_executed_write(
                    evidence_valid=True,
                    was_stale=False,
                    was_conflicting=False,
                )
                self._accumulated_ev_ids.clear()
                checked_calls.append(tc)

            elif verdict == "reconcile":
                # --- Python ARB as secondary fallback ---
                candidate = CandidateWrite(
                    action=fn, arguments=args,
                    target_objects=target_objects,
                    referenced_evidence_ids=tuple(self._accumulated_ev_ids),
                )
                vis_state = VisibleEvidenceState.from_views(self._all_views)
                from .commit_gate import GateDecision
                gate_dec = GateDecision(
                    verdict="reconcile",
                    reasons=tuple(verifier_result.get("reasons", ["verifier_reconcile"])),
                )
                arb_result = self._arb.reconcile(candidate, gate_dec, vis_state)

                self._events.append(RAVELEvent(
                    step=self._step, event_type="arb",
                    tool_name=fn, arb_stage=arb_result.max_stage_reached,
                    gate_verdict=arb_result.final_verdict,
                ))

                if arb_result.final_verdict == "commit":
                    self._events.append(RAVELEvent(
                        step=self._step, event_type="gate_pass", tool_name=fn,
                        extra={"via_arb": True}
                    ))
                    self._safety.record_executed_write(
                        evidence_valid=True, was_stale=False, was_conflicting=False
                    )
                    self._accumulated_ev_ids.clear()
                    checked_calls.append(tc)
                else:
                    return self._abstain_message(fn, target_objects, verifier_result, msg)

            else:  # abstain
                self._safety.record_blocked_candidate(
                    oracle_was_conflicting=False,
                    ravel_caught=True,
                    oracle_safe_and_necessary=True,
                )
                return self._abstain_message(fn, target_objects, verifier_result, msg)

        if not checked_calls:
            return AssistantMessage.text(
                content="I need additional verification before proceeding.",
                cost=getattr(msg, "cost", 0.0),
            )
        if len(checked_calls) == len(msg.tool_calls):
            return msg
        return AssistantMessage.text(
            content="", tool_calls=checked_calls, cost=getattr(msg, "cost", 0.0)
        )

    def _abstain_message(
        self,
        fn: str,
        target_objects: tuple[str, ...],
        verifier_result: dict,
        original_msg: "AssistantMessage",
    ) -> "AssistantMessage":
        self._events.append(RAVELEvent(
            step=self._step, event_type="abstain", tool_name=fn
        ))
        missing = verifier_result.get("missing_evidence", [])
        reasons = verifier_result.get("reasons", [])
        content = (
            f"The Commit Verifier rejected the proposed {fn} action. "
            f"Reasons: {'; '.join(reasons)}. "
            + (f"Missing evidence: {missing}. " if missing else "")
            + "Please provide the required information before proceeding."
        )
        return AssistantMessage.text(
            content=content, cost=getattr(original_msg, "cost", 0.0)
        )

    # ------------------------------------------------------------------
    # Observation regime (same as RAVELAgent)
    # ------------------------------------------------------------------

    def _apply_regime(
        self, message: "ValidAgentInputMessage"
    ) -> "ValidAgentInputMessage":
        if isinstance(message, UserMessage):
            return message
        if isinstance(message, MultiToolMessage):
            filtered = [self._filter_single(tm) for tm in message.tool_messages]
            if all(f is t for f, t in zip(filtered, message.tool_messages)):
                return message
            return MultiToolMessage(role="tool", tool_messages=filtered)
        if isinstance(message, ToolMessage):
            return self._filter_single(message)
        return message

    def _filter_single(self, tm: "ToolMessage") -> "ToolMessage":
        tool_name = getattr(tm, "name", None) or "tool"
        raw_payload = _parse_payload(tm.content or "")
        object_id = _extract_object_id(tool_name, raw_payload)

        if self._regime == "Delayed":
            return self._delayed_filter(tm, raw_payload, object_id, tool_name)

        record = self._ledger.ingest(
            object_id=object_id, tool_name=tool_name,
            payload=raw_payload, source_agent="tool_worker",
        )
        self._accumulated_ev_ids.append(record.evidence_id)
        self._all_ev_ids.append(record.evidence_id)

        view = self._vpol.project(record, agent_id="orchestrator", event_index=self._step)
        self._all_views.append(view)

        visible = dict(view.visible_fields)
        if self._regime == "FieldMask":
            visible = _mask_fields(visible, self._mask_fraction, self._seed, self._step)

        self._total_raw_fields += len(raw_payload)
        self._total_visible_fields += len(visible)

        self._events.append(RAVELEvent(
            step=self._step, event_type="observe",
            tool_name=tool_name, object_id=object_id,
            regime=self._regime,
            visible_field_count=len(visible),
            total_field_count=len(raw_payload),
            extra={"evidence_id": record.evidence_id},
        ))

        if visible == raw_payload:
            return tm
        return _reconstruct_tool_message(tm, visible)

    def _delayed_filter(
        self, tm: "ToolMessage", payload: dict, object_id: str, tool_name: str
    ) -> "ToolMessage":
        record = self._ledger.ingest(
            object_id=object_id, tool_name=tool_name,
            payload=payload, source_agent="tool_worker",
        )
        self._accumulated_ev_ids.append(record.evidence_id)
        self._all_ev_ids.append(record.evidence_id)
        self._delayed_buffer.append((payload, object_id, tool_name))

        buf_idx = len(self._delayed_buffer) - 1 - self._delay
        if buf_idx < 0:
            stale = {"_ravel_status": f"evidence_pending_step_{self._step + self._delay}"}
        else:
            stale, _, _ = self._delayed_buffer[buf_idx]

        view = self._vpol.project(record, agent_id="orchestrator", event_index=self._step)
        self._all_views.append(view)
        self._total_raw_fields += len(payload)
        self._total_visible_fields += len(stale)

        self._events.append(RAVELEvent(
            step=self._step, event_type="observe",
            tool_name=tool_name, object_id=object_id,
            regime="Delayed", visible_field_count=len(stale),
            total_field_count=len(payload),
        ))

        if stale == payload:
            return tm
        return _reconstruct_tool_message(tm, stale)

    # ------------------------------------------------------------------
    # Metrics export (identical structure to RAVELAgent)
    # ------------------------------------------------------------------

    def build_trial_summary(self) -> "RAVELTrialSummary":
        obs = sum(1 for e in self._events if e.event_type == "observe")
        checks = sum(1 for e in self._events if e.event_type == "gate_check")
        passes = sum(1 for e in self._events if e.event_type == "gate_pass")
        verifier_calls = sum(1 for e in self._events if e.event_type == "commit_verifier")
        supervisor_calls = sum(1 for e in self._events if e.event_type == "supervisor")
        policy_calls = sum(1 for e in self._events if e.event_type == "policy_agent")
        worker_calls = sum(1 for e in self._events if e.event_type == "tool_worker")
        ratio = (
            self._total_visible_fields / self._total_raw_fields
            if self._total_raw_fields > 0 else 1.0
        )
        return RAVELTrialSummary(
            task_id=self._task_id,
            domain=self._domain,
            regime=self._regime,
            delay=self._delay,
            gate_enabled=self._gate_enabled,
            total_steps=self._step,
            observations=obs,
            gate_checks=checks,
            gate_passes=passes,
            gate_fails=checks - passes,
            arb_commits=0,
            arb_abstains=sum(1 for e in self._events if e.event_type == "abstain"),
            total_field_count=self._total_raw_fields,
            visible_field_count=self._total_visible_fields,
            token_compression_ratio=ratio,
            events=self._events,
            safety={
                "evidence_valid_rate": self._safety.evidence_valid_rate(),
                "stale_action_rate": self._safety.stale_action_rate(),
                "conflicting_write_rate": self._safety.conflicting_write_rate(),
                "overblock_rate": self._safety.overblock_rate(),
                "llm_calls_per_turn": {
                    "supervisor": supervisor_calls,
                    "policy_agent": policy_calls,
                    "tool_worker": worker_calls,
                    "commit_verifier": verifier_calls,
                    "total": supervisor_calls + policy_calls + worker_calls + verifier_calls,
                },
            },
        )


# ---------------------------------------------------------------------------
# Factory function (tau2 registry compatible)
# ---------------------------------------------------------------------------

_RAVEL_KEYS: frozenset[str] = frozenset({
    "regime", "delay", "mask_fraction", "gate_enabled", "arb_max_stage",
    "task_id", "domain", "seed",
})


def create_multiagent_orchestrator(tools, domain_policy, **kwargs):
    """Factory for MultiAgentOrchestrator (tau2 registry-compatible).

    Drop-in replacement for create_ravel_agent with true 4-role multi-agent
    architecture: Supervisor + Policy Agent + Tool Worker + Commit Verifier.
    """
    raw_llm_args = dict(kwargs.get("llm_args") or {})

    ravel_cfg: dict = {}
    for k in list(raw_llm_args.keys()):
        if k in _RAVEL_KEYS:
            ravel_cfg[k] = raw_llm_args.pop(k)
    for k in _RAVEL_KEYS:
        if k in kwargs and k not in ravel_cfg:
            ravel_cfg[k] = kwargs[k]

    domain = ravel_cfg.get("domain", "unknown")
    task_obj = kwargs.get("task")
    task_id = ravel_cfg.get("task_id", str(getattr(task_obj, "id", "unknown")))

    return MultiAgentOrchestrator(
        tools=tools,
        domain_policy=domain_policy,
        llm=kwargs.get("llm", ""),
        llm_args=raw_llm_args,
        regime=ravel_cfg.get("regime", "FullSync"),
        delay=int(ravel_cfg.get("delay", 1)),
        mask_fraction=float(ravel_cfg.get("mask_fraction", 0.3)),
        write_tools=DOMAIN_WRITE_TOOLS.get(domain),
        gate_enabled=bool(ravel_cfg.get("gate_enabled", True)),
        arb_max_stage=int(ravel_cfg.get("arb_max_stage", 6)),
        task_id=task_id,
        domain=domain,
        seed=int(ravel_cfg.get("seed", 42)),
    )
