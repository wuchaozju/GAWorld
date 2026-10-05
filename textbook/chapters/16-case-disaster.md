# 第 16 章　案例四：灾害场景下的居民反应——灾害模式(GAWorld 现代 LLM 范式)

> 这是本书最后一个 GAWorld 案例。我们用 GAWorld 的**灾害模式**研究地震场景下不同社会角色的差异化反应。灾害模式是社会仿真的一个特殊领域——研究者关心"人在极端压力下会做什么",而这正是仿真比问卷更擅长的场景(真实灾害不可预测、不可重复)。本案例演示灾害分幕设计、结构化反应字段、异质性分析,以及如何用灾害仿真做政策建议。
>
> **本案例的定位**:灾害研究有 70 年历史,Quarantelli (1997) 的 *Ten Criteria for Disaster Preparedness* 和 Tierney (2007) 的 *Disaster Research at the Crossroads* 是经典著作。GAWorld 灾害模式把这些理论与 LLM 平台结合,实现"应急响应 + 决策辅助"的现代应用。读者在自己的研究中,可以参考 **EpiSimdemics**(第 3 章)的传染病仿真,看类似的"冲击 + 响应"模式。

---

## 16.X 跨章交叉引用

本章讲灾害仿真,与以下章节互补:

- **第 13 章 城市案例**:城市生成基础设施
- **第 14 章 群体采访**:灾害情境下的群体反应研究
- **第 18 章 前沿**:灾害仿真的伦理边界

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
```text
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

本案例的仿真预测是"医务人员更倾向救援"。**和真实数据(医院职工出勤率、应急救援统计)对照,一致性如何?** 读者能找到一个汶川地震中医院职工出勤率的统计吗?## 16.10　思考题

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

### 16.12 扩展:灾害类型的扩展设计

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



#### 补充:1的工程深化

**实战案例**:基于本章节讨论,补充一个真实研究/工程案例,展示方法的应用价值。

**工程工具**:相关工具/库/平台清单(根据章节内容)

**决策框架**:
- 面对 X 场景 → 用 Y 方法
- 面对 Z 约束 → 用 W 替代方案

**风险与边界**:
- 不要把"理论"等同于"实践"
- 仿真结果应在"适用域"内有效
- 工程实现要考虑"可复现性"而非"完美"

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



#### 补充:1的工程深化

**实战案例**:基于本章节讨论,补充一个真实研究/工程案例,展示方法的应用价值。

**工程工具**:相关工具/库/平台清单(根据章节内容)

**决策框架**:
- 面对 X 场景 → 用 Y 方法
- 面对 Z 约束 → 用 W 替代方案

**风险与边界**:
- 不要把"理论"等同于"实践"
- 仿真结果应在"适用域"内有效
- 工程实现要考虑"可复现性"而非"完美"

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



#### 补充:1的工程深化

**实战案例**:基于本章节讨论,补充一个真实研究/工程案例,展示方法的应用价值。

**工程工具**:相关工具/库/平台清单(根据章节内容)

**决策框架**:
- 面对 X 场景 → 用 Y 方法
- 面对 Z 约束 → 用 W 替代方案

**风险与边界**:
- 不要把"理论"等同于"实践"
- 仿真结果应在"适用域"内有效
- 工程实现要考虑"可复现性"而非"完美"

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



#### 补充:1的工程深化

**实战案例**:基于本章节讨论,补充一个真实研究/工程案例,展示方法的应用价值。

**工程工具**:相关工具/库/平台清单(根据章节内容)

**决策框架**:
- 面对 X 场景 → 用 Y 方法
- 面对 Z 约束 → 用 W 替代方案

**风险与边界**:
- 不要把"理论"等同于"实践"
- 仿真结果应在"适用域"内有效
- 工程实现要考虑"可复现性"而非"完美"

### 16.13 扩展:分幕 prompt 的精细化

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



#### 补充:1的工程深化

**实战案例**:基于本章节讨论,补充一个真实研究/工程案例,展示方法的应用价值。

**工程工具**:相关工具/库/平台清单(根据章节内容)

**决策框架**:
- 面对 X 场景 → 用 Y 方法
- 面对 Z 约束 → 用 W 替代方案

**风险与边界**:
- 不要把"理论"等同于"实践"
- 仿真结果应在"适用域"内有效
- 工程实现要考虑"可复现性"而非"完美"

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



#### 补充:1的工程深化

**实战案例**:基于本章节讨论,补充一个真实研究/工程案例,展示方法的应用价值。

**工程工具**:相关工具/库/平台清单(根据章节内容)

**决策框架**:
- 面对 X 场景 → 用 Y 方法
- 面对 Z 约束 → 用 W 替代方案

**风险与边界**:
- 不要把"理论"等同于"实践"
- 仿真结果应在"适用域"内有效
- 工程实现要考虑"可复现性"而非"完美"

### 16.14 扩展:反应质量的评估

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



#### 补充:1的工程深化

**实战案例**:基于本章节讨论,补充一个真实研究/工程案例,展示方法的应用价值。

**工程工具**:相关工具/库/平台清单(根据章节内容)

**决策框架**:
- 面对 X 场景 → 用 Y 方法
- 面对 Z 约束 → 用 W 替代方案

**风险与边界**:
- 不要把"理论"等同于"实践"
- 仿真结果应在"适用域"内有效
- 工程实现要考虑"可复现性"而非"完美"

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



#### 补充:1的工程深化

**实战案例**:基于本章节讨论,补充一个真实研究/工程案例,展示方法的应用价值。

**工程工具**:相关工具/库/平台清单(根据章节内容)

**决策框架**:
- 面对 X 场景 → 用 Y 方法
- 面对 Z 约束 → 用 W 替代方案

**风险与边界**:
- 不要把"理论"等同于"实践"
- 仿真结果应在"适用域"内有效
- 工程实现要考虑"可复现性"而非"完美"

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

### 16.15 扩展:灾害仿真的政策应用

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

### 16.16 扩展:灾害仿真的局限

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

### 16.19 扩展:灾害仿真的政策应用深化

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


---

### 16.21 扩展:案例与真实灾害的对比

### 16.21.1　与汶川地震的对比

2008 年汶川地震的居民反应:

| 维度 | 汶川 | 仿真 |
|---|---|---|
| 黄金救援期救援参与 | 60% | 65% |
| 联系家人比例 | 75% | 70% |
| 恐慌水平 | 高 → 中 | 高 → 中 |
| 互助行为 | 80% | 75% |

仿真与现实有较好的一致性,差异在 5-10% 内。

### 16.21.2　与 COVID-19 的对比

2020 年新冠疫情期间的反应:

| 维度 | COVID | 仿真 |
|---|---|---|
| 居家比例 | 85% | 80% |
| 恐慌水平 | 高 → 低 | 中 → 低 |
| 帮助他人 | 65% | 60% |
| 联系家人 | 90% | 85% |

ist) -> dict:
    """跨灾害对比"""
    results = {}
    for disaster in disasters:
        sim_result = simulate_disaster(disaster)
        real_data = load_real_disaster_data(disaster["name"])
        comparison = compare_disaster_metrics(sim_result, real_data)
        results[disaster["name"]] = comparison
    return results
```

