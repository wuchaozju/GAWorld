# GAWorld API 参考

GAWorld 对外暴露三种 API 表面，覆盖从单条 CLI 命令到多服务 HTTP 集成的全部用法：

| 表面 | 适用场景 | 入口 |
| --- | --- | --- |
| **HTTP** | Dashboard / 前端 / 第三方系统接入、机器对机器集成 | `dashboard_server.py`、`twin_server.py`、`distributed_comm_server.py`、`external_environment_server.py` |
| **CLI** | 本地仿真运行、单次任务、批量实验、子进程流水线 | `python generative_city_sim.py <cmd>`、`python -m gaworld.<sub>` |
| **Python** | 把仿真内核或子系统嵌入自己的脚本 / Notebook | `import gaworld`、`from gaworld.<sub> import …` |

> 约定
> - 所有 HTTP 服务的请求/响应均为 UTF‑8 JSON；`POST` body 也用 JSON。
> - 通用错误：`{"error": "..."}`，HTTP 400/403/404/500。
> - Dashboard（端口 8766）会从请求头读取 token，但不强制；其余独立服务鉴权策略见各自章节。
> - 默认数据/产物目录：`data/`（输入）、`output/`（仿真产物）。

---

## 1. HTTP API

GAWorld 运行时会启动三类 HTTP 服务。文档给出的路径默认相对各服务的端口前缀。

### 1.1 Dashboard 服务（默认 8766）

启动：

```bash
python generative_city_sim.py dashboard --host 127.0.0.1 --port 8766
# 或仓库根目录的兼容 wrapper（旧部署脚本用）
python dashboard_server.py
```

`http://127.0.0.1:8766/` 是项目首页：`/console`、`/dashboard`、`/board`、`/m` 等入口聚合在控制台。
所有 `/api/*` 路径由 `gaworld/apps/dashboard_server.py:2398`（GET）与 `gaworld/apps/dashboard_server.py:2578`（POST）分发到 `gaworld/apps/<module>_api.py` 的 `handle_get/handle_post`。

> **机器可读描述**：`GET /api/openapi.json`（OpenAPI 3.1，源在 `gaworld/apps/openapi.py`）。目前覆盖对外的编程接口——干预、事件流、信息源、评测、经济；控制台各面板自用的路由仍以本文档为准。`tests/test_openapi.py` 会校验文档合法，并逐条请求确认每个列出的路由都真实存在。可直接导入 Swagger UI / Postman，或用 `openapi-generator` 生成客户端。

#### 1.1.1 顶层路由

