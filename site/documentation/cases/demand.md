# 需求估计提示词

需求估计实验在多个价格点询问购买意愿，比较不同提示方式下的回答。它将商品、居民与价格组合成调用网格，保存原始文本，再分析需求曲线及模型补全的情境信息。

## 研究问题与五种条件

**研究问题**：当商品价格变化时，模型如何判断是否购买？明确提供居民及商品情境，或说明价格随机化设计，会怎样改变回答？

| 条件（arm） | 提供的信息 |
| --- | --- |
| `blind` | 商品与价格 |
| `covariate` | 居民人口学信息，以及明确列出的收入、竞品价和上次购买价 |
| `unblinded` | 商品与价格，并说明随机化设计 |
| `agent` | 居民档案，以及购买记忆、货架价格和预算感受形式的情境 |
| `agent_unblinded` | 居民情境，并说明随机化设计 |

`agent` 与 `covariate` 使用同一批情境数值，通过不同文本形式传入。情境由居民、商品和种子生成，同一组合在各价格点保持一致；这里的购买记忆是实验构造的情境。

## 先运行一个小案例

完成 [模型配置](../models.md)，在当前工作区执行：

```bash
python -m gaworld.experiments --name demand-case --product-limit 1 --subject-limit 1 --arms blind agent --dry-run
```

本例比较 `blind` 和 `agent`，使用 1 个商品、1 位居民、11 个价格点与两类问题，共 **44 次调用**。`--dry-run` 保存计划并打印调用数量。

确认设置后执行：

```bash
python -m gaworld.experiments --name demand-case --product-limit 1 --subject-limit 1 --arms blind agent
```

模型默认使用工作区路由；也可追加 `--provider` 与已配置的后端名称。这个小案例用于检查输入、回答解析与报告输出。扩大样本时增加商品与居民，并保留一致的条件和采样设置。

`--draws` 控制无居民条件的采样次数，`--subject-draws` 控制每位居民每个组合的采样次数；调整任一参数后，可重新预览调用量。

## 两类问题分别看什么

| 问题 | 返回内容 | 分析目的 |
| --- | --- | --- |
| `elicit` | 模型补全的上次购买价、竞品价与保质期 | 检查这些回答是否随处理价格变化 |
| `purchase` | 购买或不购买 | 在各价格点汇总购买概率，形成需求曲线 |

在 `elicit` 中，被询问的情境变量会从提示词中移除，因此它观察模型自行补全信息的方式。`purchase` 则按各条件提供相应信息，观察购买决策。

例如，报告中的 `last_price` 斜率为正，表示模型自述的上次购买价随当前处理价格上升。比较购买曲线时，继续查看各条件的变化形状，以及明确提供情境后购买概率的过渡是否更接近阶跃。

## 输出与分析指标

文件保存在 `output/experiments/demand-case/`：`spec.json` 记录计划，`results.jsonl` 保存每次调用的原文，`summary.json` 与 `report.md` 保存分析结果。

| 指标 | 阅读方式 |
| --- | --- |
| 需求曲线 | 对照价格点、有效回答数与购买比例 |
| 情境变量斜率 | 查看模型补全的信息如何随处理价格改变 |
| `step_rule_agreement` | 比较不同条件的回答与“价格不高于竞品价就买”规则的一致程度 |
| `transition_width` | 查看购买概率处于 5%–95% 之间的相对价格带宽度 |

比较 `agent` 与 `covariate` 时，把需求曲线、过渡宽度和有效回答一起阅读；小样本下也要逐条回看原始文本。

重新分析已有结果：

```bash
python -m gaworld.experiments --analyze-only --name demand-case
```

相同运行命令支持接续已有回答。更换研究条件时使用新的名称，保留每次实验的配置与结果。

## 对应代码

```{container} code-map

| 位置 | 在本案例中的作用 |
| --- | --- |
| [stimulus.py](https://github.com/wuchaozju/GAWorld/blob/main/gaworld/experiments/stimulus.py) | 读取商品目录，定义相对价格网格 |
| [subjects.py](https://github.com/wuchaozju/GAWorld/blob/main/gaworld/experiments/subjects.py) | 构造居民与跨价格保持一致的情境 |
| [arms.py](https://github.com/wuchaozju/GAWorld/blob/main/gaworld/experiments/arms.py) | 将五种条件转成提示词 |
| [runner.py](https://github.com/wuchaozju/GAWorld/blob/main/gaworld/experiments/runner.py) | 展开调用网格，执行并保存回答 |
| [analysis.py](https://github.com/wuchaozju/GAWorld/blob/main/gaworld/experiments/analysis.py) | 解析回答，计算曲线、斜率与过渡宽度 |

```

实验背景、设计说明与首次运行记录见 [需求估计实验](https://github.com/wuchaozju/GAWorld/blob/main/docs/DEMAND_EXPERIMENT.md)。
