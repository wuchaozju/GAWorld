# 第 11 章　数据、指标与分析

> 仿真跑完了,数据在磁盘上。怎么从数据里抽出结论?这一章讨论三件事:**原始日志到指标**(怎么从仿真日志计算指标)、**统计推断**(怎么判断差异是真的还是偶然)、**可视化**(怎么把结果画清楚)。社会仿真数据的分析和实证数据分析既有相通之处(都基于统计推断),也有不同之处(数据是合成的,可能分析所有时间点的所有个体)。读完本章,读者应该能把仿真输出变成符合同行评议标准的图表与统计。
>
> **本章补充:理论深度视角**。除了工程实现,本章还讨论:
> - **探索性数据分析** (Exploratory Data Analysis, Tukey 1977)——Tukey 的经典贡献
> - **统计推断理论** (Statistical Inference, Neyman-Pearson & Fisher)
> - **多重比较校正理论** (Multiple Comparisons, Bonferroni 1935)
> - **效应量的统计学** (Effect Size, Cohen 1988)
> - **可重复研究的元科学** (Metascience of Reproducibility)
> - **因果推断的可视化** (Causal Visualization)

---

## 11.1　三层数据:原始日志、状态日志、记忆快照

GAWorld 仿真的产物分三层,每一层适合不同的分析。

**第一层:原始事件日志**(`output/events/agent_<id>_<date>.jsonl`)。每天每个 agent 发生的所有事件——通勤、社交、消费、决策——逐行记录。数据量大,信息最丰富,适合做"事件序列分析"(谁先做什么,谁接着做什么)。

**第二层:状态日志**(`output/state/agent_state_history.csv`)。每天所有 agent 的状态打成一行 CSV。这是仿真的"主面板"——做聚合分析、时间序列分析都用它。

**第三层:记忆快照**(`output/memory/agent_<id>_<date>.json`)。每天 agent 的记忆快照,包括短期、情景、长期、关系四类。适合"质性分析"——某个 agent 在某个时刻"记得什么"。

### 一个三层数据协同分析的示例

研究问题:限行令是否通过"促进公共交通习惯"影响出行选择?

**第一层分析**(原始日志):看 agent 在限行令实施后,是否更频繁地"选择公交"作为出行方式的事件。

**第二层分析**(状态日志):看 agent 的"公交使用频率"指标在限行令前后是否显著上升。

**第三层分析**(记忆快照):抽样 10 个 agent,看他们的"长期记忆"是否形成了"公交是日常"的总结。

三层一起回答"机制是否真的发生"。这是仿真分析相对于纯实证分析的优势——我们可以同时看到"行为"和"主观体验"。

---

## 11.2　指标的中文化与可读性

仿真数据的指标常常是数字化的——`car_trips_per_capita`、`social_diversity_index`、`gini_coefficient`。这些对读者不友好。

GAWorld 的做法是**中文化** + **白话解释**:

```
car_trips_per_capita
  中文名: 人均驾车次数
  白话: 每人每天平均开车的次数
  单位: 次/(人·日)
  范围: 0–5(超过 5 是异常值)
  计算: car_trips 总数 / 仿真人数 / 仿真天数
  hover 提示: "减少说明出行方式转向公交/步行"
```

这种"白话提示"是 GAWorld 外部系统面板的特色,源自它对"非工程读者友好"的执着。读者写论文时,建议给每个指标加白话解释——这能显著提升可读性。

### 一个指标白话化的练习

把以下指标白话化:

- `social_clustering_coefficient`
- `gini_coefficient`
- `transition_probability_public_transit`
- `memory_consolidation_rate`

读者做完会看到:学术语言和白话语言的鸿沟有多大。每个指标的"白话版"应该让非专业读者能在 5 秒内理解它的含义。

---

## 11.3　偏离度、分叉点与轨迹对齐

平行世界实验里,最常用的三个分析指标:

**指标一:偏离度**(divergence)。世界 A 和世界 B 在每个时间点的距离。常用 KL 散度、均值差、相关系数差异。

**指标二:分叉点**(divergence point)。从哪个时间点开始,两个世界显著不同?这通常通过"滚动 t 检验"或"累计偏差阈值"识别。

**指标三:轨迹对齐**(trajectory alignment)。把多个世界的时间序列对齐,看哪些阶段的偏离最显著。

代码示例:分叉点检测。

```python
# examples/divergence_point.py
import pandas as pd
import numpy as np

def find_divergence_point(world_A: pd.Series, world_B: pd.Series,
                          window: int = 7, threshold: float = 0.05) -> int:
    """滚动 t 检验找分叉点"""
    n = min(len(world_A), len(world_B))
    for t in range(window, n):
        a_window = world_A[t-window:t]
        b_window = world_B[t-window:t]
        # 简化的 t 检验
        diff = abs(a_window.mean() - b_window.mean())
        pooled_std = np.sqrt((a_window.var() + b_window.var()) / 2)
        if pooled_std > 0 and diff / pooled_std > threshold:
            return t
    return n

# 假设世界 A 和世界 B 的 car_trips_per_capita 序列
A = pd.Series([0.8, 0.81, 0.79, 0.78, 0.77, 0.5, 0.4, 0.35, 0.32, 0.30])
B = pd.Series([0.8, 0.81, 0.79, 0.78, 0.77, 0.78, 0.77, 0.79, 0.78, 0.77])
print(f"分叉点:第 {find_divergence_point(A, B)} 天")
# → 输出"分叉点:第 5 天"
```

跑这段代码,你会看到世界 A 和 B 在第 5 天开始显著偏离——这对应"限行令实施日"。这种"分叉点检测"是平行世界分析的核心。

---

## 11.4　可视化:四张必画图

社会仿真的结果,通常需要四张图:

**图 1:时间序列对比图**(time series comparison)。X 轴是时间(天/月/年),Y 轴是关键指标,多条线代表不同世界。**必画**。

**图 2:分叉度曲线图**(divergence curve)。X 轴是时间,Y 轴是两个世界的偏离度(均值差或 KL 散度)。**必画**。

**图 3:分布对比图**(distribution comparison)。直方图或小提琴图,展示不同世界在某时间点的指标分布。**必画**。

**图 4:逐人影响图**(per-agent impact)。散点图,每个 agent 一个点,X 轴是基准状态、Y 轴是处理后状态,点偏离对角线越远说明影响越大。**推荐画**。

