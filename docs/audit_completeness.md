# RAVEL 新一轮实验对照 Proposal 的完成度分析草稿

## Executive Summary

**当前判断**：基于你已提供的实验报告与 Proposal，可以形成一份**结构化、可执行的分析草稿**，但**还不足以形成终版定量结论**。最关键的缺口不是“有没有结果”，而是**缺少原始 per-trial 结果文件、独立日志、完整运行配置、commit/patch 清单与模型服务快照**，因此目前很多结论只能到“方向性判断”，还不能稳健地给出 Proposal 所要求的 paired bootstrap、mixed-effects、Holm 校正和完整复现链。fileciteturn0file0 fileciteturn0file1

**当前最强证据**是：在相同系统内，仅改变 visibility regime，确实会改变最终成功率与 failure path；这一点与 Proposal 的核心问题高度一致，也与 τ-bench/τ²-bench 对真实工具轨迹和最终数据库状态评价的设计方向一致。当前报告中，Qwen3 airline 域已经出现了 FullSync、Delayed、FieldMask、ConflictingView 四种 regime 的明显差异，而且 ConflictingView 在部分任务上出现了反直觉提升，这说明“visibility 是一等变量”的命题具备实证支撑，但“单调退化”的简单叙事已经受到挑战。fileciteturn0file0 fileciteturn0file1 citeturn0academia47turn0academia46turn0academia45

**当前最弱证据**集中在 Proposal 的真正主张上：`TokensUncached`、`EvidenceValidRate`、`UAR`、`CWR`、`CWCR`、`Recovery`、`Overblock` 等关键指标，Proposal 已明确定义，但你上传的实验报告并未提供结构化原始统计表，也未提供严格的写安全 oracle 结果。因此，Proposal 中关于“token–utility–write-safety Pareto frontier”的主张，目前最多只能说**概念上已对齐、工程上开始实现、定量上尚未闭合**。fileciteturn0file1 fileciteturn0file0

**对论文叙事最有价值的发现**有两个。其一，`ConflictingView` 在 airline 上并未一律伤害性能，反而可能通过“打断无限重查、迫使快速提交”改善部分任务的完成情况；这意味着原 Proposal 里“信息越全越好”的对照叙事必须改写成“visibility policy 会改变 trajectory，且不同 regime 可能通过不同机制改善或恶化任务”。其二，telecom 域目前基本被 `max_steps=25` 和 timeout 机制主导，因此尚不能用于判断 visibility 或 RAVEL 的真实效果。fileciteturn0file0 fileciteturn0file1

**因此，当前最合理的定位**不是“写最终论文结果”，而是先完成一版**审计型中期报告**：把已证实、被削弱、尚未检验的 Proposal 主张逐项标出来；把基础设施 bug、运行环境不公平、GT 提示不一致、模型 checkpoint 与 Proposal 偏离这些偏差源写清楚；然后基于最小补充文件集，尽快把这份草稿升级为可投稿级分析报告。NeurIPS 的 checklist 明确要求主实验应给出可复现路径、准确环境与命令、训练/评估细节与误差条；ACM 的 artifact 指南则强调 documented、consistent、complete、exercisable 是可审计实验的基本标准。citeturn2search0turn2search2turn1search2turn1search3

## Next Actions

- 先补交 **原始 per-trial 结果文件**，至少要有每个 `task_id × model × regime × repeat` 的 reward、termination、duration、messages、token、seed、error。  
- 立刻补交 **git 提交与 patch 证据**，包括 benchmark repo、实验 repo、未提交改动、实际运行命令。  
- 单独导出 **write/gate/ledger 事件日志**；没有这些日志，就无法对 Proposal 的写安全假设作结论。  
- 把当前报告里的“汇总结论”下沉为 **机器可读表格**，否则 paired bootstrap 和 mixed-effects 只能停留在计划层。  
- 先做一次 **结果完整性审计**，再做统计检验；否则会把 infrastructure bias 错当成 visibility effect。 citeturn2search0turn1search2

## 输入清单与当前可验证范围

