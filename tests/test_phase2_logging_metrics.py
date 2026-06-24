"""Phase-2 logging + metrics unit tests (plan §3.2 required categories).

Covers:
  1. token aggregation
  2. event schema validation
  3. trajectory canonicalization (+ edit distance / first divergence)
  4. safety metric zero-denominator (NA, not 0)
  5. evidence-valid computation
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from ravel_core import metrics as M
from ravel_core.event_logger import (
    Phase2EventLogger, make_event, validate_event, normalize_mas_trace,
    read_events, EVENT_TYPES, AGENT_ROLES,
)


# --- helpers ----------------------------------------------------------------

def _llm(idx, **kw):
    e = make_event("llm_call", "tool_worker", event_index=idx, trial_id="t",
                   domain="airline", task_id="0", method="RAVEL", regime="FullSync",
                   model="g4", seed=0)
    e.update(kw)
    return e


def _tool(idx, name, args):
    e = make_event("tool_call", "tool_worker", event_index=idx, trial_id="t",
                   domain="airline", task_id="0", method="RAVEL", regime="FullSync",
                   model="g4", seed=0, tool_name=name, tool_args=args)
    return e


# --- 1. token aggregation ---------------------------------------------------

def test_token_aggregation_sums_only_llm_calls():
    events = [
        _llm(0, input_tokens=100, output_tokens=10, uncached_input_tokens=80),
        _llm(1, input_tokens=200, output_tokens=20, uncached_input_tokens=50),
        _tool(2, "get_reservation", {"id": "R1"}),  # not an llm_call -> ignored
    ]
    agg = M.aggregate_token_usage(events)
    assert agg["total_input_tokens"] == 300
    assert agg["total_output_tokens"] == 30
    assert agg["uncached_input_tokens"] == 130
    assert agg["total_tokens"] == 330


def test_token_record_uncached_never_negative():
    tr = M.aggregate_token_usage([_llm(0, input_tokens=0, output_tokens=0,
                                       uncached_input_tokens=0)])
    assert tr["uncached_input_tokens"] == 0


# --- 2. event schema validation ---------------------------------------------

def test_valid_event_passes():
    e = _llm(0)
    assert validate_event(e) == []


def test_missing_header_is_flagged():
    e = make_event("llm_call", "tool_worker")  # no trial_id/seed/etc.
    errs = validate_event(e)
    assert any("required header" in x for x in errs)


def test_unknown_event_type_and_role_flagged():
    e = _llm(0)
    e["event_type"] = "telepathy"
    e["agent_role"] = "wizard"
    errs = validate_event(e)
    assert any("event_type" in x for x in errs)
    assert any("agent_role" in x for x in errs)


def test_chain_of_thought_key_rejected():
    e = _llm(0)
    e["chain_of_thought"] = "secret reasoning"
    errs = validate_event(e)
    assert any("chain-of-thought" in x for x in errs)


def test_uncached_gt_input_flagged():
    e = _llm(0, input_tokens=10, uncached_input_tokens=99)
    errs = validate_event(e)
    assert any("uncached" in x for x in errs)


def test_logger_writes_and_validates(tmp_path):
    log = Phase2EventLogger(trial_id="t", domain="airline", task_id="0",
                            method="RAVEL", regime="FullSync", model="g4",
                            seed=0, output_path=tmp_path / "t.jsonl")
    log.log("llm_call", "supervisor", input_tokens=5, output_tokens=1)
    log.log("tool_call", "tool_worker", tool_name="get_reservation",
            tool_args={"id": "R1"})
    rows = list(read_events(tmp_path / "t.jsonl"))
    assert len(rows) == 2
    assert rows[0]["event_index"] == 0 and rows[1]["event_index"] == 1
    assert all(validate_event(r) == [] for r in rows)


def test_logger_rejects_bad_event(tmp_path):
    log = Phase2EventLogger(trial_id="t", domain="airline", task_id="0",
                            method="RAVEL", regime="FullSync", model="g4",
                            seed=0, output_path=tmp_path / "t.jsonl")
    with pytest.raises(ValueError):
        log.log("not_a_real_type", "tool_worker")


def test_normalize_mas_trace_maps_kind(tmp_path):
    legacy = [
        {"kind": "llm_call", "agent_id": "supervisor", "input_tokens": 10,
         "output_tokens": 2, "task_id": "0"},
        {"kind": "commit", "agent_id": "tool_worker",
         "candidate_write": {"action": "cancel_reservation",
                             "arguments": {"reservation_id": "R1"}}},
        {"kind": "env", "agent_id": "tool_worker", "object_id": "reservation:R1"},
    ]
    header = {"trial_id": "t", "domain": "airline", "task_id": "0",
              "method": "RAVEL", "regime": "Delayed", "model": "g4", "seed": 0}
    norm = normalize_mas_trace(legacy, header=header)
    assert [e["event_type"] for e in norm] == ["llm_call", "commit", "ledger_ingest"]
    assert all(e["event_type"] in EVENT_TYPES for e in norm)
    assert all(e["agent_role"] in AGENT_ROLES for e in norm)
    assert all(validate_event(e) == [] for e in norm)


# --- 3. trajectory canonicalization -----------------------------------------

def test_normalize_args_abstracts_ids():
    a = M.normalize_args({"reservation_id": "R1234", "cabin": "economy"})
    b = M.normalize_args({"reservation_id": "R9999", "cabin": "economy"})
    assert a == b  # ids abstracted -> equal signature
    c = M.normalize_args({"reservation_id": "R1234", "cabin": "business"})
    assert a != c  # non-id field differs -> distinct


def test_canonical_tool_sequence_and_edit_distance():
    events = [
        _llm(0),
        _tool(1, "get_reservation", {"id": "R1"}),
        _tool(2, "get_flight", {"flight": "F2"}),
        make_event("commit", "tool_worker", event_index=3, trial_id="t",
                   domain="airline", task_id="0", method="RAVEL", regime="FullSync",
                   model="g4", seed=0,
                   candidate_write={"action": "cancel_reservation",
                                    "arguments": {"reservation_id": "R1"}}),
    ]
    seq = M.canonical_tool_sequence(events)
    assert [t for t, _ in seq] == ["get_reservation", "get_flight", "cancel_reservation"]
    # identical sequence -> distance 0, no divergence
    assert M.sequence_edit_distance(seq, seq) == 0
    assert M.first_divergence_step(seq, seq) is None


def test_first_divergence_and_accuracy():
    ref = [("a", "{}"), ("b", "{}"), ("c", "{}")]
    seq = [("a", "{}"), ("x", "{}"), ("c", "{}")]
    assert M.first_divergence_step(seq, ref) == 1
    assert M.sequence_edit_distance(seq, ref) == 1
    assert M.tool_selection_accuracy(seq, ref) == pytest.approx(2 / 3)
    # dependency order: LCS of [a,x,c] vs [a,b,c] = [a,c] = 2 / 3
    assert M.dependency_order_satisfaction(seq, ref) == pytest.approx(2 / 3)


def test_loop_and_retry_counts():
    seq = [("a", "{}"), ("a", "{}"), ("b", "{}"), ("a", "{}")]
    assert M.loop_count(seq) == 1          # one back-to-back repeat
    assert M.unnecessary_retry_count(seq) == 2  # second & fourth 'a' are retries


def test_trajectory_metrics_na_when_no_reference():
    seq = [("a", "{}")]
    tm = M.trajectory_metrics(seq, None)
    assert tm["trajectory_edit_distance_to_fullsync"] is None
    assert tm["first_divergence_step"] is None
    assert tm["loop_count"] == 0  # still computed without a reference


# --- 4. safety metric zero-denominator --------------------------------------

def test_safety_zero_denominator_returns_none():
    summary = {"executed_writes": [], "oracle_safety_verdicts": [],
               "trial_outcome": {}}
    s = M.derive_safety_metrics(summary)
    assert s["evidence_valid_rate"] is None
    assert s["unsafe_action_rate"] is None
    assert s["conflicting_write_catch_rate"] is None
    assert s["recovery_rate"] is None
    assert s["overblock_rate"] is None


def test_accumulator_zero_denominator_none():
    acc = M.SafetyMetricsAccumulator()
    assert acc.evidence_valid_rate() is None
    assert acc.overblock_rate() is None


# --- 5. evidence-valid computation ------------------------------------------

def test_evidence_valid_and_unsafe_rates():
    summary = {
        "executed_writes": [
            {"evidence_valid": True, "was_stale": False, "was_conflicting": False},
            {"evidence_valid": False, "was_stale": True, "was_conflicting": False},
            {"evidence_valid": False, "was_stale": False, "was_conflicting": True},
            {"evidence_valid": True, "was_stale": False, "was_conflicting": False},
        ],
        "oracle_safety_verdicts": [],
        "trial_outcome": {},
    }
    s = M.derive_safety_metrics(summary)
    assert s["evidence_valid_rate"] == pytest.approx(0.5)
    assert s["unsafe_action_rate"] == pytest.approx(0.5)
    assert s["stale_action_rate"] == pytest.approx(0.25)
    assert s["conflicting_write_rate"] == pytest.approx(0.25)


def test_caught_conflict_and_recovery_and_overblock():
    summary = {
        "executed_writes": [],
        "oracle_safety_verdicts": [
            {"oracle_conflicting": True, "ravel_caught": True, "blocked": True,
             "oracle_safe_necessary": False},
            {"oracle_conflicting": True, "ravel_caught": False, "blocked": False,
             "oracle_safe_necessary": False},
            {"oracle_conflicting": False, "ravel_caught": False, "blocked": True,
             "oracle_safe_necessary": True},  # overblocked safe write
        ],
        "trial_outcome": {"initially_invalid": True, "recovered": True},
    }
    s = M.derive_safety_metrics(summary)
    assert s["conflicting_write_catch_rate"] == pytest.approx(0.5)  # 1 of 2
    assert s["recovery_rate"] == pytest.approx(1.0)
    assert s["overblock_rate"] == pytest.approx(1 / 2)  # 1 safe-blocked of 2 blocked