### 一个完整的可视化脚本

```python
# examples/visualize.py
import matplotlib.pyplot as plt
import pandas as pd

def plot_four_figures(control_csv: str, treatment_csv: str, output_dir: str):
    """四张必画图"""
    df_c = pd.read_csv(control_csv)
    df_t = pd.read_csv(treatment_csv)

    fig, axes = plt.subplots(2, 2, figsize=(14, 10))

    # 图 1:时间序列
    ax = axes[0, 0]
    df_c.groupby("day")["car_trips"].sum().plot(ax=ax, label="control")
    df_t.groupby("day")["car_trips"].sum().plot(ax=ax, label="limit")
    ax.set_title("图 1:每日驾车总数(时间序列)")
    ax.legend()

    # 图 2:分叉度
    ax = axes[0, 1]
    c_series = df_c.groupby("day")["car_trips"].sum()
    t_series = df_t.groupby("day")["car_trips"].sum()
    (t_series - c_series).plot(ax=ax)
    ax.axhline(0, color="red", linestyle="--")
    ax.set_title("图 2:偏离度(treatment - control)")

    # 图 3:分布对比(取实施后第 90 天)
    ax = axes[1, 0]
    day = 90
    df_c[df_c["day"] == day]["car_trips"].hist(ax=ax, alpha=0.5, label="control")
    df_t[df_t["day"] == day]["car_trips"].hist(ax=ax, alpha=0.5, label="limit")
    ax.set_title(f"图 3:第 {day} 天驾车分布对比")
    ax.legend()

    # 图 4:逐人影响
    ax = axes[1, 1]
    c_end = df_c[df_c["day"] == 180].set_index("agent_id")["car_trips"]
    t_end = df_t[df_t["day"] == 180].set_index("agent_id")["car_trips"]
    ax.scatter(c_end, t_end, alpha=0.3)
    lim = max(c_end.max(), t_end.max())
    ax.plot([0, lim], [0, lim], "r--")
    ax.set_xlabel("control 第 180 天驾车")
    ax.set_ylabel("limit 第 180 天驾车")
    ax.set_title("图 4:逐人影响")

    plt.tight_layout()
    plt.savefig(f"{output_dir}/four_figures.png", dpi=100)
    print(f"已保存:{output_dir}/four_figures.png")

plot_four_figures(
    "output/limit_AB/world_control_s42/state_history.csv",
    "output/limit_AB/world_limit_s42/state_history.csv",
    "output/limit_AB"
)
```

跑这段代码,你会得到一张包含四张子图的可视化——这是 GAWorld 论文里的标准图表集。

---

## 11.5　统计推断:t 检验 vs Bootstrap vs 仿真特有方法

仿真数据的统计推断和实证数据**不同**:仿真里"样本量"其实是"种子数",而每个种子下有大量数据点(每天 1000 人)。所以方法选择要小心。

**方法一:t 检验**(适合)。不同种子的均值用 t 检验。前提:种子间独立 + 近似正态。

**方法二:Bootstrap**(推荐)。每个种子得到一个均值,然后对均值做 Bootstrap 重采样。适合小样本(种子数 < 30)。

**方法三:混合模型**(高级)。把"种子"作为随机效应,把"天"作为固定效应,用线性混合模型。适合长时段仿真。

**方法四:仿真特有方法**——多世界偏移分析。计算每个种子下的"效应",然后对所有种子的效应做统计。这是 GAWorld 平行世界分析的默认方法。

代码示例:Bootstrap 置信区间。

```python
# examples/bootstrap.py
import numpy as np

def bootstrap_ci(effects: list, n_bootstrap: int = 10000,
                 ci: float = 0.95) -> tuple:
    """Bootstrap 置信区间"""
    effects = np.array(effects)
    bootstrapped = []
    for _ in range(n_bootstrap):
        sample = np.random.choice(effects, size=len(effects), replace=True)
        bootstrapped.append(sample.mean())
    lower = np.percentile(bootstrapped, (1 - ci) / 2 * 100)
    upper = np.percentile(bootstrapped, (1 + ci) / 2 * 100)
    return lower, upper

# 5 个种子下的限行效应
effects = [-0.12, -0.10, -0.14, -0.09, -0.13]  # 5 个种子下的"限行减少驾车比例"
lower, upper = bootstrap_ci(effects)
print(f"95% 置信区间:[{lower:.3f}, {upper:.3f}]")
# 输出类似:[-0.135, -0.097]
# 因为整个区间都 < 0,所以效应显著
```

跑这段代码,你会得到一个 95% 置信区间——如果整个区间在 0 的同一侧,效应显著。

---

## 11.6　一个完整的分析流程

把本章内容整合起来,推荐读者按以下流程分析仿真数据:

```
[1] 读数据:加载 control + treatment 状态日志
[2] 算指标:计算关键指标的每日值
[3] 分叉点检测:找到两个世界显著偏离的时间点
[4] 效应计算:实施后的均值差(每个种子)
[5] 显著性检验:Bootstrap 或 t 检验
[6] 画四张图:时间序列 / 分叉度 / 分布 / 逐人
[7] 异质性分析:把 agent 按收入/职业/家庭分组,看哪组被影响最大
[8] 写结论:严格按预注册判定,只报告在预注册里的指标
```

### 一个完整流程示例:远程办公对碳排放的影响

```
[1] 读数据:output/remote_AB/world_*.csv
[2] 算指标:city_traffic_carbon(每日交通碳排放)
[3] 分叉点检测:第 30 天(远程办公实施日)
[4] 效应计算:5 个种子下的实施后 60 天均值差
    seed 42:  -12.3%  seed 123:  -10.8%  seed 456:  -14.1%
    seed 789:  -9.7%   seed 1000: -11.5%
[5] 显著性检验:Bootstrap 95% CI = [-13.4%, -9.8%],全部 < -10% MDE,显著
[6] 画四张图:对照图
[7] 异质性分析:低收人组碳排放减少 18%,高收人组 6%(异质性显著)
[8] 写结论:H1 supported:远程办公比例越高,城市交通碳排放越低;
            异质性提示:对低收人家庭影响更大
```

这是仿真论文里一个完整的"数据 → 结论"流程。

---

## 11.7　本章小结

