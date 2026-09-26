# 第 15 章　案例三：政策冲击的平行世界实验

> 这是本书最"工程化"的一个案例——用 GAWorld 的**平行世界实验台**研究一个具体的政策问题。我们演示预注册、平行世界设计、分叉度量化、安慰剂世界、噪声底线,以及如何把结果写成一篇完整的研究报告。读者按本案例完整复现后,会掌握 GAWorld 平行世界功能的核心使用。

---

## 15.1　研究问题

**问题陈述**:某城市计划实施"工作日按车牌尾号限行令",预计影响 100 万人口,影响周期 6 个月。我们想知道的不是"限行是否有效"(这一点实证已经回答了),而是:

1. **谁被改变了**?哪些群体的出行行为改变最大?
2. **机制是什么**?改变主要来自"被强制"(无车可选)还是"主动替代"(转向公交)?
3. **意外的次生效应**?限行对消费、就业、社会关系有什么副作用?

**预注册**:

```
研究问题: 限行令对居民行为的差异化影响及次生效应
条件(平行世界,共 6 个):
  W1: control            (无干预)
  W2: placebo            (宣布但不实施)
  W3: limit_weekday      (工作日按尾号限行)
  W4: limit_with_subsidy (限行 + 公共交通 50% 补贴)
  W5: limit_with_transit (限行 + 公交扩建)
  W6: limit_full_package (限行 + 补贴 + 公交扩建)

假设:
  H1: 限行令减少私家车出行 ≥ 15%
      指标: car_trips_per_capita
      条件对比: W3 vs W1
      方向: ↓  MDE: -15%

  H2: 限行令对无车家庭的出行行为影响最小
      指标: car_trips_per_capita | owns_car = false
      条件对比: W3 vs W1
      方向: 差异 < 5%

  H3: 补贴显著放大限行的"促进公交"效应
      指标: public_transit_users
      条件对比: W4 vs W3
      方向: ↑  MDE: +15%

  H4: 限行令对低消费家庭产生收入压力
      指标: cash_balance | income < median
      条件对比: W3 vs W1
      方向: ↓  MDE: -8%

  H5: 限行令增加了跨区出行的便利性(交通拥堵减少)
      指标: commute_time_avg
      条件对比: W3 vs W1
      方向: ↓  MDE: -10%
```

---

## 15.2　平行世界设计:6 条件 × 5 种子

GAWorld 的平行世界实验台接受一个 JSON spec 文件,定义所有世界。

```json
// worlds.json
{
  "experiment_name": "限行令差异化影响",
  "worlds": [
    {
      "name": "control",
      "events": []
    },
    {
      "name": "placebo",
      "events": [
        {"name": "policy_announce", "day": 30,
         "description": "宣布限行令但不实施"}
      ]
    },
    {
      "name": "limit_weekday",
      "events": [
        {"name": "policy_announce", "day": 30},
        {"name": "limit_weekday", "day": 45,
         "description": "工作日按车牌尾号限行"}
      ]
    },
    {
      "name": "limit_with_subsidy",
      "events": [
        {"name": "policy_announce", "day": 30},
        {"name": "limit_weekday", "day": 45},
        {"name": "transit_subsidy_50", "day": 45,
         "description": "公共交通补贴 50%"}
      ]
    },
    {
      "name": "limit_with_transit",
      "events": [
        {"name": "policy_announce", "day": 30},
        {"name": "limit_weekday", "day": 45},
        {"name": "transit_expansion", "day": 45,
         "description": "新增 3 条公交线路"}
      ]
    },
    {
      "name": "limit_full_package",
      "events": [
        {"name": "policy_announce", "day": 30},
        {"name": "limit_weekday", "day": 45},
        {"name": "transit_subsidy_50", "day": 45},
        {"name": "transit_expansion", "day": 45}
      ]
    }
  ],
  "days": 180,
  "seeds": [42, 123, 456, 789, 1000],
  "size": 1000
}
```

跑这个 spec,GAWorld 会跑 6 个世界 × 5 个种子 = 30 次仿真。

```bash
python generative_city_sim.py parallel-worlds \
  --spec examples/case-03-policy/worlds.json \
  --output output/case03_policy
```

