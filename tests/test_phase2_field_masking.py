"""Phase-2 deterministic field-masking regime tests (plan §5.2)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from ravel_core import field_masking as FM
from ravel_core.dependency_router import build_dependency_graph

FIELDS = ["status", "cabin", "history", "marketing_blurb", "noise"]


def _graph():
    # status/cabin are action-critical (airline schemas); history supporting
    return build_dependency_graph("airline", supporting_fields=[("reservation", "history")])


def test_random_mask_is_deterministic_for_seed():
    g = _graph()
    a = FM.fields_to_mask("FieldMaskRandom_20", object_ref="reservation",
                          object_id="reservation:R1", fields=FIELDS, graph=g, seed=7)
    b = FM.fields_to_mask("FieldMaskRandom_20", object_ref="reservation",
                          object_id="reservation:R1", fields=FIELDS, graph=g, seed=7)
    assert a == b  # reproducible
    c = FM.fields_to_mask("FieldMaskRandom_20", object_ref="reservation",
                          object_id="reservation:R1", fields=FIELDS, graph=g, seed=8)
    # different seed usually differs (not asserted strictly, but rate is fixed)
    assert len(a) == round(0.20 * len(FIELDS))
    assert len(c) == round(0.20 * len(FIELDS))


def test_mask_action_critical_only_targets_must_keep():
    g = _graph()
    masked = FM.fields_to_mask("MaskActionCriticalOnly", object_ref="reservation",
                               object_id="reservation:R1", fields=FIELDS, graph=g, seed=0)
    assert "status" in masked and "cabin" in masked
    assert "noise" not in masked


def test_dependency_preserving_never_masks_critical():
    g = _graph()
    masked = FM.fields_to_mask("DependencyPreservingMask", object_ref="reservation",
                               object_id="reservation:R1", fields=FIELDS, graph=g, seed=0)
    assert "status" not in masked and "cabin" not in masked
    assert "marketing_blurb" in masked  # non-critical masked


def test_mask_irrelevant_only_keeps_critical_and_supporting():
    g = _graph()
    masked = FM.fields_to_mask("MaskIrrelevantOnly", object_ref="reservation",
                               object_id="reservation:R1", fields=FIELDS, graph=g, seed=0)
    assert "status" not in masked and "cabin" not in masked
    assert "history" not in masked  # supporting kept
    assert "marketing_blurb" in masked or "noise" in masked


def test_apply_mask_and_rate():
    fields = {f: f"val_{f}" for f in FIELDS}
    masked = {"noise", "marketing_blurb"}
    out = FM.apply_mask(fields, masked)
    assert "noise" not in out and "status" in out
    assert FM.mask_rate(fields, masked) == pytest.approx(2 / 5)


def test_mask_rate_none_when_no_fields():
    assert FM.mask_rate({}, set()) is None


def test_unknown_regime_raises():
    g = _graph()
    with pytest.raises(ValueError):
        FM.fields_to_mask("Telepathy", object_ref="reservation",
                          object_id="reservation:R1", fields=FIELDS, graph=g, seed=0)