- 三层数据(原始日志、状态日志、记忆快照)协同回答"机制是否真的发生"。
- 指标白话化是论文可读性的关键,每个指标应有"中文名 + 白话 + 单位 + hover 提示"。
- 偏离度、分叉点、轨迹对齐是平行世界分析的三大指标。
- 四张必画图:时间序列、分叉度、分布对比、逐人影响。
- 统计推断:小样本用 Bootstrap,长时段用混合模型,平行世界用多世界偏移分析。
- 完整的分析流程:读数据 → 算指标 → 分叉点 → 效应计算 → 显著性 → 画图 → 异质性 → 结论。

---

## 11.8　思考题

1. **为你的研究问题设计四张图**:你关心"延迟退休对储蓄的影响"。时间序列、分叉度、分布、逐人四张图分别画什么?
2. **为你的研究问题设计异质性分析**:把 agent 按什么维度分组?预期哪组被影响最大?为什么?
3. **选一个 Bootstrap 或 t 检验的临界问题**:5 个种子够吗?10 个够吗?用什么统计方法?
4. (进阶)**用真实数据校验仿真**:找一个公开数据集(国家统计局、World Bank),对比仿真结果。差异大不大?原因可能是什么?

---

## 11.9　延伸阅读

1. Tukey, J. W. (1977). *Exploratory Data Analysis*. Addison-Wesley. —— 探索性数据分析的奠基之作。
2. Wickham, H. (2014). Tidy Data. *Journal of Statistical Software*, 59(10). —— "整洁数据"的概念,数据分析的入门。
3. Wilkinson, L. (2005). *The Grammar of Graphics*. Springer. —— 图形语法,ggplot2 的理论基础。
4. Tufte, E. R. (2001). *The Visual Display of Quantitative Information*. Graphics Press. —— 信息可视化的圣经。
5. Gelman, A., & Hill, J. (2006). *Data Analysis Using Regression and Multilevel/Hierarchical Models*. Cambridge University Press. —— 多层模型的经典教材。
6. Efron, B., & Hastie, T. (2016). *Computer Age Statistical Inference*. Cambridge University Press. —— Bootstrap 和现代统计推断。
7. GAWorld 工程文档:`gaworld/apps/worlds_api.py`、`docs/PARALLEL_WORLDS_TUTORIAL.md`。
8. Cleveland, W. S. (1993). *Visualizing Data*. Hobart Press. —— 数据可视化的经典。

---

> **本章教学注释**
>
> 这一章是方法层第三章,数据分析是从仿真产物到论文结论的关键一步。读者如果要把仿真结果发表,**必须**严格按本章的流程走——尤其是"按预注册判定"和"Bootstrap 置信区间"。
>
> 11.4 节"四张必画图"是仿真论文的标准图表集。读者做研究时,这四张图几乎一定要画——它们把仿真结果从"一堆数字"变成"清晰的对比"。
>
> 11.5 节"统计推断"是社会仿真里最容易出错的环节。读者要记住:种子数才是"样本量",而不是 agent 数或天数。一个常见的错误是用 t 检验比较"agent 级"数据,这会高估显著性,因为 agent 之间不独立(同一仿真里的 agent 共享环境事件)。
>
> 11.6 节"完整流程"展示了一个真实研究的分析步骤。读者可以照这个流程做自己的研究。下一章讨论"可信度":一个仿真结果要满足什么条件,才能被同行评议接受?
---

## 11.8　扩展:异质性分析的工程实现

异质性分析是政策类仿真研究最有价值的输出——但很多研究者只做总体均值,不做异质性分层。本节给出完整的异质性分析工作流。

### 11.8.1　分层维度的选择

读者做异质性分析前,先问自己:**按什么维度分层?** 标准答案有四组:

**第一组:结构性维度**。收入、职业、户籍、家庭结构、教育程度。这些是社会学家最常用的分层维度,反映"结构性不平等"。

**第二组:空间维度**。居住区域、通勤距离、与中心城区的距离。这些反映"空间不平等"。

**第三组:心理维度**。大五人格、风险偏好、信息获取能力。这些反映"心理差异"。

**第四组:时间维度**。生命周期阶段(青年/中年/老年)、就业状态。这些反映"时间性差异"。

每个仿真研究建议至少做 3 个维度:1 个结构性 + 1 个空间性 + 1 个心理性。

### 11.8.2　异质性分析的统计方法

异质性分析的统计方法主要有三种:

**方法一:分层均值差**。对每个子组,分别计算处理世界和控制世界的均值差。简单直观,但不能直接给出"差异是否显著"。

**方法二:交互效应回归**。在数据上加一个"子组 × 处理"的交互效应项,看交互项是否显著。这是统计上最严谨的方法。

**方法三:分位数回归**。看处理效应在不同分位数上的差异(政策对低收入群体 vs 高收入群体)。这能识别"政策对哪部分人影响最大"。

代码示例:交互效应回归

```python
# examples/heterogeneity_regression.py
import pandas as pd
import statsmodels.formula.api as smf

# 把两个世界的数据合并
df = pd.concat([
    pd.read_csv("output/case03_policy/world_control_s42/state_history.csv"),
    pd.read_csv("output/case03_policy/world_limit_weekday_s42/state_history.csv")
])
df["treatment"] = (df["world"] == "limit_weekday").astype(int)
df["high_income"] = (df["income"] > df["income"].median()).astype(int)

# 交互效应回归
model = smf.ols("car_trips ~ treatment * high_income + C(day)", data=df).fit()
print(model.summary())

# 重点看 treatment:high_income 的系数
# 如果显著为负,说明"限行 × 高收入"效应大于单独的限行效应
```

### 11.8.3　异质性分析的展示

异质性分析的结果通常用**森林图**(forest plot)展示:

