# GAWorld API 参考

GAWorld 对外暴露三种 API 表面，覆盖从单条 CLI 命令到多服务 HTTP 集成的全部用法：

| 表面 | 适用场景 | 入口 |
| --- | --- | --- |
| **HTTP** | Dashboard / 前端 / 第三方系统接入、机器对机器集成 | `dashboard_server.py`、`twin_server.py`、`distributed_comm_server.py`、`external_environment_server.py`；Python 客户端 `gaworld.client`（见 3.4） |
| **CLI** | 本地仿真运行、单次任务、批量实验、子进程流水线 | `python generative_city_sim.py <cmd>`、`python -m gaworld.<sub>` |
| **Python** | 把仿真内核或子系统嵌入自己的脚本 / Notebook | `import gaworld`、`from gaworld.<sub> import …` |

> 约定
> - 所有 HTTP 服务的请求/响应均为 UTF‑8 JSON；`POST` body 也用 JSON。
> - 通用错误：`{"error": "..."}`；Dashboard 各状态码的含义见 1.1.0。
> - Dashboard（端口 8766）只在设置了 `GAWORLD_DASHBOARD_TOKEN` 或开启账号后才要求鉴权（见第 4 节）；其余独立服务鉴权策略见各自章节。
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
所有 `/api/*` 路径由 `DashboardHandler._handle_api_get` / `_handle_api_post`（`gaworld/apps/dashboard_server.py`）分发：按整段前缀交给 `gaworld/apps/<module>_api.py` 的 `handle_get/handle_post`（前缀表在 `gaworld/apps/routes.py`），其余在 handler 里直接处理。

#### 1.1.0 接口约定与机器可读描述

**`GET /api/openapi.json`**（OpenAPI 3.1，源在 `gaworld/apps/openapi.py`）描述 Dashboard 的**全部** `/api/*` 路由（约 280 个操作），控制台各面板自用的也在内；本文档下面的表是导读，字段以它为准。可直接导入 Swagger UI / Postman，或用 `openapi-generator` 生成客户端。每个操作自动带有：

- `operationId`：`<method>_<路径段>`，参数段取参数名，`-`/`.` 换成 `_`。例：`GET /api/agents/{agent_id}/state` → `get_agents_agent_id_state`，`POST /api/games/rumor/run` → `post_games_rumor_run`。`gaworld.client` 按它调用任意接口（3.4）。
- `x-gaworld-access`：开启账号后需要的级别（`public` / `member` / `city` / `world` / `admin`，取自 `gaworld/accounts/policy.py`）；`x-gaworld-quota: true` 标出会花模型调用、成员当日额度用完后被拒的请求。
- 分布式世界节点用的 `/api/cluster/node*`、`/api/cluster/relay/*` 标 `security: node`（节点令牌）。

`tests/test_openapi.py` 双向校验它不与代码脱节：文档合法；文档里的每个 GET 都逐条请求、确认已注册，每个 POST 的路径段都在代码里；反过来，服务端代码和控制台脚本里出现的每个 `/api/…` 路由都必须在文档里——**新加路由时同时在 `openapi.py` 里加一条**，否则测试失败。

**状态码**（错误体一律 `{"error": "..."}`）：

| 状态 | 含义 |
| --- | --- |
| 200 | 成功 |
| 202 | 已排队 / 已开作业：后台作业返回 `{"job_id": …}`（干预返回请求记录） |
| 400 | 参数不对（缺字段、类型错、JSON 体不是对象） |
| 401 / 403 | 未登录或令牌不对 / 已登录但无权限 |
| 404 | 找不到对象（居民、作业、会话…）；路由不存在时统一为 `{"error": "Unknown endpoint"}` |
| 405 | 路由存在但不支持这个方法；响应头 `Allow` 与体里的 `allowed` 列出可用方法（依据 OpenAPI 文档判断） |
| 409 | 状态冲突：已有仿真在运行或排队、没有运行中的仿真可干预、已有平行世界实验/研究在跑、居民已被别人认领 |
| 413 | 请求体过大（分布式节点上传） |
| 429 | 成员当日模型调用额度已用完 |
| 500 / 502 | 服务端异常（traceback 打到服务端日志）/ 上游模型调用失败 |

