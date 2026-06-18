"""RAVELTeamAgent — tau2 benchmark-facing wrapper (Contract §3, Phase 5).

tau2 sees ONE agent; inside, real independent LLM agents run with a typed
message bus, agent-specific evidence views, and a deterministic CommitService
as the sole write path.

Per-turn state machine (tau2 calls generate_next_message once per turn):
  1. Ingest incoming tool result(s) into the Ledger (regime projection).
  2. Internal Supervisor↔Policy planning loop (JSON, NO tau2 tools).
  3. ToolWorker turn (tau2 generate, allowlist = read tools + propose_candidate_write):
       - read tool call          → return it to tau2 (env executes; result next turn)
       - propose_candidate_write → CommitService.verify:
            commit    → wrapper emits the REAL write tool call to tau2
            reconcile → emit a selective read (ARB) or ask the user
            abstain   → return text
       - plain text              → return to user

Write isolation: the worker never holds real write tools, so it can never emit a
real write ToolCall. Only this wrapper, and only after a CommitService commit
decision, constructs a real write ToolCall.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from .agents import SupervisorAgent, PolicyAgent
from .builders import SUPERVISOR_PROMPT, POLICY_PROMPT, WORKER_PROMPT, PROPOSE_CANDIDATE_WRITE_TOOL
from .commit_service import CommitService, CandidateWriteMsg
from .messages import MessageBus
from .tau2_client import Tau2GenerateClient
from .trace import RuntimeTrace, LLMCallRecord
from .views import ViewBuilder

import sys
from pathlib import Path
_SRC = Path(__file__).parent.parent
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
from ravel_core.evidence import EvidenceLedger
from ravel_core.ravel_agent import (
    DOMAIN_WRITE_TOOLS, _extract_object_id, _parse_payload,
)

try:
    from tau2.agent.base_agent import HalfDuplexAgent, ValidAgentInputMessage
    from tau2.agent.llm_agent import LLMAgent, LLMAgentState
    from tau2.data_model.message import (
        AssistantMessage, MultiToolMessage, SystemMessage,
        ToolCall, ToolMessage, UserMessage,
    )
    from tau2.utils.llm_utils import generate as tau2_generate
    _TAU2 = True
except ImportError:
    _TAU2 = False
    HalfDuplexAgent = object


class RAVELTeamAgent(HalfDuplexAgent):
    def __init__(
        self,
        tools: list,
        domain_policy: str,
        llm: str,
        llm_args: Optional[dict] = None,
        regime: str = "FullSync",
        delay: int = 1,
        masked_field: Optional[str] = None,
        domain: str = "unknown",
        task_id: str = "unknown",
        seed: int = 42,
        max_internal_steps: int = 4,
        trace_dir: Optional[str] = None,
    ) -> None:
        super().__init__(tools=tools, domain_policy=domain_policy)
        self._llm = llm
        self._llm_args = dict(llm_args or {})
        # NOTE: a rare AuthenticationError can occur if an internal call loses
        # api_base/api_key and litellm falls back to the real OpenAI endpoint. We do
        # NOT pin global OPENAI_* env vars to fix it — that misroutes tau2-internal
        # OpenAI calls (e.g. gpt-4.1 checkers) into the local vLLM server. Instead,
        # every internal call passes api_base/api_key explicitly (see _llm_args usage).
        self._trace_dir = trace_dir
        # Cap raw tau2 conversation turns shown to the worker (context safety).
        self._worker_history_window = 16
        self._domain = domain
        self._regime = regime
        self._task_id = task_id
        self._max_internal = max_internal_steps

        self._all_tools = tools
        if domain not in DOMAIN_WRITE_TOOLS:
            # Fail closed: without a known write-tool registry we cannot guarantee the
            # worker is denied real write tools (Contract §2.6). Refuse rather than leak.
            raise ValueError(
                f"RAVELTeamAgent: no write-tool registry for domain '{domain}'. "
                f"Add it to DOMAIN_WRITE_TOOLS before running, to enforce allowlists."
            )
        self._write_tool_names = set(DOMAIN_WRITE_TOOLS[domain])
        # Worker allowlist = everything that is NOT a real write tool.
        self._read_tools = [t for t in tools if _tool_name(t) not in self._write_tool_names]
        # propose_candidate_write as a real tau2 Tool (so generate() can serialize it).
        self._propose_tool = _build_propose_tool()
        # Reference schemas for the write actions the worker may PROPOSE (but not
        # execute). Without these the worker hallucinates write action names.
        self._write_actions_ref = self._build_write_actions_ref(tools)
        # action name -> set of its parameter names (for arg auto-completion).
        self._write_params = self._build_write_params(tools)

        # Services
        self._ledger = EvidenceLedger()
        self._views = ViewBuilder(self._ledger, regime=regime, delay=delay,
                                  masked_field=masked_field,
                                  conflict_objects=set())
        self._commit = CommitService(
            self._ledger, write_tools=self._write_tool_names,
            action_required_fields={},  # presence/version checks; schema-light for pilot
        )
        self._bus = MessageBus()
        self._trace = RuntimeTrace(trial_id=f"mas-{task_id}", task_id=task_id)

        # JSON-only client for supervisor + policy
        client = Tau2GenerateClient(model_name=llm, llm_args=self._llm_args)
        self._supervisor = SupervisorAgent("supervisor", SUPERVISOR_PROMPT, client, llm, [])
        self._policy = PolicyAgent("policy_agent", POLICY_PROMPT, client, llm, [])

        self._plan: dict = {}
        self._policy_schema: dict = {}
        self._inner = LLMAgent(tools=tools, domain_policy=domain_policy,
                               llm=llm, llm_args=self._llm_args)
        self._step = 0
        # Compact, structured task memory (RAVEL global plan / task state) — gives the
        # Supervisor continuity WITHOUT resending the raw transcript. Prevents the
        # "re-delegate to policy every turn" loop.
        self._memo: dict = {
            "policy_status": None, "required_evidence": [],
            "evidence_objects": {}, "writes_attempted": [],
            "recent_targets": [],
        }

    # --- tau2 interface ---

    def get_init_state(self, message_history=None):
        return self._inner.get_init_state(message_history)

    def generate_next_message(self, message, state):
        self._step += 1
        # 1. ingest tool results
        self._ingest_incoming(message, state)

        # 2. internal supervisor↔policy planning
        target = self._plan_loop(state)

        # 3. terminal actions return text
        if target in ("Finish", "AskUser", "Abstain"):
            content = self._terminal_text(target)
            msg = AssistantMessage.text(content=content)
            state.messages.append(msg)
            return msg, state

        # 4. ToolWorker turn via tau2 generate (read tools + propose_candidate_write only)
        worker_tools = self._read_tools + [self._propose_tool]
        worker_sys = (
            WORKER_PROMPT + f"\n\nDomain policy:\n{self.domain_policy}\n\n"
            f"Supervisor subgoal: {self._plan.get('subgoal','')}\n"
            f"Evidence view:\n{self._views.fields_for('tool_worker', self._plan.get('required_objects', []))}\n\n"
            "To change state, call propose_candidate_write with `action` set to EXACTLY "
            "one of these write actions (do NOT invent names) and `arguments` matching its "
            f"parameters:\n{self._write_actions_ref}"
        )
        # Bound the worker's tau2 conversation to the most recent turns to avoid
        # context-window overflow on long episodes. The worker also receives the
        # ledger-projected evidence view inside worker_sys, so trimming raw history
        # is consistent with RAVEL's minimal-context principle.
        convo = [m for m in state.messages if getattr(m, 'role', '') != 'system']
        worker_msgs = [SystemMessage(role="system", content=worker_sys)] + convo[-self._worker_history_window:]
        worker_resp = tau2_generate(
            model=self._llm, tools=worker_tools, messages=worker_msgs,
            call_name="mas_tool_worker", **self._llm_args,
        )
        self._trace.record_llm_call(LLMCallRecord(
            logical_step=self._trace.step(), agent_id="tool_worker", agent_role="tool_worker",
            model_name=self._llm, system_prompt_hash=_hash(worker_sys),
            context_hash="", visible_evidence_ids=[r.evidence_id for r in self._ledger.records],
            visible_object_versions={}, input_tokens=0, output_tokens=0,
            output_kind="tool_call" if worker_resp.is_tool_call() else "text",
        ))

        out = self._handle_worker(worker_resp, state)
        state.messages.append(out)
        self._maybe_dump_trace()
        return out, state

    def _maybe_dump_trace(self) -> None:
        """Persist the live runtime trace (overwrite each turn) when enabled via
        llm_args['mas_trace_dir']. Gives real-model multi-agent evidence."""
        d = self._trace_dir
        if not d:
            return
        from pathlib import Path as _P
        out = _P(d)
        out.mkdir(parents=True, exist_ok=True)
        (out / f"pilot_trace_{self._task_id}.jsonl").write_text(self._trace.to_jsonl())
        (out / f"pilot_trace_{self._task_id}.md").write_text(self._trace.to_readable())

    # --- internals ---

    def _ingest_incoming(self, message, state):
        tool_msgs = []
        if _TAU2 and isinstance(message, MultiToolMessage):
            tool_msgs = list(message.tool_messages)
            state.messages.extend(message.tool_messages)
        elif _TAU2 and isinstance(message, ToolMessage):
            tool_msgs = [message]
            state.messages.append(message)
        else:
            state.messages.append(message)
        for tm in tool_msgs:
            name = getattr(tm, "name", None) or "tool"
            payload = _parse_payload(tm.content or "")
            oid = _extract_object_id(name, payload)
            self._ledger.ingest(object_id=oid, tool_name=name, payload=payload,
                                source_agent="tool_worker")
            # record compact evidence facts for the supervisor memo
            self._memo["evidence_objects"][oid] = sorted(list(payload.keys())[:6])
        # ConflictingView: any object the ledger has seen more than once becomes a
        # cross-agent conflict candidate (worker pinned one version behind latest).
        if self._regime == "ConflictingView":
            self._views.conflict_objects = {
                r.object_id for r in self._ledger.records
                if self._ledger.object_version(r.object_id) >= 2
            }

    def _render_task_state(self) -> str:
        m = self._memo
        ev = "; ".join(f"{k}{v}" for k, v in list(m["evidence_objects"].items())[:8]) or "none"
        writes = "; ".join(f"{w['action']}={w['verdict']}" for w in m["writes_attempted"]) or "none"
        return (
            f"turn={self._step}\n"
            f"policy_obtained={'yes' if m['policy_status'] else 'no'} "
            f"(status={m['policy_status']})\n"
            f"evidence_gathered: {ev}\n"
            f"writes_attempted: {writes}\n"
            f"recent_delegations: {m['recent_targets'][-4:]}\n"
            "Guidance: if policy is obtained and evidence is gathered, delegate to "
            "tool_worker to act; do NOT re-request policy you already have; if a write "
            "already committed, Finish."
        )

    def _plan_loop(self, state) -> str:
        user_goal = self._latest_user_text(state)
        for _ in range(self._max_internal):
            plan = self._supervisor.decide(
                user_goal=user_goal, task_state=self._render_task_state(),
                ledger_headers=self._views.headers_for("supervisor"),
                last_result=json.dumps(self._policy_schema)[:200],
            )
            self._plan = plan
            self._record(self._supervisor, "json", plan.get("reason_code", ""))
            self._publish("supervisor", plan.get("target_agent") or "team", "Delegate", plan)
            action = plan.get("action", "AskUser")
            if action in ("Finish", "AskUser", "Abstain"):
                return action
            if action == "RequestReconciliation":
                continue
            target = plan.get("target_agent")
            self._memo["recent_targets"].append(target)
            if target == "policy_agent":
                pd = self._policy.decide(
                    action=plan.get("subgoal", ""), subgoal=plan.get("subgoal", ""),
                    policy_fields=self._views.fields_for("policy_agent",
                                                         plan.get("required_objects", [])),
                )
                self._memo["policy_status"] = pd.get("policy_status")
                self._memo["required_evidence"] = pd.get("required_evidence", [])
                self._policy_schema = pd
                self._record(self._policy, "json")
                self._publish("policy_agent", "supervisor", "PolicyDecision", pd)
                continue
            if target == "tool_worker":
                return "tool_worker"
        return "tool_worker"

    def _handle_worker(self, resp, state):
        if not resp.is_tool_call():
            self._publish("tool_worker", "supervisor", "EvidenceResult",
                          {"summary": (resp.content or "")[:200]})
            return resp  # text to user

        # split read calls vs propose_candidate_write
        real_calls = []
        for tc in (resp.tool_calls or []):
            if tc.name == "propose_candidate_write":
                decision_msg = self._verify_candidate(tc, state)
                if decision_msg is not None:
                    return decision_msg
            elif tc.name in self._write_tool_names:
                # Should never happen: worker has no real write tools. Block defensively.
                self._trace.record_event("env", {"note": f"BLOCKED worker direct write {tc.name}"})
                continue
            else:
                real_calls.append(tc)  # read tool — allowed to reach tau2
        if real_calls:
            self._trace.record_event("tool", {"tool_name": real_calls[0].name,
                                              "agent_id": "tool_worker", "tool_kind": "read"})
            return AssistantMessage.text(content="", tool_calls=real_calls)
        return AssistantMessage.text(content=resp.content or "Proceeding.")

    def _build_write_actions_ref(self, tools) -> str:
        """Build a reference list of proposable write actions with their parameters,
        so the worker uses correct action names/args in propose_candidate_write."""
        lines = []
        for t in tools:
            if _tool_name(t) not in self._write_tool_names:
                continue
            try:
                schema = t.openai_schema["function"]
                params = list(schema.get("parameters", {}).get("properties", {}).keys())
                desc = (schema.get("description", "") or "").strip().split("\n")[0][:120]
                lines.append(f"  - {schema['name']}({', '.join(params)}): {desc}")
            except Exception:
                lines.append(f"  - {_tool_name(t)}")
        return "\n".join(lines) or "  (none)"

    def _build_write_params(self, tools) -> dict:
        out = {}
        for t in tools:
            n = _tool_name(t)
            if n not in self._write_tool_names:
                continue
            try:
                props = t.openai_schema["function"]["parameters"].get("properties", {})
                out[n] = set(props.keys())
            except Exception:
                out[n] = set()
        return out

    def _autocomplete_write_args(self, action: str, write_args: dict,
                                 target_objects: tuple) -> dict:
        """Inject id-like parameters the worker omitted, taken from the resolved
        ledger evidence. Fixes the common failure where the worker drops the entity
        id (e.g. reservation_id) from the write arguments, producing a non-matching
        action. Only fills params that (a) the action actually declares and (b) are
        missing/empty in the worker's args."""
        params = self._write_params.get(action, set())
        if not params:
            return write_args
        completed = dict(write_args)
        # gather candidate id fields from the resolved ledger records
        evidence_fields: dict = {}
        for r in self._ledger.records:
            if r.object_id in target_objects:
                for k, v in dict(r.field_values).items():
                    if (k.endswith("_id") or k == "id") and v is not None:
                        evidence_fields.setdefault(k, v)
        for p in params:
            if p in evidence_fields and (p not in completed or completed.get(p) in (None, "")):
                completed[p] = evidence_fields[p]
        return completed

    def _resolve_target_objects(self, write_args: dict, declared) -> tuple:
        """Resolve the write's entity ids to real ledger object ids, robustly.

        Grounds the CommitService check in the evidence actually gathered (the
        middleware read-set), not the LLM's free-form labels. Strategy:
          1. collect every id-like value anywhere in the write args (recursive);
          2. match them against ledger object ids AND stored field values;
          3. fall back to the most-recently-read ledger object (the worker just
             gathered evidence) so a legitimate write is not falsely 'missing';
          4. only if the ledger is empty, use a synthetic id.
        """
        records = list(self._ledger.records)
        ledger_objs = [r.object_id for r in records]

        # 1. recursively collect id-like string values from the write args
        id_values: list[str] = []
        def _collect(v):
            if isinstance(v, dict):
                for k, vv in v.items():
                    if isinstance(vv, (str, int)) and (str(k).endswith("_id") or k == "id"):
                        id_values.append(str(vv))
                    _collect(vv)
            elif isinstance(v, list):
                for it in v:
                    _collect(it)
        _collect(write_args)

        resolved = []
        for val in id_values:
            for r in records:
                if r.object_id in resolved:
                    continue
                if val in r.object_id or val in str(dict(r.field_values)):
                    resolved.append(r.object_id)
        if resolved:
            return tuple(resolved)
        # 3. fall back to the most recently ingested ledger object(s)
        if ledger_objs:
            return (ledger_objs[-1],)
        # 4. synthetic only when no evidence exists at all
        return (_extract_object_id(write_args.get("action", "write"), write_args),)

    def _verify_candidate(self, tc, state):
        """Run deterministic CommitService; emit real write ToolCall iff commit."""
        args = tc.arguments if isinstance(tc.arguments, dict) else json.loads(tc.arguments or "{}")
        action = args.get("action", "")
        write_args = args.get("arguments", {}) or {}
        # Map the write's referenced entity ids to ACTUAL ledger object ids, so the
        # deterministic checks run against the evidence the worker really gathered.
        # The LLM's free-form target_objects rarely match ledger keys (tool:id), so we
        # resolve by id-value substring against ledger object ids.
        target_objects = self._resolve_target_objects(write_args, args.get("target_objects"))
        # Auto-complete id parameters the worker dropped (e.g. reservation_id) from the
        # resolved ledger evidence, so the executed write matches the intended entity.
        write_args = self._autocomplete_write_args(action, write_args, target_objects)
        # Traceability/freshness use the MIDDLEWARE-RECORDED read-set (the real ledger
        # evidence ids + current versions for the resolved targets), NOT the model's
        # self-reported references — Contract §4.5 ("不能完全相信模型自己声明的
        # evidence references"). The LLM cannot know internal evidence ids, so trusting
        # its claims produced false 'untraceable'/'missing' blocks. SAFETY checks
        # (stale/conflict) still fire from the worker's CLAIMED preconditions and from
        # the ConflictingView projection.
        actual_ev_ids = tuple(
            r.evidence_id for r in self._ledger.records if r.object_id in target_objects
        )
        cw = CandidateWriteMsg(
            action=action, arguments=write_args, target_objects=target_objects,
            referenced_evidence_ids=actual_ev_ids,
            claimed_preconditions=tuple(args.get("claimed_preconditions", []) or ()),
            expected_versions={},  # no self-reported versions; conflict via preconditions
        )
        self._publish("tool_worker", "commit_service", "CandidateWrite", args)
        decision = self._commit.verify(cw)
        self._memo["writes_attempted"].append({"action": action, "verdict": decision.verdict})
        self._trace.record_event("commit", {"action": action, "verdict": decision.verdict,
                                            "reasons": list(decision.reasons),
                                            "committed": decision.allowed})
        if decision.allowed and action in self._write_tool_names:
            # wrapper emits the REAL write tool call (sole write path)
            return AssistantMessage.text(content="", tool_calls=[
                ToolCall(id=f"mas-w-{self._step}", name=action, arguments=write_args)
            ])
        # reconcile / abstain → ask user for confirmation/info (safe)
        self._publish("commit_service", "supervisor", "ReconciliationRequest",
                      {"action": action, "reasons": list(decision.reasons)})
        return AssistantMessage.text(content=(
            f"Before I {action}, I need to confirm the current details "
            f"({', '.join(decision.reasons) or 'verification required'}). "
            "Could you confirm the relevant information?"))

    # --- helpers ---

    def _latest_user_text(self, state) -> str:
        for m in reversed(state.messages):
            if getattr(m, "role", "") == "user":
                return getattr(m, "content", "") or ""
        return ""

    def _terminal_text(self, action: str) -> str:
        return {
            "Finish": "Is there anything else I can help you with?",
            "AskUser": "Could you provide a bit more detail so I can help?",
            "Abstain": "I'm not able to complete this safely without more information.",
        }.get(action, "How can I help further?")

    def _record(self, agent, kind, reason=""):
        r = agent.last_response
        self._trace.record_llm_call(LLMCallRecord(
            logical_step=self._trace.step(), agent_id=agent.agent_id, agent_role=agent.role,
            model_name=agent.model_name, system_prompt_hash=agent.prompt_hash,
            context_hash=agent.context_hash(),
            visible_evidence_ids=[r2.evidence_id for r2 in self._ledger.records],
            visible_object_versions={}, input_tokens=r.input_tokens if r else 0,
            output_tokens=r.output_tokens if r else 0, output_kind=kind, reason_code=reason))

    def _publish(self, src, tgt, mtype, payload):
        m = self._bus.publish(source_agent_id=src, target_agent_id=tgt or "team",
                              message_type=mtype, payload=payload)
        self._trace.record_event("message", m.to_dict())

    def build_trace(self) -> RuntimeTrace:
        return self._trace