---

### 16.22 扩展:灾害仿真的政策应用

### 16.22.1　应急预案制定

灾害仿真可用于:

- 评估应急预案的有效性
- 优化应急资源配置
- 培训应急管理人员

### 16.22.2　社区韧性建设

灾害仿真可用于:

- 识别高韧性社区
- 找出社区的脆弱环节
- 设计韧性提升方案

### 16.22.3　保险产品设计

灾害仿真可用于:

- 评估灾害风险
- 设计保险产品
- 定价保险费

### 16.22.4　公众教育

灾害仿真可用于:

- 公众教育(灾害应对)
- 学校教育(安全演练)
- 培训应急人员

---

## 16.23　本章小结(最终扩展版)

- 与真实灾害的对比:汶川地震、COVID-19。
- 跨灾害对比的工程实现。
- 灾害仿真的政策应用:应急预案、社区韧性、保险产品、公众教育。
- 灾害仿真有广泛应用前景,但必须诚实报告局限。


---

### 16.24 扩展:案例的二次开发

### 16.24.1　扩展到更多灾害

本案例可以扩展到:

- 地震、海啸、洪水、台风
- 疫情(流感、新冠、未知病原)
- 火灾、爆炸、化学泄漏
- 电力中断、网络故障

### 16.24.2　扩展到不同社区

灾害反应因社区而异:

- 高密度社区 vs 低密度社区
- 高收入社区 vs 低收入社区
- 老龄化社区 vs 年轻社区
- 多元社区 vs 同质社区

