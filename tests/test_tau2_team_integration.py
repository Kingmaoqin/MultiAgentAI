"""Phase 5 — RAVELTeamAgent (tau2 wrapper) write-isolation integration test.

Runs only where tau2 is importable (the tau2-clean uv env). Stubs the model so no
real LLM/network is needed. Verifies the wrapper's core guarantees:
  - the ToolWorker tool list excludes real write tools (allowlist)
  - a candidate write REJECTED by CommitService yields NO real write ToolCall
  - a candidate write ACCEPTED by CommitService yields the real write ToolCall
  - a worker read tool call is passed through to tau2 unchanged
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

pytest.importorskip("tau2", reason="tau2 not importable in this env (run under uv)")

import ravel_mas.team_agent as ta
from ravel_mas.team_agent import RAVELTeamAgent, _tool_name
from tau2.data_model.message import AssistantMessage, ToolCall, UserMessage


class _Tool:
    def __init__(self, name):
        self.name = name


AIRLINE_TOOLS = [_Tool("get_reservation_details"), _Tool("cancel_reservation"),
                 _Tool("book_reservation")]


def _agent():
    return RAVELTeamAgent(
        tools=AIRLINE_TOOLS, domain_policy="policy", llm="openai/g4",
        llm_args={}, domain="airline", task_id="t1",
    )


def test_worker_toollist_excludes_real_write_tools():
    a = _agent()
    names = {_tool_name(t) for t in a._read_tools}
    assert "cancel_reservation" not in names
    assert "book_reservation" not in names
    assert "get_reservation_details" in names


def test_rejected_candidate_emits_no_real_write(monkeypatch):
    a = _agent()
    # ledger has reservation status=cancelled; worker claims confirmed → conflict
    a._ledger.ingest(object_id="cancel_reservation:R1", tool_name="get_reservation_details",
                     payload={"reservation_id": "R1", "status": "cancelled"},
                     source_agent="tool_worker")
    cand = ToolCall(id="c1", name="propose_candidate_write", arguments={
        "action": "cancel_reservation",
        "arguments": {"reservation_id": "R1"},
        "target_objects": ["cancel_reservation:R1"],
        "claimed_preconditions": [{"object_id": "cancel_reservation:R1",
                                   "field": "status", "operator": "equals",
                                   "value": "confirmed"}],
        "expected_versions": {"cancel_reservation:R1": 1},
    })
    out = a._verify_candidate(cand, state=None)
    # rejected → text message, NO tool calls (no real write leaks to tau2)
    assert out.tool_calls is None or len(out.tool_calls) == 0


def test_accepted_candidate_emits_real_write(monkeypatch):
    a = _agent()
    a._ledger.ingest(object_id="cancel_reservation:R1", tool_name="get_reservation_details",
                     payload={"reservation_id": "R1", "status": "confirmed"},
                     source_agent="tool_worker")
    cand = ToolCall(id="c1", name="propose_candidate_write", arguments={
        "action": "cancel_reservation",
        "arguments": {"reservation_id": "R1"},
        "target_objects": ["cancel_reservation:R1"],
        "expected_versions": {"cancel_reservation:R1": 1},
    })
    out = a._verify_candidate(cand, state=None)
    # accepted → emits the REAL write tool call (sole write path)
    assert out.tool_calls is not None and len(out.tool_calls) == 1
    assert out.tool_calls[0].name == "cancel_reservation"


def test_worker_read_call_passes_through():
    a = _agent()

    class _Resp:
        def __init__(self):
            self.content = ""
            self.tool_calls = [ToolCall(id="r1", name="get_reservation_details",
                                        arguments={"reservation_id": "R1"})]

        def is_tool_call(self):
            return True

    out = a._handle_worker(_Resp(), state=None)
    assert out.tool_calls is not None
    assert out.tool_calls[0].name == "get_reservation_details"


# --- Regression tests for the corrected (non-circular) safety measurement ---

def _make_write_tc():
    return ToolCall(id="w1", name="propose_candidate_write", arguments={
        "action": "cancel_reservation",
        "arguments": {"reservation_id": "R1"},
        "target_objects": ["cancel_reservation:R1"],
    })


def _seed_stale_object(a):
    """Worker observed v1; ledger advanced to v2 -> oracle-stale."""
    a._ledger.ingest(object_id="cancel_reservation:R1", tool_name="get_reservation_details",
                     payload={"reservation_id": "R1", "status": "confirmed"},
                     source_agent="tool_worker")
    a._worker_seen_version["cancel_reservation:R1"] = 1
    a._ledger.ingest(object_id="cancel_reservation:R1", tool_name="concurrent_update",
                     payload={"reservation_id": "R1", "status": "cancelled"},
                     source_agent="external_process")
    # ledger now at v2, worker saw v1


def test_gate_on_miss_is_counted_non_circular(monkeypatch):
    """If the gate WRONGLY allows an oracle-unsafe write, unsafe_executed must
    increment under gate ON. Proves the metric is not structurally zero."""
    a = _agent()
    a._gate_enabled = True
    _seed_stale_object(a)
    # Force the deterministic gate to ALLOW everything (simulate a gate miss).
    from ravel_mas.commit_service import CommitDecision, AllowedCommitToken
    monkeypatch.setattr(a._commit, "verify",
                        lambda cw: CommitDecision(verdict="commit", reasons=("forced",),
                                                  token=AllowedCommitToken("t", cw.action, {})))
    out = a._verify_candidate(_make_write_tc(), state=None)
    assert out.tool_calls and out.tool_calls[0].name == "cancel_reservation"  # executed
    assert a._safety["oracle_unsafe_attempts"] == 1
    assert a._safety["unsafe_executed"] == 1   # gate-ON miss IS counted


def test_gate_on_catch_records_zero_unsafe_executed():
    """With the real gate, an oracle-stale write is blocked -> unsafe_executed=0,
    and it is NOT an overblock (the write was genuinely unsafe)."""
    a = _agent()
    a._gate_enabled = True
    _seed_stale_object(a)
    out = a._verify_candidate(_make_write_tc(), state=None)
    assert (out.tool_calls is None) or len(out.tool_calls) == 0   # blocked
    assert a._safety["oracle_unsafe_attempts"] == 1
    assert a._safety["unsafe_executed"] == 0
    assert a._safety["overblock"] == 0


def test_gate_off_executes_oracle_unsafe_write():
    a = _agent()
    a._gate_enabled = False
    _seed_stale_object(a)
    out = a._verify_candidate(_make_write_tc(), state=None)
    assert out.tool_calls and out.tool_calls[0].name == "cancel_reservation"
    assert a._safety["unsafe_executed"] == 1   # same oracle, executed under gate OFF


def test_fullsync_safe_write_not_overblocked():
    """No perturbation -> oracle-safe write; real gate should allow it, no overblock."""
    a = _agent()
    a._gate_enabled = True
    a._ledger.ingest(object_id="cancel_reservation:R1", tool_name="get_reservation_details",
                     payload={"reservation_id": "R1", "status": "confirmed"},
                     source_agent="tool_worker")
    a._worker_seen_version["cancel_reservation:R1"] = 1
    out = a._verify_candidate(_make_write_tc(), state=None)
    assert a._safety["oracle_unsafe_attempts"] == 0
    assert a._safety["overblock"] == 0
