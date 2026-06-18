"""MSE-Router: Minimal Sufficient Evidence routing for RAVEL.

Implements the rule-based, auditable routing formula from Proposal §4.3:

    F_i^t = F_role(i) ∩ F_goal_i ∪ F_deps(goal_i)

For reads/low-risk steps, the router provides headers, delta previews, and
required fields from the ledger.  For high-risk candidate writes, the gate
itself constructs the minimal read-set from the action schema — the router
defers to the gate rather than guessing completeness.

Design constraints from §1.2:
- Rule-based first; do NOT train a learned router until ablations prove need.
- Fallback to widening the field set or fetching raw payload, never direct commit.
- All routing decisions are logged with reason codes for audit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .evidence import EvidenceLedger, thaw_value


@dataclass(frozen=True)
class EvidenceSlice:
    """Minimal prompt-facing evidence package produced by the MSE-Router."""

    object_ids: tuple[str, ...]
    headers: tuple[dict[str, Any], ...]
    delta_fields: tuple[dict[str, Any], ...]
    pointers: tuple[str, ...]
    reason_codes: tuple[str, ...]
    fallback_decision: str  # "normal" | "widened" | "raw_fetch_required"
    token_estimate: int  # rough field-count proxy; replace with real tokenizer


@dataclass
class AgentContext:
    """Caller-provided context for routing decisions."""

    agent_id: str
    role: str  # "supervisor" | "policy_agent" | "tool_worker" | "commit_verifier"
    subgoal: str
    required_field_names: tuple[str, ...] = ()
    dependency_object_ids: tuple[str, ...] = ()
    is_high_risk_write: bool = False
    risk_state: float = 0.0  # normalised 0–1 from ARB risk score


# Role-level field allowlists (§4.3 F_role(i)).
# Supervisor gets only summary headers; worker gets full required fields.
_ROLE_FIELD_POLICY: dict[str, str] = {
    "supervisor": "header_only",
    "policy_agent": "header_and_policy_fields",
    "tool_worker": "required_fields",
    "commit_verifier": "required_fields_latest",
}


def _header_from_record(record: Any) -> dict[str, Any]:
    """Build compact header (§4.2 h_j) from a ledger record."""
    return {
        "object_id": record.object_id,
        "version": record.version,
        "changed_fields": list(record.changed_fields),
        "logical_clock": record.logical_clock,
        "source_agent": record.source_agent,
        "risk_tag": record.risk_tag,
        "conflict_flag": record.conflict_flag,
        "digest": record.digest[:16],  # truncated for prompt efficiency
        "pointer": record.raw_payload_pointer,
    }


def _delta_from_record(record: Any) -> dict[str, Any]:
    """Return only the changed-field values as a delta slice."""
    return {
        field_name: thaw_value(record.field_values[field_name])
        for field_name in record.changed_fields
        if field_name in record.field_values
    }


class MSERouter:
    """Rule-based Minimal Sufficient Evidence router.

    Usage::

        router = MSERouter(ledger)
        ctx = AgentContext(
            agent_id="worker_1",
            role="tool_worker",
            subgoal="cancel reservation R1",
            required_field_names=("status", "reservation_id"),
            dependency_object_ids=("reservation:R1",),
        )
        evidence_slice = router.route(ctx)
    """

    def __init__(self, ledger: EvidenceLedger) -> None:
        self._ledger = ledger

    def route(self, ctx: AgentContext) -> EvidenceSlice:
        """Produce a minimal evidence slice for the given agent context."""
        policy = _ROLE_FIELD_POLICY.get(ctx.role, "required_fields")

        headers: list[dict[str, Any]] = []
        deltas: list[dict[str, Any]] = []
        pointers: list[str] = []
        reason_codes: list[str] = []
        fallback_decision = "normal"

        for obj_id in ctx.dependency_object_ids:
            record = self._ledger.latest(obj_id)
            if record is None:
                reason_codes.append(f"no_evidence_for:{obj_id}")
                fallback_decision = "raw_fetch_required"
                continue

            headers.append(_header_from_record(record))
            pointers.append(record.raw_payload_pointer)

            if policy == "header_only":
                reason_codes.append(f"role_header_only:{obj_id}")
                continue

            # For workers and verifiers: add delta and required fields.
            if record.changed_fields:
                deltas.append(_delta_from_record(record))
                reason_codes.append(f"delta_preview:{obj_id}")

            if ctx.required_field_names and policy in (
                "required_fields",
                "required_fields_latest",
                "header_and_policy_fields",
            ):
                # Verify required fields are present and fresh.
                for field_name in ctx.required_field_names:
                    entry = self._ledger.latest_field(obj_id, field_name)
                    if entry is None:
                        reason_codes.append(f"missing_required_field:{obj_id}.{field_name}")
                        fallback_decision = "raw_fetch_required"
                    else:
                        reason_codes.append(f"field_present:{obj_id}.{field_name}")

        # High-risk write: signal that gate must construct read-set, not us.
        if ctx.is_high_risk_write:
            reason_codes.append("deferred_to_gate:high_risk_write")
            fallback_decision = "widened" if fallback_decision == "normal" else fallback_decision

        # Estimate token cost as field-count proxy (replace with real tokenizer).
        token_estimate = (
            sum(len(h) for h in headers)
            + sum(len(d) for d in deltas)
            + len(pointers) * 4  # pointer line ≈ 4 tokens
        )

        return EvidenceSlice(
            object_ids=tuple(ctx.dependency_object_ids),
            headers=tuple(headers),
            delta_fields=tuple(deltas),
            pointers=tuple(pointers),
            reason_codes=tuple(reason_codes),
            fallback_decision=fallback_decision,
            token_estimate=token_estimate,
        )
