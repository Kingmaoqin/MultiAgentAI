"""Contract §15 / §5.3 — one-task runtime proof and ARB ladder."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from ravel_mas.runtime_proof import run_one_task_proof


def test_one_task_proof_stale_then_safe_commit():
    r = run_one_task_proof()
    assert r["stale_detected"] is True
    assert r["distinct_agents"] >= 3
    assert r["final_verdict"] == "commit"      # safely commits after reconciliation
    assert r["committed"] is True
    assert r["env_cancelled"] is True


def test_arb_escalates_to_selective_requery_stage():
    r = run_one_task_proof()
    # stale read is only fixed by the selective-requery stage (stage 4), not stage 1
    assert r["arb_max_stage"] >= 4


def test_proof_artifacts_written():
    r = run_one_task_proof()
    d = Path(r["artifacts_dir"])
    for fn in [
        "runtime_trace.jsonl", "runtime_trace_readable.md",
        "agent_state_manifest.json", "tool_permission_manifest.json",
        "evidence_visibility_manifest.json",
    ]:
        assert (d / fn).exists(), fn


def test_proof_agent_states_have_distinct_object_ids():
    import json
    r = run_one_task_proof()
    manifest = json.loads((Path(r["artifacts_dir"]) / "agent_state_manifest.json").read_text())
    state_ids = {v["state_object_id"] for v in manifest.values()}
    assert len(state_ids) == 3       # three independent state objects


def test_proof_worker_holds_no_real_write():
    import json
    r = run_one_task_proof()
    perm = json.loads((Path(r["artifacts_dir"]) / "tool_permission_manifest.json").read_text())
    assert perm["worker_holds_real_write"] is False
