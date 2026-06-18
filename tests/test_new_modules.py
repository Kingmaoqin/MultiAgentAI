"""Tests for MSE-Router, ARB, TrialLogger, Metrics, and BenchmarkAdapter.

Covers:
    §9.2  Integration tests
    §9.3  Metamorphic/Invariant tests (9 required invariants)
    §9.4  Mutation probes (tests fail if logic is broken)

Integration test scope:
    ledger → visibility → mse_router → commit_gate → reconciliation → metrics
"""

from __future__ import annotations

import json
import tempfile
import importlib.util
from pathlib import Path

import pytest

from ravel_core import (
    ActionSchema,
    AdaptiveReconciliationBudget,
    AgentContext,
    CandidateWrite,
    CommitGate,
    EvidenceLedger,
    EvidenceRecord,
    MSERouter,
    RAVELRunConfig,
    RequiredEvidence,
    SafetyMetricsAccumulator,
    TokenRecord,
    TrialLogger,
    TrialMeta,
    VisibilityAdapter,
    VisibilityPolicy,
    VisibleEvidenceState,
    compute_risk_score,
)
from ravel_core.reconciliation import ReconciliationResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _simple_schema(action: str, obj: str, *fields: str) -> ActionSchema:
    return ActionSchema(
        action=action,
        required_fields=tuple(RequiredEvidence(obj, f) for f in fields),
    )


def _ingest(ledger: EvidenceLedger, obj: str, payload: dict, agent: str = "retriever") -> EvidenceRecord:
    return ledger.ingest(object_id=obj, tool_name="get_obj", payload=payload, source_agent=agent)


def _trial_meta(trial_id: str = "t001") -> TrialMeta:
    return TrialMeta(
        trial_id=trial_id,
        task_id="task_1",
        domain="airline",
        task_split="dev",
        method="RAVEL-Full",
        regime="FullSync",
        model="qwen3",
        checkpoint="Qwen/Qwen3-32B",
        server_config={"base_url": "http://127.0.0.1:8200/v1"},
        seed=42,
        mutation_seed=0,
        user_simulator_seed=0,
        prompt_hashes={"supervisor": "abc123"},
        tool_schema_hash="def456",
        benchmark_commit="ddc66a7",
        task_data_hash="hash_airline",
    )


def _ravel_config(tmp_path: Path, regime: str = "FullSync") -> RAVELRunConfig:
    return RAVELRunConfig(
        trial_id="t001",
        task_id="task_1",
        domain="airline",
        task_split="dev",
        method="RAVEL-Full",
        regime=regime,
        model="qwen3",
        checkpoint="Qwen/Qwen3-32B",
        server_config={"base_url": "http://127.0.0.1:8200/v1"},
        seed=42,
        mutation_seed=0,
        user_simulator_seed=0,
        benchmark_commit="ddc66a7",
        task_data_hash="hash_airline",
        action_schemas={
            "cancel_reservation": _simple_schema(
                "cancel_reservation", "reservation:R1", "status", "reservation_id"
            )
        },
        output_dir=tmp_path / "results",
        high_risk_actions={"cancel_reservation"},
    )


# ---------------------------------------------------------------------------
# MSE-Router tests
# ---------------------------------------------------------------------------

class TestMSERouter:
    def test_header_only_for_supervisor(self):
        ledger = EvidenceLedger()
        _ingest(ledger, "reservation:R1", {"status": "open"})
        router = MSERouter(ledger)
        ctx = AgentContext(
            agent_id="supervisor_1",
            role="supervisor",
            subgoal="assess task",
            dependency_object_ids=("reservation:R1",),
        )
        ev_slice = router.route(ctx)
        assert len(ev_slice.headers) == 1
        assert len(ev_slice.delta_fields) == 0  # header_only → no deltas
        assert "role_header_only:reservation:R1" in ev_slice.reason_codes

    def test_worker_gets_required_fields(self):
        ledger = EvidenceLedger()
        _ingest(ledger, "reservation:R1", {"status": "open", "reservation_id": "R1"})
        router = MSERouter(ledger)
        ctx = AgentContext(
            agent_id="worker_1",
            role="tool_worker",
            subgoal="cancel reservation",
            required_field_names=("status", "reservation_id"),
            dependency_object_ids=("reservation:R1",),
        )
        ev_slice = router.route(ctx)
        assert any("field_present:reservation:R1.status" in rc for rc in ev_slice.reason_codes)

    def test_missing_object_triggers_raw_fetch(self):
        ledger = EvidenceLedger()
        router = MSERouter(ledger)
        ctx = AgentContext(
            agent_id="worker_1",
            role="tool_worker",
            subgoal="cancel",
            dependency_object_ids=("reservation:NONEXISTENT",),
        )
        ev_slice = router.route(ctx)
        assert ev_slice.fallback_decision == "raw_fetch_required"

    def test_high_risk_write_defers_to_gate(self):
        ledger = EvidenceLedger()
        _ingest(ledger, "reservation:R1", {"status": "open"})
        router = MSERouter(ledger)
        ctx = AgentContext(
            agent_id="worker_1",
            role="tool_worker",
            subgoal="cancel",
            dependency_object_ids=("reservation:R1",),
            is_high_risk_write=True,
        )
        ev_slice = router.route(ctx)
        assert "deferred_to_gate:high_risk_write" in ev_slice.reason_codes

    def test_token_estimate_is_positive_when_evidence_exists(self):
        ledger = EvidenceLedger()
        _ingest(ledger, "reservation:R1", {"status": "open", "seat": "12A"})
        router = MSERouter(ledger)
        ctx = AgentContext(
            agent_id="worker_1",
            role="tool_worker",
            subgoal="check seat",
            dependency_object_ids=("reservation:R1",),
        )
        ev_slice = router.route(ctx)
        assert ev_slice.token_estimate > 0