**后台作业**：耗时的请求（游戏场各局、群体采访、研究分析、真人蒸馏、人口合成、批量导入、斗兽场、严肃游戏设计、政策仿真）立刻返回 `202` + `{"job_id"}`，再轮询同一前缀下的 `…/jobs/{job_id}`（`POST /api/games/rumor/run` → `GET /api/games/rumor/jobs/{job_id}`），直到 `status` 不再是 `running`：`done` 时读 `result`，`failed` / `error` 时读 `error`。例外：评测 `POST /api/bench/run` 返回的作业 id 在 `id` 字段；研究 `POST /api/research/studies/{id}/run` 的作业在 `/api/research/jobs/{job_id}`；平行世界用 `GET /api/parallel-worlds/job?id=`。

**当前世界**：开启账号后，每个请求读写的都是 cookie `gaworld_world` 指定的世界（`POST /api/worlds/select` 切换），见 1.1.7。

#### 1.1.1 顶层路由

居民相关的读写在 `gaworld/apps/residents.py`，其余在 `dashboard_server.py` 本身。

| Method | 路径 | 用途 | Handler / 参考 |
| --- | --- | --- | --- |
| GET | `/api/config` | 当前生效的仿真配置摘要（合并 `config.py` + `dashboard_config.json` + 环境覆盖） | `dashboard_server._config_summary` |
| POST | `/api/config` | 部分覆盖配置并写回当前世界的 `dashboard_config.json` | `dashboard_server._save_config_patch` |
| GET | `/api/agents` | 全部 agent 摘要列表（id、姓名、年龄、性别、状态概览） | `residents.agents_summary` |
| POST | `/api/agents` | 创建一个新 agent（body：`name, gender, age, hukou, residence, job, personality, daily_life, values, education_income, social_network, state`） | `residents.create_agent` |
| GET | `/api/agents/{id}/avatar` | 生成的头像（`image/svg+xml`） | `build_agent_avatar_svg` |
| GET | `/api/agents/{id}/profile` | 单个 agent 的 profile markdown + 解析后的结构化字段 | `residents.agent_profile` |
| POST | `/api/agents/{id}/profile` | `body.text` 写入 profile | `residents.save_agent_profile` |
| GET | `/api/agents/{id}/state` | 九维状态（情绪/能量/社交/金钱等） | `residents.agent_state` |
| POST | `/api/agents/{id}/state` | 改写/补充九维状态：`{state, age?}` | `residents.save_agent_state` |
| GET | `/api/agents/{id}/big5` | Big Five 性格（O/C/E/A/N） | `residents.agent_big5` |
| POST | `/api/agents/{id}/big5` | `{values: {openness…neuroticism}}`，每项 0–1；非法 → 400 | `residents.save_agent_big5` |
| GET | `/api/agents/{id}/detail` | 完整合成快照（profile + state + big5 + 关系 + 财务等） | `residents.agent_detail` |
| GET | `/api/agents/{id}/autobiography` | 由记忆写成的自传（一次模型调用；失败 502） | `autobiography_api.handle_get` |
| GET | `/api/agents/{id}/memory` | 记忆列表 + 摘要 + 标签分布 | `residents.memory_payload` |
| POST | `/api/agents/{id}/memory` | 追加一条记忆 `{text, kind?}` | `residents.append_agent_memory` |
| GET | `/api/agents/{id}/goals` | 当前目标树 | `residents.agent_goals_payload` |
| POST | `/api/agents/{id}/goals` | 改写目标树；非法 → 400 | `residents.save_agent_goals_payload` |
| POST | `/api/agents/{id}/relationships` | 写入社会关系 `{relations, removed?}`（只有 POST；读取走 `/detail`） | `residents.save_agent_relationships` |
| POST | `/api/agents/{id}/finance` | 写入经济账户 `{accounts}`（只有 POST；读取走 `/detail`） | `residents.save_agent_finance` |
| GET | `/api/skills` | 技能库（名称 + 触发词 + 版本） | `residents.skills_library` |
| GET | `/api/agents/{id}/…` 的 404 | `{"error": "Agent not found"}` 或 `Profile not found` | — |
| GET | `/api/run/status?log_offset=N` | 仿真运行状态（启动/停止/进度/排队位置/最近日志偏移量） | `runs.run_status` |
| GET | `/api/run/log/export` | 把运行日志导出成 Markdown 文件下载 | `dashboard_server._run_log_markdown` |
| GET | `/api/trace/meta` | 最近一次 trace 的元信息（输出目录、agent 数） | `dashboard_server._latest_trace_meta` |
| GET | `/api/trace/data` | 最近一次 trace 的帧数据 | `dashboard_server._trace_payload` |
| GET | `/api/replay/runs` | 全部历史 run 目录，可用于 `/api/analytics/{section}?run=<id>` | `dashboard_server._replay_runs` |
| GET | `/api/life-events` | 整城生命事件列表 | `dashboard_server._life_events_payload` |
| POST | `/api/life-events` | 注入一个生命事件：`{title, description, severity, agent_id \| agent_ids, schedule_mode, day?, time?, state_effects?, impact_tags?}`，或只给 `{candidate_key, agent_id}` 由候选目录补全 | `dashboard_server._add_life_event` |
| GET | `/api/life-events/candidates?agent_id=&limit=` | 给定 agent 的候选事件（用于"今晚让 ta 遇到什么"面板） | `dashboard_server._life_event_candidates_payload` |
| GET | `/api/todos` | 整个 todo 看板 | `dashboard_server._todo_board_payload` |
| POST | `/api/todos` | `body.items` 整体替换 todo 列表 | `dashboard_server._save_todo_board` |
| POST | `/api/todos/create` | 新建一条 todo | `dashboard_server._create_todo_item` |
| POST | `/api/todos/update` | 改 todo（完成、编辑、移动列），`body.id` 必填 | `dashboard_server._update_todo_item` |
| POST | `/api/todos/clear` | 清空 todo 板 | `dashboard_server._save_todo_board([])` |
| POST | `/api/todos/create-form` | 表单版新建 todo（`application/x-www-form-urlencoded`），完成后 303 → `/board` | `dashboard_server._create_todo_item` |
| POST | `/api/interview` | 单 agent 采访（子进程跑 `generative_city_sim.py interview`）：`{agent_id, questions: str \| [str], context?, timeout?=300}` | `dashboard_server._interview_agent` |
| POST | `/api/fos-export` | 读取仿真产物并用 LLM 生成一份 FOS（Frame‑of‑Science）提示词；body `output_dir?`、`hint?`、`english?` | `dashboard_server._fos_export` |
| POST | `/api/relationships/friends` | 给一组 agent 建立双向好友关系（多智能体互动前置步骤）：`{agent_ids}` | `CollaborationService.make_friends` |

