# 多用户：一个部署，多人各自的世界，部分世界开放共玩

日期：2026-10-01
状态：P0–P5 全部已实现
场景：课堂 / 工作坊——几十人短期同时在线，教师（管理员）能看全部，学生各做各的，
部分城市设为「开放」，多人同时进入同一座正在运行的城市，与 AI 居民和彼此互动。
**单机单人用法保持不变：没有账号库时，一切行为与今天相同。**

---

## 一、现状核查：今天的 GAWorld 是「一台服务器 = 一个人 = 一个世界」

| 事实 | 位置 | 多用户下的后果 |
|---|---|---|
| 鉴权只有一个全局令牌 `GAWORLD_DASHBOARD_TOKEN`，拿到即全权 | `apps/dashboard_server.py:2440` `_guard` | 无法区分谁是谁，无法分权 |
| 仿真运行状态是进程级单例 `RUN_STATE`，一次只能跑一个 | `dashboard_server.py:73`、`_start_simulation:1903` | 第二个人按「运行」得到 "already running" |
| 配置写回同一个 `dashboard_config.json`；`city use` 也写它 | `_save_config_patch:632`、`city/__main__.py:48` | A 切城市 / 改参数，B 的下一次运行跟着变 |
| 运行日志固定在 `output/dashboard/simulation_run.log` | `dashboard_server.py:51` | 日志互相覆盖 |
| 记忆、大五、社交、财务按 agent id 平铺在 `output/*` 下（AGENTS.md 已注明「属于正在运行的城市」） | `output/memory` 等 12+ 处 | 两个世界的 31 号居民写到同一个文件 |
| 静态文件从**仓库根**提供（只挡了点开头路径） | `dashboard_server.py:2420` 注释 | 任何登录者可直接 GET 别人的 `/output/...`、`/data/...` |
| 游戏 / 采访 / 研究的作业放在各自内存 `JobStore`，不带属主 | `apps/game_jobs.py:35` | 谁都能列出、读取别人的作业 |
| LLM 提供商与 key 全局唯一，无配额 | `llm/providers.py` | 一个人的大批量采访能耗尽全班额度 |

**已经存在、可以直接复用的三块：**

1. **按世界改写输出路径**——平行世界为每个世界生成一组 overrides（`memory_dir`、`state_output_dir`、
   `kernel.interventions_path`……共 15 个键），经 `GAWORLD_CONFIG_OVERRIDES` 交给子进程
   （`parallel/spec.py:241 world_overrides`、`parallel/runner.py:242`）。「每人的世界」就是这个机制的常驻版本。
2. **跨进程干预队列**——dashboard → 运行中的仿真，带文件锁、每 tick 排空、进入 `controller.intervention`
   审计表（`kernel/remote.py`、`apps/kernel_api.py`）。开放世界里「玩家的动作」走这条通道，不需要新的实时引擎。
3. **事件流 + 席位**——`/api/events/stream` 已把 Recorder 每一行推成 SSE；严肃游戏已有「人类席位 + 席位链接」
   （`research/serious_game.py` 的 `seat_by_token`）。开放世界的「广播」和「认领居民」都是它们的泛化。

---

## 二、核心概念

```
User ──(member of)──▶ World ──(built from)──▶ City bundle (data/cities/<slug>)
                       │
                       ├─ visibility: private | class | open
                       ├─ root: output/worlds/<world_id>/   ← 所有运行产物
                       ├─ config.json                       ← 该世界的配置叠加层
                       └─ members: {user_id: owner | player | observer}
```

- **User**：`admin`（教师）或 `member`（学生）。全局角色只有这两种；另有一个可授予的权限位
  `can_create_city`（见第八节第 1 条）。
- **World**：一座城市 bundle + 一棵独立的输出树 + 一份配置叠加层 + 至多一个运行中的仿真进程。
  今天的单人模式等价于一个隐式的 `default` 世界，根目录就是 `output/`，配置就是 `dashboard_config.json`。
