# 第 4 章　智能体：身份、状态与决策

> 从这一章开始,我们要从"为什么"进入"怎么做"。社会仿真的最小单元是**智能体**(agent)——一个有身份、有状态、能行动的"假人"。这一章解决三个问题:智能体应该有哪些数据(身份与状态)?这些数据怎么用(决策)?数据怎么存(记忆)?工程实现以 GAWorld 为蓝本,代码示例都可以直接拷贝运行。建议读者边读边敲代码,光看不练难以真正掌握。

---

## 4.1　智能体的最小身份 schema

要给一个智能体"起户口",最少需要哪些字段?经过 GAWorld 在多种城市、人口规模下的反复测试,我们总结出一份"11 项最小完备集":

| 字段 | 含义 | 取值范围 | 缺失后果 |
|---|---|---|---|
| id | 全局唯一编号 | 1 ~ 1e6 | 系统冲突 |
| name | 姓名 | 字符串 | 无法对话 |
| age | 年龄 | 0–110 | 决策失真 |
| gender | 性别 | F / M / NB | 部分场景失真 |
| education | 学历 | 小学 ~ 博士 | 职业分布失真 |
| job | 职业 | 自由文本 | 收入为空 |
| income_hourly | 时薪 | 0–1000 | 经济仿真退化为零 |
| family_role | 家庭角色 | 户主/配偶/子女/独居 | 家庭仿真失效 |
| residence | 住址 | 城市包内地点 | 出行为零 |
| hukou | 户籍 | 城市/省份 | 福利/补贴失真 |
| political_leaning | 政治倾向 | -1–1 | 群体态度失真 |

**为什么是 11 项?而不是 50 项?** 因为仿真研究的瓶颈不在数据丰富度,而在数据**互一致性**。一个"高中学历、博士职业、月薪 5 万"的智能体会让经济仿真直接崩盘。所以这 11 项是经过联合分布约束检验的——任何一项缺失,与其相关的子系统就会出现明显异常。

经验法则:**11 项必须联合一致,而非独立完整**。具体来说,"年龄—职业—收入—学历"是高度相关的(28 岁的博士很少有,60 岁的外卖员也少见);"住址—工作地点—通勤时间"是高度相关的(住郊区的人在市中心工作意味着长通勤);"家庭角色—年龄—婚姻状态"是高度相关的(独居的 15 岁少年和独居的 60 岁鳏夫是两种社会角色)。GAWorld 在生成人口时,会先按联合分布抽样,再赋具体字段,避免出现"高中学历 + 月薪 5 万"这样的荒诞组合。

代码示例:用 Python 定义一个最小智能体类。

```python
# examples/agent_min.py
from dataclasses import dataclass, field
from typing import Optional

@dataclass
class AgentIdentity:
    id: int
    name: str
    age: int
    gender: str = "F"
    education: str = "本科"
    job: str = "未就业"
    income_hourly: float = 0.0
    family_role: str = "独居"
    residence: str = ""
    hukou: str = ""
    political_leaning: float = 0.0

# 创建一个 31 号居民
a = AgentIdentity(id=31, name="林素", age=34, gender="F",
                  education="本科", job="社区医生",
                  income_hourly=85.0, family_role="户主",
                  residence="柯桥-笛扬路-12号",
                  hukou="绍兴", political_leaning=-0.2)
print(a)
```

这一段代码跑起来会打印一个完整的智能体身份,后续章节会逐步给它加状态、加记忆、加决策。

### 一个关于"学历—职业—收入"联合分布的真实数据练习

读者如果想验证 GAWorld 的人口生成质量,可以做以下练习:

1. 从国家统计局《中国统计年鉴》取一组"分学历分行业收入"数据。
2. 把数据按学历(高中、本科、硕士、博士) × 行业(制造业、金融、教育、医疗)分组,算出每个组合的均值和标准差。
3. 用这组分布作为 GAWorld `gaworld/population.py` 的输入参数。
4. 跑出 1000 个居民,验证生成的人口分布是否和真实分布一致。

如果一致,说明联合分布建模成功;如果不一致,说明仿真失真,需要调整。这个练习用 1 个下午就能完成,是验证仿真可信度的入门实践。

---

## 4.2　九维状态空间

