# 经典行为实验

经典实验库让同一批居民回答不同条件下的题目，比较框架、锚点和博弈规则改变后的选择。它读取居民的初始状态与档案，通过独立问答运行六个范式。

## 案例：获益与损失框架

**研究问题**：面对结果等价、表达方式不同的两个方案，居民选择确定方案的比例是否变化？

框架效应模块使用获益框架与损失框架。每位居民分别回答两个条件，两次调用各自提供相同居民档案，并独立生成回答。分析时再按居民编号配对，计算“获益框架 − 损失框架”的选择比例差值。

这里使用的是档案驱动的一次性问答。若需要研究居民经历事件后的回答，可使用 [研究工作台的组合研究](../research.md)。

## 运行框架效应案例

先完成 [模型配置](../models.md)，确认当前本地配置的居民输入。下面选择至多 20 位居民，每人每条件调用一次。

```bash
python -m gaworld.experiments.classics list
python -m gaworld.experiments.classics run framing --name framing-case --subject-limit 20 --dry-run
```

居民数据充足时，预览显示 **40 次调用**。确认范式、样本与模型后执行：

```bash
python -m gaworld.experiments.classics run framing --name framing-case --subject-limit 20
```

需要指定模型时，在运行命令中追加 `--provider` 与已配置的后端名称。相同命令可接续已有结果，失败的调用会重试；新的实验条件使用新的 `--name` 保存。

## 输出与判读

结果位于 `output/experiments/classics/framing-case/`：

| 文件 | 内容 |
| --- | --- |
| `spec.json` | 范式、样本、种子、采样与模型设置 |
| `results.jsonl` | 每次调用的原始回答、居民信息与模型路由 |
| `summary.json` | 条件水平、配对效应与统计结果 |
| `report.md` | 可阅读的实验报告 |

按“有效配对人数 → 两组选择比例 → 配对效应 → 区间与判定”的顺序阅读。当前规则在有效居民少于 10 人时标记样本不足；方向符合预期且 `p < 0.05` 时标记复现，显著反向时标记反向，其余标记未复现。

这些判定描述当前题面和居民档案下的模型回答方向。人类实验数字在报告中作为参考，分析同时保留各范式的解释说明。

重新分析已有回答：

```bash
python -m gaworld.experiments.classics analyze --name framing-case
```

分析命令直接读取保存的回答，可以在调整解析或分析代码后重新生成报告。

## 六个可选范式

| ID | 比较条件 | 分析指标 |
| --- | --- | --- |
| `framing` | 获益框架与损失框架 | 选择确定方案的比例 |
| `anchoring` | 高锚与低锚 | 数量估计值的对数 |
| `dictator_ultimatum` | 独裁者与最后通牒提议方 | 分给对方的比例 |
| `ultimatum_responder` | 低额与均等分配 | 拒绝提议的比例 |
| `trust_ingroup` | 同小区居民与外地人 | 转出的金额比例 |
| `public_goods_mpcr` | 高与低边际人均回报 | 公共账户投入比例 |

命令中可同时列出多个 ID，例如 `run framing anchoring`。锚定包含三个题目，每位居民共回答六次；运行前用同一组参数加 `--dry-run` 查看总调用量。

## 对应代码

```{container} code-map

| 位置 | 在本案例中的作用 |
| --- | --- |
| [experiments/subjects.py](https://github.com/wuchaozju/GAWorld/blob/main/gaworld/experiments/subjects.py) | 读取居民状态与档案，构造受试者 |
| [classics/paradigms.py](https://github.com/wuchaozju/GAWorld/blob/main/gaworld/experiments/classics/paradigms.py) | 定义条件、题面、解析与预期方向 |
| [classics/runner.py](https://github.com/wuchaozju/GAWorld/blob/main/gaworld/experiments/classics/runner.py) | 展开居民与条件，调用模型并保存原始回答 |
| [classics/analysis.py](https://github.com/wuchaozju/GAWorld/blob/main/gaworld/experiments/classics/analysis.py) | 按居民配对，生成区间、检验与报告 |

```

完整设计与范式说明见 [经典实验库](https://github.com/wuchaozju/GAWorld/blob/main/docs/CLASSIC_EXPERIMENTS.md)。
