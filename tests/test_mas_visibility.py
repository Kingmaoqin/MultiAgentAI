"""Contract §10.7 / §10.9 — agent-specific evidence visibility & FullSync integrity."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from ravel_mas.visibility_proof import run_conflicting_view_proof, build_conflicting_ledger
from ravel_mas.views import ViewBuilder


def test_agents_receive_distinct_evidence_views():
    r = run_conflicting_view_proof()
    worker = r["views"]["tool_worker"]
    supervisor = r["views"]["supervisor"]
    commit = r["views"]["commit_service"]
    assert worker["version"] != supervisor["version"]
    assert commit["version"] == max(worker["version"], supervisor["version"])


def test_conflicting_view_is_real_cross_agent_not_synthetic():
    """Worker and commit disagree on the *actual* status value at their versions."""
    r = run_conflicting_view_proof()
    worker_status = r["views"]["tool_worker"]["visible_fields"].get("status")
    commit_status = r["views"]["commit_service"]["visible_fields"].get("status")
    assert worker_status == "confirmed"     # stale v4
    assert commit_status == "cancelled"     # latest v5
    # No synthetic corruption markers
    assert "CONFLICT::" not in str(r)


def test_fullsync_does_not_corrupt_tool_payload():
    """FullSync: commit_service view equals the raw latest field set (semantic identity)."""
    ledger = build_conflicting_ledger()
    vb = ViewBuilder(ledger, regime="FullSync")
    commit = vb.view_for("commit_service", "reservation:R1")
    latest = ledger.latest("reservation:R1")
    assert commit.version == latest.version
    assert dict(commit.visible_fields) == dict(latest.field_values)


def test_delayed_regime_pins_worker_to_older_version():
    ledger = build_conflicting_ledger()
    vb = ViewBuilder(ledger, regime="Delayed", delay=1)
    worker = vb.view_for("tool_worker", "reservation:R1")
    supervisor = vb.view_for("supervisor", "reservation:R1")
    assert worker.version == supervisor.version - 1


def test_role_aware_field_mask_hides_only_from_worker():
    ledger = build_conflicting_ledger()
    vb = ViewBuilder(ledger, regime="RoleAwareFieldMask", masked_field="status")
    worker = vb.view_for("tool_worker", "reservation:R1")
    commit = vb.view_for("commit_service", "reservation:R1")
    assert "status" not in worker.visible_fields      # hidden from worker
    assert "status" in commit.visible_fields          # commit still sees it