### 已提供且当前可直接作为证据的文件

| 类别 | 文件 | 当前用途 | 当前状态 |
|---|---|---|---|
| 实验总结 | `EXPERIMENT_REPORT_20260615.md` | 当前唯一可直接支撑实验现状、故障时间线、部分汇总结果、部分逐任务明细的主证据 | **已提供** fileciteturn0file0 |
| 原 Proposal | `MultiAiAgentProposal.pdf` | 当前用于抽取研究问题、可证伪假设、方法模块、visibility regimes、指标与统计要求 | **已提供** fileciteturn0file1 |
| Proposal 重复副本 | `ravel_proposal_cn.pdf` | 与上面内容基本重复，可作为交叉核对 | **已存在本地，但非新增证据** fileciteturn0file2 |
| 辅助旧稿 | `Pasted text.txt` | 可能是更早期算法报告，必要时可用于追踪术语演化，但不宜替代 Proposal 本身 | **可选** fileciteturn0file3 |

### 当前从实验报告中能确认的事实

目前能够从实验报告中较可靠抽取的配置包括：主实验路径位于 `/home/xqin5/multiaiagent/`；至少一个 benchmark worktree 为 `tau2-clean`，commit 为 `ddc66a7`；主模型之一为本地 vLLM 提供的 `Qwen3.6-27B`，端口 `8190`；硬件包括 `4× A100 80GB`；Qwen3 阶段的 airline/retail/telecom、以及后续 Gemma4-31B 与 gpt-oss-120b 的 airline/retail 实验，已经在报告中留下部分汇总结果。fileciteturn0file0

同时也能确认，当前实验链条中存在三类会直接伤害内部效度的重大问题：`CommitGate` 初始空 schema bug、`run_ravel_exp.py` 的 `f-string ValueError` 导致续跑中断、以及 tau2 的 cooperative timeout 使阻塞式 LLM 调用无法被抢占取消。报告还明确记录了 GPU 竞争、Qwen3 CoT 泄漏、GT 提示不一致、FieldMask 中的 OOM、telecom 的 `max_steps=25` 硬瓶颈等问题。fileciteturn0file0

### 当前仍然是 UNKNOWN 或 NOT PROVIDED 的键信息

下列信息对 Proposal 终版评估是**必需**的，但当前未提供或仅在 Markdown 中被口头描述，尚不足以作为可审计证据：

| 项目 | 当前状态 |
|---|---|
| 原始 per-trial JSONL / CSV / Parquet | **NOT PROVIDED** |
| benchmark 任务清单与 split manifest | **NOT PROVIDED** |
| τ-bench / τ²-bench 的准确 repo+commit+patch | **PARTIAL / UNKNOWN** |
| 所有模型 endpoint 快照、served model name、quantization、context length、parser | **PARTIAL / UNKNOWN** |
| `TokensUncached`、`TokensTotal`、`TokensWriteWindow` 原始记录 | **NOT PROVIDED** |
| `EvidenceValidRate` / `SAR` / `CWR` / `UAR` / `CWCR` / `Recovery` / `Overblock` 机器可读结果 | **NOT PROVIDED** |
| trajectory 级事件日志 | **NOT PROVIDED** |
| gate / ledger / candidate write 级日志 | **NOT PROVIDED** |
| 基线与 RAVEL 的 exact prompts / config hashes | **NOT PROVIDED** |
| repo 未提交修改、patch diff、运行时环境锁定 | **NOT PROVIDED** |

这意味着：**你现在已经有“实验故事”，但还没有“可投稿级证据链”**。按照 NeurIPS checklist 和 ACM artifact 指南，这些缺口会直接影响可复现性与结果验证。citeturn2search0turn2search2turn1search2turn1search3

## 评估方法与复现检查草稿

### 数据完整性验证流程

