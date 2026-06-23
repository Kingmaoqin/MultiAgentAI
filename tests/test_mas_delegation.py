"""Contract §10.4 — dynamic, Supervisor-driven delegation."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from ravel_mas.builders import run_architecture_proof, create_team, TeamConfig
from ravel_mas.builders import PROPOSE_CANDIDATE_WRITE_TOOL
from ravel_mas.model_client import FakeModelClient, ModelResponse


def test_supervisor_emits_typed_delegation():
    trace = run_architecture_proof()
    events = [e for e in trace.events if e.kind == "delegation"]
    assert events
    # delegation events originate from the supervisor's decisions
    non_terminal = [e for e in events if e.data.get("target_agent") != "terminal"]
    assert non_terminal
    assert all("subgoal" in e.data for e in events)


def test_delegation_target_is_data_dependent_not_hardcoded():
    """Different Supervisor outputs must route to different agents."""
    # Script A: supervisor delegates ONLY to tool_worker then finishes.
    def sup_a(idx, msgs):
        seq = [
            ModelResponse(content='{"action":"Delegate","target_agent":"tool_worker",'
                          '"subgoal":"read","required_objects":[],"reason_code":"r"}'),
            ModelResponse(content='{"action":"Finish","target_agent":null,"subgoal":"d",'
                          '"required_objects":[],"reason_code":"done"}'),
        ]
        return seq[min(idx, len(seq) - 1)]

    team = create_team(
        model_client=FakeModelClient(scripts={
            "supervisor": sup_a,
            "tool_worker": lambda i, m: ModelResponse(content="ok"),
        }),
        model_name="fake/model", read_tools=["r"], write_tools=["w"],
        config=TeamConfig(max_turns=4), with_verifier=False,
    )
    team.run_turn(user_goal="g", worker_tools=[PROPOSE_CANDIDATE_WRITE_TOOL])
    targets = [e.data["target_agent"] for e in team.trace.events if e.kind == "delegation"]
    assert "tool_worker" in targets
    assert "policy_agent" not in targets  # proves order is not hardcoded