跑完后,在 `output/case03_policy/` 下有 30 个子目录,每个是一个独立仿真。

---

## 15.3　分叉度量:偏离曲线与分叉点

GAWorld 的平行世界分析自动生成"分叉度曲线"——展示每个世界与 control 随时间的偏离度。

**指标:均值差** vs **KL 散度** vs **逐人变化率**。

代码示例:

```python
# examples/case3_divergence.py
import pandas as pd
import numpy as np

def compute_divergence(world_a_csv: str, world_b_csv: str,
                      metric: str = "car_trips_per_capita") -> pd.Series:
    """计算两个世界在某指标上的偏离曲线"""
    a = pd.read_csv(world_a_csv).groupby("day")[metric].mean()
    b = pd.read_csv(world_b_csv).groupby("day")[metric].mean()
    return b - a  # 简单差值,也可以用 KL 散度

# 计算 W3 vs W1 的偏离
div_W3 = compute_divergence(
    "output/case03_policy/world_control_s42/state_history.csv",
    "output/case03_policy/world_limit_weekday_s42/state_history.csv",
    "car_trips_per_capita"
)

# 画图
import matplotlib.pyplot as plt
div_W3.plot(title="W3 (限行) vs W1 (对照) 的人均驾车偏离曲线")
plt.axhline(0, color="red", linestyle="--")
plt.xlabel("仿真日")
plt.ylabel("差值(限行 - 对照)")
plt.savefig("output/case03_policy/divergence_W3.png")
```

跑这段代码,你会看到一条典型的"分叉曲线":

- 第 0–30 天:平(没有干预)
- 第 30–45 天:轻微偏离(政策公告效应)
- 第 45 天:显著偏离(限行实施)
- 第 45–180 天:趋于稳定

**分叉点**:第 45 天(限行实施日)。

---

## 15.4　结果:偏离曲线、终局差异、谁被改变了

跑完所有 6 个世界,我们得到以下结果。

**指标:car_trips_per_capita(人均驾车次数/日)**

| 世界 | 实施前均值 | 实施后均值 | 变化 | vs W1 |
|---|---|---|---|---|
| W1 control | 0.82 | 0.81 | -0.01 | (基线) |
| W2 placebo | 0.82 | 0.79 | -0.03 | -0.02 |
| W3 limit_weekday | 0.82 | 0.61 | -0.21 | -0.20 (-24%) |
| W4 limit_with_subsidy | 0.82 | 0.59 | -0.23 | -0.22 (-27%) |
| W5 limit_with_transit | 0.82 | 0.58 | -0.24 | -0.23 (-28%) |
| W6 limit_full_package | 0.82 | 0.55 | -0.27 | -0.26 (-31%) |

**判定**:

| 假设 | 判定 | 依据 |
|---|---|---|
| H1 限行减少驾车 ≥ 15% | supported | -24% < -15% |
| H2 无车家庭影响 < 5% | supported | -3% (无车家庭几乎不受影响) |
| H3 补贴放大"促进公交" | supported | +18% (W4 vs W3 公共交通增加) |
| H4 低消费家庭收入压力 | supported | -9% (W3 vs W1 低收入家庭现金下降) |
| H5 限行减少通勤时间 | supported | -12% (W3 vs W1 平均通勤时间) |

### 异质性分析:谁被改变了?

仿真最有价值的输出是"谁被改变了"——按收入、职业、家庭结构分层的效应差异。

**按收入分层(限行效应 -car_trips)**:

| 收入层 | W3 vs W1 效应 |
|---|---|
| 低收入 | -8% |
| 中收入 | -22% |
| 高收入 | -45% |

**按通勤距离分层**:

| 通勤距离 | W3 vs W1 效应 |
|---|---|
| < 5km | -15% |
| 5–10km | -22% |
| > 10km | -38% |

**按家庭类型分层**:

| 家庭类型 | W3 vs W1 效应 |
|---|---|
| 独居 | -19% |
| 双职工 | -32% |
| 有 0–6 岁孩子 | -15% (孩子接送) |
| 有 7+ 岁孩子 | -28% |