针对当前材料，建议把“验证”分成三层。第一层是**文件层审计**：确认所有结果文件可枚举、无空文件、无重复 trial ID、无 partial overwrite、无同名不同义结果。第二层是**实验层审计**：校验每个 `task_id × model × regime × repeat` 是否唯一、是否都有 reward / termination / duration / seeds / config hash；并检查是否存在“同一 regime 使用不同 timeout 或不同 benchmark patch”的情况。第三层是**语义层审计**：对写安全相关指标，验证 `candidate write → gate decision → final commit / block / reconcile` 的事件链是否可重放；对 final-state 结果，核对 evaluator 输出与最终数据库状态是否一致。这个分层方案与 Proposal 的指标定义和 NeurIPS/ACM 对可复现主实验的要求是对齐的。fileciteturn0file1 citeturn2search0turn1search2

如果你暂时还没有整理这些文件，建议先用下面这组 shell 命令自动扫描环境与结果资产。它们本身不产生论文结论，但能迅速把“当前到底有什么”固化成 manifest。

```bash
pwd
find . -maxdepth 4 -type f \( -name "*.jsonl" -o -name "*.csv" -o -name "*.parquet" -o -name "*.log" -o -name "*.yaml" -o -name "*.yml" -o -name "*.json" \) | sort > file_manifest.txt

git rev-parse HEAD
git status --short
git diff --stat
git submodule status

find results -type f | sort
find logs -type f | sort

python - <<'PY'
import os, json, hashlib, pathlib
for p in pathlib.Path(".").rglob("*"):
    if p.is_file() and p.suffix in {".jsonl",".csv",".parquet",".log",".yaml",".yml",".json"}:
        try:
            h = hashlib.sha256(p.read_bytes()).hexdigest()[:16]
            print(f"{p}\t{p.stat().st_size}\t{h}")
        except Exception as e:
            print(f"{p}\tERROR\t{e}")
PY
```

### 复现性检查步骤

Proposal 已明确要求 benchmark 版本冻结、task split 冻结、paired design、重复运行和非劣效检验；τ-bench 与 τ²-bench 本身也都强调任务状态和环境交互的可验证性，而不是单看文本答案。正式报告里，应把复现性检查步骤写成固定顺序：**环境快照 → benchmark/version 快照 → task split 快照 → model endpoint 快照 → smoke test → pilot → validated manifest → 主分析**。fileciteturn0file1 citeturn0academia47turn0academia46turn2search0

当前这一步最需要核对的是：基线与 RAVEL 是否真的在相同 timeout、相同 GPU 负载、相同 tool parser、相同 GT 提示条件下比较。你上传的实验报告已经表明这些条件并不完全一致，尤其是 GPU 竞争、GT 提示缺失、Qwen3 thinking 泄漏、telecom 的 `max_steps` 限制，会直接污染内部效度。fileciteturn0file0

### 统计检验方法草稿

Proposal 里已经预注册了 paired bootstrap、mixed-effects model、Holm 校正、FSS 非劣效边界等分析策略，因此这份草稿建议完全沿用该框架。具体来说：

- **主分析**：同一 `task seed` 下的 regime / method 差异，用 task-clustered paired bootstrap 给出差值与 95% CI。  
- **二元结局**：`FSS`、`EvidenceValid`、`UAR` 采用 mixed-effects logistic regression。  
- **计数/连续结局**：`TokensUncached`、tool calls、reconciliation count、latency 用 Gamma / log-normal / negative binomial mixed model，视分布而定。  
- **多重比较**：主假设用 Holm，探索性分析用 FDR。  
- **非劣效检验**：对 Proposal 的 `FSS` 非劣效边界 `ε = 2pp` 做单侧检验。 fileciteturn0file1

在目前可用材料下，只有 Qwen3 airline 域的逐任务表足以做一个**临时** paired bootstrap 复算。按报告中的逐任务明细粗算，`FullSync - Baseline` 的 FSS 差值为 `0 pp`，95% bootstrap CI 约为 `[-30, +30] pp`；`Delayed - Baseline` 为 `-20 pp`，CI 约 `[-50, 0] pp`；`ConflictingView - Baseline` 为 `+10 pp`，CI 约 `[-20, +40] pp`。这组结果的价值在于说明“方向性已经出现”，但样本只有 10 个任务，而且未接入原始日志和完整配对表，因此**不能替代终版统计结果**。fileciteturn0file0