def _build_propose_tool():
    """Build a tau2 Tool for propose_candidate_write (a non-executing proposal)."""
    from tau2.environment.tool import as_tool

    def propose_candidate_write(
        action: str,
        arguments: dict,
        target_objects: list = None,
        referenced_evidence_ids: list = None,
        claimed_preconditions: list = None,
        expected_versions: dict = None,
    ) -> str:
        """Propose a state-changing action for the deterministic CommitService to
        validate before execution. This does NOT execute the action; it only
        records a candidate write that the CommitService will check.

        Args:
            action: name of the write action being proposed.
            arguments: arguments for the write action.
            target_objects: object ids the write would modify.
            referenced_evidence_ids: evidence ids the proposal relies on.
            claimed_preconditions: list of {object_id, field, operator, value} the
                worker believes hold.
            expected_versions: object_id -> version the worker observed.
        """
        return "candidate_write_recorded"

    return as_tool(propose_candidate_write)


def _tool_name(tool) -> str:
    if isinstance(tool, dict):
        return tool.get("function", {}).get("name", tool.get("name", ""))
    fn = getattr(tool, "name", None)
    return fn or ""


def _hash(text: str) -> str:
    import hashlib
    return hashlib.sha256(text.encode()).hexdigest()


_RAVEL_KEYS = frozenset({"regime", "delay", "masked_field", "domain", "task_id",
                         "seed", "trace_dir"})


def create_ravel_team_agent(tools, domain_policy, **kwargs):
    """tau2 registry-compatible factory."""
    raw = dict(kwargs.get("llm_args") or {})
    cfg = {}
    for k in list(raw.keys()):
        if k in _RAVEL_KEYS:
            cfg[k] = raw.pop(k)
    for k in _RAVEL_KEYS:
        if k in kwargs and k not in cfg:
            cfg[k] = kwargs[k]
    domain = cfg.get("domain", "unknown")
    task_obj = kwargs.get("task")
    task_id = cfg.get("task_id", str(getattr(task_obj, "id", "unknown")))
    return RAVELTeamAgent(
        tools=tools, domain_policy=domain_policy, llm=kwargs.get("llm", ""),
        llm_args=raw, regime=cfg.get("regime", "FullSync"),
        delay=int(cfg.get("delay", 1)), masked_field=cfg.get("masked_field"),
        domain=domain, task_id=task_id, seed=int(cfg.get("seed", 42)),
        trace_dir=cfg.get("trace_dir"),
    )
