"""Adaptive Reconciliation Budget for ravel_mas (Contract §5.3).

Escalates strictly in order, re-checking the deterministic CommitService after
each stage. Does NOT broadcast all raw context on first failure.

Stages:
  1 fetch missing required field
  2 fetch latest delta
  3 inspect conflicting versions
  4 selective tool requery
  5 optional stronger semantic verification (advisory)
  6 supervisor replan
  7 user confirmation or abstention
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from .commit_service import CommitService, CandidateWriteMsg, CommitDecision

STAGE_NAMES = {
    1: "fetch_missing_field",
    2: "fetch_latest_delta",
    3: "inspect_conflicting_versions",
    4: "selective_tool_requery",
    5: "semantic_verification",
    6: "supervisor_replan",
    7: "user_confirmation_or_abstain",
}


@dataclass
class ReconStep:
    stage: int
    stage_name: str
    trigger: str
    verdict_after: str


@dataclass
class ReconResult:
    steps: list[ReconStep] = field(default_factory=list)
    final_verdict: str = "abstain"
    final_decision: Optional[CommitDecision] = None

    @property
    def max_stage(self) -> int:
        return max((s.stage for s in self.steps), default=0)


class ReconciliationBudget:
    """Drives selective requery against a CommitService.

    requery_fn(object_id) -> None should re-ingest the latest tool result into
    the ledger for that object (simulating a fresh read). The budget calls it
    only at the selective-requery stage, only for the offending objects.
    """

    def __init__(
        self,
        commit_service: CommitService,
        *,
        requery_fn: Optional[Callable[[str], None]] = None,
        semantic_verifier: Any = None,
        max_stage: int = 7,
    ) -> None:
        self.svc = commit_service
        self.requery_fn = requery_fn
        self.semantic_verifier = semantic_verifier
        self.max_stage = max_stage

    def reconcile(self, cw: CandidateWriteMsg, decision: CommitDecision) -> ReconResult:
        result = ReconResult(final_verdict=decision.verdict, final_decision=decision)
        if decision.verdict == "commit":
            return result

        requeried = False
        for stage in range(1, self.max_stage + 1):
            trigger = self._trigger(stage, decision)
            # Stage actions
            if stage == 4 and self.requery_fn is not None:
                # selective requery: refresh only the offending objects
                for obj in self._offending_objects(decision):
                    self.requery_fn(obj)
                requeried = True
            if stage == 5 and self.semantic_verifier is not None:
                # advisory only; cannot authorize
                self.semantic_verifier.advise(
                    candidate=cw.__dict__, evidence_summary="(reconcile)")

            # The worker can only re-propose with refreshed evidence AFTER a real
            # selective requery (stage 4). Diagnostic stages 1-3 do not fix a stale read.
            candidate = self._refresh_expected(cw) if requeried else cw
            new_decision = self.svc.verify(candidate)
            result.steps.append(ReconStep(
                stage=stage, stage_name=STAGE_NAMES[stage],
                trigger=trigger, verdict_after=new_decision.verdict,
            ))
            result.final_verdict = new_decision.verdict
            result.final_decision = new_decision

            if new_decision.verdict == "commit":
                # execute the now-valid write
                self.svc.execute_write(candidate, new_decision.token)
                return result
            decision = new_decision

        # Ladder exhausted → safe abstain
        result.final_verdict = "abstain"
        return result

    @staticmethod
    def _offending_objects(decision: CommitDecision) -> list[str]:
        objs = []
        for item in list(decision.stale) + list(decision.conflict) + list(decision.missing):
            obj = item.split(":")[0].split(".")[0]
            if obj and obj not in objs:
                objs.append(obj)
        return objs

    def _refresh_expected(self, cw: CandidateWriteMsg) -> CandidateWriteMsg:
        """After a requery, the worker re-proposes with expected = current latest."""
        new_expected = {
            obj: self.svc.ledger.object_version(obj) for obj in cw.target_objects
        }
        return CandidateWriteMsg(
            action=cw.action, arguments=cw.arguments,
            target_objects=cw.target_objects,
            referenced_evidence_ids=cw.referenced_evidence_ids,
            claimed_preconditions=cw.claimed_preconditions,
            expected_versions=new_expected,
        )

    @staticmethod
    def _trigger(stage: int, decision: CommitDecision) -> str:
        if decision.missing:
            return "missing_required_evidence"
        if decision.stale:
            return "stale_read_set"
        if decision.conflict:
            return "unresolved_conflict"
        return "untraceable_or_other"