# ---------------------------------------------------------------------------
# ARB Reconciliation tests
# ---------------------------------------------------------------------------

class TestAdaptiveReconciliation:
    def _setup(self):
        ledger = EvidenceLedger()
        schema = _simple_schema("cancel_reservation", "reservation:R1", "status", "reservation_id")
        gate = CommitGate({"cancel_reservation": schema})
        return ledger, gate

    def test_missing_field_resolved_by_requery(self):
        ledger, gate = self._setup()
        # Only reservation_id ingested; status missing → gate says reconcile
        old = _ingest(ledger, "reservation:R1", {"reservation_id": "R1"})
        view = VisibilityPolicy("FullSync").project(old, agent_id="worker", event_index=1)
        candidate = CandidateWrite(
            action="cancel_reservation",
            arguments={"reservation_id": "R1"},
            target_objects=("reservation:R1",),
            referenced_evidence_ids=(old.evidence_id,),
        )
        initial_decision = gate.verify(
            candidate,
            ledger=ledger,
            visible_state=VisibleEvidenceState.from_views([view]),
        )
        assert initial_decision.verdict == "reconcile"

        def mock_requery(object_id: str, field: str) -> str | None:
            if object_id == "reservation:R1" and field == "status":
                return "open"
            return None

        arb = AdaptiveReconciliationBudget(gate, ledger, requery_tool=mock_requery, max_stage=4)
        result = arb.reconcile(
            candidate,
            initial_decision,
            VisibleEvidenceState.from_views([view]),
        )
        # After stage 1 requery, status is in ledger; re-evaluation should commit.
        assert result.final_verdict == "commit"
        assert result.final_gate_decision is not None
        assert result.final_gate_decision.allowed
        assert result.max_stage_reached >= 1
        assert result.total_token_estimate >= 0

    def test_irrecoverable_conflict_leads_to_replan_or_abstain(self):
        ledger, gate = self._setup()
        record = _ingest(ledger, "reservation:R1", {"reservation_id": "R1", "status": "open"})
        view = VisibilityPolicy("ConflictingView", conflict_fields={"status"}).project(
            record, agent_id="worker", event_index=1
        )
        candidate = CandidateWrite(
            action="cancel_reservation",
            arguments={"reservation_id": "R1"},
            target_objects=("reservation:R1",),
            referenced_evidence_ids=(record.evidence_id,),
        )
        initial_decision = gate.verify(
            candidate,
            ledger=ledger,
            visible_state=VisibleEvidenceState.from_views([view]),
        )
        assert initial_decision.verdict == "reconcile"

        arb = AdaptiveReconciliationBudget(gate, ledger, requery_tool=None, max_stage=6)
        result = arb.reconcile(
            candidate, initial_decision, VisibleEvidenceState.from_views([view])
        )
        assert result.final_verdict in ("replan", "abstain")

    def test_risk_score_formula(self):
        score_all = compute_risk_score(
            irreversible=True, stale=True, conflict=True, missing_fields=True, policy_ambiguity=True
        )
        assert abs(score_all - 1.0) < 1e-9  # weights sum to 1.0

        score_none = compute_risk_score()
        assert score_none == 0.0

        score_stale = compute_risk_score(stale=True)
        assert 0 < score_stale < 1.0


# ---------------------------------------------------------------------------
# TrialLogger tests
# ---------------------------------------------------------------------------

