# AI Social Scientist：把研究工作台接成一个有闸门的研究闭环

日期：2026-09-19
状态：阶段一已实现；阶段二的 composite（先跑世界，再采访居民）已实现（2026-10-03，见 §2.6），独立问卷与经济 / 网络指标未做
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
| kind | `parallel_worlds`；`composite`（阶段二：平行世界 + 跑后问卷，见 §2.6）；`survey` / `grid` 未做 | 见 §2.3 |
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

### 2.6 阶段二：composite —— 先跑世界，再采访居民（2026-10-03 实现）

状态变量回答不了「居民怎么看」：信任、满意度、支持与否只能问。composite 研究 = 平行世界 + 跑后问卷，问卷答案和状态指标一样进判定。

- **编译**：方案要测态度时，模型写 `kind: composite` 和 `survey: {context, questions[]}`。题型只有三种：`scale`（有序单选，默认五级同意度，可给 3–7 个有序选项）、`boolean`（是 / 否）、`open`（只进报告，不计分）；最多 8 题。只要有一道可计分题，协议就是 composite；一道都没有时，模型写的是 parallel_worlds 就丢掉问卷，写的是 composite 则跑前检查报错。
- **指标**：每道 scale / boolean 题成为指标 `survey.Q<n>`（0–1：量表按所选选项位置归一，第一项 0、最后一项 1；是非题是答「是」的比例），和状态指标一起进可测量目录，假设可以引用；开放题当指标用的假设在编译时丢弃。
- **跑前**：composite 至少要一道可计分题；调用量加上 `居民 × 题数 × 世界 × 种子`（每人每题一次调用）。
- **运行**：每个种子跑完全部世界后，逐世界起一个 `python -m gaworld.interview` 子进程，带上**该世界运行时的 config 覆盖**（记忆目录、向量库、目标都解析到这个世界的文件），居民的状态取**该世界最后一步**（`state/agent_state_history.csv`）。受访者 = 协议样本，或该世界状态表里出现过的居民；被升级成居民的家人（`family.members_as_agents`）没有档案，不采访。产物：`<world>/survey_spec.json`、`survey_answers.json`、`survey.json`（得分 + 逐人答案）。一个世界采访失败只记为数据质量问题，不让整项研究报错。
- **判定**：一个世界、一个种子、一道题一个分数；同一个数同时充当 `final` 与 `mean`。噪声底线、方向、最小效应规则不变。**居民配对关**也照用：同一批居民在每个世界都回答了，所以「处理世界的答案 − 对照世界的答案」逐人配对（bootstrap 区间、符号翻转 p、该种子各问卷假设间 BH），且不要求对照是基准世界。
- **质量**：某种子没有问卷结果、某世界采访失败、某题超过 20% 的回答对不上选项或是非，都写进质量问题。无法计分的回答不进得分，而不是算作 0。
- **报告**：预注册里列出问卷题目与题型；问卷得分和状态指标一起进结果数值表；另有一张「问卷作答」表（每种子、每世界、每题的计分人数与无法计分数）。

**没做的**：不跑世界的独立问卷（直接采访当前城市）；跑完之后改题重问；开放题的编码与计分；问卷中途追问。

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
| 二 | composite（先跑世界，再采访各世界居民）**已实现**，见 §2.6；独立 survey（不跑世界、直接采访）与经济 / 网络指标进目录未做 |
| 三 | 泛化 `gaworld.experiments` 为通用「刺激 × 被试 × 问题」网格，支持情境实验 |
| 四 | autopilot 下的后续研究循环；文献检索；论文草稿 |

## 五、明确不做的

- 不做工具调用型 agent 循环：现有 `call_llm` 只有文本进出、后端混杂，仓库里「模型出 JSON、代码校验」的范式可测、可 stub。
- 不让模型算统计：它拿到的是算好的数字，每条 claim 要能对回一条数字。
- 不在报告里出现目录外的指标：编译时就挡掉。
