# 第 10 章　实验设计：单因子、析因与平行世界

> 预注册协议写好了,接下来是"怎么把它变成可执行的实验"。社会仿真的实验设计和传统实验设计有相通之处(对照、随机化、重复),也有不同之处(平行世界、群体模式、快进)。这一章讨论四种常见设计:**单因子 A/B**、**析因设计**、**平行世界**、**群体模式**。每种设计都给出 GAWorld 实现 + 代码示例 + 适用场景。读完本章,读者应该能根据预注册协议,选择合适的实验设计。

---

## 10.1　A/B 与时间对照:最简单的入门设计

**A/B 设计**(也称单因子设计)是最简单的实验设计:两个条件,一个变量变化。适合"我想看 X 政策是否有效"这种问题。

**时间对照**(temporal control)是 A/B 的一个变体:用"同一群体在事件前 vs 事件后"做对照。适合"已经发生的事件"。

### 一个 A/B 设计的完整流程

研究问题:限行令是否减少私家车出行?

```
世界 A (control): 不实施限行
世界 B (treatment): 实施限行
其他一切条件相同
跑 5 个种子 × 2 个世界 = 10 次仿真
```

GAWorld 实现:

```bash
python generative_city_sim.py parallel-worlds \
  --spec worlds.json \
  --output output/limit_AB

# worlds.json:
{
  "worlds": [
    {"name": "control", "events": []},
    {"name": "limit", "events": [{"name": "limit_weekday", "day": 30}]}
  ],
  "days": 180,
  "seeds": [42, 123, 456, 789, 1000],
  "size": 1000
}
```

跑完后,比较 control 和 limit 两个世界的 car_trips_per_capita 指标:

```python
# examples/analyze_AB.py
import pandas as pd

df_control = pd.read_csv("output/limit_AB/world_control_s42/state_history.csv")
df_limit = pd.read_csv("output/limit_AB/world_limit_s42/state_history.csv")

# 计算每日人均驾车次数
control_car = df_control.groupby("day")["car_trips"].sum() / 1000
limit_car = df_limit.groupby("day")["car_trips"].sum() / 1000

# 比较实施后的均值
post_control = control_car[30:].mean()
post_limit = limit_car[30:].mean()
effect = (post_limit - post_control) / post_control
print(f"限行后人均驾车:control={post_control:.2f}, limit={post_limit:.2f}, 效应={effect:+.2%}")
```

A/B 设计的优点是简单、清晰、易解释。缺点是只能回答"是否有效",不能回答"为什么有效"——这是析因设计的任务。

---

## 10.2　析因设计:2×2 与交互效应

**析因设计**(factorial design)是同时操纵多个变量,看它们的**交互效应**。最常见的是 2×2 设计(两个变量,每个两水平)。

**例子:限行令 × 公共交通补贴**

```
2 × 2 设计:
因素 A: 限行令 (有 / 无)
因素 B: 公共交通补贴 (有 / 无)

四个条件:
  W1: 无限行,无补贴 (control)
  W2: 限行,无补贴
  W3: 无限行,有补贴
  W4: 限行,有补贴 (双重干预)
```

跑 4 个世界 × 5 个种子 = 20 次仿真。分析:

```
主效应 A(限行): W2 + W4 vs W1 + W3
主效应 B(补贴): W3 + W4 vs W1 + W2
交互效应 A×B: (W4 - W2) - (W3 - W1)
```

如果交互效应显著大于 0,说明"限行 + 补贴"产生了协同效应——单独做限行没什么用,但加上补贴,效果放大。这是政策评估里非常常见但重要的发现。

### 一个完整的 2×2 设计示例

研究问题:限行令 + 补贴对低碳出行的协同效应?