| Method | 路径 | 用途 | Handler / 参考 |
| --- | --- | --- | --- |
| GET | `/api/config` | 当前生效的仿真配置摘要（合并 `config.py` + `dashboard_config.json` + 环境覆盖） | `dashboard_server._config_summary` |
| POST | `/api/config` | 部分覆盖配置并写回 `dashboard_config.json` | `dashboard_server._save_config_patch` |
| GET | `/api/agents` | 全部 agent 摘要列表（id、姓名、年龄、性别、状态概览） | `dashboard_server._agents_summary` |
| POST | `/api/agents` | 创建一个新 agent（body：profile 字段） | `dashboard_server._create_agent` |
| GET | `/api/agents/{id}/profile` | 单个 agent 的 profile markdown + 解析后的结构化字段 | `dashboard_server._agent_profile` |
| POST | `/api/agents/{id}/profile` | `body.text` 写入 profile | `dashboard_server._save_agent_profile` |
| GET | `/api/agents/{id}/state` | 九维状态（情绪/能量/社交/金钱等） | `dashboard_server._agent_state` |
| POST | `/api/agents/{id}/state` | 改写/补充九维状态 | `dashboard_server._save_agent_state` |
| GET | `/api/agents/{id}/big5` | Big Five 性格（O/C/E/A/N） | `dashboard_server._agent_big5` |
| POST | `/api/agents/{id}/big5` | 写入 Big Five，body 必含 5 个 0–1 浮点数 | `dashboard_server._save_agent_big5` |
| GET | `/api/agents/{id}/detail` | 完整合成快照（profile + state + big5 + 关系 + 财务等） | `dashboard_server._agent_detail` |
| GET | `/api/agents/{id}/memory` | 记忆列表 + 摘要 + 标签分布 | `dashboard_server._memory_payload` |
| POST | `/api/agents/{id}/memory` | 追加一条记忆（来自人工或外部系统） | `dashboard_server._append_agent_memory` |
| GET | `/api/agents/{id}/goals` | 当前目标树 | `dashboard_server._agent_goals_payload` |
| POST | `/api/agents/{id}/goals` | 改写目标树 | `dashboard_server._save_agent_goals_payload` |
| GET | `/api/agents/{id}/relationships` | （GET 走外部子模块；见 1.1.4） | `interview_api` 之外 |
| POST | `/api/agents/{id}/relationships` | 写入社会关系 | `dashboard_server._save_agent_relationships` |
| GET | `/api/agents/{id}/finance` | （GET 走外部子模块） | — |
| POST | `/api/agents/{id}/finance` | 写入经济账本 | `dashboard_server._save_agent_finance` |
| GET | `/api/skills` | 技能库（名称 + 触发词 + 版本） | `dashboard_server._skills_library` |
| GET | `/api/agents/{id}/profile\|state\|big5\|detail\|memory\|goals` 的 404 | `{"error": "Agent not found"}` 或 `Profile not found` | — |
| GET | `/api/run/status?log_offset=N` | 仿真运行状态（启动/停止/进度/最近日志偏移量） | `dashboard_server._run_status` |
| GET | `/api/run/log/export` | 把最近运行日志导出成 Markdown 文件下载 | `dashboard_server._run_log_markdown` |
| GET | `/api/trace/meta` | 最近一次 trace 的元信息（输出目录、agent 数） | `dashboard_server._latest_trace_meta` |
| GET | `/api/replay/runs` | 全部历史 run 目录，可用于 `/api/analytics/?run=<id>` | `dashboard_server._replay_runs` |
| GET | `/api/life-events` | 整城生命事件列表 | `dashboard_server._life_events_payload` |
| POST | `/api/life-events` | `body` 注入一个新生命事件 | `dashboard_server._add_life_event` |
| GET | `/api/life-events/candidates?agent_id=&limit=` | 给定 agent 的候选事件（用于"今晚让 ta 遇到什么"面板） | `dashboard_server._life_event_candidates_payload` |
| GET | `/api/todos` | 整个 todo 看板 | `dashboard_server._todo_board_payload` |
| POST | `/api/todos` | `body.items` 整体替换 todo 列表 | `dashboard_server._save_todo_board` |
| POST | `/api/todos/create` | 新建一条 todo | `dashboard_server._create_todo_item` |
| POST | `/api/todos/update` | 改 todo（完成、编辑、移动列） | `dashboard_server._update_todo_item` |
| POST | `/api/todos/clear` | 清空 todo 板 | `dashboard_server._save_todo_board([])` |
| POST | `/api/todos/create-form` | 表单版新建 todo（`application/x-www-form-urlencoded`），完成后 302 → `/board` | `dashboard_server._create_todo_item` |
| POST | `/api/fos-export` | 读取仿真产物并用 LLM 生成一份 FOS（Frame‑of‑Science）提示词；body `output_dir?`、`hint?`、`english?` | `dashboard_server._fos_export` |
| POST | `/api/relationships/friends` | 给一组 agent 建立双向好友关系（多智能体互动前置步骤） | `dashboard_server._get_collaboration_service().make_friends` |

#### 1.1.2 仿真运行控制

| Method | 路径 | 用途 |
| --- | --- | --- |
| POST | `/api/run/start` | 启动一次仿真运行，body 可含 `--sim-days / --seed / --time-unit / --fast-forward` 等同 `run` CLI 的选项；后台线程执行 |
| POST | `/api/run/stop` | 发送停止信号给后台仿真线程 |
| POST | `/api/run/schedule` | 把下一次仿真安排为定时任务，body `{cron, days, ...}` |
| POST | `/api/run/schedule/cancel` | 取消已安排的定时仿真 |

#### 1.1.3 Analytics 仪表盘

`/api/analytics/{section}`（或 `/api/analytics/{section}?run=<run_id>`）：聚合一份 run 的产物。

| Method | 路径 | Section 含义 |
| --- | --- | --- |
| GET | `/api/analytics/runs` | 列出可分析的所有 run |
| GET | `/api/analytics/overview` | 概况（agent 数、记忆/事件计数、健康度） |
| GET | `/api/analytics/state-history` | 九维状态时间序列（按 agent 维度） |
| GET | `/api/analytics/economy` | 经济账本时间序列：收入/支出/余额/储蓄/投资/债务/恩格尔系数/经济安全感 |
| GET | `/api/analytics/social` | 社交网络结构（度分布、中心性、聚类） |
| GET | `/api/analytics/behavior` | 行为习惯热力图（早/午/下午/晚/夜 × 活动） |
| GET | `/api/analytics/events` | 事件时间轴 |

参考：`gaworld/apps/dashboard_server.py:2298 _analytics_payload`。

#### 1.1.4 子模块路由（按 namespace 拆分）

以下子 namespace 在 `dashboard_server.py` 顶层分发到独立模块，路径均以 `/api/<ns>/` 起头；详细字段见各自文件。