- **可见性**
  - `private`：只有 owner（和 admin）能看、能操作。默认值。
  - `class`：所有成员只读（看地图、轨迹、采访结果），不能运行、不能改。用于教师发布示范世界。
  - `open`：任何成员可以 **加入**；加入后成为 `player`，可认领一位居民并在运行中行动。
- **世界内角色**：`owner`（启停、改配置、发事件、踢人）> `player`（认领居民、行动、聊天）> `observer`（只看）。
  admin 在任何世界都等价于 owner。

**城市 bundle 与世界分离**：`data/cities/<slug>` 仍是共享的「模板」。创建世界时把 bundle 的
`agents.csv` / `profiles.md` 复制进世界目录（copy-on-write），Agent Studio 在世界里改居民只改副本——
这同时解决了 AGENTS.md 里写的「跨城编辑会写到别人身上」的问题。bundle 本身只有它的创建者和 admin 能改
（建城人记在账号库的 `city_owners` 表，不改 bundle 格式；没有记录的城市视为 admin 所有）。

---

## 三、账号与登录（课堂规模，够用即可）

- **存储**：`output/accounts/accounts.sqlite`（标准库 `sqlite3`，零新依赖）。表：`users`、`sessions`、
  `invites`、`worlds`、`memberships`、`usage`、`audit`。
- **开户方式：邀请码**。教师在控制台批量生成 N 个一次性邀请码（可附班级标签、过期时间、配额模板、
  是否授予 `can_create_city`），学生打开 `/join?code=…` 填昵称并**必须设置密码**即完成注册；之后用昵称 + 密码登录。
  不做公网自助注册。
- **会话**：登录成功写 `gaworld_session`（随机 32 字节，库里只存哈希），`HttpOnly; SameSite=Strict`，
  沿用现有 `_guard` 的 cookie / Bearer 两条路径；脚本继续用 `GAWORLD_DASHBOARD_TOKEN`（个人 API token 留待以后）。
- **向后兼容**：`GAWORLD_DASHBOARD_TOKEN` 继续有效，持有者视为 admin（用于引导第一个管理员和运维脚本）。
- **开关**：账号库不存在 ⇒ 单人模式，`_guard` 行为与今天逐字相同。`python -m gaworld.accounts init` 创建库和首个 admin。

---

## 四、世界隔离：把「当前世界」变成请求上下文

### 4.1 请求 → 世界（已实现）

当前世界是一个 cookie（`gaworld_world`），而不是 URL 前缀或请求头：控制台的 fetch、iframe、SSE 和 trace 静态文件
都会自动带上它，几十个面板无需改动。cookie 只是"意愿"——`_guard` 每个请求都重新校验可见性，看不到就退回共享默认世界。
解析结果放进 `contextvars.ContextVar`，`_effective_config()` 变为：

`defaults ← dashboard_config.json（全局，管理员） ← 世界 config.json ← 环境 ← 城市 ← 世界路径 ← 环境`

全局文件仍是底座（模型设置等由老师统一配置），世界只覆盖自己改过的键；路径最后由世界钉死。
`POST /api/config` 在世界里写世界的 `config.json`，且不允许改 `city`（居民是建世界时从该城市复制的）。
直接用模块常量的路径改成了按世界解析的函数（`_profile_path()`、`_state_csv_path()`、`_records_dir()`、`_run_log_path()` 等），
常量本身保留为默认世界的值，原有测试的 monkeypatch 不受影响。

**一个踩到的坑**：`python -m gaworld.apps.dashboard_server` 会把这个文件作为 `__main__` 再加载一份，
而各 `*_api.py` 导入的是正式模块——两份各有一套当前世界、运行表和队列。现在 `-m` 入口改为委托正式模块启动，
并有回归测试（`ModuleEntryPointTest`）。

### 4.2 路径映射（已实现）

