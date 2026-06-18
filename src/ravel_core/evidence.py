"""Append-only evidence ledger primitives for RAVEL.

The ledger stores raw tool outputs outside the prompt-facing view. Prompt views
should receive headers, field slices, deltas, and pointers produced by
``visibility.py``.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping


def _normalize(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(k): _normalize(value[k]) for k in sorted(value)}
    if isinstance(value, list):
        return [_normalize(v) for v in value]
    if isinstance(value, tuple):
        return [_normalize(v) for v in value]
    return value


def canonical_json(value: Any) -> str:
    """Return deterministic JSON for structured payloads."""

    return json.dumps(
        _normalize(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def digest_value(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def freeze_value(value: Any) -> Any:
    """Recursively freeze mutable containers before storing ledger state."""

    if isinstance(value, Mapping):
        return MappingProxyType({str(k): freeze_value(value[k]) for k in sorted(value)})
    if isinstance(value, list):
        return tuple(freeze_value(v) for v in value)
    if isinstance(value, tuple):
        return tuple(freeze_value(v) for v in value)
    return value


def thaw_value(value: Any) -> Any:
    """Return a mutable prompt-facing copy of a frozen ledger value."""

    if isinstance(value, Mapping):
        return {k: thaw_value(v) for k, v in value.items()}
    if isinstance(value, tuple):
        return [thaw_value(v) for v in value]
    return value


def parse_payload(payload: Any) -> Any:
    if isinstance(payload, str):
        try:
            return json.loads(payload)
        except json.JSONDecodeError:
            return payload
    return payload


def flatten_fields(value: Any, prefix: str = "") -> dict[str, Any]:
    """Flatten structured payloads into deterministic field paths.

    Empty structures and scalars are represented as ``__value__`` unless a
    non-empty prefix was provided.
    """

    value = parse_payload(value)
    if isinstance(value, Mapping):
        if not value:
            return {prefix or "__value__": {}}
        out: dict[str, Any] = {}
        for key in sorted(value):
            child_prefix = f"{prefix}.{key}" if prefix else str(key)
            out.update(flatten_fields(value[key], child_prefix))
        return out
    if isinstance(value, list):
        if not value:
            return {prefix or "__value__": []}
        out = {}
        for idx, item in enumerate(value):
            child_prefix = f"{prefix}[{idx}]" if prefix else f"[{idx}]"
            out.update(flatten_fields(item, child_prefix))
        return out
    return {prefix or "__value__": value}


@dataclass(frozen=True)
class EvidenceRecord:
    evidence_id: str
    object_id: str
    tool_name: str
    raw_payload_pointer: str
    canonical_payload: str
    version: int
    logical_clock: int
    source_agent: str
    changed_fields: tuple[str, ...]
    digest: str
    dependencies: tuple[str, ...] = ()
    risk_tag: str = "normal"
    conflict_flag: bool = False
    field_values: Mapping[str, Any] = field(default_factory=dict)


class EvidenceLedger:
    """Append-only evidence ledger with object-level versions."""

    def __init__(self) -> None:
        self._records: list[EvidenceRecord] = []
        self._object_versions: dict[str, int] = {}
        self._latest_fields: dict[tuple[str, str], tuple[int, Any, str]] = {}
        self._clock = 0

    @property
    def records(self) -> tuple[EvidenceRecord, ...]:
        return tuple(self._records)

    @property
    def logical_clock(self) -> int:
        return self._clock

    def ingest(
        self,
        *,
        object_id: str,
        tool_name: str,
        payload: Any,
        source_agent: str,
        raw_payload_pointer: str | None = None,
        dependencies: tuple[str, ...] = (),
        risk_tag: str = "normal",
        conflict_flag: bool = False,
    ) -> EvidenceRecord:
        parsed = parse_payload(payload)
        fields = {
            field_name: freeze_value(value)
            for field_name, value in flatten_fields(parsed).items()
        }
        previous = {
            field_name: self._latest_fields.get((object_id, field_name))
            for field_name in fields
        }
        changed = tuple(
            sorted(
                field_name
                for field_name, value in fields.items()
                if previous[field_name] is None or previous[field_name][1] != value
            )
        )

        version = self._object_versions.get(object_id, 0) + 1
        self._object_versions[object_id] = version
        self._clock += 1
        payload_digest = digest_value(parsed)
        evidence_id = f"ev-{self._clock:06d}-{payload_digest[:12]}"
        pointer = raw_payload_pointer or f"ledger://{evidence_id}"

        record = EvidenceRecord(
            evidence_id=evidence_id,
            object_id=object_id,
            tool_name=tool_name,
            raw_payload_pointer=pointer,
            canonical_payload=canonical_json(parsed),
            version=version,
            logical_clock=self._clock,
            source_agent=source_agent,
            changed_fields=changed,
            digest=payload_digest,
            dependencies=dependencies,
            risk_tag=risk_tag,
            conflict_flag=conflict_flag,
            field_values=MappingProxyType(dict(fields)),
        )
        self._records.append(record)
        for field_name, value in fields.items():
            self._latest_fields[(object_id, field_name)] = (
                version,
                value,
                evidence_id,
            )
        return record

    def get(self, evidence_id: str) -> EvidenceRecord | None:
        for record in self._records:
            if record.evidence_id == evidence_id:
                return record
        return None

    def latest(self, object_id: str) -> EvidenceRecord | None:
        for record in reversed(self._records):
            if record.object_id == object_id:
                return record
        return None

    def latest_field(self, object_id: str, field_name: str) -> tuple[int, Any, str] | None:
        return self._latest_fields.get((object_id, field_name))

    def object_version(self, object_id: str) -> int:
        return self._object_versions.get(object_id, 0)
