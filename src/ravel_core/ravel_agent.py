"""RAVEL-augmented tau2 agent.

Wraps tau2's LLMAgent with:
  - VDL evidence ingestion on every tool result
  - MSE-Router projection per observation regime (FullSync/Delayed/FieldMask/ConflictingView)
  - CommitGate verification before each write-tool call
  - ARB escalation on gate failure
  - SafetyMetricsAccumulator recording
  - Token tracking per API call

Factory function ``create_ravel_agent`` is compatible with tau2 registry.register_agent_factory.
"""

from __future__ import annotations

import hashlib
import json
import random
import uuid
from dataclasses import dataclass, field
from typing import Any

from .commit_gate import (
    ActionSchema,
    CandidateWrite,
    CommitGate,
    GateDecision,
    RequiredEvidence,
    VisibleEvidenceState,
)
from .evidence import EvidenceLedger
from .metrics import SafetyMetricsAccumulator
from .reconciliation import AdaptiveReconciliationBudget
from .visibility import EvidenceView, VisibilityPolicy

# Optional tau2 imports — only used when running inside tau2 environment.
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
    _TAU2_AVAILABLE = True
except ImportError:  # pragma: no cover
    _TAU2_AVAILABLE = False
    HalfDuplexAgent = object  # type: ignore[assignment,misc]


# ---------------------------------------------------------------------------
# Write-tool registries (mirrored from task_audit.py)
# ---------------------------------------------------------------------------

AIRLINE_WRITE_TOOLS: frozenset[str] = frozenset({
    "book_reservation", "cancel_reservation", "send_certificate",
    "update_reservation_baggages", "update_reservation_flights",
    "update_reservation_passengers",
})
RETAIL_WRITE_TOOLS: frozenset[str] = frozenset({
    "exchange_delivered_order_items", "return_delivered_order_items",
    "modify_pending_order_items", "modify_pending_order_payment",
    "modify_pending_order_address", "cancel_pending_order",
})
TELECOM_WRITE_TOOLS: frozenset[str] = frozenset({
    "connect_vpn", "disconnect_vpn", "disable_roaming", "enable_roaming",
    "refuel_data", "reseat_sim_card", "reset_apn_settings", "resume_line",
    "send_payment_request", "set_apn_settings", "set_network_mode_preference",
    "suspend_line", "toggle_airplane_mode", "toggle_data", "toggle_data_saver_mode",
    "toggle_roaming", "toggle_wifi", "toggle_wifi_calling",
})
DOMAIN_WRITE_TOOLS: dict[str, frozenset[str]] = {
    "airline": AIRLINE_WRITE_TOOLS,
    "retail": RETAIL_WRITE_TOOLS,
    "telecom": TELECOM_WRITE_TOOLS,
}


# ---------------------------------------------------------------------------
# Evidence helpers
# ---------------------------------------------------------------------------

def _extract_object_id(tool_name: str, payload: dict[str, Any]) -> str:
    """Heuristic: first *_id field in payload, else tool + hash."""
    for key, val in payload.items():
        if key.endswith("_id") and val is not None:
            return f"{tool_name}:{val}"
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode()
    ).hexdigest()[:10]
    return f"{tool_name}:{digest}"


def _parse_payload(content: str) -> dict[str, Any]:
    """Parse ToolMessage.content to a flat dict. Returns {} on failure."""
    if not content:
        return {}
    try:
        data = json.loads(content)
        if isinstance(data, dict):
            return data
        return {"_result": data}
    except (json.JSONDecodeError, TypeError):
        return {"_raw": content[:512]}


def _reconstruct_tool_message(original: "ToolMessage", visible: dict[str, Any]) -> "ToolMessage":
    """Return a ToolMessage with only visible fields in its content."""
    filtered_content = json.dumps(visible, default=str)
    return ToolMessage(
        id=original.id,
        role=original.role,
        content=filtered_content,
        requestor=original.requestor,
        error=original.error,
        turn_idx=original.turn_idx,
    )


def _mask_fields(
    fields: dict[str, Any], mask_fraction: float, seed: int, step: int
) -> dict[str, Any]:
    """Deterministically mask mask_fraction of keys for FieldMask regime."""
    if not fields or mask_fraction <= 0:
        return fields
    rng = random.Random(seed ^ (step * 1337))
    keys = list(fields.keys())
    n_mask = max(0, int(len(keys) * mask_fraction))
    masked = set(rng.sample(keys, n_mask)) if n_mask else set()
    return {k: v for k, v in fields.items() if k not in masked}


# ---------------------------------------------------------------------------
# RAVEL event log (lightweight, in-memory per trial)
# ---------------------------------------------------------------------------