没有另起一张表：城市运行早已有 `gaworld/city/config.py:RUN_PATHS`（16 个运行时路径），拆出
`run_root_overrides(base)` 后世界直接复用，另补两项城市运行仍共享的：Recorder（`records.output_dir`）和干预队列
（`kernel.interventions_path`）。世界目录 `output/worlds/<id>/` = `config.json` + `seed/`（居民 CSV / 人物志副本，
copy-on-write）+ 全部运行产物。平行世界的 `world_overrides` 没有并入（它是子集，改动风险大于收益），留作后续。

### 4.3 运行管理（已实现）

默认世界仍用 `RUN_STATE`；其他世界在 `WORLD_RUNS[world_id]`，日志写 `<world root>/run.log`，仿真子进程以
`GAWORLD_CONFIG_OVERRIDES` = 世界配置 + 世界路径启动（与面板看到的叠加顺序一致，仿真代码零改动）。
两道闸存在账号库 `settings` 表，`POST /api/worlds/settings`（管理员）即时生效：

| 限制 | 键 | 默认 |
|---|---|---|
| 全服同时运行的仿真 | `max_concurrent_runs` | 4 |
| 每个用户同时运行（管理员不受限） | `max_runs_per_user` | 1 |

超出时进入 FIFO 队列（队首优先；只因属主自己的上限被挡的条目不阻塞后面的人），面板显示「排队中（第 k 位）」，
按「停止」可取消排队。排队和定时运行都保存了请求上下文的副本，到点时在原来的世界里启动。

### 4.4 静态文件守卫（必须先做）

在 `_guard` 里对 `/output/worlds/<id>/…` 校验成员资格，对 `/output/` 其余路径和 `/data/` 只允许 admin
（学生的数据都在自己的世界目录里，经 API 读取）。`/site/`、`/docs/` 照旧放行。

### 4.5 结果带属主（已实现）

`gaworld/accounts/ownership.py`：创建时盖章（`owner_id` / `owner`），列表、读取、删除只对创建者和管理员开放；
没有成员属主的记录（账号开启前的旧数据、运维令牌建的、只有管理员能建的研究）只给管理员看。单人模式一切照旧。
各存储一律"创建时盖章、读写前检查"，没有迁移目录：

| 结果 | 位置 | 属主记在 |
|---|---|---|
| 灾难 / 谣言 / 公投 / 严肃游戏 / 政策仿真的作业 | 内存 `JobStore` | 作业记录 |
| 灾难 / 谣言 / 公投的对局存档（2026-10-03） | `output/games/<kind>/` | 存档 JSON 的 `owner_id` / `owner`；没有读取接口，只给 Bench Track B 读 |
| 谁是真人的房间（2026-10-04） | 内存；揭晓后存档到 `output/games/whois/` | 房间记录（房主）；**座位链接**能让持有者（须是能写 `/api/games/` 的成员）打开并操作那个座位，收轮 / 揭晓只有房主；存档同上，只给 Bench Track D 读 |
| 采访会话 | `output/interviews/<id>/session.json` | 会话 JSON（续问别人的会话被拒） |
| 研究方案；研究（study） | `output/research/` | 方案 JSON；研究只有管理员能建，故只给管理员看 |
| 严肃游戏的设计与对局 | `output/research/serious_games/` | JSON；**席位链接**仍能让持有者打开并操作那个席位 |
| 政策仿真 | `output/research/policy/` | JSON |
| 人物蒸馏 | `output/personas/<slug>/` | 旁边的 `owner.json`；同名画像不能覆盖别人的 |
| 劝说、猜心、竞技场、对决 | 内存 | 会话/回合/作业记录；竞技场的淘汰名单按人分开 |

后台线程用 `ownership.spawn` 启动，继承发起请求时的上下文（用户、世界）——新线程默认是空上下文。
这些模块的删除接口改为成员级、由 handler 校验属主。

---

## 五、开放世界：多人进入同一座城市（已实现）

### 5.1 进入与认领

