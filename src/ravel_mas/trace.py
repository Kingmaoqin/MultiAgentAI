"""RuntimeTrace — structured per-call/per-message/per-commit event log.

Implements Contract §14. No hidden chain-of-thought is stored; only structured
plans, reason codes, typed decisions, evidence links, and token counts.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from typing import Any, Optional


@dataclass
class LLMCallRecord:
    logical_step: int
    agent_id: str
    agent_role: str
    model_name: str
    system_prompt_hash: str
    context_hash: str
    visible_evidence_ids: list[str]
    visible_object_versions: dict[str, int]
    input_tokens: int
    output_tokens: int
    output_kind: str            # "json" | "tool_call" | "text"
    reason_code: str = ""


@dataclass
class TraceEvent:
    kind: str                   # "llm_call" | "message" | "delegation" | "commit" | "tool" | "env"
    logical_step: int
    data: dict[str, Any] = field(default_factory=dict)


class RuntimeTrace:
    def __init__(self, trial_id: str, task_id: str) -> None:
        self.trial_id = trial_id
        self.task_id = task_id
        self.events: list[TraceEvent] = []
        self.llm_calls: list[LLMCallRecord] = []
        self._step = 0

    def step(self) -> int:
        self._step += 1
        return self._step

    @property
    def current_step(self) -> int:
        return self._step

    def record_llm_call(self, rec: LLMCallRecord) -> None:
        self.llm_calls.append(rec)
        self.events.append(TraceEvent(
            kind="llm_call", logical_step=rec.logical_step,
            data={
                "agent_id": rec.agent_id,
                "agent_role": rec.agent_role,
                "model_name": rec.model_name,
                "system_prompt_hash": rec.system_prompt_hash,
                "context_hash": rec.context_hash,
                "visible_evidence_ids": rec.visible_evidence_ids,
                "visible_object_versions": rec.visible_object_versions,
                "input_tokens": rec.input_tokens,
                "output_tokens": rec.output_tokens,
                "output_kind": rec.output_kind,
                "reason_code": rec.reason_code,
            },
        ))

    def record_event(self, kind: str, data: dict[str, Any]) -> None:
        self.events.append(TraceEvent(kind=kind, logical_step=self._step, data=data))

    # --- queries used by architecture tests ---

    @property
    def llm_agent_ids(self) -> set[str]:
        return {c.agent_id for c in self.llm_calls}

    @property
    def internal_agent_ids(self) -> set[str]:
        # user_simulator is a benchmark component, never recorded as internal (Contract §2.7)
        return {c.agent_id for c in self.llm_calls if c.agent_id != "user_simulator"}

    def events_of_kind(self, kind: str) -> list[TraceEvent]:
        return [e for e in self.events if e.kind == kind]

    def to_jsonl(self) -> str:
        lines = []
        for e in self.events:
            lines.append(json.dumps({
                "trial_id": self.trial_id,
                "task_id": self.task_id,
                "kind": e.kind,
                "logical_step": e.logical_step,
                **e.data,
            }, default=str))
        return "\n".join(lines)

    def to_readable(self) -> str:
        out = [f"# Runtime trace — trial={self.trial_id} task={self.task_id}", ""]
        for e in self.events:
            if e.kind == "llm_call":
                out.append(
                    f"[step {e.logical_step}] LLM_CALL agent={e.data['agent_id']} "
                    f"role={e.data['agent_role']} prompt#{e.data['system_prompt_hash'][:8]} "
                    f"out={e.data['output_kind']} in_tok={e.data['input_tokens']} "
                    f"out_tok={e.data['output_tokens']} reason={e.data.get('reason_code','')}"
                )
            elif e.kind == "message":
                out.append(
                    f"[step {e.logical_step}] MESSAGE {e.data.get('source_agent_id')}→"
                    f"{e.data.get('target_agent_id')} type={e.data.get('message_type')}"
                )
            elif e.kind == "delegation":
                out.append(
                    f"[step {e.logical_step}] DELEGATION supervisor→{e.data.get('target_agent')} "
                    f"subgoal={e.data.get('subgoal','')[:60]}"
                )
            elif e.kind == "commit":
                out.append(
                    f"[step {e.logical_step}] COMMIT_SERVICE verdict={e.data.get('verdict')} "
                    f"action={e.data.get('action')} reasons={e.data.get('reasons')}"
                )
            elif e.kind == "tool":
                out.append(
                    f"[step {e.logical_step}] TOOL {e.data.get('tool_name')} "
                    f"by={e.data.get('agent_id')} kind={e.data.get('tool_kind')}"
                )
            elif e.kind == "env":
                out.append(f"[step {e.logical_step}] ENV {e.data.get('note')}")
        return "\n".join(out)
