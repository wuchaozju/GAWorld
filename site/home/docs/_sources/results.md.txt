# 回放、分析与导出

运行结束后，先确认当前世界与城市，再选择要查看的运行。轨迹用于追踪行动，状态历史用于比较变化，日志和记忆用于回查具体经历。

## 功能与准备

本章用于找到一次运行的轨迹、状态和日志，并把结果带入后续分析。准备一个已有输出的运行，先确认其城市、世界与运行编号，再选择回放、Analytics 或文件读取。

```{figure} _static/screenshots/replay.png
:alt: 仿真回放界面，地图显示居民位置，右侧显示行动，下方是播放时间轴
:figclass: guide-shot guide-tall
:target: _static/screenshots/replay.png

轨迹回放示例。上方选择运行，下方拖动时间轴，右侧查看对应居民的行动。 点击图片查看完整尺寸。
```

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

```{figure} _static/screenshots/analytics.png
:alt: 仿真结果分析界面，包含运行选择、总览和居民状态曲线
:figclass: guide-shot guide-tall
:target: _static/screenshots/analytics.png

Analytics 示例。右上角选择运行，下面查看运行总览与状态变化。 点击图片查看完整尺寸。
```

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

## 完成后检查

在回放与 Analytics 中核对所选运行，比较居民编号与时间范围。下载或读取文件后，检查字段和记录数量；将结果文件与对应配置放在一起，供后续复查。

## 代码结构与执行流程

### 模块分工

```{container} code-map

| 源码位置 | 职责 |
| --- | --- |
| [gaworld/apps/visualizer.py](https://github.com/wuchaozju/GAWorld/blob/main/gaworld/apps/visualizer.py) | 记录仿真帧，写入实时轨迹及按运行编号归档的轨迹。 |
| [gaworld/apps/replay\_runs.py](https://github.com/wuchaozju/GAWorld/blob/main/gaworld/apps/replay_runs.py) | 发现实时、归档及情景实验中的可回放运行。 |
| [gaworld/apps/analytics.py](https://github.com/wuchaozju/GAWorld/blob/main/gaworld/apps/analytics.py) | 读取状态、经济、社交与行为文件，生成分析页的数据。 |
| [gaworld/apps/world\_paths.py](https://github.com/wuchaozju/GAWorld/blob/main/gaworld/apps/world_paths.py) | 定位当前世界的记录、日志、记忆和运行根目录。 |
| [gaworld/kernel/recorder.py](https://github.com/wuchaozju/GAWorld/blob/main/gaworld/kernel/recorder.py) | 把统一事件表写成 JSONL 文件。 |
| [site/dashboard/analytics.js](https://github.com/wuchaozju/GAWorld/blob/main/site/dashboard/analytics.js) | 读取分析接口，展示所选运行的统计与图表。 |

```

### 执行流程

```text
仿真与插件 → 轨迹 / 状态 CSV / 事件 JSONL
  → replay_runs 发现运行 → 回放页面
  → analytics 按目录读取 → Analytics 图表
```

visualizer 在写入实时 `simulation_trace.json` 的同时维护 `visualization/runs/<run_id>/` 下的轨迹归档。replay_runs 读取轨迹元信息建立运行列表；Analytics 按调用方选定的目录汇总文件。统一事件流由 Recorder 按表写入，经济和记忆等模块也保存各自的结果。

### 从哪里修改

新增分析图表时，同时检查 `apps/analytics.py` 的数据读取和 `analytics.js` 的展示。新增结构化事件时，查看 Recorder 及对应插件的记录调用。读取网页当前世界的数据时，通过 `world_paths.py` 解析路径。
