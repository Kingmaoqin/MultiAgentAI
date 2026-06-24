"""Phase-2 canonical event logger and schema (plan §3.1).

Every trial emits an append-only JSONL event log whose rows follow ONE canonical
schema, so that downstream trajectory / token / safety analysis can read any run
(single-agent, MAS, or RAVEL) uniformly.

Design notes
------------
* The repo already has two loggers: ``ravel_core.trial_logger.TrialLogger``
  (``event_type`` rows) and ``ravel_mas.trace.RuntimeTrace`` (``kind`` rows).
  Rather than replace them, this module defines the *canonical* Phase-2 schema
  and provides:
    - ``Phase2EventLogger`` for new code that writes canonical rows directly;
    - ``normalize_mas_trace`` / ``normalize_event`` adapters that map existing
      trace rows into the canonical schema so old runs remain analyzable.
* No implicit chain-of-thought is ever stored. ``validate_event`` actively
  rejects rows that carry a raw reasoning field (plan §3.1).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator

# --- canonical vocabularies (plan §3.1) -------------------------------------

EVENT_TYPES: frozenset[str] = frozenset({
    "llm_call", "tool_call", "tool_return", "ledger_ingest",
    "visibility_projection", "candidate_write", "gate_verdict",
    "reconcile_step", "commit", "abort", "final_eval",
})

AGENT_ROLES: frozenset[str] = frozenset({
    "supervisor", "policy_agent", "tool_worker", "commit_verifier",
    "single_agent", "user_simulator",
})

# Keys that would leak hidden chain-of-thought; never permitted in an event.
_FORBIDDEN_KEYS: frozenset[str] = frozenset({
    "chain_of_thought", "cot", "reasoning_trace", "hidden_reasoning",
    "scratchpad", "thinking",
})

# Header fields that must be present and non-null on every event.
_REQUIRED_HEADER: tuple[str, ...] = (
    "trial_id", "domain", "task_id", "method", "regime", "model", "seed",
    "event_index", "event_type", "agent_role",
)

# Full canonical field set with default values (plan §3.1).
_DEFAULTS: dict[str, Any] = {
    "trial_id": None, "domain": None, "task_id": None, "method": None,
    "regime": None, "model": None, "seed": None, "event_index": None,
    "event_type": None, "agent_role": None,
    "visible_evidence_ids": [], "hidden_evidence_ids": [],
    "tool_name": None, "tool_args": None, "tool_return_digest": None,
    "object_id": None, "object_version": None, "changed_fields": [],
    "candidate_write": None, "required_fields": [], "missing_fields": [],
    "stale_fields": [], "conflicting_fields": [],
    "traceability_ok": None, "policy_ok": None, "gate_decision": None,
    "reconcile_stage": None,
    "input_tokens": 0, "output_tokens": 0, "uncached_input_tokens": 0,
    "latency_sec": 0.0,
    "raw_prompt_hash": None, "visible_prompt_hash": None,
}

CANONICAL_KEYS: frozenset[str] = frozenset(_DEFAULTS)


def make_event(event_type: str, agent_role: str, **fields: Any) -> dict[str, Any]:
    """Build a canonical event dict, filling defaults. Does NOT validate."""
    event = dict(_DEFAULTS)
    event["event_type"] = event_type
    event["agent_role"] = agent_role
    event.update(fields)
    return event


def validate_event(event: dict[str, Any], *, strict_keys: bool = False) -> list[str]:
    """Return a list of schema violations for one event row (empty == valid).

    * required header fields present and non-null;
    * ``event_type`` / ``agent_role`` in the canonical vocabularies;
    * no forbidden chain-of-thought key;
    * token counts non-negative ints; uncached <= input;
    * with ``strict_keys`` also flag unknown keys.
    """
    errors: list[str] = []

    forbidden = _FORBIDDEN_KEYS & set(event)
    if forbidden:
        errors.append(f"forbidden chain-of-thought key(s): {sorted(forbidden)}")

    for key in _REQUIRED_HEADER:
        if key not in event or event[key] is None:
            errors.append(f"missing/null required header field: {key}")

    et = event.get("event_type")
    if et is not None and et not in EVENT_TYPES:
        errors.append(f"unknown event_type: {et!r}")
    ar = event.get("agent_role")
    if ar is not None and ar not in AGENT_ROLES:
        errors.append(f"unknown agent_role: {ar!r}")

    for tok_key in ("input_tokens", "output_tokens", "uncached_input_tokens"):
        val = event.get(tok_key, 0)
        if not isinstance(val, int) or isinstance(val, bool) or val < 0:
            errors.append(f"{tok_key} must be a non-negative int, got {val!r}")
    inp = event.get("input_tokens", 0)
    unc = event.get("uncached_input_tokens", 0)
    if isinstance(inp, int) and isinstance(unc, int) and unc > inp:
        errors.append(f"uncached_input_tokens ({unc}) > input_tokens ({inp})")

    if strict_keys:
        unknown = set(event) - CANONICAL_KEYS
        if unknown:
            errors.append(f"unknown keys: {sorted(unknown)}")

    return errors


@dataclass
class Phase2EventLogger:
    """Append-only canonical JSONL event logger for one trial.

    Header identity is bound once at construction; per-event callers pass only
    the event-specific fields. ``event_index`` auto-increments.
    """

    trial_id: str
    domain: str
    task_id: str
    method: str
    regime: str
    model: str
    seed: int
    output_path: Path
    validate: bool = True
    _index: int = field(default=0, init=False)
    _events: list[dict[str, Any]] = field(default_factory=list, init=False)

    def __post_init__(self) -> None:
        self.output_path = Path(self.output_path)
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        # truncate any stale file for this trial
        self.output_path.write_text("")

    def log(self, event_type: str, agent_role: str, **fields: Any) -> dict[str, Any]:
        event = make_event(event_type, agent_role, **fields)
        event.update({
            "trial_id": self.trial_id, "domain": self.domain,
            "task_id": self.task_id, "method": self.method,
            "regime": self.regime, "model": self.model, "seed": self.seed,
            "event_index": self._index,
        })
        if self.validate:
            errs = validate_event(event)
            if errs:
                raise ValueError(f"invalid event #{self._index}: {errs}")
        self._index += 1
        self._events.append(event)
        with self.output_path.open("a") as fh:
            fh.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")
        return event

    @property
    def events(self) -> list[dict[str, Any]]:
        return list(self._events)


# --- adapters for existing (legacy) trace rows ------------------------------

# ravel_mas.trace.RuntimeTrace "kind" -> canonical event_type
_MAS_KIND_TO_EVENT: dict[str, str] = {
    "llm_call": "llm_call",
    "message": "llm_call",        # typed inter-agent message ~ an llm decision
    "tool_call": "tool_call",
    "tool_return": "tool_return",
    "commit": "commit",
    "candidate_write": "candidate_write",
    "gate_verdict": "gate_verdict",
    "env": "ledger_ingest",       # exogenous perturbation / ingest
    "final_eval": "final_eval",
}


def normalize_event(
    row: dict[str, Any],
    *,
    header: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Map a single legacy trace row (``kind``- or ``event_type``-based) to the
    canonical schema. ``header`` supplies trial-level identity fields the legacy
    row lacks (domain/method/regime/model/seed)."""
    header = header or {}
    et = row.get("event_type") or _MAS_KIND_TO_EVENT.get(row.get("kind", ""), None)
    role = row.get("agent_role") or row.get("source_agent_id") or row.get("agent_id") or "single_agent"
    if role not in AGENT_ROLES:
        role = "single_agent"
    event = make_event(et or "llm_call", role)
    # carry through canonical fields present on the row
    for key in CANONICAL_KEYS:
        if key in row and row[key] is not None:
            event[key] = row[key]
    # identity
    for key in ("trial_id", "domain", "task_id", "method", "regime", "model", "seed"):
        if row.get(key) is not None:
            event[key] = row[key]
        elif header.get(key) is not None:
            event[key] = header[key]
    if event["event_type"] is None:
        event["event_type"] = et or "llm_call"
    return event


def normalize_mas_trace(
    rows: Iterable[dict[str, Any]],
    *,
    header: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Normalize and re-index an iterable of legacy trace rows."""
    out: list[dict[str, Any]] = []
    for i, row in enumerate(rows):
        ev = normalize_event(row, header=header)
        ev["event_index"] = i
        out.append(ev)
    return out


def read_events(path: str | Path) -> Iterator[dict[str, Any]]:
    """Yield JSON rows from a JSONL event log (skips blank lines)."""
    with Path(path).open() as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield json.loads(line)