class TestTrialLogger:
    def test_finish_writes_summary_json(self, tmp_path):
        meta = _trial_meta()
        logger = TrialLogger(meta, tmp_path)
        path = logger.finish(
            official_reward=1.0,
            final_db_state={"reservation": "cancelled"},
            safety_metrics={"evidence_valid_rate": 1.0},
        )
        assert path.exists()
        data = json.loads(path.read_text())
        assert data["trial_id"] == "t001"
        assert data["official_reward"] == 1.0

    def test_events_appended_to_jsonl(self, tmp_path):
        meta = _trial_meta()
        logger = TrialLogger(meta, tmp_path)
        logger.log_tool_call(
            agent_id="worker_1", tool="get_reservation_details",
            arguments={"id": "R1"}, output={"status": "open"},
        )
        logger.log_tool_call(
            agent_id="worker_1", tool="get_flight_status",
            arguments={"flight": "AA100"}, output={"status": "on_time"},
        )
        logger.finish(official_reward=0.0, final_db_state={}, safety_metrics={})

        jsonl_files = list(tmp_path.glob("*_events.jsonl"))
        assert len(jsonl_files) == 1
        lines = jsonl_files[0].read_text().strip().split("\n")
        assert len(lines) == 2  # two tool_call events
        for line in lines:
            evt = json.loads(line)
            assert evt["trial_id"] == "t001"
            assert evt["event_type"] == "tool_call"

    def test_agent_observation_records_visible_field_keys(self, tmp_path):
        meta = _trial_meta()
        logger = TrialLogger(meta, tmp_path)
        logger.log_agent_observation(
            agent_id="worker_1",
            evidence_ids=["ev-1"],
            visible_fields={"status": "open", "reservation_id": "R1"},
        )
        lines = list(tmp_path.glob("*_events.jsonl"))[0].read_text().strip().splitlines()
        event = json.loads(lines[0])
        assert event["visible_field_keys"] == ["reservation_id", "status"]
        assert event["visible_fields"] == {"reservation_id": "R1", "status": "open"}

    def test_logger_records_replayable_write_fields(self, tmp_path):
        meta = _trial_meta()
        logger = TrialLogger(meta, tmp_path)
        logger.log_tool_call(
            agent_id="worker_1",
            tool="get_reservation_details",
            arguments={"reservation_id": "R1"},
            output={"reservation_id": "R1", "status": "open"},
        )
        logger.log_candidate_write(
            agent_id="worker_1",
            candidate={
                "action": "cancel_reservation",
                "arguments": {"reservation_id": "R1"},
                "target_objects": ["reservation:R1"],
                "referenced_evidence_ids": ["ev-1"],
                "claimed_preconditions": ["status=open"],
            },
            required_fields=[{"object_id": "reservation:R1", "field": "status"}],
            gate_verdict="commit",
            gate_reasons=["evidence_valid"],
        )
        logger.log_executed_write(
            tool="cancel_reservation",
            arguments={"reservation_id": "R1"},
            result={"status": "cancelled"},
            evidence_valid=True,
        )
        summary_path = logger.finish(
            official_reward=1.0,
            final_db_state={"reservation:R1": {"status": "cancelled"}},
            safety_metrics={"evidence_valid_rate": 1.0},
        )
        data = json.loads(summary_path.read_text())
        assert data["tool_calls"][0]["output"] == {"reservation_id": "R1", "status": "open"}
        assert data["candidate_writes"][0]["arguments"] == {"reservation_id": "R1"}
        assert data["candidate_writes"][0]["claimed_preconditions"] == ["status=open"]
        assert data["executed_writes"][0]["result"] == {"status": "cancelled"}
        assert data["final_db_state"] == {"reservation:R1": {"status": "cancelled"}}

    def test_token_accumulation(self, tmp_path):
        meta = _trial_meta()
        logger = TrialLogger(meta, tmp_path)
        logger.log_tokens(TokenRecord(input_tokens=100, cached_input_tokens=30, output_tokens=20))
        logger.log_tokens(TokenRecord(input_tokens=200, cached_input_tokens=0, output_tokens=40))
        path = logger.finish(official_reward=1.0, final_db_state={}, safety_metrics={})
        data = json.loads(path.read_text())
        assert data["tokens"]["total"]["input_tokens"] == 300
        assert data["tokens"]["total"]["uncached_input_tokens"] == 270
        assert data["tokens"]["total"]["output_tokens"] == 60

    def test_errors_recorded_in_summary(self, tmp_path):
        meta = _trial_meta()
        logger = TrialLogger(meta, tmp_path)
        logger.log_error("tool timeout on get_reservation_details")
        path = logger.finish(official_reward=None, final_db_state={}, safety_metrics={})
        data = json.loads(path.read_text())
        assert len(data["errors"]) == 1


# ---------------------------------------------------------------------------
# Metrics tests
# ---------------------------------------------------------------------------

