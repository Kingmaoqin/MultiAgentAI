# Phase-2 日志与指标系统（02_logging_and_metrics_tests）

**日期**：2026-06-24 ｜ **状态**：代码 + 单元测试完成（19/19 通过）；运行期集成（MAS trace 发射 canonical 行）为下一步。

## 1. 交付的代码

| 文件 | 内容 |
|---|---|
| `src/ravel_core/event_logger.py` | **新增**。Canonical Phase-2 事件 schema（§3.1）：`EVENT_TYPES`/`AGENT_ROLES` 词表、`make_event`、`validate_event`、`Phase2EventLogger`（append-only JSONL，自增 `event_index`、写时校验）、`normalize_mas_trace`/`normalize_event`（把现有 `RuntimeTrace` 的 `kind` 行与 `TrialLogger` 的 `event_type` 行归一到同一 schema）、`read_events`。 |
| `src/ravel_core/metrics.py` | **扩展**（保留原 safety 代码）。新增 trajectory/token 指标：`normalize_args`（id 抽象的参数签名）、`canonical_tool_sequence`、`sequence_edit_distance`、`first_divergence_step`、`tool_selection_accuracy`、`argument_accuracy`、`dependency_order_satisfaction`、`loop_count`、`unnecessary_retry_count`、`aggregate_token_usage`、`count_tool_calls`、`trajectory_metrics`。 |
| `scripts/analyze_phase2_results.py` | **新增**。遍历 `*_summary.json` + event log → 每 trial 一行 §3.2 CSV；FullSync 按 (domain,task,method,model,seed) 作为 trajectory 参照；**零分母 / 未定义统一写 `NA`**（§9.8）。 |
| `tests/test_phase2_logging_metrics.py` | **新增**。19 测试，覆盖计划 §3.2 要求的 5 类。 |

## 2. 设计要点（符合计划约束）

- **不存隐式 CoT**（§3.1）：`validate_event` 主动**拒绝** `chain_of_thought/cot/reasoning_trace/scratchpad/thinking` 等键。
- **零分母 = None/NA**（§9.8）：safety 与 trajectory 指标在分母为 0 时返回 `None`，CSV 落 `NA`，绝不强填 0。
- **复用而非重写**：safety 指标沿用既有 `derive_safety_metrics`/`SafetyMetricsAccumulator`；新增只补 trajectory/token 层与统一 schema。
- **id 抽象的轨迹比较**（§3.2 "standardized arguments"）：`normalize_args` 把形如 `R1234` 的实体 id 抽象为 `<ID>`，使不同 reservation/order id 的同构轨迹可比，同时保留非 id 字段差异（如 `cabin=economy` vs `business`）。

## 3. 单元测试（5 类全覆盖，19/19 通过）

| 计划要求的测试类 | 对应用例 |
|---|---|
| token aggregation | `test_token_aggregation_sums_only_llm_calls`、`test_token_record_uncached_never_negative` |
| event schema validation | `test_valid_event_passes`、`test_missing_header_is_flagged`、`test_unknown_event_type_and_role_flagged`、`test_chain_of_thought_key_rejected`、`test_uncached_gt_input_flagged`、`test_logger_writes_and_validates`、`test_logger_rejects_bad_event`、`test_normalize_mas_trace_maps_kind` |
| trajectory canonicalization | `test_normalize_args_abstracts_ids`、`test_canonical_tool_sequence_and_edit_distance`、`test_first_divergence_and_accuracy`、`test_loop_and_retry_counts`、`test_trajectory_metrics_na_when_no_reference` |
| safety metric zero-denominator | `test_safety_zero_denominator_returns_none`、`test_accumulator_zero_denominator_none` |
| evidence valid computation | `test_evidence_valid_and_unsafe_rates`、`test_caught_conflict_and_recovery_and_overblock` |

运行：`conda run -n MDPC python -m pytest tests/test_phase2_logging_metrics.py -q -p no:hypothesis` → **19 passed**。
（注：`-p no:hypothesis` 仅为绕过环境内 hypothesis 插件缺 `sortedcontainers` 的 summary-hook 报错，与本测试无关。）

## 4. 真实数据交叉验证

对 smoke 的 `pilot_trace_0.jsonl`（25 行）归一后：`aggregate_token_usage` = `total_tokens 22620`，与 `safety_0.json` 完全一致 → token 口径自洽。

## 5. 下一步（仍属"写代码"阶段）

1. **运行期集成**：扩展 `ravel_mas` 的 trace 发射，使其在每次 worker 读工具调用 / commit 时写 canonical `tool_call`/`commit` 行（带 `tool_name`/`tool_args`/`object_version`），让 trajectory 指标对 MAS 运行真正可算。
2. 进入 §4 ActionSchema + 非 permissive CommitGate。
