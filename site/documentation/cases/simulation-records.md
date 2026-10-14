# 已有仿真实验

仓库保存了信息传播、观点极化、记忆一致性、经济状态、政策事件和社交网络等实验的设计与运行记录。本页按研究问题整理入口，便于从一个案例找到对应的条件、指标和报告。

本页的运行范围依据 **2026 年 6 月 6 日实验报告，Dev 版本 `75c6ed8`** 整理。每项记录反映该次实验的实际进度；在当前版本开展新的实验，可按 [平行世界教程](../parallel-worlds.md) 重新建立条件。

## 信息传播与观点极化

### 谣言传播与信息干预

**研究问题**：居民接收到一条传闻后，信息风险与跨观点接触如何变化？增加信息多样性后，结果是否不同？

原实验使用 5 位居民，设置三个条件：

| 条件 | 设置 |
| --- | --- |
| Control | 自然演化 |
| Treatment A | 第 1 天 08:00 向 1 号居民注入地铁涨价传闻 |
| Treatment B | 同一传闻，加上 `diversity_boost=0.3` |

历史报告记录三组均有输出，实际覆盖约 1–2 天。报告中的平均 `intervention_reward` 分别为 0.3888、0.3712 和 0.3860；同时，`misinformation_risk` 在三组中均为零。

阅读这个案例时，先核对各组记录数和时间范围，再结合居民原话、跨观点接触与干预指标解释差异。这里的干预奖励与信息风险是两个指标，奖励差异应按其自身定义阅读。

[实验设计](https://github.com/wuchaozju/GAWorld/blob/main/docs/proposals/EXP-INFO-001_misinfo_spread.md) · [执行脚本](https://github.com/wuchaozju/GAWorld/blob/main/docs/proposals/experiments/exp_misinfo_spread.py) · [历史报告](https://github.com/wuchaozju/GAWorld/blob/main/docs/EXPERIMENTS_REPORT.md)

### 极化与回音壁

**研究问题**：增加跨观点曝光，是否改变居民立场分布与极化指标？

原实验以 5 位居民比较基准和多样性干预，在第 3 天广播争议性公共政策事件，历史报告记录实际运行 5 天。分析同时使用极化指数、立场标准差与跨观点曝光。

报告中，处理组的最终极化指数高于基准，而平均立场标准差较低。阅读时分别核对两项统计的定义、汇总时间和居民轨迹，可以看出不同指标为何可能呈现不同方向。

[实验设计](https://github.com/wuchaozju/GAWorld/blob/main/docs/proposals/EXP-POL-001_polarization.md) · [执行脚本](https://github.com/wuchaozju/GAWorld/blob/main/docs/proposals/experiments/exp_polarization.py)

## 记忆、经济与社会关系

| 案例 | 条件与分析对象 | 历史记录中的运行范围 |
| --- | --- | --- |
| 记忆一致性 | 完整记忆、阶段重置、删除摘要、注入冲突记忆；比较阶段前后的状态与行为 | 完整记忆条件完成两个阶段，其余条件的第二阶段未完成 |
| 宏观经济与幸福感 | 观察 emotion、stress 与 econ_security 的时间变化 | 保存了 5 位居民、3 天运行的分析报告 |
| 网络演化与同质性 | 观察共同位置、特质相似性与网络连接 | 有效记录主要覆盖第 0–1 天，适合回查初始网络 |

记忆案例可从 [比较报告](https://github.com/wuchaozju/GAWorld/blob/main/docs/proposals/results/exp_memory_consistency/COMPARISON_REPORT.md) 入手；经济案例提供 [状态变化分析](https://github.com/wuchaozju/GAWorld/blob/main/docs/proposals/results/exp_macro_economy/run_42/wellbeing_report.md)；网络案例的条件与指标见 [实验设计](https://github.com/wuchaozju/GAWorld/blob/main/docs/proposals/EXP-NET-001_network_evolution.md)。

对这些记录，先确定哪些条件和阶段实际有数据，再在相同时间范围内比较。原始状态序列、日志和记忆能够帮助追溯报告中的变化。

## 政策事件比较

已有政策框架包含四类事件：临时交通限行、医疗报销比例上调、职业技能培训补贴和住房补贴。它们使用 `compare-event` 比较有事件与无事件两个条件，并在第 3 天注入事件。

阅读顺序是：确认政策文本与发生时间，找到两组状态历史，再查看报告中的指标差值。事件描述、模型中的状态响应与账本中的实际支付分别对应不同机制，按实验配置确认自己分析的是哪一种。

[政策实验设计](https://github.com/wuchaozju/GAWorld/blob/main/docs/proposals/EXP-POLICY-001_policy_framework.md) · [执行脚本](https://github.com/wuchaozju/GAWorld/blob/main/docs/proposals/experiments/exp_policy_framework.py)

## 从已有案例开始自己的实验

1. 选择一个研究问题，记录原案例的居民、事件、指标与实际运行时长。
2. 在当前版本中用 [平行世界](../parallel-worlds.md) 建立共同输入与各组差异。
3. 用 [研究工作台](../research.md) 保存假设、指标、种子与判定规则。
4. 将新实验的配置、代码版本和输出一起保存，按 [结果分析](../results.md) 阅读状态记录与报告。

完整历史清单见仓库的 [GAWorld 仿真实验报告](https://github.com/wuchaozju/GAWorld/blob/main/docs/EXPERIMENTS_REPORT.md)。