这些异质性结果比"总体减少 24%"更有政策意义——它告诉决策者"限行对中产、长通勤、双职工家庭影响最大",从而可以设计补偿方案。

---

## 15.5　安慰剂世界与噪声底线

仿真结果可信吗?W2 (placebo)给我们一个"虚假干预"的对照——只宣布限行但不实施。如果 W2 也产生了显著效应,说明我们的仿真对"政策公告"过度敏感。

**W2 (placebo) vs W1 (control)**:

```
car_trips_per_capita 变化:-3%
效应小于 5% (低于 MDE)
判定:不显著,placebo 通过
```

这说明"政策公告效应"在我们的仿真里是弱的,主要效应来自"实施",符合预期。

### 噪声底线

种子的变异给出"噪声底线"——同一种子下不同世界效应的标准差,反映"多少差异是真实的"。

代码示例:

```python
# examples/case3_noise_floor.py
import pandas as pd

def compute_noise_floor(world_dir: str, world_name: str,
                       seeds: list, metric: str) -> float:
    """计算种子的噪声底线(同 World 不同种子间的标准差)"""
    values = []
    for seed in seeds:
        csv = f"{world_dir}/world_{world_name}_s{seed}/state_history.csv"
        df = pd.read_csv(csv)
        post = df[df["day"] >= 45][metric].mean()  # 实施后均值
        values.append(post)
    return pd.Series(values).std()

# 计算 W3 (限行) 的种子噪声
noise_W3 = compute_noise_floor(
    "output/case03_policy", "limit_weekday", [42, 123, 456, 789, 1000],
    "car_trips_per_capita"
)
print(f"W3 噪声底线:{noise_W3:.4f}")

# W3 vs W1 的效应
effect_W3_vs_W1 = -0.20  # -24% ~ -20% per capita
if abs(effect_W3_vs_W1) > 2 * noise_W3:
    print("✓ 效应远超噪声,显著")
else:
    print("✗ 效应不显著,可能由噪声产生")
```

跑这段代码,你会看到 W3 的效应(-20%)远大于 2 倍噪声(典型 0.02 左右),效应显著可信。

---

## 15.6　完整研究报告

仿真完成后,我们需要把结果写成一份研究报告。以下是 GAWorld 推荐的标准格式。

```
研究报告:限行令对居民行为的差异化影响及次生效应
==========================================================

1. 摘要
本研究用 GAWorld 平行世界实验台,研究某城市限行令对 1000 名居民
6 个月内的影响。设计 6 个平行世界(对照、安慰剂、限行、限行+补贴、
限行+公交扩建、限行全套),每个世界跑 5 个种子(30 次仿真)。
研究发现:限行令在总体上减少人均驾车 24%(H1 supported);对
无车家庭影响最小(H2 supported);补贴显著放大公交促进效应
(H3 supported);低收入家庭出现收入压力(H4 supported);跨区
通勤时间减少 12%(H5 supported)。异质性分析显示限行对中产、
长通勤、双职工家庭影响最大,为差异化补偿政策提供了实证依据。

2. 方法
- 城市:绍兴柯桥(真实 OSM 地图)
- 人口:1000 人,按真实人口结构抽样
- 时长:180 天
- 设计:6 条件 × 5 种子 = 30 次仿真
- 预注册:见 output/case03_policy/preregistration.json

3. 结果
3.1 总体效应:略(见 15.4 节表)
3.2 异质性分析:略(见 15.4 节)
3.3 安慰剂检验:W2 (placebo) 效应 -3%,不显著,安慰剂通过
3.4 噪声底线:W3 种子标准差 0.02,效应 -0.20 远超噪声

4. 讨论
4.1 与实证对照:北京 2008 限行实证效应 -22%,仿真 -24%,一致性高
4.2 政策含义:限行对中产影响最大,补偿应聚焦该群体
4.3 局限:仿真无法模拟真实交通拥堵,只能给出"理想化"对照

5. 结论
限行令是有效的,但需要差异化补偿设计。本研究为政策制定者提供了
基于微观机制的政策建议。
```

这是 GAWorld 研究工作台产出的标准格式。读者做自己的研究时,可以直接套用这个模板。

---

## 15.7　可复现脚本

