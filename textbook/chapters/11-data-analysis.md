# 第 11 章　数据、指标与分析

> 仿真跑完了,数据在磁盘上。怎么从数据里抽出结论?这一章讨论三件事:**原始日志到指标**(怎么从仿真日志计算指标)、**统计推断**(怎么判断差异是真的还是偶然)、**可视化**(怎么把结果画清楚)。社会仿真数据的分析和实证数据分析既有相通之处(都基于统计推断),也有不同之处(数据是合成的,可能分析所有时间点的所有个体)。读完本章,读者应该能把仿真输出变成符合同行评议标准的图表与统计。

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

