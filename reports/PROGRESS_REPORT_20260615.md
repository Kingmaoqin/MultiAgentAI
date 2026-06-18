# RAVEL 多智能体实验进度报告

**日期**: 2026-06-15  
**作者**: Claude Code (代 Xinyu Qin 整理)  
**项目路径**: `/home/xqin5/multiaiagent/`  
**状态**: NO-GO（持出集）/ GO（开发集冒烟 + 模块开发）

---

## 1. 项目概述

**RAVEL**（Risk-Adaptive Visibility and Evidence Ledger）是针对多智能体 LLM 系统的**令牌高效、写安全**框架，包含以下核心模块：

| 模块 | 功能 |
|------|------|
| VDL（版本化增量账本） | 追加式证据存储；字段级版本追踪、摘要、不可变冻结 |
| MSE-Router（最小充分证据路由器） | 规则路由，仅向每个智能体分发所需最小证据 |
| Commit Gate（提交门控） | 两阶段写控制；工作智能体提议候选写，验证器审核 5 项条件 |
| ARB（自适应协调预算） | 6 阶梯逐级升级，拒绝直接跳转全量原始获取 |

**实验台**: tau2-bench（airline / retail / telecom 三域）  
**模型**: Qwen3.6-27B（本地 vLLM 端口 8190/8200）、Gemma-4-31B（端口 8005）  
**算力**: 4× A100 80GB，与 zihao_runs 共享

---

## 2. 本轮完成工作（2026-06-15）

### 2.1 基线冒烟测试 ✅ 三域全部通过

| 领域 | 任务 | 奖励 | 结果细节 | 耗时 |
|------|------|------|----------|------|
| Airline | task 32（航班改签） | **1.0** | DB=1.0，5 工具调用（3R+2W），user_stop | 297s |
| Retail | task 0（换货） | **1.0** | DB=1.0，NL_ASSERTION=1.0，5 工具调用（4R+1W），user_stop | 218s |
| Telecom | airplane_mode+roaming | **1.0** | DB=1.0，ENV_ASSERTION=1.0（数据已开+速度=excellent），2W，user_stop | 86s |

- 模型：Qwen3.6-27B（端口 8190），`temperature=0.0`，`seed=101`
- Benchmark 根：`/home/xqin5/multiaiagent/worktrees/tau2-clean`（commit `ddc66a7`，干净）
- 结果存储：`results/baseline_reproduction/{airline,retail,telecom}_smoke/results.json`

> **意义**：B5 阻塞项已消除。任务加载、用户模拟器、工具执行、DB 重置、官方评估器三域均已在真实模型下验证通过。

### 2.2 RAVEL 核心模块完成

| 文件 | 状态 |
|------|------|
| `src/ravel_core/evidence.py` | ✅ VDL + 不可变冻结 |
| `src/ravel_core/visibility.py` | ✅ 4 观察机制（FullSync / Delayed / FieldMask / ConflictingView） |
| `src/ravel_core/commit_gate.py` | ✅ 两阶段门控，5 条件审核 |
| `src/ravel_core/mse_router.py` | ✅ 最小充分证据路由，角色+目标+依赖三层过滤 |
| `src/ravel_core/reconciliation.py` | ✅ ARB 6 阶梯 + 风险评分公式（eq.14） |
| `src/ravel_core/trial_logger.py` | ✅ JSONL 事件日志 + §17 摘要 JSON |
| `src/ravel_core/metrics.py` | ✅ 7 项安全指标（eq.19-25） |
| `src/ravel_core/benchmark_adapter.py` | ✅ 零 tau2 导入适配层 |

**测试覆盖**: 58 个测试全部通过（单元/集成/不变量/变异探针）

### 2.3 任务审计与分割

- `artifacts/task_audit/all_tasks.csv`：2449 个任务（airline 50 + retail 114 + telecom 2285）
- `artifacts/task_audit/included_tasks.csv`：2227 个任务满足 RAVEL §3.2 纳入条件
- `artifacts/task_audit/splits_{dev,pilot,held_out}.csv`：固定种子 `seed=20260615` 确定性分割

### 2.4 tau2 基准环境

- 干净 worktree：`worktrees/tau2-clean`（commit `ddc66a7`，无补丁）
- 原始仓库 `/home/xqin5/tau2-bench` 有本地消息解析器补丁——仅可用于显式标注的"补丁敏感性检查"，不得用于正式结果

---

## 3. 当前阻塞项状态

