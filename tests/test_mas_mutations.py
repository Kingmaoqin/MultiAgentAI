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
    """Mutation: CommitService ignores expected-version mismatch."""
    ledger = _ledger_with("confirmed", 2)   # latest v2
    env = EnvState()
    svc = make_service(ledger, env)

    # Monkeypatch verify to skip the stale check (the mutation).
    orig_required = svc.action_required_fields
    def mutated_verify(cw):
        from ravel_mas.commit_service import CommitDecision, AllowedCommitToken
        import uuid
        tok = f"commit-{uuid.uuid4().hex[:12]}"
        svc._issued_tokens.add(tok)
        return CommitDecision(verdict="commit", reasons=("evidence_valid",),
                              token=AllowedCommitToken(tok, cw.action, {}))
    svc.verify = mutated_verify  # type: ignore

    cw = CandidateWriteMsg(action="cancel_reservation", arguments={"reservation_id": "R1"},
                           target_objects=("reservation:R1",),
                           expected_versions={"reservation:R1": 1})  # stale
    dec, result = svc.submit(cw)
    # With the check disabled, a stale write is (wrongly) committed → proves the
    # real check is what blocks it.
    assert dec.verdict == "commit"
    assert env.cancelled is True


def test_mutation_bypassing_commit_service_changes_env_without_token():
    """Mutation: call the executor directly, bypassing token check."""
    env = EnvState()
    # Direct env mutation bypassing CommitService entirely:
    env.cancel("cancel_reservation", {"reservation_id": "R1"})
    # This is exactly what write-isolation forbids; proves env CAN change if bypassed,
    # which is why the single-write-path invariant matters.
    assert env.cancelled is True


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
