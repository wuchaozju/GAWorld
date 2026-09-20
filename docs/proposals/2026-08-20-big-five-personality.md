# 设计提案：给 Agent 增加大五人格（Big Five / OCEAN）

- 日期：2026-08-20
- 状态：**待拍板**（评审已完成，决策清单见 §10）
- 评审团队：人格计算建模 / 仿真架构 / LLM Prompt 工程 / 实验评测与可证伪性（四人，含一轮交叉质询）
- 影响面：`gaworld/personality/`（新）、`gaworld/sim/_action.py`、`gaworld/behavior/dynamic.py`、`data/agents_big5.csv`（新）、`benchmark/`（新 Track F）

---

## 0. 一句话结论

**可以做，但默认应视为无效直到被证伪性实验推翻。** 这个功能有三条大概率的失败路径——只改文风、只是把 `risk_preference` 等旧变量换个名字、把 LLM 采样噪声包装成个体差异。本提案的核心不是"怎么加五个数字"，而是**怎么让它在加进去之前就无法自欺**。

四位评审在交叉质询后**收敛到一套共同方案**，只剩 8 个需要你拍板的取舍（§10）。

---

## 1. 现状勘察（已在仓库中核实）

### 1.1 `personality` 今天是什么

`agent["personality"]` 是一段**中文自由文本**，由 `gaworld/sim/agents_loader.py:42` 从 `data/hangzhou_profiles_with_names.md` 的 `**性格与情绪特征**：…` 解析而来。它今天只经两类通道生效：

**规则通道（窄且粗暴，共 2 处）**

| 位置 | 做法 |
|---|---|
| `gaworld/behavior/dynamic.py:680-696` | `_PERSONALITY_KEYWORDS` + `_classify_personality()`，中文关键词分成 4 类，唯一调用点在 `:800`，产出中断优先级 modifier |
| `gaworld/behavior/dynamic.py:563-576` | `is_extrovert = _contains_any(["外向","活泼","社交","热情","开朗"])`，命中就给 `encounter_prob += 0.10` |
| `gaworld/economy/finance.py:953-958` | 关键词 → `wealth_drive` |

**Prompt 通道（宽但一次性，约 15 处）**
`gaworld/sim/_action.py:209,291`、`_schedule.py:161,223`、`_news.py:570,630,849,922`、`_rag.py:125-141,195,224`、`_location.py:77`、`goals.py:236,478`、`cognition/realism.py:335`、`work/capabilities.py:52-79`、`interests.py:54,545`、`social/network.py:342`。

### 1.2 最重要的勘察发现：决策主循环里没有人格

`gaworld/sim/_action.py:388 choose_action()` 是**纯确定性加权评分 + `random.choices`**：

```python
total_weight = 1.0 + sum(components.values())          # :666
total_weight *= random.uniform(1-decision_noise, 1+decision_noise)   # :667-668
```

`personality` 在这个函数里**一个字都没有**。它只出现在 `_llm_generate_actions`(:209) 与 `_llm_generate_location_bias`(:291) 这两个**生成期**调用里，产物还被 `save_action_space`(:270) 永久缓存到 `agent_N_actions.json`。

> **结论：人格接进 `choose_action` 的 `components` 字典，收益远大于写进任何 prompt——零 token、可复现、可 ablate。** 而且接口是现成的：`:536` 的 `styles = _action_style_tags(act)` 已经把每个动作打成 `{avoidant, social, progress, maintain, restorative, quick}` 六个标签，这就是 OCEAN 的天然投影面，不需要新造语义。

### 1.3 一个顺带发现的既有缺陷

`gaworld/sim/_cognition.py:151`：

```python
agent["state"]["emotion"] += 0.1 * (avg_emotion - agent["state"]["emotion"])
```

情绪传染**只拉向邻居均值，没有拉向个人基线**。长期必然把全城情绪收敛成一个值、抹平个体差异。这是当前代码里已经存在的实质缺陷，**也是 N（神经质）能否生效的前提**——如果不修，给 N 加情绪基线会被这条传染项反复抹平。

### 1.4 共线性隐患（本功能最大的设计陷阱）

`data/hangzhou_agents_state_init.csv`（51 人 + 表头 = 52 行）已有 5 个与 OCEAN 高度共线的变量：`risk_preference`、`voice_propensity`、`mobility_intent`、`policy_sensitivity`、`platform_dependence`。

更麻烦的是 `gaworld/population/writer.py:56-60`：合成人口的 `personality_bits` **只由 `state["stress"]` 和 `state["voice_propensity"]` 两个阈值拼成两句模板**——合成人口的中文性格文本本身就是 state 的函数。

> 如果 OCEAN 从这些 state 变量映射生成，增量信息在结构上恒为 0，这个功能就是零收益的重参数化。**这一条否决了评审初轮里的一个方案（见 §9）。**

---

## 2. 三个必须先排除的失败模式

整套设计围绕这三条组织，验收也围绕它们组织：

| 失败模式 | 症状 | 排除手段 |
|---|---|---|
| **(i) 只改文风** | 日记更有个性，但去不去聚会的概率没变 | 所有验收指标只看**结构化输出**（活动名、style tag 计数、二值选择），不看自然语言；`A3 style-only` 对照臂 |
| **(ii) 旧变量改名** | OCEAN 与既有 5 变量共线，ΔR²≈0 | 事前 CCA 诊断（零成本，见 §7.1）+ `A6 residual-trait` 对照臂 |
| **(iii) 噪声被误读为个体差异** | 任意随机标签都能造出同样的离散度 | `A2 shuffled` + `A5 random-trait` + `A8 additive-null` 对照臂 |

---

## 3. 数据模型

### 3.1 落点

```
agent["ext"]["big_five"] = {"v": 1, "source": "llm_coded|prior_sampled",
                            "o": 0.0, "c": 0.0, "e": 0.0, "a": 0.0, "n": 0.0}   # z 分数，截断 ±2.5
```

经 `ctx.agent_ext(agent, "big_five")`（`gaworld/kernel/context.py:48`），与 `gaworld/family/plugin.py` 做法一致。

**明确不做的三件事：**

