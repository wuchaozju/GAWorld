# 回放、分析与导出

运行结束后，先确认当前世界与城市，再选择要查看的运行。轨迹用于追踪行动，状态历史用于比较变化，日志和记忆用于回查具体经历。

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

平行世界的结果位于工作区的 `output/parallel_worlds/` 下对应实验目录，其中包括 `experiment.json`、`report.json`、`divergence_summary.md` 与各世界的输出。

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

按当前运行生成的文件选择路径。`Recorder` 和记忆访问接口见 [记录与记忆](api/storage.md)。
