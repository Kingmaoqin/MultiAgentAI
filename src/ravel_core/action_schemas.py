"""ActionSchema registry for high-risk write tools (plan §4.1).

Pilot coverage of the *main* high-risk write actions in airline + retail (the
plan explicitly says NOT to cover every tool at once). Each schema declares the
evidence that must be present, fresh, and traceable before a commit, plus
programmatic policy checks grounded in the tau2 domain policies.

These schemas turn the CommitGate from permissive into an evidence-checked gate
so H3/H4/H5 (write-safety) become measurable.

`required_for` taxonomy: precondition | argument | policy | authorization |
conflict_check.  Field freshness is ``latest_required`` for every decision field
(a write on a stale decision field is exactly the unsafe case RAVEL targets).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .commit_gate import ActionSchema, RequiredEvidence


@dataclass(frozen=True)
class FieldSpec:
    """Rich field spec (plan §4.1 JSON shape) — superset of RequiredEvidence."""
    object_ref: str
    field: str
    freshness: str = "latest_required"
    source_tools: tuple[str, ...] = ()
    required_for: str = "precondition"


@dataclass(frozen=True)
class RichActionSchema:
    """The full §4.1 schema. ``to_action_schema`` projects it onto the runtime
    ``ActionSchema`` the CommitGate consumes (object_ref+field → RequiredEvidence
    keyed by the candidate's resolved target object id at gate time)."""
    action_name: str
    risk_level: str
    target_object_type: str
    required_fields: tuple[FieldSpec, ...]
    policy_checks: tuple[str, ...]
    allowed_write_tools: tuple[str, ...]
    requires_user_confirmation: bool = False
    requires_compare_and_swap: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_name": self.action_name,
            "risk_level": self.risk_level,
            "target_object_type": self.target_object_type,
            "required_fields": [vars(f) for f in self.required_fields],
            "policy_checks": list(self.policy_checks),
            "allowed_write_tools": list(self.allowed_write_tools),
            "requires_user_confirmation": self.requires_user_confirmation,
            "requires_compare_and_swap": self.requires_compare_and_swap,
        }


def _F(object_ref: str, field: str, required_for: str = "precondition",
       source_tools: tuple[str, ...] = ()) -> FieldSpec:
    return FieldSpec(object_ref=object_ref, field=field,
                     source_tools=source_tools, required_for=required_for)


# --- AIRLINE (§4.1) ---------------------------------------------------------

_AIRLINE: tuple[RichActionSchema, ...] = (
    RichActionSchema(
        action_name="cancel_reservation", risk_level="high",
        target_object_type="reservation",
        required_fields=(
            _F("reservation", "status", "precondition", ("get_reservation_details",)),
            _F("reservation", "cabin", "policy", ("get_reservation_details",)),
            _F("reservation", "flight_type", "policy", ("get_reservation_details",)),
        ),
        policy_checks=(
            "basic_economy is non-refundable unless within 24h of booking or insured",
            "reservation must not be already cancelled",
        ),
        allowed_write_tools=("cancel_reservation",),
        requires_user_confirmation=True,
    ),
    RichActionSchema(
        action_name="update_reservation_flights", risk_level="high",
        target_object_type="reservation",
        required_fields=(
            _F("reservation", "status", "precondition", ("get_reservation_details",)),
            _F("reservation", "cabin", "policy", ("get_reservation_details",)),
            _F("flight", "status", "conflict_check", ("search_direct_flight",)),
        ),
        policy_checks=("fare difference must be charged/refunded to original payment",),
        allowed_write_tools=("update_reservation_flights",),
    ),
    RichActionSchema(
        action_name="book_reservation", risk_level="high",
        target_object_type="reservation",
        required_fields=(
            _F("flight", "status", "precondition", ("search_direct_flight",)),
            _F("user", "payment_methods", "authorization", ("get_user_details",)),
        ),
        policy_checks=("payment method must belong to the user and cover total cost",),
        allowed_write_tools=("book_reservation",),
        requires_user_confirmation=True,
    ),
    RichActionSchema(
        action_name="update_reservation_passengers", risk_level="medium",
        target_object_type="reservation",
        required_fields=(
            _F("reservation", "status", "precondition", ("get_reservation_details",)),
        ),
        policy_checks=("passenger count must match booked seats",),
        allowed_write_tools=("update_reservation_passengers",),
    ),
    RichActionSchema(
        action_name="update_reservation_baggages", risk_level="medium",
        target_object_type="reservation",
        required_fields=(
            _F("reservation", "status", "precondition", ("get_reservation_details",)),
            _F("user", "membership", "policy", ("get_user_details",)),
        ),
        policy_checks=("free baggage allowance depends on cabin + membership tier",),
        allowed_write_tools=("update_reservation_baggages",),
    ),
    RichActionSchema(
        action_name="send_certificate", risk_level="high",
        target_object_type="user",
        required_fields=(
            _F("user", "user_id", "authorization", ("get_user_details",)),
        ),
        policy_checks=("compensation amount must follow the airline policy table",),
        allowed_write_tools=("send_certificate",),
    ),
)