## Proposal 对照矩阵

### 研究问题与可证伪假设的当前状态

下表按 Proposal 本身的 RQ/H 假设来对照，而**不是**按实验报告里更早期的 H1/H2/H3 口径来对照。两者并不完全等价，这一点应在终版报告中明确声明。fileciteturn0file1 fileciteturn0file0

| Proposal 项 | Proposal 要求 | 当前证据结论 | 证据强度 | 当前可给出的依据 | 当前不确定性来源 |
|---|---|---|---|---|---|
| RQ1 可见性因果效应 | 固定任务/工具/模型/拓扑，只改 visibility regime，看轨迹、终态、写安全是否系统变化 | **部分证实** | **中** | Qwen3 airline 四 regime 出现明显分化；Gemma4/gpt-oss 在 airline/retail 也出现 regime 差异，且 ConflictingView 有反直觉提升。fileciteturn0file0 | 未提供标准化 trajectory divergence、写安全 oracle、统一 runtime 条件 |
| RQ2 效率–效用权衡 | 相对 full-sync / scratchpad，MSE 能显著降 `TokensUncached` 且 FSS 非劣 | **未检验** | **弱** | Proposal 已定义指标与非劣效边界。fileciteturn0file1 | 当前无 `TokensUncached` 原始表，也没有 MAS-FullSync / Shared Scratchpad / RAVEL-MSE 完整对照 |
| RQ3 写安全 | ledger + commit gate 能降 stale/conflicting/unsupported writes，且不是靠过度阻断 | **未检验** | **弱** | 报告记录了 CommitGate bug 与修复、个别成功写入案例。fileciteturn0file0 | 缺 `EvidenceValidRate/UAR/CWR/CWCR/Overblock/Recovery` 机器可读数据 |
| RQ4 风险自适应预算 | 高风险时再加预算，优于所有回合都高预算或都低预算 | **未检验** | **弱** | Proposal 对 ARB 模块有清晰定义。fileciteturn0file1 | 当前无 low/normal/high reasoning budget 对照 |
| RQ5 跨模型/跨域稳健性 | 结果应跨模型、领域、扰动强度与次级架构复现 | **部分证实** | **中-弱** | 现已有 Qwen3、Gemma4、gpt-oss；域上有 airline/retail/telecom。fileciteturn0file0 | Proposal 预设的 GLM-4.5-Air、Llama-3.3-70B-Instruct 未完成；telecom 被 `max_steps` 主导 |

| Proposal 假设 | 目标 | 当前结论 | 证据强度 | 备注 |
|---|---|---|---|---|
| H1 轨迹敏感性 | Delayed / FieldMask / ConflictingView 相对 FullSync 增加轨迹分叉、降低高风险写证据有效性 | **部分证实** | **中** | regime 明显改变结果与 failure mode；但“证据有效性下降”未被直接量化，且 ConflictingView 并不总是更差。fileciteturn0file0turn0file1 |
| H2 token 非劣效 | RAVEL 比 full-sync 至少降 20% `TokensUncached`，FSS 下降不超过 2pp | **未检验** | **弱** | 现在没有 token 表；且方法矩阵不完整。fileciteturn0file1 |
| H3 安全优越性 | 在 delayed/conflicting 下，RAVEL 比 full-sync、ledger-only、commit-gate-only 降 UAR/CWR | **未检验** | **弱** | 缺必要 baseline 与写安全日志。fileciteturn0file1 |
| H4 非过度阻断 | Overblock ≤ 12%，Recovery ≥ 50% | **未检验** | **弱** | 当前没有 overblock / recovery oracle。fileciteturn0file1 |
| H5 组件必要性 | 去掉任一核心组件会损害 token/safety/recovery | **未检验** | **弱** | 目前有“实现 bug 造成灾难性失败”的证据，但这不是合格的消融。fileciteturn0file0turn0file1 |

### 关键模块、regime 与指标的实现状态