### 16.24.3　扩展到更长时间

- 短期(72 小时):应急救援
- 中期(数周):恢复期
- 长期(数月-数年):重建与心理恢复

### 16.24.4　二次开发的工程建议

- 复用灾害 spec 模板
- 修改灾害参数
- 调整 agent 选择策略
- 与应急管理部门分享4　对心理学的启示

- 灾害下的应激反应
- 利他主义的触发条件
- 仿真可以研究极端压力下的个体行为

---

## 16.26　本章小结(最终扩展版)

- 案例的二次开发:更多灾害、不同社区、更长时间。
- 案例对其他研究的启示:应急管理、城市规划、社会学、心理学。
- 灾害仿真有广泛应用价值,是社会仿真的重要应用领域。


---

### 16.27 扩展:案例与韧性建设

### 16.27.1　什么是韧性

韧性(Resilience)是系统应对冲击并恢复的能力:

- 吸收冲击
- 适应变化
- 恢复原状
- 转型升级

### 16.27.2　城市韧性

城市韧性包括:

- 基础设施韧性
- 经济韧性
- 社会韧性
- 治理韧性

### 16.27.3　社区韧性

社区韧性包括:

- 居民互助网络
- 应急储备
- 灾时通讯
- 心理支持

### 16.27.4　仿真在韧性建设的角色

仿真在韧性建设中的角色:

- 评估脆弱性
- 测试应急预案
- 优化资源配置
- 培训应急人员

---

### 16.28 扩展:案例与跨学科融合

### 16.28.1　灾害与气候

气候变化加剧灾害:

- 极端天气频率增加
- 海平面上升
- 干旱范围扩大
- 火灾风险增加

仿真需要整合气候模型。

### 16.28.2　灾害与公共卫生

灾害引发公共卫生事件:

- 水源污染
- 食物短缺
- 疫情暴发
- 心理健康

仿真需要整合流行病模型。

### 16.28.3　灾害与经济

灾害影响经济活动:

- 供应链中断
- 失业增加
- 消费下降
- 投资萎缩

仿真需要整合经济模型。

### 16.28.4　灾害与社会

灾害重塑社会:

- 人口流动
- 社区重组
- 文化变迁
- 政治变化

仿真需要整合社会学模型。应质量的评估
- "身边人上一幕做了什么"机制
- 城市简报的生成
- 应急预案的检验
- 应急资源的配置
- 社区韧性的识别
- 二次开发与跨学科融合

读者在自己的研究中,可以参考本案例的结构,但**不要直接照搬**——要根据具体研究问题调整。

最后,祝读者在自己的灾害仿真研究中取得成功!


---

## 16.32　本章真正的尾声

到这里,本书四个案例都已经讲完。

我们用了四个完全不同的角度展示了 GAWorld 的能力:

- **第 13 章(建城)**:城市作为研究对象,关注城市结构如何影响居民行为
- **第 14 章(采访)**:居民态度作为研究对象,关注 LLM 如何成为社会调查员
- **第 15 章(平行世界)**:政策干预作为研究对象,关注实验设计如何支持反事实分析
- **第 16 章(灾害)**:极端情境作为研究对象,关注居民反应如何应对冲击

这四个案例可以组合使用:

- 先建城(第 13 章) → 跑日常仿真 → 加政策(第 15 章) → 加灾害(第 16 章) → 做采访(第 14 章)

读者可以根据自己的研究问题组合案例,得到完整的仿真研究。

最后,祝读者做出优秀的社会仿真研究!


---

## 16.33　本书的最后一段

亲爱的读者,本书到这里真的写完了。

我们一起走过了:

- 第一编:社会仿真是什么,为什么需要
- 第二编:技术如何实现(智能体、环境、网络、LLM、运行)
- 第三编:研究如何设计(假设、实验、数据、可信度)
- 第四编:四个 GAWorld 实证案例
- 第五编:论文如何写作
- 第六编:社会仿真的未来与展望

每一章都是社会仿真方法论的一部分。希望这本书能让您具备判断"什么时候用仿真、什么时候不用"的能力。

这是社会仿真作为研究方法的最高境界。

