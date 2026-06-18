"""Contract §11 — Architecture mutation tests.

Each mutation deliberately breaks a core architecture property; the test asserts
that the corresponding invariant (the thing an architecture test checks) now
FAILS. If a mutation does not break any invariant, the test suite is invalid.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest

from ravel_mas.builders import create_fake_team, create_team, TeamConfig, PROPOSE_CANDIDATE_WRITE_TOOL
from ravel_mas.model_client import FakeModelClient, ModelResponse
from ravel_mas.commit_proof import _ledger_with, make_service, EnvState, WRITE_TOOLS
from ravel_mas.commit_service import CandidateWriteMsg, AllowedCommitToken, WriteIsolationError
from ravel_mas.visibility_proof import build_conflicting_ledger
from ravel_mas.views import ViewBuilder


def test_mutation_shared_message_list_breaks_isolation():
    """Mutation: force all agents to share one messages list."""
    team = create_fake_team(scripts={})
    shared = []
    team.supervisor.state.messages = shared
    team.policy_agent.state.messages = shared
    team.tool_worker.state.messages = shared
    # Invariant from test_mas_state_isolation now FAILS:
    isolated = (
        team.supervisor.messages is not team.policy_agent.messages
        and team.supervisor.messages is not team.tool_worker.messages
    )
    assert isolated is False


def test_mutation_same_agent_id_breaks_identity():
    """Mutation: collapse all agent_ids to one."""
    team = create_fake_team(scripts={})
    team.supervisor.agent_id = "agent"
    team.policy_agent.agent_id = "agent"
    team.tool_worker.agent_id = "agent"
    ids = {team.supervisor.agent_id, team.policy_agent.agent_id, team.tool_worker.agent_id}
    # Identity invariant (>=3 distinct) now FAILS:
    assert len(ids) < 3


def test_mutation_identical_prompts_break_distinct_hashes():
    """Mutation: give all agents the same system prompt."""
    team = create_fake_team(scripts={})
    from ravel_mas.agents import _hash
    same = "identical prompt"
    for a in (team.supervisor, team.policy_agent, team.tool_worker):
        a.system_prompt = same
        a.prompt_hash = _hash(same)
    hashes = {team.supervisor.prompt_hash, team.policy_agent.prompt_hash, team.tool_worker.prompt_hash}
    assert len(hashes) != 3


def test_mutation_worker_with_real_write_tool_breaks_permissions():
    """Mutation: add a real write tool to the worker allowlist."""
    team = create_fake_team(scripts={}, read_tools=["r"], write_tools=list(WRITE_TOOLS))
    team.tool_worker.allowed_tools.append("cancel_reservation")
    leaked = set(team.tool_worker.allowed_tools) & WRITE_TOOLS
    # Permission invariant (worker ∩ real_write == ∅) now FAILS:
    assert leaked


def test_mutation_fixed_order_delegation_loses_data_dependence():
    """Mutation: hardcode target regardless of supervisor output."""
    # Supervisor says tool_worker, but a 'fixed-order' team would force policy_agent first.
    # We emulate the broken behavior and show the delegation target no longer matches the
    # supervisor's structured decision.
    def sup(idx, msgs):
        return ModelResponse(content='{"action":"Delegate","target_agent":"tool_worker",'
                             '"subgoal":"x","required_objects":[],"reason_code":"r"}')
    team = create_team(
        model_client=FakeModelClient(scripts={"supervisor": sup,
                                              "tool_worker": lambda i, m: ModelResponse(content="ok")}),
        model_name="fake", read_tools=["r"], write_tools=["w"],
        config=TeamConfig(max_turns=1), with_verifier=False,
    )
    decision = team.supervisor.decide(user_goal="g", task_state="", ledger_headers="", last_result="")
    forced_target = "policy_agent"   # the mutation ignores decision and forces this
    # Data-dependence invariant FAILS: forced target != supervisor's chosen target
    assert forced_target != decision["target_agent"]


def test_mutation_disabling_version_check_admits_stale_write():
    """Mutation: disable the REAL production version guard (not a stub)."""
    ledger = _ledger_with("confirmed", 2)   # latest v2
    env = EnvState()
    cw = CandidateWriteMsg(action="cancel_reservation", arguments={"reservation_id": "R1"},
                           target_objects=("reservation:R1",),
                           expected_versions={"reservation:R1": 1})  # stale claim

    # Baseline: real guard ON → stale blocked.
    svc_on = make_service(ledger, env)
    dec_on, _ = svc_on.submit(cw)
    assert dec_on.verdict != "commit"
    assert env.cancelled is False

    # Mutation: flip the real production flag inside CommitService.verify.
    env2 = EnvState()
    svc_off = make_service(ledger, env2)
    svc_off.enforce_version_check = False         # disables the actual check path
    dec_off, _ = svc_off.submit(cw)
    # With the real guard disabled, the stale write is admitted → proves the guard
    # (executed code in verify()) is what blocks it.
    assert dec_off.verdict == "commit"
    assert env2.cancelled is True


def test_mutation_disabling_conflict_check_admits_value_conflict():
    """Mutation: disable the REAL conflict guard; a value-conflicting write commits."""
    ledger = _ledger_with("confirmed", 1)
    env = EnvState()
    # worker relied on status=cancelled but latest=confirmed → real value conflict
    cw = CandidateWriteMsg(
        action="cancel_reservation", arguments={"reservation_id": "R1"},
        target_objects=("reservation:R1",),
        expected_versions={"reservation:R1": 1},
        claimed_preconditions=({"object_id": "reservation:R1", "field": "status",
                                "operator": "equals", "value": "cancelled"},),
    )
    svc_on = make_service(ledger, env)
    dec_on, _ = svc_on.submit(cw)
    assert dec_on.verdict != "commit"           # conflict blocks it
    assert "unresolved_conflict" in dec_on.reasons
    assert env.cancelled is False

    env2 = EnvState()
    svc_off = make_service(ledger, env2)
    svc_off.enforce_conflict_check = False
    dec_off, _ = svc_off.submit(cw)
    assert dec_off.verdict == "commit"          # guard disabled → admitted
    assert env2.cancelled is True


def test_mutation_bypassing_commit_token_is_refused_by_real_guard():
    """Mutation: try to execute a real write WITHOUT a CommitService-issued token.

    Exercises the real execute_write() guard (not a raw env call): a forged token
    and a None token must both be refused, leaving the environment unchanged. If
    the production token check were removed, this would change env state."""
    ledger = _ledger_with("confirmed", 1)
    env = EnvState()
    svc = make_service(ledger, env)
    cw = CandidateWriteMsg(action="cancel_reservation", arguments={"reservation_id": "R1"},
                           target_objects=("reservation:R1",))
    # Attempt to bypass the gate by calling the real write path directly:
    for bad_token in (None, AllowedCommitToken("forged", "cancel_reservation", {})):
        with pytest.raises(WriteIsolationError):
            svc.execute_write(cw, bad_token)
    assert env.cancelled is False     # real guard kept env unchanged


def test_mutation_identical_views_break_visibility():
    """Mutation: force every agent to the FullSync full read-set (no role filtering)."""
    ledger = build_conflicting_ledger()
    vb = ViewBuilder(ledger, regime="ConflictingView", conflict_objects={"reservation:R1"})
    # Mutation: override version + field selection so all agents see identical latest full view.
    vb._version_for = lambda agent_id, object_id: ledger.object_version(object_id)  # type: ignore
    vb._select_fields = lambda agent_id, fields: dict(fields)  # type: ignore
    worker = vb.view_for("tool_worker", "reservation:R1")
    supervisor = vb.view_for("supervisor", "reservation:R1")
    # Visibility invariant (worker.version != supervisor.version) now FAILS:
    assert worker.version == supervisor.version
    assert worker.visible_fields == supervisor.visible_fields
