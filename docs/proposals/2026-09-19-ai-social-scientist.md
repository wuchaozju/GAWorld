# AI Social Scientist：把研究工作台接成一个有闸门的研究闭环

日期：2026-09-19
状态：阶段一实现中
范围：新增 `gaworld/research/{measures,protocol,backends,evaluate,interpret,report,study}.py`；扩展 `gaworld/apps/research_api.py` 与 `site/dashboard/research.*`。
**不改任何执行引擎**：平行世界、群体采访、提示词实验网格照旧，只被调用。

---

## 一、动机：链条断在哪里

研究工作台已经能把一个想法或一篇论文变成结构化方案（问题、假设、功能映射、条件、事件、指标、步骤）。
但方案是文档，不是规格：步骤里的命令是字符串，没有任何东西去执行它，跑完也没有任何东西把结果对回 H1、H2。

仓库里以前的九个实验（`docs/proposals/EXP-*.md`、`docs/proposals/experiments/`）是靠手写 harness 加人工写论文完成的，
复盘报告 `docs/EXPERIMENTS_REPORT.md` 记下的失败模式全是**静默的**：

| 失败模式 | 出处 |
|---|---|
| 指标恒为 0 仍写进结论 | EXP-INFO-001，`misinformation_risk` 全程 0.0 |
| 计划 14 天、实际 1–2 天，仍照写 | EXP-INFO-001 / EXP-POL-001 |
| n=5、单种子、无安慰剂，报「恢复了约 84%」 | `paper_misinfo_spread_academic_v3.md` |

自动化研究如果只是把这套流程交给模型跑，只会更快地产出同样的东西。所以本提案的核心不是「让模型多做几步」，而是：

1. 方案与执行之间加一份**机器可读的预注册协议**；
2. 统计判定在代码里、解释在模型里，两者分开；
3. 跑前、跑后各一道**硬闸门**，不过就不写报告。

## 二、闭环

```
材料 → Plan（已有）→ Protocol（预注册）→[审批]→ Run（映射到已有引擎）
     → Evaluate（代码算统计、判假设）→ Interpret（模型只解释给定数字）
     → Report → Next（后续研究提案，回到 Protocol）
```

### 2.1 Protocol：预注册文档，也是可执行规格

| 字段 | 内容 | 落到哪 |
|---|---|---|
| kind | `parallel_worlds`（阶段一唯一支持）；`survey` / `grid` / `composite` 预留 | 见 §2.3 |
| sample | agent_ids、城市备注 | ExperimentSpec.agent_ids |
| sim_days / fast | 时长与快速模式 | ExperimentSpec |
| conditions | 每个条件 = 角色（baseline / treatment / placebo）+ 事件表 + config 补丁 | 逐一就是 WorldSpec |
| measures | 只能从**可测量目录**里选 | `evaluate` 读的列 |
| hypotheses | `{measure, treatment, control, direction, min_effect, aggregation}` | 自动打分的形态 |
| validity | seeds 列表、是否加安慰剂世界 | 每个种子跑一次实验；安慰剂世界自动补 |
| budget | 估算调用量与上限 | 超限不允许进入 running |

**可测量目录** `measures.py` 与 `docs/FEATURES.md` 同等地位：它是编译提示词里唯一可引用的指标清单，
阶段一只登记 `state/agent_state_history.csv` 里的状态指标（即平行世界报告已经能比较的那些）。
模型给出目录外的指标时，那条假设会被丢弃并写进 `dropped`，而不是被默默保留成一条永远测不到的假设。

### 2.2 两道闸门

**跑前（preflight）**：至少一条可评估的假设；每条假设的两个条件都存在；仿真天数不小于最晚事件日；
估算调用量不超过上限。错误阻断审批；「只有一个种子」「没有安慰剂」是警告。

**跑后（evaluate 的 quality）**：每个种子、每个世界都要有状态数据；每个指标在所有世界里要有方差。
质量问题写进评估结果和报告，模型解读时也看得见。

### 2.3 假设判定（确定性）

对每条假设、每个种子：`effect = value(treatment) − value(control)`，value 取 `final` 或 `mean`（协议里指定）。

- **噪声底线**：安慰剂世界相对基准的偏差，取各种子的最大值。
- **supported**：所有种子的效应方向都与预测一致，均值绝对值 ≥ `min_effect`，且高于噪声底线。
- **contradicted**：所有种子的效应方向都与预测相反，且高于噪声底线。
- **inconclusive**：其余情况。只有一个种子又没有安慰剂时，最高只能到这一档。
- **unmeasured**：没有任何种子拿到两个条件的值。

判定附带 `reasons`，报告里逐条列出为什么是这个结论。

### 2.4 解释与报告

`interpret.py` 把评估结果（数字表、判定、质量问题）交给模型，要求 JSON：findings（每条挂一个假设 id）、limitations、next_studies。
`check_claims` 把挂不上假设 id 的 finding 标为 `grounded=false`。模型调用失败不阻断：报告照样渲染，解读一节留空并注明。

报告 `report.py` 的顺序是：预注册 → 执行记录 → 逐假设结果表 → 数据质量 → 解读 → 后续研究。预注册在前，是为了让读者先看到预测再看结果。

### 2.5 Copilot 优先

`study.py` 是状态机：`protocol → approved → running → evaluated → reported`，任一步可进 `error`。
默认在 `protocol` 停下等人点「批准」；`autopilot=true` 只是「preflight 无错误即自动批准并开跑」。

## 三、落点与复用

| 新文件 | 复用 |
|---|---|
| `research/measures.py` | `parallel.analysis.METRIC_LABELS` |
| `research/protocol.py` | `parallel.spec.normalize_event / sanitize_world_config`，`city.knowledge._parse_json_object` |
| `research/backends.py` | `parallel.spec.normalize_experiment`，`parallel.runner.prepare_experiment / ExperimentRunner` |
| `research/evaluate.py` | 平行世界 `report.json` 的 `worlds` 与 `deltas` |
| `research/study.py` | 与 `workbench` 同一个 `output/research/` 根，研究放在 `studies/<id>/` |
| `apps/research_api.py` | 已有的 job 管道；一次只跑一项研究，同 `parallel_worlds_api` |

跑出来的每个种子就是一次普通的平行世界实验，落在 `output/parallel_worlds/study_<id>_s<seed>/`，
在「平行世界」页签里能照常打开看分叉图和逐帧回放。

## 四、阶段

| 阶段 | 内容 |
|---|---|
| 一（本次） | parallel_worlds 一种 kind，方案 → 协议 → 审批 → 多种子运行 → 判定 → 解读 → 报告；面板可审批、运行、看结果 |
| 二 | survey 与 composite（先跑世界，再采访各世界居民，需要采访能指向某个世界的记忆目录）；经济与网络指标进目录 |
| 三 | 泛化 `gaworld.experiments` 为通用「刺激 × 被试 × 问题」网格，支持情境实验 |
| 四 | autopilot 下的后续研究循环；文献检索；论文草稿 |

## 五、明确不做的

- 不做工具调用型 agent 循环：现有 `call_llm` 只有文本进出、后端混杂，仓库里「模型出 JSON、代码校验」的范式可测、可 stub。
- 不让模型算统计：它拿到的是算好的数字，每条 claim 要能对回一条数字。
- 不在报告里出现目录外的指标：编译时就挡掉。