@dataclass
class RAVELEvent:
    step: int
    event_type: str  # "observe" | "gate_check" | "gate_pass" | "gate_fail" | "arb" | "abstain"
    tool_name: str = ""
    object_id: str = ""
    regime: str = ""
    visible_field_count: int = 0
    total_field_count: int = 0
    token_estimate: int = 0
    gate_verdict: str = ""
    arb_stage: int = 0
    extra: dict = field(default_factory=dict)


@dataclass
class RAVELTrialSummary:
    task_id: str
    domain: str
    regime: str
    delay: int
    gate_enabled: bool
    total_steps: int
    observations: int
    gate_checks: int
    gate_passes: int
    gate_fails: int
    arb_commits: int
    arb_abstains: int
    total_field_count: int
    visible_field_count: int
    token_compression_ratio: float  # visible / total
    events: list[RAVELEvent] = field(default_factory=list)
    safety: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# RAVEL Agent
# ---------------------------------------------------------------------------

class RAVELAgent(HalfDuplexAgent):
    """Half-duplex agent with RAVEL evidence management layer.

    Designed for single-agent tau2 simulations.  Multi-agent extension is
    out of scope for the current experiment.
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
        write_tools: frozenset[str] | None = None,
        gate_enabled: bool = True,
        arb_max_stage: int = 6,
        task_id: str = "unknown",
        domain: str = "unknown",
        seed: int = 42,
    ) -> None:
        super().__init__(tools=tools, domain_policy=domain_policy)
        self._regime = regime
        self._delay = delay
        self._mask_fraction = mask_fraction
        self._write_tools = write_tools if write_tools is not None else DOMAIN_WRITE_TOOLS.get(domain, frozenset())
        self._gate_enabled = gate_enabled
        self._task_id = task_id
        self._domain = domain
        self._seed = seed

        # Inner LLM (blind — no GT hints; for paired comparison with llm_agent_gt baseline)
        self._inner = LLMAgent(
            tools=tools,
            domain_policy=domain_policy,
            llm=llm,
            llm_args=llm_args or {},
        )

        # RAVEL core modules
        self._ledger = EvidenceLedger()
        self._vpol = VisibilityPolicy(regime=regime, delay=delay, seed=seed, mask_fields=set())
        # Legacy single-agent path keeps permissive mode explicitly (visibility
        # regimes studied without a second gate confound). Phase-2 write-safety
        # runs pass real schemas + permissive=False (plan §4.2).
        self._gate = CommitGate(schemas={}, permissive=True)
        self._arb = AdaptiveReconciliationBudget(
            gate=self._gate,
            ledger=self._ledger,
            max_stage=arb_max_stage,
        )
        self._safety = SafetyMetricsAccumulator()

        # Per-trial state
        self._step = 0
        self._accumulated_ev_ids: list[str] = []  # since last write
        self._all_ev_ids: list[str] = []
        self._all_views: list[EvidenceView] = []
        # Delayed buffer: list of (raw_payload, object_id, tool_name) per step
        self._delayed_buffer: list[tuple[dict, str, str]] = []
        self._events: list[RAVELEvent] = []

        # Token tracking
        self._total_raw_fields = 0
        self._total_visible_fields = 0

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

        # 1. Process incoming tool result(s) through RAVEL evidence layer
        filtered = self._apply_regime(message)

        # 2. Append filtered message to conversation state (bypassing inner's append)
        if isinstance(filtered, MultiToolMessage):
            state.messages.extend(filtered.tool_messages)
        else:
            state.messages.append(filtered)

        # 3. Generate next agent action via inner LLM (using state directly)
        all_messages = state.system_messages + state.messages
        from tau2.utils.llm_utils import generate
        assistant_msg = generate(
            model=self._inner.llm,
            tools=self._inner.tools,
            messages=all_messages,
            call_name="ravel_agent_response",
            **self._inner.llm_args,
        )

        # 4. CommitGate check for write tool calls
        if self._gate_enabled and assistant_msg.is_tool_call():
            assistant_msg = self._run_gate(assistant_msg)

        state.messages.append(assistant_msg)
        return assistant_msg, state

    # ------------------------------------------------------------------
    # Observation regime filtering
    # ------------------------------------------------------------------

    def _apply_regime(self, message: "ValidAgentInputMessage") -> "ValidAgentInputMessage":
        """Project tool results through VDL + visibility policy."""
        if isinstance(message, UserMessage):
            return message
        if isinstance(message, MultiToolMessage):
            filtered_tms = [self._filter_single(tm) for tm in message.tool_messages]
            if all(fm is tm for fm, tm in zip(filtered_tms, message.tool_messages)):
                return message
            return MultiToolMessage(role="tool", tool_messages=filtered_tms)
        if isinstance(message, ToolMessage):
            return self._filter_single(message)
        return message

    def _filter_single(self, tm: "ToolMessage") -> "ToolMessage":
        """Ingest one ToolMessage into VDL and return the regime-filtered view."""
        tool_name = getattr(tm, "name", None) or "tool"
        raw_payload = _parse_payload(tm.content or "")
        object_id = _extract_object_id(tool_name, raw_payload)

        # Delayed regime: return stale payload, queue current
        if self._regime == "Delayed":
            return self._delayed_filter(tm, raw_payload, object_id, tool_name)

        # Ingest into VDL
        record = self._ledger.ingest(
            object_id=object_id,
            tool_name=tool_name,
            payload=raw_payload,
            source_agent="tool_worker",
        )
        self._accumulated_ev_ids.append(record.evidence_id)
        self._all_ev_ids.append(record.evidence_id)

        # Project through visibility policy
        view = self._vpol.project(record, agent_id="ravel_agent", event_index=self._step)
        self._all_views.append(view)

        # Build visible payload
        visible = dict(view.visible_fields)
        if self._regime == "FieldMask":
            visible = _mask_fields(visible, self._mask_fraction, self._seed, self._step)

        # Track field counts
        self._total_raw_fields += len(raw_payload)
        self._total_visible_fields += len(visible)

        # Record event
        self._events.append(RAVELEvent(
            step=self._step, event_type="observe",
            tool_name=tool_name, object_id=object_id,
            regime=self._regime,
            visible_field_count=len(visible),
            total_field_count=len(raw_payload),
            extra={"evidence_id": record.evidence_id},
        ))

        if visible == raw_payload:
            return tm  # no change needed
        return _reconstruct_tool_message(tm, visible)

    def _delayed_filter(
        self, tm: "ToolMessage", payload: dict, object_id: str, tool_name: str
    ) -> "ToolMessage":
        """Buffer current payload; return payload from `delay` steps ago."""
        # Ingest into VDL
        record = self._ledger.ingest(
            object_id=object_id, tool_name=tool_name,
            payload=payload, source_agent="tool_worker",
        )
        self._accumulated_ev_ids.append(record.evidence_id)
        self._all_ev_ids.append(record.evidence_id)

        # Push to buffer
        self._delayed_buffer.append((payload, object_id, tool_name))

        # Return payload from `delay` steps ago
        buf_idx = len(self._delayed_buffer) - 1 - self._delay
        if buf_idx < 0:
            # No stale evidence yet → empty response
            stale = {"_ravel_status": f"evidence_pending_step_{self._step + self._delay}"}
        else:
            stale, _, _ = self._delayed_buffer[buf_idx]

        view = self._vpol.project(record, agent_id="ravel_agent", event_index=self._step)
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
    # CommitGate
    # ------------------------------------------------------------------

    def _run_gate(self, msg: "AssistantMessage") -> "AssistantMessage":
        """Check each write tool call through CommitGate; abstain if ARB exhausted."""
        checked_calls: list[ToolCall] = []
        for tc in msg.tool_calls:
            fn = tc.function.name if hasattr(tc, "function") else getattr(tc, "name", "")
            if fn not in self._write_tools:
                checked_calls.append(tc)
                continue

            # Build candidate write
            try:
                args = json.loads(tc.function.arguments) if isinstance(tc.function.arguments, str) else dict(tc.function.arguments)
            except Exception:
                args = {}
            target_objects = tuple(
                f"{fn}:{v}" for k, v in args.items() if k.endswith("_id") and v
            ) or (fn,)

            candidate = CandidateWrite(
                action=fn,
                arguments=args,
                target_objects=target_objects,
                referenced_evidence_ids=tuple(self._accumulated_ev_ids),
                claimed_preconditions=(),
            )

            # Build visible state from all views
            vis_state = VisibleEvidenceState.from_views(self._all_views)

            # Gate check
            initial_decision = self._gate.verify(
                candidate, ledger=self._ledger, visible_state=vis_state
            )

            self._events.append(RAVELEvent(
                step=self._step, event_type="gate_check",
                tool_name=fn, gate_verdict=initial_decision.verdict,
                extra={"target_objects": list(target_objects)},
            ))

            if initial_decision.allowed:
                self._events.append(RAVELEvent(step=self._step, event_type="gate_pass", tool_name=fn))
                self._safety.record_executed_write(
                    evidence_valid=bool(self._accumulated_ev_ids),
                    was_stale=bool(initial_decision.stale_fields),
                    was_conflicting=bool(initial_decision.conflicting_fields),
                )
                self._accumulated_ev_ids.clear()  # reset after approved write
                checked_calls.append(tc)
                continue

            # Run ARB
            arb_result = self._arb.reconcile(candidate, initial_decision, vis_state)
            self._events.append(RAVELEvent(
                step=self._step, event_type="arb",
                tool_name=fn, arb_stage=arb_result.max_stage_reached,
                gate_verdict=arb_result.final_verdict,
            ))

            if arb_result.final_verdict == "commit":
                self._events.append(RAVELEvent(step=self._step, event_type="gate_pass", tool_name=fn, extra={"via_arb": True}))
                self._safety.record_executed_write(
                    evidence_valid=True,
                    was_stale=bool(initial_decision.stale_fields),
                    was_conflicting=bool(initial_decision.conflicting_fields),
                )
                self._accumulated_ev_ids.clear()
                checked_calls.append(tc)
            else:
                # Abstain: drop this tool call, generate text explanation
                self._events.append(RAVELEvent(step=self._step, event_type="abstain", tool_name=fn))
                # Record as blocked candidate (we don't know oracle verdict, assume safe-but-blocked)
                self._safety.record_blocked_candidate(
                    oracle_was_conflicting=bool(initial_decision.conflicting_fields),
                    ravel_caught=bool(initial_decision.conflicting_fields),
                    oracle_safe_and_necessary=not bool(initial_decision.conflicting_fields),
                )
                return AssistantMessage.text(
                    content=(
                        f"I need to gather more information before I can {fn}. "
                        f"The evidence for {list(target_objects)} is insufficient "
                        f"(ARB stage {arb_result.max_stage_reached}: {arb_result.final_verdict}). "
                        "Please confirm the relevant details so I can proceed safely."
                    ),
                    cost=getattr(msg, "cost", 0.0),
                )

        # All write calls approved; replace tool_calls with filtered list
        if len(checked_calls) == len(msg.tool_calls):
            return msg
        if not checked_calls:
            return AssistantMessage.text(
                content="I need additional information before proceeding with the requested action.",
                cost=getattr(msg, "cost", 0.0),
            )
        return AssistantMessage.text(
            content="",
            tool_calls=checked_calls,
            cost=getattr(msg, "cost", 0.0),
        )

    # ------------------------------------------------------------------
    # Summary / metrics export
    # ------------------------------------------------------------------

    def build_trial_summary(self) -> RAVELTrialSummary:
        obs = sum(1 for e in self._events if e.event_type == "observe")
        checks = sum(1 for e in self._events if e.event_type == "gate_check")
        passes = sum(1 for e in self._events if e.event_type == "gate_pass")
        fails = checks - passes
        arb_commits = sum(1 for e in self._events if e.event_type == "arb" and e.gate_verdict == "commit")
        arb_abstains = sum(1 for e in self._events if e.event_type == "abstain")
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
            gate_fails=fails,
            arb_commits=arb_commits,
            arb_abstains=arb_abstains,
            total_field_count=self._total_raw_fields,
            visible_field_count=self._total_visible_fields,
            token_compression_ratio=ratio,
            events=self._events,
            safety={
                "evidence_valid_rate": self._safety.evidence_valid_rate(),
                "stale_action_rate": self._safety.stale_action_rate(),
                "conflicting_write_rate": self._safety.conflicting_write_rate(),
                "overblock_rate": self._safety.overblock_rate(),
            },
        )


# ---------------------------------------------------------------------------
# Factory function (tau2 registry compatible)
# ---------------------------------------------------------------------------

# Keys that belong to RAVEL config (not passed to litellm)
_RAVEL_KEYS: frozenset[str] = frozenset({
    "regime", "delay", "mask_fraction", "gate_enabled", "arb_max_stage",
    "task_id", "domain", "seed",
})


def create_ravel_agent(tools, domain_policy, **kwargs):
    """Factory for RAVELAgent (tau2 registry-compatible).

    tau2 calls this as:
        factory(tools, domain_policy, llm=..., llm_args=..., task=..., ...)

    RAVEL-specific config is embedded in ``llm_args`` under _RAVEL_KEYS.
    Those keys are stripped before forwarding to litellm.

    Recognised RAVEL keys (in llm_args):
        regime: "FullSync" | "Delayed" | "FieldMask" | "ConflictingView"
        delay: int   (Delayed regime — steps to delay)
        mask_fraction: float  (FieldMask regime — fraction of fields to hide)
        gate_enabled: bool
        arb_max_stage: int (1-6)
        task_id: str
        domain: str
        seed: int
    """
    raw_llm_args = dict(kwargs.get("llm_args") or {})

    # Extract RAVEL-specific args from llm_args
    ravel_cfg: dict = {}
    for k in list(raw_llm_args.keys()):
        if k in _RAVEL_KEYS:
            ravel_cfg[k] = raw_llm_args.pop(k)

    # Also accept RAVEL keys as top-level kwargs (for programmatic use)
    for k in _RAVEL_KEYS:
        if k in kwargs and k not in ravel_cfg:
            ravel_cfg[k] = kwargs[k]

    domain = ravel_cfg.get("domain", "unknown")
    task_obj = kwargs.get("task")
    task_id = ravel_cfg.get("task_id", str(getattr(task_obj, "id", "unknown")))

    return RAVELAgent(
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
