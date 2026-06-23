"""Gate-2 proof: the same evidence object yields distinct per-agent views.

Produces artifacts/mas_proof/agent_views.json with at least two different agent
views of the same object (Contract §9 Gate 2, §10.7).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import sys
_SRC = Path(__file__).parent.parent
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
from ravel_core.evidence import EvidenceLedger
from .views import ViewBuilder


def build_conflicting_ledger() -> EvidenceLedger:
    """Ingest 5 versions of reservation:R1; status flips confirmed→cancelled."""
    ledger = EvidenceLedger()
    seq = [
        {"reservation_id": "R1", "status": "confirmed", "refundable": True, "cabin": "economy"},
        {"reservation_id": "R1", "status": "confirmed", "refundable": True, "cabin": "economy"},
        {"reservation_id": "R1", "status": "confirmed", "refundable": True, "cabin": "business"},
        {"reservation_id": "R1", "status": "confirmed", "refundable": False, "cabin": "business"},
        {"reservation_id": "R1", "status": "cancelled", "refundable": False, "cabin": "business"},
    ]
    for payload in seq:
        ledger.ingest(object_id="reservation:R1", tool_name="get_reservation_details",
                      payload=payload, source_agent="tool_worker")
    return ledger


def run_conflicting_view_proof() -> dict[str, Any]:
    """ConflictingView: worker pinned to v4 (confirmed), supervisor sees v5 (cancelled),
    commit sees latest v5 with full read-set."""
    ledger = build_conflicting_ledger()
    vb = ViewBuilder(ledger, regime="ConflictingView", conflict_objects={"reservation:R1"})

    worker = vb.view_for("tool_worker", "reservation:R1")
    supervisor = vb.view_for("supervisor", "reservation:R1")
    policy = vb.view_for("policy_agent", "reservation:R1")
    commit = vb.view_for("commit_service", "reservation:R1")

    result = {
        "regime": "ConflictingView",
        "object_id": "reservation:R1",
        "latest_version": ledger.object_version("reservation:R1"),
        "views": {
            "tool_worker": worker.to_dict() if worker else None,
            "supervisor": supervisor.to_dict() if supervisor else None,
            "policy_agent": policy.to_dict() if policy else None,
            "commit_service": commit.to_dict() if commit else None,
        },
    }
    return result


def latest_view(result: dict, agent_id: str, object_id: str) -> dict:
    return result["views"][agent_id]


def write_proof(out_dir: str = "artifacts/mas_proof") -> str:
    result = run_conflicting_view_proof()
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / "agent_views.json"
    path.write_text(json.dumps(result, indent=2))
    return str(path)


if __name__ == "__main__":
    p = write_proof()
    print(f"wrote {p}")
    r = run_conflicting_view_proof()
    print(json.dumps(r, indent=2))