身份是"不变的户口",状态是"每天都在变的心情、钱包、关系"。GAWorld 把状态分成 9 个维度,这是经过数十次实验后留下的"性价比最优"——再多就开始算力撑不住,再少就开始行为失真。

| 维度 | 字段 | 取值范围 | 主要驱动 |
|---|---|---|---|
| 生理 | health, fatigue | 0–1 | 时间、睡眠、饮食 |
| 心理 | mood, stress | -1–1 | 事件、社交、记忆 |
| 社会 | belonging, reputation | 0–1 | 互动频率、被点赞 |
| 经济 | cash, savings | 0–1e6 | 工资、消费、投资 |
| 认知 | info, skill | 0–1 | 学习、遗忘、培训 |
| 关系 | intimacy, obligation | 0–1 | 接触、义务衰减 |
| 能力 | skill_proficiency | 0–1 | 重复训练 |
| 目标 | priority, plan | 枚举 | 决策选择 |
| 偏好 | taste, values | 枚举 | 提示词背景 |

**9 维不是冗余,是协同**。举个例子:同一条"朋友借钱"事件,在不同维度组合下会触发完全不同的决策:

- 高 cash + 低 intimacy → 拒绝
- 低 cash + 高 obligation → 同意(但可能违约)
- 中 cash + 中 mood + 高 obligation → 同意但焦虑
- 高 savings + 高 obligation → 同意且帮助寻找其他方案

读者做研究的时候,如果把 9 维简化到 2–3 维,这类"组合行为"会大量消失,仿真结果就会失真。这是 GAWorld 长期迭代得出的经验。

代码示例:9 维状态的简单 Python 实现。

```python
# examples/agent_state.py
from dataclasses import dataclass

@dataclass
class AgentState:
    # 生理
    health: float = 1.0
    fatigue: float = 0.0
    # 心理
    mood: float = 0.0      # -1 抑郁, +1 兴奋
    stress: float = 0.0    # 0 完全放松, 1 满负荷
    # 社会
    belonging: float = 0.5
    reputation: float = 0.5
    # 经济
    cash: float = 10000.0
    savings: float = 50000.0
    # 认知
    info: float = 0.5
    skill: float = 0.5
    # 关系(对一个具体对象)
    intimacy: float = 0.0
    obligation: float = 0.0
    # 能力
    skill_proficiency: float = 0.5
    # 目标
    priority: str = "生存"
    plan: str = "未制定"
    # 偏好
    taste: str = ""
    values: str = ""

    def stress_to_action(self) -> str:
        """简单决策:高疲劳 + 高压力 → 休息"""
        if self.fatigue > 0.7 or self.stress > 0.7:
            return "回家休息"
        if self.cash < 1000:
            return "找工作或借钱"
        return "维持常规活动"

s = AgentState(fatigue=0.8, stress=0.6, cash=200)
print(s.stress_to_action())  # → 回家休息
```

这段代码演示了"状态 → 决策"的最小实现。真正的 GAWorld 用 LLM 做决策(详见第 7 章),但核心逻辑一致:把状态打包,问"在这种情况下你会做什么"。

### 9 维之间的耦合

9 维不是独立的——它们之间有强耦合。GAWorld 在每次仿真 tick 里会运行一组"耦合规则",例如:

- 失业 → cash 下降 → stress 上升 → mood 下降
- 恋爱 → intimacy 上升 → mood 上升 → stress 下降
- 长期疲劳 → health 下降 → skill_proficiency 下降 → 收入下降 → cash 下降 → ...

耦合规则是社会仿真里"涌现"的核心来源。少一个耦合,行为就少一类变化;多一个耦合,行为就多一类涌现。这是 9 维选择的经验根据。

---

## 4.3　行为策略四象限

智能体怎么从状态走到行动?历史上主要有四种策略,各有适用范围。

**象限一:规则(IF-THEN)**。可解释、可复现、成本低,但行为单调。适合做"机制演示"——谢林的隔离模型就是这一类。GAWorld 的默认行为引擎在低层级使用大量规则(疲劳度阈值、通勤时长、经济守恒)。

**象限二:效用最大化(Expected Utility)**。经济学传统,假设人是理性的。适合做"市场模拟""政策评估"——但行为单调,缺乏人味。GAWorld 的就业、储蓄、投资决策使用效用模型,因为这些场景确实接近理性人假设。

