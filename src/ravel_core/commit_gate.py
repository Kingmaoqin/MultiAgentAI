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
    risk_level: str = "high"   # low | medium | high (plan §4.1)


@dataclass(frozen=True)
class GateDecision:
    verdict: str
    reasons: tuple[str, ...]
    missing_fields: tuple[RequiredEvidence, ...] = ()
    stale_fields: tuple[RequiredEvidence, ...] = ()
    conflicting_fields: tuple[RequiredEvidence, ...] = ()
    untraceable_fields: tuple[RequiredEvidence, ...] = ()
    checked_fields: tuple[RequiredEvidence, ...] = ()
    schema_missing: bool = False   # high-risk write lacked an ActionSchema (§4.2)

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

    ``permissive`` (plan §4.2) is **explicit** and defaults to ``False``: a
    silent permissive mode is not allowed for real experiments. Permissive may
    be turned on only for dev/debug.

    Behaviour when a candidate's action has no ActionSchema:
      * ``permissive=True``  → commit (dev only), reason ``permissive_mode``;
      * else, action is high-risk (``high_risk_actions`` is None ⇒ fail-closed:
        every unschemaed write is treated as high-risk) → verdict ``abstain``,
        ``schema_missing=True`` (counted in failure analysis, never dropped);
      * else (action explicitly outside ``high_risk_actions``) → commit with
        reason ``low_risk_no_schema``.
    """

    def __init__(
        self,
        schemas: Mapping[str, ActionSchema],
        *,
        permissive: bool = False,
        high_risk_actions: set[str] | None = None,
    ) -> None:
        self.schemas = dict(schemas)
        self._permissive = permissive
        # None ⇒ fail-closed (treat any unschemaed write as high-risk).
        self._high_risk_actions = high_risk_actions

    def _is_high_risk(self, action: str) -> bool:
        if self._high_risk_actions is None:
            return True
        return action in self._high_risk_actions

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
            if self._is_high_risk(candidate.action):
                return GateDecision(
                    verdict="abstain",
                    reasons=("schema_missing", f"high_risk_no_schema:{candidate.action}"),
                    schema_missing=True,
                )
            return GateDecision(
                verdict="commit",
                reasons=("low_risk_no_schema",),
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