1. **不进 `agent["state"]`**。`state` 是可漂移层——`gaworld/cognition/realism.py:97-267` 每步重写 `self_control`/`social_need`，`gaworld/parallel/analysis.py` 会把新键当时序变量画图。放进去等于让人格自己抖动。
2. **不加 `CSV_COLUMNS` / `STATE_VAR_KEYS` 列**（`gaworld/population/schema.py`）。那是 population writer / dashboard studio / synth 三方共享的契约。
3. **不重蹈 interests 的覆辙**。`gaworld/interests_plugin.py` 头部注释自陈 `agent["growth_profile"]` 留在顶层是因为读侧还内联。这次的办法不是"选对 key"，而是**从第一天起不让任何模块字面索引这个 dict**——全项目只暴露 `gaworld/personality/traits.py` 的三个纯函数。

### 3.2 维度数

**5 维，不拆 facet。** n=51 时 30-facet 是伪精度，采样噪声压过效应。（人格评审曾建议拆 E→(assertiveness, sociability)、C→(orderliness, industriousness) 共 7 个数，作为可选项保留在 §10-D4。）

### 3.3 持久化

- `data/agents_big5.csv`（`id,o,c,e,a,n,source,coder_icc,v`）——**离线冻结、进 git、运行时只读**，独立数据资产，不碰 `CSV_COLUMNS`。
- `output/traits/agent_traits.csv`——每次 run 落实际生效的 trait + `arm` 列，防配置漂移。
- `ctx.recorder.record("big_five.profile", ...)` 供审计。

### 3.4 向后兼容契约（写成测试）

> **缺失 traits ⇒ 中性 0 ⇒ 所有 modifier 恒等于 1.0、`trait_style_fit` 恒等于 0 ⇒ 行为逐位等同于今天（容差 1e-9）。**

有了它旧 run 重放天然安全：`gaworld/apps/replay_runs.py` 只读 trace meta 头；`agents_loader.parse_profile` 只抽已知加粗字段、忽略未知行；`dashboard_server` 构造 payload 时显式列键——三处都对新字段无感。

---

## 4. 数值从哪来

### 4.1 51 人真实语料 → LLM 一次性反向标定

从 `data/hangzhou_profiles_with_names.md` 的「性格与情绪特征」段编码，`scripts/calibrate_big5.py` 离线跑一次，冻结进 `data/agents_big5.csv`。

三条质量要求：

1. **逐维独立打分**，每维给 −2/0/+2 的行为化锚点。**不要一次吐五个数**（光环效应）。
2. 每份打 3 次取中位数，双 coder 一致性 **ICC ≥ 0.7**，低一致维度人工复核。
3. **profile 没提到的维度不能记 0**——多数 profile 只写了 N 和 E，记 0 会压缩人群方差。未提及 → 从条件分布采样。

选它而非重写文本的理由：`agents_loader.parse_profile` 解出的 `personality` 已经喂进 `interests.py` 的 prompt 模板、记忆与既有轨迹，重写文本等于让全部下游派生失效。

### 4.2 `synth.py` 500 人合成人口 → 人群先验独立采样

合成人口的中文文本是 state 的模板函数（§1.4），标定即循环论证。改走：`derive_rng(spec.seed, "big5")`（`gaworld/population/synth.py:111` 已有的流派生模式），按 OCEAN 人群先验做**多元正态抽样**：

- 每维 `z ~ N(0,1)`，**不要 U(0,1)**（会造出过多极端人格）。
- 维度间相关取实证共识区间中位值（非精确文献数字）：N–E/A/C/O ≈ −0.25/−0.25/−0.30/−0.15；A–C ≈ +0.25、E–A ≈ +0.15、E–O ≈ +0.25、C–O ≈ +0.05。Cholesky 生成。
- **仅允许条件于 age/sex 边际，严禁条件于任何 `STATE_VAR_KEYS`**——这样 ρ₁ 由采样噪声决定而非结构决定。
- n=51 时均值标准误约 0.14 SD，**必须抽样后重标定**（rescale to target mean/sd），否则整城人格会系统性偏移。

条件依赖量级（挂在 `synth.py:652` 已有的 `couple_states_to_attributes` 开关下）：年龄每 10 岁 C +0.10 SD、N −0.08 SD；女性 N/A 约 +0.3 SD；职业选择效应封顶 0.2–0.4 SD，再大就是刻板印象。

> **中国样本的均值常模差异不确定**——跨国均值比较受中庸/默许反应风格污染，建议**不做均值平移**。结构（五因子可复现、维度间相关方向）在中国样本基本一致，可放心用。

---

## 5. 调制机制（核心设计）

### 5.1 唯一读取入口

```python
# gaworld/personality/traits.py —— 叶子模块，零 gaworld 内部依赖
BigFive = dict[str, float]                       # {"o","c","e","a","n"}，z 分数

def traits_of(agent) -> BigFive: ...             # 缺失即全 0
def style_fit(traits, styles) -> float: ...      # 主通道：加性
def trait_modifier(agent, name, *, strength=1.0) -> float: ...   # 次通道：乘性
```

### 5.2 主通道：`choose_action` 的加性 `trait_style_fit`

**不是给三十个 component 各乘一个数，而是新增一个加性 component**：

```python
components["trait_style_fit"] = style_fit(traits_of(agent), _action_style_tags(act))
driver_labels["trait_style_fit"] = "性格倾向"      # 可解释性白送，进决策归因
```

系数表（style 标签 × trait）：`social×E`、`progress×C`、`avoidant×(−C,+N)`、`restorative×N`、`quick×(−C)`、`progress/新奇×O`。

**幅度 ±0.6**，与既有 component 同量级（`growth_drive`=0.6、`location_prefer`=1.0、`habit`≈0.9）。

### 5.3 次通道：乘性 modifier 表

一张命名表 + 一个纯函数，**硬夹 0.75–1.25**：

```python
_MODS = {
    "interrupt_threshold": {"c": +0.30, "n": -0.15},   # dynamic.py:181
    "spontaneity_chance":  {"c": -0.25, "o": +0.20},   # dynamic.py:321
    "social_encounter":    {"e": +0.35, "a": +0.10},   # dynamic.py:573
    "decision_noise":      {"o": +0.20},               # _action.py:469
    "impulse_gate":        {"c": -0.25},               # _action.py:678
    "wealth_drive":        {"c": +0.20, "n": +0.10},   # finance.py:953
}
```

三条自律，用来挡住"这是不是过度设计"的质疑：