#### 1.1.2 仿真运行控制

| Method | 路径 | 用途 |
| --- | --- | --- |
| POST | `/api/run/start` | 在当前世界启动（或在名额满时排队）一次仿真子进程：`{config?, reset?}`——`config` 是配置补丁（`sim_span`、`time_step_minutes`、`agent_ids`…），先写入再启动；`reset` 先清空产物。已有运行或排队 → **409** |
| POST | `/api/run/stop` | 停止当前世界的仿真 |
| POST | `/api/run/schedule` | 定时启动：`{at, config?, reset?}`，`at` 为 ISO 时间或 `HH:MM` |
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

未知 section → 404 `Unknown analytics section`；`run` 不在列表里 → 404 `Unknown run`。参考：`dashboard_server._analytics_payload`。

#### 1.1.4 子模块路由（按 namespace 拆分）

以下子 namespace 在 `dashboard_server.py` 顶层分发到独立模块，路径均以 `/api/<ns>/` 起头；详细字段见各自文件。

| Namespace | 模块 | 主要路径 | 文档 |
| --- | --- | --- | --- |
| `population` | `gaworld/apps/population_api.py` | `GET /api/population/schema`、`GET /api/population/jobs/{id}`、`GET /api/population/export`、`GET /api/population/last`；`POST /api/population/preview`、`POST /api/population/generate`、`POST /api/population/group-run`、`POST /api/population/validate` | [CITY_TUTORIAL](CITY_TUTORIAL.md) |
| `import` | `gaworld/apps/import_api.py` | `GET /api/import/schema`、`GET /api/import/jobs/{id}`；`POST /api/import/preview`、`POST /api/import/run` | [BULK_IMPORT_TUTORIAL](BULK_IMPORT_TUTORIAL.md) |
| `arena` | `gaworld/apps/arena_api.py` | `GET /api/arena/tasks`、`/api/arena/agents`、`/api/arena/jobs/{id}`；`POST /api/arena/generate`、`/api/arena/run`、`/api/arena/retain`、`/api/arena/refill`、`/api/arena/state` | [ARENA_TUTORIAL](ARENA_TUTORIAL.md) |
| `games/` | `gaworld/apps/games_api.py` | 游戏场。`GET /api/games/agents?city=`、`/api/games/persuasion/sessions[/{id}]`；`POST /api/games/persuasion/start`（body `{city, agent_id, question, max_turns}` → 完整 session，含 `initial_answer`）、`/api/games/persuasion/say`（`{session_id, message}`，用完最后一轮时连带结算）、`/api/games/persuasion/settle`（`{session_id}` → 复问 + 裁判，`outcome ∈ {success, failed}`）。会话只在内存里（≤ 50 局）。**谁是真人**转发给 `whois_api.py`：`GET /api/games/whois/catalogue`（话题与人数上限）`\|/rooms`（自己的房间）`\|/rooms/{id}?seat=`（不带 `seat` 是房主视图，含座位链接与谁还没发 / 没投；带 `seat` 只看得到座位号、聊天记录和自己的状态，揭晓前没有身份）；`POST /api/games/whois/rooms`（`{city, agent_ids?, agents, humans, rounds, topic_id\|custom}`，建房即开第一轮，不阻塞，居民在后台写）、`/rooms/{id}/say`（`{seat, text}`）、`/rooms/{id}/vote`（`{seat, verdicts: {座位号: "human"\|"resident"}, reason?}`，要覆盖除自己外的每个座位）、`/rooms/{id}/next`（房主：不等缺席的人收这一轮）、`/rooms/{id}/reveal`（房主：不等没投的人揭晓）。房间只在内存里，揭晓时存档到 `output/games/whois/` 供 Bench Track D。**灾害模式**转发给 `gaworld/apps/disaster_api.py`：`GET /api/games/disaster/catalogue\|/api/games/disaster/runs\|/api/games/disaster/jobs/{id}`；`POST /api/games/disaster/run`（body `{city, agent_ids, disaster_id|custom, stages}` → `{job_id}`，作业跑完 `result` 是整场推演：逐人 `reactions` + 逐幕 `stats` + `summary`）。**谣言扩散局**转发给 `gaworld/apps/rumor_api.py`：`GET /api/games/rumor/catalogue\|/api/games/rumor/graph?city=&agent_ids=1,2,3`（关系图预览，**不花模型调用**）`\|/api/games/rumor/runs\|/api/games/rumor/jobs/{id}`；`POST /api/games/rumor/run`（body `{city, agent_ids, rumor_id|custom, seeds, rounds}` → `{job_id}`，作业跑完 `result` 含 `nodes` / `edges` / `transmissions`（传播树）/ 逐轮 `rounds` / `stats`（含 `superspreader`、`firewalls`）/ `summary`）。关系图按档案推导（同小区 / 同姓 / 同行 / 同学 / 同龄），每人限 6 条边。**双队竞赛**转发给 `gaworld/apps/duel_api.py`：`GET /api/games/duel/catalogue`（内置任务，每个自带一对相反的办法）`\|/api/games/duel/runs\|/api/games/duel/jobs/{id}`；`POST /api/games/duel/run`（body `{city, team_a, team_b, task_id|custom, rounds}` → `{job_id}`，作业跑完 `result` 含逐队 `members[].moves` / 逐轮 `plans` / `verdict`（四维打分、`order` 蒙名顺序、`judge_said`）/ `stats`）。评审拿到的是「方案一 / 方案二」且顺序随机，赢家由**总分**决定而不是模型说了算；自定义任务必须给两个办法，同一个人不能在两队。**公投局**转发给 `referendum_api.py`：`GET /api/games/referendum/catalogue\|/runs\|/jobs/{id}`；`POST /api/games/referendum/run`（body `{city, agent_ids, motion_id|custom, campaign}` → `{job_id}`，先私下表态再公开表决，`result` 含逐人 `private`/`public`、`flips`、`stats.swing`）。**猜人局**转发给 `guess_api.py`：`GET /api/games/guess/catalogue\|/scoreboard\|/rounds/{id}`；`POST /api/games/guess/deal`（发牌，**不花调用**）、`/answer`（`{round_id, guess}` → 对错）、`/again`（复问同一人同一题，量档案稳定性）。**小说局** `novel_api.py`：`GET /api/games/novel/catalogue\|/agents?city=\|/runs\|/jobs/{id}`；`POST /api/games/novel/run`（`{city, agent_ids, style_id\|style_custom, target_words, chunks_per_chapter, outline?, title_hint?}`）。**陪审团** `jury_api.py`：`GET /api/games/jury/catalogue\|/runs\|/jobs/{id}`；`POST /api/games/jury/run`（`{city, agent_ids, case_id\|custom, rounds, question_key?}`）。**新闻评论** `commentary_api.py`：`GET /api/games/commentary/catalogue\|/runs\|/jobs/{id}`；`POST /api/games/commentary/run`（`{city, agent_ids, url\|title+body}`）。所有 `…/run` 都返回 **202** + `{job_id}`。后台作业用 `gaworld/apps/game_jobs.py` 的 `JobStore`，每个游戏一个。斗兽场仍在 `arena` 命名空间 | [PLAYGROUND_TUTORIAL](PLAYGROUND_TUTORIAL.md) |
| `family` | `gaworld/apps/family_api.py` | `GET /api/family/overview`（`/api/family` 同）`\|/api/family/preview?agent_id=`（`GET /api/family/override` 同）`\|/api/family/agent?agent_id=`；`POST /api/family/override`（`{agent_id, override\|clear}`） | [FAMILY_DESIGN](FAMILY_DESIGN.md) |
| `interview/`（带尾斜杠，避开单 agent 旧接口） | `gaworld/apps/interview_api.py` | `GET /api/interview/roster\|/api/interview/sessions\|/api/interview/jobs/{id}\|/api/interview/sessions/{id}[/export]`；`POST /api/interview/plan`、`/api/interview/run`、`/api/interview/delete` | [GROUP_INTERVIEW_TUTORIAL](GROUP_INTERVIEW_TUTORIAL.md) |
| `research/` | `gaworld/apps/research_api.py` | `GET /api/research/context\|/api/research/plans\|/api/research/jobs/{id}\|/api/research/plans/{id}[/export]\|/api/research/studies[/{id}]`；`POST /api/research/digest`、`/api/research/analyze`、`/api/research/extract`、`/api/research/delete`、`/api/research/studies`（可带 `design_index` 选实验设计）、`/api/research/studies/{id}`（动作：update / approve / run / pause / resume / stop / reset / delete；另一项研究在跑 → 409）。**严肃游戏** `serious_game_api.py`：`GET /api/research/games\|/games/{game_id}\|/games/jobs/{id}\|/games/sessions/{id}[/export]?seat=`；`POST /api/research/games/design`（202）、`/games/sessions`、`/games/sessions/{id}/act\|resolve\|delete`、`/games/{game_id}/update\|delete`。**政策仿真** `policy_sim_api.py`：`GET /api/research/policy\|/policy/{run_id}[/export]\|/policy/jobs/{id}`；`POST /api/research/policy/run`（202，`{policy, candidate?, city, sample_size, seed, verify, provider}`）、`/policy/{run_id}/delete` | [EXPERIMENTS_REPORT](EXPERIMENTS_REPORT.md) |
| `persona/` | `gaworld/apps/persona_api.py` | `GET /api/persona/list\|/api/persona/jobs/{id}\|/api/persona/detail/{slug}`；`POST /api/persona/distill`、`/api/persona/deploy`、`/api/persona/install-skill`、`/api/persona/delete` | [PERSONA_DISTILL_TUTORIAL](PERSONA_DISTILL_TUTORIAL.md) |
| `external-systems` | `gaworld/apps/external_systems_api.py` | `GET /api/external-systems/overview\|/api/external-systems/health\|/api/external-systems/interventions`；`POST /api/external-systems/config`、`/api/external-systems/interventions`、`/api/external-systems/interventions/cancel` | [EXTERNAL_SYSTEMS_TUTORIAL](EXTERNAL_SYSTEMS_TUTORIAL.md) |
| `parallel-worlds` | `gaworld/apps/parallel_worlds_api.py` | `GET /api/parallel-worlds/overview\|/api/parallel-worlds/experiments\|/api/parallel-worlds/experiment?root={root}[&baseline={world}]\|/api/parallel-worlds/heterogeneity?root=&world=&metric=[&baseline=]\|/api/parallel-worlds/interpretation?root=[&baseline=]\|/api/parallel-worlds/job?id={id}`；`POST /api/parallel-worlds/preview`、`/api/parallel-worlds/sweep`（把一个数值参数的几组取值展开成世界，不运行）、`/api/parallel-worlds/start`（可带 `seeds: [..]` 重复多个种子）、`/api/parallel-worlds/stop`、`/api/parallel-worlds/interpret` | [PARALLEL_WORLDS_TUTORIAL](PARALLEL_WORLDS_TUTORIAL.md) |
| `settings` | `gaworld/apps/settings_api.py` | `GET /api/settings/overview`；`POST /api/settings/save`、`/api/settings/reset`、`/api/settings/reset-all`、`/api/settings/llm/provider`、`/api/settings/llm/test` | — |
| `city` | `gaworld/apps/city_api.py` | `GET /api/city/overview\|/api/city/detail?city=\|/api/city/catalogue\|/api/city/agents?city=&q=&limit=&offset=\|/api/city/agent?city=&id=\|/api/city/map?city=\|/api/city/knowledge?city=\|/api/city/news?city=`；`POST /api/city/create`、`/api/city/population`、`/api/city/agent`、`/api/city/migrate`、`/api/city/knowledge`、`/api/city/news`、`/api/city/select`、`/api/city/delete` | [CITY_TUTORIAL](CITY_TUTORIAL.md) |
| `infosources/`（只读） | `gaworld/apps/infosources_api.py` | `GET /api/infosources/sources`（注册表 + 各源缓存条数、上次抓取时间）、`/api/infosources/feed?source_id=&limit=`（缓存中的条目）、`/api/infosources/diets[?agent_id=]`（每位居民读哪些源、权重与理由）、`/api/infosources/reads?url=&source_id=&agent_id=&limit=`（`infosources.read` 记录，最新在前）。写入走干预：`POST /api/interventions/inject_info_item` | — |
| `bench/` | `gaworld/apps/bench_api.py` | `POST /api/bench/run`（body `kind: "bench"\|"rubric"` + 白名单选项，对应 `benchmark/gaworld_bench.py` / `rubric_bench.py` 的 CLI 参数：bench 支持 `track`（`A｜B｜C｜D`）`, all, synthetic, output_dir, games_dir, comparisons_root, run, days, seed, seeds, resume, fast, llm_provider`；rubric 支持 `output_dir, synthetic, synthetic_mode, judges, samples_per_judge, min_days, ablate, dim`；路径必须在仓库内）→ `202` + job；同一时间只跑一个（结果文件共用），否则 `409`。`GET /api/bench/jobs[/{id}]`（状态、命令、日志尾部、**该次运行的 scorecard 快照**）、`/api/bench/scorecard`（两套最新 scorecard）、`/api/bench/reports[/{name}]`（历史报告 Markdown）。Track R 人类锚点校准：`GET /api/bench/calibration`（校准集列表、各人标注数、结论）、`GET /api/bench/calibration/{set_id}?annotator=`（题目，只附该标注者自己的标注；不含哪些题被改坏）、`POST /api/bench/calibration/build`（`output_dir?, n?, seed?`，默认取当前世界的运行目录）、`POST …/{set_id}/label`（`annotator, task_id, score: 0｜1｜2｜null, note?`）、`POST …/{set_id}/analyze`；judge 打分走 `POST /api/bench/run`（`kind: "calibration", judge: true, set, judges`，会调模型） | [GAWORLD_BENCH_DESIGN](../benchmark/GAWORLD_BENCH_DESIGN.md) |
| `economy/`（只读） | `gaworld/apps/economy_api.py` | `GET /api/economy/overview`（宏观状态、部门资金池、货币守恒审计、财富分布、城市日账——与 External Systems 面板同一份数据）、`/api/economy/loans`（居民间借贷图：`borrower → lender, amount`，银行负债榜，以及借贷双方账目是否对得上：`consistent` / `mismatches`）、`/api/economy/ledger?agent_id=&limit=`（单个居民的逐期账本 + 当前欠/借出）。经济干预仍走 `POST /api/external-systems/interventions`（按天排期） | — |
| `moltbook` | `gaworld/apps/moltbook_api.py` | `GET /api/moltbook/agent?id=`；`POST /api/moltbook/toggle`（`{agent_id, enabled, name?}`）、`/api/moltbook/refresh`（`{agent_id}`） | — |
| `home` | `gaworld/apps/home_api.py` | `GET /api/home`（有户型设计的居民）、`/api/home/{agent_id}?tail=`（户型 + 最近的在家观察；还没设计 → 404） | — |
| 单 agent 旧接口 | `dashboard_server._interview_agent` | `POST /api/interview`（body `{agent_id, questions, context?, timeout?}`，见 1.1.1） | [TUTORIAL](TUTORIAL.md) |

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
- 开启账号后，成员经此接口发的 `update_config` 只能改仿真参数（`gaworld/accounts/policy.py` 的 `CONFIG_PARAM_SECTIONS`），且不能改路径、地址、凭据类的键或整段替换，否则 403；管理员与单人模式不受限。进程内 `controller.intervene` 不受此限制。
- 新一次运行启动时会丢弃上一次遗留的 pending 请求；仿真进程已退出（含崩溃）即视为未运行。
- 平行世界各用自己的队列（`<world_dir>/kernel/interventions.json`），此接口只作用于主运行。
- 事件流只包含写进 Recorder 的表。常用表：`agent.step`（每个 agent 每个 tick 一行：`agent_id, name, scheduled_activity, activity, action, location, target_location, changed, change_reason`；感知/计划/反思等长文本仍只在 trace 里）、`controller.intervention` / `controller.intervention_failed`、`infosources.injected` / `infosources.read`（`agent_id, name, source_id, title, url, thought`）、`traffic.tick`、`travel.*`、`family.*`。快进（月/年粒度）模式不经过逐 tick 管线，不产生 `agent.step`。