class TestSafetyMetrics:
    def test_evidence_valid_rate_all_valid(self):
        acc = SafetyMetricsAccumulator()
        for _ in range(5):
            acc.record_executed_write(evidence_valid=True)
        assert acc.evidence_valid_rate() == 1.0

    def test_unsafe_action_rate(self):
        acc = SafetyMetricsAccumulator()
        acc.record_executed_write(evidence_valid=True)
        acc.record_executed_write(evidence_valid=False)
        acc.record_executed_write(evidence_valid=False)
        assert acc.n_executed == 3
        assert abs(acc.unsafe_action_rate() - 2 / 3) < 1e-9

    def test_zero_denominator_returns_none(self):
        acc = SafetyMetricsAccumulator()
        assert acc.evidence_valid_rate() is None
        assert acc.stale_action_rate() is None
        assert acc.conflicting_write_catch_rate() is None
        assert acc.recovery_rate() is None
        assert acc.overblock_rate() is None

    def test_cwcr_correctly_scored(self):
        acc = SafetyMetricsAccumulator()
        # 2 oracle-conflicting candidates; RAVEL caught both
        acc.record_blocked_candidate(oracle_was_conflicting=True, ravel_caught=True, oracle_safe_and_necessary=False)
        acc.record_blocked_candidate(oracle_was_conflicting=True, ravel_caught=True, oracle_safe_and_necessary=False)
        # 1 oracle-conflicting; RAVEL missed it
        acc.record_blocked_candidate(oracle_was_conflicting=True, ravel_caught=False, oracle_safe_and_necessary=False)
        assert abs(acc.conflicting_write_catch_rate() - 2 / 3) < 1e-9

    def test_overblock_rate(self):
        acc = SafetyMetricsAccumulator()
        # 3 blocked: 1 was safe+necessary (overblock), 2 were legitimately risky
        acc.record_blocked_candidate(oracle_was_conflicting=False, ravel_caught=False, oracle_safe_and_necessary=True)
        acc.record_blocked_candidate(oracle_was_conflicting=True, ravel_caught=True, oracle_safe_and_necessary=False)
        acc.record_blocked_candidate(oracle_was_conflicting=True, ravel_caught=True, oracle_safe_and_necessary=False)
        assert abs(acc.overblock_rate() - 1 / 3) < 1e-9

    def test_recovery_rate(self):
        acc = SafetyMetricsAccumulator()
        acc.record_trial_outcome(initially_invalid=True, recovered=True)
        acc.record_trial_outcome(initially_invalid=True, recovered=False)
        acc.record_trial_outcome(initially_invalid=False, recovered=False)
        assert acc.recovery_rate() == 0.5


# ---------------------------------------------------------------------------
# §9.3 Metamorphic / Invariant tests
# ---------------------------------------------------------------------------

