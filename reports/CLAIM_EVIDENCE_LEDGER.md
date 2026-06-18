# Claim-Evidence Ledger (Proposal §19)

Every claim in the final report must link to an entry here.
This table is populated AFTER experiments complete and validated results exist.

| Claim | Supporting Experiment | Effect Size | 95% CI | Result File | Limitations |
|-------|-----------------------|-------------|--------|-------------|-------------|
| (Pending: no held-out experiments run yet) | — | — | — | — | — |

## Pre-populated claim boundaries (§8.3)

The following claims are PERMITTED if experiments support hypotheses:

> In versioned tool environments with high-risk write tasks, evidence visibility is an important
> runtime variable that affects multi-agent tool trajectories and safety.  Through an external
> ledger, minimal sufficient routing, and pre-write evidence validation, it is possible to reduce
> context tokens while maintaining task success non-inferiorly and improving robustness to stale
> and conflicting evidence.

The following claims are NOT PERMITTED regardless of results:

- RAVEL provides unconditional safety guarantees for all multi-agent architectures.
- EvidenceValid in this simulation context is equivalent to legal/financial/medical safety.
- Results generalise to free-text tools or real production systems.

## Claim Tagging Convention

| Tag | Meaning |
|-----|---------|
| `[H1]` | Supported by preregistered Hypothesis 1 |
| `[EXPLORE]` | Exploratory analysis only; not preregistered |
| `[NEGATIVE]` | Null or adverse result; reported as-is |
| `[BOUNDARY]` | Describes a condition where RAVEL fails |
