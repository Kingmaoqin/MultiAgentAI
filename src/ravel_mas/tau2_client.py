"""Adapter that lets ravel_mas agents call models through tau2's litellm stack.

Supervisor and PolicyAgent are JSON-only (no tools) and use this client. The
ToolWorker's tool-calling turn is handled directly in team_agent.py because its
tool calls must be returned to the tau2 orchestrator as native tau2 ToolCalls.
"""

from __future__ import annotations

from typing import Any, Optional

from .model_client import BaseModelClient, ModelResponse


class Tau2GenerateClient(BaseModelClient):
    """JSON-only model client backed by tau2.utils.llm_utils.generate."""

    def __init__(self, model_name: str, llm_args: Optional[dict[str, Any]] = None) -> None:
        self.model_name = model_name
        self.llm_args = dict(llm_args or {})

    def generate(
        self,
        *,
        agent_id: str,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: Optional[list[dict[str, Any]]] = None,
        temperature: float = 0.0,
    ) -> ModelResponse:
        from tau2.utils.llm_utils import generate as tau2_generate
        from tau2.data_model.message import SystemMessage, UserMessage, AssistantMessage

        msgs: list[Any] = [SystemMessage(role="system", content=system_prompt)]
        for m in messages:
            role = m.get("role")
            content = m.get("content", "") or ""
            if role == "user":
                msgs.append(UserMessage(role="user", content=content))
            elif role == "assistant":
                msgs.append(AssistantMessage(role="assistant", content=content))
        result = tau2_generate(
            model=self.model_name,
            tools=[],                      # JSON-only roles never hold tools
            messages=msgs,
            call_name=f"mas_{agent_id}",
            **self.llm_args,
        )
        content = getattr(result, "content", "") or ""
        cost = getattr(result, "cost", None)
        usage = getattr(result, "usage", None) or {}
        in_tok = 0
        out_tok = 0
        if isinstance(usage, dict):
            in_tok = usage.get("prompt_tokens", 0) or 0
            out_tok = usage.get("completion_tokens", 0) or 0
        return ModelResponse(content=content, input_tokens=in_tok, output_tokens=out_tok)
