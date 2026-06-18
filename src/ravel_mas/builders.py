"""Team builders and architecture-proof scenarios.

create_team(): assemble a RAVELTeam from a model client, enforcing tool allowlists.
run_architecture_proof(): deterministic FakeModelClient run proving Gate-1 identity,
delegation, independent state, and tool-permission isolation WITHOUT tau2.
"""

from __future__ import annotations

from typing import Any, Optional

from .agents import (
    PolicyAgent,
    SemanticVerifierAgent,
    SupervisorAgent,
    ToolWorkerAgent,
)
from .messages import MessageBus
from .model_client import BaseModelClient, FakeModelClient, ModelResponse
from .team import RAVELTeam, TeamConfig
from .trace import RuntimeTrace

# Distinct system prompts → distinct prompt hashes (Contract §10.3)
SUPERVISOR_PROMPT = (
    "You are the SUPERVISOR agent. You never call business tools. You decompose "
    "the user goal, maintain the global plan, and dynamically delegate to "
    "policy_agent or tool_worker. You output only structured delegation JSON."
)
POLICY_PROMPT = (
    "You are the POLICY agent. You interpret domain policy and produce the "
    "required evidence schema for a candidate action. You never hold write tools."
)
WORKER_PROMPT = (
    "You are the TOOL WORKER agent. You call read tools and may only PROPOSE "
    "writes via propose_candidate_write. You never execute real write tools."
)
VERIFIER_PROMPT = (
    "You are the SEMANTIC VERIFIER agent. You give an advisory verdict on a "
    "candidate write. You cannot authorize any write."
)

PROPOSE_CANDIDATE_WRITE_TOOL = {
    "type": "function",
    "function": {
        "name": "propose_candidate_write",
        "description": "Propose a state-changing action for the CommitService to validate. "
                       "Does NOT execute the action.",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {"type": "string"},
                "arguments": {"type": "object"},
                "target_objects": {"type": "array", "items": {"type": "string"}},
                "referenced_evidence_ids": {"type": "array", "items": {"type": "string"}},
                "expected_versions": {"type": "object"},
            },
            "required": ["action", "arguments"],
        },
    },
}


def create_team(
    *,
    model_client: BaseModelClient,
    model_name: str,
    read_tools: Optional[list[str]] = None,
    write_tools: Optional[list[str]] = None,
    policy_tools: Optional[list[str]] = None,
    config: Optional[TeamConfig] = None,
    with_verifier: bool = True,
    ledger: Any = None,
    view_builder: Any = None,
    commit_service: Any = None,
) -> RAVELTeam:
    """Assemble a team with enforced tool allowlists (Contract §2.6).

    Worker allowlist = read_tools + propose_candidate_write (NO real write tools).
    Real write_tools are NOT given to any agent; only CommitService holds them.
    """
    read_tools = read_tools or []
    write_tools = write_tools or []
    policy_tools = policy_tools or []

    supervisor = SupervisorAgent(
        agent_id="supervisor", system_prompt=SUPERVISOR_PROMPT,
        model_client=model_client, model_name=model_name, allowed_tools=[],
    )
    policy_agent = PolicyAgent(
        agent_id="policy_agent", system_prompt=POLICY_PROMPT,
        model_client=model_client, model_name=model_name,
        allowed_tools=list(policy_tools),
    )
    tool_worker = ToolWorkerAgent(
        agent_id="tool_worker", system_prompt=WORKER_PROMPT,
        model_client=model_client, model_name=model_name,
        # Allowlist excludes real write tools by construction.
        allowed_tools=list(read_tools) + ["propose_candidate_write"],
    )
    verifier = None
    if with_verifier:
        verifier = SemanticVerifierAgent(
            agent_id="semantic_verifier", system_prompt=VERIFIER_PROMPT,
            model_client=model_client, model_name=model_name, allowed_tools=[],
        )

    team = RAVELTeam(
        supervisor=supervisor, policy_agent=policy_agent, tool_worker=tool_worker,
        semantic_verifier=verifier, config=config or TeamConfig(),
        ledger=ledger, view_builder=view_builder, commit_service=commit_service,
    )
    # Record the real write tools as belonging to the commit service only.
    team.real_write_tools = list(write_tools)  # type: ignore[attr-defined]
    return team


# ---------------------------------------------------------------------------
# Gate-1 architecture proof (deterministic, no tau2)
# ---------------------------------------------------------------------------

def _supervisor_script(idx: int, messages: list[dict]) -> ModelResponse:
    """Supervisor: delegate to policy, then worker, then finish."""
    seq = [
        ModelResponse(content=(
            '{"action":"Delegate","target_agent":"policy_agent",'
            '"subgoal":"determine cancellation requirements",'
            '"required_objects":["reservation:R1"],"evidence_refs":[],'
            '"reason_code":"policy_check_required"}'), input_tokens=120, output_tokens=40),
        ModelResponse(content=(
            '{"action":"Delegate","target_agent":"tool_worker",'
            '"subgoal":"gather reservation status then propose cancel",'
            '"required_objects":["reservation:R1"],"evidence_refs":[],'
            '"reason_code":"evidence_collection"}'), input_tokens=130, output_tokens=42),
        ModelResponse(content=(
            '{"action":"Finish","target_agent":null,"subgoal":"done",'
            '"required_objects":[],"evidence_refs":[],"reason_code":"goal_met"}'),
            input_tokens=90, output_tokens=20),
    ]
    return seq[min(idx, len(seq) - 1)]


def _policy_script(idx: int, messages: list[dict]) -> ModelResponse:
    return ModelResponse(content=(
        '{"action":"cancel_reservation","policy_status":"conditionally_allowed",'
        '"required_evidence":[{"object_selector":"reservation:R1","field":"status",'
        '"freshness":"latest"}],"required_user_confirmations":["explicit_cancel"],'
        '"policy_checks":["not_already_cancelled"],"ambiguities":[]}'),
        input_tokens=110, output_tokens=55)


def _worker_script(idx: int, messages: list[dict]) -> ModelResponse:
    # Worker proposes a candidate write (never executes it).
    return ModelResponse(
        content="",
        tool_calls=[{
            "name": "propose_candidate_write",
            "arguments": (
                '{"action":"cancel_reservation","arguments":{"reservation_id":"R1"},'
                '"target_objects":["reservation:R1"],'
                '"referenced_evidence_ids":["ev-1"],"expected_versions":{"reservation:R1":1}}'
            ),
        }],
        input_tokens=140, output_tokens=48)


def run_architecture_proof() -> RuntimeTrace:
    """Deterministic Gate-1 proof: three distinct LLM agents, dynamic delegation,
    typed messages, independent state, worker proposes (not executes) a write."""
    client = FakeModelClient(scripts={
        "supervisor": _supervisor_script,
        "policy_agent": _policy_script,
        "tool_worker": _worker_script,
    })
    team = create_team(
        model_client=client, model_name="fake/model",
        read_tools=["get_reservation_details"],
        write_tools=["cancel_reservation", "book_reservation"],
        config=TeamConfig(trial_id="arch-proof", task_id="proof-1", max_turns=6),
        with_verifier=False,
    )
    team.run_turn(
        user_goal="Cancel my reservation R1.",
        worker_tools=[PROPOSE_CANDIDATE_WRITE_TOOL],
    )
    return team.trace


def create_fake_team(scripts: dict[str, Any], **kwargs) -> RAVELTeam:
    """Helper for tests: build a team backed by a FakeModelClient."""
    client = FakeModelClient(scripts=scripts)
    return create_team(model_client=client, model_name="fake/model", **kwargs)