| 编号 | 阻塞描述 | 状态 |
|------|----------|------|
| **B1** | tau2 解析器补丁污染 | ✅ **已解决**：干净 worktree 作为正式根 |
| **B2** | Proposal 指定模型端点未确认 | ❌ 当前用 Qwen3.6-27B；Proposal 要求 gpt-oss-120b、Qwen3-32B 等 |
| **B3** | Airline 任务数量不足 | ❌ 仅 15 个任务有写操作纳入，持出集为 0；需确定扩展规则（拒绝任务/种子重复/人工标注） |
| **B4** | patch_002 独立评审未通过 | ❌ 评审发现 3 个阻塞点（ARB 提交控制、适配器写门执行、回放日志）；作者已修复，等待重新评审 |
| **B5** | 各域基线未复现 | ✅ **已解决**（2026-06-15）：三域全部 reward=1.0 |

**当前剩余阻塞**: B2、B3、B4（B4 最紧迫，影响 pilot 启动）

---

## 4. 审查与预注册

| 文档 | 状态 |
|------|------|
| `docs/04_PREREGISTRATION.md` | ✅ RQ1-5, H1-H5，统计方案，异常处理已填写 |
| `reviews/patch_001_ravel_core_review.md` | ✅ APPROVED |
| `reviews/patch_002_modules_review.md` | ❌ CHANGES REQUIRED（待二轮评审） |
| `reports/CLAIM_EVIDENCE_LEDGER.md` | ✅ 声明边界模板已建立 |

---

## 5. GO/NO-GO 当前状态

```
NO-GO  ← 持出集实验（B2/B3/B4 任一阻塞）
GO     ← 开发集冒烟运行 ✅（现已全部通过）
GO     ← 模块开发与单元测试 ✅
GO     ← patch_002 独立评审（可并行进行）
GO     ← Airline 扩展规则讨论与文档
```

---

## 6. 下一步计划

### 紧急（本周）

1. **patch_002 二轮独立评审**（B4 阻塞 pilot）
   - 评审人确认 3 个修复点：ARB 不直接提交（必须经门控）、适配器写门强制执行、回放事件含完整证据 ID
   - 通过后 → `GO` for pilot

2. **Airline 扩展规则决策**（B3）
   - 方案 A：纳入拒绝型任务（agent 正确拒绝不合规请求），扩充 airline 任务池
   - 方案 B：种子重复（同一任务不同 seed = 不同观察机制实例）
   - 方案 C：人工添加任务标注（修改标注而非基准）
   - **建议**: 优先方案 A，不需要修改 tau2 任务数据

3. **模型端点确认**（B2）
   - 确认 Qwen3-32B（或等效 32B 量级）是否可部署
   - 若无法部署 gpt-oss-120b，需在预注册中记录替代模型并说明差异

### 短期（patch_002 通过后）

4. **Pilot Run**（10 对任务/域，FullSync + 1 扰动机制，1 轮重复）
   - 验证 TokenRecord 日志、安全指标累积、配对 bootstrap

5. **更新 MANIFEST.json**（当前显示 51 测试，应为 58）

6. **开发集扩展运行**（每域 5-10 个额外任务，不含持出集）

---

## 7. 资产快照

```
/home/xqin5/multiaiagent/
├── src/ravel_core/           ← 8 个模块，全部实现
├── tests/test_new_modules.py ← 58 个测试（全通过）
├── scripts/
│   ├── task_audit.py         ← AST 写工具检测（已修复）
│   └── generate_splits.py    ← 种子固定分割
├── artifacts/task_audit/     ← 2449/2227 任务 CSV + 分割 JSON
├── results/baseline_reproduction/
│   ├── airline_smoke/        ← reward=1.0, 297s ✅
│   ├── retail_smoke/         ← reward=1.0, 218s ✅
│   └── telecom_smoke/        ← reward=1.0, 86s  ✅
├── reports/
│   ├── GO_NO_GO_REPORT.md    ← 实时更新
│   └── PROGRESS_REPORT_20260615.md  ← 本文档
├── docs/
│   ├── 04_PREREGISTRATION.md ← H1-H5, RQ1-5 预注册
│   └── 00_ASSET_INVENTORY.md ← 4 个活跃端点
├── worktrees/tau2-clean/     ← 正式 benchmark 根（commit ddc66a7）
└── RUNBOOK.md                ← 14 步复现手册
```

---

## 8. 技术备注

### 令牌经济（未正式验证）
- TokenRecord 已实现：`input_tokens`、`cached_input_tokens`、`output_tokens`
- uncached_input_tokens = max(0, input - cached)（eq.16）
- 当前 `agent_cost=0.0`（本地端点不计费），需添加 token 计数 hook 验证

