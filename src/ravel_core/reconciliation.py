"""Adaptive Reconciliation Budget (ARB) for RAVEL.

Implements the reconciliation ladder from Proposal §4.5:

    missing-field fetch
    → latest-delta fetch
    → conflicting-version fetch
    → selective tool requery
    → stronger verifier/reasoning budget
    → replan/user confirmation/abstain

Each stage is recorded with its trigger, estimated token cost, new evidence
found, and the verdict produced.  The controller does NOT skip to raw fetch
on the first failure — it climbs the ladder in order.

Risk score formula from Proposal eq. (14):
    r_t = α1·𝟙[irreversible] + α2·𝟙[stale] + α3·𝟙[conflict]
          + α4·𝟙[missing_fields] + α5·𝟙[policy_ambiguity]
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from .commit_gate import CandidateWrite, CommitGate, GateDecision, VisibleEvidenceState
from .evidence import EvidenceLedger, thaw_value


# Default risk weights (§4.5 αi).  Can be overridden per experiment config.
DEFAULT_ALPHA = {
    "irreversible": 0.4,
    "stale": 0.2,
    "conflict": 0.2,
    "missing_fields": 0.15,
    "policy_ambiguity": 0.05,
}


def compute_risk_score(
    *,
    irreversible: bool = False,
    stale: bool = False,
    conflict: bool = False,
    missing_fields: bool = False,
    policy_ambiguity: bool = False,
    alpha: dict[str, float] | None = None,
) -> float:
    """Compute normalised risk score from auditable binary features (eq. 14)."""
    w = alpha or DEFAULT_ALPHA
    return (
        w["irreversible"] * int(irreversible)
        + w["stale"] * int(stale)
        + w["conflict"] * int(conflict)
        + w["missing_fields"] * int(missing_fields)
        + w["policy_ambiguity"] * int(policy_ambiguity)
    )


@dataclass
class ReconciliationStep:
    """Record of one rung on the reconciliation ladder."""

    stage: int  # 1-6
    stage_name: str
    trigger: str
    token_estimate: int
    latency_ms: float | None
    new_evidence_ids: tuple[str, ...] = ()
    verdict: str = "pending"  # pending | escalate | commit | replan | abstain


@dataclass
class ReconciliationResult:
    """Full outcome of an ARB reconciliation attempt."""

    candidate: CandidateWrite
    steps: list[ReconciliationStep] = field(default_factory=list)
    final_verdict: str = "abstain"
    final_gate_decision: GateDecision | None = None
    total_token_estimate: int = 0

    @property
    def max_stage_reached(self) -> int:
        return max((s.stage for s in self.steps), default=0)


class AdaptiveReconciliationBudget:
    """Reconciliation ladder controller.

    The controller wraps a CommitGate and a tool-requery callback.  It climbs
    the ladder stage-by-stage until EvidenceValid is satisfied or the ladder
    is exhausted.

    ``requery_tool`` is a callable(object_id, field_name) → Any that fetches
    fresh data.  In production this calls the real benchmark tool.  In tests
    it can be mocked deterministically.

    No LLM is called inside this class; reasoning budget is handled externally
    by the caller at stage 5.
    """

    STAGE_NAMES = {
        1: "missing_field_fetch",
        2: "latest_delta_fetch",
        3: "conflicting_version_fetch",
        4: "selective_tool_requery",
        5: "stronger_verifier_budget",
        6: "replan_or_abstain",
    }

    def __init__(
        self,
        gate: CommitGate,
        ledger: EvidenceLedger,
        requery_tool: Any = None,
        max_stage: int = 6,
    ) -> None:
        self._gate = gate
        self._ledger = ledger
        self._requery_tool = requery_tool
        self._max_stage = max_stage

    def reconcile(
        self,
        candidate: CandidateWrite,
        initial_decision: GateDecision,
        visible_state: VisibleEvidenceState,
    ) -> ReconciliationResult:
        """Climb the ladder from the initial gate failure."""
        result = ReconciliationResult(candidate=candidate)
        current_state = visible_state
        current_decision = initial_decision
        current_candidate = candidate

        if current_decision.allowed:
            result.final_verdict = "commit"
            result.final_gate_decision = current_decision
            return result

        for stage in range(1, self._max_stage + 1):
            step = self._run_stage(
                stage,
                current_candidate,
                current_decision,
                current_state,
            )
            result.steps.append(step)
            result.total_token_estimate += step.token_estimate

            if step.verdict in ("replan", "abstain"):
                result.final_verdict = step.verdict
                result.final_gate_decision = current_decision
                return result

            # Escalate: surface fetched evidence and re-run the commit gate.
            # A stage may not commit directly; EvidenceValid must be rechecked
            # against the updated visible state and augmented evidence refs.
            if step.new_evidence_ids:
                current_candidate = self._with_reconciled_references(
                    current_candidate,
                    step.new_evidence_ids,
                )
                current_state = self._build_updated_state(current_state, step)
                current_decision = self._gate.verify(
                    current_candidate,
                    ledger=self._ledger,
                    visible_state=current_state,
                )
                if current_decision.allowed:
                    step.verdict = "commit"
                    result.final_verdict = "commit"
                    result.final_gate_decision = current_decision
                    return result

        result.final_verdict = "abstain"
        result.final_gate_decision = current_decision
        return result

    def _run_stage(
        self,
        stage: int,
        candidate: CandidateWrite,
        decision: GateDecision,
        visible_state: VisibleEvidenceState,
    ) -> ReconciliationStep:
        name = self.STAGE_NAMES[stage]
        trigger = self._trigger_description(stage, decision)

        if stage == 1:
            return self._stage_missing_field_fetch(name, trigger, decision)
        if stage == 2:
            return self._stage_latest_delta_fetch(name, trigger, decision)
        if stage == 3:
            return self._stage_conflicting_version_fetch(name, trigger, decision)
        if stage == 4:
            return self._stage_selective_requery(name, trigger, decision)
        if stage == 5:
            return ReconciliationStep(
                stage=5,
                stage_name=name,
                trigger=trigger,
                token_estimate=0,
                latency_ms=None,
                verdict="escalate",
            )
        # stage 6
        return ReconciliationStep(
            stage=6,
            stage_name=name,
            trigger=trigger,
            token_estimate=0,
            latency_ms=None,
            verdict="abstain",
        )

    def _trigger_description(self, stage: int, decision: GateDecision) -> str:
        if stage == 1:
            return f"missing_fields:{[str(r) for r in decision.missing_fields]}"
        if stage == 2:
            return f"stale_fields:{[str(r) for r in decision.stale_fields]}"
        if stage == 3:
            return f"conflicting_fields:{[str(r) for r in decision.conflicting_fields]}"
        if stage == 4:
            return "selective_requery_after_delta_insufficient"
        if stage == 5:
            return "budget_elevation_requested"
        return "ladder_exhausted"

    def _stage_missing_field_fetch(
        self, name: str, trigger: str, decision: GateDecision
    ) -> ReconciliationStep:
        """Stage 1: attempt to fetch only the missing required fields."""
        new_ids: list[str] = []
        token_est = 0
        if self._requery_tool and decision.missing_fields:
            for req in decision.missing_fields:
                raw = self._requery_tool(req.object_id, req.field)
                if raw is not None:
                    record = self._ledger.ingest(
                        object_id=req.object_id,
                        tool_name=f"requery:{req.field}",
                        payload={req.field: raw},
                        source_agent="reconciler",
                    )
                    new_ids.append(record.evidence_id)
                    token_est += 8  # approximate header tokens
        return ReconciliationStep(
            stage=1, stage_name=name, trigger=trigger,
            token_estimate=token_est, latency_ms=None,
            new_evidence_ids=tuple(new_ids), verdict="escalate",
        )

    def _stage_latest_delta_fetch(
        self, name: str, trigger: str, decision: GateDecision
    ) -> ReconciliationStep:
        """Stage 2: fetch latest delta for stale objects."""
        new_ids: list[str] = []
        token_est = 0
        if self._requery_tool and decision.stale_fields:
            seen_objects: set[str] = set()
            for req in decision.stale_fields:
                if req.object_id in seen_objects:
                    continue
                seen_objects.add(req.object_id)
                latest = self._ledger.latest(req.object_id)
                if latest:
                    token_est += len(latest.changed_fields) * 4
                    new_ids.append(latest.evidence_id)
        return ReconciliationStep(
            stage=2, stage_name=name, trigger=trigger,
            token_estimate=token_est, latency_ms=None,
            new_evidence_ids=tuple(new_ids), verdict="escalate",
        )

    def _stage_conflicting_version_fetch(
        self, name: str, trigger: str, decision: GateDecision
    ) -> ReconciliationStep:
        """Stage 3: surface conflicting versions for manual resolution."""
        token_est = 0
        new_ids: list[str] = []
        if decision.conflicting_fields:
            for req in decision.conflicting_fields:
                records = [
                    r for r in self._ledger.records
                    if r.object_id == req.object_id and req.field in r.field_values
                ]
                for r in records[-2:]:  # last two versions
                    token_est += 12
                    new_ids.append(r.evidence_id)
        return ReconciliationStep(
            stage=3, stage_name=name, trigger=trigger,
            token_estimate=token_est, latency_ms=None,
            new_evidence_ids=tuple(new_ids), verdict="escalate",
        )

    def _stage_selective_requery(
        self, name: str, trigger: str, decision: GateDecision
    ) -> ReconciliationStep:
        """Stage 4: call read tools for specific conflicting fields."""
        new_ids: list[str] = []
        token_est = 0
        if self._requery_tool:
            for req in list(decision.stale_fields) + list(decision.conflicting_fields):
                raw = self._requery_tool(req.object_id, req.field)
                if raw is not None:
                    record = self._ledger.ingest(
                        object_id=req.object_id,
                        tool_name=f"selective_requery:{req.field}",
                        payload={req.field: raw},
                        source_agent="reconciler",
                    )
                    new_ids.append(record.evidence_id)
                    token_est += 12
        return ReconciliationStep(
            stage=4, stage_name=name, trigger=trigger,
            token_estimate=token_est, latency_ms=None,
            new_evidence_ids=tuple(new_ids), verdict="escalate",
        )

    @staticmethod
    def _with_reconciled_references(
        candidate: CandidateWrite,
        evidence_ids: tuple[str, ...],
    ) -> CandidateWrite:
        """Return a candidate whose read-set includes reconciled evidence."""
        merged = tuple(dict.fromkeys(candidate.referenced_evidence_ids + evidence_ids))
        return replace(candidate, referenced_evidence_ids=merged)

    def _build_updated_state(
        self, old_state: VisibleEvidenceState, step: ReconciliationStep
    ) -> VisibleEvidenceState:
        """Build a new VisibleEvidenceState including freshly ingested records."""
        from .visibility import EvidenceView, VisibilityPolicy

        policy = VisibilityPolicy("FullSync")
        new_views = []
        for ev_id in step.new_evidence_ids:
            record = self._ledger.get(ev_id)
            if record is not None:
                new_views.append(
                    policy.project(record, agent_id="reconciler", event_index=record.logical_clock)
                )

        combined_versions = dict(old_state.versions)
        combined_evidence_ids = dict(old_state.evidence_ids)
        combined_conflicts = set(old_state.conflicts)

        for view in new_views:
            for field_name in view.visible_fields:
                key = (view.object_id, field_name)
                if view.version > combined_versions.get(key, 0):
                    combined_versions[key] = view.version
                    combined_evidence_ids[key] = view.evidence_id
                    combined_conflicts.discard(key)

        new_state = VisibleEvidenceState()
        new_state.versions = combined_versions
        new_state.evidence_ids = combined_evidence_ids
        new_state.conflicts = combined_conflicts
        return new_state
