"""Contract §10.5 / §10.6 — tool permission isolation (allowlist, not prompt)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from ravel_mas.builders import create_fake_team

REAL_WRITE_TOOLS = {"cancel_reservation", "book_reservation"}
CANDIDATE_WRITE_TOOLS = {"propose_candidate_write"}


def _team():
    return create_fake_team(
        scripts={},
        read_tools=["get_reservation_details"],
        write_tools=list(REAL_WRITE_TOOLS),
        policy_tools=[],
    )


def test_worker_has_no_real_write_tools():
    worker = _team().tool_worker
    assert not (set(worker.allowed_tools) & REAL_WRITE_TOOLS)
    assert set(worker.allowed_tools) & CANDIDATE_WRITE_TOOLS


def test_supervisor_and_policy_have_no_business_write_tools():
    team = _team()
    assert not (set(team.supervisor.allowed_tools) & REAL_WRITE_TOOLS)
    assert not (set(team.policy_agent.allowed_tools) & REAL_WRITE_TOOLS)


def test_real_write_tools_reserved_for_commit_service():
    team = _team()
    # real write tools are not held by any agent; recorded against the team's commit path
    assert REAL_WRITE_TOOLS <= set(team.real_write_tools)
    assert not (REAL_WRITE_TOOLS & set(team.supervisor.allowed_tools))
    assert not (REAL_WRITE_TOOLS & set(team.policy_agent.allowed_tools))
    assert not (REAL_WRITE_TOOLS & set(team.tool_worker.allowed_tools))
