# Skill 系统 — 设计与使用

> 让仿真 agent 持有**可复用、可重排版的小技能**（Skill），技能既可以来自一个**全局库**（手写 markdown，全员共享），也可以由 agent**自己从经历中提炼**出来变成私有的；运行时 Skill 会注入到 cognition 和 work brief 提示词里，影响行为与产物。

设计原则与 `AGENTS.md` 一致：最小改动、可关闭、不破坏现有 tick 行为；新代码全在 `gaworld/skills/` 下，并配测试。

---

## 0. 关键决策（已确认）

| 决策项 | 选择 |
| --- | --- |
| 存储与共享 | **混合**：全局库（`data/skills/*.md`，全员共享）+ 私有库（`output/memory/agent_<id>_skills/*.md`，每 agent 一份） |
| 文件格式 | **Markdown + YAML frontmatter**（`name` / `description` / `triggers` / 其他元数据）—— 不依赖 PyYAML，内置极简解析器 |
| 经验 → Skill 触发 | **由仿真主循环周期触发**（`run_daily_memory_lifecycle`），默认 OFF；也开放 API 供脚本手动调用 |
| 接入深度 | **完整**：cognition 的 `perception` 提示词 + work router 的 brief（`【可用技能】` 块）—— adapter 直接拼 brief，无需改 |

---

## 1. 模块清单

```
gaworld/skills/
├── __init__.py            # 公开 API 重新导出
├── schemas.py             # Skill dataclass + Markdown/YAML 解析、序列化、slugify
├── registry.py            # SkillRegistry：全局 + 私有，attach/detach/save_private
├── prompt_helpers.py      # render_agent_skills / relevant_skills_for_text
└── consolidation.py       # summarize_experience_to_skill + run_skill_consolidation
```

接入点（surgical）：
- `gaworld/core/agent.py` — `Agent.skill_ids` 属性
- `gaworld/settings/runtime.py` — 新增 `memory.skill_consolidation` 与顶层 `skills` 配置块
- `gaworld/memory/lifecycle.py` — `run_daily_memory_lifecycle` 多走一步调 `run_skill_consolidation`
- `gaworld/sim/_cognition.py` — `perception` 提示词附上 agent 当前 skill 列表
- `gaworld/work/router.py` — `RealWorkRouter` 注入 `skill_registry`；`_build_brief_text` 追加 `【可用技能】`

---

## 2. Skill 文件格式

```markdown
---
name: 海报网格排版
description: 用三栏网格 + 单一主色，快速给宣传海报定排版
triggers: [海报, 排版, 设计, poster]
source: global              # 或 private
origin: seed                # 或 consolidation
owner_agent_id: 7           # 仅 private 必填
created_day: 12             # 可选
---

1. 先选一个主色（占面积 ≥ 60%），再选 1 个对比色和 1 个中性色。
2. 把版面切成上 / 中 / 下三个带，标题在上带，主图在中带，信息在下带。
3. 留白不要少于 8% 边距；字号梯度按 4:2:1 设置。
```

约束：
- **`skill_id` 就是文件名去掉 `.md`**。`slugify_skill_id()` 支持中文（CJK 统一表意区）、字母、数字、连字符、下划线；其他字符折叠成 `-`。
- **frontmatter 是 flat YAML**：只支持标量和单层 list `[a, b, c]`。不用 PyYAML——`schemas.py` 里有 60 行自带解析器，足够这个格式。
- **没有 frontmatter 也能用**：解析器降级把第一行当 `name`，剩下作为 `body`。

---

## 3. 注册表（SkillRegistry）

```python
from gaworld.skills import SkillRegistry

reg = SkillRegistry()  # 用 CONFIG["skills"]["global_dir"] 与 CONFIG["memory_dir"]
```

API：

| 方法 | 用途 |
|---|---|
| `list_global()` | 全局库里所有 Skill |
| `list_private(agent_id)` | 这个 agent 私有的 Skill |
| `list_for_agent(agent)` | 私有 + 已挂载的全局；**私有 id 同名时优先于全局** |
| `get(skill_id, agent_id=None)` | 单个查找；给了 agent_id 则私有优先 |
| `attach_to_agent(agent, skill_id)` | 把全局 skill 挂到 `agent["skill_ids"]`；id 不存在时拒绝并返回 `False` |
| `detach_from_agent(agent, skill_id)` | 卸下 |
| `save_private(agent_id, skill)` | 把 Skill 写到私有目录；id 为空时自动 slugify |
| `reload()` | 清缓存，下次访问重新扫盘 |

**Lazy 加载**：第一次访问全局/私有目录时才扫盘，扫一次之后缓存在内存。

**默认实例**：`gaworld.skills.registry.get_default_registry()` 在进程里只创建一次；测试可以传自己的 registry。

---

## 4. 经验 → Skill 提炼

`summarize_experience_to_skill(agent, *, llm, registry=None, today=None, lookback_days=None, min_episodes=4)` 的流程：

1. 用 `gaworld.memory.consolidation.fetch_recent_episodes` 拿最近 episodes（与 memory consolidation 共用同一个 fetcher，避免重复实现）。
2. 不足 `min_episodes` 直接返回 `None`。
3. 构造 prompt，让 LLM 输出形如 `{"name", "description", "triggers", "body"}` 的 JSON；如果 LLM 判断没有可复用模式，应输出 `{"skip": true}`。
4. 解析 / 校验：必须有 `name` 和 `body`；triggers 限制 ≤ 4；body ≤ 1200 字。
5. 用 `registry.save_private` 写盘；返回保存后的 `Skill`。