#### 1.1.7 账号、世界、分布式与多人共玩

这些路由要用请求里的用户、账号库或 cookie，所以由 `dashboard_server` 直接分发（不在 `routes.py` 的前缀表里）。没有账号库时 `/api/auth/me`、`/api/worlds` 返回 `{"mode": "single"}`，其余返回 404 `账号功能未开启`。

| 模块 | 路径 | 说明 |
| --- | --- | --- |
| `accounts_api.py` | `GET /api/auth/me`；`POST /api/auth/login`（`{nickname, password}`）、`/register`（`{code, nickname, password}`）、`/reset`（`{code, password}`）、`/logout`、`/password`（`{old, new}`） | 登录/注册/重置会设置 `gaworld_session` cookie（HttpOnly、SameSite=Strict）；登录失败 401 |
| `accounts_api.py`（管理员） | `GET /api/auth/users\|/invites\|/audit\|/usage`；`POST /api/auth/invites`（`{count, label, expires_days, can_create_city}`）、`/api/auth/invites/{id}/revoke`、`/api/auth/users/{id}/reset`、`/api/auth/users/{id}/city`（`{allow}`） | 教师控制台用 |
| `worlds_api.py` | `GET /api/worlds`、`/api/worlds/{id}/trail`、`/api/worlds/settings`（管理员）；`POST /api/worlds/create`（`{name, city}`）、`/select`（`{id}`，`""` 为共享默认世界）、`/{id}/visibility`（`private\|class\|open`）、`/{id}/stop`、`/{id}/delete`、`/settings`（运行名额、每日额度）、`/broadcast`（`{title, description, severity, world_ids}`，管理员） | `create` / `select` 设置 `gaworld_world` cookie；之后所有请求作用于该世界 |
| `cluster_api.py`（世界主人） | `GET /api/cluster`；`POST /api/cluster/nodes`（`{name, agent_ids}` → 一次性返回节点令牌）、`/api/cluster/nodes/{id}/agents`、`/api/cluster/nodes/{id}/delete` | 下次运行生效 |
| `cluster_api.py`（节点，`Authorization: Bearer <world>.<node>.<secret>`） | `GET /api/cluster/node\|/node/bundle\|/node/interventions\|/relay/directory`；`POST /api/cluster/node/heartbeat\|/node/records\|/node/sync\|/relay/register\|/relay/message/send\|/relay/message/poll` | `python -m gaworld.cluster join` 使用；节点令牌只到自己的世界 |
| `play_api.py` | `GET /api/play`；`POST /api/play/claim`（`{agent_id}`，两分钟租约，每 30 s 续）、`/release`、`/act`（`{text}`）、`/say`（`{target_id, text}`） | 别人正在玩该居民 → 409 |

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