### 观察机制（4 种，尚未对比实验）
- FullSync：智能体看到所有当前字段
- Delayed(d=1,2)：证据延迟 d 步到达
- FieldMask：部分字段被屏蔽
- ConflictingView：两个智能体看到不一致的字段值

### GPU 共享注意
- 4× A100 与 zihao_runs 共享
- 避免多卡并发：每次单 GPU 顺序运行 + watchdog
- telecom 任务仅需 86s/任务，风险较低

---

---

## 9. 实验进展（2026-06-15 20:30 更新）

### 9.1 关键 Bug 发现并修复：CommitGate 全量阻塞

**症状**: 所有 RAVEL 实验条件（FullSync/Delayed/FieldMask/ConflictingView）reward 全部为 0.0

**根因**: `CommitGate(schemas={})` 初始化为空 schema 时对所有写操作返回 `verdict="abstain"`（应为 `commit`）  
代码位置：`src/ravel_core/commit_gate.py` 第 95-100 行

```python
# BUG（已修复前）:
schema = self.schemas.get(candidate.action)
if schema is None:
    return GateDecision(verdict="abstain", ...)  # ← 阻塞所有写

# FIX:
if schema is None:
    if self._permissive:  # empty schemas → permissive mode
        return GateDecision(verdict="commit", reasons=("permissive_mode",))
    return GateDecision(verdict="abstain", ...)
```

**影响**: 当前所有 RAVEL 运行结果（约 40+ 完成任务）全部无效，奖励应为 0.0 是因为**所有写操作被门控阻塞**，而非可见性机制造成的降级

**修复验证**: `test_commit_gate_permissive_allows_all_writes()` 和 `test_commit_gate_strict_blocks_unknown_action()` 两个新测试通过；全部 18 个单元测试通过

### 9.2 当前进行中实验状态

| 实验条件 | 完成 | 奖励 | 说明 |
|---------|------|------|------|
| Baseline (llm_agent_gt) [airline] | 9/10 | 0.333 | task 33 卡住（>42min） |
| Baseline (llm_agent_gt) [retail] | 13/14 | 0.231 | task 109 仍运行中 |
| Baseline (llm_agent_gt) [telecom] | 6/14 | 0.333 | 运行中 |
| RAVEL-FullSync × 3 域 | 2-6/10-14 | **全部 0.0** | ⚠️ 受 CommitGate bug 影响 |
| RAVEL-Delayed × 3 域 | 2-5/10-14 | **全部 0.0** | ⚠️ 受 CommitGate bug 影响 |
| RAVEL-FieldMask × 3 域 | 3-6/10-14 | **全部 0.0** | ⚠️ 受 CommitGate bug 影响 |
| RAVEL-ConflictingView × 3 域 | 2/10-14 | **全部 0.0** | ⚠️ 受 CommitGate bug 影响 |

⚠️ **当前运行中的进程将全部产生无效结果（0.0），因为它们已加载 bug 版本代码**

### 9.3 GPU 竞争分析

- 当前同时运行约 **30 个进程 / 38 并发 vLLM 请求**
- 每次 LLM 调用耗时从基线的 8-13s 增至 **31-100s**（38 个并发请求争抢 GPU 0）
- 基线在 GPU 空闲时运行（3-5 并发），当前 RAVEL 运行在满载时进行
- 导致：原本需要 200s 的任务现在需要 400-800s，大量任务超时

### 9.4 下一步：修复版重新运行

当前进程完成后执行：

```bash
# 等待当前所有进程结束（检查无活跃 run_ravel_exp 进程）
ps aux | grep run_ravel_exp | grep -v grep

# 执行修复版顺序运行（每个域依次进行，避免 GPU 竞争）
cd /home/xqin5/multiaiagent/worktrees/tau2-clean
bash /home/xqin5/multiaiagent/scripts/run_ravel_corrected.sh airline
bash /home/xqin5/multiaiagent/scripts/run_ravel_corrected.sh retail
bash /home/xqin5/multiaiagent/scripts/run_ravel_corrected.sh telecom

# 分析结果
PYTHONPATH=/home/xqin5/multiaiagent/src python3 /home/xqin5/multiaiagent/scripts/analyze_results.py --corrected
```

### 9.5 新增文件

| 文件 | 说明 |
|------|------|
| `scripts/analyze_results.py` | 配对 bootstrap 统计分析（95% CI, p 值） |
| `scripts/run_ravel_corrected.sh` | 修复版顺序运行脚本（含 ConflictingView） |
| `results/analysis_summary.json` | 机器可读实验摘要 |

---

*报告最终更新于 2026-06-15 20:30 UTC+0*
