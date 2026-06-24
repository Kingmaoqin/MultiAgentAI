# Phase-2 §7: Evidence Uptake Attribution + Dependency-Preserving Router（09）

**状态**：代码 + 单元测试完成（`evidence_uptake.py`、`dependency_router.py`、`field_masking.py`）；对照实验（§7.3）**待批准**。

## 1. Evidence Uptake Attribution（§7.1）

核心问题：不是 agent 是否"看见"证据，而是它是否"使用"证据。

`attribute(...)` 为每个候选写动作建立 argument→evidence 归因：每个参数值映射到 `evidence_id | stale_memory | hallucinated | unsupported`；据此分类 `uptake_status∈{used_seen,ignored_seen,used_stale,hallucinated,unsupported}` 与 `uptake_failure_type∈{seen_but_unused,conflict_ignored,dependency_break,...}`。

`UptakeAccumulator.metrics()` 输出 §7.1 指标（零分母→None）：`SeenButUnusedRate, StaleEvidenceUseRate, UnsupportedArgumentRate, ConflictIgnoredRate, EvidenceToActionCoverage, CorrectionSensitivity`。

与已有 dependency-memory 工作的区别（§7 要求写清）：已有工作多关注 long-context memory construction；**这里关注 field-level evidence 是否被用于高风险写动作**，并据此度量"看见但没用"。

## 2. Dependency-Preserving Router（§7.2）

`build_dependency_graph(domain)` 从 ActionSchema registry 派生 field-level 依赖：凡作为某动作的 argument/precondition/policy/authorization/conflict_check 的字段即 action-critical。`classify_field` → `{must_keep, should_keep, compressible, droppable}`。`route_evidence`：must_keep 发原值+version+source+digest；should_keep 发 header/delta；compressible 发 schema summary；droppable 仅留 ledger pointer。`required_read_set` 给出高风险写前必须 fetch 的 read-set（强制 preflight）。

与 random mask 的关键区别：DPR **从不删 action-critical 字段**，只压缩/丢弃无下游依赖的字段 → 这是"用 token 节约换 success/safety 损失"之外的、有算法价值的第三条路。

## 3. Field-masking 机制拆解（§5.2，配合 DPR）

`field_masking.py` 实现确定性、seed 控制的 regimes：`FieldMaskRandom_{5,10,20,30}`（seeded 可复现）、`MaskIrrelevantOnly`、`MaskSupportingOnly`、`MaskActionCriticalOnly`（压力探针）、`DependencyPreservingMask`（≈DPR）。字段类别来自 DPR 依赖图（基于 schema，非猜测）。

## 4. 单元测试（17，全过）

uptake：used_seen / hallucinated / used_stale / 零分母 None / coverage+unsupported rate / correction probe。DPR：must_keep 保留、未知压缩、列出可丢弃、route 形状 + 正 token 节约、高风险 read-set。masking：random 对 seed 确定性、action-critical 定向、dependency-preserving 不删关键、irrelevant-only 保关键、apply+rate、零字段 None、未知 regime 抛错。

## 5. 待批准对照（§7.3）

FullSync raw / RandomMask10 / RecencyMask / HeaderOnly / DPR / OracleRouter / RAVEL-DPR+CSI+Gate。目标：DPR 比 RandomMask 稳、比 FullSync 省 token、接近 OracleRouter、不增 UAR、降低 SeenButUnusedRate 或 UnsupportedArgumentRate。

## 6. 诚实限制

- uptake 的参数→证据匹配目前按**值相等**（`_match_value`）；同值字段可能误归因，正式 uptake 实验前需评估是否改为 key-aware 匹配（已在 CODE_REVIEW_REQUEST 标注）。
- DPR `routing_token_savings` 是字符长度代理，非真实 tokenizer 计数。
