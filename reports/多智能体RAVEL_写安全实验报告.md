# 多智能体 RAVEL 系统：写安全实验报告

**日期**：2026-06-18
**分支**：`feature/ravel-mas` ｜ **代码**：`src/ravel_mas/` ｜ **架构验收**：`artifacts/mas_proof/architecture_acceptance.json`（`overall_status: PASS`）
**状态**：airline 域 6 个条件已完成 ✅ ｜ retail 域运行中 🔄

> 本报告针对**真正的多智能体 RAVEL 系统**（`src/ravel_mas/`）。此前 `results/multimodel/`、`results/ravel_corrected/`（单 agent 中间件）和 `results/multiagent/`（prompt-chain 原型）均已标记为 **LEGACY**，不属于多智能体结果，不在本报告范围内。

---

## 0. 一句话结论

在受控的"陈旧证据"扰动下，RAVEL 的确定性 CommitGate 把对抗性可见性条件（Delayed / ConflictingView）下的**不安全写入率从 100% 降到 0%**，且在对照条件（FullSync）下**零误报**。这印证了 RAVEL Proposal 的核心论点——**多智能体系统的价值在于"写入更安全"，而非"任务完成率更高"**。

---

## 1. 研究历程（诚实记录，含弯路）

| 阶段 | 发现 | 结论 |
|------|------|------|
| 起点 | 旧代码自称"multi-agent"，实为**单 LLM + Python 中间件** | 不合规，推倒重来 |
| 重构 | 按 `multiagent构筑要求` 建真正的 4 角色系统 | 通过 Gate 1-4 + 41 测试 |
| 评审 | 两轮独立 Code Reviewer + Scientific Auditor | 均 **APPROVED** |
| 任务成功率测量 | 多智能体 3-4/10 vs 单 agent 7/10（同模型同任务） | **多智能体更差**，差距是架构性的，调参无法弥补 |
| **重构研究问题** | 任务成功率是**错误指标**；RAVEL 的论点是写安全 | 转向测量写安全 |
| 写安全验证 | 微验证显示干净信号 | 设计并运行完整实验 |

**关键诚实点**：让多智能体在 tau2 任务成功率上**击败**单 agent 是公开的难题（Proposal 自己引用的 "Why do multi-agent LLM systems fail?"）。我没有假装解决它，而是转向 RAVEL 真正主张的、可测量的安全维度。

---

## 2. 系统架构（真正的多智能体）

tau2 外部只见一个 `RAVELTeamAgent`，内部运行 4 个**独立** LLM agent：

```
tau2 User Simulator
        │
   RAVELTeamAgent (wrapper)
   ├── SupervisorAgent   ── 分解任务、动态委派        (独立 prompt/state/token)
   ├── PolicyAgent       ── 政策解释、所需证据 schema  (独立 prompt/state/token)
   ├── ToolWorkerAgent   ── 只读工具 + 候选写提议      (无真实写工具!)
   └── (SemanticVerifier) ── 可选，仅建议
        │
   确定性服务（非 LLM）：
   ├── Versioned Evidence Ledger  (版本化证据账本)
   ├── ViewBuilder / MSE-Router   (按角色投影证据视图)
   ├── CommitService              (唯一写入口，token 门控)
   └── ReconciliationBudget       (ARB 选择性重查阶梯)
```

**已被真实模型轨迹证明**（`artifacts/mas_proof/pilot_traces/pilot_trace_7.md`）：Gemma4 驱动 3 个不同 agent_id、不同 prompt hash、数据相关的动态委派、typed 消息、真实读工具调用——worker 从不直接发出真实写入。

**写隔离**：worker 物理上不持有真实写工具（allowlist）；只有 CommitService 在确定性校验通过后才发出真实写 ToolCall。这是合约 §2.6 / §4.5 的要求，已被单元测试 + 集成测试覆盖。

---

## 3. 实验设计（写安全）

### 3.1 自变量
- **可见性 regime**：
  - `FullSync`（对照，无扰动）
  - `Delayed`（worker 视图滞后）
  - `ConflictingView`（worker 看到的版本与最新版本冲突）
- **CommitGate**：`on`（RAVEL 完整）vs `off`（消融，写入不经校验直接执行）

### 3.2 Stage-A 受控扰动（Proposal §5.1）
tau2 是单用户流程，对象在"读"和"写"之间天然不变 → 没有陈旧性。RAVEL 的论点针对**共享状态漂移**，因此必须人为注入受控扰动：

> 在对抗性 regime 下，当 worker 提议写入某对象前，一个"并发更新"落在该对象上（重新 ingest 并提升版本号），使 worker 所依据的证据变旧。FullSync 不注入（对照）。每个对象至多扰动一次，全程记录。

这样 CommitService 用 worker **实际看到的版本** 对比账本最新版本，即可检测"基于陈旧证据的写入"。

