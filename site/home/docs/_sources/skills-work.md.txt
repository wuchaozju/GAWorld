# 技能与真实工作

Skill 文件说明一种能力的适用场景和操作步骤。感知阶段读取居民已挂载或私有的技能；工作路由再根据任务文本、描述与触发词选择相关技能，加入工作说明。

本例把会议记录技能保存给当前本地城市的 1 号居民。先完成 [第一次仿真](quickstart.md)，并在同一工作区中操作。

## 技能如何参与行动

全局技能放在 `data/skills/`，挂载后供居民使用。私有技能保存在当前输出目录的 `memory/agent_<id>_skills/`，按居民读取；同 ID 时使用私有版本。

`skills.inject_into_cognition` 控制感知提示词中的技能内容，`skills.inject_into_work_brief` 控制工作任务说明中的技能内容。

## 创建第一个技能

在工作区的 `data/skills/` 中创建 `meeting-notes.md`：

```markdown
---
name: 会议记录
description: 将讨论整理为结论、行动项和待确认问题
triggers: [会议, 讨论, 记录]
source: global
origin: seed
---

1. 记录讨论主题和参加者。
2. 把已经达成一致的内容写成结论。
3. 列出行动项、负责人和完成时间。
4. 将尚未确定的问题单独列出。
```

## Frontmatter 字段

| 字段 | 含义 |
| --- | --- |
| `name` | 技能名称 |
| `description` | 适用任务与能力描述 |
| `triggers` | 用于匹配任务文本的触发词列表 |
| `source` | `global` 或 `private` |
| `origin` | 例如 `seed` 或 `consolidation` |
| `owner_agent_id` | 私有技能所属居民 |
| `created_day` | 创建时的仿真日，可选 |

解析器支持平铺字段和单层列表。正文使用普通 Markdown，按实际操作顺序写步骤。

## 将技能保存给实际居民

本例把刚创建的全局技能保存为居民的私有副本。私有技能由注册表按居民编号自动读取，适合在工作区中直接配置。

先在 Agent Studio 确认目标居民编号，再在工作区执行：

```python
from copy import deepcopy
from pathlib import Path
from gaworld.settings import build_config
from gaworld.skills import SkillRegistry

agent_id = 1
config = build_config()
registry = SkillRegistry(memory_dir=config["memory_dir"])
skill = registry.get("meeting-notes")
if skill is None:
    raise ValueError("请先创建 data/skills/meeting-notes.md")
registry.save_private(agent_id, deepcopy(skill))
path = Path(registry.memory_dir) / f"agent_{agent_id}_skills/meeting-notes.md"
print("已保存：", path.resolve())

# 用一个新注册表从文件重新读取，验证保存结果。
check = SkillRegistry(memory_dir=config["memory_dir"])
print([item.skill_id for item in check.list_for_agent(agent_id)])
```

最后一行应包含 `meeting-notes`。重新打开 Agent Studio 的该居民技能页，可以查看私有技能。

### 在下一次运行中使用

确认 `skills.inject_into_cognition` 已启用，使用同一城市、同一居民启动普通运行。`SkillsPlugin` 会在感知阶段读取其私有技能；`skills.max_per_prompt` 控制一次注入的数量。需要观察会议记录相关行为时，在居民的任务或日程中安排对应活动，再检查行动日志。

文件保存和读取是技能接入的检查点；实际行动取决于居民当时的任务、日程与模型决策。真实工作产物按本页后面的工作队列流程检查。

### 团队世界与全局技能挂载

团队世界的私有技能保存在服务器的 `output/worlds/<世界编号>/memory/agent_<居民编号>_skills/`。有服务器文件权限的维护者可将上例 `memory_dir` 显式设为该世界的 `output/worlds/<世界编号>/memory/` 目录，再保存技能；网页会话中的世界选择与本地 Python 配置分别管理。

`attach_to_agent(agent, skill_id)` 用于扩展运行代码：它修改已经初始化的居民对象的 `skill_ids`，作用于该次运行。需要每次启动都挂载全局技能时，可在插件的居民初始化钩子中对实际居民执行挂载，参见 [编写插件](plugins.md)。本页的私有副本流程通过文件保存配置。

## 编写建议

- 每个技能处理一个明确任务。
- 在描述中写清适用场景，在正文中写清步骤。
- 需要产物时说明格式和内容。
- 用少量准确的触发词匹配任务。
- 在短运行中查看日志和工作产物，再调整技能内容。

## 常见问题

### 找不到技能

检查文件目录、扩展名和技能 ID。修改文件后调用 `reload()` 或重启运行。

### 技能没有进入提示词

检查实际运行的记忆目录是否包含该居民的私有文件，或运行对象是否已挂载全局技能；再核对 `inject_into_cognition`、`inject_into_work_brief` 和 `max_per_prompt`。

### 私有技能与全局技能同名

