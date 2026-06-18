# 07 — Implementation Report

**Branch:** `feature/ravel-mas`
**Module:** `src/ravel_mas/`
**Status:** Architecture implemented; all gates pass; pending independent reviews before pilot.

## Components delivered

| File | Role | Contract |
|---|---|---|
| `messages.py` | typed `Message` + `MessageBus` + event log | §2.3 |
| `model_client.py` | `BaseModelClient`, `FakeModelClient`, `OpenAIModelClient` | §9 |
| `agents.py` | `BaseAgent` + Supervisor/Policy/ToolWorker/SemanticVerifier (id, state, prompt, allowlist) | §2.1, §2.2, §4.1–4.4 |
| `views.py` | `ViewBuilder` agent-specific projections + regimes | §2.5, §6 |
| `commit_service.py` | deterministic `CommitService` (sole writer, token-gated) | §4.5 |
| `reconciliation.py` | ARB selective-requery ladder | §5.3 |
| `team.py` | `RAVELTeam` dynamic delegation loop | §2.4 |
| `trace.py` | `RuntimeTrace` structured log | §14 |
| `builders.py` | `create_team`, Gate-1 proof | §9 |
| `visibility_proof.py` | Gate-2 proof + `agent_views.json` | §9 |
| `commit_proof.py` | Gate-3 write-isolation scenarios | §9 |
| `runtime_proof.py` | one-task §15 trajectory + manifests | §15 |
| `team_agent.py` | `RAVELTeamAgent` tau2 wrapper | §3, Phase 5 |
| `tau2_client.py` | JSON-only model adapter over tau2 litellm | Phase 5 |

## Gate results (machine-verified)

| Gate | Property | Result |
|---|---|---|
| 1 | ≥3 distinct LLM agent ids, distinct prompts, dynamic delegation, typed messages | PASS |
| 2 | same object → distinct per-agent views; worker.v≠supervisor.v; commit.v=max | PASS |
| 3 | valid→commit; stale→blocked+env unchanged; conflict→blocked; worker/forged write→denied | PASS |
| 4 | stale read fixed only by ARB selective requery (stage 4) | PASS |
| §15 | one-task stale→reconcile→commit trajectory; 3 agents; env safe | PASS |

`artifacts/mas_proof/architecture_acceptance.json` → `overall_status: PASS_ARCHITECTURE_PENDING_REVIEW`.

## Tests

`tests/test_mas_*.py` — 36 passing:
- identity (4), state isolation (3), delegation (3), tool permissions (4),
  visibility (5), commit isolation (6), mutations (8), runtime proof (5).

Mutation tests (§11): each architecture-breaking mutation flips at least one invariant — suite has teeth.

## How the tau2 wrapper enforces the contract

- Supervisor + Policy run as JSON-only LLM calls (no tau2 tools).
- ToolWorker is given **read tools + `propose_candidate_write` only**; the real write
  tools are never in its tool list, so it physically cannot emit a real write ToolCall.
- A real write ToolCall is constructed **only by the wrapper, only after CommitService
  returns commit**. This is the single write path inside the tau2 turn model.
- Regimes are applied as per-agent view differences via `ViewBuilder`.

## Known limitations (honest)

1. **CommitService schema is light for the pilot** — presence + version + conflict checks
   are wired; full per-action `required_evidence` schemas per domain are stubbed
   (`action_required_fields={}`). Sufficient for stale/conflict isolation; domain schemas
   to be filled before any main experiment.
2. **Benchmark integrity not yet machine-verified** — FullSync-vs-unmodified reward parity
   (Contract §10.9 at the tau2 level) is asserted in unit form, not yet by a tau2 run.
   `architecture_acceptance.benchmark_integrity = NOT_VERIFIED`.
3. **One-task proof uses the FakeModelClient** for determinism (Contract §9 explicitly
   wants fake responses before tau2). The tau2 wrapper is import/registration/allowlist
   verified but a real tau2 trajectory is part of the pilot, gated on reviews.
4. **Legacy results** in `results/multimodel/`, `results/ravel_corrected/`,
   `results/multiagent/` are single-agent / prompt-chain and are relabeled legacy
   (see `docs/mas/00`); they are NOT multi-agent results.

## Next (blocked on reviews)

- Independent Code Reviewer + Scientific Auditor (clean context).
- On APPROVED: 2-task pilot (1 model, FullSync + ConflictingView, ≤2 reps) per §16.
