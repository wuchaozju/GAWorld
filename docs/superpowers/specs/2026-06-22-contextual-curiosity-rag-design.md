# 情境驱动的好奇/求知 → RAG 设计 (Contextual Curiosity → RAG)

- 日期: 2026-06-22
- 状态: 已批准设计，待实现计划

## 1. 背景与目标

智能体应能"在生活和工作中提出相关关键字，并通过 web 搜索把相关知识放入其 RAG"。

现有系统 (`gaworld/sim/_news.py` + `gaworld/sim/_rag.py`) 已具备大部分管线：
- 每天按 `info_schedule` 在随机时间点触发 `info_seek_and_store`（调用点 `generative_city_sim.py:3105`）。
- 已能 `web_search`（Google/Baidu/Bing fallback）并写入 RAG（`vector_db_add_entry`，类型 `info_seek`/`web_search`）。
- 但**关键字来自静态 profile 的词频**（`_extract_interest_keywords`），查询是模板化的（`{keyword} 最新消息`）。

**缺口**：关键字不是由智能体"当前正在做什么/经历什么"驱动的。本设计补齐两点（用户已确认"两者都要"）：
1. **情境驱动关键字** — 用 LLM 根据当前情境提出关键字。
2. **事件驱动触发** — 用启发式阈值门控决定是否额外触发一次求知（控成本），门控通过后才花 LLM 提词。

## 2. 输入信号（已确认四组全要）

提出关键字时参考：
- **当前活动/日程** — `scheduled_activity`、工作任务上下文。
- **近期记忆/事件** — 最近事件、环境事件 (`env_events`)、生活事件 (`life_events`)、社交互动。
- **情绪/状态** — `stress`、`econ_security`、`curiosity` 等 `state` 字段。
- **兴趣/成长目标** — `growth_profile` 中的爱好与正在发展的技能。

## 3. 触发机制（已确认：启发式阈值 + LLM 提词）

廉价启发式门控先判定是否触发；通过后才调用 LLM 提出情境关键字。避免每次决策都多一次 LLM 推理。

## 4. 架构与组件

### 4.1 新模块 `gaworld/sim/_curiosity.py`

三个单元，单一职责、可独立测试：

1. `assemble_curiosity_context(agent, *, scheduled_activity, recent_events, day, time_str) -> dict`
   - **纯函数**。把四组信号打包成紧凑 context dict。
   - 近期记忆通过现有记忆检索接口获取（与 `_external_rag_hint` 同源的 `retrieve_relevant_memories`），不引入新检索机制。

2. `should_seek_knowledge(agent, context, *, budget_left, config) -> tuple[bool, str]`
   - **启发式门控，无 LLM**。返回 `(是否触发, 触发原因)`。
   - 判定流程：先看是否有任一**硬条件**命中 —— 存在新鲜 env/life 事件、`stress >= stress_threshold`、估计好奇心 `>= curiosity_threshold`、存在显著 growth focus；任一命中后，再用单一概率 `trigger_chance_on_event` 掷骰决定是否真正触发（避免每次硬条件命中都触发，平滑频率）。
   - 复用现有 `_estimate_curiosity`。
   - 额外约束：`budget_left > 0` 且 `event_driven.enabled`。
   - 随机性沿用现有代码的 `random` 用法，便于用 seed 做确定性测试。

3. `propose_contextual_keywords(agent, context, *, config) -> list[str]`
   - **LLM 调用**，仅在门控通过后执行。
   - 输出 1–`contextual_max_keywords` 个情境查询词。
   - 通过 `_llm_providers.call_llm` 调用（与现有测试 mock 模式一致，模块属性派发）。
   - JSON 解析；空/非法/失败 → 回退到现有 `_build_search_query`。

### 4.2 修改 `gaworld/sim/_news.py`

- `_choose_info_target(..., keywords=None)` 与 `info_seek_and_store(..., keywords=None)` 增加可选参数。
- 当传入 `keywords` 时：用其构建查询并优先走 `web_search`。
- 不传时：行为完全不变（向后兼容）。

### 4.3 修改 `generative_city_sim.py` 主循环

- 保留现有 `info_schedule` 调度路径。当 `contextual_keywords` 开启时，调度触发的 seek 也把查询经由 `propose_contextual_keywords` 生成。
- 新增 per-agent 每日 `curiosity_budget`（来自 `max_extra_seeks_per_day`）。
- 每个 tick：`assemble_curiosity_context` → `should_seek_knowledge` →
  若触发且 budget>0 → `propose_contextual_keywords` → `info_seek_and_store(..., keywords=...)` →
  budget 递减、写日志、写 RAG。

## 5. 数据流

```
tick
 └─ assemble_curiosity_context(活动 / 近期记忆 / state / growth_focus)
     └─ should_seek_knowledge  (启发式门控 + 预算)
         └─[通过]─ propose_contextual_keywords  (LLM)
             └─ info_seek_and_store(keywords=...)  (复用现有 web_search)
                 └─ vector_db_add_entry / save_agent_memory  (类型 info_seek / web_search)
                     └─ RAG（由常规记忆检索召回，受 decay/consolidation 覆盖）
```

## 6. 存储与召回

- 复用现有 `save_agent_memory` + `vector_db_add_entry`，类型 `info_seek`/`web_search`。
- 这些类型已被 `gaworld/memory/decay.py` 与 `consolidation.py` 纳入 episodic 处理，并由常规 `retrieve_relevant_memories` 召回进规划 prompt。
- 条目附带触发原因 + 关键字，便于追溯。

## 7. 配置

`gaworld/settings/behavior.py` 中 `behavior.info_seek` 新增键（默认开启，但完全受配置门控）：

```python
"contextual_keywords": True,        # 用 LLM 提词器生成查询
"contextual_max_keywords": 3,
"event_driven": {
    "enabled": True,
    "max_extra_seeks_per_day": 2,
    "stress_threshold": 0.6,
    "curiosity_threshold": 0.6,
    "trigger_chance_on_event": 0.5,
},
```

关闭这些键后，系统回到现有行为，**现有运行与测试不受影响**。

## 8. 错误处理

- LLM 提词失败/空/非 JSON → 回退现有 `_build_search_query`。
- Web 搜索失败 → 沿用现有不崩溃路径（`http_guard` + 超时，返回 None 并记录日志）。
- 预算耗尽 → 静默跳过。

## 9. 测试

遵循现有 `tests/` 目录与 `patch.object(module, attr, ...)` 约定：

- **单元**：
  - `assemble_curiosity_context` 纯函数断言。
  - `should_seek_knowledge` 在固定信号 + 固定 random seed 下确定性触发/不触发；预算耗尽时不触发。
  - `propose_contextual_keywords`：mock `_llm_providers.call_llm` 返回合法 JSON；返回 garbage → 回退到 `_build_search_query`。
- **集成**：
  - 一个 tick 内出现新鲜 `life_event` → 触发一次额外 info-seek → 写出一条 RAG 条目（mock `web_search` + `call_llm`）。

## 10. 范围边界（YAGNI）

- 不引入新的检索/向量机制，复用现有记忆与 RAG 接口。
- 不做 LLM-in-the-loop 的每步好奇判定（已在 Q3 否决）。
- 不改动 bootstrap 初始化 RAG 的逻辑（`_rag.py` 的 bootstrap 路径保持原样）。
