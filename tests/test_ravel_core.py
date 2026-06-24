import pytest

from ravel_core import (
    ActionSchema,
    CandidateWrite,
    CommitGate,
    EvidenceLedger,
    RequiredEvidence,
    VisibilityPolicy,
    VisibleEvidenceState,
    canonical_json,
    flatten_fields,
)


def test_canonicalization_is_deterministic():
    left = {"b": 2, "a": {"y": 1, "x": [3, 2]}}
    right = {"a": {"x": [3, 2], "y": 1}, "b": 2}
    assert canonical_json(left) == canonical_json(right)


def test_flatten_fields_nested_payload():
    payload = {"reservation": {"id": "R1", "status": "open"}, "price": 10}
    assert flatten_fields(payload) == {
        "price": 10,
        "reservation.id": "R1",
        "reservation.status": "open",
    }


def test_ledger_versions_and_changed_fields():
    ledger = EvidenceLedger()
    first = ledger.ingest(
        object_id="reservation:R1",
        tool_name="get_reservation_details",
        payload={"status": "open", "seat": "12A"},
        source_agent="retriever",
    )
    second = ledger.ingest(
        object_id="reservation:R1",
        tool_name="get_reservation_details",
        payload={"status": "cancelled", "seat": "12A"},
        source_agent="retriever",
    )

    assert first.version == 1
    assert second.version == 2
    assert second.changed_fields == ("status",)
    assert ledger.latest_field("reservation:R1", "status")[0] == 2


def test_fullsync_view_exposes_all_fields():
    ledger = EvidenceLedger()
    record = ledger.ingest(
        object_id="order:O1",
        tool_name="get_order_details",
        payload={"status": "delivered", "total": 25},
        source_agent="worker",
    )
    view = VisibilityPolicy("FullSync").project(
        record, agent_id="executor", event_index=record.logical_clock
    )
    assert view.visible_fields == {"status": "delivered", "total": 25}
    assert view.projection_type == "raw"


def test_delayed_view_hides_fields_until_release():
    ledger = EvidenceLedger()
    record = ledger.ingest(
        object_id="order:O1",
        tool_name="get_order_details",
        payload={"status": "delivered"},
        source_agent="retriever",
    )
    policy = VisibilityPolicy("Delayed", delay=2)
    early = policy.project(record, agent_id="executor", event_index=record.logical_clock)
    late = policy.project(
        record, agent_id="executor", event_index=record.logical_clock + 2
    )

    assert early.visible_fields == {}
    assert early.projection_type == "pointer"
    assert late.visible_fields == {"status": "delivered"}


def test_field_mask_only_changes_view_not_ledger():
    ledger = EvidenceLedger()
    record = ledger.ingest(
        object_id="order:O1",
        tool_name="get_order_details",
        payload={"status": "delivered", "total": 25},
        source_agent="retriever",
    )
    policy = VisibilityPolicy("FieldMask", mask_fields={"total"})
    view = policy.project(record, agent_id="executor", event_index=record.logical_clock)

    assert "total" not in view.visible_fields
    assert record.field_values["total"] == 25
    assert any(reason == "masked:total" for reason in view.reason_codes)


def test_conflicting_view_does_not_mutate_ledger():
    ledger = EvidenceLedger()
    record = ledger.ingest(
        object_id="order:O1",
        tool_name="get_order_details",
        payload={"status": "delivered", "total": 25},
        source_agent="retriever",
    )
    policy = VisibilityPolicy("ConflictingView", conflict_fields={"status"})
    view = policy.project(record, agent_id="executor", event_index=record.logical_clock)

    assert view.visible_fields["status"] == "CONFLICT::delivered"
    assert view.conflict_fields == ("status",)
    assert record.field_values["status"] == "delivered"


def test_view_mutation_cannot_mutate_ledger_mutable_values():
    ledger = EvidenceLedger()
    record = ledger.ingest(
        object_id="object:1",
        tool_name="get_object",
        payload={"empty": [], "nested": {"items": []}},
        source_agent="retriever",
    )
    view = VisibilityPolicy("FullSync").project(
        record, agent_id="executor", event_index=record.logical_clock
    )

    view.visible_fields["empty"].append("mutated")
    view.visible_fields["nested.items"].append("changed")

    assert record.field_values["empty"] == ()
    assert record.field_values["nested.items"] == ()


def test_record_field_mapping_is_immutable():
    ledger = EvidenceLedger()
    record = ledger.ingest(
        object_id="object:1",
        tool_name="get_object",
        payload={"status": "open"},
        source_agent="retriever",
    )

    with pytest.raises(TypeError):
        record.field_values["status"] = "closed"