```python
# examples/factorial_design.py
import pandas as pd
import numpy as np

# 跑 4 个世界 × 5 种子,得到 20 次仿真的低碳出行占比
results = {
    "W1_control": [],   # 无限行,无补贴
    "W2_limit":   [],   # 限行,无补贴
    "W3_subsidy": [],   # 无限行,有补贴
    "W4_both":    [],   # 限行 + 补贴
}

# 假设已跑完仿真,读入结果
# results["W1_control"] = [0.30, 0.31, 0.29, 0.32, 0.30]  # 5 个种子

# 计算主效应和交互效应
def main_effect(group_A, group_B):
    return np.mean(group_A + group_B) - np.mean(group_A + group_B)  # 简化

# 主效应 A(限行)
a_effect = np.mean(results["W2_limit"] + results["W4_both"]) - \
           np.mean(results["W1_control"] + results["W3_subsidy"])
# 主效应 B(补贴)
b_effect = np.mean(results["W3_subsidy"] + results["W4_both"]) - \
           np.mean(results["W1_control"] + results["W2_limit"])
# 交互效应 A×B
interaction = (np.mean(results["W4_both"]) - np.mean(results["W2_limit"])) - \
              (np.mean(results["W3_subsidy"]) - np.mean(results["W1_control"]))

print(f"主效应 A(限行):  {a_effect:+.3f}")
print(f"主效应 B(补贴):  {b_effect:+.3f}")
print(f"交互效应 A×B:    {interaction:+.3f}")
```

### 析因设计的成本与扩展

2×2 设计是入门,但可以扩展到 3×3、2×2×2 等。计算量随因素数指数增长:

| 设计 | 条件数 | 推荐规模(条件 × 种子) | 总仿真次数 |
|---|---|---|---|
| 2 × 2 | 4 | 4 × 5 | 20 |
| 3 × 3 | 9 | 9 × 5 | 45 |
| 2 × 2 × 2 | 8 | 8 × 5 | 40 |
| 3 × 3 × 3 | 27 | 27 × 3 | 81 |

经验法则:**因素不超过 3 个,每个因素不超过 3 水平**。再多就建议用**部分因子设计**(fractional factorial),只跑关键的几个条件。

---

## 10.3　平行世界:同源多事件、多结果与分叉度

**平行世界**(parallel worlds)是 GAWorld 的特色设计:一次实验最多 8 个世界,共用同一批居民、种子、天数、模型,各带自己的事件表。报告给出"逐步偏离度、分叉点与逐人影响"。

平行世界和 A/B、析因的区别:

| 设计 | 条件数 | 输出 | 适用问题 |
|---|---|---|---|
| A/B | 2 | 平均差异 | 是否有效 |
| 析因 | 4+ | 主效应 + 交互 | 为什么有效 |
| **平行世界** | **8** | **分叉度 + 分叉点 + 逐人影响** | **谁被改变了** |

平行世界擅长回答"哪些条件导致哪些个体被显著影响"——这是 A/B 和析因回答不了的"异质性"问题。

### 一个平行世界示例

研究问题:不同政策组合对不同人群的差异化影响?

```
W1: control(无干预)
W2: 限行(无补偿)
W3: 限行 + 小额补贴
W4: 限行 + 大额补贴
W5: 限行 + 公交扩建
W6: 限行 + 公交扩建 + 大额补贴
W7: 拥堵费(无补偿)
W8: 拥堵费 + 大额补贴
```

跑 8 个世界 × 5 个种子 = 40 次仿真。GAWorld 给出每个世界的"分叉度"曲线(随时间偏离 control 的程度)、分叉点(哪一天开始显著偏离)、逐人影响表(每个 agent 在每个世界下被如何影响)。

代码示例:

```bash
python generative_city_sim.py parallel-worlds \
  --spec policy_worlds.json \
  --output output/policy_8worlds
```

跑完后,用 `worlds.html` Dashboard 页面可视化对比。

### 分叉度的量化

GAWorld 用三种量化指标衡量世界之间的分叉:

**指标一:均值差**。世界 A 和世界 B 在第 t 天的关键指标均值差。

**指标二:KL 散度**。世界 A 和世界 B 在第 t 天的指标分布差异(衡量"分布形状"差异)。

**指标三:逐人变化率**。每个 agent 在两个世界中的状态变化超过阈值的比例。

这三种指标一起回答"世界分叉的程度"。读者写论文时,通常报告"均值差 + 分叉点 + 关键 agent 列表"。

---

## 10.4　群体模式与验证门 L1–L4

**群体模式**(cohort mode)是大规模仿真的成本优化方案:把人口划分成群体(每群 100+ 人),每群每天 1 次 LLM 调用;按预算实体化少数个体(典型 5–10 人全程跟踪)。这让 10000+ 人仿真的成本可控。

群体模式的核心思想:**多数 agent 的具体决策不重要,关键 agent 的具体决策很重要**。多数 agent 用群体代表(汇总行为),少数关键 agent 用个体(LLM 决策)。这在管理学和经济学里叫"代表性抽样 + 个案深挖"。

GAWorld 的群体模式命令:

```bash
python -m gaworld.group --size 500 --days 7 --no-llm
# → 不调用 LLM,纯规则群体仿真(用于快速验证)
# 加上 --llm: 群体仿真 + 关键 agent 实体化(更接近生产)
# --focal 7,42: 指定全程跟踪 agent 7 和 42
# --network-coupling 0.7: 打开网络耦合
```

### 群体模式的验证门 L1–L4

群体模式简化了行为,**可能**失真。所以需要"验证门"(validation gate)——一组配对实验,量化简化造成的代价。

**L1 门:行为分布对比**。跑同一仿真,一群用群体模式,一群用全实体化模式。比较关键指标的分布(均值、标准差、分位数)。如果差异 < 5%,通过 L1。

**L2 门:网络耦合对比**。开网络耦合(社交图传播)再跑一次。如果群体模式下传播效应失真 > 10%,**不通过**——群体模式不能用于网络传播研究。

**L3 门:政策效应对比**。同一政策在两种模式下跑,看效应估计的偏差。如果偏差 > 10%,**不通过**——群体模式不能用于政策评估。

**L4 门:长期动态对比**。跑 1 年或更长,看长期趋势是否一致。如果群体模式过早"趋同"或"发散",**不通过**。

L1 是入门,L4 是金标准。GAWorld 的 `gaworld/group.validate` 子命令会自动跑完这四道门,给出"能回答哪类研究问题"的结论:

```bash
python -m gaworld.group.validate --size 100 --days 14 --network-coupling 0.7
```

输出示例:

```
=== L1 行为分布对比 ===
✓ 通过(均值差 < 5%)

=== L2 网络耦合对比 ===
✓ 通过(传播效应偏差 < 10%)

=== L3 政策效应对比 ===
✗ 未通过(限行效应估计偏差 14%)

=== L4 长期动态对比 ===
⚠️  警告(群体模式 6 个月后偏差 > 15%)

结论: 群体模式适用于:
  ✓ 短期(< 3 个月)
  ✓ 不依赖网络传播
  ✗ 不适用于政策评估
  ✗ 不适用于长期仿真
```

读者用群体模式前,**必须**跑验证门。验证门不通过的结论,论文里不应该用群体模式的数据。

---

## 10.5　快进、长时段与折算规则

社会仿真需要跨越不同时间尺度。GAWorld 用三种模式应对:

**模式一:快进**(fast-forward)。把"日内时刻循环"压缩成"每个 agent 每天一条简报",跳过 tick-by-tick 决策。适合 60–600 天长期仿真。

```bash
python generative_city_sim.py run --sim-days 600 --fast-forward
```

**模式二:大跨度**(long-run)。一步 = 一个月或一年,适合 10 年、50 年、100 年研究。

```bash
python generative_city_sim.py run --sim-years 10
```

**模式三:折算**(compression)。把日级决策的 LLM 调用结果"折算"成月级或年级效应——通常用"趋势外推"或"分阶段抽样"。

### 折算规则的真实数据校验

仿真里的快进和大跨度,**可能**丢失细节。校验方法是用真实数据反推:

1. 跑 180 天精细仿真,得到 car_trips_per_capita 日级曲线
2. 把日级数据"折算"成月级均值
3. 用真实城市的月度出行数据(交通部月度报告)校验
4. 如果折算误差 < 5%,折算规则可信

这一步称为**backtest**(回溯测试)。读者做长跨度仿真时,**必须**做 backtest。

---

## 10.6　一个完整的实验设计工作流

把本章内容整合起来,推荐读者按以下流程设计实验:

```
[1] 预注册(第 9 章)
    ↓
[2] 选择实验设计
    - 简单 A/B → 政策效应
    - 析因 → 机制识别
    - 平行世界 → 异质性
    - 群体模式 → 大规模 + 简化
    - 快进/大跨度 → 长期
    ↓
[3] 估算成本
    仿真数 = 条件数 × 种子数
    单次仿真成本 = 人口 × 天数 × 决策频次 × 单次成本
    总成本 = 仿真数 × 单次仿真成本
    ↓
[4] 跑验证门(群体模式才需要)
    ↓
[5] 跑实验
    ↓
[6] 分析:均值差 / 析因 / 分叉度 / 群体对比
    ↓
[7] 报告:严格按预注册的判定规则
```

### 一个完整工作流示例:远程办公对城市碳排放的影响