1. 模块是叶子，不 import 任何 gaworld 内部包，等价于 `_clip`。
2. `_MODS` **只在有真实消费者时才新增条目**，禁止预置"将来可能用到"的名字。
3. **不提供注册 API、不提供插件扩展 hook。**

> 为什么表而不是几个 `if`：P1 就有 6 个消费者，写死会复制 6 份系数逻辑。表在第二个消费者出现时才真正省事，而我们一上来就有 6 个。

### 5.4 ⚠️ 必须给调制加残差（否则验收指标失去意义）

这是交叉质询里发现的关键点。如果 `trait → 行为倾向` 是**确定性**映射，观测窗口一长，相关就趋于 1：

| 观测天数 T | 1 | 7 | 17 | 30 | 90 | ∞ |
|---|---|---|---|---|---|---|
| 隐含 r | 0.14 | 0.35 | 0.50 | 0.61 | 0.80 | **1.00** |

（Poisson 社交事件、λ₀=2/天、±25% 调制下的解析解）

**修正**：调制器加人内/人间残差 `m_i = 1 + 0.1·z_i + η_i`，`η ~ N(0, 0.268²)`。渐近 `r = 0.1/√(0.01+0.0716) = 0.35`，人格解释 **12.3%** 的 between-agent 行为方差——正落在 5–15% 的实证带内。

**报告窗口固定 7–14 天**（此时 r ≈ 0.30–0.34）。任何不带窗口归一的效应量判据都是在测天数，不是在测人格。

### 5.5 特质—状态动力学（N → 情绪）

人格是慢变量，情绪是快变量。建议的日尺度形式：

```
μ_i = clip(0.50 − 0.12·z_N + 0.04·z_E, 0.25, 0.75)    # 个人情绪基线
λ_i = 0.25 · (1 − 0.30·z_N)                            # 回复速率，半衰期≈2.4 天
σ_i = 0.05 · (1 + 0.50·z_N)                            # 日噪声，高 N 波动大
e ← e + λ_i(μ_i − e) + Σshock + σ_i·ξ
```

**前置修复**：`gaworld/sim/_cognition.py:151` 的传染系数从 0.1 降到 0.05–0.08，并让个人基线回复项与它**并列**而非被它独占。不修这条，N 的效应会被传染反复抹平（§1.3）。

### 5.6 人格漂移

**P0/P1 不漂移。** 成熟度原则的实证量级是成年期每十年 C/A 上升、N 下降约 0.1–0.2 SD，折算到日尺度几乎为零；仿真跨度是天，给它加日常漂移是纯粹的投机抽象。

P2 可选研究开关：只在 `gaworld/events/life.py` 的重大事件上施加 0.05–0.15 SD 阶跃，带 60% 回弹（set-point 理论）。校验：仿真一年后全体 rank correlation 应 > 0.9。

---

## 6. Prompt 通道（P2，默认 off）

### 6.1 三条硬规则

1. **不写数字。** "（外向性 0.73）"这类括号补充也不要——它只会诱导 LLM 做"我是 0.73 所以我该很外向"的漫画化表演。
2. **只写偏离显著的维度**，中间段输出空串。
3. **每场景最多 2 维、共 ≤60 字**，作为**资料块**注入而非**要求块**（要求块的祈使句权重更高，会让人格盖过情境）。

### 6.2 锚句必须是"第二人称 + 可观测行为 + 一个具体阈值"

这是让 LLM 产生**决策**差异而非**文风**差异的唯一可靠手法。示例：

> **E 低**：社交倾向：你会主动回避临时聚会，人多的场合待一小时就想找借口离开；恢复精力靠独处。
> **E 高**：社交倾向：你在陌生场合会主动搭话，独处超过两天就会觉得不对劲，宁可绕路也要顺道见个人。
> **C 低**：做事方式：你常把计划排得很满然后放掉一半，deadline 前一天才动手，且不太为此内疚。
> **C 高**：做事方式：你会提前把当天要做的事排好顺序，被打断后一定会补回来，很少让事情过夜。

### 6.3 概率渲染，不用硬阈值

硬阈值 |z|>0.8 会把连续特质**人为压成三分类**（写/静音/写）。改为：

- `P(渲染此维) = Φ((|z| − 0.5) / 0.4)`，z=0.8 处恰好 50%，边界抹成渐变。
- 锚句分 4 级：|z|∈[0.8,1.5] 用"偏…"，>1.5 用"明显…"。

这把等效阶跃从 1.0 降到约 0.35。判据：行为对 z 回归，检验 z=±0.8 处的跳跃，**|jump| > 0.3 残差 SD 即判定三分类泄漏**。

### 6.4 场景—维度映射

| 场景 | 注入点 | 维度 | 通道 |
|---|---|---|---|
| 行动选择 | `_action.py:choose_action` | O,C,E,A,N | **规则**（主战场） |
| 消费决策 | `finance.py:953` | C, N | **规则** |
| 日程规划 | `generative_city_sim.py` daily_routine | C, E | prompt 资料块 |
| 社交/关系补全 | `social/network.py:342` | E, A | prompt |
| 新闻反应 | `_news.py:570,630` | O, N | prompt（O 管看不看，N 管怕不怕） |
| 目标设定 | `goals.py:236` | O, C | prompt（一次性 bootstrap） |
| 日记/反思 | `_diary.py` | N, A | prompt（这里**允许**影响文风） |
| 动作空间生成 | `_action.py:209,291` | — | **不接**（见下） |

**动作空间缓存不打版本号、不重生成。** `agent_N_actions.json` 每人 47 个活动 × 每活动 18–22 个动作，且 `_llm_generate_actions` 的 prompt 本来就要求"覆盖推进/维持/回避/社交型"——旧缓存不是"无人格产物"，而是**人格中性的宽候选池**，正是我们想要的、由 `trait_style_fit` 在其上做选择的底座。若把人格塞回生成期，人格就被烘进不可 ablate 的缓存里，**反而毁掉可归因性**。

### 6.5 关键词逻辑退役

`_classify_personality`(dynamic.py:688) 只有一个调用点(:800)，在函数体内做"traits 优先、关键词兜底"是外科手术；跨模块双轨才是债。

⚠️ 注意语义冲突：`_PERSONALITY_KEYWORDS`(:680) 里的"开放"被当成 adventurous，与 OCEAN 的 O 只是同名。接入时必须**整体替换**，不要让两套语义共存。

