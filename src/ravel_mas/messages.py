"""Typed Agent-to-Agent messages and the MessageBus.

Implements Contract §2.3 / docs/mas/05_MESSAGE_SCHEMAS.md.

A function returning a Python object is NOT agent communication. Communication
is only counted when a typed Message is published on the MessageBus and recorded
as an event with a full envelope (message_id, source, target, type, logical_time,
parent_message_id, evidence_ids).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

# Allowed message types (Contract §2.3)
MESSAGE_TYPES = frozenset({
    "TaskAssignment",
    "Delegate",
    "PolicyRequest",
    "PolicyDecision",
    "EvidenceRequest",
    "EvidenceResult",
    "CandidateWrite",
    "ReconciliationRequest",
    "ReplanRequest",
    "AgentResult",
})

# Allowed Supervisor delegation actions (Contract §2.4 / §4.1)
SUPERVISOR_ACTIONS = frozenset({
    "Delegate", "RequestReconciliation", "AskUser", "Finish", "Abstain",
})


@dataclass(frozen=True)
class Message:
    """A single typed inter-agent message with full envelope."""

    message_id: str
    logical_time: int
    source_agent_id: str
    target_agent_id: str
    message_type: str
    payload: dict[str, Any] = field(default_factory=dict)
    evidence_ids: tuple[str, ...] = ()
    parent_message_id: Optional[str] = None

    def __post_init__(self) -> None:
        if self.message_type not in MESSAGE_TYPES:
            raise ValueError(f"unknown message_type: {self.message_type}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "message_id": self.message_id,
            "logical_time": self.logical_time,
            "source_agent_id": self.source_agent_id,
            "target_agent_id": self.target_agent_id,
            "message_type": self.message_type,
            "parent_message_id": self.parent_message_id,
            "evidence_ids": list(self.evidence_ids),
            "payload": self.payload,
        }


class MessageBus:
    """Routes typed messages between agents and records an append-only event log.

    The bus does NOT mutate the Evidence Ledger (Contract §5.2 separation).
    """

    def __init__(self) -> None:
        self._log: list[Message] = []
        self._counter = 0
        self._clock = 0

    def _next_id(self) -> str:
        self._counter += 1
        return f"m-{self._counter:06d}"

    def tick(self) -> int:
        self._clock += 1
        return self._clock

    def publish(
        self,
        *,
        source_agent_id: str,
        target_agent_id: str,
        message_type: str,
        payload: dict[str, Any] | None = None,
        evidence_ids: tuple[str, ...] = (),
        parent_message_id: str | None = None,
    ) -> Message:
        """Create, log, and return a typed message."""
        msg = Message(
            message_id=self._next_id(),
            logical_time=self.tick(),
            source_agent_id=source_agent_id,
            target_agent_id=target_agent_id,
            message_type=message_type,
            payload=dict(payload or {}),
            evidence_ids=tuple(evidence_ids),
            parent_message_id=parent_message_id,
        )
        self._log.append(msg)
        return msg

    @property
    def log(self) -> tuple[Message, ...]:
        return tuple(self._log)

    def messages_of_type(self, message_type: str) -> list[Message]:
        return [m for m in self._log if m.message_type == message_type]

    def messages_between(self, source: str, target: str) -> list[Message]:
        return [
            m for m in self._log
            if m.source_agent_id == source and m.target_agent_id == target
        ]
