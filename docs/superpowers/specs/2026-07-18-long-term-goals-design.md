# 长期规划驱动的日常生活设计 (Goal-Driven Daily Life)

- 日期: 2026-07-18
- 状态: 已批准设计，待实现计划

## 1. 背景与目标

智能体目前的"长期性"来自兴趣/技能成长画像（`growth_profile`）、习惯、关系与记忆整合，但**没有显式的目标层级**：日初的 `build_daily_intentions` 只看当前状态与近期经历，日程生成（`generate_daily_routine`）没有"我在为什么努力"的方向感。记忆显著性公式中的 `goal_relevance`（权重 0.20，`gaworld/cognition/realism.py:78`）也只是硬编码的 0.2/0.8（`generative_city_sim.py:3509`）。

本设计新增**三层目标体系**并让它驱动每日意图与日程：

- **人生目标（life goals）**：1-2 个，方向性、极少变动（如"在杭州安家、给家人稳定生活"）。
- **长期目标（long-term goals）**：1-3 个，数月尺度，有进度（如"两年内攒够首付"）。
- **短期目标（short-term goals）**：2-4 个，1-2 周尺度，直接影响日常安排（如"这两周完成基金调仓"）。

已确认的关键决策：

1. **目标来源**：混合 —— LLM 从 profile 自动引导生成 + 持久化 JSON 可编辑（dashboard 或直接改文件）。
2. **更新节奏**：日轻量（搭 `consolidate_day` 便车，0 新增每日 LLM 调用）+ 周回顾（每 7 天 1 次专门 LLM 调用）+ 重大生活事件触发即时回顾。
3. **接入范围**：每日意图 + 今日日程（核心）、记忆显著性 `goal_relevance` 真实化、dashboard 查看/编辑、访谈/日记反映目标。
4. **架构**：微内核插件（方案 A），完全仿照 `InterestsPlugin` 的成熟模式。

## 2. 数据模型与持久化

每 agent 一个文件 `output/memory/agent_{id}_goals.json`（与 `agent_{id}_intentions.json` 同目录同模式）：

```json
{
  "life_goals": [
    {"id": "lg1", "title": "在杭州安家、给家人稳定生活", "domain": "family",
     "description": "……", "status": "active"}
  ],
  "long_term_goals": [
    {"id": "ltg1", "parent": "lg1", "title": "两年内攒够首付",
     "horizon_days": 700, "progress": 0.15, "status": "active",
     "created_day": 1, "updated_day": 8}
  ],
  "short_term_goals": [
    {"id": "stg1", "parent": "ltg1", "title": "这两周调整支出、完成基金调仓",
     "target_day": 14, "progress": 0.4, "status": "active",
     "created_day": 1, "recent_note": "已比较了两只基金"}
  ],
  "last_review_day": 7,
  "needs_review": false,
  "review_log": [
    {"day": 7, "type": "weekly", "summary": "……", "changes": ["完成 stg1", "新增 stg2"]}
  ]
}
```

- `domain` 取值：`career | family | health | wealth | social | self`。
- `status` 状态机：`active → completed | abandoned | paused`（`paused` 可回 `active`）。
- 数量约束（超出截断）：life 1-2、long-term 1-3、short-term 2-4，上限可配。
- `review_log` 只保留最近 N 条（默认 12），防无限膨胀。

## 3. 生命周期（四段）

### 3.1 引导生成（`agents.built` 钩子）

- 每 agent 一次性 1 个 LLM 调用（`task="goals_bootstrap"`）：输入 profile（姓名/年龄/职业/性格/日常/价值观）+ 当前 state，输出三层目标 JSON。
- stateful 模式下若 `agent_{id}_goals.json` 已存在则**直接加载、跳过 LLM**——这就是"可编辑"的入口：用户改了文件，下次运行生效。
- LLM 失败或解析失败 → 启发式兜底（仿 `_fallback_intentions`）：按职业类别（上班族/学生/退休/自由职业）、年龄段与 `econ_security` 生成通用三层目标。
- goals 文件损坏（JSON 解析失败）→ 重新引导并记 warning。

### 3.2 日轻量进度（0 新增 LLM 调用）