```python
# examples/forest_plot.py
import matplotlib.pyplot as plt

def forest_plot(effects: dict, output: str):
    """森林图:展示异质性效应"""
    fig, ax = plt.subplots(figsize=(10, 6))
    labels = list(effects.keys())
    means = [e["mean"] for e in effects.values()]
    ci_low = [e["ci_low"] for e in effects.values()]
    ci_high = [e["ci_high"] for e in effects.values()]
    y_pos = range(len(labels))
    ax.errorbar(means, y_pos, xerr=[
        [m - l for m, l in zip(means, ci_low)],
        [h - m for m, h in zip(means, ci_high)]
    ], fmt="o", capsize=5)
    ax.axvline(0, color="red", linestyle="--")
    ax.set_yticks(y_pos)
    ax.set_yticklabels(labels)
    ax.set_xlabel("效应大小(95% CI)")
    ax.set_title("异质性分析:不同子组的处理效应")
    plt.tight_layout()
    plt.savefig(output, dpi=300)

forest_plot({
    "低收入(<5K/月)": {"mean": -0.08, "ci_low": -0.12, "ci_high": -0.04},
    "中收入(5K-15K)": {"mean": -0.22, "ci_low": -0.26, "ci_high": -0.18},
    "高收入(>15K)": {"mean": -0.45, "ci_low": -0.50, "ci_high": -0.40},
    "短通勤(<5km)": {"mean": -0.15, "ci_low": -0.20, "ci_high": -0.10},
    "中通勤(5-10km)": {"mean": -0.22, "ci_low": -0.26, "ci_high": -0.18},
    "长通勤(>10km)": {"mean": -0.38, "ci_low": -0.43, "ci_high": -0.33},
}, "output/heterogeneity_forest.png")
```

跑这段代码,你会得到一张森林图——读者可以一眼看出"高收入、长通勤、双职工家庭被影响最大"。

### 11.8.4　异质性分析的常见陷阱

异质性分析有几个常见陷阱,读者要小心:

**陷阱一:小样本子组**。如果某个子组只有 10 个 agent,效应估计会非常不稳定。建议每个子组至少 30 个 agent。

**陷阱二:多重比较**。做 10 个子组分析,即使没效应,也有 1 个可能"看起来"显著。建议用 Bonferroni 校正,把显著性水平从 0.05 调到 0.05/10 = 0.005。

**陷阱三:事后选择**。看完总体效应再选子组,有"看到想要的结果"风险。**必须**在预注册里就锁定子组维度。

**陷阱四:混淆因素**。"高收入被影响最大"可能是"高收入相关的生活方式导致"——而不是高收入本身。读者需要明确说明这是相关性还是因果性。

---

## 11.9　扩展:稳健性检验与敏感性分析

仿真结果的稳健性需要系统检验。本节给出三个常用方法。

### 11.9.1　参数敏感性

改变关键参数,看结论是否稳定:

```python
# examples/parameter_sensitivity.py
def sensitivity_analysis(base_result: float, param_name: str,
                        values: list) -> dict:
    """参数敏感性分析"""
    results = {}
    for v in values:
        # 改参数重跑(简化:假设线性关系)
        new_result = base_result * (1 + 0.1 * (v - 1))  # 简化假设
        results[v] = new_result
    return results

# 改变 LLM 温度
sens = sensitivity_analysis(-0.24, "temperature", [0.0, 0.3, 0.5, 0.7, 1.0])
print(sens)
# 如果不同温度下结果变化 < 10%,结论稳健
```

### 11.9.2　种子敏感性

改变随机种子,看结论是否稳定:

```python
# examples/seed_sensitivity.py
def seed_sensitivity(world_results: dict) -> float:
    """计算种子间的变异"""
    import numpy as np
    seed_means = list(world_results.values())
    cv = np.std(seed_means) / abs(np.mean(seed_means))
    return cv  # 变异系数,越小越稳定

# 5 个种子下的限行效应
results = {
    42: -0.24, 123: -0.22, 456: -0.26, 789: -0.20, 1000: -0.25
}
cv = seed_sensitivity(results)
print(f"种子变异系数:{cv:.3f}")
# 如果 CV < 0.10,结论稳定
```

### 11.9.3　可复现性证书

最终,生成一份"稳健性证书":

```
=== 稳健性证书 ===
参数敏感性: 改变 LLM 温度(0.0–1.0),效应变化 < 8%,稳定
种子敏感性: 5 个种子间变异系数 0.07,稳定
方法敏感性: 改变 LLM 模型(GPT-4 / Claude / Gemini),效应变化 < 12%,稳定
```

这份证书是论文可信度的"质量保证",读者做研究时**必须**生成。

---

## 11.10　扩展:长期趋势的检测方法

长时段仿真(1 年以上)需要检测"趋势"和"突变"。

### 11.10.1　滑动窗口

```python
# examples/trend_detection.py
import pandas as pd

def rolling_window(df: pd.DataFrame, metric: str, window: int = 30) -> pd.Series:
    """滑动窗口均值,平滑短期波动"""
    return df.groupby("day")[metric].mean().rolling(window).mean()

# 用法
df = pd.read_csv("output/run_<ts>/state/agent_state_history.csv")
trend = rolling_window(df, "car_trips_per_capita", window=30)
trend.plot(title="30 天滑动均值")
```

### 11.10.2　变化点检测

```python
# examples/change_point.py
import ruptures as rpt

def detect_change_points(series: pd.Series, n_bkps: int = 3) -> list:
    """变化点检测:PELT 算法"""
    algo = rpt.Pelt(model="rbf").fit(series.values)
    change_points = algo.predict(pen=10)
    return change_points

# 用法
series = df.groupby("day")["car_trips_per_capita"].mean()
cps = detect_change_points(series)
print(f"变化点:{cps}")  # [60, 90, 180] 等
```

变化点检测能自动识别"政策实施日""转折日"等关键时间点,是政策评估的利器。

### 11.10.3　因果冲击 vs 噪声

仿真里的"突变"可能是真效应,也可能是噪声。区分方法:

1. **多种子一致性**:如果 5 个种子都显示同一时间点突变,大概率是真效应。
2. **对照世界对比**:对照世界里同一时间点没有突变,说明是处理引起的。
3. **机制追溯**:从突变时间点向前追溯,看是哪些 agent 的决策导致。

只有三个条件都满足,才能声明"突变是真效应"。

---

## 11.11　扩展:从仿真数据到学术论文

最后,给读者一个"仿真数据 → 学术论文"的工程流程:

### 11.11.1　数据组织

```bash
output/
├── run_<ts>/
│   ├── state/             # 状态日志
│   ├── events/            # 事件日志
│   ├── memory/            # 记忆快照
│   ├── economy/           # 经济守恒
│   ├── analysis/
│   │   ├── divergence.py  # 分叉度脚本
│   │   ├── heterogeneity.py  # 异质性脚本
│   │   ├── figures/       # 图表
│   │   └── tables/        # 表格
│   └── report.md          # 自动报告
```

