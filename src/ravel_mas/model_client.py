"""Model clients for ravel_mas agents.

Two implementations:
  - OpenAIModelClient: real vLLM/OpenAI-compatible endpoint.
  - FakeModelClient: deterministic scripted responses for architecture tests
    (Contract §9 Phase 1 requires fake responses to prove identity/flow BEFORE tau2).

Each LLM invocation returns a ModelResponse carrying token accounting so the
team can record per-agent token usage (Contract §2.1).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Optional


@dataclass
class ModelResponse:
    content: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    raw: dict[str, Any] = field(default_factory=dict)

    def is_tool_call(self) -> bool:
        return bool(self.tool_calls)


class BaseModelClient:
    def generate(
        self,
        *,
        agent_id: str,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: Optional[list[dict[str, Any]]] = None,
        temperature: float = 0.0,
    ) -> ModelResponse:
        raise NotImplementedError


class FakeModelClient(BaseModelClient):
    """Deterministic client driven by a per-agent script.

    scripts: maps agent_id -> list of ModelResponse (consumed in order), OR
             agent_id -> callable(call_index, messages) -> ModelResponse.
    Used only for architecture proof tests; never in real experiments.
    """

    def __init__(
        self,
        scripts: dict[str, Any],
        default: Optional[ModelResponse] = None,
    ) -> None:
        self._scripts = scripts
        self._default = default or ModelResponse(content="{}")
        self._calls: dict[str, int] = {}

    def generate(
        self,
        *,
        agent_id: str,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: Optional[list[dict[str, Any]]] = None,
        temperature: float = 0.0,
    ) -> ModelResponse:
        idx = self._calls.get(agent_id, 0)
        self._calls[agent_id] = idx + 1
        script = self._scripts.get(agent_id)
        if script is None:
            return self._default
        if callable(script):
            return script(idx, messages)
        if isinstance(script, list):
            if idx < len(script):
                return script[idx]
            return script[-1] if script else self._default
        return self._default


class OpenAIModelClient(BaseModelClient):
    """Real client for a vLLM/OpenAI-compatible endpoint via litellm.

    Imported lazily so architecture tests run without network/tau2.
    """

    def __init__(self, model_name: str, api_base: str, api_key: str = "EMPTY",
                 extra_args: Optional[dict[str, Any]] = None) -> None:
        self.model_name = model_name
        self.api_base = api_base
        self.api_key = api_key
        self.extra_args = dict(extra_args or {})

    def generate(
        self,
        *,
        agent_id: str,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: Optional[list[dict[str, Any]]] = None,
        temperature: float = 0.0,
    ) -> ModelResponse:
        import litellm

        full_messages = [{"role": "system", "content": system_prompt}] + messages
        kwargs: dict[str, Any] = {
            "model": self.model_name,
            "messages": full_messages,
            "temperature": temperature,
            "api_base": self.api_base,
            "api_key": self.api_key,
            **self.extra_args,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        resp = litellm.completion(**kwargs)
        choice = resp.choices[0]
        msg = choice.message
        content = msg.get("content") if isinstance(msg, dict) else getattr(msg, "content", "") or ""
        raw_tool_calls = (
            msg.get("tool_calls") if isinstance(msg, dict) else getattr(msg, "tool_calls", None)
        ) or []
        tool_calls = []
        for tc in raw_tool_calls:
            fn = tc["function"] if isinstance(tc, dict) else tc.function
            name = fn["name"] if isinstance(fn, dict) else fn.name
            args = fn["arguments"] if isinstance(fn, dict) else fn.arguments
            tool_calls.append({"name": name, "arguments": args})

        usage = getattr(resp, "usage", None) or {}
        in_tok = usage.get("prompt_tokens", 0) if isinstance(usage, dict) else getattr(usage, "prompt_tokens", 0)
        out_tok = usage.get("completion_tokens", 0) if isinstance(usage, dict) else getattr(usage, "completion_tokens", 0)

        return ModelResponse(
            content=content or "",
            tool_calls=tool_calls,
            input_tokens=in_tok or 0,
            output_tokens=out_tok or 0,
        )


def parse_json_response(content: str, default: dict | None = None) -> dict:
    """Extract a JSON object from a model response (tolerant)."""
    import re
    if not content:
        return dict(default or {})
    try:
        return json.loads(content.strip())
    except (json.JSONDecodeError, ValueError):
        pass
    m = re.search(r"\{[\s\S]*\}", content)
    if m:
        try:
            return json.loads(m.group(0))
        except (json.JSONDecodeError, ValueError):
            pass
    return dict(default or {})
