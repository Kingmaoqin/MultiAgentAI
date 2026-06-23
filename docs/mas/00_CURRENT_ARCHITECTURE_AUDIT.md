# 00 — Current Architecture Audit

**Date:** 2026-06-17
**Commit audited:** `608b691c06b2dc52c60c42e6d0c08bd7fba1923c` (branch `main`)
**Auditor basis:** actual LLM call sites, actual tool permissions, actual shared state, actual runtime traces — NOT README/docstring/class names (per Contract §1).

---

## 0. Verdict (one line)

**The repository does NOT contain a true Multi-Agent RAVEL system as defined in `multiagent构筑要求` §2.**
Both runtime agents (`RAVELAgent`, `MultiAgentOrchestrator`) FAIL the core conditions. Large-scale experiments were running against `MultiAgentOrchestrator` and have been **STOPPED** (Contract §16/§21).

---

## 1. What actually runs today

Two benchmark-facing agents exist and have both been executed against tau2:

| Agent | File | LLM calls / turn | Runtime status |
|-------|------|------------------|----------------|
| `RAVELAgent` | `src/ravel_core/ravel_agent.py` | **1** (`generate` at line 272) | EXECUTED — all results in `results/multimodel/`, `results/ravel_corrected/` |
| `MultiAgentOrchestrator` | `src/ravel_core/multi_agent_orchestrator.py` | **3–4** (`generate` at lines 289, 328, 363, 408) | EXECUTED partial (1 task), STOPPED 2026-06-17 |

### 1.1 `RAVELAgent` = single LLM + Python middleware
- Exactly one model call per turn (`ravel_agent.py:272`).
- VisibilityPolicy / EvidenceLedger / CommitGate / ARB are Python functions wrapped around that single call.
- **This is the agent behind every result currently in the repo and in `EXPERIMENT_REPORT_20260615.md`.**
- Self-documented as such: `ravel_agent.py:184` — *"Designed for single-agent tau2 simulations. Multi-agent extension is out of scope."*

### 1.2 `MultiAgentOrchestrator` = 4 prompted LLM calls sharing one state
- Four `generate()` calls per turn with four distinct system prompts (Supervisor / Policy / Tool Worker / Commit Verifier).
- **This is closer, but still fails the Contract** — see §3.

---

## 2. Proposal-construct → runtime audit table

Status legend (Contract §7):
`EXECUTED` = implemented and runs · `UNUSED` = implemented but never called at runtime · `IFACE` = interface/class only · `TEST` = test-only · `DOC` = naming/comment only · `MISSING` = not implemented.

| Proposal / Contract construct | Current code | Actual runtime proof | Status | Required change |
|---|---|---|---|---|
| ≥3 independent LLM agents (§2.1) | `MultiAgentOrchestrator` makes 4 prompted calls | 4 `generate()` sites, but no per-agent identity object | **DOC/partial** | Real `Agent` objects with `agent_id`, own state, own tools |
| Independent message state (§2.2) | All roles read `all_msgs = state.system_messages + state.messages` (`multi_agent_orchestrator.py:233`) | Single shared mutable list | **MISSING** | Per-agent `messages` containers |
| Typed Agent-to-Agent messages (§2.3) | none | `grep message_id/source_agent_id` → 0 hits | **MISSING** | `MessageBus` + typed message dataclasses + event log |
| Dynamic delegation (§2.4) | Hardcoded order supervisor→policy→worker→verifier each turn (`:236,:243,:251`) | fixed Python sequence | **MISSING** | Supervisor LLM emits structured `Delegate{target_agent,...}` |
| Agent-specific evidence views (§2.5) | All agents read same conversation + same tool result | MSE-Router not called (grep → "NOT CALLED") | **MISSING** | Route per-agent views via MSE-Router |
| Tool permission isolation / allowlist (§2.6) | Tool Worker gets `tools=self._all_tools` incl. real write tools (`:169,:365`) | worker holds real write tools; only prompt + post-hoc gate restrains it | **MISSING** | Worker allowlist = read + candidate-write ONLY |
| Deterministic CommitService = sole writer (§4.5) | "Commit Verifier" is an **LLM** deciding `commit` (`:408`) | LLM authorizes writes | **MISSING** | Deterministic CommitService; LLM only advisory |
| Versioned Evidence Ledger (§5.1) | `evidence.py` `EvidenceLedger` | called by both agents (`ingest`) | **EXECUTED** (reusable) | Add `valid/observed/delivery_time` fields if absent |
| MSE-Router (§5.2) | `mse_router.py` `MSERouter` | grep → not called by either agent | **UNUSED** | Wire into per-agent view construction |
| Adaptive Reconciliation Budget (§5.3) | `reconciliation.py` ARB | called by `RAVELAgent._run_gate`; in MA only on LLM "reconcile" | **EXECUTED/partial** | Wire to deterministic CommitService stages |
| CommitGate deterministic checks (§4.5) | `commit_gate.py` `CommitGate.verify` | used by `RAVELAgent`; **NOT** used by MA (LLM used instead) | **EXECUTED (single-agent only)** | Make it the CommitService core in MA |
| TrialLogger structured trace (§14) | `trial_logger.py` | grep → not wired into either runtime | **UNUSED** | Emit per-call/per-message trace |
| Visibility regimes cross-agent (§6) | `visibility.py` operates on single observation | applied to one shared observation, not across agents | **partial/MISSING** | Implement as per-agent projections |