世界属主把可见性设为 `open`；任何登录用户在顶栏切换到这个世界，打开「多人共玩」页签（`site/dashboard/play.html`）
即可认领一位居民。属主和管理员在自己的任何世界里也能玩。没有单独的「加入」或成员表——认领就是加入。

认领是 **2 分钟租约**，页面每 30 秒续一次，关闭页面时立刻释放（`sendBeacon`）；断线两分钟后居民自动交还给模型。
一位居民同一时刻只属于一个玩家，一个玩家在一个世界里同时只扮演一位（认领新的会放下旧的）。
租约放在 dashboard 进程内存（`apps/play_api.py`），因为它本来就是转瞬即逝的状态。

「以新居民身份入城」**没有做**：运行中造人（`add_agent`）内核尚未实现（见 `docs/PLUGIN_AUTHORING.md`）。

### 5.2 行动：走现成的干预队列

`gaworld/multiplayer/plugin.py`（内置插件，排在所有 `action.selected` 过滤器之后，玩家有最终决定权）注册四个干预：

| 干预 | 参数 | 作用（下一个 tick 生效） |
|---|---|---|
| `player_claim` | `agent_id, player, until` | 记下谁在扮演、到期时间；每次续租都会再发一次，所以玩家先进、仿真后启动也能在 30 秒内同步 |
| `player_release` | `agent_id` | 交还给模型 |
| `player_act` | `agent_id, text` | 写进该居民感知（`perception.sections`：「你此刻的决定」），规划与移动据此展开；并成为这一步的动作（`action.selected`） |
| `player_say` | `agent_id, target_id, text` | 对方下一次感知里出现「X 对你说：…」，说话者也记得自己说过 |

一个意图只驱动**一次真正的动作选择**：居民还在路上（这一步的动作就是移动）时意图保留、继续出现在感知里，到达后才执行——
这是全仿真测试抓到的问题，单元测试看不出来。HTTP 侧（`/api/play/act|say`）要求调用者持有该居民的租约，且仿真在运行。

**没有被玩家操作的居民就是普通 AI 居民**，玩家不在线不会让世界停下来。

### 5.3 节奏

默认异步。世界属主可在「管理世界」里设「每个 tick 等玩家（秒）」（`multiplayer.wait_for_players_seconds`，0–300）：
tick 开始时若有在线玩家还没出手，最多等这么久，等待中自己去取干预队列。运行中修改经 `update_config` 立即下发。

### 5.4 广播与在场

行动和说话由插件写进 `multiplayer.act` / `multiplayer.say` 记录表；认领、交还、租约到期由 dashboard 直接追加到世界的
`records/multiplayer.presence.jsonl`——仿真没在跑时也能看到谁在线。页面通过 `/api/events/stream`（已按世界解析）实时显示。

---

## 六、配额与审计（已实现）

- **用量**：`call_llm` 每次调用（含失败）向账号库旁的 `usage.jsonl` 追加一行（时间、用户、世界、任务）。
  单位是"调用次数"——各提供商的 token 回报不统一，次数也更便于老师估算。dashboard 内的调用从请求上下文取用户；
  仿真与采访子进程经环境变量 `GAWORLD_USER_ID` / `GAWORLD_WORLD_ID` 继承。短行 `O_APPEND` 写入是原子的，多进程无需加锁；
  dashboard 增量读取并按"日期 × 用户"计数。管理员看 `GET /api/auth/usage`。
- **软配额**：`daily_llm_calls_per_user`（默认 0 = 不限，`POST /api/worlds/settings` 调整）。用完后只拒绝**会启动模型调用**的请求
  （启动 / 定时仿真、采访、研究分析与读论文、蒸馏、各游戏、严肃游戏设计与开局、政策仿真、建城类），返回 429；
  在跑的任务不中断，改配置、停止、删除不受影响；管理员不受限。清单在 `accounts/policy.py:QUOTA_GATED_*`。
