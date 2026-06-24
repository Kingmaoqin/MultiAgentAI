# Phase-2 §6: Conflict-as-Signal Evidence Interface（RAVEL-CSI）（08）

**状态**：代码 + 单元测试完成（`src/ravel_core/conflict_signal.py`）；对照实验（§6.3）**待批准**。

## 1. 动机与与已有工作的区别

原 `ConflictingView` regime **污染事实值**（给 worker 一个错的/旧的字段值），把"冲突信息是否有用"与"扰动值是否改变探索路径"混在一起。CSI 把"冲突"从**错误值扰动**变成**结构化不确定性接口**：始终给 agent 可靠的当前值，外加一个 typed conflict signal。

与已有工作区别（§6 要求写清）：已有工作多讨论 fault injection、read-set consistency、execution provenance、dependency memory；**CSI 聚焦的是在多智能体工具写操作中，把版本冲突暴露为结构化 uncertainty signal，而不是把冲突值直接塞进上下文。**

## 2. 接口（§6.1）

`build_conflict_signal(...)` 由版本状态确定性派生 `ConflictSignal`：`field, current_value, current_version, conflict_status∈{none,possible_conflict,confirmed_conflict,stale_view}, conflict_source∈{agent_local_view,ledger_version_gap,exogenous_mutation,user_side_update}, older_versions_available, write_precondition∈{none,must_recheck_before_commit}, recommended_resolution∈{fetch_latest,compare_versions,ask_user,block_write}`。

派生规则：seen_version=None → possible_conflict + fetch_latest + recheck；seen<current 且值不同 → confirmed_conflict + compare_versions；seen<current 值相同 → stale_view；seen==current → none。

## 3. 四个 variant（§6.2，均不给假值）

| variant | 暴露内容 |
|---|---|
| `LabelOnly` | 当前值 + conflict label + version + pointer |
| `DualVersion` | 当前值 + 旧版本值（显式标记两版本） |
| `GatePreflight` | LabelOnly + 强制 `must_recheck_before_commit` |
| `NoWrongValue` | 当前值 + label，硬保证不出现假值（vs OriginalConflictingView 的对照探针） |

**错误值扰动（WrongValueOnly）只作为 perturbation probe，不作为方法**（§6.2）。

## 4. 单元测试（7，全过）

所有 variant 都暴露可靠 current_value、绝不暴露假值；DualVersion 同时给两版本；stale vs confirmed 区分；fresh→无 conflict 无 recheck；未见字段→possible_conflict；GatePreflight 强制 recheck；未知 variant 抛错。

## 5. 待批准的评估问题（§6.3）

1. CSI 是否保留 ConflictingView 的收益；2. 是否减少 wrong-value corruption；3. 是否增加 requery-before-write；4. 是否降低 UnsafeActionRate/ConflictingWriteRate；5. 是否不显著牺牲 FSS；6. token 是否增加但仍低于 FullSync raw。
将用 §3.2 指标（first_divergence_step、requery count、gate verdict 分布、UAR/CWR）跨 Gemma4/gpt-oss、airline/retail 评估。