参考：`generative_city_sim.py` 的 `_build_arg_parser`。

| Command | 主要参数 | 作用 |
| --- | --- | --- |
| `run` | `--sim-days`、`--sim-years`、`--sim-months`、`--time-unit`、`--seed`、`--fast-forward`、`--resume-from` | 跑一次完整仿真 |
| `reset` | — | 清空 `output/` 下的状态、记忆、日志、缓存 |
| `interview` | `--agent-id`、`--question`（可重复）、`--questions-file`、`--context` | 单 agent 采访，输出到 stdout 与 `output/interviews/` |
| `create-agent-from-social` | `--url\|--file\|--text`（互斥），`--name` | 用社媒页面或文本生成一个新 agent |
| `rag-add` | `--agent-id`、`--text`、`--timestamp?`、`--source?` | 注入一条 RAG 外部信息到指定 agent |
| `rag-import` | `--agent-id`、`--file`、`--format?`、`--source?` | 从文件/目录批量注入 RAG |
| `compare-event` | `--event-name`、`--event-description`、`--event-day`、`--event-time?`、`--sim-days?`、`--seed?`、其它 | "有/无事件"两路对比，产出对比报告 |
| `parallel-worlds` | `--spec worlds.json` 或 `--sweep 路径=取值1,取值2,…`（参数扫描，可加 `--placebo`）、`--sim-days`、`--seed`、其它 | 平行世界实验；详见 [PARALLEL_WORLDS_TUTORIAL](PARALLEL_WORLDS_TUTORIAL.md) |
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