def _schema_gate():
    schema = ActionSchema(
        action="cancel_reservation",
        required_fields=(
            RequiredEvidence("reservation:R1", "status"),
            RequiredEvidence("reservation:R1", "reservation_id"),
        ),
    )
    return CommitGate({"cancel_reservation": schema})


def test_commit_gate_allows_complete_fresh_traceable_write():
    ledger = EvidenceLedger()
    record = ledger.ingest(
        object_id="reservation:R1",
        tool_name="get_reservation_details",
        payload={"reservation_id": "R1", "status": "open", "irrelevant": "x"},
        source_agent="retriever",
    )
    view = VisibilityPolicy("FullSync").project(
        record, agent_id="executor", event_index=record.logical_clock
    )
    candidate = CandidateWrite(
        action="cancel_reservation",
        arguments={"reservation_id": "R1"},
        target_objects=("reservation:R1",),
        referenced_evidence_ids=(record.evidence_id,),
    )

    decision = _schema_gate().verify(
        candidate,
        ledger=ledger,
        visible_state=VisibleEvidenceState.from_views([view]),
    )
    assert decision.allowed
    assert decision.reasons == ("evidence_valid",)


def test_commit_gate_checks_schema_fields_not_global_ledger_fields():
    ledger = EvidenceLedger()
    reservation = ledger.ingest(
        object_id="reservation:R1",
        tool_name="get_reservation_details",
        payload={"reservation_id": "R1", "status": "open"},
        source_agent="retriever",
    )
    other = ledger.ingest(
        object_id="flight:F1",
        tool_name="get_flight_status",
        payload={"delay": "conflicting"},
        source_agent="retriever",
    )
    reservation_view = VisibilityPolicy("FullSync").project(
        reservation, agent_id="executor", event_index=ledger.logical_clock
    )
    other_view = VisibilityPolicy("ConflictingView", conflict_fields={"delay"}).project(
        other, agent_id="executor", event_index=ledger.logical_clock
    )
    candidate = CandidateWrite(
        action="cancel_reservation",
        arguments={"reservation_id": "R1"},
        target_objects=("reservation:R1",),
        referenced_evidence_ids=(reservation.evidence_id,),
    )

    decision = _schema_gate().verify(
        candidate,
        ledger=ledger,
        visible_state=VisibleEvidenceState.from_views([reservation_view, other_view]),
    )
    assert decision.allowed


def test_commit_gate_detects_stale_required_evidence():
    ledger = EvidenceLedger()
    old = ledger.ingest(
        object_id="reservation:R1",
        tool_name="get_reservation_details",
        payload={"reservation_id": "R1", "status": "open"},
        source_agent="retriever",
    )
    old_view = VisibilityPolicy("FullSync").project(
        old, agent_id="executor", event_index=old.logical_clock
    )
    ledger.ingest(
        object_id="reservation:R1",
        tool_name="get_reservation_details",
        payload={"reservation_id": "R1", "status": "cancelled"},
        source_agent="retriever",
    )
    candidate = CandidateWrite(
        action="cancel_reservation",
        arguments={"reservation_id": "R1"},
        target_objects=("reservation:R1",),
        referenced_evidence_ids=(old.evidence_id,),
    )

    decision = _schema_gate().verify(
        candidate,
        ledger=ledger,
        visible_state=VisibleEvidenceState.from_views([old_view]),
    )
    assert decision.verdict == "reconcile"
    assert decision.stale_fields


def test_visible_state_keeps_version_and_evidence_id_paired_out_of_order():
    ledger = EvidenceLedger()
    old = ledger.ingest(
        object_id="reservation:R1",
        tool_name="get_reservation_details",
        payload={"reservation_id": "R1", "status": "open"},
        source_agent="retriever",
    )
    new = ledger.ingest(
        object_id="reservation:R1",
        tool_name="get_reservation_details",
        payload={"reservation_id": "R1", "status": "cancelled"},
        source_agent="retriever",
    )
    new_view = VisibilityPolicy("FullSync").project(
        new, agent_id="executor", event_index=ledger.logical_clock
    )
    old_view = VisibilityPolicy("FullSync").project(
        old, agent_id="executor", event_index=ledger.logical_clock
    )
    state = VisibleEvidenceState.from_views([new_view, old_view])
    key = ("reservation:R1", "status")

    assert state.versions[key] == new.version
    assert state.evidence_ids[key] == new.evidence_id

    candidate = CandidateWrite(
        action="cancel_reservation",
        arguments={"reservation_id": "R1"},
        target_objects=("reservation:R1",),
        referenced_evidence_ids=(old.evidence_id,),
    )
    decision = _schema_gate().verify(candidate, ledger=ledger, visible_state=state)
    assert decision.verdict == "replan"
    assert RequiredEvidence("reservation:R1", "status") in decision.untraceable_fields


