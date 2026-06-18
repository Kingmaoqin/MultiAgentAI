"""Per-trial structured logger for RAVEL experiments.

Records all fields required by Proposal §17 as an append-only event log
(JSONL) plus a final trial summary JSON.  The logger is passive: it only
records what callers push into it.  It does not call benchmark code or LLMs.

Required fields (§17):
    trial_id, task_id, domain, task_split, method, regime, model, checkpoint,
    server_config, seed, mutation_seed, user_simulator_seed, prompt_hashes,
    tool_schema_hash, benchmark_commit, task_data_hash,
    agent-visible messages, agent-visible evidence IDs,
    tool calls, tool arguments, tool outputs, object versions,
    environment mutations, candidate writes, required fields, gate verdicts,
    reconciliation steps, executed writes,
    input tokens, cached input tokens, uncached input tokens, output tokens,
    latency, errors, final database state, official reward, all safety metrics.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def _sha256_str(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _json_safe(value: Any) -> Any:
    """Return a replay-friendly JSON value, stringifying unsupported objects."""
    return json.loads(json.dumps(value, sort_keys=True, default=str))


@dataclass
class TokenRecord:
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0

    @property
    def uncached_input_tokens(self) -> int:
        return max(0, self.input_tokens - self.cached_input_tokens)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def add(self, other: "TokenRecord") -> None:
        self.input_tokens += other.input_tokens
        self.cached_input_tokens += other.cached_input_tokens
        self.output_tokens += other.output_tokens

    def to_dict(self) -> dict[str, int]:
        return {
            "input_tokens": self.input_tokens,
            "cached_input_tokens": self.cached_input_tokens,
            "uncached_input_tokens": self.uncached_input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
        }


@dataclass
class TrialMeta:
    """Immutable trial identification and configuration (§17 header fields)."""

    trial_id: str
    task_id: str
    domain: str
    task_split: str  # "dev" | "pilot" | "held_out"
    method: str      # e.g. "MAS-FullSync", "RAVEL-Full"
    regime: str      # e.g. "FullSync", "Delayed", "FieldMask", "ConflictingView"
    model: str
    checkpoint: str
    server_config: dict[str, Any]
    seed: int
    mutation_seed: int
    user_simulator_seed: int
    prompt_hashes: dict[str, str]  # role → sha256
    tool_schema_hash: str
    benchmark_commit: str
    task_data_hash: str


class TrialLogger:
    """Append-only per-trial event log and summary writer.

    Usage::

        logger = TrialLogger(meta, output_dir=Path("results/raw"))
        logger.log_agent_observation(agent_id="worker_1", evidence_ids=["ev-000001"])
        logger.log_tool_call(agent_id="worker_1", tool="get_reservation_details",
                             arguments={"id": "R1"}, output={...})
        logger.log_candidate_write(agent_id="worker_1", candidate={...}, gate_verdict="commit")
        logger.log_executed_write(tool="cancel_reservation", arguments={...}, result={...})
        logger.log_tokens(TokenRecord(input_tokens=512, output_tokens=64))
        logger.finish(official_reward=1.0, final_db_state={...}, safety_metrics={...})
    """

    def __init__(self, meta: TrialMeta, output_dir: Path) -> None:
        self._meta = meta
        self._output_dir = output_dir
        self._events: list[dict[str, Any]] = []
        self._token_total = TokenRecord()
        self._token_write_window = TokenRecord()
        self._tool_calls: list[dict[str, Any]] = []
        self._candidate_writes: list[dict[str, Any]] = []
        self._executed_writes: list[dict[str, Any]] = []
        self._mutations: list[dict[str, Any]] = []
        self._gate_verdicts: list[str] = []
        self._reconciliation_steps: list[dict[str, Any]] = []
        self._errors: list[str] = []
        self._start_time = time.monotonic()
        output_dir.mkdir(parents=True, exist_ok=True)
        self._event_file = output_dir / f"{meta.trial_id}_events.jsonl"

    def _push_event(self, event_type: str, payload: dict[str, Any]) -> None:
        event = {
            "trial_id": self._meta.trial_id,
            "t": time.monotonic() - self._start_time,
            "event_type": event_type,
            **payload,
        }
        self._events.append(event)
        with self._event_file.open("a") as fh:
            fh.write(json.dumps(event, ensure_ascii=False) + "\n")

    def log_agent_observation(
        self,
        agent_id: str,
        evidence_ids: list[str],
        visible_fields: dict[str, Any] | None = None,
        message_hash: str | None = None,
    ) -> None:
        """Record what evidence IDs and fields an agent actually saw."""
        self._push_event("agent_observation", {
            "agent_id": agent_id,
            "evidence_ids": evidence_ids,
            "visible_field_keys": sorted(visible_fields or {}),
            "visible_fields": _json_safe(visible_fields or {}),
            "message_hash": message_hash,
        })

    def log_tool_call(
        self,
        agent_id: str,
        tool: str,
        arguments: dict[str, Any],
        output: Any,
        object_versions: dict[str, int] | None = None,
    ) -> None:
        """Record a tool invocation and its output."""
        record = {
            "agent_id": agent_id,
            "tool": tool,
            "arguments": arguments,
            "output_hash": _sha256_str(json.dumps(output, sort_keys=True, default=str))[:16],
            "output": _json_safe(output),
            "object_versions": object_versions or {},
        }
        self._tool_calls.append(record)
        self._push_event("tool_call", record)

    def log_environment_mutation(
        self,
        object_id: str,
        field_name: str,
        before: Any,
        after: Any,
        trigger_step: int,
    ) -> None:
        """Record an exogenous state mutation (§8)."""
        record = {
            "object_id": object_id,
            "field_name": field_name,
            "before_hash": _sha256_str(json.dumps(before, default=str))[:16],
            "after_hash": _sha256_str(json.dumps(after, default=str))[:16],
            "before": _json_safe(before),
            "after": _json_safe(after),
            "trigger_step": trigger_step,
        }
        self._mutations.append(record)
        self._push_event("environment_mutation", record)

    def log_candidate_write(
        self,
        agent_id: str,
        candidate: dict[str, Any],
        required_fields: list[dict[str, Any]],
        gate_verdict: str,
        gate_reasons: list[str],
    ) -> None:
        """Record a candidate write proposal and the gate verdict."""
        record = {
            "agent_id": agent_id,
            "action": candidate.get("action"),
            "arguments": _json_safe(candidate.get("arguments", {})),
            "target_objects": candidate.get("target_objects", []),
            "referenced_evidence_ids": candidate.get("referenced_evidence_ids", []),
            "claimed_preconditions": candidate.get("claimed_preconditions", []),
            "required_fields": required_fields,
            "gate_verdict": gate_verdict,
            "gate_reasons": gate_reasons,
        }
        self._candidate_writes.append(record)
        self._gate_verdicts.append(gate_verdict)
        self._push_event("candidate_write", record)

    def log_reconciliation_step(self, step: dict[str, Any]) -> None:
        """Record one rung of the ARB ladder."""
        self._reconciliation_steps.append(step)
        self._push_event("reconciliation_step", step)

    def log_executed_write(
        self,
        tool: str,
        arguments: dict[str, Any],
        result: Any,
        evidence_valid: bool,
        was_stale: bool = False,
        was_conflicting: bool = False,
    ) -> None:
        """Record a write that was actually executed (post-gate commit)."""
        record = {
            "tool": tool,
            "arguments": arguments,
            "result_hash": _sha256_str(json.dumps(result, default=str))[:16],
            "result": _json_safe(result),
            "evidence_valid": evidence_valid,
            "was_stale": was_stale,
            "was_conflicting": was_conflicting,
        }
        self._executed_writes.append(record)
        self._push_event("executed_write", record)

    def log_tokens(
        self,
        tokens: TokenRecord,
        in_write_window: bool = False,
    ) -> None:
        """Accumulate token counts. Set in_write_window for candidate-write steps."""
        self._token_total.add(tokens)
        if in_write_window:
            self._token_write_window.add(tokens)
        self._push_event("tokens", {
            **tokens.to_dict(),
            "in_write_window": in_write_window,
        })

    def log_error(self, message: str) -> None:
        self._errors.append(message)
        self._push_event("error", {"message": message})

    def finish(
        self,
        official_reward: float | None,
        final_db_state: dict[str, Any],
        safety_metrics: dict[str, Any],
        policy_violations: list[str] | None = None,
        oracle_safety_verdicts: list[dict[str, Any]] | None = None,
        trial_outcome: dict[str, Any] | None = None,
    ) -> Path:
        """Write the final trial summary JSON and return its path."""
        wall_latency = time.monotonic() - self._start_time
        summary: dict[str, Any] = {
            # Identity (§17)
            "trial_id": self._meta.trial_id,
            "task_id": self._meta.task_id,
            "domain": self._meta.domain,
            "task_split": self._meta.task_split,
            "method": self._meta.method,
            "regime": self._meta.regime,
            "model": self._meta.model,
            "checkpoint": self._meta.checkpoint,
            "server_config": self._meta.server_config,
            "seed": self._meta.seed,
            "mutation_seed": self._meta.mutation_seed,
            "user_simulator_seed": self._meta.user_simulator_seed,
            "prompt_hashes": self._meta.prompt_hashes,
            "tool_schema_hash": self._meta.tool_schema_hash,
            "benchmark_commit": self._meta.benchmark_commit,
            "task_data_hash": self._meta.task_data_hash,
            # Trajectory counts
            "n_tool_calls": len(self._tool_calls),
            "n_candidate_writes": len(self._candidate_writes),
            "n_executed_writes": len(self._executed_writes),
            "n_environment_mutations": len(self._mutations),
            "n_reconciliation_steps": len(self._reconciliation_steps),
            "gate_verdicts": self._gate_verdicts,
            "tool_calls": self._tool_calls,
            "candidate_writes": self._candidate_writes,
            "executed_writes": self._executed_writes,
            "environment_mutations": self._mutations,
            "reconciliation_steps": self._reconciliation_steps,
            # Token accounting (§6.2)
            "tokens": {
                "total": self._token_total.to_dict(),
                "write_window": self._token_write_window.to_dict(),
            },
            # Latency
            "wall_latency_s": wall_latency,
            # Errors
            "errors": self._errors,
            # Final state
            "final_db_state_hash": _sha256_str(
                json.dumps(final_db_state, sort_keys=True, default=str)
            )[:32],
            "final_db_state": _json_safe(final_db_state),
            "official_reward": official_reward,
            "policy_violations": policy_violations or [],
            "oracle_safety_verdicts": _json_safe(oracle_safety_verdicts or []),
            "trial_outcome": _json_safe(trial_outcome or {}),
            # Safety metrics (§6.3)
            "safety_metrics": safety_metrics,
            # Event log pointer
            "event_log": str(self._event_file),
        }

        summary_path = self._output_dir / f"{self._meta.trial_id}_summary.json"
        with summary_path.open("w") as fh:
            json.dump(summary, fh, indent=2, ensure_ascii=False)
        return summary_path
