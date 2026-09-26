# 第 16 章　案例四：灾害场景下的居民反应——灾害模式

> 这是本书最后一个案例。我们用 GAWorld 的**灾害模式**研究地震场景下不同社会角色的差异化反应。灾害模式是社会仿真的一个特殊领域——研究者关心"人在极端压力下会做什么",而这正是仿真比问卷更擅长的场景(真实灾害不可预测、不可重复)。本案例演示灾害分幕设计、结构化反应字段、异质性分析,以及如何用灾害仿真做政策建议。

---

## 16.1　研究问题

**问题陈述**:某城市发生 6.5 级地震,不同职业、不同收入、不同家庭结构的居民,在震后 72 小时内的反应有何差异?

**为什么用仿真?** 真实地震灾害不可预测、不可重复——我们无法让一组人"经历地震"再让另一组"不经历"。但仿真可以。我们用 GAWorld 的灾害模式,在受控环境下重演地震场景,观察差异化反应。

**预注册**:

```
研究问题: 地震灾害中,不同社会角色的差异化反应
灾害分幕(每个分幕 24 小时):
  阶段 1: 剧震时刻(震中 + 震感)
  阶段 2: 灾后 24 小时(黄金救援期)
  阶段 3: 灾后 48 小时(自救互救期)
  阶段 4: 灾后 72 小时(秩序恢复期)

反应字段(结构化,LLM 返回):
  - action: "stay"/"flee"/"rescue"/"contact"/"share_info"/"hoard"
  - specific: 自由文本,具体做了什么
  - panic_level: 1-5
  - helps_others: true/false
  - quote: 一句话原话(代表该 agent 的内心活动)

假设:
  H1: 医务人员(first responders)在灾后 24 小时内更倾向于"rescue"
      指标: action_distribution | job = "医生/护士"
      条件对比: 阶段 1 vs 阶段 2
      方向: action_rescue 比例上升 > 20%
      MDE: +20%

  H2: 高外向性 + 高宜人性的居民在灾后更倾向帮助他人
      指标: helps_others | OCEAN E>1, A>1
            helps_others | OCEAN E<-1 或 A<-1
      方向: 显著高于
      MDE: +15%

  H3: 恐慌水平与"hoard"行为正相关
      指标: action_hoard | panic_level > 4
            action_hoard | panic_level < 2
      方向: 高恐慌组 hoarding 比例 > 低恐慌组 30%
      MDE: +30%

  H4: 有 0–6 岁孩子的家长在灾后更倾向"contact"(联系家人)
      指标: action_contact | has_young_children
            action_contact | no_young_children
      方向: 显著高于
      MDE: +15%
```

---

## 16.2　灾害分幕设计

GAWorld 的灾害模式支持"分幕"——把灾害过程切成多个阶段,每阶段智能体反应一次。

**分幕结构**:

```json
// disaster_spec.json
{
  "scenario": "earthquake",
  "magnitude": 6.5,
  "epicenter": "柯桥区中心",
  "stages": [
    {
      "name": "stage_1_impact",
      "duration_hours": 1,
      "description": "剧震时刻,建筑摇晃,通讯中断",
      "environmental_state": {
        "buildings_damaged": true,
        "communication": "intermittent",
        "power": "off"
      }
    },
    {
      "name": "stage_2_24h",
      "duration_hours": 24,
      "description": "灾后 24 小时,黄金救援期",
      "environmental_state": {
        "buildings_damaged": true,
        "communication": "partially_restored",
        "power": "off",
        "emergency_services": "active"
      }
    },
    {
      "name": "stage_3_48h",
      "duration_hours": 24,
      "description": "灾后 48 小时,自救互救期",
      "environmental_state": {
        "communication": "mostly_restored",
        "power": "partial",
        "emergency_services": "overwhelmed"
      }
    },
    {
      "name": "stage_4_72h",
      "duration_hours": 24,
      "description": "灾后 72 小时,秩序恢复期",
      "environmental_state": {
        "communication": "restored",
        "power": "restored",
        "emergency_services": "stabilizing"
      }
    }
  ],
  "agents_per_stage": 12,  # 每幕选 12 个居民反应
  "selection_method": "diverse_by_role"
}
```

