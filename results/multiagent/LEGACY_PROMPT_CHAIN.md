# LEGACY — prompt-chain prototype (NON-COMPLIANT)

These results came from `src/ravel_core/multi_agent_orchestrator.py`: 4 prompted
LLM calls sharing ONE conversation state, hardcoded order, worker holding real
write tools. It FAILS the multi-agent contract (docs/mas/00, §3 violations).

Superseded by `src/ravel_mas/` (true multi-agent). Do not cite these as results.
