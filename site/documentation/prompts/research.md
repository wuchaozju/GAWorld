# 研究与实验提示词

研究流程中的提示词承担不同任务：读懂材料、提出方案、编译协议、解释结果，或让居民对政策和实验题面作答。先确定当前阶段，再修改它使用的输入与模板，可以保持研究设计和结果分析的一致性。

## 研究工作台的四个阶段

```{raw} html
<ol class="prompt-flow" aria-label="研究提示词的四个阶段">
<li><strong>读材料</strong><span>从论文中提取理论、方法、变量与发现，供研究者核对。</span></li>
<li><strong>拟方案</strong><span>结合平台功能目录，将研究问题转成候选实验设计。</span></li>
<li><strong>编译协议</strong><span>确定条件、事件、指标、假设与重复种子。</span></li>
<li><strong>解释结果</strong><span>读取已经计算的估计与判定，解释发现并提出后续研究。</span></li>
</ol>
```

### 论文解读与研究方案

`workbench.py::build_digest_prompt()` 接收论文标题、正文和语言，生成论文解读任务。解读内容包括理论、方法、变量、发现、研究问题和假设，研究者可以核对后继续生成方案。

`build_prompt()` 在研究材料之外加入平台概况、功能目录与已确认的论文解读。功能目录来自 `docs/FEATURES.md`；模型根据这些内容提出方案，并按固定 JSON 结构返回研究问题、假设、功能对应关系、候选设计、操作步骤与验证方法。

**操作。** 在 [研究工作台](../research.md) 输入研究问题或论文，先检查材料解读，再选择研究设计。需要补充研究对象、时间尺度或比较条件时，先完善输入材料。要调整方案的固定要求，则定位 `workbench.py` 中的 `_PROMPT` 与 `build_prompt()`。

### 预注册协议

`protocol.py::build_compile_prompt()` 将研究方案与可测指标目录组合起来，要求模型生成结构化协议。后续代码整理条件、假设、问卷、种子和预算，并进行执行前检查。

| 协议部分 | 提示词要求表达的内容 | 执行时的用途 |
| --- | --- | --- |
| `conditions` | 基准、处理条件与事件表 | 定义各世界接收的干预 |
| `hypotheses` | 指标、比较对象、方向与阈值 | 指定如何判定研究假设 |
| `measures` | 可测量指标 ID | 连接实际数据与估计程序 |
| `validity` | 重复种子与安慰剂设置 | 组织稳健性检查 |
| `survey` | 复合研究的题目与背景 | 在各世界运行后收集居民回答 |

事件的 `description` 是居民会看到的具体描述。编辑事件时写清楚发生了什么、谁受到影响、何时发生。协议中的研究假设则交代你预期比较出什么变化。

**操作。** 选择方案后检查协议的条件表、事件日期、指标和方向，再运行。要新增可测指标，先在指标注册与计算代码中实现，再让协议引用该 ID。详细流程见 [平行世界](../parallel-worlds.md)。

### 结果解释

研究结果先由 `research/evaluate.py` 计算和判定。`research/interpret.py::build_interpret_prompt()` 读取协议、逐假设结果与数据质量信息，要求模型返回：

```json
{
  "findings": [
    {"hypothesis": "H1", "claim": "结论", "evidence": "结果表中的依据"}
  ],
  "limitations": ["影响结论的具体因素"],
  "next_studies": [
    {"title": "后续研究", "rationale": "研究理由", "change": "相对本次研究的修改"}
  ]
}
```

上面展示字段结构，内容为说明性占位。每条发现通过假设 ID 对应到结果表。`check_claims()` 检查结论与已给出的判定是否相符；修改解释语气时，保留这些关联字段。

平行世界页面的独立解读使用 `gaworld/parallel/interpret.py::build_prompt()`，读取的是平行世界估计报告。修改研究报告与修改平行世界解读时，分别找到各自的模板入口。

## 政策反应与优化

`policy_sim.py::reaction_prompt()` 将居民资料、政策全文和城市名组合起来，让居民从自身处境出发回答。模型返回支持度、生活影响、家庭财务影响、遵从意愿，以及具体应对、担忧和建议。

```{raw} html
<details class="prompt-details"><summary>查看完整示例：公交末班车调整政策</summary>
```

```{literalinclude} ../_static/prompts/policy-reaction.txt
:language: text
```

```{raw} html
</details>
```

