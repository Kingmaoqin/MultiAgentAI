"""Schema-scoped commit gate for high-risk writes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from .evidence import EvidenceLedger
from .visibility import EvidenceView


@dataclass(frozen=True)
class CandidateWrite:
    action: str
    arguments: Mapping[str, Any]
    target_objects: tuple[str, ...]
    referenced_evidence_ids: tuple[str, ...]
    claimed_preconditions: tuple[str, ...] = ()


@dataclass(frozen=True)
class RequiredEvidence:
    object_id: str
    field: str


@dataclass(frozen=True)
class ActionSchema:
    action: str
    required_fields: tuple[RequiredEvidence, ...]
    policy_checks: tuple[str, ...] = ()


@dataclass(frozen=True)
class GateDecision:
    verdict: str
    reasons: tuple[str, ...]
    missing_fields: tuple[RequiredEvidence, ...] = ()
    stale_fields: tuple[RequiredEvidence, ...] = ()
    conflicting_fields: tuple[RequiredEvidence, ...] = ()
    untraceable_fields: tuple[RequiredEvidence, ...] = ()
    checked_fields: tuple[RequiredEvidence, ...] = ()

    @property
    def allowed(self) -> bool:
        return self.verdict == "commit"


@dataclass
class VisibleEvidenceState:
    versions: dict[tuple[str, str], int] = field(default_factory=dict)
    evidence_ids: dict[tuple[str, str], str] = field(default_factory=dict)
    conflicts: set[tuple[str, str]] = field(default_factory=set)

    @classmethod
    def from_views(cls, views: list[EvidenceView]) -> "VisibleEvidenceState":
        """Build effective visibility state.

        Views are order-independent for the same object field: the highest
        version wins, and its evidence ID stays paired with that version.
        """

        state = cls()
        for view in views:
            view_conflicts = {
                (view.object_id, field_name) for field_name in view.conflict_fields
            }
            for field_name in view.visible_fields:
                key = (view.object_id, field_name)
                current_version = state.versions.get(key, 0)
                if view.version > current_version:
                    state.versions[key] = view.version
                    state.evidence_ids[key] = view.evidence_id
                    state.conflicts.discard(key)
                    if key in view_conflicts:
                        state.conflicts.add(key)
                elif view.version == current_version and key in view_conflicts:
                    state.conflicts.add(key)
        return state


class CommitGate:
    """Validate candidate writes against action-specific evidence schemas.

    When ``schemas`` is empty the gate runs in *permissive* mode: all writes
    are approved without evidence checks.  This is the correct default so that
    the RAVEL visibility regimes (Delayed, FieldMask, ConflictingView) can be
    studied in isolation without the gate adding a second confound.
    """

    def __init__(self, schemas: Mapping[str, ActionSchema]) -> None:
        self.schemas = dict(schemas)
        self._permissive = not bool(schemas)  # empty dict → permissive

    def verify(
        self,
        candidate: CandidateWrite,
        *,
        ledger: EvidenceLedger,
        visible_state: VisibleEvidenceState,
    ) -> GateDecision:
        schema = self.schemas.get(candidate.action)
        if schema is None:
            if self._permissive:
                return GateDecision(verdict="commit", reasons=("permissive_mode",))
            return GateDecision(
                verdict="abstain",
                reasons=(f"unknown_action_schema:{candidate.action}",),
            )

        missing: list[RequiredEvidence] = []
        stale: list[RequiredEvidence] = []
        conflicting: list[RequiredEvidence] = []
        untraceable: list[RequiredEvidence] = []
        referenced = set(candidate.referenced_evidence_ids)

        for req in schema.required_fields:
            latest = ledger.latest_field(req.object_id, req.field)
            key = (req.object_id, req.field)
            if latest is None:
                missing.append(req)
                continue
            latest_version, _value, latest_evidence_id = latest
            seen_version = visible_state.versions.get(key)
            if seen_version is None:
                missing.append(req)
                continue
            if seen_version < latest_version:
                stale.append(req)
            if key in visible_state.conflicts:
                conflicting.append(req)
            seen_evidence_id = visible_state.evidence_ids.get(key)
            if not referenced or (
                seen_evidence_id not in referenced
                and latest_evidence_id not in referenced
            ):
                untraceable.append(req)

        reasons = []
        if missing:
            reasons.append("missing_required_evidence")
        if stale:
            reasons.append("stale_required_evidence")
        if conflicting:
            reasons.append("conflicting_required_evidence")
        if untraceable:
            reasons.append("untraceable_required_evidence")

        if missing or stale or conflicting:
            verdict = "reconcile"
        elif untraceable:
            verdict = "replan"
        else:
            verdict = "commit"
            reasons.append("evidence_valid")

        return GateDecision(
            verdict=verdict,
            reasons=tuple(reasons),
            missing_fields=tuple(missing),
            stale_fields=tuple(stale),
            conflicting_fields=tuple(conflicting),
            untraceable_fields=tuple(untraceable),
            checked_fields=schema.required_fields,
        )