| Namespace | 模块 | 主要路径 | 文档 |
| --- | --- | --- | --- |
| `population` | `gaworld/apps/population_api.py` | `GET /api/population/schema`、`GET /api/population/jobs/{id}`、`GET /api/population/export`、`GET /api/population/last`；`POST /api/population/preview`、`POST /api/population/generate`、`POST /api/population/group-run`、`POST /api/population/validate` | [CITY_TUTORIAL](CITY_TUTORIAL.md) |
| `import` | `gaworld/apps/import_api.py` | `GET /api/import/schema`、`GET /api/import/jobs/{id}`；`POST /api/import/preview`、`POST /api/import/run` | [BULK_IMPORT_TUTORIAL](BULK_IMPORT_TUTORIAL.md) |
| `arena` | `gaworld/apps/arena_api.py` | `GET /api/arena/tasks`、`/api/arena/agents`、`/api/arena/jobs/{id}`；`POST /api/arena/generate`、`/api/arena/run`、`/api/arena/retain`、`/api/arena/refill`、`/api/arena/state` | [ARENA_TUTORIAL](ARENA_TUTORIAL.md) |
| `games/` | `gaworld/apps/games_api.py` | 游戏场。`GET /api/games/agents?city=`、`/api/games/persuasion/sessions[/{id}]`；`POST /api/games/persuasion/start`（body `{city, agent_id, question, max_turns}` → 完整 session，含 `initial_answer`）、`/api/games/persuasion/say`（`{session_id, message}`，用完最后一轮时连带结算）、`/api/games/persuasion/settle`（`{session_id}` → 复问 + 裁判，`outcome ∈ {success, failed}`）。会话只在内存里（≤ 50 局）。**灾害模式**转发给 `gaworld/apps/disaster_api.py`：`GET /api/games/disaster/catalogue\|/api/games/disaster/runs\|/api/games/disaster/jobs/{id}`；`POST /api/games/disaster/run`（body `{city, agent_ids, disaster_id|custom, stages}` → `{job_id}`，作业跑完 `result` 是整场推演：逐人 `reactions` + 逐幕 `stats` + `summary`）。**谣言扩散局**转发给 `gaworld/apps/rumor_api.py`：`GET /api/games/rumor/catalogue\|/api/games/rumor/graph?city=&agent_ids=1,2,3`（关系图预览，**不花模型调用**）`\|/api/games/rumor/runs\|/api/games/rumor/jobs/{id}`；`POST /api/games/rumor/run`（body `{city, agent_ids, rumor_id|custom, seeds, rounds}` → `{job_id}`，作业跑完 `result` 含 `nodes` / `edges` / `transmissions`（传播树）/ 逐轮 `rounds` / `stats`（含 `superspreader`、`firewalls`）/ `summary`）。关系图按档案推导（同小区 / 同姓 / 同行 / 同学 / 同龄），每人限 6 条边。斗兽场仍在 `arena` 命名空间 | [PLAYGROUND_TUTORIAL](PLAYGROUND_TUTORIAL.md) |
| `family` | `gaworld/apps/family_api.py` | `GET /api/family/overview\|/api/family/preview?agent_id=\|/api/family/agent?agent_id=`；`POST /api/family/override` | [FAMILY_DESIGN](FAMILY_DESIGN.md) |
| `interview/`（带尾斜杠，避开单 agent 旧接口） | `gaworld/apps/interview_api.py` | `GET /api/interview/roster\|/api/interview/sessions\|/api/interview/jobs/{id}\|/api/interview/sessions/{id}[/export]`；`POST /api/interview/plan`、`/api/interview/run`、`/api/interview/delete` | [GROUP_INTERVIEW_TUTORIAL](GROUP_INTERVIEW_TUTORIAL.md) |
| `research/` | `gaworld/apps/research_api.py` | `GET /api/research/context\|/api/research/plans\|/api/research/jobs/{id}\|/api/research/plans/{id}[/export]\|/api/research/studies[/{id}]`；`POST /api/research/digest`、`/api/research/analyze`、`/api/research/extract`、`/api/research/delete`、`/api/research/studies`（可带 `design_index` 选实验设计）、`/api/research/studies/{id}`（动作：update / approve / run / pause / resume / stop / reset / delete） | [EXPERIMENTS_REPORT](EXPERIMENTS_REPORT.md) |
| `persona/` | `gaworld/apps/persona_api.py` | `GET /api/persona/list\|/api/persona/jobs/{id}\|/api/persona/detail/{slug}`；`POST /api/persona/distill`、`/api/persona/deploy`、`/api/persona/install-skill`、`/api/persona/delete` | [PERSONA_DISTILL_TUTORIAL](PERSONA_DISTILL_TUTORIAL.md) |
| `external-systems` | `gaworld/apps/external_systems_api.py` | `GET /api/external-systems/overview\|/api/external-systems/health\|/api/external-systems/interventions`；`POST /api/external-systems/config`、`/api/external-systems/interventions`、`/api/external-systems/interventions/cancel` | [EXTERNAL_SYSTEMS_TUTORIAL](EXTERNAL_SYSTEMS_TUTORIAL.md) |
| `parallel-worlds` | `gaworld/apps/parallel_worlds_api.py` | `GET /api/parallel-worlds/overview\|/api/parallel-worlds/experiments\|/api/parallel-worlds/experiment?={id}\|/api/parallel-worlds/job?id={id}`；`POST /api/parallel-worlds/preview`、`/api/parallel-worlds/start`、`/api/parallel-worlds/stop` | [PARALLEL_WORLDS_TUTORIAL](PARALLEL_WORLDS_TUTORIAL.md) |
| `settings` | `gaworld/apps/settings_api.py` | `GET /api/settings/overview`；`POST /api/settings/save`、`/api/settings/reset`、`/api/settings/reset-all`、`/api/settings/llm/provider`、`/api/settings/llm/test` | — |
| `city` | `gaworld/apps/city_api.py` | `GET /api/city/overview\|/api/city/detail?city=\|/api/city/catalogue\|/api/city/agents?city=&q=&limit=&offset=\|/api/city/agent?city=&id=\|/api/city/map?city=\|/api/city/knowledge?city=\|/api/city/news?city=`；`POST /api/city/create`、`/api/city/population`、`/api/city/agent`、`/api/city/migrate`、`/api/city/knowledge`、`/api/city/news`、`/api/city/select`、`/api/city/delete` | [CITY_TUTORIAL](CITY_TUTORIAL.md) |
| `infosources/`（只读） | `gaworld/apps/infosources_api.py` | `GET /api/infosources/sources`（注册表 + 各源缓存条数、上次抓取时间）、`/api/infosources/feed?source_id=&limit=`（缓存中的条目）、`/api/infosources/diets[?agent_id=]`（每位居民读哪些源、权重与理由）、`/api/infosources/reads?url=&source_id=&agent_id=&limit=`（`infosources.read` 记录，最新在前）。写入走干预：`POST /api/interventions/inject_info_item` | — |
| `bench/` | `gaworld/apps/bench_api.py` | `POST /api/bench/run`（body `kind: "bench"\|"rubric"` + 白名单选项，对应 `benchmark/gaworld_bench.py` / `rubric_bench.py` 的 CLI 参数：bench 支持 `track, all, synthetic, output_dir, comparisons_root, run, days, seed, seeds, resume, fast, llm_provider`；rubric 支持 `output_dir, synthetic, synthetic_mode, judges, samples_per_judge, min_days, ablate, dim`；路径必须在仓库内）→ `202` + job；同一时间只跑一个（结果文件共用），否则 `409`。`GET /api/bench/jobs[/{id}]`（状态、命令、日志尾部、**该次运行的 scorecard 快照**）、`/api/bench/scorecard`（两套最新 scorecard）、`/api/bench/reports[/{name}]`（历史报告 Markdown） | [GAWORLD_BENCH_DESIGN](../benchmark/GAWORLD_BENCH_DESIGN.md) |
| `economy/`（只读） | `gaworld/apps/economy_api.py` | `GET /api/economy/overview`（宏观状态、部门资金池、货币守恒审计、财富分布、城市日账——与 External Systems 面板同一份数据）、`/api/economy/loans`（居民间借贷图：`borrower → lender, amount`，银行负债榜，以及借贷双方账目是否对得上：`consistent` / `mismatches`）、`/api/economy/ledger?agent_id=&limit=`（单个居民的逐期账本 + 当前欠/借出）。经济干预仍走 `POST /api/external-systems/interventions`（按天排期） | — |
| `moltbook` | `gaworld/apps/moltbook_api.py` | `GET /api/moltbook/agent?id=`；`POST /api/moltbook/toggle`、`/api/moltbook/refresh` | — |
| 单 agent 旧接口 | `dashboard_server.py:2682` | `POST /api/interview`（body `{agent_id, question[, context]}`） | [TUTORIAL](TUTORIAL.md) |