- 扩展 `consolidate_day`（`gaworld/cognition/realism.py`）：
  - 新增可选参数 `goals_context`（`format_goals_context` 的输出；goals 禁用时传 `"无"`，prompt 不变）。
  - prompt 注入当前目标块，要求输出 JSON 增加字段
    `"goal_progress": [{"id": "stg1", "progress": 0.5, "note": "今天做了……"}]`。
  - 返回 dict 增加 `goal_progress` 键；解析失败返回空列表，不影响 memory_text / intentions 原有路径。
- 主循环在 `consolidate_day` 调用点之后内联调用 `goals.apply_goal_progress(agent, goal_progress, day)`：
  - 只允许更新 `short_term_goals` 与 `long_term_goals` 的 `progress`（clamp 0-1，且单日增幅上限默认 0.34，防 LLM 一步拉满）与 `recent_note`/`updated_day`。
  - `progress >= 1.0` 的短期目标自动置 `completed`（长期目标的完成判定留给周回顾，更稳）。
  - stateful 时保存文件。

### 3.3 周回顾（每 `review_interval_days` 天，每 agent 1 个 LLM 调用）

- 触发条件：`day - last_review_day >= review_interval_days`（默认 7），在 `GoalsPlugin.on_day_end` 中执行。
- 输入：目标全量 + 本周（自上次回顾以来）高显著性 episode 摘要 + 当前 state + growth_profile 焦点。
- 输出 JSON（`task="goals_review"`）：
  - `short_term_goals`：逐条给出 `keep | complete | adjust | abandon`，可 `new` 新增（补足到 2-4 个）；
  - `long_term_goals`：进度修订，完成/放弃判定，完成或放弃后可 `new` 新增（保持 1-3 个）；
  - `summary`：一段中文回顾小结。
- 应用规则：人生目标层在周回顾中**只读**；新增目标必须挂到已有上层目标（`parent` 无效则挂到第一个 active 上层目标）。
- `summary` 同时写入 `review_log` 和一条"周反思"记忆记录（`_append_memory_record` 同款入口），使回顾能被记忆检索命中、反哺后续意图。
- LLM 预算：沿用 HUMAN_REALISM 的 per-agent llm_budget 机制；预算不足则顺延到下一天（`last_review_day` 不更新）。

### 3.4 事件触发回顾

- 当日出现 routine-impacting 生活事件且 severity ≥ `event_review_severity`（默认 0.7）时，置 `needs_review = true`。
- 当晚 `on_day_end` 优先执行一次回顾（`type="event"`，prompt 额外注入触发事件描述），执行后清除标记并更新 `last_review_day`。
- **只有事件回顾允许变动人生目标层**（如"失业后重新思考职业方向"），且单次最多变动 1 条。

## 4. 每日驱动与读侧接入（4 点）

核心原则：目标是**上下文倾向而非命令**——日程自然服务于短期目标（每天推进 0-2 个即可），受状态/事件/星期约束时目标推进让位。

1. **每日意图** `build_daily_intentions`：prompt 注入 `format_goals_context(agent)`（短期为主 + 长期背景 + 人生目标一句话），要求 priorities 自然体现 0-2 项短期目标相关事项。输出结构不变。
2. **今日日程** `generate_daily_routine`：prompt 增加"当前目标"块与一条规则（与现有规则 7-11 同级，不覆盖状态/事件让位逻辑）。
3. **`goal_relevance` 真实化**：`goals.match_goal_relevance(goals, episode_text) -> float`——目标标题/关键词与当步 activity+action+reflection 的轻量文本匹配（无 LLM，仿 `match_growth_items`），返回 `relevance_floor`(0.2) ~ `relevance_cap`(0.9)，替换 `generative_city_sim.py:3509` 硬编码。形成"目标 → 行为 → 记忆 → 意图"闭环。
4. **日记与访谈**：`generate_daily_diary` 与 `interview_agent` 的 prompt 注入目标上下文（日记自然流露进度心情；访谈能回答"你最近在为什么努力"）。

所有注入点在 `CONFIG["goals"]["enabled"] = false` 时返回 `"无"`，行为与现状完全一致。

## 5. 架构与组件

### 5.1 新模块 `gaworld/goals.py`

单一职责单元（均可独立测试）：

