# 01 — Proposal → Runtime Gap

Maps each Proposal/Contract construct to the concrete gap and the minimal change that closes it.
Source-of-truth order (Contract §1): Proposal > Architecture Contract > preregistration > benchmark > current code.

| # | Construct | Intended (Proposal/Contract) | Current runtime | Gap | Minimal change |
|---|-----------|------------------------------|-----------------|-----|----------------|
| G1 | Agent count | ≥3 LLM decision entities w/ identity | 4 prompted calls, no identity objects | No `agent_id`/state/tools per agent | `BaseAgent` subclasses w/ id+state+allowlist |
| G2 | Independent state | each agent owns its `messages` | one shared `state.messages` | shared mutable history | per-agent state container |
| G3 | A2A messages | typed messages w/ ids + event log | python dict passing | no message bus, no log | `MessageBus` + typed dataclasses |
| G4 | Delegation | Supervisor LLM picks next agent | hardcoded order | static chain | Supervisor emits `Delegate` decision; team executes legal transitions |
| G5 | Evidence views | per-agent projections of same object | identical view to all | MSE-Router unused | route Supervisor/Policy/Worker/Commit views |
| G6 | Tool isolation | worker = read + candidate-write only | worker holds real write tools | prompt-only restraint | allowlist enforced before tool exposure |
| G7 | CommitService | deterministic, sole writer | LLM decides commit | model is writer | deterministic service wrapping `CommitGate` |
| G8 | Advisory verifier | LLM is advisory only | LLM is authoritative | role inverted | SemanticVerifierAgent → advisory verdict |
| G9 | ARB | staged selective requery | partial, gate-coupled | not wired to CommitService | ARB driven by CommitService verdicts |
| G10 | Runtime trace | full per-call/message/commit log | none wired | TrialLogger unused | trace every LLM call + message + commit |
| G11 | Regimes cross-agent | version/field differ by agent | one observation mutated | not cross-agent | regimes as per-agent view policy |

**Closure path:** G1–G3 in Phase 1 (skeleton+bus+state), G5 in Phase 2 (views), G6–G8 in Phase 3 (commit isolation), G9 in Phase 4 (ARB), G4+G10+G11 threaded throughout.