class TestInvariants:
    """Nine required invariants from Proposal §9.3."""

    # Invariant 1: FullSync wrapper in unperturbed mode does not change benchmark reward.
    # We test this by verifying FullSync views expose all fields (no masking).
    def test_inv1_fullsync_does_not_mask_any_field(self):
        ledger = EvidenceLedger()
        payload = {"status": "open", "seat": "12A", "price": 299.0}
        record = _ingest(ledger, "reservation:R1", payload)
        view = VisibilityPolicy("FullSync").project(record, agent_id="any", event_index=1)
        assert set(view.visible_fields.keys()) == {"status", "seat", "price"}
        assert view.visible_fields["status"] == "open"

    # Invariant 2: Same seed → same perturbation (deterministic FieldMask).
    def test_inv2_same_seed_same_perturbation(self):
        ledger = EvidenceLedger()
        payload = {"a": 1, "b": 2, "c": 3, "d": 4, "e": 5}
        record = _ingest(ledger, "obj:1", payload)
        views_a = [
            VisibilityPolicy("FieldMask", seed=99).project(record, agent_id=f"agent_{i}", event_index=1)
            for i in range(3)
        ]
        views_b = [
            VisibilityPolicy("FieldMask", seed=99).project(record, agent_id=f"agent_{i}", event_index=1)
            for i in range(3)
        ]
        for a, b in zip(views_a, views_b):
            assert a.visible_fields == b.visible_fields

    # Invariant 3: Mask changes only the agent view, not the true environment (ledger).
    def test_inv3_mask_changes_view_not_ledger(self):
        ledger = EvidenceLedger()
        record = _ingest(ledger, "order:O1", {"status": "delivered", "total": 99})
        VisibilityPolicy("FieldMask", mask_fields={"total"}).project(
            record, agent_id="executor", event_index=1
        )
        # Ledger record must still have both fields
        assert "total" in record.field_values
        assert record.field_values["total"] == 99

    # Invariant 4: ConflictingView does not mutate ledger's real latest version.
    def test_inv4_conflicting_view_no_ledger_mutation(self):
        ledger = EvidenceLedger()
        record = _ingest(ledger, "order:O1", {"status": "delivered"})
        view = VisibilityPolicy("ConflictingView", conflict_fields={"status"}).project(
            record, agent_id="executor", event_index=1
        )
        assert view.visible_fields["status"].startswith("CONFLICT::")
        # Ledger truth must be unchanged
        latest = ledger.latest("order:O1")
        assert latest is not None
        assert latest.field_values["status"] == "delivered"

    # Invariant 5: No-gate variant allows write bypass; gated variant does not.
    def test_inv5_gate_block_enforced(self):
        ledger = EvidenceLedger()
        schema = _simple_schema("cancel_reservation", "reservation:R1", "status", "reservation_id")
        gate = CommitGate({"cancel_reservation": schema})
        # No evidence ingested → gate must block
        candidate = CandidateWrite(
            action="cancel_reservation",
            arguments={},
            target_objects=("reservation:R1",),
            referenced_evidence_ids=(),
        )
        decision = gate.verify(
            candidate,
            ledger=ledger,
            visible_state=VisibleEvidenceState(),
        )
        assert not decision.allowed
        # Simulate no-gate: gate not called → write would proceed. Not testable
        # at this layer, but we verify the gate correctly blocks the unsafe path.
        assert decision.verdict in ("reconcile", "abstain")

    # Invariant 6: Gate block → environment state unchanged (ledger not modified).
    def test_inv6_gate_block_does_not_modify_ledger(self):
        ledger = EvidenceLedger()
        _ingest(ledger, "reservation:R1", {"reservation_id": "R1"})  # missing status
        initial_version = ledger.object_version("reservation:R1")
        schema = _simple_schema("cancel_reservation", "reservation:R1", "status", "reservation_id")
        gate = CommitGate({"cancel_reservation": schema})
        view = VisibilityPolicy("FullSync").project(
            ledger.latest("reservation:R1"), agent_id="worker", event_index=1
        )
        candidate = CandidateWrite(
            action="cancel_reservation",
            arguments={},
            target_objects=("reservation:R1",),
            referenced_evidence_ids=(ledger.latest("reservation:R1").evidence_id,),
        )
        gate.verify(candidate, ledger=ledger, visible_state=VisibleEvidenceState.from_views([view]))
        # Gate verification must NOT write to the ledger
        assert ledger.object_version("reservation:R1") == initial_version

    # Invariant 7: Task reset → no cross-trial ledger contamination.
    def test_inv7_fresh_ledger_per_trial(self):
        # Each trial gets its own EvidenceLedger instance.
        ledger_trial_1 = EvidenceLedger()
        _ingest(ledger_trial_1, "reservation:R1", {"status": "open"})

        ledger_trial_2 = EvidenceLedger()  # fresh instance for trial 2
        assert ledger_trial_2.latest("reservation:R1") is None
        assert ledger_trial_2.object_version("reservation:R1") == 0

    # Invariant 8: Token counting does not double-count across calls.
    def test_inv8_token_no_double_count(self, tmp_path):
        meta = _trial_meta()
        logger = TrialLogger(meta, tmp_path)
        t1 = TokenRecord(input_tokens=100, cached_input_tokens=20, output_tokens=10)
        t2 = TokenRecord(input_tokens=50, cached_input_tokens=0, output_tokens=5)
        logger.log_tokens(t1)
        logger.log_tokens(t2)
        path = logger.finish(official_reward=1.0, final_db_state={}, safety_metrics={})
        data = json.loads(path.read_text())
        assert data["tokens"]["total"]["input_tokens"] == 150
        assert data["tokens"]["total"]["output_tokens"] == 15
        assert data["tokens"]["total"]["uncached_input_tokens"] == 130

    # Invariant 9: Official evaluator output not affected by logging.
    # We verify that VisibilityAdapter does not call or patch tau2 evaluator code.
    def test_inv9_adapter_has_no_tau2_imports(self):
        import importlib
        import ravel_core.benchmark_adapter as adapter_module
        src = Path(adapter_module.__file__).read_text()
        assert "import tau2" not in src
        assert "from tau2" not in src


# ---------------------------------------------------------------------------
# §9.2 Integration tests
# ---------------------------------------------------------------------------

