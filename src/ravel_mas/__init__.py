"""ravel_mas — True Multi-Agent RAVEL runtime.

Distinct from ravel_core (single-agent middleware). Implements the
orchestrator-workers architecture in docs/mas/03_ARCHITECTURE_CONTRACT.md:
real independent LLM agents, typed message bus, agent-specific evidence views,
and a deterministic CommitService as the sole write path.
"""

from .messages import Message, MessageBus, MESSAGE_TYPES, SUPERVISOR_ACTIONS
from .model_client import (
    BaseModelClient,
    FakeModelClient,
    OpenAIModelClient,
    ModelResponse,
    parse_json_response,
)
from .agents import (
    AgentState,
    BaseAgent,
    SupervisorAgent,
    PolicyAgent,
    ToolWorkerAgent,
    SemanticVerifierAgent,
)
from .trace import RuntimeTrace, LLMCallRecord, TraceEvent

__all__ = [
    "Message", "MessageBus", "MESSAGE_TYPES", "SUPERVISOR_ACTIONS",
    "BaseModelClient", "FakeModelClient", "OpenAIModelClient",
    "ModelResponse", "parse_json_response",
    "AgentState", "BaseAgent", "SupervisorAgent", "PolicyAgent",
    "ToolWorkerAgent", "SemanticVerifierAgent",
    "RuntimeTrace", "LLMCallRecord", "TraceEvent",
]
