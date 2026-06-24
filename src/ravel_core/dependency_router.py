"""Dependency-Preserving Router (RAVEL-DPR, plan §7.2).

Random field masking destroys action-critical evidence and is an unfair stand-in
for "minimal context". DPR instead routes evidence by its *downstream dependency*:
fields that feed a tool argument, write precondition, or policy check are kept at
full fidelity; fields with no downstream dependency are dropped to a pointer.

The dependency graph is built from the ActionSchema registry (field → action
argument / precondition / policy), optionally augmented by an oracle trajectory's
observed field→tool-arg edges. The router then classifies each field and produces
a routed view, plus a forced read-set fetch before high-risk writes.

Deterministic, no LLM.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field as dc_field
from typing import Any, Iterable

from .action_schemas import rich_schemas

# field categories (§7.2)
MUST_KEEP = "must_keep"
SHOULD_KEEP = "should_keep"
COMPRESSIBLE = "compressible"
DROPPABLE = "droppable"

# required_for values that make a field action-critical
_CRITICAL_REQUIRED_FOR = {"precondition", "argument", "policy", "authorization",
                          "conflict_check"}


@dataclass
class FieldDependencyGraph:
    """field-level dependency edges derived from schemas (+ optional oracle)."""
    # (object_ref, field) -> set of dependency kinds it participates in
    critical: dict[tuple[str, str], set[str]] = dc_field(default_factory=dict)
    supporting: set[tuple[str, str]] = dc_field(default_factory=set)

    def is_critical(self, object_ref: str, field: str) -> bool:
        return (object_ref, field) in self.critical

    def is_supporting(self, object_ref: str, field: str) -> bool:
        return (object_ref, field) in self.supporting


def build_dependency_graph(
    domain: str,
    *,
    oracle_arg_fields: Iterable[tuple[str, str]] = (),
    supporting_fields: Iterable[tuple[str, str]] = (),
) -> FieldDependencyGraph:
    """Build the graph from the rich ActionSchemas for ``domain``.

    ``oracle_arg_fields`` are extra (object_ref, field) pairs observed feeding a
    tool argument in an oracle trajectory; ``supporting_fields`` aid reasoning but
    are not direct args.
    """
    g = FieldDependencyGraph()
    for s in rich_schemas(domain):
        for f in s.required_fields:
            if f.required_for in _CRITICAL_REQUIRED_FOR:
                g.critical.setdefault((f.object_ref, f.field), set()).add(f.required_for)
    for pair in oracle_arg_fields:
        g.critical.setdefault(pair, set()).add("argument")
    for pair in supporting_fields:
        if pair not in g.critical:
            g.supporting.add(pair)
    return g


def classify_field(graph: FieldDependencyGraph, object_ref: str, field: str,
                   *, droppable_fields: set[str] | None = None) -> str:
    """Classify one field into a routing category (§7.2)."""
    if graph.is_critical(object_ref, field):
        return MUST_KEEP
    if graph.is_supporting(object_ref, field):
        return SHOULD_KEEP
    if droppable_fields and field in droppable_fields:
        return DROPPABLE
    # default: compress unknown fields (summary), keep a pointer
    return COMPRESSIBLE


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()
                          ).hexdigest()[:12]


def route_evidence(
    graph: FieldDependencyGraph,
    *,
    object_ref: str,
    object_id: str,
    version: int,
    source_tool: str,
    fields: dict[str, Any],
    droppable_fields: set[str] | None = None,
) -> dict[str, Any]:
    """Produce a routed view of one object's fields (§7.2 routing policy).

    must_keep   → full value + version + source + digest
    should_keep → compact header/delta (value + version)
    compressible→ schema summary (type only)
    droppable   → omitted from the view; a ledger pointer is retained
    """
    routed: dict[str, Any] = {}
    pointers: list[str] = []
    for name, value in fields.items():
        cat = classify_field(graph, object_ref, name, droppable_fields=droppable_fields)
        if cat == MUST_KEEP:
            routed[name] = {"value": value, "version": version,
                            "source": source_tool, "digest": _digest(value)}
        elif cat == SHOULD_KEEP:
            routed[name] = {"value": value, "version": version}
        elif cat == COMPRESSIBLE:
            routed[name] = {"type": type(value).__name__, "summary": True}
        else:  # DROPPABLE
            pointers.append(f"ledger://{object_id}@v{version}#{name}")
    return {"object_id": object_id, "version": version, "fields": routed,
            "dropped_pointers": pointers}


def required_read_set(domain: str, action: str) -> list[tuple[str, str]]:
    """The (object_ref, field) read-set that must be fetched before a high-risk
    write (forced reconcile preflight, §7.2)."""
    for s in rich_schemas(domain):
        if s.action_name == action:
            return [(f.object_ref, f.field) for f in s.required_fields]
    return []


def routing_token_savings(full_fields: dict[str, Any], routed_view: dict[str, Any]
                          ) -> dict[str, Any]:
    """Rough token-proxy comparison: serialized char length full vs routed."""
    full_len = len(json.dumps(full_fields, default=str))
    routed_len = len(json.dumps(routed_view, default=str))
    return {
        "full_chars": full_len,
        "routed_chars": routed_len,
        "reduction": None if full_len == 0 else 1 - routed_len / full_len,
    }