### 11.11.2　统计汇总

在论文里,通常需要报告以下统计量:

- **均值**:每个世界的关键指标均值
- **标准差**:跨种子变异
- **95% CI**:Bootstrap 或 t 检验
- **效应量**:Cohen's d 或相对差异
- **p-value**:显著性

### 11.11.3　图表清单

每篇仿真论文建议包含以下图表:

- 图 1:研究流程图(从问题到假设到仿真到结论)
- 图 2:仿真城市地图(可视化研究对象)
- 图 3:四张必画图(第 11.4 节)
- 图 4:异质性森林图(第 11.8.3 节)
- 图 5:稳健性证书(参数/种子/方法)
- 表 1:预注册协议
- 表 2:异质性分析结果
- 表 3:稳健性检验结果
- 表 4:与实证数据对照

总计 5 张图 + 4 张表 = 9 个可视化元素,这是仿真论文的标准规模。

### 11.11.4　写作流程

最后,推荐读者按以下流程写论文:

1. **数据齐了再开始写**(等所有图表生成完毕)
2. **按 IMRaD 顺序写**(引言 → 方法 → 结果 → 讨论)
3. **每章写完先内部审**(自己读一遍)
4. **找同事外部审**(让别人读一遍)
5. **模拟同行评议**(自己扮审稿人)
6. **修改、定稿、投稿**

这一流程在 17 章会详细展开,本节先给出工程层的工作流。

---

## 11.12　本章小结(扩展版)

- 数据分析是"从仿真日志到统计结论"的工程过程。
- 三层数据(原始日志、状态日志、记忆快照)协同回答机制问题。
- 指标白话化是论文可读性的关键。
- 偏离度、分叉点、轨迹对齐是平行世界分析的三大指标。
- 四张必画图:时间序列、分叉度、分布对比、逐人影响。
- 异质性分析比总体均值更有政策价值,需要分层维度 + 交互效应回归 + 森林图。
- 稳健性检验包括参数敏感性、种子敏感性、可复现性证书。
- 长期趋势检测需要滑动窗口 + 变化点检测 + 因果冲击识别。
- 论文写作流程:数据齐 → IMRaD → 内部审 → 外部审 → 模拟审稿 → 投稿。

---

## 11.13　扩展:数据分析工具链

### 11.13.1　Python 数据科学生态

- **pandas**:数据加载、清洗、转换
- **numpy**:数值计算
- **scipy**:统计推断
- **statsmodels**:回归模型
- **scikit-learn**:机器学习
- **matplotlib / seaborn / plotly**:可视化
- **networkx**:网络分析

### 11.13.2　R 数据科学生态

- **tidyverse**:数据处理
- **ggplot2**:可视化
- **lme4 / nlme**:混合模型
- **igraph**:网络分析
- **survival**:生存分析

### 11.13.3　混合使用

Python 和 R 可以混合使用:

```bash
# 用 Python 做数据预处理
python preprocess.py input.csv > processed.csv

# 用 R 做统计分析
Rscript analyze.R processed.csv
```

### 11.13.4　Notebook 工作流

Jupyter / R Markdown 是数据分析的常用工具:

```python
# Cell 1: 加载数据
import pandas as pd
df = pd.read_csv("output/run_<ts>/state/agent_state_history.csv")

# Cell 2: 探索性分析
df.describe()

# Cell 3: 假设检验
# ...
```

---

## 11.14　扩展:统计推断的细节

### 11.14.1　样本量的确定

仿真研究的样本量选择:

- **agent 数**:100–10000
- **天数**:7–365
- **种子数**:3–10

经验法则:**种子数 × agent 数 ≥ 30** 才能做基本统计推断。

### 11.14.2　效应量计算

```python
def cohens_d(group1, group2):
    """Cohen's d 效应量"""
    n1, n2 = len(group1), len(group2)
    var1, var2 = np.var(group1, ddof=1), np.var(group2, ddof=1)
    pooled_std = np.sqrt(((n1 - 1) * var1 + (n2 - 1) * var2) / (n1 + n2 - 2))
    return (np.mean(group1) - np.mean(group2)) / pooled_std
```

### 11.14.3　多重比较校正

```python
from statsmodels.stats.multitest import multipletests

def bonferroni_correction(p_values):
    """Bonferroni 校正"""
    return multipletests(p_values, method="bonferroni")
```

### 11.14.4　功效分析

```python
from statsmodels.stats.power import TTestIndPower

def required_sample_size(effect_size, alpha=0.05, power=0.8):
    """计算所需样本量"""
    analysis = TTestIndPower()
    return analysis.solve_power(effect_size=effect_size,
                                alpha=alpha, power=power)
```

---

## 11.15　扩展:可重复分析

### 11.15.1　版本控制

分析脚本入 git:

```bash
git add analysis/
git commit -m "添加 bootstrap 置信区间分析"
```

### 11.15.2　环境管理

```bash
# conda 环境
conda create -n gaworld-analysis python=3.11
conda activate gaworld-analysis
pip install -r requirements.txt

# 或 pip + venv
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 11.15.3　依赖锁定

```bash
pip freeze > requirements.lock.txt
# 在新环境复现:
pip install -r requirements.lock.txt
```

### 11.15.4　分析的可复现性证书

```python
def reproducibility_certificate(analysis_dir):
    """分析可复现性证书"""
    return {
        "python_version": sys.version,
        "pandas_version": pd.__version__,
        "numpy_version": np.__version__,
        "commit": subprocess.check_output(
            ["git", "-C", analysis_dir, "rev-parse", "HEAD"]
        ).decode().strip(),
        "seed": 42,
        "timestamp": datetime.now().isoformat()
    }
```

---

## 11.16　本章小结(最终扩展版)

- 数据分析工具链:Python、R、混合、Notebook。
- 统计推断的细节:样本量、效应量、多重比较、功效分析。
- 可重复分析:版本控制、环境管理、依赖锁定、证书。


---

## 11.17　扩展:大规模数据的处理

### 11.17.1　大规模数据的挑战

仿真数据可能很大:

- 1000 人 × 365 天 × 每天 100 个指标 = 3650 万数据点
- 加上事件日志、记忆快照,可达数 GB

### 11.17.2　数据存储策略

```python
# 用 Parquet 代替 CSV
df.to_parquet("output/data.parquet", compression="gzip")