| Proposal 模块 | Proposal 定义 | 当前实现状态 | 当前审计结论 |
|---|---|---|---|
| VDL 版本化证据账本 | 外置 raw，前台只给 header/delta/pointer | **部分实现** | 报告表明 ledger/gate 已在系统中占据中心位置，但缺少机器可读 ledger 事件导出，无法审计版本/冲突/依赖是否真的完整。fileciteturn0file0turn0file1 |
| MSE-Router | 最小充分证据路由 | **部分实现或未充分证实** | 当前看到的是 regime 级 visibility 干预，不足以证明 rule-based MSE 已按 action schema 稳定工作。fileciteturn0file1turn0file0 |
| Commit Gate | propose–validate–commit 两阶段写 | **已实现但曾有严重 bug** | 空 schema bug 已修；个别任务已验证写入执行成功，但仍缺“严格 schema”实证。fileciteturn0file0 |
| ARB 风险自适应预算 | 风险高时再加 evidence/reasoning budget | **未证实** | 当前没有统一预算实验。fileciteturn0file1 |
| FullSync / Delayed / FieldMask / ConflictingView | 四类 observation regimes | **已部分到充分测试** | Qwen3 airline 四者已全；telecom 四者已全但不具诊断性；retail 不完整。fileciteturn0file0 |
| 指标集 | FSS、TokensUncached、EvidenceValidRate、UAR、CWR、CWCR、Recovery、Overblock | **多数未落表** | FSS 有，token/写安全核心指标基本未落成结构化结果。fileciteturn0file1turn0file0 |

## 指标表与可视化脚手架

### 当前可落表的指标摘要

下面这张表只汇总**当前上传材料中可直接确认**的核心结果。由于 retail/telecom 的原始 per-task 表和 token 表未提供完整版本，很多单元只能标 `UNKNOWN` 或“不可比”。

| 模型 | 领域 | 方法/Regime | FSS | n | 与该模型基线的粗差值 | 统计状态 | 数据来源 |
|---|---|---|---:|---:|---:|---|---|
| Qwen3.6-27B | airline | Baseline | 3/10 = 30.0% | 10 | 参考 | — | `EXPERIMENT_REPORT_20260615.md` fileciteturn0file0 |
| Qwen3.6-27B | airline | FullSync | 3/10 = 30.0% | 10 | `0 pp` | 临时 bootstrap CI `[-30,+30] pp` | 同上 fileciteturn0file0 |
| Qwen3.6-27B | airline | Delayed | 1/10 = 10.0% | 10 | `-20 pp` | 临时 bootstrap CI `[-50,0] pp` | 同上 fileciteturn0file0 |
| Qwen3.6-27B | airline | FieldMask | 0/10 = 0.0% | 10 | `-30 pp` | **不可稳健解释**，含 2 个 infra_error | 同上 fileciteturn0file0 |
| Qwen3.6-27B | airline | ConflictingView | 4/10 = 40.0% | 10 | `+10 pp` | 临时 bootstrap CI `[-20,+40] pp` | 同上 fileciteturn0file0 |
| Qwen3.6-27B | telecom | Baseline | 2/14 = 14.3% | 14 | 参考 | — | 同上 fileciteturn0file0 |
| Qwen3.6-27B | telecom | 四个 regime | 0/14 = 0.0% | 14 | `-14.3 pp` | 当前**不可归因**，被 `max_steps=25` 和 timeout 主导 | 同上 fileciteturn0file0 |
| Gemma4-31B | airline | Baseline / FullSync / CV | 4/10, 3/10, 3/10 | 10 | `-10 pp`, `-10 pp` | 仅汇总值，待原始表 | 同上 fileciteturn0file0 |
| Gemma4-31B | retail | Baseline / FullSync / CV | 2/14, 3/14, 4/14 | 11 有效 | `+7.1 pp`, `+14.3 pp` | 含 3 个永久 IE，需谨慎 | 同上 fileciteturn0file0 |
| gpt-oss-120b | airline | Baseline / FullSync / CV | 1/10, 1/10, 2/10 | 10 | `0 pp`, `+10 pp` | 仅汇总值，待原始表 | 同上 fileciteturn0file0 |
| gpt-oss-120b | retail | Baseline / FullSync / CV | 5/14, 1/14, 3/14 | 14 | `-28.6 pp`, `-14.3 pp` | 仅汇总值，待原始表 | 同上 fileciteturn0file0 |

