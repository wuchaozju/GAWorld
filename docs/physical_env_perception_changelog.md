# 物理环境感知与反应能力增强 —— 变更说明（P0–P4 + 持久化）

> 配套现状分析见 `docs/physical_env_perception_analysis.md`。本文记录依其差距清单实现的 P0–P4，以及 P4 的跨运行持久化。
> 设计原则：**全部配置门控、向后兼容、纯规则（无新增 LLM 调用）**；新代码只进 `gaworld/` 包，主循环改动最小化。

---

## 一、总览

| 阶段 | 能力 | 核心新增/改动 |
|---|---|---|
| P0 | 局部物理感知层接线 | 新增 `gaworld/world/local_physical.py`；主循环每 tick 更新占用+营业时间，感知前注入"身边物理环境" |
| P1 | 反应消费结构化信号 | `behavior/dynamic.py`：分类结构化优先 + 消费 `impact_tags` + 局部物理中断 |
| P2 | 异常一等公民 | `env/system.py` 给事件打 `anomaly`/`anomaly_score`；`dynamic.py` 升级反应；局部"人流骤增"涌现异常 |
| P3 | 当日重规划入口 | `sim/_schedule.py` 新增 `replan_affected_interval`；主循环在持续性异常时只重排受影响区间 |
| P4 | 结构化长期学习 | 新增 `gaworld/memory/spatial_preferences.py`：地点规避偏好；`experience.py` 增持久化 |

改动规模：`gaworld/` + 主文件共 5 个既有文件改动（+443/−36 行），新增 2 个模块、6 个测试文件。

---

## 二、各阶段做了什么

### P0 — 接通局部物理感知层

城市地图里早已定义但从未被调用的 `occupancy` / `is_open` 现在真正生效：

- `update_occupancy_from_agents(city_map, agents)`：每 tick 从"谁在哪"重算节点占用并写回地图运行时（同时保存上一 tick 占用，供 P2 检测激增）。
- `set_sim_time(city_map, time_str)`：每 tick 写入仿真时间，使 `is_open` 生效。
- `local_physical_state(...)`：每个 agent 感知前生成当前位置快照（拥挤度 / 是否营业 / 当地天气 / 异常标记），存到 `agent["_local_physical"]` 供后续阶段读取。
- `physical_state_text(...)`：把快照渲染为中文片段注入 perception 上下文（"身边的物理环境：…"）。

### P1 — 反应消费结构化信号

`behavior/dynamic.py`：

- `_classify_event_type` 改为**结构化优先**：先看 `type/topic/impact_tags`，关键词兜底；**应急检测提到最前**（修复"`natural` 型地震被误判为天气"的排序 bug）；经济/政治/技术事件按严重度路由到 `news/breaking|local`（此前一律落兜底）。
- `impact_tags` 现在加成中断优先级（`mobility/stress/public_service/...`），不再被丢弃。
- 新增 `generate_local_physical_interrupts`：把局部物理状态转为中断候选——拥挤→"避开人群换个地方"；关门→"改去其他开门的地方"（不可恢复，必须换地点）。已接入 `evaluate_step_dynamics`，无数据时自动空转（自门控）。

### P2 — 异常作为一等公民

- `env/system.py` 新增 `_annotate_anomaly`：对 day + tick 的每个事件打 `anomaly`（布尔）与 `anomaly_score`。判定为"相对常态的偏离"代理：日常天气/小波动不算；极端/突发/应急/高严重度才算。
- `dynamic.py` 升级异常反应：`anomaly` 事件加优先级；`anomaly_score` 高于阈值时强制**不可恢复**；mood 影响更强。
- 局部涌现异常：当某地"人流骤增"（占用率高且较上一 tick 跳变大）→ 快照打 `anomaly=crowd_surge` → 升级为 `crowd_anomaly` 中断（"尽快离开拥挤区域"，不可恢复）。

### P3 — 当日日程重规划入口

- `sim/_schedule.py` 新增纯函数 `replan_affected_interval(schedule, start, end, *, is_affected, relocate=None, defer=True, ...)`：**只重排受影响的连续区间**（改址 / 顺延 / 丢弃），窗口外不动；返回 `(新日程, 变更记录)`。
- 主循环触发：当胜出的中断是**持续性异常**（不可恢复的物理/应急反应）时，把被打断活动在窗口内的后续时段顺延到窗口之后，并写日志。区别于此前只能改单个时间格。

### P4 — 结构化长期学习 + 持久化

- 新增 `gaworld/memory/spatial_preferences.py`：
  - `record_anomaly_experience`：仅对**地点绑定**的异常（拥挤/关门，不含全城宏观异常，避免错误归因）累积该地点的规避分，按时段加权。
  - `location_aversion` / `decay_preferences`（按天半衰期衰减 + 剪枝）/ `redirect_for_aversion`（规避分超阈值时，改去同类、规避更低的替代地点）。
