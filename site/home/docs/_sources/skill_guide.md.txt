# Skill 编写指南

Skill 文件说明一种能力的适用场景和操作步骤。GAWorld 根据技能描述与触发词选择相关内容，再加入居民的感知或工作说明。

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

确认文件被读取后，使用 `attach_to_agent()` 挂载到参与运行的居民。

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
