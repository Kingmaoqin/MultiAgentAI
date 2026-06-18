# 02 Gap and Reuse Analysis

| Proposal Requirement | Existing Asset | Gap | Minimal Change | New Code Needed? |
| -------------------- | -------------- | --- | -------------- | ---------------- |
| Preserve benchmark semantics | Clean worktree `/home/xqin5/multiaiagent/worktrees/tau2-clean` official runner/evaluator | Original asset repo has dirty parser patch | Formal runs use clean worktree; avoid editing tau2; use wrappers | No tau2 edits |
| Versioned Evidence Ledger | v2 `EvidenceLedger` in `run_v2.py` | Single-file, historical, known gate metric issues | Reimplement small append-only ledger with tests | Yes |
| Minimal sufficient evidence routing | v2 `ObservationRouter` | Not tied to RAVEL schema; includes `LOSSY_SUMMARY` not in Proposal core | Implement deterministic projections with headers/pointers/fields | Yes |
| Visibility regimes | v2 router has FULL_SYNC, DELAYED_2, FIELD_MASK, STALE_VERSION, LOSSY_SUMMARY, CONFLICTING_VIEW | Proposal wants FullSync, Delayed, FieldMask, ConflictingView; perturbation strength needs preregistration | Reuse concepts; deterministic seed; record actual visible fields | Yes |
| Commit gate | v2/v3 gate code | v2 global-field check invalid; v3 relevance-scoped partial fix | Implement schema-scoped gate only over required fields | Yes |
| Per-domain write classification | tau2 `ToolType.WRITE` decorators; v3 whitelist | Old substring classifier invalid | Derive from tool metadata or explicit schemas | Yes, adapter |
| Adaptive reconciliation budget | Stage-3 decision gate and scout metrics | Not RAVEL ARB; Track F audit scaffold only | Define ladder and logging schema before integration | Yes |
| Official baseline reproduction | tau2 CLI and existing historical results | Only mock smoke run completed in this workspace | Run airline/retail/telecom baseline after endpoint/model freeze | Yes, launch configs |
| Task audit and split freeze | tau2 tasks/splits and historical selected tasks | No RAVEL-specific included/excluded CSV yet | Programmatic dependency/write audit using official actions + historical trajectories | Yes |
| Statistical analysis | v2 `stats_v2.py`, scout CSV summaries | Underpowered and metrics caveats | New paired bootstrap/mixed model scripts on immutable raw results | Yes |
| Reviewer Agent protocol | Tooling available via sub-agent | Not yet run for current patch | Spawn reviewer after code/tests exist | Yes, review artifact |

## Reuse Decisions

- Reuse tau2 official runner/evaluator as authority for FSS and DB state.
- Reuse tau2 `ToolType.WRITE` metadata as the canonical write source.
- Reuse historical v2/v3 only for lessons, not as unqualified evidence.
- Do not reuse v2 SAR/CWR definitions without fixing denominator and relevance issues.
- Do not modify tau2 tasks, policies, DB, tools, user simulator, or evaluator for RAVEL.