# --- RETAIL (§4.1) ----------------------------------------------------------

_RETAIL: tuple[RichActionSchema, ...] = (
    RichActionSchema(
        action_name="cancel_pending_order", risk_level="high",
        target_object_type="order",
        required_fields=(
            _F("order", "status", "precondition", ("get_order_details",)),
        ),
        policy_checks=("order status must be 'pending' (cannot cancel processed/delivered)",),
        allowed_write_tools=("cancel_pending_order",),
        requires_user_confirmation=True,
    ),
    RichActionSchema(
        action_name="return_delivered_order_items", risk_level="high",
        target_object_type="order",
        required_fields=(
            _F("order", "status", "precondition", ("get_order_details",)),
            _F("order", "items", "argument", ("get_order_details",)),
        ),
        policy_checks=("order status must be 'delivered'; items must belong to the order",),
        allowed_write_tools=("return_delivered_order_items",),
    ),
    RichActionSchema(
        action_name="exchange_delivered_order_items", risk_level="high",
        target_object_type="order",
        required_fields=(
            _F("order", "status", "precondition", ("get_order_details",)),
            _F("order", "items", "argument", ("get_order_details",)),
            _F("product", "available", "conflict_check", ("get_product_details",)),
        ),
        policy_checks=("exchange target must be same product type and available",),
        allowed_write_tools=("exchange_delivered_order_items",),
    ),
    RichActionSchema(
        action_name="modify_pending_order_items", risk_level="high",
        target_object_type="order",
        required_fields=(
            _F("order", "status", "precondition", ("get_order_details",)),
            _F("product", "available", "conflict_check", ("get_product_details",)),
        ),
        policy_checks=("order status must be 'pending'; new item must be available",),
        allowed_write_tools=("modify_pending_order_items",),
    ),
    RichActionSchema(
        action_name="modify_pending_order_payment", risk_level="high",
        target_object_type="order",
        required_fields=(
            _F("order", "status", "precondition", ("get_order_details",)),
            _F("user", "payment_methods", "authorization", ("get_user_details",)),
        ),
        policy_checks=("new payment method must belong to the user",),
        allowed_write_tools=("modify_pending_order_payment",),
    ),
    RichActionSchema(
        action_name="modify_pending_order_address", risk_level="medium",
        target_object_type="order",
        required_fields=(
            _F("order", "status", "precondition", ("get_order_details",)),
        ),
        policy_checks=("order status must be 'pending'",),
        allowed_write_tools=("modify_pending_order_address",),
    ),
)

_REGISTRY: dict[str, tuple[RichActionSchema, ...]] = {
    "airline": _AIRLINE,
    "retail": _RETAIL,
}


def rich_schemas(domain: str) -> tuple[RichActionSchema, ...]:
    return _REGISTRY.get(domain, ())


def high_risk_actions(domain: str) -> set[str]:
    """Actions whose missing schema must NOT be silently committed (§4.2)."""
    return {s.action_name for s in rich_schemas(domain)
            if s.risk_level in ("high", "medium")}


def build_action_schemas(domain: str, target_object_id: str | None = None
                         ) -> dict[str, ActionSchema]:
    """Project the rich registry onto runtime ``ActionSchema`` objects keyed by
    action name. ``RequiredEvidence.object_id`` is set to ``target_object_id``
    when known (resolved at gate time), else to the abstract ``object_ref`` so
    the schema is still inspectable/coverable in tests."""
    out: dict[str, ActionSchema] = {}
    for s in rich_schemas(domain):
        reqs = tuple(
            RequiredEvidence(object_id=target_object_id or f.object_ref, field=f.field)
            for f in s.required_fields
        )
        out[s.action_name] = ActionSchema(
            action=s.action_name, required_fields=reqs,
            policy_checks=s.policy_checks, risk_level=s.risk_level,
        )
    return out


def schema_coverage(domain: str, write_tools: set[str]) -> dict[str, Any]:
    """Coverage report: which domain write tools have a schema (plan §4.3)."""
    covered = {s.action_name for s in rich_schemas(domain)}
    return {
        "domain": domain,
        "n_write_tools": len(write_tools),
        "n_covered": len(covered & write_tools),
        "covered": sorted(covered & write_tools),
        "uncovered": sorted(write_tools - covered),
        "coverage_rate": (len(covered & write_tools) / len(write_tools)
                          if write_tools else None),
    }