研究问题:远程办公对城市碳排放的影响?

**预注册**:
- 条件 W1: 无远程办公
- 条件 W2: 部分远程办公(20% 员工每周 2 天)
- 条件 W3: 完全远程办公(100% 员工每周 5 天)
- 假设 H1: 远程办公比例越高,城市交通碳排放越低
- 指标: city_traffic_carbon
- MDE: -10%

**设计选择**:3 个条件 × 5 种子 = 15 次仿真。析因 + 时间对照。

**成本估算**:
- 1000 人 × 365 天 × 日级步长 × LLM 调用 = ~36 万次
- 乘以 15 次仿真 = 540 万次 LLM 调用
- 用 GPT-4o-mini:$0.15/M tokens × 平均 500 tokens/次 = $0.075/次
- 总成本:540 万 × $0.075 ≈ $40,500

太贵。**改用快进**:`--fast-forward` 让每人每天只 1 次 LLM 调用,每天 LLM 调用降为 36 万次,总成本 ~$2700。可接受。

**实验**:跑 15 次仿真,180 天(够长又不太贵)。

**分析**:W2 vs W1、W3 vs W2、W3 vs W1 三组对比,看效应是否单调。

**报告**:严格按预注册,只报告 city_traffic_carbon 指标 + 预注册过的辅助指标。

---

## 10.7　本章小结

- A/B 设计是最简单的入门设计,适合"是否有效"问题。
- 析因设计(2×2 起)适合"为什么有效"问题,可识别主效应和交互效应。
- 平行世界适合"谁被改变了"问题,GAWorld 用分叉度、分叉点、逐人变化率三个指标衡量。
- 群体模式是大规模仿真的成本优化,但需要 L1–L4 验证门确认不失真。
- 快进和大跨度适合长期仿真,但需要 backtest 校验折算规则。
- 完整的实验设计工作流:预注册 → 选设计 → 估算成本 → 验证门 → 跑 → 分析 → 报告。

---

## 10.8　思考题

1. **为一个研究问题选择设计**:你关心"延迟退休政策对代际财富转移的影响"。A/B、析因、平行世界、群体模式哪个最合适?为什么?
2. **设计一个 2×2 实验**:两个自变量(工伤保险覆盖率 × 最低工资),四个条件,3 个假设。完整写出预注册 + 实验设计。
3. **用群体模式前的判断**:你的研究问题能用群体模式吗?为什么?需要跑哪些验证门?
4. (进阶)**为限行令案例做 backtest**:用真实城市限行前后的出行数据(可从公开数据找到),校验仿真里的折算规则是否可信。

---

## 10.9　延伸阅读

1. Cohen, J. (1988). *Statistical Power Analysis for the Behavioral Sciences*. Lawrence Erlbaum.
2. Montgomery, D. C. (2017). *Design and Analysis of Experiments*. Wiley. —— 实验设计的标准教材。
3. Railsback, S. F., & Grimm, V. (2019). *Agent-Based and Individual-Based Modeling: A Practical Introduction*. Princeton University Press.
4. Grimm, V., et al. (2020). *The ODD Protocol for Describing Agent-Based Models: A First Update*. *JASSS*, 23(2). —— ODD 协议,描述仿真模型的标准格式。
5. Bonabeau, E. (2002). Agent-Based Modeling: Methods and Techniques for Simulating Human Systems. *PNAS*, 99(3), 7280–7287.
6. GAWorld 工程文档:`gaworld/group/`、`docs/PARALLEL_WORLDS_TUTORIAL.md`、`docs/DEMAND_EXPERIMENT.md`。
7. Box, G. E. P., Hunter, J. S., & Hunter, W. G. (2005). *Statistics for Experimenters*. Wiley. —— 实验统计的经典。
8. Edmonds, B., & Hales, D. (2010). Replication, Replication and Replication: Some Hard Lessons from Simple Models. In *Simulating Social Complexity*.

---

> **本章教学注释**
>
> 这一章是方法层第二章,实验设计是从预注册到结果的桥梁。读者如果做研究,**必须**理解这四种设计的适用边界——选错设计会让结论失效。
>
> 10.4 节的"验证门 L1–L4"是 GAWorld 的核心工程创新之一。读者在大规模仿真前,**必须**跑验证门——这是论文能发表的前提。GAWorld 的 `gaworld/group.validate` 命令会自动跑完四道门,建议读者把它作为大规模仿真的"前置检查"。
>
> 10.5 节的 backtest 是长跨度仿真的关键步骤。读者做 10 年、50 年、100 年研究时,**必须**用真实数据校验折算规则——否则结论是空中楼阁。
>
> 10.6 节的"远程办公对城市碳排放的影响"是一个真实的研究问题,展示了完整工作流。读者可以照这个格式做自己的研究。下一章讨论"数据分析":从原始日志到统计推断到可视化,数据怎么变成结论。
---