**象限三:启发式(Heuristic)**。行为经济学的累积前景理论、有限理性。规则比效用模型多,行为比纯规则更丰富,但工程实现复杂。GAWorld 的部分决策(消费倾向、信息搜索)用启发式。

**象限四:LLM 推理**。把状态打包成提示词,让语言模型决定下一步。行为丰富、可解释性中等、成本高。LLM 决策是 GAWorld 的核心创新点,第 7 章会展开。

选择哪种策略,主要看三个维度:**可解释性需求 / 真实感需求 / 算力预算**。

| 维度 | 规则 | 效用 | 启发式 | LLM |
|---|---|---|---|---|
| 可解释性 | 高 | 高 | 中 | 中 |
| 真实感 | 低 | 中低 | 中 | 高 |
| 算力 | 低 | 低 | 中 | 高 |
| 工程难度 | 低 | 中 | 中高 | 高 |
| 适用场景 | 机制演示 | 市场/政策 | 消费/搜索 | 社交/采访 |

GAWorld 的设计哲学:**默认用规则 + 启发式(可解释且高效),关键决策(社交、采访、灾害反应)用 LLM(真实感)**。这样在算力和真实感之间找到平衡。

### 一个选择决策策略的工作流

做研究时,推荐按以下流程选择决策策略:

1. **明确决策场景**(社交、消费、出行、职业选择……)
2. **评估真实感需求**(用户问卷 vs 政策模拟 vs 机制研究,需求不同)
3. **评估可解释性需求**(论文是否需要展示规则?同行能否审查逻辑?)
4. **评估算力预算**(一年一次的实验 vs 一天 100 次的批量实验)
5. **混合策略**:对 80% 的"低重要性"决策用规则,对 20% 的"高重要性"决策用 LLM

这个工作流能避免最常见的两个反模式:**全用 LLM**(成本失控、行为难复现)和**全用规则**(行为失真、缺少人味)。

---

## 4.4　记忆系统

人之所以是"同一个人",是因为有记忆——能记住昨天发生的事、能总结过去一年的经验、能记住某个朋友对自己的态度。智能体也一样。

GAWorld 把记忆分成 4 类:

1. **短期记忆(Working Memory)**:当前会话/当前日的最近 N 条信息,容量有限(7 ± 2 条)。用于实时对话和行动选择。
2. **情景记忆(Episodic Memory)**:按"时间—地点—人物—事件"组织的具体记忆,有日期、有地点、有情绪标签。这是 LLM 提示词里最常用的一类。
3. **长期记忆(Long-term / Semantic)**:从情景记忆里提炼出的总结、规律、价值判断。比如"我和老张合作过三次,都很愉快"——这是从 3 条情景记忆里抽象出来的总结。
4. **关系记忆(Relational Memory)**:对每一个具体对象的印象。"老张:友好、可靠、欠我一次人情"——这是关系记忆。

代码示例:一个简单的记忆结构。

```python
# examples/agent_memory.py
from dataclasses import dataclass, field
from datetime import datetime
from typing import List

@dataclass
class Episode:
    timestamp: datetime
    location: str
    persons: List[str]
    action: str
    emotion: float  # -1 ~ 1
    summary: str = ""

@dataclass
class AgentMemory:
    working: List[str] = field(default_factory=list)  # 最近 N 条
    episodes: List[Episode] = field(default_factory=list)  # 情景
    semantic: List[str] = field(default_factory=list)  # 长期总结
    relations: dict = field(default_factory=dict)  # {person: impression}

    def add_episode(self, ep: Episode):
        self.episodes.append(ep)
        # 触发长期记忆更新
        if len(self.episodes) > 10:
            self.consolidate()

    def consolidate(self):
        """简化的记忆巩固:从最近 10 条里抽 1 条总结"""
        recent = self.episodes[-10:]
        summary = f"过去经历了 {len(recent)} 件事,平均情绪 {sum(e.emotion for e in recent)/len(recent):.2f}"
        self.semantic.append(summary)

m = AgentMemory()
m.add_episode(Episode(datetime.now(), "公司", ["老张"], "项目协作", 0.5))
m.add_episode(Episode(datetime.now(), "家", ["配偶"], "晚餐", 0.8))
# ... 加 8 条 ...
m.add_episode(Episode(datetime.now(), "公司", ["老张"], "项目复盘", 0.6))
m.consolidate()
print(m.semantic)  # → ['过去经历了 10 件事,平均情绪 0.60']
```