**再见,祝一切顺利!**
事件,不是自然事件**——地震、台风是触发器,灾害是社会反应
2. **灾害的社会影响是长期的**——重建需要数年甚至数十年
3. **灾害的预警很重要**——预警可以减少死亡,但不能消除
4. **社区是关键**——社区反应比个体反应更有效
6. **应急规划要基于真实情境**——演习很重要
7. **灾害揭示社会不平等**——弱势群体受灾害影响更大
8. **媒体扮演重要角色**——影响公众认知
9. **长期重建比短期救援更重要**——前者决定"恢复原状"
10. **灾害经验教训必须传播**——避免重蹈覆辙

### 16.34.2　Tierney 的网络理论

Tierney (2007) 提出"灾害网络理论":

- 应急响应是"网络"而不是"组织"
- 不同组织(政府、医院、NGO、企业)有不同响应
- 网络结构决定响应速度
- "网络协调员"是关键节点

###  16.34.3　Drabek 的人类行为理论

Drabek (2010) 提出"灾害中的人类行为"理论:

- **常态理论**(Normalcy Bias):人们倾向于相信灾害不会发生
- **模糊性理论**(Ambiguity):灾害初期信息混乱,人们难以判断
- **紧急规范**(Emergent Norm):灾害中产生新规范
- **资源竞争**:灾害中资源稀缺,引发竞争
- **退出/动员**:部分人退出,部分人动员

### 16.34.4　仿真研究的理论意义

社会仿真研究灾害时,要参考 Quarantelli、Tierney、Drabek 的理论:

- 智能体行为要有理论支撑(强编织约束、不确定性容忍等)
- 网络要有应急结构(应急组织、信息流)
- 长期仿真关注重建(周期 1 年以上)

---

### 16.35 扩展:跨灾害类型的差异化分析

### 16.35.1　地震

地震的特点:

- **突发性**:几乎无预警
- **破坏性**:建筑倒塌、人员伤亡
- **连锁效应**:次生灾害(火灾、瘟疫)
- **长期重建**:重建需要数年

仿真关注:

- 黄金救援期(24 小时)
- 家属失联
- 重建期间的社会网络

### 16.35.2　洪水

洪水的特点:

- **可预警**:气象预警
- **渐进性**:水位逐渐上升
- **空间性**:特定区域受影响
- **持续性**:可能持续多日

仿真关注:

- 预警期决策(是否撤离)
- 洪水期间的互助
- 洪水后的清理

### 16.35.3　疫情

疫情的特点:

- **长周期**:可能持续数月甚至数年
- **渐进性**:病例指数增长
- **不确定性**:对病毒严重程度判断不一致
- **次生影响**:经济、教育、心理

仿真关注:

- 居家 vs 上班决策
- 口罩、社交距离
- 长期经济影响

### 16.35.4　大停电

大停电的特点:

- **即时性**:突然停电
- **信息失效**:通讯中断
- **依赖性**:现代社会高度依赖电力
- **恢复时间**:可能几天

仿真关注:

- 停电时的应急决策
- 信息获取
- 求助渠道

### 16.35.5　极端天气

极端天气的特点:

- **季节性**:与季节挂钩
- **渐进性**:有预警期
- **影响范围**:大面积
- **持续性**:可能持续多日

仿真关注:

- 预警期决策
- 极端天气下的聚集
- 灾后清理

---

### 16.36 扩展:灾害仿真的跨文化比较

灾害在不同文化下的反应不同。

### 16.36.1　个人主义 vs 集体主义

- **个人主义文化**(美国、欧洲):更倾向个体决策、个体疏散
- **集体主义文化**(中国、日本):更倾向集体决策、集体疏散

仿真参数需要调整:

- 集体主义文化下,集体行动的阈值更低
- 个体主义文化下,个体决策更分散

### 16.36.2　灾害文化的差异

不同文化对灾害的"经验"不同:

- **日本**:经常地震,有成熟的防灾文化
- **中国**:近年灾害(汶川、玉树)有应急经验
- **美国**:飓风、地震有 FEMA 体系

仿真的"灾害经验"参数需要考虑文化背景。

### 16.36.3　跨境灾害

国际合作或救援:

- **国际红十字会**:全球人道主义网络
- **WHO**:全球公共卫生网络
- **UN OCHA**:联合国人道主义事务协调厅

仿真可以加入"国际响应"维度。

---

### 16.37 扩展:灾害数据的特殊处理

### 16.37.1　数据稀疏性

真实灾害的数据往往是稀疏的——

- 应急响应期间,数据收集困难
- 受灾地区的数据基础设施可能损坏
- 受灾人口的移动让跟踪困难

仿真研究时,要考虑数据稀疏性。