示例使用虚构城市与居民；文本由实际函数生成。[下载政策反应提示词](../_static/prompts/policy-reaction.txt)

| 字段 | 模板中的尺度 |
| --- | --- |
| `support` | −2 至 2 的整数 |
| `wellbeing`、`finance` | −5 至 5 的整数 |
| `compliance` | 0 至 100 的整数 |
| `behavior`、`concern`、`suggestion` | 各一句具体说明 |

`parse_reaction()` 读取这些字段并限制取值范围。`metrics()` 和 `composite_score()` 计算汇总指标；`optimise_prompt()` 接收已得到的反应与统计，提出政策修改。比较原政策和候选政策时，查看同一批居民的反应与评分变化。

**操作。** 在 [政策推演](../policy-games.md) 输入政策与候选方案。改变评分尺度时，同时检查提示词、`parse_reaction()`、聚合和评分函数；改变政策文本时则直接修改政策输入。

## 严肃游戏中的角色与主持人

`research/serious_game.py` 将情景设计、角色行动、回合裁定和复盘拆成不同的提示词。

| 构建函数 | 输入 | 主要输出 |
| --- | --- | --- |
| `design_prompt()` | 场景描述、回合数与角色数 | 情景、角色、回合与指标等游戏设计 |
| `agent_prompt()` | 居民资料、角色目标、私有信息、历史与当前回合 | `choice`、`action`、`thought` |
| `resolve_prompt()` | 当前局面与本轮各角色行动 | `narration`、`indicator_changes`、`role_outcomes` |
| `debrief_prompt()` | 已完成的会话与角色表现 | 游戏复盘与角色评价 |

角色行动提示词提供该角色掌握的信息；同时行动阶段，各角色依据本轮开始时的局面作答。主持人随后读取各方行动并裁定结果。修改角色提示词时保留角色的信息范围，修改裁定模板时检查指标变化与 `apply_resolution()` 的处理方式。

## 提示词本身作为实验条件

**需求估计。** `experiments/arms.py::build_prompt()` 为每个条件构建 `PromptSpec(system, user)`。`arm_id` 决定提供哪类角色或情境信息；`question` 区分 `elicit` 与 `purchase`。代码在询问待测变量时控制信息披露，再在购买任务中按条件加入协变量或情境。具体条件、命令与输出见 [需求估计实验](../cases/demand.md)。

**经典行为实验。** `experiments/classics/paradigms.py::build_prompt()` 根据范式、题目、条件与受试者构建系统消息和用户正文。两种条件共享配对设计中的受试者与题目，比较的是题面或处理条件变化后的回答，见 [经典行为实验](../cases/classics.md)。

修改这类提示词时，保存每个条件最终发送的文本，并核对条件之间实际改变了哪些信息。模板中透露了什么、隐去了什么，本身就是实验设计的一部分。

## 源码与修改检查

```{container} code-map

| 源码 | 修改后重点检查 |
| --- | --- |
| [research/workbench.py](https://github.com/wuchaozju/GAWorld/blob/main/gaworld/research/workbench.py) | 材料、功能目录与研究方案是否对应 |
| [research/protocol.py](https://github.com/wuchaozju/GAWorld/blob/main/gaworld/research/protocol.py) | 条件 ID、指标 ID、假设和协议校验 |
| [research/interpret.py](https://github.com/wuchaozju/GAWorld/blob/main/gaworld/research/interpret.py) | 发现与假设 ID、判定和证据的对应关系 |
| [parallel/interpret.py](https://github.com/wuchaozju/GAWorld/blob/main/gaworld/parallel/interpret.py) | 解释与估计报告中的行、判定是否一致 |
| [research/policy_sim.py](https://github.com/wuchaozju/GAWorld/blob/main/gaworld/research/policy_sim.py) | 字段、尺度、解析和评分的一致性 |
| [research/serious_game.py](https://github.com/wuchaozju/GAWorld/blob/main/gaworld/research/serious_game.py) | 角色可见信息、回合输入与指标更新 |
| [experiments/arms.py](https://github.com/wuchaozju/GAWorld/blob/main/gaworld/experiments/arms.py) | system/user 两段文本与实验条件的对应关系 |
| [experiments/classics/paradigms.py](https://github.com/wuchaozju/GAWorld/blob/main/gaworld/experiments/classics/paradigms.py) | 配对题目、条件与回答结构 |
```

需要在本地查看组装结果或检查解析逻辑，继续阅读 [修改与验证](editing.md)。