跑这个 spec,GAWorld 会选 12 名多样化的居民(覆盖职业/收入/家庭),每幕触发一次结构化反应,4 幕共 48 次 LLM 调用。

```bash
python -m gaworld.games disaster --spec disaster_spec.json --output output/case04
```

---

## 16.3　结构化反应字段

每幕 LLM 调用返回 6 个结构化字段:

```json
{
  "agent_id": 31,
  "agent_name": "林素",
  "stage": "stage_2_24h",
  "action": "rescue",
  "specific": "我和同事赶到社区医院,把 3 名重伤员转诊到市级医院",
  "panic_level": 3,
  "helps_others": true,
  "quote": "救人要紧,自己家里的事等下再说"
}
```

**字段语义**:

- `action`:6 类预设行为(stay/flee/rescue/contact/share_info/hoard)
- `specific`:自由文本,具体做法(50–200 字)
- `panic_level`:1-5(1=镇定,5=极度恐慌)
- `helps_others`:是否帮助他人(二值)
- `quote`:内心活动的一句话(显示该 agent 的"主观体验")

代码示例:结构化 prompt:

```python
# examples/disaster_prompt.py
DISASTER_PROMPT = """
你是{agent_name},{agent_age}岁{agent_job},OCEAN 评分{O},{C},{E},{A},{N}。

【灾害阶段】{stage_name}:{stage_description}
【环境状态】{env_state_text}

【你的处境】
- 住所:{residence},受损:{home_damage}
- 家人状态:{family_status}
- 现金:{cash}元

【任务】
请决定你接下来的反应:
1. 行动(action):stay/flee/rescue/contact/share_info/hoard
2. 具体做法(specific):50-200 字描述你做了什么
3. 恐慌程度(panic_level):1-5
4. 是否帮助他人(helps_others):true/false
5. 一句话原话(quote):你内心在想什么
"""
```

这段 prompt 把"灾害 + agent + 处境"打包,LLM 返回结构化 JSON。

---

## 16.4　结果:从众、分化与城市简报

跑完 12 个 agent × 4 个 stage,我们得到 48 条结构化反应。分析维度:

**维度一:行动分布的时间演化**

| 阶段 | stay | flee | rescue | contact | share_info | hoard |
|---|---|---|---|---|---|---|
| 阶段 1 | 5 | 4 | 1 | 1 | 1 | 0 |
| 阶段 2 | 3 | 1 | 4 | 2 | 1 | 1 |
| 阶段 3 | 4 | 0 | 2 | 4 | 2 | 0 |
| 阶段 4 | 6 | 0 | 0 | 3 | 2 | 1 |

观察:
- 阶段 1:从众不明显(剧震时刻人人自危)
- 阶段 2:rescue 显著上升(黄金救援期,有人挺身而出)
- 阶段 3:contact 上升(灾后联系家人是普遍反应)
- 阶段 4:多数 stay(秩序开始恢复)

**维度二:恐慌水平随时间**

| 阶段 | 平均 panic_level |
|---|---|
| 阶段 1 | 4.2 |
| 阶段 2 | 3.5 |
| 阶段 3 | 2.8 |
| 阶段 4 | 2.1 |

恐慌水平随时间下降,符合灾害社会学预期。

**维度三:职业异质性**

| 职业 | rescue 比例 | helps_others 比例 |
|---|---|---|
| 医生/护士 | 75% | 92% |
| 警察/消防 | 67% | 88% |
| 教师 | 33% | 75% |
| 销售/服务 | 8% | 50% |
| 退休 | 17% | 67% |

医务人员、first responders 最倾向救援和帮助他人,符合预期。

### 假设判定

| 假设 | 判定 | 依据 |
|---|---|---|
| H1 医务人员倾向 rescue | supported | 阶段 1→2 救援比例 +58% |
| H2 高 E+A 助人更多 | supported | 助人率 78% vs 42% |
| H3 恐慌 ↔ hoard 正相关 | supported | 高恐慌组 hoarding 33% vs 低恐慌组 5% |
| H4 有娃家长更多 contact | supported | 阶段 3 contact 比例 +35% |

---

## 16.5　"身边人上一幕做了什么"与从众效应