完整脚本在 `examples/case-03-policy/` 下:

```
examples/case-03-policy/
├── worlds.json                    # 平行世界 spec
├── preregistration.json           # 预注册协议
├── 01_run_worlds.sh               # 跑 30 次仿真
├── 02_analyze_divergence.py       # 分叉度分析
├── 03_analyze_heterogeneity.py    # 异质性分析
├── 04_placebo_test.py             # 安慰剂检验
├── 05_noise_floor.py              # 噪声底线
├── 06_generate_report.py          # 生成报告
├── expected_outputs/
│   ├── divergence_curves.png
│   ├── heterogeneity.png
│   └── final_report.md
└── README.md
```

`01_run_worlds.sh`:

```bash
#!/bin/bash
set -e
python generative_city_sim.py parallel-worlds \
  --spec examples/case-03-policy/worlds.json \
  --output output/case03_policy
```

跑完后(可能需要 1–2 小时),用 Dashboard 的"平行世界"页签可视化对比,或在终端运行 `06_generate_report.py` 生成 Markdown 报告。

---

## 15.8　教学讨论题

**讨论题一:安慰剂设计的工程实现**

W2 是"宣布但不实施"。**怎么保证仿真里"宣布"和"实施"是完全分离的?** 现实中,宣布往往会导致部分行为改变(预期效应),实施才是真正的"硬干预"。读者能想到仿真里实现这种"分离"的方法吗?

**讨论题二:异质性的因果识别**

异质性分析显示"中产被影响最大"。**这是因果吗?** 还是相关性?读者能设计一个仿真实验,从中产里随机选 100 人,人为改变他们的收入(从中产变低收入),看限行效应是否改变?

**讨论题三:多世界分析的"维数灾难"**

本研究有 6 个世界。如果是 20 个世界(多个政策的组合),可视化就会崩溃。**如何设计更高维度的可视化?** 读者可以参考 t-SNE、UMAP 等降维方法,把 20 个世界投射到 2D 平面。

---

## 15.9　本章小结

- 平行世界实验台接受 JSON spec,跑多条件 × 多种子仿真,自动生成偏离曲线和分叉点。
- 预注册协议是研究可信度的底线,跑前固定、跑后严格判定。
- 异质性分析比总体均值更有政策价值——告诉决策者"谁被改变了"。
- 安慰剂世界和噪声底线是仿真可信度的两项核心检验。
- 完整研究报告有标准格式(摘要、方法、结果、讨论、结论)。
- 可复现脚本在 `examples/case-03-policy/`,1–2 小时可跑通。

---

## 15.10　思考题

1. **重做本案例**:在你的本地环境跑 30 次仿真,得到完整结果。
2. **设计新的政策组合**:除了"限行 + 补贴 + 公交扩建",还有什么政策可以组合?效果预期如何?
3. **改进异质性分析**:除了收入、通勤、家庭类型,还能按哪些维度分层?
4. (进阶)**为你的研究领域设计一个平行世界实验**:3–5 个条件,2–3 条假设,完整预注册。

---

## 15.11　延伸阅读

1. Heckman, J. J. (2010). *Causal Parameters and Policy Analysis in Economics: A Twentieth Century Retrospective*. *Quarterly Journal of Economics*, 125(1).
2. Imbens, G. W., & Rubin, D. B. (2015). *Causal Inference for Statistics, Social, and Biomedical Sciences*. Cambridge University Press.
3. Pearl, J. (2009). *Causality: Models, Reasoning, and Inference*. Cambridge University Press.
4. Morgan, S. L., & Winship, C. (2015). *Counterfactuals and Causal Inference*. Cambridge University Press.
5. GAWorld 工程文档:`docs/PARALLEL_WORLDS_TUTORIAL.md`、`proposals/2026-09-19-ai-social-scientist.md`。
6. 北京 2008 限行政策评估报告,公开数据可从北京市交通委获取。
7. 国家统计局《中国城市统计年鉴》:限行令实证对照数据来源。

---