这张表已经足以支持一条重要中间结论：**Proposal 的“visibility policy 是一等变量”得到了中等强度支持，但 Proposal 的“token–write-safety 优化”暂时还没有同等级证据。**fileciteturn0file1turn0file0

### 建议写入终版报告的三张图

Proposal 明确希望出现 Token–Safety Pareto、Trajectory Divergence Timeline 与 Reconciliation Waterfall；这三类图也与 trajectory-aware benchmark 的评估思路一致。下面给出**可执行代码脚手架**。你只需要把文件路径替换成实际导出的 Parquet/CSV 即可。fileciteturn0file1 citeturn0academia45

#### Token–Safety Pareto

```python
import pandas as pd
import matplotlib.pyplot as plt

# 期望列：
# model, domain, method, regime, task_id, repeat_id,
# tokens_uncached, unsafe_action_rate, final_state_success
df = pd.read_parquet("results/validated/main_trials.parquet")

agg = (
    df.groupby(["model", "domain", "method", "regime"], dropna=False)
      .agg(tokens_uncached_mean=("tokens_uncached", "mean"),
           unsafe_action_rate_mean=("unsafe_action_rate", "mean"),
           fss_mean=("final_state_success", "mean"),
           n=("task_id", "nunique"))
      .reset_index()
)

fig, ax = plt.subplots(figsize=(8, 6))
for _, row in agg.iterrows():
    ax.scatter(row["tokens_uncached_mean"], row["unsafe_action_rate_mean"], s=60)
    ax.text(row["tokens_uncached_mean"], row["unsafe_action_rate_mean"],
            f'{row["model"]}\n{row["domain"]}\n{row["method"]}/{row["regime"]}',
            fontsize=8)

ax.set_xlabel("Mean TokensUncached")
ax.set_ylabel("Mean UnsafeActionRate")
ax.set_title("Token–Safety Pareto")
plt.tight_layout()
plt.show()
```

#### Trajectory Divergence Timeline

```python
import pandas as pd
import matplotlib.pyplot as plt

# 期望列：
# model, domain, task_id, regime, step_idx, diverged_from_fullsync (0/1)
events = pd.read_parquet("results/validated/trajectory_events.parquet")

first_div = (
    events[events["diverged_from_fullsync"] == 1]
    .groupby(["model", "domain", "task_id", "regime"])["step_idx"]
    .min()
    .reset_index(name="first_divergence_step")
)

fig, ax = plt.subplots(figsize=(9, 6))
for regime, sub in first_div.groupby("regime"):
    ax.hist(sub["first_divergence_step"], bins=20, alpha=0.6, label=regime)

ax.set_xlabel("First Divergence Step")
ax.set_ylabel("Count")
ax.set_title("Trajectory Divergence Timeline")
ax.legend()
plt.tight_layout()
plt.show()
```

#### Reconciliation Waterfall

```python
import pandas as pd
import matplotlib.pyplot as plt

# 期望列：
# stage in {
#   "candidate_write", "missing_field_fetch", "delta_fetch",
#   "raw_fetch", "selective_requery", "verifier_escalation",
#   "commit", "block", "recover"
# }
rec = pd.read_parquet("results/validated/reconciliation_events.parquet")

order = [
    "candidate_write", "missing_field_fetch", "delta_fetch",
    "raw_fetch", "selective_requery", "verifier_escalation",
    "commit", "block", "recover"
]

counts = rec["stage"].value_counts().reindex(order, fill_value=0)

fig, ax = plt.subplots(figsize=(9, 5))
counts.plot(kind="bar", ax=ax)
ax.set_xlabel("Reconciliation Stage")
ax.set_ylabel("Count")
ax.set_title("Reconciliation Waterfall")
plt.tight_layout()
plt.show()
```