---

## 3. Why `MultiAgentOrchestrator` fails the Contract (concrete)

Even though it makes 4 LLM calls, it violates these **core** conditions (any one ⇒ not Multi-Agent, §2):

1. **§2.2 shared state** — every role reads the same `state.messages` list. No `team.supervisor.state is not team.policy_agent.state`. *(code: `:233`)*
2. **§2.3 no typed messages** — roles exchange plain Python dicts inside one method; no `message_id`, `source_agent_id`, `target_agent_id`, no event log. *(grep: 0 hits)*
3. **§2.4 no dynamic delegation** — the order is hardcoded; Supervisor does not emit a structured `Delegate` decision that selects the next agent. *(code: `:236→:243→:251`)*
4. **§2.5 no agent-specific views** — all roles see the same tool payload; MSE-Router never invoked. *(grep: "NOT CALLED")*
5. **§2.6 no tool isolation** — Tool Worker is handed the real write tools; restraint is prompt + post-hoc interception, explicitly forbidden ("必须使用 allowlist，而不是仅靠 prompt"). *(code: `:169,:365`)*
6. **§4.5 LLM as writer** — the deciding "Commit Verifier" is an LLM; the Contract requires a **deterministic** CommitService as the sole write authority, with the LLM only advisory. *(code: `:408`)*

It also matches three items on the §17 forbidden list:
- "把固定 prompt chain 称为动态 orchestrator"
- "让所有 Agent 共用同一 message history"
- "让 Worker 直接持有真实写工具"

---

## 4. Reusable deterministic assets (keep, do not rewrite — §8)

These are sound and should be reused behind thin adapters:
- `evidence.py::EvidenceLedger` — append-only, versioned, field-level delta, latest-field lookup. **Reuse as the Versioned Evidence Ledger.**
- `commit_gate.py::CommitGate.verify` — deterministic schema/freshness/conflict/traceability checks. **Reuse as the core of the deterministic CommitService.**
- `mse_router.py::MSERouter` — exists, unused; **wire it** for per-agent views.
- `reconciliation.py::AdaptiveReconciliationBudget` — staged ladder; **wire to CommitService**.
- `visibility.py::VisibilityPolicy` — regime projection; **re-target to per-agent projection**.
- `trial_logger.py::TrialLogger` — structured logging; **wire to runtime trace**.

## 5. Legacy labeling (§8)

- All existing results in `results/multimodel/`, `results/ravel_corrected/`, and the numbers in `reports/EXPERIMENT_REPORT_20260615.md` must be relabeled **"legacy single-agent visibility pilot"**. They must NOT be presented as Multi-Agent RAVEL results. (Action item; not yet applied.)
- `results/multiagent/` (the stopped 4-prompt run) must be labeled **"prompt-chain prototype — non-compliant, see docs/mas/00"** and not used as Multi-Agent results.

---

## 6. Models / endpoints actually available (runtime fact)

| Endpoint | Model id | GPU | Status |
|---|---|---|---|
| `http://127.0.0.1:8005/v1` | `g4` (Gemma-4-31B-it) | GPU2 | ACTIVE |
| `http://127.0.0.1:8006/v1` | `g4` (duplicate) | GPU0 | ACTIVE (idle duplicate) |
| `http://127.0.0.1:8192/v1` | `gpt-oss` (gpt-oss-120b, TP=2) | GPU1+GPU3 | ACTIVE |
| Qwen3-27B | — | — | NOT RUNNING (user: skip Chinese model) |

Same checkpoint may serve multiple agents (allowed by §2.1) — so a single Gemma4 endpoint can back Supervisor/Policy/Worker/Verifier as distinct agent identities.

---

## 7. Gate verdict

```
Stage: Phase 0 — Architecture Audit
Completed: Honest audit of current runtime vs Contract §2–§6
Runtime evidence: 4 generate() sites confirmed; shared state at :233; worker write tools at :169/:365; MSE-Router NOT CALLED; LLM-as-writer at :408
Tests executed: NONE yet (architecture tests not written)
Reviewer status: NOT_RUN
Problems found: 6 core Contract violations (§2.2,§2.3,§2.4,§2.5,§2.6,§4.5)
Files produced: docs/mas/00_CURRENT_ARCHITECTURE_AUDIT.md
Gate verdict: FAIL (current code is not Multi-Agent RAVEL)
Next action: Build src/ravel_mas/ real 3-agent skeleton per Contract §9 Phase 1
```
