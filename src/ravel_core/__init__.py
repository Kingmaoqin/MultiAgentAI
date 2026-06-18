"""RAVEL runtime primitives.

This package intentionally contains no tau2 imports in its core modules. It is
a thin adapter layer that can be unit-tested before being wired into benchmark
runners.

Modules:
    evidence            — Append-only VDL ledger (§4.2)
    visibility          — Observation regime projections (§3.2, §5.3)
    commit_gate         — Schema-scoped commit gate (§4.4)
    mse_router          — Minimal Sufficient Evidence router (§4.3)
    reconciliation      — Adaptive Reconciliation Budget ladder (§4.5)
    trial_logger        — Per-trial structured event log (§17)
    metrics             — Safety/token/task metrics evaluator (§6, §14)
    benchmark_adapter   — Tau2 wrapper (no tau2 edits required) (§1.3)
    ravel_agent         — Tau2-compatible half-duplex RAVEL agent (§5)
"""

from .benchmark_adapter import RAVELRunConfig, VisibilityAdapter
from .commit_gate import (
    ActionSchema,
    CandidateWrite,
    CommitGate,
    GateDecision,
    RequiredEvidence,
    VisibleEvidenceState,
)
from .evidence import EvidenceLedger, EvidenceRecord, canonical_json, flatten_fields
from .metrics import SafetyMetricsAccumulator, TrialMetrics, compute_metrics
from .trial_logger import TokenRecord, TrialLogger, TrialMeta
from .mse_router import AgentContext, EvidenceSlice, MSERouter
from .reconciliation import (
    AdaptiveReconciliationBudget,
    ReconciliationResult,
    ReconciliationStep,
    compute_risk_score,
)
from .visibility import EvidenceView, VisibilityPolicy

# ravel_agent has optional tau2 dependency — import lazily to keep unit tests clean
try:
    from .ravel_agent import (
        RAVELAgent,
        RAVELEvent,
        RAVELTrialSummary,
        create_ravel_agent,
        DOMAIN_WRITE_TOOLS,
    )
    _RAVEL_AGENT_AVAILABLE = True
except ImportError:
    _RAVEL_AGENT_AVAILABLE = False

__all__ = [
    # evidence
    "EvidenceLedger",
    "EvidenceRecord",
    "canonical_json",
    "flatten_fields",
    # visibility
    "EvidenceView",
    "VisibilityPolicy",
    # commit_gate
    "ActionSchema",
    "CandidateWrite",
    "CommitGate",
    "GateDecision",
    "RequiredEvidence",
    "VisibleEvidenceState",
    # mse_router
    "AgentContext",
    "EvidenceSlice",
    "MSERouter",
    # reconciliation
    "AdaptiveReconciliationBudget",
    "ReconciliationResult",
    "ReconciliationStep",
    "compute_risk_score",
    # trial_logger
    "TrialLogger",
    "TrialMeta",
    "TokenRecord",
    # metrics
    "SafetyMetricsAccumulator",
    "TrialMetrics",
    "compute_metrics",
    # benchmark_adapter
    "RAVELRunConfig",
    "VisibilityAdapter",
]

