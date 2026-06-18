"""Agent-specific evidence projection (Contract §2.5, §6).

The SAME ledger object yields DIFFERENT views per agent:
  Supervisor   → headers + change summaries (no raw values by default)
  PolicyAgent  → policy-relevant fields
  ToolWorker   → action-required fields
  CommitService→ complete latest read-set

Visibility regimes are realized as differences BETWEEN these per-agent views
(version pinning + field selection), not by mutating one shared observation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

# Reuse the deterministic ledger.
import sys
from pathlib import Path
_SRC = Path(__file__).parent.parent
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
from ravel_core.evidence import EvidenceLedger, EvidenceRecord


@dataclass
class AgentView:
    agent_id: str
    object_id: str
    version: int
    visible_fields: dict[str, Any]
    kind: str  # "header" | "fields" | "full"

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "object_id": self.object_id,
            "version": self.version,
            "visible_fields": self.visible_fields,
            "kind": self.kind,
        }


# Role → field-selection policy. "*" = all fields.
ROLE_FIELD_POLICY: dict[str, str] = {
    "supervisor": "header",       # change-summary only
    "policy_agent": "policy",     # policy-relevant fields
    "tool_worker": "action",      # action-required fields
    "commit_service": "full",     # complete read-set
}

# Which fields are policy-relevant vs action-required (domain-agnostic heuristic;
# refined per-domain in Phase 5). Status/refundable/eligibility are policy; ids and
# quantities are action-required.
POLICY_FIELDS = {"status", "refundable", "eligible", "membership", "cabin", "policy"}
ACTION_FIELDS = {"status", "reservation_id", "order_id", "amount", "quantity", "id"}


class ViewBuilder:
    """Produces per-agent views over a shared ledger, honoring the regime.

    Regime semantics (per object):
      FullSync           : every agent sees the latest version (role-filtered fields)
      Delayed            : tool_worker sees version (latest - delay); others latest
      RoleAwareFieldMask : a named required field hidden from the worker only
      ConflictingView    : worker pinned to an older version, supervisor to latest
    """

    def __init__(
        self,
        ledger: EvidenceLedger,
        *,
        regime: str = "FullSync",
        delay: int = 1,
        masked_field: Optional[str] = None,
        conflict_objects: Optional[set[str]] = None,
    ) -> None:
        self.ledger = ledger
        self.regime = regime
        self.delay = delay
        self.masked_field = masked_field
        self.conflict_objects = conflict_objects or set()

    # --- version selection per agent/regime ---

    def _version_for(self, agent_id: str, object_id: str) -> int:
        latest = self.ledger.object_version(object_id)
        if latest == 0:
            return 0
        if self.regime == "Delayed" and agent_id == "tool_worker":
            return max(1, latest - self.delay)
        if self.regime == "ConflictingView":
            if agent_id == "tool_worker" and object_id in self.conflict_objects:
                return max(1, latest - 1)   # worker sees stale version
            # supervisor/policy/commit see latest
        return latest

    def _record_at(self, object_id: str, version: int) -> Optional[EvidenceRecord]:
        for r in self.ledger.records:
            if r.object_id == object_id and r.version == version:
                return r
        return None

    def _select_fields(self, agent_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        policy = ROLE_FIELD_POLICY.get(agent_id, "full")
        if policy == "full":
            return dict(fields)
        if policy == "header":
            # headers: only the field names that changed, values redacted to "<v>"
            return {k: "<changed>" for k in fields}
        if policy == "policy":
            sel = {k: v for k, v in fields.items() if k in POLICY_FIELDS}
            return sel or {k: v for k, v in list(fields.items())[:1]}
        if policy == "action":
            sel = {k: v for k, v in fields.items() if k in ACTION_FIELDS or k.endswith("_id")}
            sel = sel or dict(fields)
            # RoleAwareFieldMask hides one required field from the worker only
            if self.regime == "RoleAwareFieldMask" and self.masked_field in sel:
                sel = {k: v for k, v in sel.items() if k != self.masked_field}
            return sel
        return dict(fields)

    def view_for(self, agent_id: str, object_id: str) -> Optional[AgentView]:
        version = self._version_for(agent_id, object_id)
        if version == 0:
            return None
        rec = self._record_at(object_id, version)
        if rec is None:
            return None
        fields = self._select_fields(agent_id, dict(rec.field_values))
        kind = ROLE_FIELD_POLICY.get(agent_id, "full")
        kind = "header" if kind == "header" else ("full" if kind == "full" else "fields")
        return AgentView(agent_id=agent_id, object_id=object_id,
                         version=version, visible_fields=fields, kind=kind)

    # --- text projections used by the team prompts ---

    def headers_for(self, agent_id: str) -> str:
        objs = {r.object_id for r in self.ledger.records}
        if not objs:
            return "(no evidence yet)"
        lines = []
        for oid in sorted(objs):
            v = self.view_for(agent_id, oid)
            if v:
                lines.append(f"  {oid} v{v.version}: changed={sorted(v.visible_fields)}")
        return "\n".join(lines) or "(no evidence yet)"

    def fields_for(self, agent_id: str, object_ids: list[str]) -> str:
        if not object_ids:
            object_ids = sorted({r.object_id for r in self.ledger.records})
        lines = []
        for oid in object_ids:
            v = self.view_for(agent_id, oid)
            if v:
                lines.append(f"  {oid} v{v.version}: {v.visible_fields}")
        return "\n".join(lines) or "(no fields visible)"

    def commit_readset(self, object_id: str) -> Optional[AgentView]:
        """CommitService sees the complete latest read-set."""
        return self.view_for("commit_service", object_id)


def simple_ledger_headers(ledger: EvidenceLedger) -> str:
    """Fallback header summary when no ViewBuilder is wired (Phase 1)."""
    objs = {r.object_id for r in ledger.records}
    if not objs:
        return "(no evidence yet)"
    out = []
    for oid in sorted(objs):
        out.append(f"  {oid} v{ledger.object_version(oid)}")
    return "\n".join(out)
