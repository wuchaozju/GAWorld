# Repository Guidelines

## Project Structure & Module Organization

```
GAWorld/
├── gaworld/                  # 核心包（所有功能的正式实现）
│   ├── kernel/               # 微内核（clock, bus, registry, controller, recorder, context, interventions）
│   ├── plugins/              # 内置插件装配点（builtin_plugins()，9 个插件）
│   ├── accounts/             # 多用户账号（store/policy/CLI：邀请码注册、强制密码、会话、角色、建城权限、审计；库不存在即单人模式）
│   ├── worlds/               # 每人的世界（output/worlds/<id>/：config.json + 居民副本 + 全部运行产物；路径复用 city.config.RUN_PATHS）
│   ├── apps/                 # 服务器与可视化（dashboard 后端含 Agent Studio API, visualizer, …）
│   ├── behavior/             # 动态行为模块（dynamic.py + plugin.py）
│   ├── cognition/            # 人类真实感模块（realism.py）
│   ├── core/                 # Agent 基础与并发执行（agent.py, runner.py）
│   ├── distributed/          # 分布式通信（comm.py：中继客户端）
│   ├── cluster/              # 分布式世界（nodes/hub/bundle/node/plugin：一个世界的居民分到多台机器，枢纽 = dashboard）
│   ├── economy/              # 经济模块（finance.py + plugin.py）
│   ├── public_sector/        # 公共部门（policy/plugin：政府与政策 → 改写经济规则 + 转移支付 + 居民简报；换届；默认关）
│   ├── env/                  # 环境系统（system.py）
│   ├── events/               # 生命事件（life.py + plugin.py）
│   ├── family/               # 家庭与户（assign/overrides/ties/duties/finance/events + plugin.py）
│   ├── infosources/          # 外部信息源（registry/channels/feed/diet/search + plugin.py：新闻/社交/专业站 → 每人信息食谱）
│   ├── interview/            # 群体采访（schema/roster/prompt/runner/aggregate/report/store/session；__main__ 为按城市的子进程）
│   ├── io/                   # IO 工具（avatar.py, http_guard.py, web_scrape.py）
│   ├── llm/                  # LLM 提供商（providers.py）
│   ├── memory/               # 记忆系统（store, experience, consolidation, decay, …）
│   ├── multiplayer/          # 多人共玩插件（玩家认领居民：player_claim/act/say/release 干预 → 感知 + 动作；可选每 tick 等玩家）
│   ├── moltbook/             # Moltbook 集成（accounts/client/log + plugin：居民上智能体社交网络发帖，行动逐条记录）
│   ├── persona/              # 真人蒸馏（research/distill/render/store：姓名或网址 → 居民 + 思维框架）
│   ├── personality/          # 大五人格 OCEAN 特质（traits/anchors + plugin.py，默认开启）
│   ├── policy/               # 干预策略（intervention.py + plugin.py）
│   ├── settings/             # 配置（CONFIG, defaults, overrides）
│   ├── skills/               # 技能系统（schemas, registry, consolidation + plugin.py）
│   ├── sim/                  # 仿真逻辑（pipeline.py 认知管线, _action, _cognition, …）
│   ├── social/               # 社交网络（network.py）
│   ├── travel/               # 离开本市（destination/trigger/itinerary + plugin.py：出差/探亲/旅行，默认关）
│   ├── work/                 # 工作模块（router, queue, market, adapters + plugin.py）
│   ├── world/                # 城市地图（city_map.py + plugin.py：物理感知/空间偏好/道路拥堵；away.py 定义「异地」）
│   ├── hooks.py              # 旧版生命周期钩子（HookBus，兼容层；新代码用 kernel/bus.py）
│   ├── client.py             # Dashboard HTTP API 的 Python 客户端（按 OpenAPI operationId 调用任意接口）
│   ├── interests.py          # 兴趣与成长档案（+ interests_plugin.py）
│   └── logging_setup.py      # 日志配置
├── generative_city_sim.py    # CLI 入口（run / reset / interview）——仅管线骨架，子系统逻辑在插件里
├── legacy/                   # 旧版 flat 模块（已弃用，不参与构建）
├── scripts/                  # 辅助脚本（generate_citymap, …）
├── site/                     # 前端（dashboard 控制台 + Agent Studio, simviz, citymap）
├── tests/                    # 测试套件（pytest）
├── data/                     # 数据资产（agents CSV, profiles MD, citymap MD）
└── output/                   # 生成产物（日志、记忆、图表）
```

