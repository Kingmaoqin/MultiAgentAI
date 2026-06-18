"""Real LLM agents for ravel_mas.

Each core agent is a distinct decision entity (Contract §2.1):
  - unique agent_id
  - independent system prompt (=> distinct prompt_hash)
  - independent message/history state (own list; never shared)
  - independent allowed tool set (allowlist enforced here, not by prompt)
  - independent LLM invocation (own generate() call via the shared model client)
  - independent token accounting
  - structured output schema

A class/function/dataclass/role-string is NOT an agent. These are agents because
each holds its own state and issues its own LLM call recorded under its own id.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Optional

from .model_client import BaseModelClient, ModelResponse, parse_json_response


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


@dataclass
class AgentState:
    """Per-agent independent conversation/history state."""
    messages: list[dict[str, Any]] = field(default_factory=list)
    last_output: dict[str, Any] = field(default_factory=dict)
    input_tokens: int = 0
    output_tokens: int = 0
    n_calls: int = 0


class BaseAgent:
    """Base class for a real LLM agent with independent identity and state."""

    role: str = "base"

    def __init__(
        self,
        agent_id: str,
        system_prompt: str,
        model_client: BaseModelClient,
        model_name: str,
        allowed_tools: Optional[list[str]] = None,
        temperature: float = 0.0,
        history_window: int = 1,
    ) -> None:
        self.agent_id = agent_id
        self.system_prompt = system_prompt
        self.prompt_hash = _hash(system_prompt)
        self._client = model_client
        self.model_name = model_name
        # Tool allowlist — names this agent is permitted to hold. Enforced by team.
        self.allowed_tools: list[str] = list(allowed_tools or [])
        self.temperature = temperature
        # How many of this agent's own past messages to resend per call. RAVEL's
        # minimal-context principle: Supervisor/Policy prompts are self-contained
        # (they carry the compact state), so default to only the current prompt.
        # The full history is still retained in self.state for independence/trace.
        self.history_window = history_window
        # INDEPENDENT state object (Contract §2.2)
        self.state = AgentState()
        # Last raw model response (for trace records)
        self.last_response: Optional[ModelResponse] = None

    @property
    def messages(self) -> list[dict[str, Any]]:
        return self.state.messages

    def _invoke(
        self,
        user_content: str,
        tools: Optional[list[dict[str, Any]]] = None,
    ) -> ModelResponse:
        """Issue this agent's own LLM call and update its own token accounting."""
        self.state.messages.append({"role": "user", "content": user_content})
        # Bounded context: resend only the last `history_window` user messages of
        # this agent (default 1 = current self-contained prompt). Prevents unbounded
        # context growth that otherwise blows past the model's window.
        keep = max(1, self.history_window)
        user_msgs = [m for m in self.state.messages if m.get("role") == "user"]
        sent = user_msgs[-keep:]
        resp = self._client.generate(
            agent_id=self.agent_id,
            system_prompt=self.system_prompt,
            messages=sent,
            tools=tools,
            temperature=self.temperature,
        )
        self.state.n_calls += 1
        self.state.input_tokens += resp.input_tokens
        self.state.output_tokens += resp.output_tokens
        self.state.messages.append({"role": "assistant", "content": resp.content})
        self.last_response = resp
        return resp

    def context_hash(self) -> str:
        return _hash("\n".join(m.get("content", "") for m in self.state.messages))


class SupervisorAgent(BaseAgent):
    """Decomposes the goal and dynamically delegates (Contract §4.1)."""
    role = "supervisor"

    def decide(self, *, user_goal: str, task_state: str, ledger_headers: str,
               last_result: str) -> dict[str, Any]:
        prompt = (
            f"User goal:\n{user_goal}\n\n"
            f"Current task state:\n{task_state}\n\n"
            f"Ledger headers (no raw payloads):\n{ledger_headers}\n\n"
            f"Last agent result:\n{last_result}\n\n"
            "Decide the single next step. Respond ONLY with JSON:\n"
            '{"action":"Delegate|RequestReconciliation|AskUser|Finish|Abstain",'
            '"target_agent":"policy_agent|tool_worker|null",'
            '"subgoal":"...","required_objects":[],"evidence_refs":[],'
            '"reason_code":"..."}'
        )
        resp = self._invoke(prompt)
        out = parse_json_response(resp.content, default={
            "action": "AskUser", "target_agent": None, "subgoal": "",
            "required_objects": [], "evidence_refs": [], "reason_code": "parse_error",
        })
        self.state.last_output = out
        return out


class PolicyAgent(BaseAgent):
    """Determines required evidence schema and policy constraints (Contract §4.2)."""
    role = "policy_agent"

    def decide(self, *, action: str, subgoal: str, policy_fields: str) -> dict[str, Any]:
        prompt = (
            f"Planned action: {action}\nSubgoal: {subgoal}\n\n"
            f"Policy-relevant evidence fields visible to you:\n{policy_fields}\n\n"
            "Produce the required evidence schema. Respond ONLY with JSON:\n"
            '{"action":"...","policy_status":"allowed|conditionally_allowed|forbidden",'
            '"required_evidence":[{"object_selector":"...","field":"...","freshness":"latest"}],'
            '"required_user_confirmations":[],"policy_checks":[],"ambiguities":[]}'
        )
        resp = self._invoke(prompt)
        out = parse_json_response(resp.content, default={
            "action": action, "policy_status": "unknown",
            "required_evidence": [], "required_user_confirmations": [],
            "policy_checks": [], "ambiguities": ["parse_error"],
        })
        self.state.last_output = out
        return out


class ToolWorkerAgent(BaseAgent):
    """Executes read tools and proposes candidate writes (Contract §4.3).

    NEVER holds real write tools; only read tools + propose_candidate_write.
    """
    role = "tool_worker"

    def act(self, *, subgoal: str, worker_view: str,
            tools: list[dict[str, Any]]) -> ModelResponse:
        prompt = (
            f"Subgoal from Supervisor: {subgoal}\n\n"
            f"Your evidence view (action-required fields only):\n{worker_view}\n\n"
            "Use a read tool to gather missing evidence, or call "
            "propose_candidate_write to propose a state change. You CANNOT execute "
            "writes directly. If the subgoal is satisfied, respond with a short "
            "structured summary."
        )
        resp = self._invoke(prompt, tools=tools)
        return resp


class SemanticVerifierAgent(BaseAgent):
    """Optional advisory verifier (Contract §4.4). Cannot authorize writes."""
    role = "semantic_verifier"

    def advise(self, *, candidate: dict[str, Any], evidence_summary: str) -> dict[str, Any]:
        prompt = (
            f"Candidate write:\n{candidate}\n\n"
            f"Evidence summary:\n{evidence_summary}\n\n"
            "Give an ADVISORY verdict only. Respond ONLY with JSON:\n"
            '{"recommendation":"recommend_commit|recommend_reconcile|'
            'recommend_replan|recommend_abstain","reasons":[]}'
        )
        resp = self._invoke(prompt)
        out = parse_json_response(resp.content, default={
            "recommendation": "recommend_abstain", "reasons": ["parse_error"],
        })
        self.state.last_output = out
        return out