#### 1.1.5 协作（discussion / cooperation）

> 路径以 `/api/collaboration/` 起头，由 `dashboard_server` 直接路由到 `CollaborationService`（见 `gaworld/collaboration/`）。

| Method | 路径 | 用途 |
| --- | --- | --- |
| GET | `/api/collaboration/sessions?kind=&status=` | 列出已有会话（`discussion` 或 `cooperation`） |
| GET | `/api/collaboration/sessions/{id}` | 单个会话详情 |
| GET | `/api/collaboration/sessions/{id}/events?after=N` | 增量事件流（轮询用） |
| POST | `/api/collaboration/sessions` | 新建：`body.kind=discussion&agent_ids=[…]&topic=…&max_rounds=6`，或 `kind=cooperation&agent_ids=[…]&task=…&leader_id=…&role_overrides={…}` |
| POST | `/api/collaboration/sessions/{id}/pause` | 暂停 |
| POST | `/api/collaboration/sessions/{id}/resume` | 继续 |
| POST | `/api/collaboration/sessions/{id}/cancel` | 取消 |

详细字段见 [GROUP_AGENT_DESIGN](GROUP_AGENT_DESIGN.md)。

#### 1.1.6 通用干预与实时事件流（kernel）

> 模块：`gaworld/apps/kernel_api.py`（HTTP）+ `gaworld/kernel/remote.py`（跨进程队列）。

仿真是 dashboard 起的**子进程**，HTTP 侧拿不到 `SimContext`，所以干预走文件队列
`output/kernel/interventions.json`：仿真启动时写入清单（pid + 内核与各插件注册的全部干预名），
**每个 tick 与每天开始**时经 `controller.intervene` 消费——与进程内调用一样被审计到
`controller.intervention` 记录表。插件新注册的干预自动出现在这里，不需要新路由。