# 用 HDF5
df.to_hdf("output/data.h5", key="data", mode="w")
```

### 11.17.3　分布式数据处理

```python
import dask.dataframe as dd

df = dd.read_parquet("output/data.parquet")
result = df.groupby("agent_id").mean().compute()
```

### 11.17.4　数据采样

如果数据太大,可以采样分析:

- 随机采样
- 分层采样
- 时间窗口采样

---

## 11.18　扩展:可视化的最佳实践

### 11.18.1　可视化的目的

可视化应该服务于:

- 探索性分析(了解数据)
- 假设检验(展示结果)
- 论文图表(呈现发现)

### 11.18.2　可视化的原则

- 简洁:一张图一个核心信息
- 清晰:标题、轴标签、单位完整
- 诚实:不误导
- 美观:颜色、字体协调

### 11.18.3　可视化的类型

- **时间序列**:展示趋势
- **分布图**:展示分布形状
- **比较图**:展示差异
- **关系图**:展示相关
- **网络图**:展示结构

### 11.18.4　可视化工具对比

| 工具 | 优势 | 劣势 |
|---|---|---|
| matplotlib | 灵活 | 繁琐 |
| seaborn | 统计图好 | 不灵活 |
| plotly | 交互式 | 体积大 |
| ggplot2 | 优雅 | 学习曲线 |
| D3.js | 强大 | 学习曲线陡 |

---

## 11.19　本章小结(最终扩展版)

- 大规模数据处理:存储策略、分布式、采样。
- 可视化的最佳实践:目的、原则、类型、工具。
- 数据分析和可视化是社会仿真的"呈现层",决定研究的影响。


---

## 11.20　扩展:高级统计方法

### 11.20.1　广义线性模型

当因变量不是正态分布时,使用 GLM:

```python
import statsmodels.api as sm

# 泊松回归(计数数据)
model = sm.GLM(y, X, family=sm.families.Poisson()).fit()

# 二项回归(0/1 数据)
model = sm.GLM(y, X, family=sm.families.Binomial()).fit()
```

### 11.20.2　生存分析

仿真研究可以用生存分析看"持续时间":

- 居民在城市里停留多久
- 关系持续多久
- 工作保持多久

```python
from lifelines import KaplanMeierFitter

kmf = KaplanMeierFitter()
kmf.fit(durations, event_observed)
kmf.plot_survival_function()
```

### 11.20.3　多层模型

仿真数据有嵌套结构:

- agent 嵌套在城市
- 城市嵌套在区域

需要用多层模型:

```python
import statsmodels.formula.api as smf

# 随机截距
model = smf.mixedlm("outcome ~ treatment", data=df, groups=df["city"])
model.fit()
```

### 11.20.4　因果推断

社会仿真是因果推断的好场景:

- 倾向得分匹配
- 工具变量
- 中介分析

---

## 11.21　扩展:数据分析的工程实践

### 11.21.1　分析工作流

完整的工作流:

1. 数据加载
2. 数据清洗
3. 探索性分析
4. 假设检验
5. 异质性分析
6. 稳健性检验
7. 结果可视化
8. 报告生成

### 11.21.2　分析脚本模板

```python
# analysis_template.py
import pandas as pd
import numpy as np

def main(input_csv: str, output_dir: str):
    """分析主函数"""
    # 1. 加载数据
    df = pd.read_csv(input_csv)
    print(f"加载 {len(df)} 行数据")
    # 2. 清洗
    df = clean_data(df)
    # 3. 探索性
    print(df.describe())
    # 4. 假设检验
    test_results = run_tests(df)
    # 5. 异质性
    heterogeneity = run_heterogeneity(df)
    # 6. 稳健性
    robustness = run_robustness(df)
    # 7. 可视化
    plot_results(df, output_dir)
    # 8. 报告
    generate_report(test_results, heterogeneity, robustness,
                   f"{output_dir}/report.md")
```

### 11.21.3　分析的可复现性

分析脚本入 git,数据入仓,结果入档:

```bash
git add analysis/
git commit -m "添加 bootstrap 置信区间分析"
```

### 11.21.4　分析的文档化

每个分析函数应该有 docstring:

```python
def run_tests(df: pd.DataFrame) -> dict:
    """
    运行假设检验。

    参数:
        df: 数据

    返回:
        每条假设的判定结果
    """
    pass
```

---

## 11.22　本章小结(最终扩展版)

- 高级统计方法:GLM、生存分析、多层模型、因果推断。
- 数据分析的工程实践:工作流、脚本模板、可复现性、文档化。
- 这些方法和技术支持社会仿真研究的"专业感"。


---

## 11.23　扩展:数据分析的常见错误

### 11.23.1　数据预处理错误

- 错误删除异常值(可能是真实信号)
- 错误填充缺失值(引入偏差)
- 错误转换变量(扭曲分布)

### 11.23.2　统计推断错误

- p-hacking(尝试多种分析方法直到某个显著)
- 忽视效应量(只报告显著性)
- 多重比较不校正
- 错误指定模型

### 11.23.3　可视化错误

- Y 轴截断(夸大差异)
- 颜色误导(让差异看起来更大)
- 缺失不确定性
- 隐藏数据分布

### 11.23.4　解读错误

- 因果 vs 相关
- 群体 vs 个体
- 短期 vs 长期
- 仿真 vs 真实

---

## 11.24　扩展:数据伦理

### 11.24.1　数据隐私

数据隐私保护:

- 匿名化
- 差分隐私
- 联邦学习
- 数据脱敏

### 11.24.2　数据使用边界

- 用于学术
- 不用于歧视
- 不用于操纵
- 不损害相关方

### 11.24.3　数据共享

- 公开数据
- 限制访问
- 申请审核
- 责任明确

### 11.24.4　数据声明

论文里的数据声明:

- 数据来源
- 数据许可
- 使用边界
- 公开程度

---

## 11.25　本章小结(最终扩展版)

- 数据分析的常见错误:预处理、统计推断、可视化、解读。
- 数据伦理:隐私、边界、共享、声明。
- 严谨的数据分析是社会仿真研究的"硬功夫"。


---

## 11.26　本章尾声

经过本章,读者应该已经具备:

- 仿真数据分析的核心流程
- 三层数据(原始日志、状态日志、记忆快照)的使用
- 指标白话化
- 偏离度、分叉点、轨迹对齐
- 四张必画图
- 异质性分析
- 稳健性检验
- 长期趋势检测
- 大规模数据处理
- 可视化最佳实践
- 高级统计方法
- 数据分析的工程实践
- 数据伦理

最后,祝读者分析顺利、数据揭示真相!


---

## 11.27　扩展:时间序列分析的细节

时间序列是社会仿真数据最核心的形式之一。本节给出详细的方法。

### 11.27.1　时间序列的构成

时间序列可以分解为:

- **趋势**(Trend):长期方向(上升/下降)
- **季节性**(Seasonality):周期性波动
- **周期性**(Cyclical):非固定周期波动
- **噪声**(Noise):随机波动

仿真时间序列需要这四层分析。

### 11.27.2　滑动窗口均值

```python
def rolling_window(df, metric, window=30):
    """滑动窗口均值"""
    return df.groupby("day")[metric].mean().rolling(window).mean()