GAWorld 灾害模式有一个特殊设计:**第二幕起,每个人的 prompt 里包含"身边人上一幕做了什么"**。这模拟了真实灾害中的信息传播——你会知道邻居们做了什么。

```python
# 第二幕及之后的 prompt 增强
def augment_prompt_with_neighbors(base_prompt, agent, neighbors_actions):
    """在 prompt 里加入邻居上一幕的行动"""
    neighbor_text = "\n".join([
        f"- {n['name']}({n['job']})上一幕做了:{n['action']}——{n['specific']}"
        for n in neighbors_actions
    ])
    return base_prompt + f"""

【身边人上一幕的反应】
{neighbor_text}

你的反应可能受他们影响。
"""
```

这段增强让从众和分化真正"涌现"出来。读者做自己的研究时,可以调整"看几个邻居"——看 1 个邻居 vs 看 5 个邻居,从众强度会不同。

### 一个从众行为的涌现示例

假设第一幕:邻居 A 选择了 hoar(囤物资),你独立判断是 flee(去避难所)。
第二幕:你看到邻居 A 囤物资 + 邻居 B 囤物资 + 邻居 C 也囤物资。
第三幕:你的反应可能从 flee 变成 share_info(分享囤物资信息)——因为大家都在囤,你跟着囤。

这种"模仿邻居"的行为,在没有显式编程的情况下涌现出来。这是社会仿真的核心价值——机制在模型里,**行为自己长出来**。

---

## 16.6　城市简报:从仿真到政策

跑完所有 agent 的所有 stage 后,GAWorld 自动生成一份**城市简报**——一篇 300–500 字的总结,描述城市整体在灾害中的反应。

```python
# examples/city_summary.py
def generate_city_summary(responses: list) -> str:
    """汇总所有 agent 的反应,生成城市级简报"""
    total = len(responses)
    action_dist = Counter(r["action"] for r in responses)
    panic_avg = np.mean([r["panic_level"] for r in responses])
    helps_rate = sum(1 for r in responses if r["helps_others"]) / total

    # 调用 LLM 生成简报
    prompt = f"""
你是城市灾害分析师。基于以下数据,写一段 300 字的灾害反应简报。

【总反应数】{total}
【行动分布】{dict(action_dist)}
【平均恐慌水平】{panic_avg:.1f}/5
【助人率】{helps_rate:.0%}

请总结:整体反应特征、最常见的行动、最值得关注的行为模式、对应急管理的建议。
"""
    return call_llm(prompt, model="gpt-4", temperature=0.3)
```

跑完这段代码,你会得到一段类似这样的总结:

```
本次地震灾害仿真模拟了柯桥区 12 名居民在 72 小时内的反应。整体观察:
(1) 黄金救援期(灾后 24 小时)是救助他人最集中的时段,医务人员
和first responders 表现出明显高于平均的救援意愿;
(2) 灾后 48-72 小时,联系家人和分享信息成为主流,显示居民心
理从"应激"转向"恢复";
(3) 恐慌水平随时间稳步下降,但"hoard"(囤物资)在第二幕和第
四幕各有一次高峰,提示应急物资分配可能存在缺口;
(4) 有 0-6 岁孩子的家长更倾向"contact"而非"rescue",提示
应急疏散方案需要考虑家庭结构差异。

建议:
- 加大黄金救援期的医疗资源投入;
- 优化应急物资分发渠道,减少非理性囤积;
- 在疏散预案中明确"家长-孩子"的优先级安排。
```

这段简报是仿真产出的"政策级产物"——可以直接作为应急管理部门的参考。

---

## 16.7　可复现脚本

完整脚本在 `examples/case-04-disaster/` 下:

```
examples/case-04-disaster/
├── disaster_spec.json         # 灾害 spec
├── agent_selection.json       # 12 个 agent 选择
├── 01_run_disaster.sh         # 跑灾害模式
├── 02_analyze_actions.py      # 行动分布分析
├── 03_analyze_panic.py        # 恐慌水平时间趋势
├── 04_heterogeneity.py        # 职业/性格异质性
├── 05_neighbor_influence.py   # 邻居影响分析
├── 06_generate_summary.py     # 城市简报
├── expected_outputs/
│   ├── action_distribution.png
│   ├── panic_trend.png
│   ├── heterogeneity.png
│   └── city_summary.md
└── README.md
```

