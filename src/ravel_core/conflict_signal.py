"""RAVEL-CSI: Conflict-as-Signal Evidence Interface (plan §6).

The original ``ConflictingView`` regime corrupts a *fact value* (it shows the
worker a wrong/old field value). That confounds "does conflict information help?"
with "does perturbing the value change exploration?". CSI removes the fake value:
it always gives the agent the *reliable current value* plus a **structured
conflict signal** describing version state and the recommended resolution.

This module is deterministic (no LLM): given the ledger version state and the
version the agent actually observed, it emits a typed ``ConflictSignal`` and
renders the agent-facing projection for one of four variants (§6.2):

  - ``LabelOnly``    : current value + conflict label + version + pointer only
  - ``DualVersion``  : current value + the older observed version, explicitly tagged
  - ``GatePreflight``: like LabelOnly but forces must_recheck_before_commit
  - ``NoWrongValue`` : current value + label, and a hard guarantee no fake value
                       is ever surfaced (the contrast probe vs OriginalConflictingView)

Wrong-value perturbation is intentionally NOT produced here; it stays only as a
separate perturbation probe (plan §6.2).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# conflict_status (§6.1)
NONE = "none"
POSSIBLE_CONFLICT = "possible_conflict"
CONFIRMED_CONFLICT = "confirmed_conflict"
STALE_VIEW = "stale_view"

# conflict_source (§6.1)
SRC_LOCAL_VIEW = "agent_local_view"
SRC_VERSION_GAP = "ledger_version_gap"
SRC_EXOGENOUS = "exogenous_mutation"
SRC_USER_SIDE = "user_side_update"

# recommended_resolution (§6.1)
RES_FETCH_LATEST = "fetch_latest"
RES_COMPARE_VERSIONS = "compare_versions"
RES_ASK_USER = "ask_user"
RES_BLOCK_WRITE = "block_write"

# write_precondition
PRE_NONE = "none"
PRE_RECHECK = "must_recheck_before_commit"

# CSI variants (§6.2)
CSI_VARIANTS = ("LabelOnly", "DualVersion", "GatePreflight", "NoWrongValue")


@dataclass(frozen=True)
class ConflictSignal:
    """Structured uncertainty signal for one (object, field) — never a fake value."""
    field: str
    current_value: Any
    current_version: int
    conflict_status: str
    conflict_source: str | None
    older_versions_available: bool
    write_precondition: str
    recommended_resolution: str
    seen_version: int | None = None
    seen_value: Any = None       # only populated for DualVersion rendering

    def to_dict(self, *, include_seen_value: bool = False) -> dict[str, Any]:
        d = {
            "field": self.field,
            "current_value": self.current_value,
            "current_version": self.current_version,
            "conflict_status": self.conflict_status,
            "conflict_source": self.conflict_source,
            "older_versions_available": self.older_versions_available,
            "write_precondition": self.write_precondition,
            "recommended_resolution": self.recommended_resolution,
        }
        if include_seen_value:
            d["seen_version"] = self.seen_version
            d["seen_value"] = self.seen_value
        return d


def build_conflict_signal(
    *,
    field: str,
    current_value: Any,
    current_version: int,
    seen_version: int | None,
    seen_value: Any = None,
    source: str = SRC_EXOGENOUS,
    user_side: bool = False,
) -> ConflictSignal:
    """Derive the typed signal from version state (deterministic).

    * seen_version is None        → agent never observed the field → POSSIBLE,
      recommend fetch_latest.
    * seen_version < current       → STALE_VIEW (a newer version exists),
      confirmed conflict if the observed value actually differs.
    * seen_version == current      → NONE (fresh).
    """
    if user_side:
        source = SRC_USER_SIDE

    if seen_version is None:
        return ConflictSignal(
            field=field, current_value=current_value, current_version=current_version,
            conflict_status=POSSIBLE_CONFLICT, conflict_source=source,
            older_versions_available=current_version > 1,
            write_precondition=PRE_RECHECK, recommended_resolution=RES_FETCH_LATEST,
            seen_version=None, seen_value=None,
        )
    if seen_version < current_version:
        differs = seen_value is not None and seen_value != current_value
        status = CONFIRMED_CONFLICT if differs else STALE_VIEW
        return ConflictSignal(
            field=field, current_value=current_value, current_version=current_version,
            conflict_status=status,
            conflict_source=SRC_VERSION_GAP if not user_side else SRC_USER_SIDE,
            older_versions_available=True,
            write_precondition=PRE_RECHECK,
            recommended_resolution=(RES_COMPARE_VERSIONS if differs else RES_FETCH_LATEST),
            seen_version=seen_version, seen_value=seen_value,
        )
    return ConflictSignal(
        field=field, current_value=current_value, current_version=current_version,
        conflict_status=NONE, conflict_source=None,
        older_versions_available=current_version > 1,
        write_precondition=PRE_NONE, recommended_resolution=RES_FETCH_LATEST,
        seen_version=seen_version, seen_value=current_value,
    )


def render_signal(signal: ConflictSignal, variant: str) -> dict[str, Any]:
    """Project a signal into the agent-facing dict for one CSI variant (§6.2).

    Crucially, **every** variant surfaces the reliable ``current_value`` and
    never a fake value (that is the whole point of CSI vs ConflictingView).
    """
    if variant not in CSI_VARIANTS:
        raise ValueError(f"unknown CSI variant: {variant!r}")

    if variant == "LabelOnly":
        d = signal.to_dict()
        d.pop("older_versions_available", None)  # label + value + version + pointer
        return d

    if variant == "DualVersion":
        # expose both the current and the older observed version, explicitly tagged
        return signal.to_dict(include_seen_value=True)

    if variant == "GatePreflight":
        d = signal.to_dict()
        # force a recheck precondition regardless of status (preflight discipline)
        d["write_precondition"] = PRE_RECHECK
        if d["conflict_status"] == NONE:
            d["recommended_resolution"] = RES_COMPARE_VERSIONS
        return d

    # NoWrongValue: hard guarantee — assert no fake value, return current only
    d = signal.to_dict()
    assert d["current_value"] == signal.current_value
    d["fake_value_surfaced"] = False
    return d


def requires_preflight(signal: ConflictSignal) -> bool:
    """Whether a candidate write on this field must re-check before commit."""
    return signal.write_precondition == PRE_RECHECK