GAWorld 的真实版本使用 LLM 做记忆巩固(把 10 条情景总结成 1–2 条长期记忆),并用向量召回检索相关情景。技术细节见 `gaworld/memory/`。

### 记忆的衰减与遗忘

人不是所有事情都记得——很多细节会随时间淡化。GAWorld 的记忆系统有"衰减"机制:

- 情景记忆的"重要性"随时间指数衰减,默认半衰期 7 天。
- 长期记忆不会衰减,但很少被创建。
- 关系记忆根据"上次互动距离"衰减,久未联系的友人,关系记忆会从"亲密"变成"认识"。

这种衰减机制有两个好处:一是控制记忆存储量(不会无限增长),二是让仿真行为有时间感——一个人对 10 年前的事情和对自己有和近的事情反应不同,是社会行为的核心特征。

---

## 4.5　大五人格(OCEAN)

人是多样的——同样的事件,有人乐观,有人悲观;有人爱社交,有人爱独处。仿真要反映这种多样性,就要给智能体注入"人格"。最常用的人格模型是**大五人格**(OCEAN):

- **O**(Openness,开放性):好奇心、想象力、对新经验的开放度
- **C**(Conscientiousness,尽责性):自律、组织性、责任感
- **E**(Extraversion,外向性):社交活跃度、能量水平
- **A**(Agreeableness,宜人性):合作、利他、信任
- **N**(Neuroticism,神经质):情绪稳定性,反向指标

大五人格有 60+ 年心理学研究基础,跨文化稳定,且有成熟的问卷量表(NEO-PI-R)。在社会仿真里,它的价值在于:

1. **可量化**:每个人的 OCEAN 都可以用 5 个 0–1 的分数表示。
2. **可关联行为**:OCEAN 各维度与决策风格有清晰的统计关联(开放性 → 风险偏好;外向性 → 表达倾向)。
3. **可生成**:LLM 在给定 OCEAN 分值的情况下,可以生成"像这个人"的言行。

GAWorld 的工程实践:

- 先用 LLM 对每个居民采样 5 个 z 分(标准化分数)
- 再用 5 个 z 分改写居民的"行为倾向描述"(51 次调用,每人 1 次)
- 把描述写进身份档案 `agent_profile.md`,运行时作为提示词背景

代码示例:OCEAN 采样。

```python
# examples/ocean.py
import random

def sample_big5(seed: int = None):
    """从 N(0, 1) 采样 5 个大五分数,夹到 [-3, 3]"""
    if seed is not None:
        random.seed(seed)
    return {
        "O": max(-3, min(3, random.gauss(0, 1))),
        "C": max(-3, min(3, random.gauss(0, 1))),
        "E": max(-3, min(3, random.gauss(0, 1))),
        "A": max(-3, min(3, random.gauss(0, 1))),
        "N": max(-3, min(3, random.gauss(0, 1))),
    }

# 居民 31 号 vs 居民 32 号
print(sample_big5(31))  # → {'O': -0.7, 'C': 0.5, ...}
print(sample_big5(32))  # → {'O': 1.2, 'C': -0.3, ...}
```

> **OCEAN 的使用警告**:OCEAN 是"统计趋势",不是"决定论"。一个高外向性的人可能偶尔选择独处,一个低外向性的人可能偶尔参加聚会。仿真里,OCEAN 只用于"决策倾向",不用于"强制结果"。把 OCEAN 当成强制规则,会让智能体变成"刻板印象集合"——这是工程上最常见的反模式。

### OCEAN 在 GAWorld 中的工程应用

GAWorld 用 OCEAN 做三件事:

1. **改写居民的人设描述**(offline,51 次 LLM 调用):把 OCEAN 分数转写成一段"行为倾向描述",作为提示词背景。
2. **影响 LLM 决策温度**(online):高 N(神经质)的居民决策温度略高(更多变化),高 C(尽责性)的居民决策温度略低(更稳定)。
3. **影响社交倾向**(online):高 E(外向性)的居民社交行动触发阈值更低,更容易与人互动。

注意 OCEAN **不是直接用作规则**——它是 LLM 决策时的"软提示"。这是工程上的一个重要选择。

---

## 4.6　代码示例:一个 200 行的最小智能体循环

