# 研究工作台

研究工作台把研究想法或论文转成实验方案，并进一步生成预注册协议、运行平行世界和汇总结果。

## 功能与准备

本章用于把研究问题或论文整理为可执行的设计，并保存假设、测量指标与判定规则。准备研究材料、城市和居民，并分别确认方案分析模型与仿真模型。

## 从问题到协议

```text
研究想法 / 论文 → 解读与审阅 → 实验设计 → 预注册协议
                                            ↓
研究报告 ← 结果解释 ← 代码判定 ← 仿真运行 ← 跑前检查
```

控制台入口为 **研究工作台**。分析方案所用模型与居民仿真所用模型可以分别设置。

```{figure} _static/screenshots/research.png
:alt: GAWorld 研究工作台的材料输入与研究列表
:figclass: guide-shot
:target: _static/screenshots/research.png

研究工作台示例。在左侧输入想法或论文材料、选择分析模型；右侧查看方案与研究记录。 点击图片查看完整尺寸。
```

## 选择研究方式

| 任务 | 使用方式 |
| --- | --- |
| 事先写明假设、条件、指标与判定规则 | 本页的预注册研究流程 |
| 手动改变事件或参数，探索效应与分叉轨迹 | [平行世界与对照实验](parallel-worlds.md) |
| 收集不同城市或群体的回答 | [访谈与群体采访](interviews.md) |
| 比较政策文本，或组织角色回合互动 | [政策推演与严肃游戏](policy-games.md) |

研究协议支持平行世界实验，以及运行后继续采访各世界居民的组合研究（`composite`）。组合研究在协议中保存题目与选项，并将跑后问卷纳入结果。

## 从研究想法开始

1. 选择 **研究想法**，写清研究对象、干预、比较条件和结果变量。
2. 选择分析模型，生成实施方案。
3. 比较候选设计中的人口、时间跨度、事件与测量指标。
4. 选择需要执行的设计，点击 **转成研究**。

例如可以提出：在同一座城市中，比较提供租金补贴与保持基线两种条件下，低收入居民的压力和经济安全感如何变化。

## 从论文开始

上传 TXT、Markdown 或带文字层的 PDF。先解读论文，再检查理论、方法、关键变量、主要发现、研究问题与假设。完成审阅后据此生成实验方案。

```{note}
把结果变量对应到 GAWorld 可以记录的指标，并在运行前明确预测方向和最小效应。保存审阅后的解读与预注册协议。
```

## 检查测量指标

在协议中为每条假设指定指标、处理条件、对照条件、预测方向与最小效应。选择编译器支持的状态变量或可计分问卷题；编译结果中的 `dropped` 列出被移除的项目及原因。

跑前检查会估算调用量并核对协议。调整居民数量、天数、种子和运行模式后，重新检查，再批准运行。

## 预注册与跑前检查

协议列出条件、指标、条件之间的对比、预测方向与最小效应。检查运行天数、种子、参与居民和模型，再进行跑前检查。

通过检查后批准并运行。协议中无法执行的部分会在编译结果中列出，应在开始前完成审阅。

## 执行协议与查看实验

平行世界从共同基线创建不同条件。研究按种子运行，记录各世界输出以及条件之间的差异。分析中包括配对估计、事件前平衡、安慰剂检查和跨种子重复等结果。

从研究卡片进入对应的平行世界实验，可查看分歧曲线、轨迹与结果文件。

## 查看判定与报告

代码按协议中的指标和预测给出假设判定；模型根据已有结果补充解释。查看报告时，将预注册条件、结果数值与运行记录一起核对。

## 结果目录

| 目录 | 内容 |
| --- | --- |
| `output/research/<id>.json` | 研究方案 |
| `output/research/studies/<id>/` | 研究协议、状态与报告 |
| `output/parallel_worlds/` | 平行世界实验及各条件输出 |
| `output/research/policy/` | 政策仿真结果 |
| `output/research/serious_games/` | 严肃游戏设计与会话 |

研究方案与协议保存在工作区的研究目录，账号部署按创建者管理访问。各次仿真的日志与状态文件见 [回放、分析与导出](results.md)。

## 完成后检查

运行前检查协议中的条件、指标、种子与预期方向；运行后对照报告中的判定、数值和对应平行世界。组合研究还需要查看跑后问卷的有效回答与计分结果。

## 代码结构与执行流程

### 模块分工

```{container} code-map

| 源码位置 | 职责 |
| --- | --- |
| [site/dashboard/research.js](https://github.com/wuchaozju/GAWorld/blob/main/site/dashboard/research.js) | 研究工作台页面：材料、方案、研究阶段和报告交互。 |
| [gaworld/apps/research\_api.py](https://github.com/wuchaozju/GAWorld/blob/main/gaworld/apps/research_api.py) | 处理分析、协议编译、批准、运行和报告请求。 |
| [gaworld/research/workbench.py](https://github.com/wuchaozju/GAWorld/blob/main/gaworld/research/workbench.py) | 读取功能目录，将想法或论文转为 ResearchPlan。 |
| [gaworld/research/protocol.py](https://github.com/wuchaozju/GAWorld/blob/main/gaworld/research/protocol.py) | 把方案编译成条件、指标和假设，执行跑前检查。 |
| [gaworld/research/study.py](https://github.com/wuchaozju/GAWorld/blob/main/gaworld/research/study.py) | 保存研究阶段、协议与运行关联信息。 |
| [gaworld/research/backends.py](https://github.com/wuchaozju/GAWorld/blob/main/gaworld/research/backends.py) | 按协议调用平行世界及组合研究中的跑后问卷。 |
| [gaworld/research/evaluate.py](https://github.com/wuchaozju/GAWorld/blob/main/gaworld/research/evaluate.py) | 按固定规则计算效应与假设判定。 |
| [gaworld/research/report.py](https://github.com/wuchaozju/GAWorld/blob/main/gaworld/research/report.py) | 将协议、结果和解释组织为研究报告。 |

```

### 执行流程

```text
材料 → workbench 方案 → protocol 协议与检查 → study 保存
批准运行 → backends → 平行世界 / 跑后问卷
结果 → evaluate 判定 → interpret 解释 → report 报告
```

方案生成读取 `docs/FEATURES.md` 中的能力目录；协议编译结合 `measures.py` 中的指标登记，把设计转为执行条件。backends 将每个种子的条件转换为平行世界实验。evaluate 读取数值计算判定，`interpret.py` 根据已有结果生成解释。

### 从哪里修改

修改设计生成查看 `workbench.py`，增加可测指标时同时核对 `measures.py`、数据来源与 `evaluate.py`。改变协议格式或检查条件查看 `protocol.py`，改变报告展示查看 `report.py` 与前端。

## 参考

[Python 与 HTTP 接口](integration.md) · [平行世界与对照实验](parallel-worlds.md) · [客户端 API](api/client.md)