### 指标表的标准导出格式

为了让这三张图和指标总表真正可复现，最终你至少需要导出四张机器可读表：

- `main_trials.parquet`：trial 级主表  
- `trajectory_events.parquet`：逐步轨迹事件表  
- `write_events.parquet`：candidate/gate/commit 表  
- `config_manifest.json`：模型、benchmark、parser、git、seed、命令、环境快照  

没有这四类表，就很难满足 Proposal 和 NeurIPS/ACM 对主实验复现的要求。fileciteturn0file1 citeturn2search0turn1search2

## 失败、偏差与结论

### 代表性失败与偏差审计结论

目前这份草稿最应强调的不是“RAVEL 好不好”，而是“**哪些结果是可信的，哪些结果被基础设施偏差污染了**”。从你上传的实验报告看，至少存在以下五类高风险偏差：

- **实现 bug**：CommitGate 空 schema bug 直接使第一轮结果全部失效。  
- **实验调度偏差**：GPU 并发竞争显著改变 wall-clock、超时与完成率。  
- **benchmark / runner 机制偏差**：tau2 cooperative timeout 不能打断长调用，导致超时含义失真。  
- **模型行为偏差**：Qwen3 的 CoT 泄漏污染了 user simulator 语义。  
- **比较口径偏差**：retail 中基线使用 `llm_agent_gt`，RAVEL 使用无 GT 提示 agent，造成 baseline 与方法不等价。 fileciteturn0file0

这些偏差意味着：当前最可靠的结论，不是“RAVEL 在某域显著更好/更差”，而是下面三条。

第一，**visibility regime 的改变会真实地改变结果与 failure path**。这一点是强于“偶然现象”的，因为它在 Qwen3、Gemma4、gpt-oss 以及 airline/retail 两域中都出现了方向性信号，只是强弱与方向并不一致。fileciteturn0file0

第二，**Proposal 中最关键的安全主张尚未被验证**。正式的写安全分析应当围绕 `EvidenceValidRate`、`UAR`、`CWR`、`CWCR`、`Recovery`、`Overblock` 展开，而现有上传材料主要还是 FSS、duration、termination、部分任务剖析。这更像“方法工程阶段的实验日志”，还不是“安全主张已经闭环”的论文证据。fileciteturn0file1turn0file0

第三，**当前最有潜力的论文贡献点已经出现**：不是“RAVEL 总是优于 FullSync”，而是“visibility policy 会通过不同机制改写轨迹，有时减少 token、有时打断无限优化、有时因冲突视图反而促成快速提交”。这更接近一个真正新颖、也更能经受 reviewer 追问的结论边界。fileciteturn0file0turn0file1

### 建议写入附录的实验时间线

下面这段 Mermaid 可以直接进入附录，作为“实验进度与里程碑”草稿。内容来自你上传的实验报告时间线。fileciteturn0file0

```mermaid
timeline
    title RAVEL 实验进度与关键里程碑
    2026-06-15 17:00 : 基线冒烟测试三域通过
    2026-06-15 18:30 : 启动 12 个 RAVEL 条件的首轮实验
    2026-06-15 19:45 : 定位 CommitGate 空 schema 全阻断 bug
    2026-06-15 19:50 : 修复 CommitGate 并补充测试
    2026-06-15 20:00 : 启动修复版顺序实验
    2026-06-15 21:19 : Airline FullSync 完成，但 f-string bug 触发脚本崩溃
    2026-06-15 21:29 : 修复 run_ravel_exp.py 的 f-string bug
    2026-06-15 21:51 : Retail task 31 暴露 tau2 cooperative timeout 问题
    2026-06-15 21:56 : SIGTERM 终止卡死进程，Telecom 开始
    2026-06-16 00:10 : Telecom Delayed 完成
    2026-06-16 00:55 : Telecom FieldMask 完成
    2026-06-16 01:35 : Telecom ConflictingView 完成
    2026-06-16 06:33 : Airline Delayed 完成
    2026-06-16 13:23 : Airline FieldMask 完成
    2026-06-16 14:16 : Airline ConflictingView 完成
    2026-06-17        : Gemma4 / gpt-oss 多模型实验完成
```

