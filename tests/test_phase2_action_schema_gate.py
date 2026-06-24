"""Phase-2 ActionSchema + non-permissive CommitGate tests (plan §4)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from ravel_core.action_schemas import (
    build_action_schemas, high_risk_actions, rich_schemas, schema_coverage,
)
from ravel_core.commit_gate import (
    CommitGate, CandidateWrite, VisibleEvidenceState, RequiredEvidence, ActionSchema,
)
from ravel_core.evidence import EvidenceLedger

AIRLINE_WRITE_TOOLS = {
    "update_reservation_passengers", "update_reservation_baggages",
    "book_reservation", "cancel_reservation", "update_reservation_flights",
    "send_certificate",
}
RETAIL_WRITE_TOOLS = {
    "return_delivered_order_items", "exchange_delivered_order_items",
    "cancel_pending_order", "modify_pending_order_items",
    "modify_pending_order_payment", "modify_pending_order_address",
}


# --- registry / coverage ----------------------------------------------------

def test_airline_retail_main_write_tools_covered():
    cov_a = schema_coverage("airline", AIRLINE_WRITE_TOOLS)
    cov_r = schema_coverage("retail", RETAIL_WRITE_TOOLS)
    # plan §4.1: cover the MAIN high-risk write tools (here: all 6 each)
    assert cov_a["uncovered"] == []
    assert cov_r["uncovered"] == []
    assert cov_a["coverage_rate"] == 1.0
    assert cov_r["coverage_rate"] == 1.0


def test_high_risk_actions_nonempty_and_have_required_fields():
    hr = high_risk_actions("airline")
    assert "cancel_reservation" in hr
    for s in rich_schemas("airline"):
        assert s.required_fields, f"{s.action_name} must declare required fields"
        assert s.risk_level in ("low", "medium", "high")


def test_build_action_schemas_projects_required_evidence():
    schemas = build_action_schemas("retail", target_object_id="order:O42")
    s = schemas["cancel_pending_order"]
    assert isinstance(s, ActionSchema)
    assert s.risk_level == "high"
    assert any(r.object_id == "order:O42" and r.field == "status"
               for r in s.required_fields)


# --- non-permissive gate (§4.2) ---------------------------------------------

def test_high_risk_missing_schema_abstains_not_commits():
    """Fail-closed default: an unschemaed high-risk write must NOT commit."""
    gate = CommitGate(schemas={})  # permissive defaults False, high_risk None=fail-closed
    d = gate.verify(
        CandidateWrite(action="cancel_reservation", arguments={},
                       target_objects=("reservation:R1",), referenced_evidence_ids=()),
        ledger=EvidenceLedger(), visible_state=VisibleEvidenceState(),
    )
    assert d.verdict == "abstain"
    assert d.schema_missing is True
    assert "schema_missing" in d.reasons


def test_permissive_dev_mode_commits_without_schema():
    gate = CommitGate(schemas={}, permissive=True)
    d = gate.verify(
        CandidateWrite(action="cancel_reservation", arguments={},
                       target_objects=("reservation:R1",), referenced_evidence_ids=()),
        ledger=EvidenceLedger(), visible_state=VisibleEvidenceState(),
    )
    assert d.allowed
    assert "permissive_mode" in d.reasons


def test_explicit_low_risk_action_commits_without_schema():
    gate = CommitGate(schemas={}, high_risk_actions={"cancel_reservation"})
    d = gate.verify(
        CandidateWrite(action="some_low_risk_log_event", arguments={},
                       target_objects=(), referenced_evidence_ids=()),
        ledger=EvidenceLedger(), visible_state=VisibleEvidenceState(),
    )
    assert d.allowed
    assert "low_risk_no_schema" in d.reasons


def test_gate_with_real_schema_blocks_stale_evidence():
    """With a real schema enabled, a write on stale evidence is caught."""
    schemas = build_action_schemas("retail", target_object_id="order:O1")
    gate = CommitGate(schemas, high_risk_actions=high_risk_actions("retail"))
    led = EvidenceLedger()
    r_old = led.ingest(object_id="order:O1", tool_name="get_order_details",
                       payload={"status": "pending"}, source_agent="worker")
    old_v, _, old_ev = led.latest_field("order:O1", "status")
    # ledger advanced to v2 (exogenous update) but the agent only saw v1
    led.ingest(object_id="order:O1", tool_name="get_order_details",
               payload={"status": "processed"}, source_agent="env")
    visible = VisibleEvidenceState(
        versions={("order:O1", "status"): old_v},
        evidence_ids={("order:O1", "status"): old_ev},
    )
    d = gate.verify(
        CandidateWrite(action="cancel_pending_order", arguments={},
                       target_objects=("order:O1",),
                       referenced_evidence_ids=(old_ev,)),
        ledger=led, visible_state=visible,
    )
    assert not d.allowed
    assert d.stale_fields  # status was stale
    assert d.verdict in ("reconcile", "replan")


def test_gate_with_real_schema_commits_fresh_traceable():
    schemas = build_action_schemas("retail", target_object_id="order:O1")
    gate = CommitGate(schemas, high_risk_actions=high_risk_actions("retail"))
    led = EvidenceLedger()
    led.ingest(object_id="order:O1", tool_name="get_order_details",
               payload={"status": "pending"}, source_agent="worker")
    v, _, ev = led.latest_field("order:O1", "status")
    visible = VisibleEvidenceState(
        versions={("order:O1", "status"): v},
        evidence_ids={("order:O1", "status"): ev},
    )
    d = gate.verify(
        CandidateWrite(action="modify_pending_order_address", arguments={},
                       target_objects=("order:O1",),
                       referenced_evidence_ids=(ev,)),
        ledger=led, visible_state=visible,
    )
    assert d.allowed
    assert "evidence_valid" in d.reasons