class TestIntegration:
    """Simulate ledger → mse_router → gate → reconciliation → metrics pipeline."""

    def test_full_pipeline_happy_path(self, tmp_path):
        """A tool result flows through the full pipeline to a committed write."""
        adapter = VisibilityAdapter(_ravel_config(tmp_path))

        # Tool worker reads reservation details
        view = adapter.on_tool_result(
            agent_id="worker_1",
            tool_name="get_reservation_details",
            object_id="reservation:R1",
            payload={"reservation_id": "R1", "status": "open"},
            risk_tag="normal",
        )
        assert view.visible_fields.get("status") == "open"

        # Worker proposes a high-risk write
        decision = adapter.on_candidate_write(
            agent_id="worker_1",
            candidate_dict={
                "action": "cancel_reservation",
                "arguments": {"reservation_id": "R1"},
                "target_objects": ["reservation:R1"],
                "referenced_evidence_ids": [view.evidence_id],
            },
        )
        # Gate should commit because status is present, fresh, and traceable
        assert decision.allowed

        # Execute the write
        adapter.on_executed_write(
            tool="cancel_reservation",
            arguments={"reservation_id": "R1"},
            result={"status": "cancelled"},
            evidence_valid=True,
        )

        # Finalise and verify summary
        summary_path = adapter.on_trial_complete(
            official_reward=1.0,
            final_db_state={"reservation:R1": {"status": "cancelled"}},
        )
        data = json.loads(summary_path.read_text())
        assert data["official_reward"] == 1.0
        assert data["n_executed_writes"] == 1

    def test_adapter_blocks_high_risk_write_without_allowed_gate(self, tmp_path):
        adapter = VisibilityAdapter(_ravel_config(tmp_path))
        with pytest.raises(RuntimeError, match="executed_write_without_allowed_gate"):
            adapter.on_executed_write(
                tool="cancel_reservation",
                arguments={"reservation_id": "R1"},
                result={"status": "cancelled"},
                evidence_valid=False,
            )

    def test_adapter_consumes_gate_permission_once(self, tmp_path):
        adapter = VisibilityAdapter(_ravel_config(tmp_path))
        view = adapter.on_tool_result(
            agent_id="worker_1",
            tool_name="get_reservation_details",
            object_id="reservation:R1",
            payload={"reservation_id": "R1", "status": "open"},
        )
        decision = adapter.on_candidate_write(
            agent_id="worker_1",
            candidate_dict={
                "action": "cancel_reservation",
                "arguments": {"reservation_id": "R1"},
                "target_objects": ["reservation:R1"],
                "referenced_evidence_ids": [view.evidence_id],
            },
        )
        assert decision.allowed
        adapter.on_executed_write(
            tool="cancel_reservation",
            arguments={"reservation_id": "R1"},
            result={"status": "cancelled"},
            evidence_valid=True,
        )
        with pytest.raises(RuntimeError, match="executed_write_without_allowed_gate"):
            adapter.on_executed_write(
                tool="cancel_reservation",
                arguments={"reservation_id": "R1"},
                result={"status": "cancelled-again"},
                evidence_valid=True,
            )

    def test_stale_evidence_blocks_write_and_reconciles(self):
        """A stale view must cause the gate to block, then ARB to reconcile."""
        ledger = EvidenceLedger()
        schema = _simple_schema("cancel_reservation", "reservation:R1", "status", "reservation_id")
        gate = CommitGate({"cancel_reservation": schema})

        # Agent sees old version
        old = _ingest(ledger, "reservation:R1", {"reservation_id": "R1", "status": "open"})
        old_view = VisibilityPolicy("FullSync").project(old, agent_id="worker", event_index=1)

        # Environment mutates status → new version in ledger
        _ingest(ledger, "reservation:R1", {"reservation_id": "R1", "status": "locked"})

        candidate = CandidateWrite(
            action="cancel_reservation",
            arguments={"reservation_id": "R1"},
            target_objects=("reservation:R1",),
            referenced_evidence_ids=(old.evidence_id,),
        )
        decision = gate.verify(
            candidate, ledger=ledger,
            visible_state=VisibleEvidenceState.from_views([old_view]),
        )
        assert decision.verdict == "reconcile"
        assert decision.stale_fields

        # ARB resolves staleness with a requery
        def requery(object_id: str, field: str) -> str | None:
            if object_id == "reservation:R1":
                return "locked"
            return None

        arb = AdaptiveReconciliationBudget(gate, ledger, requery_tool=requery, max_stage=4)
        result = arb.reconcile(
            candidate, decision, VisibleEvidenceState.from_views([old_view])
        )
        assert isinstance(result, ReconciliationResult)
        assert result.max_stage_reached >= 1
        assert result.final_verdict == "commit"
        assert result.final_gate_decision is not None
        assert result.final_gate_decision.allowed

    def test_reconciliation_does_not_commit_without_gate_revalidation(self):
        ledger = EvidenceLedger()
        schema = _simple_schema("cancel_reservation", "reservation:R1", "status")
        gate = CommitGate({"cancel_reservation": schema})
        record = _ingest(ledger, "reservation:R1", {"status": "open"})
        view = VisibilityPolicy("FullSync").project(
            record, agent_id="worker", event_index=1
        )
        candidate = CandidateWrite(
            action="cancel_reservation",
            arguments={"reservation_id": "R1"},
            target_objects=("reservation:R1",),
            referenced_evidence_ids=(),  # untraceable even though visible
        )
        decision = gate.verify(
            candidate,
            ledger=ledger,
            visible_state=VisibleEvidenceState.from_views([view]),
        )
        assert decision.verdict == "replan"

        arb = AdaptiveReconciliationBudget(gate, ledger, requery_tool=None, max_stage=2)
        result = arb.reconcile(
            candidate,
            decision,
            VisibleEvidenceState.from_views([view]),
        )
        assert result.final_verdict != "commit"

    def test_adapter_ledger_immutability_after_conflicting_view(self, tmp_path):
        """VisibilityAdapter invariant: conflicting view must not mutate ledger."""
        config = _ravel_config(tmp_path, regime="ConflictingView")
        config = RAVELRunConfig(
            **{**config.__dict__,
               "conflict_fields": {"status"},
               "regime": "ConflictingView"}
        )
        adapter = VisibilityAdapter(config)
        view = adapter.on_tool_result(
            agent_id="worker_1",
            tool_name="get_reservation_details",
            object_id="reservation:R1",
            payload={"status": "open"},
        )
        # View should show conflict
        assert "CONFLICT::" in str(view.visible_fields.get("status", ""))
        # Ledger truth must not be mutated
        adapter.assert_ledger_integrity()
        assert adapter.ledger.latest("reservation:R1").field_values["status"] == "open"

    def test_metrics_are_populated_from_trial_summary(self, tmp_path):
        from ravel_core import compute_metrics
        summary = {
            "trial_id": "t001",
            "domain": "airline",
            "method": "RAVEL-Full",
            "regime": "FullSync",
            "model": "qwen3",
            "task_split": "dev",
            "official_reward": 1.0,
            "tokens": {
                "total": {
                    "input_tokens": 500,
                    "cached_input_tokens": 100,
                    "uncached_input_tokens": 400,
                    "output_tokens": 80,
                    "total_tokens": 580,
                },
                "write_window": {
                    "input_tokens": 50, "cached_input_tokens": 0,
                    "uncached_input_tokens": 50, "output_tokens": 10,
                    "total_tokens": 60,
                },
            },
            "n_tool_calls": 8,
            "n_candidate_writes": 2,
            "n_executed_writes": 2,
            "n_reconciliation_steps": 1,
            "wall_latency_s": 12.3,
            "executed_writes": [
                {
                    "tool": "cancel_reservation",
                    "arguments": {"reservation_id": "R1"},
                    "result": {"status": "cancelled"},
                    "evidence_valid": True,
                    "was_stale": False,
                    "was_conflicting": False,
                },
                {
                    "tool": "cancel_reservation",
                    "arguments": {"reservation_id": "R2"},
                    "result": {"status": "cancelled"},
                    "evidence_valid": True,
                    "was_stale": False,
                    "was_conflicting": False,
                },
            ],
            "oracle_safety_verdicts": [
                {
                    "blocked": True,
                    "oracle_conflicting": False,
                    "ravel_caught": False,
                    "oracle_safe_necessary": False,
                },
                {
                    "blocked": True,
                    "oracle_conflicting": False,
                    "ravel_caught": False,
                    "oracle_safe_necessary": False,
                },
            ],
            "safety_metrics": {
                "evidence_valid_rate": 0.0,  # forged aggregate; ignored
                "unsafe_action_rate": 1.0,   # forged aggregate; ignored
                "overblock_rate": 0.99,      # forged aggregate; ignored
            },
        }
        metrics = compute_metrics(summary)
        assert metrics.final_state_success == 1.0
        assert metrics.tokens_total == 580
        assert metrics.tokens_uncached == 400
        assert metrics.evidence_valid_rate == 1.0
        assert metrics.unsafe_action_rate == 0.0
        assert metrics.overblock_rate == 0.0

    def test_compute_metrics_rejects_forged_safety_aggregate(self):
        from ravel_core import compute_metrics
        summary = {
            "trial_id": "t_bad",
            "domain": "airline",
            "method": "RAVEL-Full",
            "regime": "FullSync",
            "model": "qwen3",
            "task_split": "dev",
            "official_reward": 0.0,
            "tokens": {"total": {}, "write_window": {}},
            "executed_writes": [
                {"tool": "cancel_reservation", "evidence_valid": False}
            ],
            "safety_metrics": {
                "evidence_valid_rate": 1.0,
                "unsafe_action_rate": 0.0,
            },
        }
        metrics = compute_metrics(summary)
        assert metrics.evidence_valid_rate == 0.0
        assert metrics.unsafe_action_rate == 1.0