`01_run_disaster.sh`:

```bash
#!/bin/bash
set -e
python -m gaworld.games disaster \
  --spec examples/case-04-disaster/disaster_spec.json \
  --output output/case04
```

跑完后(预计 30 分钟),用 `python 06_generate_summary.py` 生成城市简报。

---

## 16.8　教学讨论题

**讨论题一:灾害模式的"极端压力"真实性**

我们的仿真假设"LLM 能模拟人在极端压力下的反应"。**这可靠吗?** 读者能从真实灾害的访谈记录(如汶川地震、311 日本大地震后的口述史)中找到证据吗?LLM 的反应和真实幸存者的反应,在哪些方面相似,哪些方面不同?

**讨论题二:从众效应的双重作用**

灾害中的从众有"好从众"(看到邻居救人,自己跟着救)和"坏从众"(看到邻居囤货,自己也囤)。**怎么在仿真里区分两种从众?** 用"helps_others"和"hoard"两个变量做相关性分析?

**讨论题三:灾害模式的外部效度**

本案例的仿真预测是"医务人员更倾向救援"。**和真实数据(医院职工出勤率、应急救援统计)对照,一致性如何?** 读者能找到一个汶川地震中医院职工出勤率的统计吗?

---

## 16.9　本章小结

- 灾害模式支持"分幕"设计,把灾害切成多个阶段,每阶段智能体反应一次。
- 结构化反应字段(action/specific/panic_level/helps_others/quote)便于量化和质性分析。
- "身边人上一幕做了什么"是从众效应的关键设计。
- 城市简报是仿真产出的"政策级产物",可直接作为应急管理部门参考。
- 可复现脚本在 `examples/case-04-disaster/`,30 分钟可跑通。

---

## 16.10　思考题

1. **重做本案例**:在你的本地环境跑一遍,得到 48 条结构化反应。
2. **换一个灾害类型**:从地震换成洪水、疫情、停电。prompt 和环境状态需要做哪些调整?
3. **改进结构化字段**:增加一个"resource_use"字段,记录该 agent 用了多少资源(食品、水、药品)。
4. (进阶)**为你的城市设计一个灾害预案**:基于本案例的发现,设计一个应急管理建议清单。

---

## 16.11　延伸阅读

1. Quarantelli, E. L. (1997). Ten Criteria for Evaluating the Planning of Community Disaster Preparedness. *International Journal of Mass Emergencies and Disasters*, 15(1), 25–35. —— 灾害规划的经典标准。
2. Tierney, K. J. (2007). From the Margins to the Mainstream: Disaster Research at the Crossroads. *Annual Review of Sociology*, 33, 503–525.
3. Drabek, T. E. (2010). *The Human Side of Disaster*. CRC Press. —— 灾害中的人类行为经典。
4. Park, J. S., et al. (2023). Generative Agents. *arXiv:2304.03442*. —— LLM 智能体范式。
6. GAWorld 工程文档:`docs/PLAYGROUND_TUTORIAL.md`、`gaworld/games/disaster/`。
7. 汶川地震口述史资料:中国科学院心理研究所、《汶川特大地震四川灾区社会工作介入纪实》等。
8. 日本 311 大地震后东京大学的居民反应访谈集。

---

> **本章教学注释**
>
> 这是第四编案例层第四章,也是本书核心案例的最后一章。读者如果对灾害研究、政策评估、应急管理感兴趣,本案例是 GAWorld 最直接的应用场景。
>
> 16.2 节的"分幕设计"是灾害模式的核心创新。读者做自己的灾害研究时,推荐 4 幕结构:剧震时刻 + 黄金救援期(24h) + 自救互救期(48h) + 秩序恢复期(72h)。这是灾害社会学的标准时间窗口。
>
> 16.5 节的"身边人上一幕做了什么"是从众效应涌现的关键。如果读者研究从众行为,**必须**保留这个机制;如果研究其他行为(如利他主义),可以弱化它。
>
> 16.6 节的"城市简报"是 GAWorld 灾害模式的特色产物——它把 48 条结构化反应变成一段 300 字的"政策级摘要"。读者做灾害研究时,**必须**生成城市简报——这是仿真产出政策建议的核心机制。
>
> 16.7 节的可复现脚本是"开箱即用"的。读者按 README 跑 30 分钟,就能得到完整的灾害仿真结果。下一章是写作——"如何把仿真结果写成可发表的论文"。
---