**幂等**：同名 skill（slugify 后 id 相同）会**覆盖**写入。也就是说同一个 agent 在不同时间多次提炼出"海报三栏法"会得到同一个文件，body 越改越准。

**触发方式**：
- `run_skill_consolidation(agent, llm=..., today=...)`：薄包装，按 config 的 `enabled` / `every_days` 决定是否真跑。`run_daily_memory_lifecycle` 已经在调它。
- `summarize_experience_to_skill(...)`：跳过配置守门，强制跑，给实验脚本/CLI 用。

---

## 5. 配置项

`gaworld/settings/runtime.py`：

```python
"memory": {
    ...
    "skill_consolidation": {
        "enabled": False,        # 默认 OFF，不影响现有仿真
        "every_days": 5,         # 每 5 个 sim-day 跑一次
        "lookback_days": 5,      # 看最近 5 天的 episodes
        "min_episodes": 4,       # 不足 4 条不提炼
    },
},
"skills": {
    "global_dir": "data/skills",
    "inject_into_cognition": True,    # perception 提示词是否附 skill 列表
    "inject_into_work_brief": True,   # work brief 是否附【可用技能】块
    "max_per_prompt": 4,              # cognition 注入上限
},
```

打开方式：

```python
# 1. 改默认（永久）：直接编辑 runtime.py
# 2. 运行时（实验脚本）：
from gaworld.settings import CONFIG
CONFIG["memory"]["skill_consolidation"]["enabled"] = True
# 3. 通过 overrides.py 的 GAWORLD_CONFIG_OVERRIDES 等机制
```

---

## 6. 接入点细节

### 6.1 Cognition

`perception(agent, ...)` 在拼提示词时调 `_agent_skill_block(agent)`，得到形如：

```
你已经掌握的小技能：
- 海报网格排版：用三栏网格 + 单一主色，快速给宣传海报定排版
- 结构化代码评审：给一段 Python 代码做三段式评审
```

若没有 skill 或开关 OFF，返回空串，提示词无变化。这是**唯一保证向后兼容**的关键：所有注入都先走开关 + 优雅降级。

### 6.2 Work Router

`RealWorkRouter.__init__` 多了一个 `skill_registry: Optional[SkillRegistry]` 参数（不传则从 `get_default_registry()` 兜底）。

dispatch 时用 `relevant_skills_for_text(all_skills, action_text, limit=3)` 选 ≤3 个相关 skill，传给 `_build_brief_text`，brief 末尾追加：

```
【可用技能】
- 海报网格排版：用三栏网格 + 单一主色，快速给宣传海报定排版
  · 1. 先选一个主色（占面积 ≥ 60%）...
```

adapter（如 `CodeAdapter`）原本就把 `brief.brief_text` 整段拼进 LLM prompt——所以**不需要改任何 adapter 代码**，skill 内容会自动出现在工作的指导上下文里。

---

## 7. 怎么用

### 7.1 加一个全局技能给所有人备选

在 `data/skills/` 下新建 `your-skill.md`，按 §2 的格式写。重启仿真（或调 `registry.reload()`）即可被发现。

### 7.2 挂载到某个 agent

```python
from gaworld.skills import SkillRegistry

reg = SkillRegistry()
reg.attach_to_agent(agent, "your-skill")     # agent 是 dict 或 Agent
```

或者在初始化 agent 时直接写 `agent["skill_ids"] = ["a", "b"]`。

### 7.3 手动给 agent 灌一个私有技能

```python
from gaworld.skills import Skill, SkillRegistry

SkillRegistry().save_private(agent_id=31, skill=Skill(
    skill_id="",                  # 留空让 registry 用 name slugify
    name="深夜灵感记录",
    description="记下深夜冒出的设计灵感，三段式分类",
    body="...",
    triggers=["灵感", "夜里"],
))
```

私有 skill 不需要 attach，`list_for_agent` 会自动算上。

### 7.4 打开自动提炼

```python
CONFIG["memory"]["skill_consolidation"]["enabled"] = True
```

之后每 5 个 sim-day（`every_days`）在 `run_daily_memory_lifecycle` 里自动给每个 agent 调一次。

---

## 8. 失败模式

| 现象 | 解释 / 处理 |
|---|---|
| skill 文件无法解析 | `SkillRegistry._load_dir` 单文件 try/except，warning 后跳过，其他 skill 不受影响 |
| LLM 提炼调用失败 | `summarize_experience_to_skill` 捕获并 warning，返回 `None` |
| LLM 返回 `{"skip": true}` 或非 JSON | 返回 `None`，不创建 skill |
| attach 一个不存在的 skill_id | `attach_to_agent` 返回 `False`，不写入 `agent["skill_ids"]`，避免悬挂引用 |
| 私有 / 全局同 id 冲突 | 私有优先（语义：自己学到的覆盖书本） |
| `inject_into_cognition` 关掉但全局还想用 | OK：router 走 `inject_into_work_brief`，互不影响 |

---

## 9. 测试

`tests/test_skill_system.py` 共 17 个用例，覆盖：

- Skill ↔ Markdown 往返（含中文、`triggers` 列表、缺 frontmatter 容错）
- `slugify_skill_id` 中文 + 特殊字符
- `Skill.matches` trigger 子串匹配
- Registry：global 加载、private 加载、attach/detach、同 id 优先级、save_private 跨实例可见
- 经验提炼：episodes 不足返回 None、`skip` 跳过、合法 payload 持久化、`run_skill_consolidation` 受配置守门
- 提示词渲染：截断、空列表、按 trigger 选相关 skill
- 与 RealWorkRouter 集成：调度后 `brief_text` 含 `【可用技能】`

跑法：
```bash
PYTHONPATH=. pytest tests/test_skill_system.py -v
```
