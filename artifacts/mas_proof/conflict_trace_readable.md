# Runtime trace — trial=conflict-proof task=cancel-R1-conflict

[step 0] ENV reservation:R1 value flipped confirmed→cancelled at v2
[step 0] COMMIT_SERVICE verdict=reconcile action=cancel_reservation reasons=['stale_read_set', 'unresolved_conflict']
[step 0] COMMIT_SERVICE verdict=reconcile action=cancel_reservation reasons=None
[step 0] COMMIT_SERVICE verdict=reconcile action=cancel_reservation reasons=None
[step 0] COMMIT_SERVICE verdict=reconcile action=cancel_reservation reasons=None
[step 0] COMMIT_SERVICE verdict=reconcile action=cancel_reservation reasons=None
[step 0] COMMIT_SERVICE verdict=reconcile action=cancel_reservation reasons=None
[step 0] COMMIT_SERVICE verdict=reconcile action=cancel_reservation reasons=None
[step 0] COMMIT_SERVICE verdict=reconcile action=cancel_reservation reasons=None
[step 0] COMMIT_SERVICE verdict=abstain action=cancel_reservation reasons=None