---

## 7. 验证与 GAWorld-Bench Track F

### 7.1 事前共线性诊断（零 LLM、几秒钟、**merge gate**）

冻结 `data/agents_big5.csv` 后，立刻对 51×5 的 OCEAN 矩阵 B 与 51×5 的既有变量矩阵 X 做：

1. 典型相关分析：**最大典型相关 ρ₁ < 0.85**
2. 逐 trait 回归：**max R²ⱼ < 0.6 且至少两个 trait R²ⱼ < 0.4**
3. 10 变量合并条件数 **< 30**

任一项不过 → **不要跑仿真，先改 trait 来源**。

### 7.2 解析效应上限（零 LLM、**merge gate**）

把 `choose_action` 的权重公式单独抽出来蒙特卡洛 10⁵ 次，算出注入强度对应的 Δp 与隐含 r。

已算出的量级参考（K=10 候选、j=3 个 social 标签、n=40 次决策/5 天）：

| 注入方式 | Δp | 隐含 \|r\| | 结论 |
|---|---|---|---|
| 乘性 ±25%，**单个动作** | 0.045 | **0.06–0.07** | ❌ 低于噪声，设计天花板就不合格 |
| 乘性 ±25%，**动作类/style 层** | 0.106 | 0.14–0.18 | ⚠️ 勉强，接近 N=51 的检出下限 |
| 加性 `trait_style_fit` ±0.6，style 层 | 8–15pp | **0.25–0.40** | ✅ 推荐 |

> **规则：调制必须施加在动作类/style 层，禁止单动作。天花板 < 0.10 直接打回设计，不许合入。**

### 7.3 统计口径统一（三方原本冲突，已收敛）

| 量 | 统一口径 |
|---|---|
| 方差解释 | **adjusted R² 或 5 折 CV R²，门槛 0.10**（N=51 时纯噪声的期望 R² 就有 5/50=0.10，raw R² 不可用） |
| S 档效应量（仿真、日级） | 目标 \|r\| **0.10–0.30**，过强 fail 阈 **> 0.45** |
| P 档效应量（20 情景聚合） | 目标 \|r\| **0.20–0.45**，过强 fail 阈 **> 0.60** |
| 跨档换算 | 奇偶情景 split-half 测 ρ_agg → Spearman-Brown 反解 ρ₁ → 报 `r_single = r_agg·√(ρ₁/ρ_agg)`。**只有 r_single 与文献 0.1–0.3 可比**，写进 `trait_effects.json` 作为必填字段 |

### 7.4 功效现实：逐对检验在设计上就是废的

N=51、α=0.05 双尾、power 0.80：

```
r_MDE = tanh[(1.96+0.84)/√(51−3)] = 0.383
```

即**单对相关的最小可检出量就是目标带的上沿**。聚合 20 情景把信度从 ρ≈0.4 提到 0.93，买到的是**效应量不是功效**。

> **唯一可行的统计量是矩阵级**：15 个预登记 (trait→behavior) 对的**平均 r**，SE = (1/√48)/√15 = 0.037 → **MDE(平均 r) ≈ 0.10**。
> 单对命中判定改为"该对的 95%CI 与目标带相交，且 CI 下界 < 0.5"，带下沿降到 0.08。所有单对结论在 report 里一律标 `underpowered`。

### 7.5 规则通道下"什么才算验证"（本次评审最重要的一条）

人格效应是**直接写进打分函数的**。因此"测出 E→社交 r=0.35"本身不是科学证据。分两层：

**第一层：参数回收（hygiene，等同 Track A 的地位）**
判据不是"有相关"，而是"**观测 r 与权重公式解析预测的 r 一致**"：`|r_obs − r_pred| < 0.05`。它只回答一件事——注入强度确实是我们设定的强度、没被其余 20 多个 component 淹没、没被冲动分支（`_action.py:681`，最高 0.40 概率完全绕过 weights）吃掉。**scorecard 上必须标 `parameter-recovery, 弱证据`**，与 Track A 的循环论证警告同款。

**第二层：涌现层（真正的验收）**
判据必须落在**规则里没写**的量上。规则编码的是"单次选择的概率偏移"，它没有编码：

| # | 指标 | 数据来源 | 判据 |
|---|---|---|---|
| 1 | 社交网络度数分布形状 | episodes 的 `social_partners` 派生 | A1 比 shuffled 更偏斜；hub 身份跨 seed 稳定（度数排名 Spearman ρ ≥ 0.5） |
| 2 | **trait-homophily** | 同上 | Newman assortativity by trait > 0，置换 p<0.05。规则里绝无"按 trait 择友"，涌现出来才是非平凡跨层结果。`GAWORLD_BENCH_DESIGN.md` Track B 已列 homophily，直接接 |
| 3 | 经济不平等 | `wealth_snapshot.csv:balance` | A1 vs shuffled 的 ΔGini ≥ 0.03，置换 p<0.05 |
| 4 | 跨情境一致性 ICC | 探针 battery | ICC(2,1) 在 A1 与 A2 之间的差，**须超过**由直接调制解析预测的量 |
| 5 | 群体极化速度 | `stance_score` 方差对天数的斜率 | A1 vs A2 显著 |

### 7.6 消融矩阵

| Arm | 操作 | 剔除的假设 |
|---|---|---|
| A0 no-Big5 | 现状 | 基线 |
| A1 full | trait 进 prompt + 规则 | 待验对象 |
| **A2 shuffled** | 51 个 OCEAN 向量整体置换到别人身上 | (iii) 噪声：A1≈A2 ⇒ 人格没生效 |
| A3 style-only | trait 只进说话风格段 | (i) 只改文风 |
| **A4 rules-only** | trait 只进规则通道 | **主臂**（本方案主战场在规则层） |
| A5 random-trait | 同分布随机数替换 trait | (iii) 任意随机标签 |
| **A6 residual-trait** | 注入"OCEAN 对既有 5 变量回归后的残差" | (ii) 零信息重参数化：A6≈0 而 A1 大 ⇒ 全由旧变量承载 |
| A7 seed-replicate | A1 同 trait 换 3 个 seed | 估 within-agent 噪声与 ICC |
| **A8 additive-null**（新） | 把权重公式单独抽出解析/蒙特卡洛推演，得到"agent 间只有独立概率偏移、无社会交互"时各涌现指标的期望。**零 LLM，秒级** | 真实仿真必须显著偏离此基线，才说明人格经由交互产生了非平凡后果。**比 shuffled 更强**——shuffled 保留交互只破坏对应关系，additive-null 直接扣掉"不需要跑仿真就能算出来的部分" |