- **审计**：所有 POST 与账号、世界、上限的变更都写 `audit` 表（P1/P2 已实现）。

---

## 七、教师控制台（已实现）

控制台「系统」组里的「教师控制台」页签（`site/dashboard/admin.html`），只对管理员显示；页面用到的每个接口在服务端再校验角色。
一页六块：

- **班级上限**：全服 / 每人同时运行的仿真数、每人每日模型调用额度，保存即生效。
- **邀请码**：按数量、班级标签、有效天数、是否可建城批量生成，直接给出 `/join?code=…` 链接（只显示一次）；
  未使用的可作废，用过的保留为谁加入的记录。
- **名单**：在线状态（两分钟内有请求，记在内存里，重启后清空）、今日 / 累计模型调用、建城权限开关、重置密码（给出一次性链接）。
- **世界**：所有世界的属主、城市、可见性、运行 / 排队、今日调用；可代为停止；导出该世界的多人共玩记录（Markdown）。
- **广播事件**：勾选世界（含共享世界），给其中**每一位居民**同一个生活事件。写进各世界自己的生活事件队列、立即生效：
  运行中的世界下一个 tick 触发，没在运行的下次启动时触发。复用 `gaworld.events.life`，不需要新的仿真机制。
- **审计**：最近 50 条。

---

## 八、已确认的决定（2026-10-01）

1. **只有有权限的用户可以建立城市。** 新增权限位 `can_create_city`（`users` 表一列）：admin 恒有；member 默认无，
   由 admin 在控制台逐人授予或随邀请码模板授予。`/api/city/create`、`add-agents`、`add-agent`、`migrate`、`delete`
   以及 CLI `python -m gaworld.city create …` 经 dashboard 调用时都检查它。无权限的用户只能基于已有城市开世界。
2. **强制密码。** 邀请码只用于首次注册，注册时必须设密码（最短 8 位，`hashlib.scrypt` 加盐存储，标准库即可）；
   之后一律「昵称 + 密码」登录。admin 可重置某人密码（生成一次性重置码，不显示明文）。
3. **开放世界默认按自己的速度跑，可设置。** `multiplayer.wait_for_players_seconds` 默认 `0`（异步），
   世界 owner 可在该世界的配置里改成 N 秒（见 5.3）。
4. **全服同时运行的仿真个数可设置。** `accounts.max_concurrent_runs`（默认 4）与 `accounts.max_runs_per_user`
   （默认 1）由 admin 在控制台修改，即时生效，不需要重启；调小时已在运行的不受影响，只影响队列出队。

---

## 九、分阶段落地