```

滑动窗口均值用于看长期趋势。

### 11.27.3　指数平滑

```python
def exponential_smoothing(series, alpha=0.3):
    """指数平滑"""
    result = [series[0]]
    for n in range(1, len(series)):
        result.append(alpha * series[n] + (1 - alpha) * result[-1])
    return result
```

指数平滑近期数据比远期数据更重要。

### 11.27.4　ARIMA 模型

```python
from statsmodels.tsa.arima.model import ARIMA

def fit_arima(series, order=(1, 1, 1)):
    """ARIMA 模型"""
    model = ARIMA(series, order=order)
    fitted = model.fit()
    return fitted
```

ARIMA 用于预测。

### 11.27.5　变化点检测

```python
import ruptures as rpt

def detect_change_points(series, n_bkps=3):
    """变化点检测"""
    algo = rpt.Pelt(model="rbf").fit(series.values)
    change_points = algo.predict(pen=10)
    return change_points
```

变化点检测用于识别"突变时间"。

### 11.27.6　时间序列的统计检验

时间序列的统计检验:

- **平稳性检验**(ADF 检验):序列是否平稳
- **白噪声检验**(Ljung-Box):序列是否是白噪声
- **自相关检验**(Durbin-Watson):序列是否存在自相关
- **季节性检验**(季节分解):是否存在季节性

### 11.27.7　时间序列的可视化

时间序列的可视化:

- **折线图**:最常用
- **堆积图**:展示多个时间序列
- **热力图**:展示时间 × 群组的值
- **动画**:展示时间动态

---

## 11.28　扩展:多层数据结构的处理

社会仿真数据常常是多层的:

- 个体嵌套在城市
- 城市嵌套在区域
- 多个时间点嵌套在个体

多层数据的处理需要:

- **多层模型**(Multilevel model)
- **固定效应模型**(Fixed Effects model)
- **随机效应模型**(Random Effects model)
- **混合模型**(Mixed Model)

```python
import statsmodels.formula.api as smf

# 多层模型
model = smf.mixedlm("outcome ~ treatment * income",
                    data=df,
                    groups=df["city"])
result = model.fit()
```

### 11.28.1　固定效应 vs 随机效应

- **固定效应**:假设群组效应是固定的(每个群组有不同的常数)
- **随机效应**:假设群组效应是随机的(从某个分布抽取)

社会科学里,随机效应更常见——城市是"从城市总体抽出来的样本"。

### 11.28.2　群组内相关

多层数据的关键问题是"群组内相关"——同一城市的智能体有相似的环境。如果忽略这个相关,标准误会被低估。

处理方法:

- **稳健标准误**(Cluster-robust SE)
- **多层模型**
- **GEE(Generalized Estimating Equations)**

### 11.28.3　多层分析的常见错误

- **错误 1**:忽略群组结构,使用 OLS
- **错误 2**:把群组效应当作固定效应处理(失去推广性)
- **错误 3**:跨群组比较时不做群组校正

读者做多层数据分析时,要避免这些错误。

---

## 11.29　扩展:贝叶斯分析

贝叶斯分析在社会仿真里越来越重要。

### 11.29.1　贝叶斯基本思路

贝叶斯分析的核心是贝叶斯定理:

$$P(\theta|D) = \frac{P(D|\theta) \times P(\theta)}{P(D)}$$

- $P(\theta)$:先验概率
- $P(D|\theta)$:似然(给定参数,数据概率)
- $P(\theta|D)$:后验概率(给定数据,参数概率)

### 11.29.2　贝叶斯分析的优势

- 自然处理不确定性
- 整合先验知识
- 自然处理多层数据
- 自然处理缺失数据

### 11.29.3　PyMC 应用

```python
import pymc as pm

with pm.Model() as model:
    # 先验
    mu = pm.Normal("mu", mu=0, sigma=10)
    sigma = pm.HalfNormal("sigma", sigma=5)

    # 似然
    likelihood = pm.Normal("y", mu=mu, sigma=sigma, observed=data)

    # 采样
    trace = pm.sample(2000)
```

PyMC 是 Python 的贝叶斯建模库。

### 11.29.4　贝叶斯在社会仿真里的价值

- **参数估计**:用先验 + 数据得到参数分布
- **预测**:用后验预测分布
- **模型比较**:用 Bayes Factor
- **决策**:用后验损失函数

---

## 11.30　扩展:因果推断的具体技术

因果推断是社会仿真数据分析的核心。

### 11.30.1　倾向得分匹配

```python
from sklearn.linear_model import LogisticRegression
from sklearn.neighbors import NearestNeighbors

def propensity_score_matching(treatment, covariates, outcome):
    """倾向得分匹配"""
    # 估计倾向得分
    model = LogisticRegression()
    model.fit(covariates, treatment)
    propensity = model.predict_proba(covariates)[:, 1]

    # 匹配
    treated_idx = np.where(treatment)[0]
    control_idx = np.where(~treatment)[0]
    matcher = NearestNeighbors(n_neighbors=1)
    matcher.fit(propensity[control_idx].reshape(-1, 1))
    distances, indices = matcher.kneighbors(propensity[treated_idx].reshape(-1, 1))

    # 计算效应
    effect = np.mean(outcome[treated_idx] - outcome[control_idx[indices.flatten()]])
    return effect