**规则：新代码只写进 `gaworld/` 包，不添加新的根目录模块。**
旧 flat 模块的正式位置见 `legacy/README.md`。

**规则：新子系统写成插件，不在 `generative_city_sim.py` 里加内联逻辑。** 这个文件和 `run_simulation` 有只减不增的行数上限（`tests/test_line_budget.py`，上限在 `tests/line_budget.json`）。
写一个 `gaworld.kernel.Plugin` 子类，经 `gaworld/plugins/builtin_plugins()`
（内置）或 `CONFIG["plugins"]` / entry point（第三方）装配；扩展点目录见
`docs/PLUGIN_AUTHORING.md`。

## Build, Test, and Development Commands
- Install deps: `pip install -r requirements.txt`
- Run simulation: `python generative_city_sim.py run`
- Long-horizon fast-forward (one daily brief per agent per day, skips the intra-day tick loop; pairs with a large `--sim-days`): `python generative_city_sim.py run --sim-days 600 --fast-forward`
- Multi-year runs at month/year granularity (one period brief per agent per month/year): `python generative_city_sim.py run --sim-years 10` / `--sim-months 24` / `--time-unit month`
- Reset simulation (clear caches/logs and restart day count): `python generative_city_sim.py reset`
- Interview an agent:
  - `python generative_city_sim.py interview --agent-id 31 --question "Question"`
  - `python generative_city_sim.py interview --agent-id 31 --questions-file questions.txt`