| 阶段 | 内容 | 验证门 |
|---|---|---|
| P0 安全底座（**已实现**） | 静态文件改为白名单：只放行 `/site/`、`/docs/`、`/video/public/`、`/output/population/`、`/output/**/visualization/**`、文档面板列出的三份根目录文档与页面别名，其余 404（`dashboard_server._static_path_allowed`）。原计划的「`POST /api/config`、`city use` 限 admin」需要身份，移入 P1 | `tests/test_dashboard_auth.py`：源码、`dashboard_config.json`、`/data/...`、`/output/memory/...` 得 404；控制台、回放 trace 仍 200 |
| P1 账号（**已实现**） | `gaworld/accounts/`（store / policy / CLI）+ `apps/accounts_api.py`（`/api/auth/*`）+ `site/auth/`（`/login` `/join` `/reset`）；控制台右上角显示当前用户与「退出登录」。**P2 之前学生写操作走白名单**（`accounts/policy.py`）：采访、游戏、研究分析、人物蒸馏可用；建城类需 `can_create_city` 且只能改自己建的城、不能 `force` 覆盖；全局配置 / 模型设置 / 启停仿真 / 切换城市 / 编辑居民 / 一切 `delete` 只限 admin；所有 POST 写审计 | `tests/test_accounts.py`（store、policy 表、建城人检查、HTTP 全流程、CLI），已入 core 套件 |
| P2 世界隔离（**已实现**） | `gaworld/worlds/`（路径、种子复制）+ 账号库 `worlds` / `settings` 表 + `apps/worlds_api.py`（`/api/worlds`：列出 / 新建 / 切换 / 可见性 / 删除 / 运行上限）；`_effective_config` 与路径函数按请求的世界解析；按世界的运行表 + 可配置闸门 + FIFO 队列；控制台顶栏世界切换器与管理对话框；属主在自己的世界里可改配置、启停/定时仿真、编辑居民（档案/状态/目标/记忆/财务/关系/大五人格——大五人格表随世界复制到 `seed/`）、发干预；生命事件仍读全局文件，保持仅管理员 | `tests/test_worlds.py`：路径、策略、配置分层与写入隔离、私有世界对他人不可见（API/静态文件）、闸门 + 排队 + 出队后在正确世界启动、删除、`-m` 入口不分裂状态 |
| P3 结果属主与配额（**已实现**） | `accounts/ownership.py`（盖章 / 可见性 / 带上下文的后台线程）接入 4.5 表中全部存储；`accounts/usage.py`（调用日志、按日按人计数、子进程继承）+ `call_llm` 钩子 + 软配额（429）+ `GET /api/auth/usage` | `tests/test_ownership.py`：规则、后台线程继承用户、每个存储的跨用户隔离、席位链接、画像不可覆盖、竞技场分账、用量计数与子进程继承、失败调用也计数、配额只拦模型工作 |
| P4 开放世界（**已实现**） | `gaworld/multiplayer/`（四个干预 + 感知/动作/等待钩子，内置插件）+ `apps/play_api.py`（`/api/play`：租约认领、行动、说话、在场记录）+ 「多人共玩」页签 + 世界对话框里的等待秒数 | `tests/test_multiplayer.py`：插件规则（意图一次、路上保留、说话一次、租约过期、等待只为未出手的玩家）、HTTP 全流程（私有不可进、一人一位、未运行拒绝、入队内容、在场记录、断线到期），以及**真实主循环**里玩家意图进入感知并成为动作 |
| P5 教师控制台（**已实现**） | `site/dashboard/admin.html`（仅管理员可见的页签）；补充接口：作废邀请码、名单在线状态、世界的排队与今日调用、代为停止、`POST /api/worlds/broadcast`、`GET /api/worlds/<id>/trail` | `tests/test_teacher_console.py`：作废规则、在线时间、世界列表与停止权限、广播写入各世界（含共享世界）且仅管理员、导出与可见性；浏览器验证全页 |

每阶段都可单独交付、单独回滚；P0 不依赖身份，单人部署同样受益（此前持令牌者可直接下载源码、`dashboard_config.json` 和全部 `output/`）。

## 十、风险

- **`dashboard_server.py` 有 3000+ 行、大量模块级全局**：P2 是本提案里最大的改动。缓解：先用 grep 列出
  所有直接拼 `output/` 的位置作为清单，逐个改，并以「全局 `output/` 无新文件」测试兜底。
- **单 LLM 提供商的速率限制**是课堂的真实瓶颈，并发闸门只能排队，不能变出额度；建议配合 P3 的配额，
  并在课前用 `trackb_*` 那类压测估算可承受的并发。
- **插件新增输出目录忘记登记到 `world_paths`**：会悄悄写回全局目录。由 P2 的兜底测试抓住。
- **开放世界里玩家输入进入居民记忆**：可能出现不当内容污染其他人的世界。owner 可开启「玩家动作先经一次审核调用」，默认关闭。

## 十一、不在本提案范围

- 公网自助注册、计费、OAuth/SSO；
- 跨机器分布式运行仿真（今天的单机多进程足够课堂规模）；
- 多个玩家同时编辑同一个城市 bundle（bundle 只有一个属主，协作通过「复制为我的城市」）。