| Method | 路径 | 用途 |
| --- | --- | --- |
| GET | `/api/interventions` | `{running, registered, pending, applied}`；`registered` 是当前运行实际可用的干预名 |
| POST | `/api/interventions/{name}` | JSON body 即该干预的 kwargs；返回 `202` + `{id, status:"pending"}`。无运行中仿真 → `409`；未注册的名字 → `404`（附 `registered`） |
| GET | `/api/interventions/{id}` | 轮询单条请求：`pending` → `applied`（带 `result`、`applied_at.day/time`）或 `failed`（带 `error`） |
| GET | `/api/events/stream?tables=a,b` | **SSE**：Recorder 各表（`output/records/<table>.jsonl`）新增的每一行推送为一条事件，`event:` 为表名；从连接时刻起推送，不回放历史；空闲 15 s 发一次 keep-alive 注释 |

当前内置干预：`set_agent_state`（`agent_id, key, value`）、`update_config`（`path, value`）、
`remove_agent`（`agent_id`，下一天开始生效）、`inject_life_event`（生命事件插件）、
`inject_info_item`（信息源插件：`source_id, title, excerpt?, url?`，把一条内容置顶到该源直到本次运行结束；
读到它的居民及其反应记入 `infosources.read`，可用 `/api/infosources/reads?url=` 追踪传播）、
`set_agent_twin_state`（孪生开启后首个 tick 才注册）。以 `GET /api/interventions` 为准。

```bash
curl -X POST localhost:8766/api/interventions/set_agent_state \
     -H 'Content-Type: application/json' -d '{"agent_id": 3, "key": "stress", "value": 0.9}'
curl -N 'localhost:8766/api/events/stream?tables=controller.intervention,traffic.tick'
```

注意：
- 生效时机是**下一个 tick**，不是请求返回时；`update_config` 对启动时已快照配置的子系统要到下次运行才生效（同 dashboard 配置覆盖）。
- 新一次运行启动时会丢弃上一次遗留的 pending 请求；仿真进程已退出（含崩溃）即视为未运行。
- 平行世界各用自己的队列（`<world_dir>/kernel/interventions.json`），此接口只作用于主运行。
- 事件流只包含写进 Recorder 的表。常用表：`agent.step`（每个 agent 每个 tick 一行：`agent_id, name, scheduled_activity, activity, action, location, target_location, changed, change_reason`；感知/计划/反思等长文本仍只在 trace 里）、`controller.intervention` / `controller.intervention_failed`、`infosources.injected` / `infosources.read`（`agent_id, name, source_id, title, url, thought`）、`traffic.tick`、`travel.*`、`family.*`。快进（月/年粒度）模式不经过逐 tick 管线，不产生 `agent.step`。

### 1.2 Twin 服务（默认 8767）— 移动端"智能体数字孪生"

启动：

```bash
python -m gaworld.apps.twin_server --host 0.0.0.0 --port 8767
# 或带发布邀请码
python -m gaworld.apps.twin_server --issue-code          # 未绑定
python -m gaworld.apps.twin_server --issue-code 31       # 绑定 agent 31
```

`http://<host>:8767/m/` 加载移动端 PWA；鉴权走"邀请码 → token → 后续 header `Authorization: Bearer …`"。

| Method | 路径 | 用途 |
| --- | --- | --- |
| POST | `/api/twin/auth` | 用邀请码换 token；body `{code}` → `{token, agent_id}` |
| GET | `/api/twin/snapshot` | 当前居民快照（位置、心情、能量等） |
| GET | `/api/twin/profile` | 个人信息卡 |
| GET | `/api/twin/trail?since_ts=…` | 最近一次上报后的活动轨迹 |
| GET | `/api/twin/agents` | 可选邻居/对象列表 |
| GET | `/api/twin/life` | 生命事件流 |
| GET | `/api/twin/reports?since_ts=…` | 历史报告流 |
| GET | `/api/twin/places?q=&limit=` | 地图兴趣点搜索 |
| POST | `/api/twin/report` | 客户端提交一次行为/事件报告 |
| POST | `/api/twin/bind` | `body.agent_id` 把当前 token 切换到指定 agent |
| POST | `/api/twin/amend` | `body.{target, op, patch?, amend_id?}`，修订历史报告 |

> 关键约定：Twin 服务必须部署在 HTTPS 之后（Cloudflare Tunnel 等），因为浏览器 Geolocation API 要求 TLS。

### 1.3 Agent Relay 服务（默认 8877）— 分布式多机通信

启动：

```bash
python generative_city_sim.py serve-distributed \
  --host 0.0.0.0 --port 8877 \
  --state-path output/distributed/relay_state.json \
  --max-messages 20000
```

参考：[OPENCLAW_INTEGRATION](OPENCLAW_INTEGRATION.md)、[EXTERNAL_SYSTEMS_TUTORIAL](EXTERNAL_SYSTEMS_TUTORIAL.md)。