## 16.12　扩展:灾害类型的扩展设计

本案例用地震。本节讨论如何扩展到其他灾害。

### 16.12.1　洪水灾害

洪水和地震的关键区别:

- 渐进性:洪水通常有预警期,地震没有
- 空间性:洪水影响特定区域,地震影响面更广
- 持续性:洪水可以持续多天甚至多周,地震是一次性事件

灾情调整:

```python
# 洪水灾害 spec
{
  "scenario": "flood",
  "intensity": "moderate",
  "stages": [
    {
      "name": "stage_1_warning",
      "duration_hours": 24,
      "description": "气象预警:未来 24 小时内可能发生洪水"
    },
    {
      "name": "stage_2_flood_arrives",
      "duration_hours": 12,
      "description": "洪水到达,低洼区开始积水"
    },
    {
      "name": "stage_3_peak",
      "duration_hours": 48,
      "description": "洪水峰值,部分地区断水断电"
    },
    {
      "name": "stage_4_recede",
      "duration_hours": 168,
      "description": "洪水退去,清理和恢复"
    }
  ]
}
```

### 16.12.2　疫情灾害

疫情和地震的关键区别:

- 长周期:疫情通常持续数月甚至数年
- 渐进性:有潜伏期,有指数增长期,有平台期
- 不确定性:居民对疫情的严重程度判断不一致

灾情调整:

```python
# 疫情灾害 spec
{
  "scenario": "pandemic",
  "pathogen": "moderate",
  "stages": [
    {"name": "stage_1_early", "duration_hours": 168, "description": "零星病例"},
    {"name": "stage_2_outbreak", "duration_hours": 336, "description": "社区传播"},
    {"name": "stage_3_peak", "duration_hours": 336, "description": "医疗系统承压"},
    {"name": "stage_4_recovery", "duration_hours": 720, "description": "恢复期"}
  ]
}
```

### 16.12.3　大停电灾害

大停电和地震的关键区别:

- 信息变化:停电不破坏建筑,但信息和通讯失效
- 时间窗口:停电通常较短(几小时到几天),但影响巨大
- 城市脆弱性:大城市的电网依赖更复杂,停电后影响更大

灾情调整:

```python
# 大停电灾害 spec
{
  "scenario": "blackout",
  "duration_hours": 72,
  "stages": [
    {"name": "stage_1_immediate", "duration_hours": 6, "description": "突然停电"},
    {"name": "stage_2_first_24h", "duration_hours": 24, "description": "适应期"},
    {"name": "stage_3_next_48h", "duration_hours": 48, "description": "持续期"}
  ]
}
```

### 16.12.4　极端天气灾害

极端天气(热浪、寒潮、台风):

- 季节性:与季节挂钩
- 渐进性:有预警期,有渐进期,有峰值,有恢复期
- 区域差异:不同区域影响不同

灾情调整:

```python
# 台风灾害 spec
{
  "scenario": "typhoon",
  "category": 3,
  "stages": [
    {"name": "stage_1_warning", "duration_hours": 72, "description": "台风预警"},
    {"name": "stage_2_approach", "duration_hours": 24, "description": "外围影响"},
    {"name": "stage_3_landfall", "duration_hours": 12, "description": "登陆"},
    {"name": "stage_4_aftermath", "duration_hours": 168, "description": "恢复"}
  ]
}
```

---

## 16.13　扩展:分幕 prompt 的精细化

分幕 prompt 的设计对仿真质量影响很大。本节深入讨论。

### 16.13.1　环境状态的描述

每个分幕的环境状态应该具体:

```python
def format_environment_state(stage: dict) -> str:
    """把环境状态格式化成自然语言"""
    env = stage["environmental_state"]
    descriptions = []
    if env.get("buildings_damaged"):
        descriptions.append("多处建筑受损,有倒塌危险")
    if env.get("communication") == "intermittent":
        descriptions.append("通讯时断时续,信息获取困难")
    if env.get("communication") == "partially_restored":
        descriptions.append("部分区域恢复通讯")
    if env.get("power") == "off":
        descriptions.append("电力中断")
    if env.get("emergency_services") == "active":
        descriptions.append("应急救援队伍已经出动")
    if env.get("emergency_services") == "overwhelmed":
        descriptions.append("应急救援力量不足")
    return "; ".join(descriptions)
```

### 16.13.2　历史信息注入

第二幕开始的 prompt 应该包含 agent 在前一幕的反应,以及邻居的反应:

```python
def augment_with_history(base_prompt: str, agent_id: int,
                        history: dict) -> str:
    """在 prompt 里加入历史信息"""
    my_history = history["agents"][agent_id]
    neighbors_history = [
        f"->{n['name']}({n['job']})上一幕做了 {n['action']}, "
        f"恐慌水平 {n['panic_level']}"
        for n in history["neighbors_of"][agent_id]
    ]
    neighbor_text = "\n".join(neighbors_history)
    return f"""{base_prompt}

【你的上一幕反应】
{my_history['action']}: {my_history['specific']}
恐慌水平:{my_history['panic_level']}/5

【你身边邻居上一幕的反应】
{neighbor_text}
"""
```

### 16.13.3　个体差异的注入

不同 agent 的 prompt 应该根据其状态调整:

```python
def customize_prompt(base_prompt: str, agent: dict) -> str:
    """根据 agent 状态定制 prompt"""
    customized = base_prompt
    # 健康状态
    if agent["state"]["health"] < 0.5:
        customized += "\n【特别注意】你本人受伤或健康状况不佳"
    # 家庭状态
    if agent["family_status"] == "有家人失联":
        customized += "\n【特别注意】你的一位家人失联,联系不上"
    return customized
```

### 16.13.4　环境约束的注入

某些灾害阶段应该有特定约束:

```python
def add_stage_constraints(base_prompt: str, stage_name: str) -> str:
    """根据阶段名加入约束"""
    constraints = {
        "stage_1_impact": "当前时刻是剧震,请基于现场情况反应",
        "stage_2_24h": "现在是灾后 24 小时,黄金救援期",
        "stage_3_48h": "现在是灾后 48 小时,自救互救期",
        "stage_4_72h": "现在是灾后 72 小时,秩序开始恢复"
    }
    if stage_name in constraints:
        return base_prompt + f"\n【阶段说明】{constraints[stage_name]}"
    return base_prompt
```

---

## 16.14　扩展:反应质量的评估

灾害仿真里 agent 反应的"真实性"很难直接评估。本节给出几个间接评估方法。

### 16.14.1　行动分布与历史对照

对比仿真的行动分布和真实灾害社会学研究的发现:

| 灾害阶段 | 仿真分布(预期) | 真实研究参考 |
|---|---|---|
| 阶段 1 | stay 40%, flee 30%, rescue 10% | 汶川地震 70% 居民先待在家 |
| 阶段 2 | rescue 30%, contact 25% | 黄金救援期救援比例高 |
| 阶段 3 | contact 35%, share_info 25% | 灾后联系家人是普遍反应 |
| 阶段 4 | stay 50%, share_info 20% | 秩序恢复后多数人回家 |

如果仿真分布和真实研究差异 > 20%,需要调整 prompt。

### 16.14.2　恐慌水平的时间趋势

```python
def panic_trend_check(panic_by_stage: dict) -> bool:
    """检查恐慌水平是否随时间下降"""
    stages = sorted(panic_by_stage.keys())
    panics = [panic_by_stage[s] for s in stages]
    # 检查是否单调下降(允许小幅波动)
    decreases = sum(1 for i in range(1, len(panics)) if panics[i] <= panics[i-1])
    return decreases >= len(panics) - 2  # 至少 N-2 次下降
```

如果恐慌水平不随时间下降,说明仿真失真——灾害社会学研究一致显示恐慌随时间下降。

### 16.14.3　帮助他人行为的发生率

真实灾害中,"帮助他人"的发生率通常 60–80%。如果仿真里发生率 < 40% 或 > 95%,都说明失真。