实施前提：`personality.channels = ["prompt", "rules", "style"]` **三个独立开关**。没有它，A3/A4 消融要靠改代码实现，等于没有对照——**功能一旦合入就永远不可归因**。

### 7.7 新增产物

1. `data/agents_big5.csv`（冻结）
2. `output/traits/agent_traits.csv`（每 run 落实际生效 trait + arm）
3. **`output/behavior/agent_behavior_summary.csv`** ← 最关键的缺口。现有 `comparison_metrics.csv` 只有 `metric,baseline_final,event_final,delta_final,...`，**没有 agent_id**，异质性完全测不了。好在每臂下有 `state/agent_state_history.csv`（长表 `agent_id,step,metric,value`，20 个 metric），派生脚本纯 stdlib 可写
4. `benchmark/results/trait_effects.json`（每对的 r、95%CI、置换 p、arm 对比、区间命中、`r_single`）

### 7.8 Track F 而非塞进 B/C

- Track B 是群体涌现、Track C 是干预因果——`SIGN_TESTS`(`gaworld_bench.py:64`) 的因变量正是 `risk_preference` 等，把 trait 塞进去会变成**自变量当因变量**，是 Track A 循环论证的翻版。
- 复用：`read_csv_rows/_floats/clamp01`、`ci95`、`_determinism_score`(:330)、覆盖度折扣 `_aggregate_c`、`build_scorecard`(:576)/`render_scorecard_md`(:609) 的 `names` 字典加 `"F": "人格有效性"`。
- `score_F = (0.4·F1 + 0.3·F2 + 0.3·F3) × coverage`

### 7.9 成本预算

实测锚点（`benchmark/TIER_B_RUNBOOK.md`）：20 agent × 60 天快进 = 1200 次调用；MiniMax 单次探针 7.4s；`day_routine_workers` 默认 **1（全串行），需手动开 8**。

| 档 | 设计 | 调用数 | 8 并发耗时 |
|---|---|---|---|
| **P 档（探针，主力，出相关系数）** | 51 agent × 20 情景 × **4 重复** × 7 arm | ≈ 2.8 万 | ≈ 7 小时 |
| **S 档（短仿真，确认方向）** | A0/A1/A2 三臂 × 20 agent × 5 天全保真 | ≈ 9000 | ≈ 4.7 小时 |
| ~~全保真长跑~~ | 51 × 30 天 × 7 臂 | ≈ 30 万 | **不做**，没有任何判据需要它 |

> 重复次数从 2 提到 4：2 次重复的 ICC 标准误太大，估不出去衰减所需的 ρ₁。

**不在 `--fast` 或 `--fast-forward` 上评人格**：前者 `deterministic_cognition` 让 planning/reflection 走 `_fallback_*`，prompt 通道基本失效；后者根本不写 episodes，行为分布无从测。

### 7.10 探针情境（P 档 battery 示例）

固定 seed、mock 新闻，每情境 × 4 重复 × 全部 51 人：

1. 临时聚会邀约（19:00，明天有交付）→ 去/不去二值率
2. 裁员传闻新闻 → 是否触发 info_seek、检索词数量
3. 周末 4 小时空白 → 插入活动的 `_action_style_tags` 分布
4. 一笔计划外 3000 元支出 → 接受率
5. 与摩擦度 0.7 的邻居狭路相逢 → 是否产生互动 episode

**负控制**：把锚句改成同义但反向的措辞，若分布不变，说明 LLM 在忽略这一块。

> ⚠️ 构念效度风险：若 20 个情景是**照着 trait 写的**，测的是 modifier 代码本身，那是 manipulation check 不是效度检验。情景应先于系数表设计。

---

## 8. 分阶段计划

| 阶段 | 改哪些文件 | 验证（gate） | 成本 |
|---|---|---|---|
| **P0**<br>数据 + 播种，不接决策 | 新增 `gaworld/personality/{traits,config,plugin}.py`；`gaworld/settings/personality.py`（含 `channels` 三开关，`rules=true`/`style=true`/`prompt=false`）+ `defaults.py` + `config_docs.SECTIONS`；`plugins/__init__.py` 加一项；离线 `scripts/calibrate_big5.py` → 冻结 `data/agents_big5.csv`；插件在 `agents.built` 读 CSV → `ctx.agent_ext` | ① 事前共线性诊断（§7.1）<br>② 解析效应上限 ≥ 0.10（§7.2）<br>③ 同 seed 双跑确定性 = 1.0（`--det-a/--det-b`）<br>④ **中性回退：trait 全 0 时与 A0 逐点一致（1e-9）**<br>⑤ 插件装配测试（仿 `tests/test_interests_plugin.py`） | **0 token，分钟级** |
| **P1**<br>接进决策，**flag 默认 off** | `_action.py:choose_action` 加 `trait_style_fit` + `driver_labels` 一条；`decision_noise`/冲动闸门/`self_control_*` 三处乘性调制；`dynamic.py:_classify_personality` 改 traits 优先关键词兜底；`_cognition.py:151` 情绪基线修复；新增 `output/behavior/agent_behavior_summary.csv` 产物 | ⑥ **校准 harness 断言 0.10 ≤ \|r\| ≤ 0.40**（mock LLM + 固定 seed + 多天 headless）<br>⑦ 参数回收测试 `\|r_obs − r_pred\| < 0.05`<br>⑧ `channels.rules=false` 时逐位等同 P0<br>⑨ S 档 shuffled 臂置换检验 | ≈ 9000 次调用<br>≈ 3–5 小时 |
| **P1.5**<br>评测闸，无代码 | — | ⑩ `max R²ⱼ < 0.6`、**adjusted ΔR² ≥ 0.10**<br>**不过则回炉标定，不进 P2** | 0 token |
| **P2**<br>**flag 默认 on 之前** | prompt 通道（默认仍 off，供 A4 对照）；`synth.py` 的 `derive_rng(seed,"big5")` 先验采样；`finance.py:_infer_wealth_drive`；interests 成长速率；删关键词表；**11 处文档/面板同步** | ⑪ 完整 Track F：涌现层五项（§7.5）+ A8 additive-null + P 档 disattenuation 交叉验证 | ≈ 2.8 万次<br>≈ 7 小时 |

