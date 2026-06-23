"""Gate-3 write-isolation proof scenarios (Contract §9 Gate 3, §10.8).

Demonstrates:
  - Worker direct write → denied (worker has no executor; only CommitService does)
  - Candidate without gate token → denied (WriteIsolationError)
  - Stale expected version → not committed
  - Conflict unresolved → not committed
  - Valid latest read-set → committed
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import sys
from pathlib import Path
_SRC = Path(__file__).parent.parent
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
from ravel_core.evidence import EvidenceLedger
from .commit_service import (
    CommitService,
    CandidateWriteMsg,
    AllowedCommitToken,
    WriteIsolationError,
)

WRITE_TOOLS = {"cancel_reservation", "book_reservation"}
REQUIRED = {"cancel_reservation": ["status"]}


@dataclass
class EnvState:
    """Toy environment whose state only changes via CommitService executor."""
    cancelled: bool = False

    def cancel(self, action: str, args: dict) -> dict:
        self.cancelled = True
        return {"ok": True, "action": action}


def _ledger_with(status: str, n_versions: int = 1) -> EvidenceLedger:
    ledger = EvidenceLedger()
    for _ in range(n_versions):
        ledger.ingest(object_id="reservation:R1", tool_name="get_reservation_details",
                      payload={"reservation_id": "R1", "status": status},
                      source_agent="tool_worker")
    return ledger


def make_service(ledger: EvidenceLedger, env: EnvState) -> CommitService:
    return CommitService(
        ledger, write_tools=WRITE_TOOLS,
        action_required_fields=REQUIRED,
        real_write_executor=env.cancel,
    )


def scenario_valid_commit() -> dict[str, Any]:
    ledger = _ledger_with("confirmed", 1)
    env = EnvState()
    svc = make_service(ledger, env)
    ev_id = ledger.records[-1].evidence_id
    cw = CandidateWriteMsg(
        action="cancel_reservation", arguments={"reservation_id": "R1"},
        target_objects=("reservation:R1",), referenced_evidence_ids=(ev_id,),
        expected_versions={"reservation:R1": 1},
    )
    dec, result = svc.submit(cw)
    return {"verdict": dec.verdict, "committed": dec.allowed,
            "env_cancelled": env.cancelled, "result": result}


def scenario_stale_write() -> dict[str, Any]:
    """Worker's expected version is v1, but environment advanced to v2 (stale)."""
    ledger = _ledger_with("confirmed", 2)  # latest = v2
    env = EnvState()
    svc = make_service(ledger, env)
    cw = CandidateWriteMsg(
        action="cancel_reservation", arguments={"reservation_id": "R1"},
        target_objects=("reservation:R1",),
        referenced_evidence_ids=(ledger.records[0].evidence_id,),
        expected_versions={"reservation:R1": 1},   # stale claim
    )
    dec, result = svc.submit(cw)
    return {"verdict": dec.verdict, "committed": dec.allowed,
            "env_cancelled": env.cancelled, "stale": dec.stale}


def scenario_conflict_write() -> dict[str, Any]:
    ledger = _ledger_with("confirmed", 1)
    # mark latest record as conflicting
    rec = ledger.records[-1]
    object.__setattr__(rec, "conflict_flag", True)
    env = EnvState()
    svc = make_service(ledger, env)
    cw = CandidateWriteMsg(
        action="cancel_reservation", arguments={"reservation_id": "R1"},
        target_objects=("reservation:R1",),
        referenced_evidence_ids=(rec.evidence_id,),
        expected_versions={"reservation:R1": 1},
    )
    dec, result = svc.submit(cw)
    return {"verdict": dec.verdict, "committed": dec.allowed,
            "env_cancelled": env.cancelled, "conflict": dec.conflict}


def scenario_worker_direct_write_denied() -> dict[str, Any]:
    """Worker cannot execute: it has no executor; only CommitService does.
    Even handing a candidate straight to execute_write without a token raises."""
    ledger = _ledger_with("confirmed", 1)
    env = EnvState()
    svc = make_service(ledger, env)
    cw = CandidateWriteMsg(
        action="cancel_reservation", arguments={"reservation_id": "R1"},
        target_objects=("reservation:R1",),
    )
    denied = False
    try:
        svc.execute_write(cw, token=None)            # no token
    except WriteIsolationError:
        denied = True
    forged_denied = False
    try:
        svc.execute_write(cw, AllowedCommitToken("forged", "cancel_reservation", {}))
    except WriteIsolationError:
        forged_denied = True
    return {"no_token_denied": denied, "forged_token_denied": forged_denied,
            "env_cancelled": env.cancelled}


def run_all() -> dict[str, Any]:
    return {
        "valid_commit": scenario_valid_commit(),
        "stale_write": scenario_stale_write(),
        "conflict_write": scenario_conflict_write(),
        "worker_direct_write": scenario_worker_direct_write_denied(),
    }