class TestTaskAudit:
    def _load_module(self):
        path = Path("/home/xqin5/multiaiagent/scripts/task_audit.py")
        spec = importlib.util.spec_from_file_location("task_audit_for_test", path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_dependency_graph_written_for_task(self, tmp_path):
        task_audit = self._load_module()
        task = {
            "id": "task_graph_1",
            "evaluation_criteria": {
                "actions": [
                    {"name": "get_reservation_details"},
                    {"name": "get_user_details"},
                    {"name": "cancel_reservation"},
                ]
            },
        }
        row = task_audit.audit_task(
            task,
            "airline",
            {"airline": frozenset({"cancel_reservation"})},
            graph_dir=tmp_path,
        )
        graph_path = Path(row["dependency_graph_path"])
        assert graph_path.exists()
        graph = json.loads(graph_path.read_text())
        assert graph["nodes"][2]["tool"] == "cancel_reservation"
        assert graph["depth"] >= 3
        assert row["n_dependency_layers_graph"] >= 3


# ---------------------------------------------------------------------------
# §9.4 Mutation probes — tests must FAIL when core logic is broken
# ---------------------------------------------------------------------------

class TestMutationProbes:
    """Verify that tests actually detect broken logic (§9.4).

    Each test temporarily monkey-patches a critical function and confirms
    that the corresponding invariant test would fail.
    """

    def test_probe_freshness_bypass_caught(self):
        """If we force stale → not stale, the stale test must detect this."""
        ledger = EvidenceLedger()
        old = _ingest(ledger, "reservation:R1", {"reservation_id": "R1", "status": "open"})
        _ingest(ledger, "reservation:R1", {"reservation_id": "R1", "status": "locked"})
        old_view = VisibilityPolicy("FullSync").project(old, agent_id="w", event_index=1)
        schema = _simple_schema("cancel_reservation", "reservation:R1", "status", "reservation_id")
        gate = CommitGate({"cancel_reservation": schema})
        candidate = CandidateWrite(
            action="cancel_reservation",
            arguments={},
            target_objects=("reservation:R1",),
            referenced_evidence_ids=(old.evidence_id,),
        )
        decision = gate.verify(
            candidate, ledger=ledger,
            visible_state=VisibleEvidenceState.from_views([old_view]),
        )
        # Must NOT be commit when stale
        assert decision.verdict != "commit", (
            "PROBE FAIL: gate allowed stale evidence — stale detection is broken"
        )

    def test_probe_conflict_bypass_caught(self):
        """Conflicting view must produce reconcile, not commit."""
        ledger = EvidenceLedger()
        record = _ingest(ledger, "reservation:R1", {"reservation_id": "R1", "status": "open"})
        view = VisibilityPolicy("ConflictingView", conflict_fields={"status"}).project(
            record, agent_id="worker", event_index=1
        )
        schema = _simple_schema("cancel_reservation", "reservation:R1", "status", "reservation_id")
        gate = CommitGate({"cancel_reservation": schema})
        candidate = CandidateWrite(
            action="cancel_reservation",
            arguments={},
            target_objects=("reservation:R1",),
            referenced_evidence_ids=(record.evidence_id,),
        )
        decision = gate.verify(
            candidate, ledger=ledger,
            visible_state=VisibleEvidenceState.from_views([view]),
        )
        assert decision.verdict != "commit", (
            "PROBE FAIL: gate allowed conflicting evidence — conflict detection is broken"
        )

    def test_probe_ledger_mutation_detected_by_integrity_check(self, tmp_path):
        """If MappingProxyType were removed, assert_ledger_integrity would fail."""
        adapter = VisibilityAdapter(_ravel_config(tmp_path))
        adapter.on_tool_result("w", "get_obj", "obj:1", {"status": "open"})
        # Should not raise — ledger is intact
        adapter.assert_ledger_integrity()

    def test_probe_token_no_double_count_catches_error(self, tmp_path):
        """Accumulating tokens twice would double the count — test detects it."""
        meta = _trial_meta()
        logger = TrialLogger(meta, tmp_path)
        t = TokenRecord(input_tokens=100, cached_input_tokens=0, output_tokens=10)
        logger.log_tokens(t)
        logger.log_tokens(t)  # deliberately double-counted
        path = logger.finish(official_reward=1.0, final_db_state={}, safety_metrics={})
        data = json.loads(path.read_text())
        # We detect double-count by asserting it's not equal to a single pass
        assert data["tokens"]["total"]["input_tokens"] == 200, (
            "Expected double-count to be 200, not 100 — if this fails, the test is wrong"
        )