## 10.10　扩展:实验设计的细节与陷阱

本节深入讨论实验设计的细节和常见陷阱。

### 10.10.1　混杂变量的控制

实验设计的关键是**控制混杂变量**。常见混杂:

- **时间趋势**:仿真里的季节效应
- **群体差异**:不同 agent 的初始状态
- **网络结构**:社会网络的不同

控制方法:

- **随机化**:把 agent 随机分配到不同条件
- **匹配**:在不同条件里匹配相似 agent
- **协变量调整**:在分析时控制混杂变量

### 10.10.2　样本量与功效分析

功效分析(power analysis)决定"能不能检测到真实效应":

```python
# examples/power_analysis.py
from statsmodels.stats.power import TTestIndPower

def compute_power(effect_size: float, sample_size: int,
                 alpha: float = 0.05) -> float:
    """功效分析"""
    analysis = TTestIndPower()
    power = analysis.power(effect_size=effect_size,
                          nobs1=sample_size,
                          alpha=alpha)
    return power

# 限行效应 -0.24,样本量 5(种子),Cohen's d ~ 2.0
power = compute_power(effect_size=2.0, sample_size=5)
print(f"功效:{power:.2%}")
# 功效 > 80%,说明能检测到
```

### 10.10.3　平衡设计与非平衡设计

**平衡设计**:每个条件样本量相同。最常用。

**非平衡设计**:不同条件样本量不同。某些场景更经济。

经验法则:**平衡优先**。

### 10.10.4　重复测量 vs 独立测量

**重复测量**:同一 agent 测量多次。适合"追踪个体变化"。

**独立测量**:不同 agent 独立测量。适合"群体效应"。

GAWorld 默认是"独立测量"。要做重复测量,需要标记 agent。

---

## 10.11　扩展:析因设计的细节

### 10.11.1　主效应与交互效应

析因设计分析两个层次:

**主效应**:每个因素单独的效应。
**交互效应**:因素间的协同效应。

例:2×2 设计

| | B0 | B1 |
|---|---|---|
| A0 | 5 | 95 |
| A1 | 50 | 110 |

主效应 A = (50+110)/2 - (5+95)/2 = 30
主效应 B = (95+110)/2 - (5+50)/2 = 75
交互效应 = (110-50) - (95-5) = -30

### 10.11.2　部分因子设计

3 因素 × 3 水平 = 27 个条件,太多。可以用**部分因子设计**(fractional factorial):

- 选 9 个条件代表 27 个
- 用正交表设计
- 主效应和低阶交互可估

### 10.11.3　响应曲面设计

析因设计只能看离散水平,**响应曲面设计**(response surface)能看连续效应:

- 中心组合设计(Central Composite Design)
- Box-Behnken 设计

适合"找最优参数"的场景。

---

## 10.12　扩展:平行世界的工程实现

### 10.12.1　种子策略

平行世界里,种子管理有几种策略:

- **同种子多世界**:同种子,不同事件 → 干净对照
- **多种子单世界**:多种子,同事件 → 估计噪声
- **多种子多世界**:两种都做 → 最完整

### 10.12.2　事件调度

事件时间调度:

- **同时事件**:所有世界同时发生
- **顺序事件**:按预设顺序
- **随机事件**:随机时间

### 10.12.3　状态隔离

每个平行世界必须有独立状态:

- 独立的 agent 状态
- 独立的经济系统
- 独立的社会网络

### 10.12.4　结果合并

跑完多个世界后,合并结果:

```python
# examples/merge_worlds.py
def merge_world_results(world_dirs: list) -> pd.DataFrame:
    """合并多个世界的仿真结果"""
    dfs = []
    for d in world_dirs:
        df = pd.read_csv(f"{d}/state/agent_state_history.csv")
        df["world"] = d.split("/")[-1]
        dfs.append(df)
    return pd.concat(dfs)
```

---

## 10.13　扩展:群体模式的细节

### 10.13.1　群体代表的设计