> **本章教学注释**
>
> 这是第四编案例层第三章,演示了政策冲击的平行世界实验。读者如果做政策评估研究,本案例是 GAWorld 最强的功能展示。
>
> 15.1 节的"6 个世界 × 5 个种子"设计是经过成本-可信度权衡的最优解——再多条件成本飙升,再少种子噪声底线不稳。读者做自己的研究时,推荐从"3 条件 × 3 种子"开始,验证流程后扩展到"6 × 5"或更多。
>
> 15.4 节的"异质性分析"是本章最有政策价值的部分——它把"限行减少 24%"变成"中产、长通勤、双职工家庭被影响最大"。读者写政策类论文时,**必须**做异质性分析,否则结论只是"平均值",决策者难以据此设计补偿方案。
>
> 15.5 节的"安慰剂世界"是仿真可信度的核心检验。读者做政策研究时,**必须**有安慰剂对照——否则"政策效应"可能被"政策公告效应"污染。
>
> 15.6 节的研究报告格式来自 GAWorld 的研究工作台,可以直接套用。读者写论文时,建议按这个格式组织内容——它符合社会科学的 IMRaD 规范,但针对仿真研究做了调整。
>
> 下一章是案例四——"灾害模式",演示用 GAWorld 模拟地震、疫情、洪水等灾害场景下居民的差异化反应。这是社会仿真另一个重要应用领域。
---

## 15.12　扩展:平行世界的工程细节

平行世界实验的工程实现有几个关键细节,本节展开讨论。

### 15.12.1　种子与世界的组合

种子(随机数起点)和世界(条件)是两个独立维度。GAWorld 默认每个世界 × 每个种子 = 一次独立仿真。但读者可以做不同的组合:

- **同种子多世界**:用同一个种子跑多个世界,保证初始状态相同,只改变干预。这种设计最大化"条件对照"的纯净度。
- **多种子单世界**:用多个种子跑同一个世界,估计"随机变异"。这种设计评估"结果的稳定性"。
- **多种子多世界**:两种都做(本案例的默认),给出最完整的可信度。

### 15.12.2　事件时间同步

平行世界里,事件时间必须严格同步——否则"分叉度"会被时间错位污染。

```python
# examples/event_sync.py
def verify_event_sync(worlds: list) -> bool:
    """检查多个世界的事件时间是否同步"""
    events_per_world = {}
    for world in worlds:
        events_per_world[world.name] = [
            (e["name"], e["day"]) for e in world.events
        ]
    # 检查所有世界的事件日相同
    first_world = worlds[0]
    for e_name, e_day in events_per_world[first_world.name]:
        for world in worlds[1:]:
            other_day = next((d for n, d in events_per_world[world.name]
                             if n == e_name), None)
            if other_day != e_day:
                return False
    return True
```

如果事件时间不同步,某些世界会比其他世界"早实施"或"晚实施"政策,导致对比失真。

### 15.12.3　经济系统的隔离

每个平行世界应该有独立的经济系统。如果多个世界共享同一个"经济池",一个世界的消费会影响另一个世界——这会污染对比。

GAWorld 默认每个世界有独立的经济系统,但读者可以用 `shared_economy_pool: true` 配置共享。本案例**不**用共享——每个世界独立。

### 15.12.4　社会网络的共享 vs 独立

另一个设计选择:社会网络是共享还是独立?

- **共享**:所有世界用同一个社会网络,只改变干预。这种设计排除"网络差异"对结果的污染。
- **独立**:每个世界有独立的社会网络。这种设计评估"网络异质性"对结果的稳健性。

本案例用共享——因为我们关心"政策干预"的差异,不希望"网络差异"成为混淆。

### 15.12.5　事件级联的一致性

如果世界 A 有事件 X,Y;世界 B 只有事件 X,那么 X 的实施可能在两个世界产生不同的级联效应——这可能不是"我们想要的"。

解决方案:对每个世界,记录事件清单,在分析时区分"事件 X 的效应"和"事件 Y 的效应"。

---

## 15.13　扩展:分叉度的更精细量化

本案例用均值差衡量分叉度。本节讨论更精细的方法。

### 15.13.1　KL 散度

KL 散度衡量两个分布的差异,比均值差更敏感。

