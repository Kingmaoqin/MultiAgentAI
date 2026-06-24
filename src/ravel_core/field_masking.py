"""Deterministic, seed-controlled field-masking regimes (plan §5.2).

The plan requires that visibility perturbations are produced by a deterministic
wrapper under a fixed seed — never by an LLM. This module implements the
FieldMask mechanism-decomposition regimes used to separate "too little info"
from "deleted action-critical fields":

  - FieldMaskRandom_{5,10,20,30} : random fraction masked, seeded & reproducible
  - MaskIrrelevantOnly           : mask only droppable/irrelevant fields
  - MaskSupportingOnly           : mask only supporting fields
  - MaskActionCriticalOnly       : mask only must_keep (action-critical) fields
  - DependencyPreservingMask     : never mask must_keep; mask the rest (≈ DPR)

Field categories come from the DPR dependency graph (action_schemas registry),
so "action-critical" is grounded in tool args / preconditions / policy, not a
guess.
"""

from __future__ import annotations

import random
from typing import Any

from .dependency_router import (
    FieldDependencyGraph, classify_field, MUST_KEEP, SHOULD_KEEP, COMPRESSIBLE,
    DROPPABLE,
)

RANDOM_REGIMES = {
    "FieldMaskRandom_5": 0.05,
    "FieldMaskRandom_10": 0.10,
    "FieldMaskRandom_20": 0.20,
    "FieldMaskRandom_30": 0.30,
}
CATEGORY_REGIMES = (
    "MaskIrrelevantOnly", "MaskSupportingOnly", "MaskActionCriticalOnly",
    "DependencyPreservingMask",
)
ALL_REGIMES = tuple(RANDOM_REGIMES) + CATEGORY_REGIMES


def _seeded_rng(seed: int, object_id: str) -> random.Random:
    """Per-object deterministic RNG so masking is stable across a run for a seed."""
    return random.Random(f"{seed}:{object_id}")


def fields_to_mask(
    regime: str,
    *,
    object_ref: str,
    object_id: str,
    fields: list[str],
    graph: FieldDependencyGraph,
    seed: int,
    droppable_fields: set[str] | None = None,
) -> set[str]:
    """Return the set of field names to hide for one object under ``regime``.

    Deterministic given (regime, seed, object_id, field list).
    """
    if regime not in ALL_REGIMES:
        raise ValueError(f"unknown FieldMask regime: {regime!r}")

    cats = {
        f: classify_field(graph, object_ref, f, droppable_fields=droppable_fields)
        for f in fields
    }

    if regime in RANDOM_REGIMES:
        rate = RANDOM_REGIMES[regime]
        rng = _seeded_rng(seed, object_id)
        ordered = sorted(fields)
        k = round(rate * len(ordered))
        # stable shuffle then take first k → reproducible subset
        rng.shuffle(ordered)
        return set(ordered[:k])

    if regime == "MaskIrrelevantOnly":
        return {f for f, c in cats.items() if c in (DROPPABLE, COMPRESSIBLE)}
    if regime == "MaskSupportingOnly":
        return {f for f, c in cats.items() if c == SHOULD_KEEP}
    if regime == "MaskActionCriticalOnly":
        return {f for f, c in cats.items() if c == MUST_KEEP}
    # DependencyPreservingMask: mask everything that is NOT action-critical
    return {f for f, c in cats.items() if c != MUST_KEEP}


def apply_mask(fields: dict[str, Any], masked: set[str]) -> dict[str, Any]:
    """Return a copy of ``fields`` with masked keys removed (real redaction)."""
    return {k: v for k, v in fields.items() if k not in masked}


def mask_rate(fields: dict[str, Any], masked: set[str]) -> float | None:
    """Effective fraction of fields hidden (None if no fields)."""
    if not fields:
        return None
    return len([k for k in fields if k in masked]) / len(fields)