**两条硬规矩：**

1. **P0 的五项 gate 全部零 token、分钟级，一项不过不许合**——卡不住开发节奏，但挡得住三种失败模式。
2. **把 flag 默认打开的那个 PR 必须挂 Track F PASS**；在此之前 scorecard 上 Track F 恒显 `UNVERIFIED`（三态，与 trust gate 同款）。这正是为了不重演"确定性从未测过、gate 却显示 OK"的假性安心。

---

## 9. 评审过程中被否决 / 修正的方案

记录下来，避免以后有人再提。

| 方案 | 提出者 | 结局 |
|---|---|---|
| OCEAN 从既有 `state` 变量确定性映射生成（可复现、零成本、覆盖 synth 人口） | 架构 | **否决并改判**。合成人口的性格文本本身就是 state 的函数（`writer.py:56-60`），ΔR² 结构上恒为 0。改为 51 人 LLM 标定 + synth 走人群先验采样 |
| 所有 modifier 硬夹 ±25% | 架构 | **部分撤销**。解析算出隐含 \|r\|≈0.14–0.18，落在 N=51 的检出下限之下——设计上就无法验收。主通道改为**加性 ±0.6 on style 层**；乘性 ±25% 降为次通道（作用于 dynamic.py 的小基率概率，那里逐 tick 复合，放宽反而失控） |
| 既有 5 变量加弱回归锚 `x ← x + 0.01(x_baseline(z) − x)` | 人格 | **修正**。纯收缩会让残差按 0.99^t 塌缩，**第 62 天击穿 `max R²<0.6`**，一年后 R²≈1.00，ΔR² 归零。改为带配对噪声的 OU：`κ=0.005`（半衰期 139 天）、`σ_x=0.0125/天`，稳态 R² 恒为 0.30±0.03。另加两条闸：每 30 日重算 R²ⱼ，>0.45 置 κ=0；**每个 trait 最多挂 2 个既有变量**（5 个都载荷于 N 时最优线性组合与 N 的相关会到 0.83，顶穿 ρ₁<0.85）|
| prompt 里只写 \|z\|>0.8 的维度、中间段静音 | Prompt | **软化**。硬阈值会把连续特质压成事实三分类。改概率渲染 `Φ((\|z\|−0.5)/0.4)` + 锚句 4 级分档，等效阶跃从 1.0 降到 0.35 |
| "跑出 r=0.8 应判 fail 并回查是否硬编码进打分函数" | 评测 | **撤回**。规则通道下它本来就编码在里面。替换为两层判据：参数回收（hygiene）+ 涌现层（真正验收），见 §7.5 |
| 目标 R² = 0.25–0.35 | 人格 | **统一口径**。若指单变量即 \|r\|=0.50–0.59，正好落在 fail 线之上；N=51 时纯噪声的期望 raw R² 就有 0.10。改为 adjusted R² / CV R²，门槛 0.10，对应人格解释 **12.3%** between-agent 方差 |
| 动作空间缓存打版本号、重生成 | 架构（初轮） | **否决**。旧缓存是人格中性的宽候选池，正是我们要的底座；把人格烘进缓存会毁掉可归因性。省下 51–102 次调用 |
| 拆 facet（E→2, C→2, 共 7 个数） | 人格 | **暂缓**，见 §10-D4 |

---

## 10. 待你拍板的决策清单

| # | 决策 | 默认推荐 | 代价 |
|---|---|---|---|
| **D1** | 主通道强度：加性 `trait_style_fit` ±0.6 | **采纳**，但 P0 必须先跑解析上限确认隐含 \|r\| 落在 0.25–0.40 | 定大了撞"过强 fail"，定小了测不出 |
| **D2** | prompt 通道何时开 | **P2 实现、默认 off**，仅作 A4 对照臂。P0/P1 中文 `personality` 文本仍是唯一叙事来源 | 推迟了"人格看起来生效"的观感收益 |
| **D3** | 既有 5 变量是否加 OU 弱回归锚 | **P1 不加，P2 再评估**。它会持续吃掉 ΔR²，且让验证多一个动态变量 | 不加则半年后人格与 state 脱钩，人格变装饰 |
| **D4** | 是否拆 facet（E→assertiveness/sociability，C→orderliness/industriousness） | **不拆**，先做 5 维 | 拆了能分离"发声 vs 社交频次"两条不同通道，但 n=51 下采样噪声压过效应 |
| **D5** | 51 人 LLM 标定的人工复核范围 | **N 与 E 两维全部人工过一遍**（约 1 小时），其余接受 3 次打分中位数 | 全维人工 ≈ 3–4 小时 |
| **D6** | `_cognition.py:151` 情绪传染缺个人基线锚，是否作为 P1 前置修复 | **是，纳入 P1**。不修则 N 的效应会被反复抹平 | 会改变所有既有实验的情绪轨迹，旧 run 不可比 |
| **D7** | 效应量口径 | S 档 \|r\| 0.10–0.30 / P 档 0.20–0.45 / adjusted ΔR² ≥ 0.10 / 报告窗口固定 7–14 天 | 口径一改，判据全部要重算 |
| **D8** | 合入门槛 | **P0 五项 gate（零 token）必过；flag 默认 on 的 PR 必须挂 Track F PASS** | Track F 完整跑一次 ≈ 7 小时 + 2.8 万次调用 |

**次要开放项**：探针 battery 的 20 个情景应当**先于**系数表设计（否则测的是 modifier 代码本身）；`benchmark/` 里 Track C 素材当前在 `output_archive_202606/comparisons/`，`output/` 下已无 `comparisons/`，Track F 的产物路径需要一并确认。

---

## 附录 A：勘察确认的代码锚点

