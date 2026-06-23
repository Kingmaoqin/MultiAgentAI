# 04 — Tool Permission Matrix

Enforced by `team`-level allowlist **before** tools are passed to any agent (Contract §2.6).
A prompt instruction is NOT sufficient; the agent must not physically hold a disallowed tool.

| Component | Read tools | Policy tools | Candidate-write tool | Real write tools |
|---|---|---|---|---|
| SupervisorAgent | No | No | No | No |
| PolicyAgent | Limited (read-meta) | Yes | No | No |
| ToolWorkerAgent | Yes | No | `propose_candidate_write` | **No** |
| SemanticVerifierAgent | No/limited | Limited | No | No |
| CommitService (not an agent) | Selective requery | Deterministic checks | Receives candidates | **Yes (sole)** |

## Real write tools per domain (only CommitService may execute)

- **airline:** `book_reservation, cancel_reservation, send_certificate, update_reservation_baggages, update_reservation_flights, update_reservation_passengers`
- **retail:** `exchange_delivered_order_items, return_delivered_order_items, modify_pending_order_items, modify_pending_order_payment, modify_pending_order_address, cancel_pending_order`
- **telecom:** `connect_vpn, disconnect_vpn, disable_roaming, enable_roaming, refuel_data, reseat_sim_card, reset_apn_settings, resume_line, send_payment_request, set_apn_settings, set_network_mode_preference, suspend_line, toggle_airplane_mode, toggle_data, toggle_data_saver_mode, toggle_roaming, toggle_wifi, toggle_wifi_calling`

(Source: `ravel_core.ravel_agent.DOMAIN_WRITE_TOOLS`.)

## Enforcement points
1. `Team.build_agents()` partitions the tau2 toolset into `read_tools` and `write_tools`.
2. ToolWorker is constructed with `read_tools + [propose_candidate_write]` only.
3. `write_tools` are handed exclusively to `CommitService`.
4. Test `test_mas_tool_permissions.py` asserts `REAL_WRITE_TOOLS ∩ worker.tools == ∅` and `REAL_WRITE_TOOLS ⊆ commit_service.tools`.