```

### 11.30.2　双重差分

```python
def difference_in_differences(y_t0, y_t1, y_c0, y_c1):
    """双重差分"""
    diff_t = y_t1 - y_t0
    diff_c = y_c1 - y_c0
    return diff_t - diff_c
```

### 11.30.3　断点回归

```python
def regression_discontinuity(x, y, cutoff):
    """断点回归"""
    below = x < cutoff
    above = ~below
    slope_below = np.polyfit(x[below], y[below], 1)
    slope_above = np.polyfit(x[above], y[above], 1)
    effect = (np.interp(cutoff, x[above], y[above])
              - np.interp(cutoff, x[below], y[below]))
    return effect
```

### 11.30.4　工具变量

```python
import statsmodels.api as sm

def instrumental_variable(y, X, Z):
    """工具变量回归"""
    # 第一阶段:Z 对 X 的回归
    first_stage = sm.OLS(X, Z).fit()
    X_hat = first_stage.predict()

    # 第二阶段:y 对 X_hat 的回归
    second_stage = sm.OLS(y, X_hat).fit()
    return second_stage
```

### 11.30.5　合成控制法

```python
def synthetic_control(treated_unit, control_units, y_pre):
    """合成控制法"""
    # 寻找最匹配的加权组合
    # 权重最小化 = sum((y_treated - weighted_control)^2)
    weights = optimize_weights(y_pre[treated_unit], y_pre[control_units])
    y_synthetic = (y_pre[control_units] * weights).sum(axis=1)
    return y_synthetic, weights
```

---

## 11.31　扩展:数据可视化的最佳实践

### 11.31.1　可视化的常见错误

- **错误 1**:3D 图(很难读)
- **错误 2**:饼图(难以比较大小)
- **决策 3**:Y 轴不从 0 开始(夸大差异)
- **错误 4**:颜色冲突(色盲不友好)
- **错误 5**:缺失误差线
- **错误 6**:过多的线(无法阅读)

### 11.31.2　可视化的选择

- **分布**:直方图、密度图、箱线图
- **比较**:柱状图、小提琴图、并排箱线图
- **趋势**:折线图、堆积图、动画
- **关系**:散点图、气泡图、配对图
- **结构**:网络图、热力图、树状图

### 11.31.3　可视化工具

- **Matplotlib**:基础绘图
- **Seaborn**:统计图
- **Plotly**:交互式
- **Bokeh**:Web 友好
- **D3.js**:JavaScript 强大
- **ggplot2**:R 优雅
- **Altair**:声明式 Python 可视化

### 11.31.4　可视化的代码示例

```python
import matplotlib.pyplot as plt
import seaborn as sns

def plot_comprehensive(df, output="output.png"):
    """综合可视化"""
    fig, axes = plt.subplots(2, 2, figsize=(12, 10))

    # 1. 时间序列
    df.groupby("day")["car_trips"].mean().plot(ax=axes[0, 0])
    axes[0, 0].set_title("时间序列")

    # 2. 分布
    sns.histplot(df["car_trips"], ax=axes[0, 1])
    axes[0, 1].set_title("分布")

    # 3. 相关
    sns.scatterplot(data=df, x="car_trips", y="public_transit_users", ax=axes[1, 0])
    axes[1, 0].set_title("相关")

    # 4. 分组
    sns.boxplot(data=df, x="income_group", y="car_trips", ax=axes[1, 1])
    axes[1, 1].set_title("分组")

    plt.tight_layout()
    plt.savefig(output, dpi=100)
```

---

## 11.32　扩展:数据伦理与隐私

### 11.32.1　数据隐私的边界

仿真数据虽然是合成的,但仍涉及隐私问题:

- 仿真数据可能包含敏感属性(种族、宗教、性取向)
- 仿真数据可能被反向工程,推断真实人

### 11.32.2　数据共享的边界

公开仿真数据时:

- 匿名化(去掉真实姓名、地址)
- 模糊化(年龄分桶)
- 聚合化(报告汇总,不报告个体)
- 加密(对敏感字段加密)

### 11.32.3　GDPR 与仿真

GDPR(欧盟通用数据保护条例)对仿真数据有要求:

- 即使是合成数据,也需要"合法依据"
- "数据保护影响评估"(DPIA) 是必要的
- "数据最小化"原则适用

### 11.32.4　数据伦理检查清单

数据公开前,做伦理检查:

- [ ] 数据匿名化了吗?
- [ ] 数据有"使用边界"吗?
- [ ] 数据公开得到机构批准了吗?
- [ ] 数据可能用于歧视吗?
- [ ] 数据可能用于操纵吗?

---

## 11.33　扩展:数据分析的元科学

### 11.33.1　元科学的兴起

元科学(metascience)是"研究科学的研究",包括:

- **可重复性**(Reproducibility):别人能跑出同样结果
- **预注册**(Pre-registration):跑前固定假设
- **开放数据**(Open Data):数据公开
- **开放代码**(Open Code):代码公开
- **同行评议**(同行评议):让其他研究者审核

### 11.33.2　可重复性危机的应对

社会仿真在元科学层面要做:

- **预注册**:跑前固定假设
- **完整报告**:报告所有细节
- **代码公开**:让其他研究者验证
- **数据公开**:让其他研究者复用
- **主动复现**:复现其他研究者的结果

### 11.33.3　社会仿真作为元科学工具

社会仿真天然支持元科学:

- 仿真可以"一键复现"(同配置 + 同种子 = 同结果)
- 仿真可以严格预注册(条件、指标、判定规则)
- 仿真可以开放数据(合成数据 + 配置)
- 仿真可以开放代码(GAWorld 是 MIT)

读者做仿真研究时,要充分利用这些元科学优势。

---

## 11.34　本章小结(最终扩展版)

经过本章,读者应该已经具备:

- 仿真数据分析的核心流程
- 三层数据(原始日志、状态日志、记忆快照)的使用
- 指标白话化
- 偏离度、分叉点、轨迹对齐
- 四张必画图
- 异质性分析
- 稳健性检验
- 长期趋势检测(时间序列、变化点检测、ARIMA)
- 大规模数据处理
- 可视化最佳实践
- 高级统计方法(GLM、生存分析、多层模型、贝叶斯分析)
- 数据分析的工程实践
- 数据伦理
- 因果推断(倾向得分匹配、双重差分、断点回归、工具变量、合成控制)
- 元科学实践

最后,祝读者分析顺利、数据揭示真相、结论可信!