群体代表如何"代表"群体?

- 平均化:用群体的平均状态
- 典型化:选一个典型 agent
- 多样化:用多个代表

GAWorld 默认用"典型化"——选 5–10 个代表,涵盖职业、收入、家庭。

### 10.13.2　关键 agent 的选择

关键 agent 是"全程跟踪"的个体。选择标准:

- 覆盖关键变量(不同收入、职业、家庭)
- 数量适中(5–10 个)
- 标记后不可变

### 10.13.3　群体决策的模拟

群体决策 ≠ 个体决策的平均:

- 群体决策有"集体思考"效应
- 个体决策有"个体独特性"

仿真里,群体决策用一个 LLM 调用,代表群体的"集体反应"。

### 10.13.4　验证门的实现细节

验证门 L1–L4 的实现:

```python
# examples/validation_gate.py
def validation_gate_l1(cohort_csv: str, full_csv: str, metric: str) -> bool:
    """L1: 行为分布对比"""
    cohort_data = pd.read_csv(cohort_csv)
    full_data = pd.read_csv(full_csv)
    cohort_mean = cohort_data[metric].mean()
    full_mean = full_data[metric].mean()
    diff = abs(cohort_mean - full_mean) / full_mean
    return diff < 0.05
```

---

## 10.14　扩展:快进与长时段的细节

### 10.14.1　快进的折算规则

快进把"日内循环"压缩成"每日 1 次 LLM 调用":

- 输入:agent 状态 + 处境
- 输出:今日决策(简化版)
- 后续:基于决策更新状态

### 10.14.2　长时段的折算

长时段把"日级循环"压缩成"月级循环":

- 输入:agent 月度汇总状态
- 输出:月度里程碑(2–4 个)
- 后续:基于里程碑更新状态

### 10.14.3　折算误差的控制

折算会引入误差,需要控制:

- 用真实数据回测折算误差
- 误差 > 10% 时调整折算规则
- 误差 < 5% 时折算可信

---

## 10.15　扩展:实验设计的工程实践

### 10.15.1　实验设计文档

每个实验应该有"实验设计文档":

```yaml
experiment:
  name: 限行令差异化影响
  design: 6 conditions × 5 seeds
  total_runs: 30
  estimated_cost: 2700 CNY
  estimated_time: 4 hours
preregistration:
  conditions: [W1_control, W2_placebo, W3_limit, W4_subsidy, W5_transit, W6_full]
  hypotheses: [H1, H2, H3, H4, H5]
  metrics: [...]
  judge_rules: [...]
```

### 10.15.2　实验运行脚本

```bash
#!/bin/bash
set -e
echo "实验开始: $(date)"
python generative_city_sim.py parallel-worlds \
  --spec spec.json --output output/case
echo "实验完成: $(date)"
```

### 10.15.3　实验日志

```yaml
run_id: case_2026_09_26_42
start_time: 2026-09-26 14:30:00
end_time: 2026-09-26 18:25:00
duration: 3h 55min
seed: 42
worlds: 6
runs_per_world: 5
total_calls: 30
total_cost: 2687.50 CNY
errors: 0
warnings: 3
```

### 10.15.4　实验对比

多次实验的对比:

```python
# examples/experiment_compare.py
def compare_experiments(exp1_csv: str, exp2_csv: str) -> dict:
    """两次实验的对比"""
    df1 = pd.read_csv(exp1_csv)
    df2 = pd.read_csv(exp2_csv)
    return {
        "exp1_mean": df1["metric"].mean(),
        "exp2_mean": df2["metric"].mean(),
        "diff": abs(df1["metric"].mean() - df2["metric"].mean())
    }
```

---

## 10.16　本章小结(扩展版)

- 实验设计的细节:混杂变量控制、样本量功效、平衡设计、重复测量。
- 析因设计:主效应与交互效应、部分因子设计、响应曲面设计。
- 平行世界工程:种子策略、事件调度、状态隔离、结果合并。
- 群体模式:群体代表、关键 agent、群体决策、验证门实现。
- 快进与长时段:折算规则、回测验证、误差控制。
- 工程实践:设计文档、运行脚本、实验日志、实验对比。


---

## 10.17　扩展:实验设计的工程细节

### 10.17.1　实验编号与命名

每个实验应该有清晰的命名:

```yaml
experiment_id: exp_2026_09_26_limit_AB
date: 2026-09-26
topic: 限行令 A/B 对照
design: 2 conditions × 5 seeds
researcher: cw
```