| 锚点 | 位置 | 用途 |
|---|---|---|
| `choose_action` | `gaworld/sim/_action.py:388` | 主接入点 |
| `_action_style_tags` | `gaworld/sim/_action.py:57,536,684` | style 标签，OCEAN 投影面 |
| `total_weight = 1.0 + sum(components.values())` | `gaworld/sim/_action.py:666` | 权重合成规则 |
| `decision_noise` | `gaworld/sim/_action.py:469,667` | 乘性调制点 |
| 冲动分支（最高 0.40 绕过 weights） | `gaworld/sim/_action.py:678-684` | 效应衰减源，参数回收要扣掉 |
| `driver_labels` | `gaworld/sim/_action.py:495,720` | 决策归因，加一条即可解释 |
| `save_action_space` | `gaworld/sim/_action.py:270` | 缓存，**不动** |
| 情绪传染无基线锚 | `gaworld/sim/_cognition.py:151` | 既有缺陷，P1 修 |
| `_PERSONALITY_KEYWORDS` / `_classify_personality` | `gaworld/behavior/dynamic.py:680,688`（唯一调用点 `:800`） | 退役目标 |
| `is_extrovert` / `encounter_prob` | `gaworld/behavior/dynamic.py:563-576` | 退役目标 |
| 中断阈值 / 冲动基率 | `gaworld/behavior/dynamic.py:181,321` | 次通道接入点 |
| `wealth_drive` 关键词 | `gaworld/economy/finance.py:953-958` | 退役 + 次通道接入点 |
| `ctx.agent_ext` | `gaworld/kernel/context.py:48` | 数据落点 |
| `derive_rng` | `gaworld/population/synth.py:111` | synth 先验采样流 |
| `personality_bits`（state 的函数） | `gaworld/population/writer.py:56-60` | 否决 state 映射方案的证据 |
| `STATE_VAR_KEYS` / `CSV_COLUMNS` | `gaworld/population/schema.py` | **不动** |
| `SIGN_TESTS` / `_determinism_score` / `build_scorecard` / `names` | `benchmark/gaworld_bench.py:64,330,576,609` | Track F 复用点 |
| `n2_swap_persona` | `benchmark/rubric/ablate.py` | A2 shuffled 的思路来源（注意：那是样本级事后破坏，Track F 需上游重跑） |

## 附录 B：⚠️ 实施注意

`gaworld/behavior/dynamic.py` 用的是**模块级 `random` 而非 `ctx.rng`**，回归测试必须显式 `random.seed()`。新代码请从 `ctx.rng` 派生，**不要再引入第二个全局 RNG**。

---

## 11. 实施记录（2026-08-21）

### 11.1 D1–D8 的最终裁定

| # | 裁定 | 与提案默认推荐的差异 |
|---|---|---|
| D1 | 加性 `trait_style_fit`，**幅度 0.30**（先跑解析上限再定） | 提案写 ±0.6。闸门跑完否掉了 0.6，见 §11.2 |
| D2 | prompt 通道**提前到 P1 且默认 on** | 提案是 P2、默认 off |
| D3 | P1 不给既有 5 个状态变量加 OU 回归锚 | 同提案 |
| D4 | 5 维，不拆 facet | 同提案 |
| D5 | 跑 LLM 标定，N/E 两维人工复核 | 同提案 |
| D6 | `_cognition.py` 情绪基线锚纳入 P1 一并修 | 同提案 |
| D7 | 全盘采纳 §7.3 效应量口径 | 同提案 |
| D8 | P0 零成本 gate 必过，Track F 后补；**flag 默认 on** | 提案要求默认 on 的 PR 挂 Track F PASS；此处放宽，scorecard 上 Track F 标 UNVERIFIED 直到真跑过 |
| D9（提案外新增） | 共线性闸门 FAIL 后：**照发 + 硬性标注**，不正交化、不砍维度 | 见 §11.6 |

三条通道最终定名为 `rules` / `prompt` / `voice`（提案里的"表达通道"独立成 `voice`，只作用于日记），
分别对应消融矩阵 §7.6 的规则臂、A4 prompt 臂、A3 style 臂。

### 11.2 D1 被闸门否掉：幅度从 0.6 降到 0.30

`scripts/big5_effect_ceiling.py` 用**真实的 `choose_action`** 蒙特卡洛 51 个合成居民，
按 §7.3 的分档口径判定（S 档 ≤60 次决策，单项 \|r\| > 0.45 判过强；P 档 >60 次决策，> 0.60 判过强）：

| 幅度 | S 档（40 次决策）最大 \|r\| | P 档（200 次决策）最大 \|r\| | 判定 |
|---|---|---|---|
| 0.25 | 0.32 | 0.48 | PASS |
| **0.30** | **0.34** | **0.54** | **PASS（选定）** |
| 0.35 | 0.39 | 0.59 | PASS，但 P 档贴线 |
| 0.40 | 0.43 | 0.62 | FAIL（P 档过强） |
| 0.60 | 0.54 | 0.73 | FAIL（两档都过强） |

复现：`python scripts/big5_effect_ceiling.py --decisions 40` 与 `--decisions 200`。
脚本本身按窗口自动选档——把 200 次决策的聚合结果拿 S 档判据去卡会误杀一个行为正常的系统
（Epstein 聚合原理：跨场合聚合会**按构造**抬高特质—行为相关）。

注意这是**上限**而非预测：脚本里没有 LLM、没有记忆、没有地点偏好、没有日程，
这些都会增加个体间方差、从而**压低**实际观测到的相关。真实运行只会比表里更低。

### 11.3 已落地

**新增**

- `gaworld/personality/` —— `traits.py`（叶子，零 gaworld 依赖）、`anchors.py`（叶子）、
  `plugin.py`（唯一碰 CONFIG / 文件系统 / kernel 的模块）、`__init__.py`（对外只暴露 5 个函数）
- `gaworld/settings/personality.py` → `CONFIG["personality"]`
- `scripts/calibrate_big5.py`（离线标定，`--dry-run` / `--review`）
- `scripts/big5_effect_ceiling.py`、`scripts/big5_collinearity.py`（两道合入闸门）
- `tests/test_personality_big_five.py`（36 项）

**改动（每处都是一到数行）**

| 位置 | 改动 |
|---|---|
| `_action.py` | 加性 `trait_style_fit` 项 + `driver_labels` 加「性格倾向」+ `decision_noise` / 冲动绕过概率乘性调制 |
| `dynamic.py` | 中断阈值、自发冲动基率、共处搭话概率三处乘性调制；`_classify_personality` 与 `is_extrovert` 改为特质优先、关键词兜底 |
| `finance.py` | `_infer_wealth_drive` 末尾乘性调制（关键词读法保留，中文里的"佛系/上进"特质向量编码不了） |
| `_cognition.py` | 情绪传染补个人基准线回复项（D6） |
| 6 处 prompt | `generative_city_sim.py`×3、`goals.py`、`_news.py`、`_diary.py`——各 1 行 |

