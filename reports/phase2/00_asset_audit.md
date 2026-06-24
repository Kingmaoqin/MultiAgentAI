# Phase-2 资产审计（00_asset_audit）

**日期**：2026-06-24 ｜ **分支**：`feature/ravel-mas` ｜ **commit**：`899494f`
**目的**：在跑任何 Phase-2 实验前，固化"当前到底有什么、什么可复用、什么阻塞复现"。
**范围说明**：本轮按用户指示**只写代码 + 跑 smoke**，正式/全量矩阵等批准后再跑。

---

## 1. 仓库与环境

| 项 | 值 |
|---|---|
| Repo | `/home/xqin5/multiaiagent` |
| Branch / HEAD | `feature/ravel-mas` / `899494f` |
| Python | 3.12.12（conda env `MDPC`） |
| tau2 / tau-bench | worktree `worktrees/tau2-clean`，commit `ddc66a7`（PR #314 之后）；通过 `uv run` 在 worktree 内运行，`src/tau2` + `src/experiments` 本地可导入 |
| tau2 在 MDPC 直接导入 | **不可**——必须经 worktree 的 uv 环境（`uv run python ...`） |
| 数据 | `worktrees/tau2-clean/data/tau2/domains/{airline,retail,telecom}/tasks.json` |

### 模型 endpoint（当前在线，已 curl 确认）

| 端口 | model id | 路径 | max_len | 角色 |
|---|---|---|---|---|
| 8005 | `g4` | `hf_p08_models/gemma-4-31B-it` | 16384 | 中等模型（agent + user） |
| 8192 | `gpt-oss` | `hf_p08_models/gpt-oss-120b` | 65536 | 强 reasoning 模型 |

### GPU

4× A100 80GB。GPU0 空闲（14 MiB）；**GPU1/2/3 被占满（74–79 GiB）**——与 co-tenant（`zihao_runs` 等）共享，存在 OOM/竞争风险。结论：Phase-2 正式跑应 **单 GPU 顺序 + watchdog**，`max-concurrency=1`，避免把 wall-clock/timeout 当成 visibility 效应（这是第二轮报告点名的偏差源）。

---

## 2. 可复用代码模块

### `src/ravel_core/`（中间件 / 单 agent 线 + 共享指标）
| 模块 | 行数 | 复用价值 |
|---|---|---|
| `metrics.py` | 290 | ✅ **直接复用**：`TrialMetrics`、`SafetyMetricsAccumulator`、`derive_safety_metrics`；EvidenceValid/SAR/CWR/UAR/CWCR/Recovery/Overblock 已实现，**零分母返回 None**（符合 §9.8） |
| `trial_logger.py` | 326 | ✅ **直接复用**：`TrialLogger` 写 JSONL event log + summary，`TokenRecord`（含 uncached），`TrialMeta`（含所有 seed/hash 字段） |
| `commit_gate.py` | 165 | ⚠️ **需改造**：schemas 为空时 `permissive` 直接 commit（见 §4 阻塞项） |
| `mse_router.py` | 168 | 🔁 MSE 路由雏形，DPR 将在其基础上扩展 |
| `reconciliation.py` | 361 | 🔁 ARB ladder 雏形 |
| `visibility.py` | 153 | 🔁 单 agent 侧 regime（FullSync/Delayed/FieldMask/ConflictingView） |
| `ravel_agent.py` / `multi_agent_orchestrator.py` | 598 / 740 | 单 agent + orchestrator 路径 |

### `src/ravel_mas/`（真正的多智能体系统，写安全实验在用）
- `team_agent.py`：`RAVELTeamAgent`（supervisor/policy/tool_worker + 确定性 CommitService），含独立 oracle、真实 FieldMask 遮蔽、按域决策字段——v2 审计修复已落地、97/97 测试通过。
- `views.py`：`ViewBuilder` regime 投影（FullSync/Delayed/RoleAwareFieldMask/ConflictingView）。
- `commit_service.py`：唯一写入口，`action_required_fields={}`（**空 → 等价 permissive**）。

