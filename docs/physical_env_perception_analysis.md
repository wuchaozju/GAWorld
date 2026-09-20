# 增强智能体物理环境感知与反应能力 —— 现状分析与差距清单

> 目标：让智能体能感知物理环境（含变化与异常），并据此触发反应——即时改动作、当日重规划、记忆/长期计划更新。
> 本文只做**现状梳理 + 差距定位 + 建议方向**，不含实现改动。所有论断均附 `文件:行号/函数` 引用，便于核对。

---

## 一、摘要

GAWorld 已经有一条完整的"环境 → 感知 → 计划 → 动作 → 反思/记忆"主循环，宏观环境层（天气/经济/政策/技术）和**即时动作反应**层都相对成熟。但围绕你提出的"**物理环境**感知"，存在三处结构性缺口：

1. **没有局部物理感知**。城市地图里其实已经写好了占用度、道路拥堵、营业时间等物理状态原语，但它们在主循环中**从未被写入或查询**，等于死代码。所有智能体共享同一份**全局**环境文本，室内的人和暴雨里的人感知到的东西完全一样。
2. **"异常"没有被单独建模**。系统只有 `severity`（严重度）这一个连续信号，没有"相对基线的异常检测"，也没有把 `EnvironmentSystem` 产出的 `impact_tags` 真正喂给反应管线（反应管线靠关键词重新猜类别）。
3. **三层反应深度不均衡**：即时动作反应很完整；当日日程重规划几乎缺失（只能改单个时间格）；记忆/长期影响是间接的（靠 salience 间接影响第二天意图），缺少结构化的空间/因果学习。

下面分层展开。

---

## 二、现有端到端闭环（已经能跑的部分）

主循环在 `generative_city_sim.py::run_simulation`（约 `2510`），每天、每个时间步的环境相关流程如下：

**日级（每天开始）**

- `env_system.start_day(day, ...)`（`2818`）生成当日宏观事件，写入 `env_timeline` 与每个 agent 的日志/向量库（`2830-2843`）。
- `EnvironmentSystem.start_day`（`gaworld/env/system.py:533`）可走 LLM 生成器或规则生成器，覆盖 natural / economic / political / technology 四域，产出 `day_events`（含 `severity`、`impact_tags`）与 `intraday_rules`。

**步级（每个时间步，默认 10–30 分钟）**

1. `env_system.tick(day, time_str)`（`2978`）→ `get_events()` / `get_context_text()`（`2979-2980`）得到本步事件与文本。
2. `agent_env_events = 全局 env_events + 该 agent 的 life_events`（`3085`）。
3. `perception(...)`（`3170`，实现于 `gaworld/sim/_cognition.py:132`）：把 `social_context + env_context + policy` 拼进 LLM 提示，输出 1–2 句感知。
4. 动态行为系统 `dynamic_transient_thought` → `evaluate_step_dynamics`（`gaworld/behavior/dynamic.py`）：环境事件 → 中断候选 → 打分挑选。
5. `planning(...)`（`3232`）：输出 goal/constraint/urge/plan/expected_outcome 的**微计划**（非整日日程）。
6. `maybe_adjust_activity(...)`（`3234`，实现于 `1974`）：LLM 决定是否临时改当前时段活动。
7. 若改变：`apply_schedule_override(schedule, time_str, activity)`（`3284`）覆盖**单个时间格**；动态系统也可 `dynamic_insert_activity` 插入一个可恢复活动（`3262`）。
8. `move_agent`（`3294`）解析地点并移动；随后形成 episode（`3545`），`env_events` 进入 episode 并通过 `event_intensity` 影响 `salience`（`3508-3529`）。

闭环本身是健全的：环境进得来，能改当前动作，也能落进记忆。问题在于**感知的颗粒度**和**反应的深度**。

---

## 三、三层感知现状与缺口

### 3.1 局部物理感知层（最大缺口）

**已有但未启用的原语**——`gaworld/world/city_map.py` 里其实已经定义了完整的局部物理状态接口：

- 节点占用/拥挤：`set_node_occupancy` / `add_node_occupancy` / `get_node_occupancy`（`1578-1590`），`occupancy_ratio`（`1594`，按 capacity 归一）。
- 道路拥堵：`set_edge_congestion` / `get_edge_congestion` / `clear_congestion`（`1565-1574`），`_route_congestion`（`1095`）。
- 营业时间：`is_open(city_map, node_id, time_str)`（`1607`）。

**问题：这些几乎都是死代码。** 全仓检索（`gaworld/` + 主文件）显示：

- `set_node_occupancy` / `add_node_occupancy` / `set_edge_congestion` / `clear_congestion` / `is_open` **没有任何调用点**。
- 因此 `get_node_occupancy` 恒为 0、`occupancy_ratio` 恒为 0、`get_edge_congestion` 恒返回默认 1.0。`_route_congestion` 算出来永远不堵。
- 唯一真正接入仿真的物理量是 `is_rush_hour`（`city_map.py:1279`），它只影响打车成本（`calc_transport_cost`，`1241`），不进入感知，也不触发反应。