| Method | 路径 | 用途 |
| --- | --- | --- |
| GET | `/health` | 健康检查 `{ok:true}` |
| GET | `/snapshot` | 整 cluster 当前 tick / 在线节点快照 |
| GET | `/directory?cluster=` | 节点目录 |
| GET | `/tick` | 当前 tick |
| GET | `/agents/profiles?cluster=` | 全部 agent profile 列表 |
| GET | `/agents/profile/{id}?cluster=` | 单个 agent profile |
| GET | `/social/snapshot?cluster=&limit=20` | 社交关系快照 |
| POST | `/register` | 注册节点 + 携带的 agents；`agent_type=openclaw` 时必须带 token |
| POST | `/tick` | 推一次 tick 更新：`{day, time, background}` |
| POST | `/auth/token` | 录入/刷新 token：`{cluster, token}` |
| POST | `/message/send` | 投递一条消息：`{cluster, node_id, message}` |
| POST | `/message/poll` | 拉消息：`{cluster, recipient_ids, since:{id:ts}, limit}` |

### 1.4 External Environment 服务

独立进程，模拟"外部世界"（天气/股市/政策）以低频 tick 推动仿真。

启动：

```bash
python -m gaworld.apps.external_environment_server
```

| Method | 路径 | 用途 |
| --- | --- | --- |
| GET | `/health` | 服务存活 |
| GET | `/snapshot` | 当前外部世界完整快照 |
| POST | `/day/start` | 通知"今天开始了"，推进并锁定当日环境 |
| POST | `/tick` | 进一步推进 tick，body 由 backend 决定 |

> 字段 schema 与仿真侧对齐 `gaworld/env/`。

---

## 2. CLI 入口

### 2.1 顶层命令：`python generative_city_sim.py <cmd>`

参考：`generative_city_sim.py:5670` `_build_arg_parser`。

| Command | 主要参数 | 作用 |
| --- | --- | --- |
| `run` | `--sim-days`、`--sim-years`、`--sim-months`、`--time-unit`、`--seed`、`--fast-forward`、`--resume-from` | 跑一次完整仿真 |
| `reset` | — | 清空 `output/` 下的状态、记忆、日志、缓存 |
| `interview` | `--agent-id`、`--question`（可重复）、`--questions-file`、`--context` | 单 agent 采访，输出到 stdout 与 `output/interviews/` |
| `create-agent-from-social` | `--url\|--file\|--text`（互斥），`--name` | 用社媒页面或文本生成一个新 agent |
| `rag-add` | `--agent-id`、`--text`、`--timestamp?`、`--source?` | 注入一条 RAG 外部信息到指定 agent |
| `rag-import` | `--agent-id`、`--file`、`--format?`、`--source?` | 从文件/目录批量注入 RAG |
| `compare-event` | `--event-name`、`--event-description`、`--event-day`、`--event-time?`、`--sim-days?`、`--seed?`、其它 | "有/无事件"两路对比，产出对比报告 |
| `parallel-worlds` | `--spec worlds.json`、`--sim-days`、`--seed`、其它 | 平行世界实验；详见 [PARALLEL_WORLDS_TUTORIAL](PARALLEL_WORLDS_TUTORIAL.md) |
| `serve-viz` | `--host`、`--port` | 跑一个静态站 + `GET /api/replay/runs`，用于回放可视化页 |
| `dashboard` | `--host`、`--port` | 启动 Dashboard 服务（见 1.1） |
| `serve-distributed` | `--host`、`--port`、`--state-path`、`--max-messages` | 启动 Agent Relay（见 1.3） |

### 2.2 子模块入口：`python -m gaworld.<module>`

| 命令 | 模块 | 作用 |
| --- | --- | --- |
| `python -m gaworld.city` | `gaworld/city/__main__.py` | 城市管理：`create / list / show / add-agents / add-agent / migrate / knowledge / news / use / delete`；详见 [CITY_TUTORIAL](CITY_TUTORIAL.md) |
| `python -m gaworld.interview` | `gaworld/interview/__main__.py` | 群体采访（按城市拆子进程）：`--spec round.json --out answers.json`；详见 [GROUP_INTERVIEW_TUTORIAL](GROUP_INTERVIEW_TUTORIAL.md) |
| `python -m gaworld.population` | `gaworld/population/__main__.py` | 参数化人口合成：`--size`、`--seed`、`--out`、`--check` |
| `python -m gaworld.group` | `gaworld/group/__main__.py` | 群体模式仿真：`--size`、`--days`、`--no-llm`、`--focal 7,42`、`--network-coupling` |
| `python -m gaworld.group.validate` | `gaworld/group/validate.py` | 群体模式 L1–L4 验证门 |
| `python -m gaworld.apps.twin_server` | `gaworld/apps/twin_server.py` | Twin 服务（见 1.2） |
| `python -m gaworld.apps.distributed_comm_server` | `gaworld/apps/distributed_comm_server.py` | Agent Relay（见 1.3） |
| `python -m gaworld.apps.external_environment_server` | `gaworld/apps/external_environment_server.py` | External Environment（见 1.4） |