def test_commit_gate_detects_conflicting_required_evidence():
    ledger = EvidenceLedger()
    record = ledger.ingest(
        object_id="reservation:R1",
        tool_name="get_reservation_details",
        payload={"reservation_id": "R1", "status": "open"},
        source_agent="retriever",
    )
    view = VisibilityPolicy("ConflictingView", conflict_fields={"status"}).project(
        record, agent_id="executor", event_index=record.logical_clock
    )
    candidate = CandidateWrite(
        action="cancel_reservation",
        arguments={"reservation_id": "R1"},
        target_objects=("reservation:R1",),
        referenced_evidence_ids=(record.evidence_id,),
    )

    decision = _schema_gate().verify(
        candidate,
        ledger=ledger,
        visible_state=VisibleEvidenceState.from_views([view]),
    )
    assert decision.verdict == "reconcile"
    assert decision.conflicting_fields == (RequiredEvidence("reservation:R1", "status"),)


def test_commit_gate_detects_missing_required_evidence():
    ledger = EvidenceLedger()
    record = ledger.ingest(
        object_id="reservation:R1",
        tool_name="get_reservation_details",
        payload={"reservation_id": "R1"},
        source_agent="retriever",
    )
    view = VisibilityPolicy("FullSync").project(
        record, agent_id="executor", event_index=record.logical_clock
    )
    candidate = CandidateWrite(
        action="cancel_reservation",
        arguments={"reservation_id": "R1"},
        target_objects=("reservation:R1",),
        referenced_evidence_ids=(record.evidence_id,),
    )

    decision = _schema_gate().verify(
        candidate,
        ledger=ledger,
        visible_state=VisibleEvidenceState.from_views([view]),
    )
    assert decision.verdict == "reconcile"
    assert RequiredEvidence("reservation:R1", "status") in decision.missing_fields
    assert "missing_required_evidence" in decision.reasons


def test_commit_gate_requires_traceability():
    ledger = EvidenceLedger()
    record = ledger.ingest(
        object_id="reservation:R1",
        tool_name="get_reservation_details",
        payload={"reservation_id": "R1", "status": "open"},
        source_agent="retriever",
    )
    view = VisibilityPolicy("FullSync").project(
        record, agent_id="executor", event_index=record.logical_clock
    )
    candidate = CandidateWrite(
        action="cancel_reservation",
        arguments={"reservation_id": "R1"},
        target_objects=("reservation:R1",),
        referenced_evidence_ids=(),
    )

    decision = _schema_gate().verify(
        candidate,
        ledger=ledger,
        visible_state=VisibleEvidenceState.from_views([view]),
    )
    assert decision.verdict == "replan"
    assert decision.untraceable_fields


# ---------------------------------------------------------------------------
# Permissive mode (empty schemas)
# ---------------------------------------------------------------------------

def test_commit_gate_permissive_allows_all_writes():
    """CommitGate with no schemas must be permissive (commit everything)."""
    from ravel_core.evidence import EvidenceLedger
    from ravel_core.commit_gate import (
        CommitGate, CandidateWrite, VisibleEvidenceState,
    )
    gate = CommitGate(schemas={}, permissive=True)
    ledger = EvidenceLedger()
    candidate = CandidateWrite(
        action="any_write_tool",
        arguments={"order_id": "O1"},
        target_objects=("order:O1",),
        referenced_evidence_ids=(),
    )
    decision = gate.verify(
        candidate,
        ledger=ledger,
        visible_state=VisibleEvidenceState(),
    )
    assert decision.allowed, f"Permissive gate must commit, got: {decision.verdict!r}"
    assert "permissive_mode" in decision.reasons


def test_commit_gate_strict_blocks_unknown_action():
    """CommitGate with at least one schema must abstain on unknown actions."""
    from ravel_core.evidence import EvidenceLedger
    from ravel_core.commit_gate import (
        ActionSchema, CommitGate, CandidateWrite, VisibleEvidenceState,
    )
    gate = CommitGate(schemas={"known_action": ActionSchema("known_action", ())})
    ledger = EvidenceLedger()
    candidate = CandidateWrite(
        action="unknown_write",
        arguments={},
        target_objects=(),
        referenced_evidence_ids=(),
    )
    decision = gate.verify(
        candidate,
        ledger=ledger,
        visible_state=VisibleEvidenceState(),
    )
    assert decision.verdict == "abstain"
