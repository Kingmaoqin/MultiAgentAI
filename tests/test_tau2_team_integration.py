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
