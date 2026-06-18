# 02 — Reuse Plan

Policy (Contract §8): reuse → thin adapter → minimal extension → new only when necessary.
Do NOT rewrite the deterministic core; do NOT delete legacy results.

| ravel_core asset | Decision | How used in ravel_mas |
|---|---|---|
| `evidence.EvidenceLedger` | **Reuse as-is** | Shared Versioned Evidence Ledger service |
| `commit_gate.CommitGate.verify` | **Reuse, wrap** | Deterministic core of `CommitService` |
| `commit_gate.CandidateWrite/ActionSchema/RequiredEvidence` | **Reuse** | CandidateWrite message + schema checks |
| `mse_router.MSERouter` | **Reuse, wire** | Per-agent `ViewBuilder` projections |
| `reconciliation.AdaptiveReconciliationBudget` | **Reuse, wire** | ARB ladder driven by CommitService |
| `visibility.VisibilityPolicy` | **Reuse, re-target** | Regime → per-agent view differences |
| `trial_logger.TrialLogger` | **Reuse, wire** | Backing store for `RuntimeTrace` |
| `ravel_agent.DOMAIN_WRITE_TOOLS` | **Reuse** | Read/write tool partition for allowlists |
| `ravel_agent.RAVELAgent` | **Keep as legacy** | Relabel "legacy single-agent pilot"; not used in MAS |
| `multi_agent_orchestrator.py` | **Quarantine** | Non-compliant prototype; superseded by ravel_mas; keep for diff/audit |

## New components (only what the Contract requires)
- `ravel_mas/messages.py` — typed `Message` + `MessageBus` + event log (G3).
- `ravel_mas/agents.py` — `BaseAgent` + Supervisor/Policy/ToolWorker/SemanticVerifier (G1,G2).
- `ravel_mas/model_client.py` — real (OpenAI-compatible) + `FakeModelClient` for deterministic tests.
- `ravel_mas/commit_service.py` — deterministic `CommitService` wrapping `CommitGate` (G7).
- `ravel_mas/views.py` — `ViewBuilder` per-agent projections over Ledger via MSE-Router (G5,G11).
- `ravel_mas/trace.py` — `RuntimeTrace` (G10).
- `ravel_mas/team.py` — `RAVELTeam` runtime + dynamic delegation (G4).
- `ravel_mas/team_agent.py` — `RAVELTeamAgent` tau2 wrapper (Phase 5).

Nothing above duplicates an existing deterministic service; each either wraps or orchestrates one.
