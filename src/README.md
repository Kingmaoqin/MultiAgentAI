# Source Layout

`ravel_core` contains standalone runtime primitives for the first RAVEL patch:

- `EvidenceLedger`: append-only, object-versioned evidence records.
- `VisibilityPolicy`: deterministic FullSync, Delayed, FieldMask, and ConflictingView projections.
- `CommitGate`: schema-scoped write validation over required evidence only.

No file in this directory imports or modifies tau2. Integration with tau2 must be done through a later wrapper patch.