### 3.4 HTTP 客户端（`gaworld.client`）

只用标准库，连一个正在运行的 Dashboard。命名方法覆盖常用流程；其余接口用 `call(operationId, …)`——操作表在第一次调用时从 `/api/openapi.json` 读取，所以服务端新增的路由不用改客户端。

```python
from gaworld.client import GAWorldClient, ConflictError, JobFailed

gw = GAWorldClient("http://127.0.0.1:8766")      # token 默认取 $GAWORLD_DASHBOARD_TOKEN，以 Bearer 发送
gw.login("老师", "…")                              # 开启账号时：保存 session cookie
gw.use_world("")                                   # 切换当前世界（"" 为共享默认世界）

gw.start_run(config={"sim_span": {"unit": "day", "count": 3}})     # 已有运行 → ConflictError（409）
req = gw.intervene("set_agent_state", agent_id=3, key="stress", value=0.9)
gw.wait_intervention(req["id"])                    # 等仿真在下一个 tick 应用

result = gw.run_job("/api/games/rumor/run",        # 开作业 → 轮询 …/jobs/{id} → 返回 result
                    {"city": "wuzhen", "agent_ids": [1, 2, 3], "rumor_id": "water"})

gw.call("get_city_agents", city="wuzhen", limit=20)          # 路径参数按名字填，其余进查询串
gw.call("post_agents_agent_id_memory", {"text": "搬了新家"}, agent_id=3)

for table, row in gw.events(["agent.step"]):       # 跟随 /api/events/stream
    print(table, row["name"], row["activity"])
```

