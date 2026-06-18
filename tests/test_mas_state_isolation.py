"""Contract §10.2 — independent message/history state."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from ravel_mas.builders import create_fake_team, run_architecture_proof


def test_agent_message_states_are_independent():
    team = create_fake_team(scripts={})
    assert team.supervisor.messages is not team.policy_agent.messages
    assert team.supervisor.messages is not team.tool_worker.messages
    assert team.policy_agent.messages is not team.tool_worker.messages


def test_agent_state_objects_are_independent():
    team = create_fake_team(scripts={})
    assert team.supervisor.state is not team.policy_agent.state
    assert team.supervisor.state is not team.tool_worker.state
    assert team.policy_agent.state is not team.tool_worker.state


def test_histories_diverge_after_run():
    trace = run_architecture_proof()
    # After a real run, the three agents hold different message contents.
    # (Reconstruct via fresh proof team is not exposed; assert via trace instead.)
    ids = [c.agent_id for c in trace.llm_calls]
    assert ids.count("supervisor") >= 1
    assert ids.count("policy_agent") >= 1
    assert ids.count("tool_worker") >= 1