- 反馈接入：`resolve_location` 之后用 `redirect_for_aversion` 偏置；异常发生时记录、每日开始衰减。
- **持久化**（本次新增）：`memory/experience.py` 增 `load/save_agent_env_preferences`，落盘到 `output/memory/agent_<id>_env_preferences.json`。启动加载、记录异常后保存、每日衰减后保存，跨运行保留学习结果（仅在 `STATEFUL` 下）。

---

## 三、配置项清单与开关

全部位于 `gaworld/settings/environment.py`，可在运行配置/覆盖文件中调整。

### `local_physical`（P0，及 P2 涌现异常阈值）

| 键 | 默认 | 含义 |
|---|---|---|
| `enabled` | `True` | **总开关**：关闭后不更新占用、不生成局部快照、局部物理中断自动空转 |
| `crowd_busy_ratio` | `0.6` | 占用率达到即标记"比较拥挤" |
| `crowd_packed_ratio` | `0.9` | 占用率达到即标记"非常拥挤" |
| `inject_into_perception` | `True` | 是否把局部快照文本注入感知（关掉则数据仍计算但不进提示） |
| `crowd_anomaly_ratio` | `0.9` | 涌现"人流骤增"异常的占用率门槛 |
| `crowd_anomaly_jump` | `0.25` | 较上一 tick 的占用率跳变门槛（与上一条同时满足才算异常） |

### `anomaly`（P2 检测）

| 键 | 默认 | 含义 |
|---|---|---|
| `enabled` | `True` | **总开关**：关闭后所有事件 `anomaly=False` |
| `severity_threshold` | `0.65` | 严重度达到即判为异常；同时作为 `anomaly_score` 归一基准 |
| `intraday_threshold` | `0.45` | 日内突发（intraday）类事件判异常的较低门槛 |

> 反应侧的升级幅度（优先级加成、不可恢复分数）是 `behavior/dynamic.py` 里的固定常量（该模块刻意与 CONFIG 解耦）：`_ANOMALY_PRIORITY_BOOST=0.15`、`_ANOMALY_NON_RESUMABLE_SCORE=0.8`、`_IMPACT_TAG_PRIORITY_BOOST`（mobility 0.06 等）。如需调参在该文件改常量。

### `replan`（P3）

| 键 | 默认 | 含义 |
|---|---|---|
| `enabled` | `True` | **总开关**：关闭后只保留单步改程，不做区间重排 |
| `window_minutes` | `120` | 假定异常持续、需重排的向前窗口长度 |
| `defer_gap_minutes` | `30` | 顺延活动重新落位时的时间间隔 |

### `spatial_preferences`（P4）

| 键 | 默认 | 含义 |
|---|---|---|
| `enabled` | `True` | **总开关**：关闭后不学习、不持久化、不做规避改址 |
| `anomaly_weight` | `1.0` | 每次地点异常累加的规避分 |
| `avoid_threshold` | `1.5` | 规避分达到即触发改址 |
| `half_life_days` | `7.0` | 规避分按天衰减的半衰期 |

### 一键回退

把任一阶段的 `enabled` 设为 `False` 即可关闭该层，行为退回改动前；四个开关相互独立。P4 持久化额外依赖既有的顶层 `stateful` 开关——仅在 `stateful=True` 时落盘。

---

## 四、改动文件清单

新增模块：`gaworld/world/local_physical.py`、`gaworld/memory/spatial_preferences.py`。

改动文件：`gaworld/settings/environment.py`（4 个配置块）、`gaworld/behavior/dynamic.py`（P1/P2）、`gaworld/env/system.py`（P2 标注）、`gaworld/sim/_schedule.py`（P3）、`gaworld/memory/experience.py`（P4 持久化）、`generative_city_sim.py`（各阶段接线）。

新增测试：`tests/test_local_physical.py`、`test_env_structured_signals.py`、`test_anomaly_modeling.py`、`test_replan_interval.py`、`test_spatial_preferences.py`、`test_env_preferences_persistence.py`。

---

## 五、向后兼容与验证

兼容性：所有新行为默认开启但**纯增量**——无局部数据时局部中断空转、无异常时不升级、无规避分时不改址，原有路径保持不变；未触及既有内存/经济/社交等模块。

测试：新增 + 受影响模块合计 **151 passed**；ruff 对全部新文件通过，主文件 F821（未定义名）零报错；新增代码未给改动文件引入新的 lint 报错。

已知环境限制（非本次改动引入）：完整 `pytest` 套件在本机 Python 3.10 下有 15 个收集错误（`apps/visualizer.py` 用了 `datetime.UTC`，需 ≥3.11）与 2 个既有失败（`test_memory_consolidation_decay` 与 `runtime.py` 默认值漂移）。建议在 **Python 3.11+** 环境跑一遍完整 `pytest tests` 终验。