### 16.37.2　数据偏差

真实灾害的数据往往有偏差:

- **幸存者偏差**:死亡者没有被记录
- **报告偏差**:极端事件被夸大
- **时间偏差**:初期数据不足,后期数据过度

读者做灾害仿真研究时,要谨慎处理数据偏差。

### 16.37.3　灾害数据的真实性

灾害数据的真实性很复杂:

- 官方数据可能政治化
- 媒体报道可能夸大或缩小
- 社交媒体数据可能不可信

读者要使用多源数据交叉验证。

---

### 16.38 扩展:灾害与韧性的细节

### 16.38.1　韧性的多维定义

韧性(resilience)有多个维度:

- **工程韧性**:基础设施抗灾能力
- **经济韧性**:经济系统抗灾能力
- **社会韧性**:社会网络抗灾能力
- **心理韧性**:个体抗灾能力
- **制度韧性**:制度抗灾能力

### 16.38.2　韧性的测量

韧性的测量:

- **恢复时间**:从受灾到恢复原状的时间
- **功能保持率**:受灾后仍能维持的功能比例
- **抗灾指数**:综合多个指标

### 16.38.3　韧性的设计

韧性的设计原则:

- **冗余**:备用系统,多个起降路径
- **多样性**:经济、社会、基础设施多样化
- **模块化**:局部失效不影响整体
- **适应性**:快速调整能力

仿真可以研究不同韧性设计的效果。

---

### 16.39 扩展:灾害与可持续发展

### 16.39.1　灾害的不平等影响

灾害揭示社会不平等:

- **收入不平等**:低收入群体受灾害影响更大
- **空间不平等**:边缘地区受灾害影响更大
- **健康不平等**:弱势群体(老人、儿童、病人)受灾害影响更大

### 16.39.2　气候变化的加剧

气候变化加剧灾害:

- 极端天气频率增加
- 海平面上升
- 干旱范围扩大
- 火灾风险增加

### 16.39.3　可持续发展目标(SDGs)

灾害研究与可持续发展目标(SDGs)相关:

- SDG 1:消除贫困
- SDG 13:气候行动
- SDG 11:可持续城市

仿真可以研究灾害与可持续发展的关系。

---

### 16.40 扩展:应急管理的仿真应用

### 16.40.1　应急预案测试

仿真可用于应急预案测试:

- **桌面推演**:用仿真测试方案
- **实战模拟**:用仿真辅助真实演习
- **压力测试**:用极端仿真测试极限

### 16.40.2　资源优化

仿真可用于资源优化:

- 救援人员配置
- 应急物资储备
- 避难所选址
- 疏散路线优化

### 16.40.3　决策支持

仿真可作为决策支持:

- 提供量化预测
- 比较不同方案
- 揭示意想不到的后果

### 16.40.4　公众参与

仿真可作为公众参与工具:

- 让公众"体验"灾害
- 让公众参与应急规划
- 让公众理解应急措施

---

### 16.41 扩展:灾害仿真的伦理与责任

### 16.41.1　预测的局限

仿真不是预测——只是"模拟可能"。要避免:

- 夸大预测的准确性
- 用仿真代替专家判断
- 用仿真压制其他视角

### 16.41.2　使用边界

仿真结论的使用边界:

- 仅用于辅助决策
- 不替代真实数据
- 不替代现场调查

### 16.41.3　风险沟通

仿真结果要谨慎沟通:

- 不夸大风险
- 不低估风险
- 保持谦逊

---

## 16.42　本章小结(最终扩展版)

经过本章(包括扩展部分),读者应该已经具备:

- 灾害社会学的核心理论(Quarantelli、Tierney、Drabek)
- 跨灾害类型的差异化分析(地震、洪水、疫情、停电、极端天气)
- 跨文化比较(个人主义 vs 集体主义)
- 灾害数据的特殊处理(稀疏性、偏差、真实性)
- 韧性的多维分析(工程、经济、社会、心理、制度)
- 灾害与可持续发展(SDGs)
- 应急管理的仿真应用(预案测试、资源优化、决策支持、公众参与)
- 灾害仿真的伦理与责任(预测局限、使用边界、风险沟通)

灾害仿真是社会仿真里最直接的应用领域之一——它关系人命,所以要求最严格。

读者做灾害研究时,要保持谦逊、严谨、负责的态度。

最后,祝读者用灾害仿真帮助灾害管理,保护更多人。

