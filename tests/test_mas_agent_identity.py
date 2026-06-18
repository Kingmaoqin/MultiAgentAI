"""Contract §10.1 / §10.3 / §10.10 — agent identity and distinct prompts."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from ravel_mas.builders import run_architecture_proof, create_fake_team
from ravel_mas.model_client import ModelResponse


def test_runtime_invokes_three_distinct_llm_agents():
    trace = run_architecture_proof()
    ids = trace.llm_agent_ids
    assert {"supervisor", "policy_agent", "tool_worker"} <= ids


def test_agent_prompt_hashes_are_distinct():
    team = create_fake_team(scripts={})
    hashes = {
        team.supervisor.prompt_hash,
        team.policy_agent.prompt_hash,
        team.tool_worker.prompt_hash,
    }
    assert len(hashes) == 3


def test_user_simulator_not_counted_as_internal_agent():
    trace = run_architecture_proof()
    internal = trace.internal_agent_ids
    assert "user_simulator" not in internal
    assert len(internal) >= 3


def test_each_agent_has_unique_id():
    team = create_fake_team(scripts={})
    ids = {team.supervisor.agent_id, team.policy_agent.agent_id, team.tool_worker.agent_id}
    assert ids == {"supervisor", "policy_agent", "tool_worker"}