### 配置 / 资产
- `configs/{benchmark_versions.json, experiment_matrix.yaml, model_endpoints.json}`。
- Splits 已存在：`artifacts/task_audit/splits_{pilot,dev,held_out}.csv` + `split_manifest.json`（✅ 复用做 paired task 选择，避免泄漏）。
- `scripts/`：`run_mas_safety.py`（regime×gate runner）、`generate_splits.py`、`aggregate_*`、`plot_*`。

---

## 3. 已有结果文件（状态标注）

| 目录 | 状态 |
|---|---|
| `results/mas_safety_corrected/` | ✅ **有效**（oracle 非循环度量，3 seed+CI，已入库 1714 文件） |
| `results/mas_safety/`, `results/mas_safety_v2/` | ❌ **已撤回**（循环度量等，见 `reports/审计回应_写安全实验_v2缺陷与修复.md`），不入 Phase-2 结论 |
| `results/multimodel/`, `results/ravel_corrected/`, `results/multiagent/` | LEGACY（单 agent / prompt-chain），不在多智能体范围 |
| `figures/fig01-04` | ✅ 修正版 headline 图 |

---

## 4. 阻塞复现 / 不可比较的原因（Blocking issues）

1. **CommitGate 仍是 permissive**（最高优先级）。`commit_gate.py:93/104` 在 `schemas` 为空时直接返回 `verdict="commit", reasons=("permissive_mode",)`；`commit_service.py` 的 `action_required_fields={}`。⇒ ActionSchema 未真正启用，**H3/H4/H5 当前不可验证**。Phase-2 §4 必须：建 ActionSchema、schema 缺失时默认 `replan/abstain`、`schema_missing` 计入失败分析、正式实验关闭 permissive。
2. **缺 trajectory / event 级新指标**。现有 `TrialLogger` 记录了 token/tool/candidate/gate/recon，但 **没有** trajectory_edit_distance、first_divergence_step、tool_selection_accuracy、argument_accuracy、dependency_order、SeenButUnused/UnsupportedArgument 等 §3.2/§7 指标 → 需新增（Phase-2 §3、§7）。
3. **缺机制拆解 regime**。当前只有 4 个粗 regime；ConflictingView 未拆成 LabelOnly/WrongValueOnly/HistoricalVersionOnly/DualVersion；FieldMask 未做 mask-rate sweep + 字段类型分层 → 需新增（§5.1/§5.2）。
4. **缺新算法**：CSI（`conflict_signal.py`）、DPR（`dependency_router.py`）、Evidence Uptake（`evidence_uptake.py`）均未实现（§6/§7）。
5. **telecom 不可直接解释**：`max_steps=25` 天花板 + cooperative timeout，需先修 max_steps→50/60、强制 timeout、固定 user seed、统一 prompt/parser、去 GT prompt leak，且只有 no-perturbation baseline > 0% 才继续（§5.4）。
6. **GPU 竞争**：见 §1，正式跑需单 GPU 顺序 + watchdog。
7. **smoke baseline runner**：现有 `run_mas_safety.py` 是 regime×gate 写安全 runner，**不是**干净的 "Single-Agent ReAct baseline vs RAVEL-FullSync" 对照 runner（§8.3 方法 1–3）→ Phase-2 需补一个统一 runner。

---

## 5. 结论

- 基础设施（logger + safety metrics + splits + 双模型 endpoint）**可复用、质量好**，不需推倒重来。
- 进入正式实验前的**必须修复**：①启用 ActionSchema/非 permissive gate；②补 trajectory/uptake 指标；③实现机制拆解 regime + CSI + DPR。
- 本轮交付顺序遵循计划 §13：audit → smoke → logging/metrics → ActionSchema/gate → 机制拆解 regime → CSI → DPR；**全量矩阵 / 统计分析等用户批准**。