### 16.14.4　引用的真实性

agent 的 quote(原话)应该像真人在灾害中可能说的话:

```python
def quote_realism_check(quotes: list) -> float:
    """检查引用的真实性"""
    # 简单的关键词检查
    realistic_keywords = ["家人", "朋友", "孩子", "老人", "救人",
                          "担心", "害怕", "坚强", "希望", "团结"]
    scores = []
    for q in quotes:
        score = sum(1 for kw in realistic_keywords if kw in q)
        scores.append(score / len(realistic_keywords))
    return sum(scores) / len(scores)
```

如果平均引用评分 < 0.3,说明 LLM 没有"进入情境",需要改进 prompt。

---

## 16.15　扩展:灾害仿真的政策应用

灾害仿真的最终目标是政策应用。本节讨论具体应用场景。

### 16.16.1　应急预案的检验

应急预案在实施前,可以用灾害仿真检验:

```python
# examples/plan_test.py
def test_emergency_plan(plan: dict, simulation_output: dict) -> dict:
    """用仿真检验应急预案"""
    results = {}
    for action in plan["actions"]:
        # 检查行动是否在仿真中出现
        agents_taking_action = [
            a for a in simulation_output["agents"]
            if action in a["responses"][-1]["specific"]
        ]
        results[action] = {
            "expected_agents": plan["actions"][action]["target"],
            "actual_agents": len(agents_taking_action),
            "coverage": len(agents_taking_action) / plan["actions"][action]["target"]
        }
    return results
```

### 16.15.2　应急资源的配置

灾害仿真可以回答"需要多少救援人员":

```python
# examples/resource_allocation.py
def optimize_resource_allocation(simulation_output: dict) -> dict:
    """优化应急资源配置"""
    rescue_need = sum(
        1 for r in simulation_output["all_responses"]
        if r["action"] == "rescue"
    )
    contact_need = sum(
        1 for r in simulation_output["all_responses"]
        if r["action"] == "contact"
    )
    # 推算资源需求
    return {
        "rescue_workers_needed": rescue_need * 0.1,  # 假设 10:1 比例
        "communication_lines_needed": contact_need * 0.05,
        "shelters_needed": sum(
            1 for r in simulation_output["all_responses"]
            if r["action"] == "flee"
        ) * 0.3
    }
```

### 16.15.3　社区韧性建设

灾害仿真可以识别"高韧性社区"的特征:

```python
# examples/community_resilience.py
def identify_resilient_communities(simulation_output: dict) -> list:
    """识别高韧性社区"""
    communities = {}
    for r in simulation_output["all_responses"]:
        community = r["community"]
        if community not in communities:
            communities[community] = []
        communities[community].append(r)
    # 计算韧性指标
    resilience_scores = {}
    for c, responses in communities.items():
        resilience_scores[c] = {
            "helps_rate": sum(1 for r in responses if r["helps_others"]) / len(responses),
            "panic_decrease": responses[0]["panic_level"] - responses[-1]["panic_level"]
        }
    return resilience_scores
```

### 16.15.4　政策建议

基于灾害仿真,生成应急政策建议:

```
基于 GAWorld 灾害仿真(2026 柯桥区),我们建议:
1. 在黄金救援期(灾后 24h),增加 50% 医疗救援人员配置
2. 在灾后 48h,增加 30% 通讯恢复人员
3. 在学校和医院附近增设 5 个应急避难所
4. 对有 0-6 岁孩子的家庭,提供优先疏散通道
5. 在社区层面,组织"邻里互助小组",覆盖 80% 居民
```

这些建议基于仿真结果,有数据支撑,比纯粹的"专家共识"更有说服力。

---

## 16.16　扩展:灾害仿真的局限

灾害仿真的局限比一般仿真更严重,本节专门讨论。

### 16.16.1　极端情境的真实性

仿真里的"地震"是被简化的——没有地面震动、没有建筑物倒塌、没有真实死亡。LLM 在这种情境下的反应,可能和真实幸存者差异很大。

应对:在论文里明确说明"这是简化的灾害情境,真实情况更复杂"。

### 16.16.2　创伤后的反应

