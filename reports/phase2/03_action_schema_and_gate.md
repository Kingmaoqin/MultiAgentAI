# Phase-2 §4: ActionSchema 与非 permissive CommitGate（03）

**状态**：代码 + 单元测试完成；§4.3 gate 小样本实验（airline/retail 10 tasks × 5 methods × 4 regimes）**待批准后运行**。

## 1. 修复的 blocking issue

Phase-1 的最大阻塞：`CommitGate` 在 schema 为空时 **silent permissive**（`commit_gate.py` 旧 `_permissive = not bool(schemas)`），导致 ActionSchema 从未真正启用 → H3/H4/H5 不可验证。

修复（`commit_gate.py`）：
- `permissive` 改为**显式参数，默认 `False`**（§4.2：禁止 silent permissive）。
- 高风险写无 schema → verdict `abstain` + `schema_missing=True` + reason `schema_missing`（fail-closed；计入失败分析，不丢弃）。
- dev/debug 可显式 `permissive=True`。
- 旧单 agent / orchestrator 路径已显式传 `permissive=True` 保持原行为（不污染写安全实验）。
- `GateDecision` 新增 `schema_missing` 字段；`ActionSchema` 新增 `risk_level`。

## 2. ActionSchema 覆盖（§4.1）

`src/ravel_core/action_schemas.py`：airline + retail 主要高风险写工具 **100% 覆盖**（各 6 个）。

| 域 | 覆盖的写动作 |
|---|---|
| airline | cancel_reservation, update_reservation_flights, book_reservation, update_reservation_passengers, update_reservation_baggages, send_certificate |
| retail | cancel_pending_order, return_delivered_order_items, exchange_delivered_order_items, modify_pending_order_items, modify_pending_order_payment, modify_pending_order_address |

每个 schema 含 §4.1 要求字段：`risk_level`、`target_object_type`、`required_fields`（object_ref/field/freshness/source_tool/required_for）、`policy_checks`、`allowed_write_tools`、`requires_user_confirmation`、`requires_compare_and_swap`。

决策字段有政策依据（非硬编码）：airline 退改依赖 `cabin`（basic economy 不可退）；retail 依赖 `order.status`（pending/delivered 决定可执行动作）。

## 3. 单元测试（8，全过）

- 覆盖率：airline/retail 主写工具 uncovered=[]。
- 非 permissive：高风险无 schema → abstain + schema_missing。
- permissive dev 模式 → commit。
- 显式低风险无 schema → commit。
- 真 schema：陈旧证据 → 拦截（stale_fields，verdict reconcile/replan）；新鲜可追溯 → commit（evidence_valid）。

## 4. 待批准实验（§4.3）

methods = {No-Gate, Gate-Only, Ledger-Only, Gate+Requery, RAVEL-Full} ×
regimes = {FullSync, Delayed, ConflictingView, FieldMask 10%}，airline/retail 各 10 tasks。
将报告：schema coverage、schema_missing rate、gate caught missing/stale/conflict、overblock/recovery/unsafe-commit 实例、H3/H4 是否变得可测。

## 5. 诚实限制

- `policy_checks` 目前为声明式字符串，**未编程强制执行**；在接入前不得声称"政策合规已强制"。
- ActionSchema 的 `required_fields` 在 gate 时需由 runtime 把 `object_ref` 解析为真实对象 id（`build_action_schemas(target_object_id=...)`）；该解析的 runtime 接线属下一步。