### 2.3 辅助脚本

```bash
# 生成单张地图（占位 / 增量）
python scripts/generate_citymap.py --description "a small city with about 1000 residents, in east china"

# 一键部署（dashboard + relay 到 systemd / nohup）
python scripts/deploy_services.py deploy --repo "$HOME/GAWorld" --branch Dev \
  --process-manager systemd-user --host 0.0.0.0 \
  --dashboard-port 8766 --relay-port 8877
```

更多部署参数见 [SERVER_DEPLOYMENT](SERVER_DEPLOYMENT.md)。

---

## 3. Python API

> `gaworld/` 是 legacy flat 体系的迁移目标；目前 `from gaworld import …` 仅暴露版本号与 `.env` 加载器（`gaworld/__init__.py`）。
> 真正可被嵌入脚本调用的"Python 公共 API"分两类：
>   1. 子模块顶层函数（如 `gaworld.city.create`），由对应的子进程 CLI 调用；
>   2. 由子模块对外导出的服务对象（`CollaborationService`、`TwinBackend`、`DistributedRelayBackend` 等），通常被 HTTP 服务内部或外部集成代码直接 `import` 使用。

### 3.1 城市管理（`gaworld.city`）

```python
from gaworld.city import (
    create, list_cities, show, add_agents, add_agent,
    migrate, rebuild_knowledge, refresh_news, select, remove,
)
```

| 函数 | 用途 | 配套 CLI |
| --- | --- | --- |
| `create(name, size, *, offline=False, scale=None, …)` | 由地名创建城市 bundle（含 OSM 道路网络或程序化兜底地图） | `python -m gaworld.city create <name>` |
| `list_cities()` | 列出 `data/cities/` 下全部城市 | `python -m gaworld.city list` |
| `show(slug)` | 一个城市的元数据（人口、地图路径、CSV 路径） | `python -m gaworld.city show <slug>` |
| `add_agents(slug, *, size=200)` | 给城市增加批量人口 | `python -m gaworld.city add-agents <slug>` |
| `add_agent(slug, *, name="…", age=30, …)` | 增加一个指定居民 | `python -m gaworld.city add-agent <slug>` |
| `migrate(slug, agent_id)` | 把当前城市里的某位居民迁到目标城市 | `python -m gaworld.city migrate <slug>` |
| `rebuild_knowledge(slug)` | 重建该城市的本地知识库（news/places） | `python -m gaworld.city knowledge <slug>` |
| `refresh_news(slug)` | 抓取最新新闻源 | `python -m gaworld.city news <slug>` |
| `select(slug)` | 切到指定城市：写 `dashboard_config.json` 让仿真/面板都看它 | `python -m gaworld.city use <slug>` |
| `remove(slug, *, yes=False)` | 删除 bundle | `python -m gaworld.city delete <slug> --yes` |

详细字段含义、bundle 文件结构、跨城市只读接口，参见 [CITY_TUTORIAL](CITY_TUTORIAL.md)。

### 3.2 仿真内核与子系统

| 模块 | 主要导出 | 用途 |
| --- | --- | --- |
| `gaworld.kernel` | `Plugin`, `Clock`, `Bus`, `Registry`, `Recorder`, `Controller`, `Context`, `Intervention` | 微内核扩展点；详见 [PLUGIN_AUTHORING](PLUGIN_AUTHORING.md) |
| `gaworld.plugins` | `builtin_plugins()` | 返回 9 个内置插件的注册列表 |
| `gaworld.core` | `Agent`（dataclass 适配器）、`Runner`（并发执行器） | Agent 模型与并行执行 |
| `gaworld.sim` | `Pipeline`（认知管线）、`_action`、`_cognition` | 仿真核心逻辑（插件化） |
| `gaworld.personality` | Big Five traits / anchors | 大五人格 |
| `gaworld.memory` | `store`、`experience`、`consolidation`、`decay` | 记忆系统 |
| `gaworld.skills` | `schemas`、`registry`、`consolidation` | 技能系统 |
| `gaworld.infosources` | `registry/channels/feed/diet/search` | 外部信息源（新闻/社交/专业站 → 每居民的信息食谱） |
| `gaworld.events` | 生命事件 | 居民大事件 |
| `gaworld.family` | assign / overrides / ties / duties / finance / events | 家庭与户 |
| `gaworld.economy` | 财务系统 | 经济模块 |
| `gaworld.work` | router / queue / market / adapters | 工作模块 |
| `gaworld.world` | 城市地图 | 空间感知、道路拥堵 |
| `gaworld.travel` | destination / trigger / itinerary | 离城（出差/探亲/旅行） |
| `gaworld.policy` | 干预策略 | 外部干预入口 |
| `gaworld.behavior` | dynamic / plugin | 动态行为模块 |
| `gaworld.cognition` | realism | 人类真实感 |
| `gaworld.interview` | schema / roster / prompt / runner / aggregate / report / store / session | 群体采访系统 |
| `gaworld.persona` | research / distill / render / store | 真人蒸馏（名字/URL → 居民 + 思维框架） |
| `gaworld.moltbook` | accounts / client / log | 居民上智能体社交网络 |
| `gaworld.llm` | `gaworld.llm.providers` 包装 + 路由 | 切/测/用 LLM 供应商 |
| `gaworld.collaboration` | `CollaborationService` | 讨论/合作任务，1.1.5 路由的 backend |
| `gaworld.twin` | `TwinBackend` + `binding.issue_code` | Twin 服务 backend；`issue_code(agent_id=None, label="", path=…)` 发行邀请码 |
| `gaworld.distributed` | `DistributedRelayBackend` | Agent Relay backend |
| `gaworld.integrations` | 外部系统（OpenClaw 等）适配 | 跨集群接入 |
| `gaworld.io` | `web_scrape`、`http_guard`、`avatar` | 网页抓取 / 头像等工具 |
| `gaworld.config` | 读取 `CONFIG`（已分层到 `gaworld/settings/`） | 配置 |
| `gaworld.env_loader` | `load_env_file(path)` | 加载 `.env`，不带 `override=True` 时真环境变量优先 |
| `gaworld.logging_setup` | 日志格式与等级 | 日志 |