**通道门在数据层，不在调用点**：`record["channels"]` 跟着 agent 走，
`traits_of(agent, channel)` 对被关掉的通道直接返回中性值。
这是 `traits.py` / `anchors.py` 能保持零 gaworld 依赖的原因，也让每个调用点都是一行。
调制旋钮同理写在 `record["tuning"]` 里，所以 `output/traits/agent_traits.csv` 记录的
就是那次运行真正生效的参数，运行结果不可能和它自称的配置不一致。

### 11.4 P0 四道零成本闸门

| 闸门 | 状态 |
|---|---|
| ② 解析效应上限 | **PASS** —— 幅度 0.30，见 §11.2 |
| ③ 确定性 | **PASS** —— `residual()` 用 `hashlib` 派生的独立 `random.Random` 实例，不消耗全局流（有测试） |
| ④ 中性回退 | **PASS** —— `personality.enabled=false` 跑全量测试与基线**逐项一致**（1445 passed / 9 存量 failed，两边同一组）；`choose_action` 40 步序列在「无记录 / 全零记录 / 通道关闭」三种 agent 下完全相同 |
| ① 共线性诊断 | **FAIL（已跑，见 §11.6）** —— O/C/E 三维基本可由已有状态变量线性预测 |

关于附录 B 的告诫：`residual()` 里的 `random.Random(seed)` 是**函数内的局部实例**，
不是第二个全局 RNG，也不从全局流取数——
`test_residual_does_not_consume_the_global_rng` 就是钉这一条的。

### 11.6 标定跑完之后（2026-08-21）

51 人 × 5 维 × 3 次 = 765 次调用全部完成。**机制本身是健康的**：0 次解析失败，
三次重复的平均极差 0.25–0.37 分（1–7 量表），34–41/51 三次完全一致。
问题全部出在语料和转换上，而且是两个独立的问题。

#### 问题 A：转换把"不知道"变成了一个主张（已修）

`性格与情绪特征` 段落里根本没写到的维度，模型按设计回了 `stated:false`。
但原来的 `standardise()` 把这些人的中点分（4 分）**当成数据一起做 z 标准化**，
于是"我们不知道"变成了一个小的非零分：E 有 41 人落在 −0.32，A 有 44 人落在 −0.29，
C 有 29 人落在 −0.66。这些值会进决策循环，还会越过 `|z| ≥ 0.25` 的锚句门槛
——按渲染概率算，约三分之一的这类居民会被写上"你更喜欢小范围相处"之类的句子，
**而人物设定里从来没有这么说过**。这是本次实现里唯一一个会让系统凭空编造的缺陷。

改法：不再以样本均值为中心，而是**锚在量表中点 4 分上**——提示词里 4 分的定义就是
"两端都不明显，或材料中看不出来"，所以它是一个已知的中性点，不该从一份大半是弃权的
样本里去估。尺度改用**有证据者**偏离中点的均方根，这样弃权人数多少不再影响被描述者
之间的相对距离。于是未提及 ⇒ 恰好 0.0 ⇒ 无行为倾向、不渲染任何锚句。

原始打分全在 `output/traits/calibration_audit.csv` 里，所以这次重算**零成本**：
`python scripts/calibrate_big5.py --from-audit output/traits/calibration_audit.csv`。

#### 问题 B：语料覆盖率太低（未解，已如实标注）

| 维度 | 有证据的居民 |
|---|---|
| N 神经质 | 35/51 |
| C 尽责性 | 26/51 |
| O 开放性 | 17/51 |
| E 外向性 | 13/51 |
| A 宜人性 | 11/51 |

E 和 A 只有两成的居民能给出证据。这不是标定的问题，是 51 份人物设定本身
就没怎么描述这两个维度。

#### 闸门 ①：FAIL

这里还发现闸门脚本自己有个缺陷：它原来在全部 51 人上算 R²，
而 35 个被钉在 0 的居民没有方差可解释，会把重叠**压低**。改成
**只在有证据的子集上算、并报告调整后 R²**（5 个自变量对 11–35 个样本，
不调整的 R² 没法读）之后：

| 维度 | n | 调整 R² | 最强重叠 | 判定 |
|---|---|---|---|---|
| O 开放性 | 17 | **0.77** | mobility_intent r=+0.90 | FAIL |
| E 外向性 | 13 | **0.74** | voice_propensity r=+0.76 | FAIL |
| C 尽责性 | 26 | **0.53** | platform_dependence r=−0.67 | FAIL |
| N 神经质 | 35 | 0.19 | — | ok |
| A 宜人性 | 11 | 0.04 | — | ok |

机制不难理解：`risk_preference` / `voice_propensity` / `mobility_intent` 这些状态变量
本来就是从同一批 `性格与情绪特征` 文字里写出来的，模型读的是同一句话，
产出的自然是它们的一个改写。这正是 §1.4 预判的陷阱。

**裁定（D9）：照发 + 硬性标注。** 不做正交化（残差化会让分数不再是"开放性"，
而锚句描述的又还是开放性，两者对不上），也不砍维度（O 仍有约四分之一的方差
是已有变量解释不了的）。改为让标注**跟着数据走**：

- `scripts/big5_collinearity.py --annotate` 把不合格的维度写进
  `data/agents_big5.csv` 的 `redundant` 列；
- 插件把 `unstated` 与 `redundant` 一并读进 agent record、写进
  `output/traits/agent_traits.csv`、放进 recorder 载荷；
- **每次运行启动时都会打印这两条警告**，不是留在一份没人打开的报告里。

结论上的约束：**O / C / E 三维的效应不得单独立论**，任何相关结果必须与
重叠变量一并报告。真正的修法是补写人物设定里的独立人格材料（顺带解决覆盖率），
但那要重写语料并重新标定。

### 11.5 还没做

1. **补写人物设定里的人格材料**，解决 §11.6 的问题 B 与闸门 ① 的 FAIL。
   这是唯一的真修法；改完需要重新标定并重跑 `--annotate`。
2. **Track F**：整套 ≈2.8 万次调用 / ≈7 小时。在此之前 scorecard 上应标 UNVERIFIED。
3. **探针 battery 的 20 个情景**（§7.10）尚未落地。
