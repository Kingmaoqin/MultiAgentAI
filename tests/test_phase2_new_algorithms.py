"""Phase-2 new-algorithm tests: CSI (§6), Evidence Uptake + DPR (§7)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from ravel_core import conflict_signal as CSI
from ravel_core import evidence_uptake as EU
from ravel_core import dependency_router as DPR


# ===================== CSI (§6) =====================

def test_csi_never_surfaces_fake_value():
    sig = CSI.build_conflict_signal(
        field="status", current_value="processed", current_version=2,
        seen_version=1, seen_value="pending")
    # confirmed conflict because observed value differs from current
    assert sig.conflict_status == CSI.CONFIRMED_CONFLICT
    for variant in CSI.CSI_VARIANTS:
        view = CSI.render_signal(sig, variant)
        # every variant exposes the RELIABLE current value, never the stale one
        assert view["current_value"] == "processed"
        if variant != "DualVersion":
            assert "seen_value" not in view


def test_csi_dualversion_exposes_both_versions():
    sig = CSI.build_conflict_signal(
        field="status", current_value="processed", current_version=3,
        seen_version=1, seen_value="pending")
    view = CSI.render_signal(sig, "DualVersion")
    assert view["current_value"] == "processed"
    assert view["seen_value"] == "pending"
    assert view["seen_version"] == 1


def test_csi_stale_view_when_value_same_but_version_behind():
    sig = CSI.build_conflict_signal(
        field="status", current_value="pending", current_version=2,
        seen_version=1, seen_value="pending")
    assert sig.conflict_status == CSI.STALE_VIEW
    assert CSI.requires_preflight(sig)


def test_csi_no_conflict_when_fresh():
    sig = CSI.build_conflict_signal(
        field="status", current_value="pending", current_version=1,
        seen_version=1, seen_value="pending")
    assert sig.conflict_status == CSI.NONE
    assert not CSI.requires_preflight(sig)


def test_csi_unseen_field_is_possible_conflict():
    sig = CSI.build_conflict_signal(
        field="status", current_value="pending", current_version=1,
        seen_version=None)
    assert sig.conflict_status == CSI.POSSIBLE_CONFLICT
    assert sig.recommended_resolution == CSI.RES_FETCH_LATEST
    assert CSI.requires_preflight(sig)


def test_csi_gatepreflight_forces_recheck():
    sig = CSI.build_conflict_signal(
        field="status", current_value="pending", current_version=1,
        seen_version=1, seen_value="pending")  # otherwise NONE / no recheck
    view = CSI.render_signal(sig, "GatePreflight")
    assert view["write_precondition"] == CSI.PRE_RECHECK


def test_csi_unknown_variant_raises():
    sig = CSI.build_conflict_signal(field="s", current_value=1, current_version=1,
                                    seen_version=1, seen_value=1)
    with pytest.raises(ValueError):
        CSI.render_signal(sig, "Telepathy")


# ===================== Evidence Uptake (§7.1) =====================

def _ev(eid, obj, field, value, version=1, stale=False, conflict=False):
    return EU.VisibleEvidence(evidence_id=eid, object_id=obj, field=field,
                              value=value, version=version, is_stale=stale,
                              conflict_flagged=conflict)


def test_uptake_used_seen_evidence():
    rec = EU.attribute(
        candidate_action="cancel_pending_order",
        arguments={"status": "pending"},
        visible=[_ev("ev1", "order:O1", "status", "pending")],
        required_fields=[("order:O1", "status")],
    )
    assert rec.uptake_status == EU.USED_SEEN
    assert rec.argument_source["status"] == "ev1"
    assert rec.uptake_failure_type is None


def test_uptake_hallucinated_argument():
    rec = EU.attribute(
        candidate_action="cancel_pending_order",
        arguments={"status": "delivered"},  # not in visible evidence
        visible=[_ev("ev1", "order:O1", "status", "pending")],
        required_fields=[("order:O1", "status")],
    )
    assert rec.argument_source["status"] == EU.HALLUCINATED
    assert rec.uptake_status == EU.HALLUCINATED


def test_uptake_stale_evidence_use():
    rec = EU.attribute(
        candidate_action="cancel_pending_order",
        arguments={"status": "pending"},
        visible=[_ev("ev1", "order:O1", "status", "pending", stale=True)],
        required_fields=[("order:O1", "status")],
    )
    assert rec.uptake_status == EU.USED_STALE
    assert rec.argument_source["status"] == "stale_memory"


def test_uptake_metrics_zero_denominator_none():
    acc = EU.UptakeAccumulator()
    m = acc.metrics()
    assert m["SeenButUnusedRate"] is None
    assert m["EvidenceToActionCoverage"] is None
    assert m["CorrectionSensitivity"] is None


def test_uptake_coverage_and_unsupported_rate():
    acc = EU.UptakeAccumulator()
    acc.add(EU.attribute(candidate_action="a", arguments={"x": "v1"},
                         visible=[_ev("e1", "o", "x", "v1")],
                         required_fields=[("o", "x")]))
    acc.add(EU.attribute(candidate_action="a", arguments={"x": "ghost"},
                         visible=[_ev("e1", "o", "x", "v1")],
                         required_fields=[("o", "x")]))
    m = acc.metrics()
    assert m["EvidenceToActionCoverage"] == pytest.approx(0.5)  # 1 of 2 args traceable
    assert m["UnsupportedArgumentRate"] == pytest.approx(0.5)   # 1 of 2 actions
    assert m["n_candidate_actions"] == 2


def test_correction_sensitivity_probe():
    acc = EU.UptakeAccumulator()
    acc.record_correction_probe(changed_action=True)
    acc.record_correction_probe(changed_action=False)
    assert acc.metrics()["CorrectionSensitivity"] == pytest.approx(0.5)


# ===================== Dependency-Preserving Router (§7.2) =====================

def test_dpr_keeps_action_critical_fields():
    g = DPR.build_dependency_graph("retail")
    # order.status is a precondition for cancel/return/modify -> must_keep
    assert DPR.classify_field(g, "order", "status") == DPR.MUST_KEEP


def test_dpr_compresses_unknown_and_drops_listed():
    g = DPR.build_dependency_graph("retail", supporting_fields=[("order", "history")])
    assert DPR.classify_field(g, "order", "history") == DPR.SHOULD_KEEP
    assert DPR.classify_field(g, "order", "marketing_blurb") == DPR.COMPRESSIBLE
    assert DPR.classify_field(g, "order", "noise",
                              droppable_fields={"noise"}) == DPR.DROPPABLE


def test_dpr_route_view_shapes_and_savings():
    g = DPR.build_dependency_graph("retail", supporting_fields=[("order", "history")])
    full = {"status": "pending", "history": [1, 2, 3],
            "marketing_blurb": "buy more!", "noise": "x" * 2000}
    view = DPR.route_evidence(
        g, object_ref="order", object_id="order:O1", version=2,
        source_tool="get_order_details", fields=full, droppable_fields={"noise"})
    assert view["fields"]["status"]["value"] == "pending"      # must_keep full
    assert "digest" in view["fields"]["status"]
    assert view["fields"]["history"]["value"] == [1, 2, 3]     # should_keep
    assert view["fields"]["marketing_blurb"]["summary"] is True  # compressible
    assert "noise" not in view["fields"]                       # droppable
    assert any("noise" in p for p in view["dropped_pointers"])
    sav = DPR.routing_token_savings(full, view)
    assert sav["reduction"] is not None and sav["reduction"] > 0  # routed is smaller


def test_dpr_required_read_set_for_high_risk_write():
    rs = DPR.required_read_set("airline", "cancel_reservation")
    assert ("reservation", "status") in rs
    assert ("reservation", "cabin") in rs