### 3.3 嵌入示例

```python
# 1. 把仿真跑在自己的脚本里
from gaworld.kernel import Controller, Clock
from gaworld.plugins import builtin_plugins

plugins = builtin_plugins()
ctrl = Controller.from_plugins(plugins, config=CONFIG, world=current_city)
clock = Clock(start_day=1)
ctrl.run_until(day=clock.sim_days=7)

# 2. 给指定居民发一次采访
from gaworld.interview.runner import run_interview
answer = run_interview(agent_id=31, question="今天最想做什么？")

# 3. 启一个 Twin 服务（嵌入到自家应用里）
from gaworld.apps.twin_server import build_backend, run_server
run_server(host="0.0.0.0", port=8767, backend=build_backend())
```

> 提示：脚本/Notebook 嵌入时建议先 `from gaworld.env_loader import load_env_file; load_env_file(".env")`，以确保 `MINIMAX_API_KEY` 等凭据被读到（`gaworld/__init__.py` 在包被 `import` 时会自动执行）。

---

## 4. 鉴权 / 错误约定 / 调试

- **Dashboard (8766)**：以点开头的静态路径（`/.env`、`/.git/`）始终 404。设置环境变量 `GAWORLD_DASHBOARD_TOKEN` 后所有请求需令牌：脚本用 `Authorization: Bearer <token>`，浏览器打开一次 `/?token=<token>` 换取 HttpOnly + SameSite=Strict cookie；未设置则不鉴权（仅建议本机使用）。见 [SERVER_DEPLOYMENT](SERVER_DEPLOYMENT.md#访问控制对外暴露前必读)。
- **Twin (8767)**：必须 HTTPS；客户端用 `Authorization: Bearer <token>` 访问 `/api/twin/*`。
- **Agent Relay (8877)**：`agent_type=native` 直通；`agent_type=openclaw` 必须 `POST /auth/token` 录入 token 后，注册/发消息都校验。
- **External Environment**：内部子网使用即可。
- 错误格式统一：`{"error": "message"}`，HTTP 4xx 表示参数/资源错，5xx 表示后端异常（Dashboard 会把 traceback 打到服务端日志）。
- 调试端点：
  - `GET /api/replay/runs` 列出全部历史 run，配合 `/api/analytics/{section}?run=<id>` 复盘。
  - `GET /api/run/status?log_offset=N` 轮询运行进度；`log_offset` 用来增量取日志。
  - `GET /api/events/stream` 用 `curl -N` 实时看 Recorder 各表的新增行（见 1.1.6）。
  - `GET /api/agents/{id}/detail` 一次性拿到 profile + state + big5 + 关系 + 财务，常用于 Agent Studio 等前端面板。

---

## 5. 相关文档

- [TUTORIAL](TUTORIAL.md) / [TUTORIAL.v2](TUTORIAL.v2.md) — 端到端入门
- [FEATURES](FEATURES.md) — 功能特性与启用方式
- [CITY_TUTORIAL](CITY_TUTORIAL.md) — 城市 bundle
- [GROUP_INTERVIEW_TUTORIAL](GROUP_INTERVIEW_TUTORIAL.md) — 群体采访
- [PARALLEL_WORLDS_TUTORIAL](PARALLEL_WORLDS_TUTORIAL.md) — 平行世界实验
- [PERSONA_DISTILL_TUTORIAL](PERSONA_DISTILL_TUTORIAL.md) — 真人蒸馏
- [OPENCLAW_INTEGRATION](OPENCLAW_INTEGRATION.md) / [EXTERNAL_SYSTEMS_TUTORIAL](EXTERNAL_SYSTEMS_TUTORIAL.md) — 外部系统
- [SERVER_DEPLOYMENT](SERVER_DEPLOYMENT.md) — 生产部署
- [PLUGIN_AUTHORING](PLUGIN_AUTHORING.md) — 插件开发