## 立即需要补充的最小文件集合

### 最小集合

如果你的目标是让我把这份草稿升级为**正式分析报告**，而不是停留在结构化草稿，那么请优先补齐下面这组最小集合。它已经按“缺了就无法做 Proposal 对照”的逻辑排序。

- **主结果表**：`main_trials.csv` 或 `main_trials.parquet`  
  必须含 `task_id, domain, model, regime, method, repeat_id, reward/fss, termination, duration_sec, num_messages, seed, timeout, max_steps, benchmark_commit, config_hash`。  

- **token 表**：至少含 `tokens_input, tokens_output, tokens_uncached, tokens_write_window`。没有它，就无法检验 Proposal 的 H2。  

- **write/gate/ledger 事件表**：至少含 `candidate_write_id, action_name, evidence_ids, gate_verdict, stale_flag, conflict_flag, policy_flag, committed, recovered`。没有它，就无法检验 H3/H4。  

- **轨迹事件表**：至少含 `step_idx, tool_name, normalized_args, regime_visible_evidence_ids`。没有它，就无法做 trajectory divergence。  

- **配置与环境 manifest**：包括 git 提交、未提交 diff、benchmark 版本、served model name、parser、quantization、context length、启动命令、端口、GPU。  

- **任务清单与 split**：开发集 / 测试集 / held-out 的 task IDs 和生成规则。没有它，就无法做泄漏与复现审计。  

### 如果你暂时没有整理好这些文件

如果你目前只有 repo 和结果目录，也可以先给我下面这些自动导出命令的输出。它们是最小、最快的替代方案，而且与 NeurIPS/ACM 的可复现要求一致。citeturn2search0turn2search2turn1search2

```bash
# 结果清单
find results -type f | sort

# 关键日志
find logs -type f \( -name "*.log" -o -name "*.jsonl" \) | sort

# benchmark / repo 状态
git rev-parse HEAD
git status --short
git diff --stat
git submodule status

# 模型服务快照
curl http://localhost:8190/v1/models
ss -ltnp | grep -E '8190|8191|8000|vllm'
nvidia-smi

# 若有 parquet/csv，先给列名
python - <<'PY'
import pandas as pd, pathlib
for p in pathlib.Path("results").rglob("*"):
    if p.suffix == ".csv":
        try:
            df = pd.read_csv(p, nrows=3)
            print("\nCSV:", p)
            print(df.columns.tolist())
        except Exception as e:
            print("ERR", p, e)
    if p.suffix == ".parquet":
        try:
            df = pd.read_parquet(p)
            print("\nPARQUET:", p)
            print(df.columns.tolist())
        except Exception as e:
            print("ERR", p, e)
PY
```

### 当前最小结论边界

在你补齐最小文件集合之前，这份草稿建议把最终结论压在以下边界内：

- **可以说**：visibility regime 已被中等强度证据支持为影响 trajectory / outcome 的关键变量。fileciteturn0file0turn0file1  
- **可以说**：当前实验暴露了若干比方法本身更强的偏差源，正式结论必须建立在结果完整性审计之后。fileciteturn0file0  
- **不能说**：RAVEL 已经证实实现了 Proposal 承诺的 token–utility–write-safety Pareto 改善。因为最核心的 token 与写安全量化环节还没有闭环。fileciteturn0file1turn0file0  
- **不能说**：某个模型或某个 regime 已经在跨域、跨架构上稳健胜出。现有证据太受 runtime、提示口径与基础设施制约。fileciteturn0file0

**建议你立即提供的最小信息清单**就是上一节的六项；只要你把这批文件给到，我就可以在这份草稿基础上继续往下落成你要求的完整正式报告，包括：Proposal 全量对照矩阵、真正的 paired bootstrap / mixed-effects 结果、三张正式图表、10–20 个失败轨迹解析、偏差审计附录、复现步骤和 BibTeX 建议。