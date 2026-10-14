# Agent Skills（智能体技能）

## 概述

Skill 是居民可以复用的操作知识。GAWorld 读取 Markdown 技能文件，将相关内容加入居民感知和工作任务说明；居民也可以从经历中提炼私有技能。

## 技能目录

```text
data/skills/                         # 全局技能库
└── meeting-notes.md
output/memory/agent_31_skills/        # 居民私有技能库
└── meeting-notes.md
```

运行使用当前输出目录。技能 ID 是文件名去掉 `.md` 后的部分；同 ID 的私有技能优先于全局技能。

## 文件格式

```markdown
---
name: 会议记录
description: 将讨论整理为结论、行动项和待确认问题
triggers: [会议, 讨论, 记录]
source: global
origin: seed
---

1. 列出已经确定的结论。
2. 为每个行动项记录负责人和时间。
3. 将尚未确认的问题单独列出。
```

Frontmatter 支持标量和单层列表。详细编写方法见 [Skill 编写指南](skill_guide.md)。

## 注册与挂载

```python
from gaworld.skills import SkillRegistry

registry = SkillRegistry()
agent = {"id": 31, "skill_ids": []}
attached = registry.attach_to_agent(agent, "meeting-notes")
print(attached)
print(registry.list_for_agent(agent))
```

将文件放入全局库后再挂载。文件更改后重启运行，或调用 `registry.reload()` 重新扫描。

## 注入到行为与工作

`skills.inject_into_cognition` 控制感知提示词中的技能内容；`skills.inject_into_work_brief` 控制工作说明中的技能内容。`skills.max_per_prompt` 设置感知中的技能数量上限。

## 从经历中提炼技能

`memory.skill_consolidation` 管理自动提炼。默认关闭；启用后按配置周期读取近期经历，调用模型提取可复用方法，并保存为居民私有技能。

```python
from gaworld.settings import CONFIG

CONFIG["memory"]["skill_consolidation"]["enabled"] = True
```

`every_days` 设置周期，`lookback_days` 设置经历范围，`min_episodes` 设置最低经历数量。

## 参考

- [Skills 模块](api/skills.md)：类型、注册表和经验提炼函数。
- [模块与参数管理](module_and_parameter_management.md)：运行配置。

```{toctree}
:maxdepth: 1
:hidden:

skill_guide
```