| 方法 | 作用 |
| --- | --- |
| `call(operation_id, body=None, **params)` / `operations()` | 按 `operationId` 调用任意接口 / 列出全部操作 |
| `get(path, **query)` / `post(path, body)` / `request(method, path, body, params)` | 原始请求；JSON 解码后返回，非 JSON（头像、zip、Markdown 下载）返回 `bytes` |
| `login` / `logout` / `me` / `worlds` / `use_world` | 账号与当前世界 |
| `agents` / `agent(id)` / `run_status` / `start_run` / `stop_run` | 居民与运行 |
| `interventions` / `intervene(name, **kwargs)` / `wait_intervention(id)` | 通用干预（1.1.6） |
| `run_job(path, body, poll=None)` / `wait_job(poll_path)` | 后台作业；失败抛 `JobFailed`，超时抛 `TimeoutError` |
| `events(tables=None)` | 事件流，产出 `(表名, 行)` |

错误按状态码抛异常：`AuthError`（401/403）、`NotFoundError`（404）、`ConflictError`（409）、`QuotaError`（429），其余为基类 `APIError`；都带 `status`、`message`（服务端的 `error`）与 `body`。

---

## 4. 鉴权 / 错误约定 / 调试

- **Dashboard (8766)**：以点开头的静态路径（`/.env`、`/.git/`）始终 404。设置环境变量 `GAWORLD_DASHBOARD_TOKEN` 后所有请求需令牌：脚本用 `Authorization: Bearer <token>`，浏览器打开一次 `/?token=<token>` 换取 HttpOnly + SameSite=Strict cookie；未设置则不鉴权（仅建议本机使用）。见 [SERVER_DEPLOYMENT](SERVER_DEPLOYMENT.md#访问控制对外暴露前必读)。
- **Twin (8767)**：必须 HTTPS；客户端用 `Authorization: Bearer <token>` 访问 `/api/twin/*`。
- **Agent Relay (8877)**：`agent_type=native` 直通；`agent_type=openclaw` 必须 `POST /auth/token` 录入 token 后，注册/发消息都校验。
- **External Environment**：内部子网使用即可。
- 开启账号（`python -m gaworld.accounts init`）后，Dashboard 还接受 `gaworld_session` cookie（`POST /api/auth/login` 设置）；每个操作需要的级别见 OpenAPI 里的 `x-gaworld-access`，令牌持有者始终是管理员。
- 错误格式统一：`{"error": "message"}`；Dashboard 各状态码（含 405 / 409 / 429）的含义见 1.1.0。5xx 表示后端异常（Dashboard 会把 traceback 打到服务端日志）。
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
