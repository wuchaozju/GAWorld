# 存储与结果访问

一次仿真使用选定的居民、城市与模型配置，推进居民行动，并记录状态、记忆、关系和环境变化。

## 设置运行范围

在仿真页面选择居民，设置时长与模型，然后保存配置。先完成一次短运行，确认居民、环境和模型输出符合实验设置，再增加运行规模。

| 设置 | 作用 |
| --- | --- |
| 居民选择 | 决定参与本次运行的智能体 |
| 仿真时长 | 决定推进多少天、月或年 |
| 默认模型与日程模型 | 决定行动和日程所使用的后端 |
| 长时段快进 | 将日内细节压缩为阶段简报 |
| 步长单位 | 在快进中选择天、月或年 |
| 随机性 | 调节快进模式中的突发事件频率与状态波动 |

## 启动、观察与停止

点击启动后，在日志中查看运行进度。轨迹回放展示居民位置与移动，居民详情展示状态、记忆和关系。

需要结束当前运行时，使用控制台的停止操作。查看最后的日志与已保存结果，再决定下一次运行的参数。

## 长时段快进

研究长期变化时，在工具栏开启 **长时段快进**，选择步长单位和时长。快进以每位居民的阶段简报推进状态、目标和关系。

| 时间尺度 | 运行方式 |
| --- | --- |
| 日内行动 | 常规仿真，按日内时刻推进 |
| 数十天到数百天 | 按天快进，每天生成日简报 |
| 月度变化 | 按月快进，每月生成阶段简报 |
| 年度变化 | 按年快进，每年生成阶段简报 |

时间尺度决定输出的细节层次。对照实验中的各组使用相同的步长与快进设置。

(outputs)=
## 查找结果文件

以下路径相对于当前运行的输出目录。默认工作区使用 `output/`；城市运行使用对应城市目录，多人部署按当前世界隔离保存。

| 路径 | 内容 |
| --- | --- |
| `logs/` | 完整日志与各居民日志 |
| `memory/` | 居民记忆、状态、技能成长与关系记录 |
| `state/agent_state_history.csv` | 居民状态时间序列 |
| `visualization/simulation_trace.json` | 仿真轨迹 |
| `economy/` | 收支账本、财富快照与宏观经济状态 |
| `network/social_network.png` | 社交网络图 |
| `records/` | 家庭、出行等系统的统一事件流 |
| `intervention/intervention_metrics.csv` | 干预评估时间序列 |
| `work/` | 工作队列、任务与产物 |

部分文件在相应功能启用并运行后生成。

## 在控制台分析

打开 **Analytics**，选择要查看的运行。按研究问题查看状态历史、经济变化、社交结构与行为分布；需要追溯单个居民时，再打开其日志或记忆。

导出运行日志可使用控制台的日志导出功能。CSV 文件可用表格软件或 Python 读取，JSON / JSONL 文件可用于后续分析。

## 保存实验配置

把城市、居民初始数据、模型、种子、运行时长、步长与干预设置一起保存。比较多个运行时，从相同基线出发，记录每组改变的条件，再查看配对结果。

平行世界的结果位于 `parallel_worlds/` 下对应实验目录，其中包括 `experiment.json`、`report.json`、`divergence_summary.md` 与各世界的输出。

## 使用 Python 读取结果

将 `output_dir` 设为本次运行的实际输出目录：

```python
from pathlib import Path
import pandas as pd

output_dir = Path("output")
state = pd.read_csv(output_dir / "state" / "agent_state_history.csv")
print(state.head())
```

结构化事件使用 JSONL，每行是一条 JSON 记录：

```python
import json
from pathlib import Path

record_path = Path("output/records/agent.step.jsonl")
with record_path.open(encoding="utf-8") as stream:
    for line in stream:
        row = json.loads(line)
        print(row)
```

按当前运行生成的文件选择路径。`Recorder` 和记忆访问接口见 [存储模块](api/storage.md)。