- Accounts for a shared deployment (多用户, opt-in): `python -m gaworld.accounts init --admin <昵称>` creates
  `output/accounts/accounts.sqlite`; from then on the console requires sign-in (`/login`, `/join?code=…`).
  Invite codes: `python -m gaworld.accounts invite --count 30 --label <班级>`. What members may call is
  `gaworld/accounts/policy.py`; `GAWORLD_DASHBOARD_TOKEN` stays an admin. Each user works in their own world
  (`/api/worlds`, the console's world switcher): a copy of a city's residents plus every run output under
  `output/worlds/<id>/`; the active world is the `gaworld_world` cookie and every path the dashboard resolves goes
  through it (`gaworld/apps/world_paths.py`: `effective_config()`, `state_csv_path()`, `records_dir()`, …) — new
  dashboard code must not read `output/` through a module constant. Runs, their queue and limits live in
  `gaworld/apps/runs.py`; a delegate API module is one line in `gaworld/apps/routes.py`, not a handler branch, and every new route
  gets an entry in `gaworld/apps/openapi.py` (`tests/test_openapi.py` fails on an undocumented route; the
  document also drives the 405 answers and `gaworld.client.call()`). Run limits live in the account DB. Anything a member creates is stamped
  with `gaworld.accounts.ownership.stamp()` and filtered with `visible()` / `owned()`; background jobs must start
  through `ownership.spawn()` so they keep the asking user and world. Model calls are counted per user
  (`gaworld.accounts.usage`, hooked into `call_llm`) for a soft daily quota. In an `open` world people play
  residents (`/api/play`, the 多人共玩 tab): a two-minute lease per resident, actions sent through the world's
  intervention queue to `gaworld/multiplayer/plugin.py`. Admins get a 教师控制台 tab (`site/dashboard/admin.html`):
  invites, roster and usage, limits, every world (stop, export the play log), and a class-wide life-event
  broadcast (`POST /api/worlds/broadcast`). Docs in `docs/SERVER_DEPLOYMENT.md`,
  design in `docs/proposals/2026-10-01-multi-user.md`
- Distributed world (分布式世界): a world's owner assigns residents to nodes in 管理世界 → 分布式节点; another
  machine runs its share with `python -m gaworld.cluster join <hub> --token <world>.<node>.<secret>`. The dashboard
  is the hub (`/api/cluster/*`: node tokens, the world's relay, a per-node intervention outbox, tick sync, record
  upload); `play_api` routes a player's action to the machine running the resident. Code in `gaworld/cluster/` +
  `gaworld/apps/cluster_api.py`; phones join through `/play/<world_id>`. Design in
  `docs/proposals/2026-10-02-distributed-worlds.md`
- Interview a crowd (群体采访): the dashboard panel at `/site/dashboard/survey.html`, backed by
  `/api/interview/*`. One round is split into one child process per city:
  - `python -m gaworld.interview --spec round.json --out answers.json`
  - Sessions land in `output/interviews/<session_id>/`; docs in `docs/GROUP_INTERVIEW_TUTORIAL.md`
- Play a round against residents (游戏场): the dashboard hub at `/site/dashboard/games.html`.
  The arena keeps its own `/api/arena/*`; every other game hangs off `/api/games/<game>/*`.
  A one-page overview (按"问题形状"分家族、按研究问题反查) lives at
  `docs/GAMES_OVERVIEW.md`; how each game runs end-to-end is in `docs/PLAYGROUND_TUTORIAL.md`.
  Games that need a background job share `gaworld/apps/game_jobs.py` (one `JobStore` each).
  Games keep their state in memory and never write to a city bundle.
  当前 14 个游戏,按玩法家族分四组:
  - 一对一(对一个居民):
    - persuasion — 提问 + 聊天 + 复问;裁判模型对比首尾两份答案是否真改主意。`gaworld/apps/games_api.py`
    - read the room (`/api/games/guess/*`) — 一人一道两难,直接猜;复问还能测稳定性。`gaworld/apps/guess_api.py`
    - jury (`/api/games/jury/*`) — 3–5 名陪审员三轮讨论 + 匿名投票 + 量刑,裁决从票里出、不是裁判给的。`gaworld/apps/jury_api.py`
  - 一群人同时面对一件事:
    - disaster mode — 一批居民过同一灾难 stage by stage;每人一个结构化 JSON
      (action / panic / help / quote),直方图不需要裁判。`gaworld/apps/disaster_api.py`
    - warzone (`/api/games/warzone/*`) — 仓库见底时每天一次全员提议 + 全员互投;
      死亡率、基尼系数、投票分歧率都是确定性代码算的。`gaworld/apps/warzone_api.py`
    - rumor spread — 一条传闻沿熟人关系网传;模型选 verb(转发 / 求证 / 辟谣 / 不管),
      图选收件人;跑完给传播树。`gaworld/apps/rumor_api.py`
    - referendum — 有利害的议案先私投再公开表决,可夹一段宣传语;跑完给民意的位移。`gaworld/apps/referendum_api.py`
    - news commentary (`/api/games/commentary/*`) — 一条新闻 + 1–12 位居民各自一句评论 + 立场 + 强度。`gaworld/apps/commentary_api.py`
  - 任务协作 / 创意:
    - team duel — 两队拿同一任务两条相反路子,评审蒙着队名按维度逐项打分;
      胜负按总分定,不是模型自己说的赢家。`gaworld/apps/duel_api.py`
    - novel writer (`/api/games/novel/*`) — 2–6 位居民当主角,按他们档案写一本带大纲的小说。`gaworld/apps/novel_api.py`
  - 长期同居 / 多人(长会话 + 真人参与):
    - roommate mode (`/api/games/roommate/*`) — 2–6 位居民合租一间公寓,
      唯一的"长会话游戏",前端按 tick 反复拉。`gaworld/apps/roommate_api.py`
    - who's human (`/api/games/whois/*`) — 居民和真人同坐一个匿名群聊,
      **唯一一个真人入场的游戏**;真人凭座位链接入座。`gaworld/apps/whois_api.py`
    - timeslip (`/api/games/timeslip/*`) — 把 2–8 位居民扔进一个真实朝代的关键时刻,
      每幕写一句古人口吻 + 一句现代内心独白;三轴评分(era_fit / stability / inner_conflict)
      是确定性代码算的、不是裁判给的。`gaworld/apps/timeslip_api.py`
- Build a resident from a real person (真人蒸馏): Agent Studio → **＋ 从真人蒸馏**, backed by
  `/api/persona/*`. A name or a URL is searched, read and distilled into a sourced portrait
  (identity + state + Big Five + mental models / heuristics / expression DNA / limits):
  - Portraits land in `output/personas/<slug>/` (`persona.json`, `research.md`, `SKILL.md`)
  - Distilling writes only there; **deploying** is the separate, reviewed step that writes the
    seed CSV and the profile Markdown. Docs in `docs/PERSONA_DISTILL_TUTORIAL.md`
- Turn a research idea or a paper into a study (研究工作台): `/site/dashboard/research.html`,
  backed by `/api/research/*`. A paper is read first (`/digest`, editable), then planned against
  `docs/FEATURES.md` with 2–3 alternative designs (`/analyze`); a chosen design compiles into a
  pre-registered protocol, runs as parallel worlds per seed, and is scored by code:
  - Plans land in `output/research/<id>.json`; studies in `output/research/studies/<id>/`
  - 严肃游戏 tab: a description becomes a turn-based role-play game (`/api/research/games/*`);
    each role is seated by a resident agent or a human (via a seat link), rounds are simultaneous,
    a facilitator call resolves each round and a debrief scores every role. Designs and sessions in
    `output/research/serious_games/`; `gaworld/research/serious_game.py` + `gaworld/apps/serious_game_api.py`
  - 政策仿真与优化 tab: pick a city, describe a policy (optionally a candidate); a seeded sample of
    residents reacts to each version in fixed-scale JSON, code aggregates and scores, one model call
    proposes modifications and a revised policy, which is re-simulated on the same residents — the
    highest composite score is the recommendation (`/api/research/policy/*`). Runs in
    `output/research/policy/`; `gaworld/research/policy_sim.py` + `gaworld/apps/policy_sim_api.py`
  - 社会调查/实验拟合度 tab (`research.html?tab=replication`): upload a paper that reports a survey or an experiment
    on real people; one model call extracts an editable spec (conditions with their stimuli, questions on their own
    scales, the human results with their sources — nothing unreported is estimated), the researcher corrects it,
    then a seeded sample of residents of the chosen size takes the same study (between-subjects or paired) and code
    compares: per-cell error on the item's range, human value inside the agents' 95% CI, treatment effects'
    direction and significance, a fidelity score (`/api/research/replication/*`). Runs in
    `output/research/replication/`; `gaworld/research/replication.py` + `gaworld/apps/replication_api.py`
  - 平行世界 · 反事实推断 tab (`research.html?tab=worlds`; the old `worlds.html` / `/console#worlds`
    redirect here): design 2–8 worlds by hand, run them (optionally under several `seeds`, one grouped
    experiment per seed), and read counterfactual estimates — paired per-resident ATE with bootstrap CI,
    sign-flip p, BH q, pre-event balance / DiD, placebo noise floor, onset order, heterogeneity, dose–response,
    replication across seeds, plus an optional one-call model reading (`POST /api/parallel-worlds/interpret`,
    `gaworld/parallel/interpret.py`: every finding is tied back to an estimates row and its verdict, cached per
    comparison world). Backed by `/api/parallel-worlds/*`; estimators in `gaworld/parallel/causal.py`
    (deterministic, no model calls); frontend `site/dashboard/worlds.js`. A study's verdicts also gate on
    each seed's paired test (`gaworld/research/evaluate.py`). Docs in `docs/PARALLEL_WORLDS_TUTORIAL.md` §13
  - Docs in `docs/RESEARCH_WORKBENCH_TUTORIAL.md`
- Generate a new city map (single, in-place):
  - `python scripts/generate_citymap.py --description "a small city with about 1000 residents, in east china"`
- Create a whole city from a place name (map + environment + agents, as a reusable bundle):
  - `python -m gaworld.city create "绍兴柯桥" --size 200` — geocodes the name, pulls the real
    OpenStreetMap road network, falls back to a procedural map when that is unavailable
  - `python -m gaworld.city create "柳溪村" --offline --scale tiny` — no network at all
  - `python -m gaworld.city add-agents <city> --size 200` / `add-agent <city> --name … --age …`
    / `migrate <city> --agent-id 31`
  - `python -m gaworld.city list` / `show <city>` / `use <city>` / `delete <city> --yes`
  - Cities live in `data/cities/<slug>/`; `use` writes `{"city": slug}` into
    `dashboard_config.json`, which repoints `map_path` / `csv_path` / `md_path`, the
    environment events and the background prompt at that bundle.
  - Residents of *any* city are readable without switching to it, straight from the
    bundle: `GET /api/city/agents?city=<slug>` / `GET /api/city/agent?city=<slug>&id=<n>`
    (`city` omitted = the default world). The 城市 panel lists them (its hand-off into
    Agent Studio is **read-only**). Agent Studio's city picker makes the picked city the
    running one and edits it: agent ids restart at 1 in every city, so Studio only ever
    edits the running city, and `world_paths.state_csv_path()` / `profile_path()` /
    `big5_csv_path()` follow a city selected after the server started. Docs in
    `docs/CITY_TUTORIAL.md`.

There is no build step beyond installing Python dependencies.

## Coding Style & Naming Conventions
- Python ≥ 3.11; follow standard PEP 8 conventions.
- Indentation: 4 spaces, no tabs.
- Naming: `snake_case` for functions/vars, `UpperCamelCase` for classes, constants in `ALL_CAPS`.
- Formatter / linter / type-checker are configured in `pyproject.toml`:
  - `ruff check .` and `ruff format --check .` (rules pinned to `E`/`F`/`W`/`I`/`UP`/`B`/`C4`/`SIM`/`PIE`/`RUF`).
    The repo carries an older backlog, so CI runs the ratchet instead:
    `python scripts/lint_ratchet.py --base origin/<target>` — a changed file may not gain findings,
    a new or already-formatted file must be formatted, and the repo totals may not rise above
    `scripts/lint_baseline.json` (`--update-baseline` after a cleanup). Run it locally with no
    arguments to check uncommitted work.
  - `black .` (line length 110).
  - `mypy gaworld` (strict typing on the new `gaworld/` tree, advisory elsewhere).
- All new code goes into `gaworld/` sub-packages. No new root-level modules.
- Import from `gaworld.*` directly; the `legacy/` shims are deprecated and excluded from the build.

## Testing Guidelines
- Tests live under `tests/` and use `pytest` discovery (`test_*.py`).
- Run locally: `pytest tests` (or `python -m unittest discover -s tests -p 'test_*.py'`).
- Two suites, designed in `docs/TEST_CASES.md`: `pytest --suite core` (~30 s smoke of the main simulation path, listed in `tests/suites/core.txt`) and `pytest --suite full` (everything). Keep the core suite green before committing; a stale entry in `core.txt` fails the run.
- New code MUST be covered by tests in the same PR; coverage is reported by `pytest-cov` in CI.
- Prefer lightweight, reproducible tests: mock LLM calls (`call_llm`) and avoid real network IO.
- If a change alters what a run with **default** config produces so that earlier runs are no longer comparable, append an `Epoch` to `gaworld/core/comparability.py` (never renumber old ones). Runs, compare-event dirs and parallel-worlds experiments are stamped with it, and replicate pooling, study verdicts and the bench gate refuse to combine across epochs. Opt-in switches that default off don't need one.

## Commit & Pull Request Guidelines
- Existing history uses short, lowercase summary messages (e.g., `updated`, `sync`, `requirement`). Keep commits concise and imperative.
- PRs (if used) should include: scope summary, config changes, and any new runtime outputs avoided or ignored.

## Security & Configuration Tips
- Do not hardcode API keys in `config.py`; use environment variables (e.g., `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`).
- Keep generated files out of commits (`output/` content should usually remain local).


<claude-mem-context>
# Memory Context

# [GAWorld] recent context, 2026-06-22 2:23am GMT+8

Legend: 🎯session 🔴bugfix 🟣feature 🔄refactor ✅change 🔵discovery ⚖️decision 🚨security_alert 🔐security_note
Format: ID TIME TYPE TITLE
Fetch details: get_observations([IDs]) | Search: mem-search skill

Stats: 50 obs (22,251t read) | 0t work

### Jun 6, 2026
S258 总结已运行的GAWorld仿真实验，生成结构化markdown报告（研究问题、设计、运行、结果、发现），供后续分析与撰写参考 (Jun 6 at 12:52 AM)
S260 Continue execution of two unrun experiments (EXP-EMO-001 emotion contagion, EXP-VAL-001 ABM validation) per user request "继续完成两个尚未运行的实验" (Jun 6 at 12:55 AM)
S261 完成两个未运行的实验 (EXP-EMO-001 情绪传染 + EXP-VAL-001 ABM验证) (Jun 6 at 1:25 AM)
861 1:26a 🟣 EXP-EMO-001 and EXP-VAL-001 launched as background tasks (3-day smoke tests)
863 1:34a 🔵 REFERENCE_BENCHMARKS is a module-level dict in exp_abm_validation.py
864 " 🔵 EXP-EMO-001 control background task bmz7pqjrl still running, no output after 12s
865 " 🔵 EXP-EMO-001 seed_agents target out-of-range agent IDs in TREATMENTS config
866 1:38a 🔴 EXP-EMO-001 control background task hung for 5+ minutes with empty output
867 1:39a 🔵 Both experiments are producing real output despite empty stdout
868 " 🔵 State CSV output is gated behind per-step flush, not directory creation
870 " 🔵 Primary session has path bug: looking for timeline.jsonl in logs/ but it lives in environment/
871 " 🔴 EXP-VAL-001 failed: LLM API returned HTTP 500 with "new_sensitive" content filter
872 " 🔵 EXP-VAL-001 silently degrades on missing economy_module and generate_agent_rag_seed
873 " 🔵 LLM provider configuration: only 1 provider, no fallback chain
869 1:40a 🔵 Per-agent logs exist but environment/timeline.jsonl is empty
874 1:50a 🔴 Primary session fixed state-CSV schema mismatch in both experiment analyzers
875 " 🔵 Transport mode data source: environment/agent_*.log not state/agent_state_history.csv
876 1:51a 🔵 Primary session confirmed 17 prior experiments produced state/agent_state_history.csv files
877 " 🔴 Primary session discovered ledger uses engel_coefficient (alternative spelling), not engels_coefficient
879 " 🔴 Emotion contagion simulation stalled at Day 1 08:32 for 10+ minutes
878 1:52a 🔵 Emotion contagion simulation is alive: Day 1 timeline has 4 events with rich detail
880 2:01a ⚖️ Primary session killed the stalled emotion contagion run after 28:49
881 " 🔵 hangzhou_agents_state_init.csv uses WIDE format with BOM; runtime state CSV is LONG format
882 " ⚖️ Primary session pivots to EXP-VAL-001 after killing EXP-EMO-001
883 2:03a 🟣 Primary session launched master run: all 4 EMO treatments + ABM validation in single task bzeah2mry
884 " 🔵 Cleanup script wipes prior partial results before relaunch
S263 继续等待 - 持续监控 bzeah2mry 后台仿真任务, 回应"进展如何"进度检查 (Jun 6 at 2:04 AM)
S264 持续监控 bzeah2mry 仿真任务, 多次轮询检查状态, 决定进入 20 分钟轮询模式 (ScheduleWakeup) (Jun 6 at 7:48 AM)
S262 进展如何 - 检查 EXP-EMO-001 (4 treatments) 和 EXP-VAL-001 的运行状态 (Jun 6 at 7:48 AM)
S265 持续监控 bzeah2mry, 诊断 SSL 重试循环导致仿真拖慢, 主会话向用户提出 4 个选项 (Jun 6 at 7:59 AM)
S267 用户决策"重试" — 主会话准备重跑实验, 复检 bzeah2mry 状态确认需要新启动 (Jun 6 at 8:00 AM)
885 9:09a 🔵 LLM API DNS resolution failure killed all experiment runs
S266 实验全面失败 — 所有 5 个仿真 (4 EMO + 1 ABM) 因 DNS 故障无法完成, 主会话向用户报告状态并提供重跑脚本 (Jun 6 at 9:09 AM)
886 " 🔵 All experiments produced zero state CSVs before DNS failure
887 10:39a 🔵 Network restored; cleanup triggered automatic directory recreation
888 " ✅ Parallel background tasks launched for retry with reduced days
889 10:40a ✅ 4 parallel Python processes running for EMO+ABM retry
891 " ✅ EMO control treatment advancing — Day 1 00:28 in 11 minutes wall-clock
892 " 🔵 Timeline writes throttled to ~hourly sim time, agent logs are per-action
890 " 🔵 LLM calls now succeeding — agent preferences being generated
893 10:50a ✅ Both experiments advancing — EMO at Day 1 08:32, ABM at 2 timeline entries
S268 用户"重试"决策后, 主会话成功启动两个并行 bgtask, EMO 推进到 Day 1 08:32, ABM 启动并产出 timeline 数据 (Jun 6 at 10:58 AM)
### Jun 16, 2026
908 11:48p 🔵 Presentations skill mandates artifact-tool JSX workflow
909 " 🔵 Brainstorming skill enforces hard-gate before implementation
910 " ✅ Created QA comeback scorecard for gaworld-project-intro deck
911 11:59p 🟣 User requested installation of GordenSun/GordenSuperPPTSkills
### Jun 17, 2026
912 12:27a 🔵 Codex skill-installer uses install-skill-from-github.py with auto/git/download methods
913 " 🔵 GAWorld repo working tree state: AGENTS.md and benchmark/report.md modified, outputs/ untracked
914 " 🔴 install-skill-from-github.py rejects --path . with "Invalid skill name"
915 " 🔵 GordenSuperPPTSkills repo structure: three skill subdirectories + examples + README
916 12:28a 🟣 GordenSuperPPTSkill installed to ~/.codex/skills/GordenSuperPPTSkill
917 " 🔵 GordenSuperPPTSkill is an orchestrator that chains GordenImagePPTGen → GordenImage2PPTX
918 " 🟣 All three GordenSuperPPTSkills now installed and verified
919 " 🔵 GordenImage2PPTX and GordenImagePPTGen ship distinct script toolkits
### Jun 22, 2026
932 2:21a 🟣 Proposed keyword-driven web search RAG enrichment capability
933 " 🔵 GAWorld project structure explored - generative city simulation framework
934 " 🔵 GAWorld existing RAG, web scrape, and news infrastructure mapped
935 " 🔵 _news.py three pipeline entry points and web_search engine details mapped
936 " 🔵 Runtime info-seek orchestration in generative_city_sim.py and memory lifecycle integration
939 2:22a 🔵 Keyword extraction rules, target chooser priority, and query builder seeds detailed
</claude-mem-context>