同 ID 时优先使用居民私有版本。

## 从经历中提炼技能

`memory.skill_consolidation` 控制经验提炼，默认关闭。开启后按 `every_days` 周期读取 `lookback_days` 范围内的经历，在满足 `min_episodes` 后调用模型生成私有技能。

```python
from gaworld.settings import CONFIG

CONFIG["memory"]["skill_consolidation"]["enabled"] = True
```

## 启用真实工作

真实工作将居民的工作活动交给适配器执行，生成网页、代码、文章、教案或研究笔记。任务根据职业能力、兴趣与技能匹配，工作机会市场记录浏览、接单和完成状态。

在运行配置中启用 `real_work.enabled`。命令行可以通过 JSON 覆盖设置后启动一次短运行：

```bash
GAWORLD_CONFIG_OVERRIDES='{"real_work":{"enabled":true}}' gaworld run --sim-days 1
```

在日志中检查能力推导与 `WorkerPool started`，再查看任务队列。`real_work.max_concurrent_tasks` 控制并发任务数，`real_work.task_timeout_seconds` 控制单个任务超时，`real_work.market` 配置工作机会市场。

## 查看任务和产物

以下路径相对于当前运行的输出目录：

| 路径 | 内容 |
| --- | --- |
| `work/capabilities.json` | 职业与能力映射缓存 |
| `work/queue.jsonl` | 任务提交、领取与结果记录 |
| `work/market.jsonl` | 工作机会与状态变化 |
| `work/agent_<id>/<task_id>/` | 该居民完成的文件 |

产物可能包括 `index.html`、`poster.svg`、`main.py`、`article.md`、`lesson_plan.md` 或 `research_note.md`，具体取决于任务类型。结合队列中的结果与产物文件检查任务是否完成。

任务匹配、适配器扩展与排查方法见仓库的 [真实工作执行说明](https://github.com/wuchaozju/GAWorld/blob/main/docs/REAL_WORK_USAGE.md)；技能类型与注册方法见 [技能 API](api/skills.md)。

## 完成后检查

先用新注册表从实际记忆目录读回私有技能，再启动短运行。真实工作启用后，结合 `work/queue.jsonl` 中的任务状态与居民任务目录中的文件检查结果；技能挂载和任务产物分别核对。

## 代码结构与执行流程

### 模块分工

```{container} code-map

| 源码位置 | 职责 |
| --- | --- |
| [gaworld/skills/registry.py](https://github.com/wuchaozju/GAWorld/blob/main/gaworld/skills/registry.py) | SkillRegistry 读取全局和私有技能，管理挂载与保存。 |
| [gaworld/skills/plugin.py](https://github.com/wuchaozju/GAWorld/blob/main/gaworld/skills/plugin.py) | SkillsPlugin 将技能加入感知，并在记忆整理阶段触发经验提炼。 |
| [gaworld/skills/consolidation.py](https://github.com/wuchaozju/GAWorld/blob/main/gaworld/skills/consolidation.py) | 从近期经历生成居民的私有技能。 |
| [gaworld/work/plugin.py](https://github.com/wuchaozju/GAWorld/blob/main/gaworld/work/plugin.py) | RealWorkPlugin 管理真实工作生命周期，并处理工作行动的结果。 |
| [gaworld/work/runtime.py](https://github.com/wuchaozju/GAWorld/blob/main/gaworld/work/runtime.py) | RealWorkRuntime 连接任务路由、市场、队列和工作线程。 |
| [gaworld/work/router.py](https://github.com/wuchaozju/GAWorld/blob/main/gaworld/work/router.py) | 根据行动、能力和市场机会生成工作任务。 |
| [gaworld/work/worker.py](https://github.com/wuchaozju/GAWorld/blob/main/gaworld/work/worker.py) | WorkerPool 从队列领取任务，交给适配器执行。 |
| [gaworld/work/adapters/base.py](https://github.com/wuchaozju/GAWorld/blob/main/gaworld/work/adapters/base.py) | 定义适配器接口；同目录的具体适配器生成各类产物。 |

```

### 执行流程

```text
Skill 文件 → SkillRegistry → SkillsPlugin → 居民感知
工作行动 → RealWorkPlugin → Router → Queue → WorkerPool → Adapter
完成的产物 → Runtime 回收 → 居民的行动结果
```

技能通过 `perception.sections` 加入居民感知，经验提炼通过 `memory.consolidate` 触发。真实工作在仿真开始时启动线程池，在 `action.outcome` 阶段分派任务并回收已完成的产物，结束时停止线程池。任务正文中的技能内容由工作路由结合当前行动选择。

### 从哪里修改

调整技能读取与优先级查看 `registry.py`，调整经验提炼查看 `consolidation.py`。增加文件产出类型时，在 `work/adapters/` 实现适配器，并核对路由与能力匹配。