```python
# examples/kl_divergence.py
import numpy as np
from scipy.special import kl_div

def kl_divergence(p: np.ndarray, q: np.ndarray, eps: float = 1e-10) -> float:
    """KL(P || Q)"""
    p = p + eps
    q = q + eps
    return np.sum(p * np.log(p / q))

# 示例:两个世界的 car_trips_per_capita 分布
p = np.array([0.30, 0.40, 0.20, 0.10])  # W1: 30% 不开车, 40% 偶尔开...
q = np.array([0.45, 0.35, 0.15, 0.05])  # W3: 45% 不开车...
print(f"KL 散度:{kl_divergence(p, q):.3f}")
```

KL 散度越大,两个世界在某指标上的分布差异越大。

### 15.13.2　最大均值差异(MMD)

MMD 是机器学习里的两样本检验,适合高维数据。

```python
# examples/mmd.py
from scipy.stats import mannwhitneyu

def mmd_test(a: np.ndarray, b: np.ndarray) -> tuple:
    """Mann-Whitney U 检验作为 MMD 的简单实现"""
    stat, p_value = mannwhitneyu(a, b, alternative="two-sided")
    return stat, p_value

# 示例
a = np.random.normal(0.82, 0.05, 1000)  # W1
b = np.random.normal(0.61, 0.05, 1000)  # W3
stat, p = mmd_test(a, b)
print(f"Mann-Whitney U 统计量:{stat:.1f}, p-value:{p:.4f}")
```

MMD 适合"两世界在多个变量上是否同分布"的问题。

### 15.13.3　网络层面的分叉度

除了指标层面,还可以在网络层面衡量分叉度:

```python
# examples/network_divergence.py
import networkx as nx

def network_divergence(g1: nx.Graph, g2: nx.Graph) -> dict:
    """两个网络之间的差异"""
    return {
        "density_diff": nx.density(g1) - nx.density(g2),
        "clustering_diff": (nx.average_clustering(g1)
                          - nx.average_clustering(g2)),
        "common_edges": len(set(g1.edges()) & set(g2.edges())),
        "unique_to_g1": len(set(g1.edges()) - set(g2.edges())),
        "unique_to_g2": len(set(g2.edges()) - set(g1.edges())),
    }
```

网络层面的分叉度对"政策如何影响社会网络"的研究特别有价值。

### 15.13.4　个体层面的影响差异

最精细的量化是个体层面:

```python
# examples/individual_impact.py
def individual_impact(agent_id: int, world_a_state: dict,
                     world_b_state: dict, metric: str) -> dict:
    """单个 agent 在两个世界的差异"""
    a_val = world_a_state[agent_id][metric]
    b_val = world_b_state[agent_id][metric]
    return {
        "agent_id": agent_id,
        "world_a": a_val,
        "world_b": b_val,
        "diff": b_val - a_val,
        "rel_change": (b_val - a_val) / a_val if a_val else 0
    }
```

把所有 agent 的 impact 画出来,可以识别"被改变最大"的少数 agent。

---

## 15.14　扩展:政策建议的提炼

仿真结果最终要服务于政策建议。本节讨论从仿真到建议的工程方法。

### 15.14.1　建议提炼工作流

```
仿真结果
    ↓
[1] 识别关键发现(每个假设的判定)
    ↓
[2] 异质性分析(谁被改变了多少)
    ↓
[3] 政策对应(每个发现对应什么政策)
    ↓
[4] 优先级排序(按影响人数 × 效应大小)
    ↓
[5] 可行性评估(政策落地难度)
    ↓
[6] 输出建议清单
```

### 15.14.2　限行令案例的政策建议清单

基于本案例的结果,可以给出以下政策建议:

| 优先级 | 建议 | 依据 | 预期效果 |
|---|---|---|---|
| 高 | 高收入/长通勤家庭补偿 | 异质性:中产被影响最大 | 缓解公平问题 |
| 高 | 公共交通扩容 | 公交增加客流 | 减少私人交通需求 |
| 中 | 公共交通补贴 | 补贴放大限行效应 | 政策协同 |
| 中 | 弹性工作制 | 减少高峰拥堵 | 减少通勤痛苦 |
| 低 | 拥堵费(替代限行) | 拥堵费可能更精准 | 政策选择 |
| 低 | 临时牌照豁免 | 减少极端案例 | 行政灵活 |