**问题：环境是全局的，不是局部的。** `agent_env_events`（`3085`）对所有智能体是同一份全局事件 + 各自的 life_event。没有按地点本地化——一个在室内办公、一个站在暴雨街头，`perception` 看到的环境文本完全相同。

**问题：感知发生在定位之前。** `perception`（`3170`）在 `move_agent`（`3294`）之前运行，所以它**拿不到**智能体当前真实所处地点的物理状况（地点类别、是否营业、拥挤度、同处的人、局部天气）。`_memory_recall.py` 里的 `physical_env_text`（`_summarize_environment_refs`，`325`）只是对全局事件做关键词过滤，并非真实局部物理状态。

**结论**：局部物理感知层在数据结构上"半成品就绪"，但**完全没有接线**——没有人去更新占用/拥堵，也没有人在感知时读取它们。这是把"物理环境感知"做实的第一优先项。

### 3.2 宏观环境链路（较成熟，可增强）

`EnvironmentSystem`（`gaworld/env/system.py`）按四域生成事件，带 `severity` 和 `impact_tags`（如 `["mobility","stress"]`）。反应侧在 `gaworld/behavior/dynamic.py`：

- `_classify_event_type`（`705`）：**关键词匹配**把事件归为 weather/traffic/commercial/news/emergency。
- `_ENV_RESPONSE_MAP`（`642`）：每类的固定反应目录（如 storm→"就地避险"）。
- `generate_environment_interrupts`（`754`）：套 `severity` 缩放 + 人格修正（`_PERSONALITY_RESPONSE_MODIFIERS`）生成中断候选。
- `EVENT_CASCADES`（`847`）：连锁反应（暴雨→交通延误→外卖延迟）。

**缺口：**

- **`impact_tags` 被丢弃**。`EnvironmentSystem` 辛苦标了 `mobility/stress/econ_security` 等标签，但 `dynamic.py` 不读它们，而是用 `description` 关键词**重新猜**类别——一条信息源、两套解释，容易错配（例如经济/技术类事件几乎都落进 `news/local` 兜底）。
- **分类脆弱**：纯中文关键词命中，描述换个说法就归错类或走兜底。
- **反应目录是封闭小集合**：`_ENV_RESPONSE_MAP` 只有 5 类、十几条，覆盖不了泛化的物理情境。

### 3.3 异常事件建模（基本缺失）

- **"异常"没有一等公民地位**：系统只有 `severity` 连续值，没有"相对预期/基线的偏离"概念。一场常规小雨和一次罕见停电只是 severity 数值不同，没有"异常"标记，也没有针对异常的升级逻辑。
- **应急目录存在但很少被触发**：`_ENV_RESPONSE_MAP["emergency"]`（fire/earthquake/flood→撤离/避险）已定义，但默认自然事件生成器的 `extreme_events` 池是"短时强降雨预警/空气质量恶化/雷暴大风"（`system.py:_generate_natural_day_event`），**不含火灾/地震/洪水**关键词，所以应急反应在默认配置下几乎不会被 `_classify_event_type` 命中。
- **没有局部异常**：停电、电梯故障、积水、设施关闭等"局部物理异常"既没有生成源（局部层未接线），也无法被定位到具体地点。

---

## 四、三层反应深度现状与缺口

### 4.1 即时动作调整 —— ✅ 较完整

两条并行通道：LLM 的 `maybe_adjust_activity`（`1974`，按承诺等级/触发强度/人格做概率门控）+ 规则的 `evaluate_step_dynamics`（`dynamic.py`，多引擎候选 + `evaluate_interrupts` 择优）。可改当前活动、可插入可恢复活动、可施加 `mood_delta`。这一层基础好，主要是上游"喂进来的物理信号太弱"。

### 4.2 当日日程重规划 —— ⚠️ 基本缺失

`gaworld/sim/_schedule.py` 里**没有**任何"重排当日剩余日程"的函数（无 replan/regenerate/reschedule）。整日日程只在每天开始由 `generate_daily_routine`（`1505`）生成一次。日中能做的只有：

- `apply_schedule_override`（`2478`）：覆盖**单个**时间格；
- `dynamic_insert_activity`（`3262`）：插入**单个**活动并顺移后续。

缺少的是：当出现持续性异常（如"整个下午主干道封闭""目的地全天停业"）时，**重新生成当天剩余时段的日程**（换地点、改顺序、取消/补做）。现在只能一步一步局部打补丁，无法做整体重排。

### 4.3 记忆与长期计划更新 —— ⚠️ 部分（间接）