把 4.1–4.5 节的内容整合起来,写一个"最小可行智能体"。这段代码不依赖任何外部库,跑起来后能看到一个智能体在虚拟的一天里做决策。

```python
# examples/mini_agent.py
# 一个 200 行的最小智能体循环
from dataclasses import dataclass, field
from typing import List
from datetime import datetime, timedelta

@dataclass
class Identity:
    name: str
    age: int
    job: str
    income_hourly: float

@dataclass
class State:
    health: float = 1.0
    fatigue: float = 0.0
    mood: float = 0.0
    cash: float = 5000.0
    stress: float = 0.0

@dataclass
class Episode:
    time: datetime
    action: str
    mood_change: float

@dataclass
class Agent:
    identity: Identity
    state: State
    memory: List[Episode] = field(default_factory=list)

    def decide(self, hour: int) -> str:
        # 简单的规则决策
        if self.state.fatigue > 0.8:
            return "睡觉"
        if hour < 8 or hour >= 22:
            return "睡觉"
        if 9 <= hour < 18 and "未就业" not in self.identity.job:
            return "工作"
        if self.state.stress > 0.6:
            return "散步减压"
        if self.state.cash < 100:
            return "回家省钱"
        return "自由活动"

    def act(self, hour: int):
        action = self.decide(hour)
        # 行动带来的状态变化
        if action == "睡觉":
            self.state.fatigue = max(0, self.state.fatigue - 0.5)
            self.state.health = min(1, self.state.health + 0.05)
            mood_change = 0.05
        elif action == "工作":
            self.state.cash += self.identity.income_hourly
            self.state.fatigue += 0.2
            self.state.stress += 0.1
            mood_change = -0.05
        elif action == "散步减压":
            self.state.stress = max(0, self.state.stress - 0.3)
            mood_change = 0.1
        elif action == "回家省钱":
            mood_change = -0.1
        else:
            mood_change = 0.0
        self.state.mood = max(-1, min(1, self.state.mood + mood_change))
        self.memory.append(Episode(datetime.now(), action, mood_change))
        return action

# 跑一天
agent = Agent(Identity("林素", 34, "社区医生", 85.0), State())
day_start = datetime(2026, 9, 26, 0, 0)
print(f"=== {agent.identity.name} 的一天 ===")
for h in range(24):
    t = day_start + timedelta(hours=h)
    a = agent.act(h)
    print(f"{t.strftime('%H:%M')} | {a:10s} | "
          f"现金={agent.state.cash:.0f} "
          f"疲劳={agent.state.fatigue:.2f} "
          f"压力={agent.state.stress:.2f} "
          f"情绪={agent.state.mood:.2f}")
```

跑这段代码,会打印一个虚拟居民从 0 点到 23 点的 24 行行为记录。这是仿真世界的"原子"——把 1000 个这样的智能体放在同一个仿真里,加上环境、网络、经济系统,就构成了一个"社会"。

> **教学讨论**:读者跑完这段代码后,会发现这个智能体太"机械"——它没有社交、没有记忆检索、没有情绪推理、没有 LLM 的灵活性。这正是规则系统的局限。但它**可解释、可复现、跑得快**——这是 LLM 系统目前做不到的。GAWorld 把规则系统和 LLM 系统组合使用,关键决策交给 LLM,日常行为交给规则,目的是在"真实感"和"算力"之间找到平衡。

---

## 4.7　本章小结

- 智能体的最小身份 schema 是 11 项:姓名、年龄、性别、学历、职业、时薪、家庭角色、住址、户籍、政治倾向、ID。这些字段必须联合一致,不能独立完整。
- 9 维状态空间(生理/心理/社会/经济/认知/关系/能力/目标/偏好)是 GAWorld 长期迭代的"性价比最优";9 维之间有耦合,耦合规则是涌现的核心来源。
- 行为策略四象限:规则、效用最大化、启发式、LLM 推理,各有适用场景,推荐混合使用。
- 记忆分 4 类:短期、情景、长期总结、关系记忆,带衰减机制。
- 大五人格(OCEAN)是给智能体注入多样性的成熟模型,但要警惕"刻板印象集合"反模式;OCEAN 在 GAWorld 里是"软提示",不是"硬规则"。
- 一个 200 行的最小智能体循环能在 1 秒内跑完一天,是仿真世界的原子单元。

---

## 4.8　思考题

