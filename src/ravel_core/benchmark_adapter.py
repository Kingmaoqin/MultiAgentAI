"""Tau2 benchmark adapter for RAVEL.

Connects tau2's official runner/evaluator to the RAVEL evidence ledger,
visibility middleware, and commit gate WITHOUT modifying any tau2 source file.

Integration points (§1.3):
    - wrapper:      RAVELRunWrapper wraps tau2.runner.run_single_task
    - middleware:   tool_result_hook intercepts tool outputs before they reach agents
    - adapter:      VisibilityAdapter projects ledger entries per regime for each agent
    - callback:     on_candidate_write fires before any high-risk tool execution
    - external ledger: EvidenceLedger is owned by the wrapper, not tau2

Benchmark integrity constraints (§1.3):
    - tau2 task objectives, policy text, database initialisation, tool semantics,
      user simulator goals, official final-state evaluator, and ground truth
      MUST NOT be modified.
    - FullSync regime MUST produce identical official_reward to an unmodified run.

Usage::

    from ravel_core.benchmark_adapter import RAVELRunConfig, VisibilityAdapter
    config = RAVELRunConfig(
        regime="FullSync",
        seed=42,
        action_schemas=AIRLINE_SCHEMAS,
        output_dir=Path("results/raw/run_001"),
    )
    adapter = VisibilityAdapter(config)
    # adapter.on_tool_result(agent_id, tool_name, payload)
    # adapter.on_candidate_write(agent_id, candidate)
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .commit_gate import (
    ActionSchema,
    CandidateWrite,
    CommitGate,
    GateDecision,
    VisibleEvidenceState,
)
from .evidence import EvidenceLedger
from .metrics import SafetyMetricsAccumulator
from .trial_logger import TokenRecord
from .mse_router import AgentContext, MSERouter
from .trial_logger import TrialLogger, TrialMeta
from .visibility import EvidenceView, VisibilityPolicy


@dataclass
class RAVELRunConfig:
    """Frozen configuration for one RAVEL experimental run."""

    trial_id: str
    task_id: str
    domain: str
    task_split: str
    method: str
    regime: str  # FullSync | Delayed | FieldMask | ConflictingView
    model: str
    checkpoint: str
    server_config: dict[str, Any]
    seed: int
    mutation_seed: int
    user_simulator_seed: int
    benchmark_commit: str
    task_data_hash: str
    action_schemas: dict[str, ActionSchema]
    output_dir: Path
    max_reconciliation_stage: int = 4
    delay: int = 1
    mask_fields: set[str] = field(default_factory=set)
    conflict_fields: set[str] = field(default_factory=set)
    # High-risk action names; all others are treated as read/low-risk
    high_risk_actions: set[str] = field(default_factory=set)
    # Prompt hashes: populated by caller after prompts are frozen
    prompt_hashes: dict[str, str] = field(default_factory=dict)
    tool_schema_hash: str = ""


class VisibilityAdapter:
    """The central RAVEL wrapper for a single tau2 trial.

    Call hooks in the order they occur in the benchmark runner:
        on_tool_result(agent_id, tool_name, object_id, payload)
        on_candidate_write(agent_id, candidate_dict) → GateDecision
        on_executed_write(tool, arguments, result, evidence_valid)
        on_environment_mutation(object_id, field, before, after, step)
        on_tokens(agent_id, token_record, in_write_window)
        on_trial_complete(official_reward, final_db_state, policy_violations)

    The adapter owns the ledger and the logger.  It does not call tau2 directly.
    """

    def __init__(self, config: RAVELRunConfig) -> None:
        self._config = config
        self._ledger = EvidenceLedger()
        self._gate = CommitGate(config.action_schemas)
        self._router = MSERouter(self._ledger)
        self._safety_acc = SafetyMetricsAccumulator()
        self._event_index = 0
        self._policy = VisibilityPolicy(
            regime=config.regime,
            delay=config.delay,
            seed=config.seed,
            mask_fields=set(config.mask_fields),
            conflict_fields=set(config.conflict_fields),
        )
        self._visible_views: dict[str, list[EvidenceView]] = {}
        self._allowed_write_keys: set[tuple[str, str]] = set()

        meta = TrialMeta(
            trial_id=config.trial_id,
            task_id=config.task_id,
            domain=config.domain,
            task_split=config.task_split,
            method=config.method,
            regime=config.regime,
            model=config.model,
            checkpoint=config.checkpoint,
            server_config=config.server_config,
            seed=config.seed,
            mutation_seed=config.mutation_seed,
            user_simulator_seed=config.user_simulator_seed,
            prompt_hashes=config.prompt_hashes,
            tool_schema_hash=config.tool_schema_hash,
            benchmark_commit=config.benchmark_commit,
            task_data_hash=config.task_data_hash,
        )
        self._logger = TrialLogger(meta, config.output_dir)

    # ------------------------------------------------------------------
    # Public hooks
    # ------------------------------------------------------------------

    def on_tool_result(
        self,
        agent_id: str,
        tool_name: str,
        object_id: str,
        payload: Any,
        risk_tag: str = "normal",
    ) -> EvidenceView:
        """Ingest a tool result into the ledger and project it for agent_id.

        Returns the visibility-projected view that should be included in the
        agent's prompt context — NOT the raw payload.
        """
        self._event_index += 1
        record = self._ledger.ingest(
            object_id=object_id,
            tool_name=tool_name,
            payload=payload,
            source_agent=agent_id,
            risk_tag=risk_tag,
        )
        view = self._policy.project(
            record, agent_id=agent_id, event_index=self._event_index
        )
        self._visible_views.setdefault(agent_id, []).append(view)
        self._logger.log_agent_observation(
            agent_id=agent_id,
            evidence_ids=[record.evidence_id],
            visible_fields=view.visible_fields,
        )
        self._logger.log_tool_call(
            agent_id=agent_id,
            tool=tool_name,
            arguments={"object_id": object_id},
            output={"evidence_id": record.evidence_id, "version": record.version},
            object_versions={object_id: record.version},
        )
        return view

    def on_candidate_write(
        self,
        agent_id: str,
        candidate_dict: dict[str, Any],
    ) -> GateDecision:
        """Validate a candidate write through the commit gate.

        The worker MUST call this before executing any high-risk write tool.
        If the gate returns verdict != "commit", the write MUST NOT proceed.
        """
        candidate = CandidateWrite(
            action=candidate_dict["action"],
            arguments=candidate_dict.get("arguments", {}),
            target_objects=tuple(candidate_dict.get("target_objects", [])),
            referenced_evidence_ids=tuple(
                candidate_dict.get("referenced_evidence_ids", [])
            ),
            claimed_preconditions=tuple(
                candidate_dict.get("claimed_preconditions", [])
            ),
        )
        visible_state = VisibleEvidenceState.from_views(
            self._visible_views.get(agent_id, [])
        )
        decision = self._gate.verify(
            candidate, ledger=self._ledger, visible_state=visible_state
        )
        self._logger.log_candidate_write(
            agent_id=agent_id,
            candidate=candidate_dict,
            required_fields=[
                {"object_id": r.object_id, "field": r.field}
                for r in decision.checked_fields
            ],
            gate_verdict=decision.verdict,
            gate_reasons=list(decision.reasons),
        )
        if decision.allowed and self._requires_gate(candidate.action):
            self._allowed_write_keys.add(
                self._write_key(candidate.action, dict(candidate.arguments))
            )
        return decision

    def on_executed_write(
        self,
        tool: str,
        arguments: dict[str, Any],
        result: Any,
        evidence_valid: bool,
        was_stale: bool = False,
        was_conflicting: bool = False,
    ) -> None:
        """Record a write that was actually committed to the environment."""
        if self._requires_gate(tool):
            key = self._write_key(tool, arguments)
            if key not in self._allowed_write_keys:
                message = f"executed_write_without_allowed_gate:{tool}"
                self._logger.log_error(message)
                raise RuntimeError(message)
            self._allowed_write_keys.remove(key)

        self._safety_acc.record_executed_write(
            evidence_valid=evidence_valid,
            was_stale=was_stale,
            was_conflicting=was_conflicting,
        )
        self._logger.log_executed_write(
            tool=tool, arguments=arguments, result=result,
            evidence_valid=evidence_valid,
            was_stale=was_stale,
            was_conflicting=was_conflicting,
        )

    def on_environment_mutation(
        self,
        object_id: str,
        field_name: str,
        before: Any,
        after: Any,
        trigger_step: int,
    ) -> None:
        """Record an exogenous state mutation from the benchmark (§8)."""
        self._logger.log_environment_mutation(
            object_id=object_id, field_name=field_name,
            before=before, after=after, trigger_step=trigger_step,
        )

    def on_tokens(
        self,
        agent_id: str,  # noqa: ARG002 — kept for future per-agent accounting
        tokens: TokenRecord,
        in_write_window: bool = False,
    ) -> None:
        self._logger.log_tokens(tokens, in_write_window=in_write_window)

    def on_trial_complete(
        self,
        official_reward: float | None,
        final_db_state: dict[str, Any],
        policy_violations: list[str] | None = None,
        oracle_safety_verdicts: list[dict[str, Any]] | None = None,
    ) -> Path:
        """Finalise the trial; return path to summary JSON."""
        if oracle_safety_verdicts:
            for verdict in oracle_safety_verdicts:
                self._safety_acc.record_blocked_candidate(
                    oracle_was_conflicting=verdict.get("oracle_conflicting", False),
                    ravel_caught=verdict.get("ravel_caught", False),
                    oracle_safe_and_necessary=verdict.get("oracle_safe_necessary", False),
                )

        safety_metrics = self._safety_acc.to_dict()
        return self._logger.finish(
            official_reward=official_reward,
            final_db_state=final_db_state,
            safety_metrics=safety_metrics,
            policy_violations=policy_violations,
            oracle_safety_verdicts=oracle_safety_verdicts,
        )

    def _requires_gate(self, action: str) -> bool:
        """Return whether this action is treated as high-risk in this trial."""
        if action in self._config.high_risk_actions:
            return True
        return action in self._config.action_schemas

    @staticmethod
    def _write_key(action: str, arguments: dict[str, Any]) -> tuple[str, str]:
        return (
            action,
            json.dumps(arguments, sort_keys=True, separators=(",", ":"), default=str),
        )

    # ------------------------------------------------------------------
    # Invariant assertions (used in tests, §9.3)
    # ------------------------------------------------------------------

    def assert_ledger_integrity(self) -> None:
        """Raise AssertionError if the ledger has been mutated by a view."""
        for record in self._ledger.records:
            # Field values must still be frozen MappingProxyType.
            from types import MappingProxyType
            assert isinstance(record.field_values, MappingProxyType), (
                f"Ledger field_values for {record.evidence_id} is no longer frozen"
            )

    @property
    def ledger(self) -> EvidenceLedger:
        return self._ledger

    @property
    def logger(self) -> TrialLogger:
        return self._logger

    @property
    def safety_accumulator(self) -> SafetyMetricsAccumulator:
        return self._safety_acc
