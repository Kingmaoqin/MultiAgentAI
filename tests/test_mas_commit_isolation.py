"""Contract §10.6 / §10.8 — write isolation & stale/conflict rejection."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest

from ravel_mas.commit_proof import (
    scenario_valid_commit,
    scenario_stale_write,
    scenario_conflict_write,
    scenario_worker_direct_write_denied,
    make_service,
    EnvState,
    _ledger_with,
    WRITE_TOOLS,
)
from ravel_mas.commit_service import CandidateWriteMsg, AllowedCommitToken, WriteIsolationError


def test_valid_latest_readset_is_committed():
    r = scenario_valid_commit()
    assert r["verdict"] == "commit"
    assert r["committed"] is True
    assert r["env_cancelled"] is True


def test_stale_candidate_is_not_committed():
    r = scenario_stale_write()
    assert r["verdict"] != "commit"
    assert r["committed"] is False
    assert r["env_cancelled"] is False     # environment_state_unchanged


def test_conflict_candidate_is_not_committed():
    r = scenario_conflict_write()
    assert r["verdict"] != "commit"
    assert r["committed"] is False
    assert r["env_cancelled"] is False


def test_worker_direct_write_denied():
    r = scenario_worker_direct_write_denied()
    assert r["no_token_denied"] is True
    assert r["forged_token_denied"] is True
    assert r["env_cancelled"] is False


def test_only_commit_service_holds_real_write_tools():
    ledger = _ledger_with("confirmed", 1)
    env = EnvState()
    svc = make_service(ledger, env)
    assert WRITE_TOOLS <= set(svc.tools)


def test_write_without_token_raises():
    ledger = _ledger_with("confirmed", 1)
    env = EnvState()
    svc = make_service(ledger, env)
    cw = CandidateWriteMsg(action="cancel_reservation",
                           arguments={"reservation_id": "R1"},
                           target_objects=("reservation:R1",))
    with pytest.raises(WriteIsolationError):
        svc.execute_write(cw, token=None)
    assert env.cancelled is False