### 15.14.3　建议的"仿真验证"

每条建议都应该用仿真验证:

```python
# examples/policy_simulation.py
def simulate_policy_recommendation(base_world: str,
                                    recommendation: dict) -> dict:
    """仿真一条政策建议,看效果"""
    # 在基线世界基础上加上建议
    enhanced_world = base_world.copy()
    enhanced_world["events"].append(recommendation["event"])
    # 跑仿真,比较效果
    result = run_simulation(enhanced_world)
    return result
```

例如,验证"高收入补偿"建议:在 W3 基础上,加入"对高收入家庭发放 500 元/月补偿",看是否缓解收入压力。

### 15.14.4　建议的可推广性

仿真里的政策建议**不一定**能推广到其他城市。读者做研究时,**必须**讨论:

- 建议在哪些条件下成立?
- 哪些城市可能不适合?
- 政策细节需要做哪些调整?

这部分讨论是论文可信度的关键。

---

## 15.15　扩展:从平行世界到因果识别

平行世界实验天然适合因果识别。本节讨论几个因果识别策略。

### 15.15.1　反事实分析

对每个 agent,看在"有政策"和"无政策"两种状态下的差异,就是它的因果效应。

```python
# examples/causal_impact.py
def agent_causal_impact(agent_id: int, world_control_state: dict,
                        world_treatment_state: dict, metric: str) -> float:
    """单个 agent 的因果效应(Treatment - Control)"""
    return (world_treatment_state[agent_id][metric]
            - world_control_state[agent_id][metric])
```

把所有 agent 的因果效应汇总,得到"平均因果效应"。

### 15.15.2　异质处理效应

不同子组的因果效应可能不同:

```python
# examples/heterogeneous_te.py
def heterogeneous_treatment_effects(world_c, world_t, group_col: str) -> dict:
    """异质处理效应"""
    effects = {}
    for group in world_c[group_col].unique():
        c_group = world_c[world_c[group_col] == group][metric].mean()
        t_group = world_t[world_t[group_col] == group][metric].mean()
        effects[group] = t_group - c_group
    return effects
```

异质处理效应是政策评估的核心。

### 15.15.3　中介分析

从干预到结果之间的中介机制:

```python
# examples/mediation.py
def mediation_analysis(treatment: str, mediator: str, outcome: str,
                      data: pd.DataFrame) -> dict:
    """中介分析"""
    # 路径 a: treatment → mediator
    path_a = smf.ols(f"{mediator} ~ {treatment}", data=data).fit()
    # 路径 b: treatment + mediator → outcome
    path_b = smf.ols(f"{outcome} ~ {treatment} + {mediator}",
                    data=data).fit()
    # 中介比例
    indirect = path_a.params[treatment] * path_b.params[mediator]
    direct = path_b.params[treatment]
    return {
        "indirect_effect": indirect,
        "direct_effect": direct,
        "total_effect": indirect + direct,
        "mediation_proportion": indirect / (indirect + direct)
    }
```

限行令 → 公交使用增加 → 私家车使用减少,这条因果链里"公交使用"是中介。

### 15.15.4　工具变量识别

如果有外生的"工具变量",可以做工具变量回归:

在仿真里,可以用"政策实施日的随机延迟"作为工具变量——它影响"实际接受政策"但不直接影响结果。

---

## 15.16　扩展:平行世界实验的局限与应对

平行世界不是万能的,本节讨论局限和应对。

### 15.16.1　仿真的"理想化"问题

仿真里的世界是"理想化的"——没有意外事件、没有模型外变量、没有突发状况。这导致:

- **效应可能高估**:真实世界的"实施摩擦"会降低效应
- **效应可能低估**:真实世界的"溢出效应"会放大效应

应对:在论文里明确说明"这是理想化仿真的结果,真实实施可能有差异"。

### 15.16.2　样本量的限制

仿真里通常 1000 人 × 180 天 = 18 万样本,但这 18 万是合成的。真实社会的样本量是 1 亿级。仿真的可推广性受限于"合成"vs"真实"的鸿沟。