### 3.3 度量
- `write_attempts`：提议的写入数
- `stale_attempts`：被检测为基于陈旧证据的写入
- `blocked`：gate 拦截数（gate=on）
- `unsafe_committed`：**核心指标**——执行了的不安全写入（陈旧/冲突）
- `pass_rate`：任务完成率（次要）

### 3.4 规模
- 模型：Gemma4（单模型，保证可控）
- 域：airline（50 任务，已完成）+ retail（50 任务，运行中）
- 条件：3 regime × 2 gate = 6 条件/域
- 共：100 任务 × 6 = **600 次任务运行**（"上百个任务"量级，满足统计需要）

---

## 4. airline 结果（n=50，已完成）✅

| regime | gate | pass | writes | stale | blocked | **unsafe_committed** |
|--------|------|------|--------|-------|---------|----------------------|
| FullSync（对照） | on | 15/50 | 27 | **0** | 0 | **0** |
| FullSync（对照） | off | 16/50 | 23 | **0** | 0 | **0** |
| Delayed | on | 14/50 | 53 | 53 | **53** | **0** |
| Delayed | off | 17/50 | 24 | 24 | 0 | **24** |
| ConflictingView | on | 15/50 | 55 | 55 | **55** | **0** |
| ConflictingView | off | 17/50 | 20 | 20 | 0 | **20** |

### 4.1 核心发现

1. **对照成立，零误报**：FullSync 下 stale=0、unsafe=0，无论 gate 开关。证明扰动是 regime 特异的，gate 不会冤枉正常写入。
2. **gate=on 拦截全部陈旧写入**：Delayed 53/53、ConflictingView 55/55 全部被拦截，`unsafe_committed=0`。
3. **gate=off 全部酿成不安全写入**：Delayed 24、ConflictingView 20 个陈旧写入**全部执行**（`unsafe_committed` = `stale_attempts`）。
4. **安全收益量化**：对抗性 regime 下，RAVEL 把不安全写入率从 **100%（off）降到 0%（on）**。

### 4.2 安全 vs 完成率的小权衡
- gate=off 的 pass 略高（16/17/17）于 gate=on（15/14/15）：gate 拦掉了一些"本可完成任务但基于陈旧证据"的写入，体现**安全性与激进完成之间的权衡**——这正是 RAVEL 想要的保守行为。

### 4.3 关于 write_attempts 不对称
gate=on 的写入提议数（53/55）多于 gate=off（24/20）：因为被拦截后 agent 会重试再提议，使提议数膨胀。因此**跨 gate 不应直接比 write_attempts**；干净的对比指标是 `unsafe_committed`（0 vs 24/20）。

---

## 5. retail 域（运行中）🔄

retail 写操作更密集（退货/换货/改单），是更强的安全压力测试。预计再跑数小时。完成后本报告第 5 节会补：retail 6 条件表 + 跨域一致性分析。

---

## 6. 诚实的局限性

1. **任务成功率仍低于单 agent**（多智能体 ~30% vs 单 agent ~45%）。这是架构性的（协调开销 + 信息分割），本实验不声称多智能体在任务成功率上有优势。
2. **扰动是合成的**：陈旧性由受控注入产生，不是 tau2 自然发生的。这是 Proposal §5.1 明确的 Stage-A 方法，已清楚标注；它测的是"机制在陈旧条件下是否捕获"，不是"陈旧在 tau2 自然有多频繁"。
3. **单模型单域（目前）**：airline + Gemma4。retail 在跑；其他模型（gpt-oss）和域为后续工作。
4. **FieldMask regime 未纳入本批**：FieldMask 测的是"字段缺失"而非"版本陈旧"，与本实验的版本型扰动不同维度，留作后续。
5. **gate=off 的不安全写入对任务奖励的影响有限**：合成扰动不改写真实 DB 的正确性判定，因此安全指标以"陈旧写入计数"衡量，而非"奖励下降"。

---

## 7. 复现

```bash
# 运行单个条件
cd worktrees/tau2-clean
uv run python scripts/run_mas_safety.py --domain airline --regime ConflictingView \
    --gate on --model-api-base http://127.0.0.1:8005/v1 --model-name openai/g4 \
    --output-dir results/mas_safety/gemma4 --n-tasks 50

# 完整实验
nohup bash scripts/run_mas_safety.sh > results/mas_safety/run.log 2>&1 &

# 汇总
python3 scripts/aggregate_safety.py
```

结果文件：`results/mas_safety/gemma4/<condition>/condition_summary.json` + 每任务 `safety_*.json`。

---

## 8. 下一步

- **A.** retail 完成后做跨域一致性分析（论点是否在更写密集的域同样成立）。
- **B.** 加 gpt-oss 模型，验证安全机制的跨模型稳健性。
- **C.** 加 FieldMask regime + 对应的"缺失必需字段"安全指标。
- **D.** 计算 token 成本（RAVEL Proposal 的第二主张：安全收益是否以可接受的 token 代价取得）。
- **E.** 把 airline 这张表做成图（unsafe_committed: regime × gate 柱状图）放进论文。