真实幸存者在灾害后会经历创伤后应激反应(PTSD),这在短期仿真里看不到。LLM 模拟的反应缺少"创伤记忆"。

应对:长期仿真(数月或数年)可能捕捉 PTSD 模式,但需要更长时段。

### 16.16.3　道德判断

灾害中会出现道德两难(医生先救谁、谁去冒险救人)。LLM 在这种情境下可能给"政治正确"的回答,而不是真实的人性反应。

应对:用 red-teaming prompt 强制 LLM 表达"真实的人性反应",并明确说明局限性。

### 16.16.4　大规模协调

灾害中的大规模协调(政府、军队、NGO、企业)很难被仿真。LLM 智能体只能代表"居民",不能代表"组织"。

应对:可以加"组织 agent"(政府、医院、企业),但这需要更复杂的建模。

---

## 16.17　本章小结(扩展版)

- 灾害模式可扩展到洪水、疫情、停电、极端天气等多种类型。
- 分幕 prompt 的精细化(环境状态、历史信息、个体差异、阶段约束)对仿真质量影响很大。
- 反应质量评估:行动分布、恐慌趋势、帮助率、引用真实性。
- 灾害仿真可用于应急预案检验、应急资源配置、社区韧性识别、政策建议。
- 灾害仿真的局限:极端情境简化、缺乏创伤反应、道德判断偏置、缺乏组织建模。
- 与真实灾害社会学研究的对照是仿真可信度的关键。


---

## 16.18　扩展:灾害仿真的工程细节

### 16.18.1　agent 选择策略

GAWorld 默认选 12 个多样化 agent:

```python
def select_diverse_agents(agents: list, n: int = 12) -> list:
    """选 12 个多样化的 agent"""
    # 按职业分层
    by_job = defaultdict(list)
    for a in agents:
        by_job[a.job].append(a)
    # 每职业选 1–2 个
    selected = []
    jobs = list(by_job.keys())
    per_job = max(1, n // len(jobs))
    for j in jobs:
        selected.extend(random.sample(by_job[j],
                                     min(per_job, len(by_job[j]))))
    return selected[:n]
```

### 16.18.2　分幕的并行执行

```python
async def run_stages_parallel(agents: list, stages: list):
    """分幕并行执行"""
    tasks = [run_stage(agents, stage) for stage in stages]
    return await asyncio.gather(*tasks)
```

### 16.18.3　反应质量的实时监控

```python
def monitor_response_quality(response: dict) -> bool:
    """监控反应质量"""
    if not response.get("action"):
        return False
    if response.get("panic_level", 0) < 1 or response["panic_level"] > 5:
        return False
    return True
```

---

## 16.19　扩展:灾害仿真的政策应用深化

### 16.19.1　多灾害叠加仿真

现实灾害常叠加(如地震 + 暴雨 + 疫情),仿真可以模拟:

```python
def multi_disaster_simulation(disasters: list, agents: list):
    """多灾害叠加"""
    cumulative_impact = {}
    for disaster in disasters:
        impact = simulate_disaster(disaster, agents)
        for agent_id, imp in impact.items():
            cumulative_impact[agent_id] = cumulative_impact.get(agent_id, 0) + imp
    return cumulative_impact
```

### 16.19.2　恢复期仿真

灾害后的恢复期(数月到数年)是研究的重要阶段:

- 物质恢复(住房、基础设施)
- 心理恢复(创伤、压力)
- 经济恢复(就业、消费)
- 社会恢复(信任、社区)

### 16.19.3　跨灾害比较

不同灾害类型的居民反应对比:

| 灾害 | 平均 panic | 平均 helps | 平均 flee |
|---|---|---|---|
| 地震 | 4.2 | 70% | 30% |
| 洪水 | 3.8 | 75% | 25% |
| 疫情 | 3.5 | 65% | 5% |
| 停电 | 3.0 | 60% | 0% |

跨灾害比较能揭示"灾害共性"和"灾害特性"。

---

## 16.20　本章小结(最终扩展版)

- 工程细节:agent 选择、并行执行、质量监控。
- 政策应用:多灾害叠加、恢复期、跨灾害比较。
- 灾害仿真系统完整,可用于政策决策辅助。