1. **补全一个智能体的身份字段**:从 11 项里选 5 项,为一个 31 岁的"自由摄影师"填写完整字段,确保内部一致性(学历、职业、收入、住址等互相支持)。
2. **状态决策对比**:同一事件("朋友借钱 5000 元"),用规则、效用、启发式、LLM 四种策略分别给出决策,比较差异。
3. **记忆检索**:为一段 50 条情景记忆,设计一个"和当前情境最相关"的检索算法(可以用关键词相似度,也可以用 LLM 摘要)。
4. (进阶)**为限行令案例设计一个智能体的"出行决策函数"**:假设该智能体是 35 岁有车上班族,他的状态变量怎么决定他是否开车上班?函数包含哪些规则?哪些情况下调用 LLM?

---

## 4.9　延伸阅读

1. Goldberg, L. R. (1993). The Structure of Phenotypic Personality Traits. *American Psychologist*, 48(1), 26–34. —— 大五人格的奠基论文。
2. Costa, P. T., & McCrae, R. R. (1992). Revised NEO Personality Inventory (NEO-PI-R). Psychological Assessment Resources. —— 大五人格最常用的量表。
3. Kahneman, D. (2011). *Thinking, Fast and Slow*. Farrar, Straus and Giroux. —— 行为经济学对"理性人假设"的根本性反思。
4. Simon, H. A. (1957). *Models of Man: Social and Rational*. Wiley. —— "有限理性"的概念起源。
5. Schelling, T. C. (1978). *Micromotives and Macrobehavior*. Norton. —— 从微观规则到宏观行为的范例。
6. Park, J. S., et al. (2023). Generative Agents. *arXiv:2304.03442*. —— LLM 智能体的经典实现。
7. Epstein, J. M. (2006). *Generative Social Science*. Princeton University Press. —— 第 6 章专门讨论智能体设计。
8. GAWorld 工程文档:`gaworld/agent.py`、`gaworld/memory/`、`gaworld/personality/`。
9. Mccrae, R. R., & Costa, P. T. (1997). Personality Trait Structure as a Human Universal. *American Psychologist*, 52(5), 509–516. —— 大五跨文化普遍性的论证。
10. Camerer, C. (2005). *Behavioral Game Theory: Experiments in Strategic Interaction*. Princeton University Press. —— 行为博弈论的代表,把心理引入经济学决策。

---

> **本章教学注释**
>
> 这是全书第一段技术章节,故意配了大量代码示例。读者如果不会 Python,**强烈建议先把代码跑起来**——动手比阅读更快建立直觉。代码可以直接拷贝运行,不需要 GAWorld 完整安装。
>
> 4.6 节的"200 行最小智能体循环"是一个非常重要的教学钩子:它让读者看到"智能体"到底长什么样、状态怎么变、决策怎么出。把这段代码改一改,比如把决策函数换成 LLM,就能直观体会到第 7 章要讲的内容。
>
> **与 GAWorld 的对应**:`gaworld/agent.py` 是 GAWorld 的完整智能体实现,涵盖本章所有概念;`gaworld/personality/traits.py` 是大五人格采样器;`gaworld/memory/store.py` 是记忆持久化;`gaworld/persona/` 是从真人(姓名/网址)蒸馏居民的高级模块,第 13 章案例会用到。下一章我们进入"环境":智能体住在什么样的城市里?城市结构如何影响他们的行为?
---

## 4.10　扩展:智能体的工程实现细节

### 4.10.1　智能体的存储

智能体的存储格式有几种选择:

**JSON**:人类可读,适合配置和调试,但占用空间大。

**CSV**:易于用 pandas 加载,适合表格数据,但难以表达嵌套结构。

**Parquet**:压缩二进制,占用空间小,适合大规模数据。

**数据库(SQLite)**:支持复杂查询,适合持久化和可重复使用。

GAWorld 的存储策略:

- **身份**:CSV + Markdown profile
- **状态**:CSV(每行一个 agent 一天)
- **事件**:JSONL(每行一个事件)
- **记忆**:JSON(每个 agent 每天一个文件)

### 4.10.2　智能体的索引

大规模仿真需要高效的索引:

```python
# 按 ID 索引
agents_by_id = {a.id: a for a in agents}

# 按状态字段索引
agents_by_job = defaultdict(list)
for a in agents:
    agents_by_job[a.job].append(a)

# 按空间索引(用于环境查询)
agents_by_region = defaultdict(list)
for a in agents:
    agents_by_region[a.region].append(a)
```