### 10.17.2　实验元数据

每次实验都记录元数据:

```python
experiment_metadata = {
    "id": "exp_2026_09_26_limit_AB",
    "start_time": "2026-09-26 14:30",
    "end_time": "2026-09-26 18:25",
    "duration_hours": 3.92,
    "conditions": ["W1_control", "W2_limit"],
    "seeds": [42, 123, 456, 789, 1000],
    "agents": 1000,
    "days": 180,
    "llm_calls": 36000,
    "cost_usd": 2700,
    "outcome": "success",
    "errors": 0
}
```

### 10.17.3　实验对比

多次实验的结果对比:

```python
def compare_experiments(exp1_id: str, exp2_id: str) -> dict:
    """两次实验的对比"""
    r1 = load_experiment_results(exp1_id)
    r2 = load_experiment_results(exp2_id)
    return {
        "exp1_effect": r1["effect"],
        "exp2_effect": r2["effect"],
        "diff": abs(r1["effect"] - r2["effect"]),
        "stable": abs(r1["effect"] - r2["effect"]) < 0.05
    }
```

### 10.17.4　实验模板

常见实验模板:

```yaml
# template_A_B.yaml
name: A/B 对照
conditions:
  - control
  - treatment
seeds: 5
default_agents: 1000
default_days: 180
metrics_required: [car_trips_per_capita]
```

```yaml
# template_2x2.yaml
name: 2x2 析因
conditions:
  - W1_control
  - W2_factor_A_only
  - W3_factor_B_only
  - W4_both
seeds: 5
default_agents: 1000
default_days: 180
```

---

## 10.18　扩展:实验运行的最佳实践

### 10.18.1　先小后大

实验规模要从"先小后大":

1. **预实验**:30 人 × 7 天,验证流程
2. **小规模**:300 人 × 30 天,验证假设
3. **中等规模**:1000 人 × 90 天,验证效应
4. **大规模**:1000 人 × 365 天,验证长期

### 10.18.2　先单后多

实验设计要从"先单后多":

1. **单因子**:先看单因子效应
2. **双因子**:加第二个因素,看交互
3. **多因子**:逐步扩展
4. **平行世界**:多事件组合

### 10.18.3　先确定性后随机性

实验要从"先确定性后随机性":

1. **固定种子**:先验证逻辑
2. **多种子**:验证稳定性
3. **完全随机**:验证推广性

### 10.18.4　先离线后在线

实验运行要从"先离线后在线":

1. **纯规则**:先验证规则逻辑
2. **小规模 LLM**:验证 LLM 决策
3. **全规模 LLM**:完整仿真
4. **在线同步**:实时仿真孪生

---

## 10.19　扩展:实验结果的交叉验证

### 10.19.1　多指标交叉验证

同一假设用多个指标验证:

```python
def cross_validate_hypothesis(hypothesis: dict, metrics_results: dict) -> dict:
    """用多个指标交叉验证假设"""
    metric_results = []
    for metric in hypothesis["metrics"]:
        result = metrics_results[metric]
        supports = result["ci_low"] > hypothesis["mde"]
        metric_results.append({
            "metric": metric,
            "supports": supports
        })
    # 多数原则
    n_supports = sum(1 for r in metric_results if r["supports"])
    return {
        "metrics": metric_results,
        "n_supports": n_supports,
        "n_total": len(metric_results),
        "hypothesis_supported": n_supports >= len(metric_results) / 2
    }
```

### 10.19.2　多方法交叉验证

同一假设用不同方法验证:

- 平行世界方法
- 析因方法
- 时间序列方法
- 反事实方法

如果多个方法都给出一致结论,假设可信度高。

### 10.19.3　多模型交叉验证

同一假设用不同 LLM 模型验证:

- GPT-4
- Claude
- Gemini

如果多个模型都给出一致结论,假设可信度高。

### 10.19.4　跨学科交叉验证

同一假设用不同学科的视角验证:

- 社会学(机制)
- 经济学(成本收益)
- 心理学(个体差异)
- 政策学(实施可行性)

---

## 10.20　本章小结(最终扩展版)

- 实验编号、命名、元数据、对比、模板是工程基础。
- 最佳实践:先小后大、先单后多、先确定性后随机性、先离线后在线。
- 交叉验证:多指标、多方法、多模型、跨学科。

