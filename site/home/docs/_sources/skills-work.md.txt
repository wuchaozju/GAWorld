# 技能与真实工作

Skill 文件说明一种能力的适用场景和操作步骤。GAWorld 根据技能描述与触发词选择相关内容，再加入居民的感知或工作说明。

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

## 挂载与检查

```python
from gaworld.skills import SkillRegistry

registry = SkillRegistry()
registry.reload()
skill = registry.get("meeting-notes")
print(skill.name if skill else "未找到技能")
```

确认文件被读取后，挂载到参与运行的居民：

```python
agent = {"id": 31, "skill_ids": []}
registry.attach_to_agent(agent, "meeting-notes")
print(registry.list_for_agent(agent))
```

在实际运行中，对初始化后的居民数据执行挂载，并保留该居民的技能配置。

## 创建私有技能

```python
from gaworld.skills import Skill, SkillRegistry

SkillRegistry().save_private(
    agent_id=31,
    skill=Skill(
        skill_id="meeting-notes",
        name="会议记录",
        description="按结论与行动项整理讨论",
        body="先写结论，再记录负责人、时间和待确认事项。",
        triggers=["会议", "讨论"],
    ),
)
```

私有技能由注册表按居民读取，无需另行挂载。

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

检查居民是否挂载了全局技能，以及 `inject_into_cognition` 或 `inject_into_work_brief` 是否启用。

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