### 4.10.3　智能体的更新

状态更新有两种模式:

**拉模式(pull)**:每个 tick 重新计算所有 agent 的状态。
**推模式(push)**:事件驱动,只在事件触发时更新。

GAWorld 用混合模式:核心状态用推模式,衍生指标用拉模式。

### 4.10.4　智能体的批处理

批处理是性能优化的关键:

```python
def batch_update(agents, time_delta):
    """批量更新所有 agent"""
    # 用 numpy 数组做向量化更新
    cash_array = np.array([a.cash for a in agents])
    income_array = np.array([a.income_hourly for a in agents])
    cash_array += income_array * time_delta
    # 写回
    for i, a in enumerate(agents):
        a.cash = cash_array[i]
```

---

## 4.11　扩展:决策策略的混合实现

第 4.3 节给出四象限决策。但在工程实践中,通常需要混合策略。

### 4.11.1　规则 + LLM 混合

```python
def hybrid_decision(agent, situation):
    """规则 + LLM 混合决策"""
    # 1. 先用规则判断"是否需要 LLM 决策"
    if agent.cash < 100 and agent.energy > 0.5:
        return "rule: sell_asset"
    # 2. 复杂决策调用 LLM
    if situation["decision"] in ["critical", "social", "moral"]:
        return call_llm_decision(agent, situation)
    # 3. 简单决策用规则
    return apply_rules(agent, situation)
```

### 4.11.2　效用 + 启发式混合

```python
def utility_heuristic_hybrid(agent, options):
    """效用最大化 + 启发式修正"""
    # 1. 计算每个选项的效用
    utilities = [compute_utility(agent, opt) for opt in options]
    # 2. 用启发式调整
    adjusted = apply_heuristics(agent, options, utilities)
    # 3. 选择最优
    return options[np.argmax(adjusted)]
```

### 4.11.3　决策的元策略

如何选择"用哪种策略"本身也是决策:

```python
def meta_decision(agent, situation):
    """元决策:决定用哪种决策策略"""
    if situation["complexity"] == "low":
        return "rule"
    elif situation["complexity"] == "medium":
        return "heuristic"
    else:
        return "llm"
```

### 4.11.4　决策成本 vs 质量的平衡

每个决策都有"成本"(计算量)和"质量"(真实感)。平衡策略:

- 高频低重要决策:用规则(便宜)
- 低频高重要决策:用 LLM(昂贵但真实)
- 关键决策:多模型投票(更贵但更可信)

---

## 4.12　扩展:智能体的伦理与隐私

### 4.12.1　合成智能体的伦理

即使智能体是合成的,也要考虑伦理:

- 不使用真实人的姓名(除非授权)
- 不涉及敏感特征(种族、宗教、性取向)
- 不生成歧视性内容

### 4.12.2　数据匿名化

公开智能体数据时,需要匿名化:

```python
def anonymize_agent(agent: dict) -> dict:
    """匿名化单个 agent"""
    return {
        "id": agent["id"],
        "name": f"Agent_{agent['id']:04d}",  # 用 ID 替代名字
        "age_bucket": age_to_bucket(agent["age"]),  # 年龄分桶
        "region": agent["region"],  # 区域可以保留
        "income_bucket": income_to_bucket(agent["income"]),  # 收入分桶
        # 移除其他识别信息
    }
```

### 4.12.3　Persona Distillation 的伦理

从真人蒸馏(Persona Distillation)需要明确授权:

- 用户主动提供姓名或网址
- 蒸馏结果明确标注"基于 {来源}"
- 部署前需要 review

### 4.12.4　智能体决策的责任

智能体决策有"伦理责任"问题:

- 谁为 LLM 的歧视性决策负责?
- 谁为 LLM 编造的事实负责?
- 谁为 LLM 的"事后解释"负责?

研究者必须明确这些责任,并在论文里声明。

---

## 4.13　本章小结(扩展版)

- 智能体的工程实现包括存储、索引、更新、批处理。
- 决策策略的混合实现是工程实践的核心。
- 元决策决定"用哪种策略"本身也是决策。
- 智能体的伦理与隐私需要主动处理:匿名化、授权、责任声明。