- env 事件会进 episode（`3555`）、写入向量库（`3071`，`type="external_env"`），`event_intensity` 抬高 `salience`（`3508-3529`），`infer_episode_tags` 打标签（`3530`）。
- 高 salience 的 episode 会被排序后喂给 `build_daily_intentions`（`2857-2868`），间接影响第二天意图。

**缺口**：这是**文本/显著度驱动的间接影响**，没有**结构化的空间/因果学习**。智能体不会形成"X 路线常堵→避开""Y 地点中午爆满→错峰""暴雨日改线上"这类可复用的、绑定地点/时段/条件的偏好。异常对长期行为的塑造很弱。

---

## 五、差距清单（汇总）

| 维度 | 现状 | 关键缺口 | 主要涉及位置 |
|---|---|---|---|
| 局部物理状态 | 占用/拥堵/营业接口已定义但**从不调用** | 接线：在 move/step 中更新与查询占用、拥堵、营业 | `world/city_map.py:1565-1607`（死代码）；`generative_city_sim.py:3085,3294` |
| 环境本地化 | 全局事件对所有 agent 一致 | 按地点把物理状况本地化到每个 agent | `generative_city_sim.py:3085`；`sim/_cognition.py:130` |
| 感知时序 | 感知早于定位，看不到真实周遭 | 让感知/反应能读取当前地点物理状态 | `generative_city_sim.py:3170` vs `3294` |
| impact_tags 利用 | 生成端标了标签，反应端丢弃 | 反应管线直接消费 `impact_tags`，而非关键词重猜 | `env/system.py` ↔ `behavior/dynamic.py:705,754` |
| 异常建模 | 只有 severity，无"异常"概念 | 引入相对基线的异常检测 + 升级反应 | `env/system.py`；`behavior/dynamic.py` |
| 应急触发 | 应急目录存在但默认极少命中 | 让局部异常/极端事件真正进入应急分类 | `behavior/dynamic.py:642` `_ENV_RESPONSE_MAP["emergency"]` |
| 即时动作反应 | ✅ 完整 | （上游信号增强即可受益） | `generative_city_sim.py:1974`；`behavior/dynamic.py` |
| 当日重规划 | 只能改单格/插单条 | 缺"重排剩余日程"的入口 | `sim/_schedule.py`（无 replan）；`generative_city_sim.py:2478` |
| 长期/记忆学习 | 间接（salience→次日意图） | 缺结构化空间/因果偏好学习 | `generative_city_sim.py:3508-3579,2857` |

---

## 六、建议方向与优先级

按"投入产出比 + 依赖关系"排序，从打地基到长期能力：

**P0 — 接通局部物理感知层（地基，解锁后面一切）**
把已存在的 `occupancy` / `congestion` / `is_open` 真正接线：在 `move_agent` 后更新地点占用与路段拥堵，在感知/反应前查询当前地点的拥挤度、是否营业、局部天气。这一步代价低（接口已就绪），但直接把"物理环境"从全局文本变成**可定位、可量化**的状态。

**P1 — 让反应消费结构化信号，而非关键词**
反应管线（`generate_environment_interrupts`）直接读取 `EnvironmentSystem` 的 `impact_tags` 与本地物理状态，减少 `_classify_event_type` 的关键词重猜；统一"一处生成、一处解释"。

**P2 — 异常作为一等公民**
引入轻量"异常 = 相对基线/预期的偏离"判定（如占用率突增、路段拥堵跳变、设施意外关闭、severity 超阈值），并打上 `anomaly` 标记驱动升级反应；同时让局部异常（停电/积水/故障/关闭）有生成源并绑定到具体地点，从而能命中应急路径。

**P3 — 当日日程重规划入口**
在 `sim/_schedule.py` 增加"重排当日剩余日程"的能力（输入：当前时间、持续性异常、可用地点；输出：剩余时段新日程），由持续性/高严重度异常触发，区别于现在的单格 override。

**P4 — 结构化长期学习**
把异常经历沉淀为绑定"地点/时段/条件"的可复用偏好（避堵路线、错峰、雨天改线上），反馈进 `generate_daily_routine` / `build_daily_intentions`，让长期计划真正被物理环境塑造。

---

## 七、待你确认的问题（影响后续设计）

1. **真实性 vs 复杂度**：局部物理状态希望做到多细？（仅"拥挤/营业/局部天气"三要素，还是含温度、噪音、设施明细等）
2. **异常来源**：异常主要由 `EnvironmentSystem` 主动生成，还是也允许由智能体行为**涌现**（如某地点被大量 agent 同时挤爆而自然异常）？
3. **重规划粒度**：当日重规划是"重排剩余所有时段"，还是"只重排受影响的连续区间"？
4. **性能预算**：P3/P4 是否允许额外 LLM 调用，还是要求纯规则（与 `dynamic.py` 当前"零 LLM"设计一致）？

> 注：以上引用基于当前工作区代码（`Dev` 分支，最近提交 `91aa846`）核对。
