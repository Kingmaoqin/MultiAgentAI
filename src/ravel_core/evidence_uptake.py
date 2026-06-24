"""Evidence Uptake Attribution (plan §7.1).

Central question: not whether an agent *saw* evidence, but whether it *used* it.
For each candidate write we attribute every argument value to a source: a visible
evidence id, stale memory, or unsupported/hallucinated. From these per-action
records we compute the §7.1 uptake metrics (zero-denominator → None).

Deterministic: operates on the candidate's arguments and the evidence the agent
was actually shown (no LLM).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# uptake_status (§7.1)
USED_SEEN = "used_seen_evidence"
IGNORED_SEEN = "ignored_seen_evidence"
USED_STALE = "used_stale_evidence"
HALLUCINATED = "hallucinated"
UNSUPPORTED = "unsupported"

# uptake_failure_type (§7.1)
FAIL_SEEN_BUT_UNUSED = "seen_but_unused"
FAIL_UNEXPECTED_NOT_INVESTIGATED = "unexpected_not_investigated"
FAIL_CONFLICT_IGNORED = "conflict_ignored"
FAIL_POLICY_EVIDENCE_IGNORED = "policy_evidence_ignored"
FAIL_DEPENDENCY_BREAK = "dependency_break"


@dataclass
class VisibleEvidence:
    """What the agent was shown for one (object, field): id, value, version, and
    whether the ledger has a newer version (i.e. this is stale)."""
    evidence_id: str
    object_id: str
    field: str
    value: Any
    version: int
    is_stale: bool = False
    conflict_flagged: bool = False


@dataclass
class EvidenceUptakeRecord:
    candidate_action: str
    arguments: dict[str, Any]
    required_evidence_ids: list[str]
    actually_visible_evidence_ids: list[str]
    cited_evidence_ids: list[str]
    argument_source: dict[str, str]       # arg name -> evidence_id | stale_memory | hallucinated | inferred
    uptake_status: str
    uptake_failure_type: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_action": self.candidate_action,
            "arguments": self.arguments,
            "required_evidence_ids": self.required_evidence_ids,
            "actually_visible_evidence_ids": self.actually_visible_evidence_ids,
            "cited_evidence_ids": self.cited_evidence_ids,
            "argument_source": self.argument_source,
            "uptake_status": self.uptake_status,
            "uptake_failure_type": self.uptake_failure_type,
        }


def _match_value(value: Any, visible: list[VisibleEvidence]) -> VisibleEvidence | None:
    for ev in visible:
        if ev.value == value:
            return ev
    return None


def attribute(
    *,
    candidate_action: str,
    arguments: dict[str, Any],
    visible: list[VisibleEvidence],
    required_fields: list[tuple[str, str]] | None = None,  # (object_id, field)
    cited_evidence_ids: list[str] | None = None,
) -> EvidenceUptakeRecord:
    """Attribute each argument to an evidence source and classify uptake."""
    required_fields = required_fields or []
    cited = list(cited_evidence_ids or [])
    visible_ids = [ev.evidence_id for ev in visible]

    arg_source: dict[str, str] = {}
    used_stale = False
    for name, value in arguments.items():
        match = _match_value(value, visible)
        if match is None:
            arg_source[name] = HALLUCINATED if value not in (None, "") else UNSUPPORTED
        elif match.is_stale:
            arg_source[name] = "stale_memory"
            used_stale = True
        else:
            arg_source[name] = match.evidence_id

    # required evidence ids = ids of visible evidence for required fields
    req_ev_ids = [
        ev.evidence_id for ev in visible
        if (ev.object_id, ev.field) in set(required_fields)
    ]

    # uptake status / failure type
    failure: str | None = None
    if any(src in (HALLUCINATED, UNSUPPORTED) for src in arg_source.values()):
        status = HALLUCINATED if HALLUCINATED in arg_source.values() else UNSUPPORTED
        failure = FAIL_DEPENDENCY_BREAK
    elif used_stale:
        status = USED_STALE
        failure = FAIL_CONFLICT_IGNORED if any(ev.conflict_flagged for ev in visible) \
            else FAIL_DEPENDENCY_BREAK
    else:
        status = USED_SEEN

    # seen-but-unused: a required field was visible & fresh but not reflected in args
    if status == USED_SEEN and req_ev_ids:
        used_ids = {s for s in arg_source.values()}
        unused_required = [eid for eid in req_ev_ids if eid not in used_ids]
        if unused_required:
            status = IGNORED_SEEN
            failure = FAIL_SEEN_BUT_UNUSED

    # ignored conflict overrides when a conflict-flagged required field was visible
    if any(ev.conflict_flagged for ev in visible if ev.evidence_id in req_ev_ids):
        if not used_stale and status == USED_SEEN:
            # conflict was visible but write proceeded without recheck citation
            if not any(eid in cited for eid in req_ev_ids):
                failure = FAIL_CONFLICT_IGNORED

    return EvidenceUptakeRecord(
        candidate_action=candidate_action,
        arguments=dict(arguments),
        required_evidence_ids=req_ev_ids,
        actually_visible_evidence_ids=visible_ids,
        cited_evidence_ids=cited,
        argument_source=arg_source,
        uptake_status=status,
        uptake_failure_type=failure,
    )


def _rate(num: int, den: int) -> float | None:
    return None if den == 0 else num / den


class UptakeAccumulator:
    """Aggregate uptake records into the §7.1 metric set (None on zero denom)."""

    def __init__(self) -> None:
        self._records: list[EvidenceUptakeRecord] = []
        self._correction_trials = 0
        self._correction_flips = 0

    def add(self, rec: EvidenceUptakeRecord) -> None:
        self._records.append(rec)

    def record_correction_probe(self, changed_action: bool) -> None:
        """CorrectionSensitivity probe: after injecting the correct critical
        evidence, did the model change its (previously wrong) action?"""
        self._correction_trials += 1
        if changed_action:
            self._correction_flips += 1

    def metrics(self) -> dict[str, float | None]:
        n = len(self._records)
        seen_but_unused = sum(1 for r in self._records
                              if r.uptake_failure_type == FAIL_SEEN_BUT_UNUSED)
        stale_use = sum(1 for r in self._records if r.uptake_status == USED_STALE)
        unsupported = sum(
            1 for r in self._records
            if any(s in (HALLUCINATED, UNSUPPORTED) for s in r.argument_source.values())
        )
        conflict_ignored = sum(1 for r in self._records
                               if r.uptake_failure_type == FAIL_CONFLICT_IGNORED)
        # evidence-to-action coverage = traceable args / total args (pooled)
        total_args = sum(len(r.argument_source) for r in self._records)
        traceable_args = sum(
            1 for r in self._records for s in r.argument_source.values()
            if s not in (HALLUCINATED, UNSUPPORTED)
        )
        return {
            "SeenButUnusedRate": _rate(seen_but_unused, n),
            "StaleEvidenceUseRate": _rate(stale_use, n),
            "UnsupportedArgumentRate": _rate(unsupported, n),
            "ConflictIgnoredRate": _rate(conflict_ignored, n),
            "EvidenceToActionCoverage": _rate(traceable_args, total_args),
            "CorrectionSensitivity": _rate(self._correction_flips, self._correction_trials),
            "n_candidate_actions": n,
        }