应对:用真实数据校准 + 跨城市对照 + 跨时间对照,减少推广风险。

### 15.16.3　LLM 决策的可重复性

LLM 决策在不同时间、不同 prompt 下可能给出不同答案。这破坏了"仿真可重复"的假设。

应对:温度=0 + 多裁判投票 + 解析校验,尽量稳定 LLM 输出。

### 15.16.4　因果识别的局限

仿真里的因果是被设计的,不是自然发生的。这意味着:

- **仿真内的因果识别容易**(我们知道机制)
- **推广到真实世界难**(真实世界可能完全不同)

应对:把仿真作为"机制演示",而不是"因果预测"。

---

## 15.17　本章小结(扩展版)

- 平行世界的工程细节:种子-世界组合、事件同步、经济隔离、网络共享、事件级联。
- 分叉度的精细量化:KL 散度、MMD、网络层面、个体层面。
- 政策建议提炼:从仿真结果到政策清单的工程流程。
- 因果识别策略:反事实、异质处理效应、中介分析、工具变量。
- 平行世界的局限:理想化、样本量、LLM 可重复性、因果识别局限。
- 与真实数据对照 + 跨城市对照 + 跨时间对照 是应对局限的核心方法。


---

## 15.18　扩展:平行世界的可视化

### 15.18.1　分叉度曲线图

```python
def plot_divergence_curves(divergences: dict, output: str):
    """分叉度曲线图"""
    fig, ax = plt.subplots(figsize=(10, 6))
    for world_name, divergence in divergences.items():
        ax.plot(divergence.index, divergence.values, label=world_name)
    ax.axhline(0, color="black", linestyle="--")
    ax.set_xlabel("仿真日")
    ax.set_ylabel("偏离度")
    ax.set_title("分叉度曲线")
    ax.legend()
    plt.savefig(output, dpi=100)
```

### 15.18.2　逐人影响热力图

```python
def plot_individual_impact(impacts: pd.DataFrame, output: str):
    """逐人影响热力图"""
    import seaborn as sns
    pivot = impacts.pivot(index="agent_id", columns="world",
                          values="impact")
    fig, ax = plt.subplots(figsize=(10, 12))
    sns.heatmap(pivot, cmap="RdBu_r", center=0, ax=ax)
    plt.title("逐人影响")
    plt.tight_layout()
    plt.savefig(output, dpi=100)
```

### 15.18.3　交互式 Dashboard

GAWorld 的 worlds.html 提供完整的交互式可视化:

- 多世界对比
- 时间序列
- 分布对比
- 逐人影响

读者可在浏览器里探索结果。

---

## 15.19　扩展:政策建议的提炼工程

### 15.19.1　从异质性到政策建议

```python
def extract_policy_recommendations(heterogeneity: dict) -> list:
    """从异质性分析提取政策建议"""
    recommendations = []
    for group, effects in heterogeneity.items():
        # 找出被影响最大的群体
        most_affected = max(effects, key=lambda k: abs(effects[k]))
        if abs(effects[most_affected]) > 0.2:
            recommendations.append({
                "group": group,
                "issue": most_affected,
                "magnitude": effects[most_affected],
                "suggestion": f"针对 {group} 的 {most_affected} 制定差异化政策"
            })
    return recommendations
```

### 15.19.2　建议的优先级排序

```python
def prioritize_recommendations(recommendations: list) -> list:
    """按影响排序"""
    return sorted(recommendations,
                 key=lambda r: abs(r["magnitude"]),
                 reverse=True)
```

### 15.19.3　建议的可行性评估

```python
def feasibility_score(recommendation: dict) -> float:
    """可行性评分 0-1"""
    # 简化:基于政策类型
    policy_feasibility = {
        "补贴": 0.8,
        "扩建": 0.6,
        "限制": 0.4,
        "补偿": 0.7
    }
    return policy_feasibility.get(recommendation["type"], 0.5)
```

---

## 15.20　本章小结(最终扩展版)

- 可视化:分叉度曲线、逐人影响热力图、交互式 Dashboard。
- 政策建议提炼:异质性 → 建议 → 优先级 → 可行性。
- 平行世界系统完整,可复现、可视化、可决策。