- `load_agent_goals(agent_id, memory_dir)` / `save_agent_goals(agent_id, goals, memory_dir)`
- `bootstrap_goals(agents, *, llm, memory_dir, stateful, config)` — 含启发式兜底 `_fallback_goals(agent)`
- `format_goals_context(goals, *, max_items) -> str` — 各 prompt 共用的目标上下文格式化
- `apply_goal_progress(goals, goal_progress, day, *, config) -> goals` — 纯函数，日终进度应用
- `run_goal_review(agent, *, llm, day, episodes, trigger, config) -> (goals, summary)` — 周/事件回顾（LLM）与结果应用
- `match_goal_relevance(goals, episode_text, *, config) -> float`
- `parse_goals_json(text)` — 引导/回顾共用的宽容解析（`_extract_json_block` 同款）

### 5.2 新插件 `gaworld/goals_plugin.py`

仿 `interests_plugin.py`：

- `id = "goals"`，`setup` 读 `ctx.config["goals"]`；
- `agents.built`（observe）→ bootstrap；
- `on_day_end`（observe，priority=15，晚于 interests 的 10）→ 事件回顾 / 周回顾判定与执行、stateful 保存。
- 注册进 `builtin_plugins`。

### 5.3 过渡耦合（与 interests 相同的取舍，注释注明）

- goals 存放在 `agent["goals"]`（不进 `agent["ext"]`），因为读侧消费者（意图/日程/日记/访谈 prompt、salience）仍为内联代码。
- 日终 `apply_goal_progress` 的调用点内联在主循环 `consolidate_day` 之后（`generative_city_sim.py:4176` 附近），避免钩子时序问题；周/事件回顾走插件 `on_day_end`。

### 5.4 Dashboard

- `dashboard_server.py`：
  - `GET /api/agents/{id}/goals` — 读 goals JSON；同时并入现有 `/detail` 响应（与 intentions 并列）。
  - `POST /api/agents/{id}/goals` — 整体写回，基本校验（三层数组存在、status 合法、数量截断）。
- `site/dashboard/`（app.js + index.html + locales）：agent 详情新增"目标"面板——三层分组展示，长期/短期带进度条与状态徽标，显示最近一次 `review_log` 小结；"编辑"打开 JSON 文本域整体保存（不做逐字段表单）。

## 6. 配置（`gaworld/config.py` 新增）

```python
"goals": {
    "enabled": True,
    "review_interval_days": 7,
    "event_review_severity": 0.7,
    "max_life_goals": 2,
    "max_long_term": 3,
    "max_short_term": 4,
    "max_daily_progress_delta": 0.34,
    "review_log_keep": 12,
    "relevance_floor": 0.2,
    "relevance_cap": 0.9,
}
```

LLM 成本：引导 = 每 agent 一次性 1 次；周回顾 ≈ 每 agent 每 7 天 1 次（50 agent 摊销 ≈ 7 次/天）；日轻量 = 0 新增。

## 7. 错误处理

- 所有 LLM 输出解析失败 → goals 保持不变 + warning 日志（`get_logger("gaworld.goals")`）。
- goals 文件缺失 → 引导；损坏 → 重新引导 + warning。
- `goal_progress` 中未知 id / 非法数值 → 逐条跳过，不整批失败。
- 周回顾预算不足 → 顺延，不阻塞日终流程。

## 8. 测试计划

复用现有 mock LLM fixture（`tests/test_mock_llm_fixture.py` 模式）：

- `tests/test_goals_module.py`：
  - 引导兜底：LLM 失败 → 启发式目标结构合法；
  - `apply_goal_progress`：clamp、单日增幅上限、短期目标自动 completed、未知 id 跳过；
  - `run_goal_review`：keep/complete/adjust/abandon/new 各路径、人生目标周回顾只读、事件回顾可动人生目标且限 1 条；
  - `match_goal_relevance`：无关 → floor、强相关 → cap、goals 为空 → floor；
  - 数量约束截断与 `review_log_keep`。
- `tests/test_goals_plugin.py`：
  - 钩子注册与 disabled 行为（agent 无 goals、注入点返回"无"）；
  - stateful 下已有文件跳过引导；
  - `needs_review` 事件触发当晚回顾并清除标记；
  - 周回顾间隔判定与预算顺延。
- 仿 `test_interest_daily_routine_prompt.py`：日程 prompt 与意图 prompt 包含目标上下文；disabled 时不包含。

## 9. 明确不做（YAGNI）

- 不做目标间依赖图/冲突消解（parent 挂载已够）。
- 不做逐字段编辑表单（JSON 文本域够用）。
- 不做每日独立目标评估 LLM 调用（已确认成本不值）。
- 不做跨 agent 目标传染（interests 的社交演化已覆盖类似机制，后续如需再议）。
