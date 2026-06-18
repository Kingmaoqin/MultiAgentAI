"""Evidence visibility projections.

The real ledger remains authoritative. These projections define what an agent
is allowed to see in prompt context for a specific observation regime.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

from .evidence import EvidenceRecord, thaw_value


@dataclass(frozen=True)
class EvidenceView:
    evidence_id: str
    object_id: str
    tool_name: str
    version: int
    agent_id: str
    visible_fields: dict[str, Any]
    raw_payload_pointer: str
    projection_type: str
    reason_codes: tuple[str, ...] = ()
    conflict_fields: tuple[str, ...] = ()


@dataclass
class VisibilityPolicy:
    regime: str = "FullSync"
    delay: int = 1
    seed: int = 0
    mask_fields: set[str] = field(default_factory=set)
    conflict_fields: set[str] = field(default_factory=set)

    def project(
        self,
        record: EvidenceRecord,
        *,
        agent_id: str,
        event_index: int,
    ) -> EvidenceView:
        regime = self.regime
        if regime == "FullSync":
            return self._view(record, agent_id, self._copy_fields(record.field_values), "raw")
        if regime == "Delayed":
            return self._delayed(record, agent_id, event_index)
        if regime == "FieldMask":
            return self._field_mask(record, agent_id)
        if regime == "ConflictingView":
            return self._conflicting(record, agent_id)
        raise ValueError(f"Unknown visibility regime: {regime}")

    def _view(
        self,
        record: EvidenceRecord,
        agent_id: str,
        fields: dict[str, Any],
        projection_type: str,
        reason_codes: tuple[str, ...] = (),
        conflict_fields: tuple[str, ...] = (),
    ) -> EvidenceView:
        return EvidenceView(
            evidence_id=record.evidence_id,
            object_id=record.object_id,
            tool_name=record.tool_name,
            version=record.version,
            agent_id=agent_id,
            visible_fields=fields,
            raw_payload_pointer=record.raw_payload_pointer,
            projection_type=projection_type,
            reason_codes=reason_codes,
            conflict_fields=conflict_fields,
        )

    @staticmethod
    def _copy_fields(fields: dict[str, Any]) -> dict[str, Any]:
        return {field_name: thaw_value(value) for field_name, value in fields.items()}

    def _delayed(
        self, record: EvidenceRecord, agent_id: str, event_index: int
    ) -> EvidenceView:
        if agent_id == record.source_agent:
            return self._view(record, agent_id, self._copy_fields(record.field_values), "raw")
        release_at = record.logical_clock + self.delay
        if event_index < release_at:
            return self._view(
                record,
                agent_id,
                {},
                "pointer",
                (f"delayed_until:{release_at}",),
            )
        return self._view(record, agent_id, self._copy_fields(record.field_values), "raw")

    def _field_mask(self, record: EvidenceRecord, agent_id: str) -> EvidenceView:
        visible = {}
        masked = []
        for field_name, value in record.field_values.items():
            if self._is_masked(agent_id, field_name):
                masked.append(field_name)
            else:
                visible[field_name] = thaw_value(value)
        return self._view(
            record,
            agent_id,
            visible,
            "field_slice",
            tuple(f"masked:{name}" for name in sorted(masked)),
        )

    def _is_masked(self, agent_id: str, field_name: str) -> bool:
        if field_name in self.mask_fields:
            return True
        key = f"{self.seed}:{agent_id}:{field_name}".encode("utf-8")
        return int(hashlib.sha256(key).hexdigest(), 16) % 5 == 0

    def _conflicting(self, record: EvidenceRecord, agent_id: str) -> EvidenceView:
        visible = self._copy_fields(record.field_values)
        selected = tuple(sorted(self.conflict_fields)) or self._first_scalar_field(record)
        conflicts = []
        for field_name in selected:
            if field_name in visible:
                visible[field_name] = self._conflict_value(visible[field_name])
                conflicts.append(field_name)
        return self._view(
            record,
            agent_id,
            visible,
            "field_slice",
            tuple(f"conflicting:{name}" for name in conflicts),
            tuple(conflicts),
        )

    @staticmethod
    def _first_scalar_field(record: EvidenceRecord) -> tuple[str, ...]:
        for field_name in sorted(record.field_values):
            value = record.field_values[field_name]
            if isinstance(value, (str, int, float, bool)) or value is None:
                return (field_name,)
        return ()

    @staticmethod
    def _conflict_value(value: Any) -> Any:
        if isinstance(value, bool):
            return not value
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return value + 1
        if value is None:
            return "CONFLICT::None"
        return f"CONFLICT::{value}"
