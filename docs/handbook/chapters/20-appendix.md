# 第 20 章　速查附录

本章是查表用的：命令、配置、产物、术语。遇到「这个参数叫什么」「这个文件在哪儿」的时候来这里翻，不必读正文。

## 20.1 命令速查

### 仿真主命令

入口是 `generative_city_sim.py`，共 11 个子命令。

```bash
# 跑仿真
python generative_city_sim.py run                       # 默认步长
python generative_city_sim.py run --sim-days 600 --fast-forward
python generative_city_sim.py run --sim-months 24
python generative_city_sim.py run --sim-years 10
python generative_city_sim.py run --time-unit month --sim-years 10

# 重置（从 Day 1 重新开始）
python generative_city_sim.py reset

# 采访单个居民
python generative_city_sim.py interview --agent-id 31 --question "你这个月开销最大的一项是什么？"
python generative_city_sim.py interview --agent-id 31 --questions-file questions.txt
python generative_city_sim.py interview --agent-id 31 --question "..." --context "背景说明"

# 外部信息注入（RAG）
python generative_city_sim.py rag-add --agent-id 31 --text "..."
python generative_city_sim.py rag-import --agent-id 31 --file ./corpus/

# 从社交媒体页面造一个居民
python generative_city_sim.py create-agent-from-social --url "https://…"
python generative_city_sim.py create-agent-from-social --file page.html
python generative_city_sim.py create-agent-from-social --text "……"

# 实验
python generative_city_sim.py compare-event \
  --event-name "租金补贴" --event-description "每月补贴 300 元" --event-day 3 --seed 42
python generative_city_sim.py parallel-worlds --spec worlds.json
python generative_city_sim.py parallel-worlds --sweep economy.shocks.layoff_base_prob=0.01,0.02,0.04 --placebo

# 服务
python generative_city_sim.py dashboard --host 127.0.0.1 --port 8766
python generative_city_sim.py serve-viz --host 127.0.0.1 --port 8000
python generative_city_sim.py serve-distributed --host 0.0.0.0 --port 8877
```

`run` 的完整参数：

| 参数 | 含义 |
|---|---|
| `--sim-days N` | 覆盖仿真天数 |
| `--sim-months N` | 跑 N 个日历月；自动开快进并按月为步长 |
| `--sim-years N` | 跑 N 个日历年；自动开快进并按年为步长 |
| `--time-unit {day,month,year}` | 快进步长单位；指定任意一个都会自动开快进 |
| `--fast-forward` | 长时段快进：每步压缩成每人一条简报，跳过日内时刻循环 |

`compare-event` 与 `parallel-worlds` 还支持 `--llm-provider`（强制所有分支用同一个 provider）、`--output-root`（产物根目录）、`--fast`（确定性认知、跳过日摘要与日记、3 人群体，调用更少但保真度下降）。

### 城市

```bash
python -m gaworld.city create "绍兴柯桥" --size 200
python -m gaworld.city create "柳溪村" --offline --scale tiny
python -m gaworld.city create "翡翠屿" --description "热带火山岛，靠渔业和潜水旅游为生"
python -m gaworld.city create "翡翠屿" --image ~/sketches/island.png

python -m gaworld.city list
python -m gaworld.city show 绍兴柯桥
python -m gaworld.city use 绍兴柯桥

python -m gaworld.city add-agents 绍兴柯桥 --size 200 --preset cn_county_town
python -m gaworld.city add-agent 绍兴柯桥 --name 林素 --age 34 --job "社区医生"
python -m gaworld.city migrate 绍兴柯桥 --agent-id 31

python -m gaworld.city knowledge 绍兴柯桥
python -m gaworld.city locale 绍兴柯桥
python -m gaworld.city news 绍兴柯桥
python -m gaworld.city delete 绍兴柯桥 --yes
```

`create` 的参数：

| 参数 | 可选值 / 含义 |
|---|---|
| `--slug` | 目录名，默认取地名的 slug |
| `--scale` | `large` / `medium` / `metro` / `small` / `tiny`，覆盖推断出的规模 |
| `--offline` | 跳过地理编码与 OSM，程序化生成 |
| `--description` | 按描述虚构一座城，而不是查地名 |
| `--image` | 按草图（PNG/JPEG）虚构，需要 vision 模型 |
| `--size` | 同时生成多少居民 |
| `--preset` | `aging_community` / `cn_county_town` / `cn_tier1_district` / `college_town` / `custom` / `us_suburb` |
| `--seed` | 程序化地图的随机种子 |
| `--force` | 覆盖同名城市 |

### 人口、群体与采访

```bash
# 参数化人口：预览 / 落盘
python -m gaworld.population --size 500 --seed 42 --check
python -m gaworld.population --size 500 --name my_town --out data/town
python -m gaworld.population --spec spec.json --json

# 群体（cohort）模拟
python -m gaworld.group --size 500 --days 7 --no-llm
python -m gaworld.group --size 500 --days 7 --focal 7,42 --no-llm
python -m gaworld.group --size 500 --days 7 --network-coupling 0.7 --no-llm
python -m gaworld.group --budget 20 --audit-fraction 0.1 --axes age_band,industry,hukou

# 群体模式的验证门（分水岭层不通过时退出码非零）
python -m gaworld.group.validate --size 100 --days 14 --network-coupling 0.7

# 群体采访：一次问一群人
python -m gaworld.interview --spec round.json --out answers.json
```

### 账号与部署

```bash
python -m gaworld.accounts init --admin 老师
python -m gaworld.accounts invite --count 30 --label 某某班
python -m gaworld.accounts users
python -m gaworld.accounts reset --nickname student01
python -m gaworld.accounts city-permission --nickname student01 --allow
```

pip 安装后的工作区入口：

```bash
gaworld init ./my-world      # 准备一个独立可写的工作区
cd my-world
gaworld dashboard             # 打开 http://127.0.0.1:8766/dashboard
```

### 环境变量

| 变量 | 作用 |
|---|---|
| `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` | 云端模型密钥；具体用哪个由 provider 的 `api_key_env` 决定 |
| `MINIMAX_API_KEY` | MiniMax 兼容接口的密钥 |
| `GAWORLD_DASHBOARD_TOKEN` | 管理员令牌；带上的请求按管理员处理 |
| `GAWORLD_CONFIG_OVERRIDES` | 一段 JSON，运行时深合并覆盖配置，等价于改 `dashboard_config.json` |
| `GAWORLD_LOG_MODE` | `simple`（默认）或 `verbose` |
| `GAWORLD_LOG_LEVEL` | 日志级别，如 `DEBUG` |

## 20.2 配置速查

配置是分层的，底层是 `gaworld/settings/` 里的默认片段，上层是 `dashboard_config.json` 里的覆盖项。面板改配置写的是后者，删掉这个文件即可回到源码默认值。

![配置中心：全部配置项按分组展开，右侧显示被覆盖数量与「清空全部覆盖」按钮](../images/29-settings.jpg)

**图 20-1　配置中心**

全平台的配置项集中在这里，按子系统分组，每个旋钮都写了它是干什么的、默认值多少、当前值从哪来。查配置时先来这里，别去翻代码。

| 位置 | 负责什么 |
|---|---|
| `gaworld/settings/llm.py` | provider 定义与路由（`llm.providers`、`llm.routing`） |
| `gaworld/settings/runtime.py` | 运行期参数（天数、并发、日志、步长） |
| `gaworld/settings/behavior.py` | 行为与动态行为开关 |
| `gaworld/settings/economy.py` | 经济参数与部门池 |
| `gaworld/settings/environment.py` | 环境、事件、局部物理感知 |
| `gaworld/settings/family.py` | 家庭与户 |
| `gaworld/settings/personality.py` | 大五人格三通道开关 |
| `gaworld/settings/public_sector.py` | 公共部门与政策 |
| `gaworld/settings/organizations.py` | 持久组织主体（默认关闭） |
| `gaworld/settings/overrides.py` | 加载 `GAWORLD_CONFIG_OVERRIDES` 与 `dashboard_config.json` |
| `dashboard_config.json` | 面板写入的覆盖项；含 `llm`、`sim_days`、`agent_ids`、`long_run`、`city` 等 |

几个最常被改的键：

```python
CONFIG["pipeline"]["agent_step"]      # 12 阶段认知管线，消融/替换/插入阶段
CONFIG["llm"]["routing"]["default"]    # 默认模型
CONFIG["llm"]["routing"]["tasks"]      # 按任务分流（schedule 等）
CONFIG["long_run"]["randomness"]       # 快进期间的随机性
CONFIG["routine_change"]["randomness"] # 日程随机度
CONFIG["plugins"]                      # 第三方插件装配列表
```

`dashboard_config.json` 的实际结构（可对照本机文件）：

```json
{
  "llm": {
    "routing": { "default": "…", "tasks": { "schedule": "…" } },
    "providers": { "…": { "type": "ollama|openai|anthropic", "url": "…", "model": "…", "api_key_env": "…" } }
  },
  "sim_days": 5,
  "seconds_per_day": 10,
  "agent_ids": [1],
  "simulate_realtime": true,
  "time_step_minutes": null,
  "long_run": { "enabled": false, "randomness": 1.0, "unit": "day" },
  "routine_change": { "randomness": 1.0 },
  "city": "wuzhen"
}
```

## 20.3 产物速查

```
output/
├── logs/            run.log（完整）、agent_<id>.log
├── memory/          agent_<id>.json、agent_<id>_episodes.jsonl
│                    agent_<id>_growth.json、growth_profiles.json
│                    agent_<id>_env_preferences.json、agent_<id>_skills/*.md
│                    vector_db.sqlite
├── state/           状态历史（长表 CSV）
├── traits/          agent_traits.csv、calibration_audit.csv
├── economy/         daily_ledger.csv、wealth_snapshot.csv、macro_state.json
│                    sectors.json、conservation_audit.csv、interventions.json
│                    agents/agent_<id>_ledger.csv、agent_<id>_snapshot.json
├── environment/     timeline.jsonl
├── network/         social_network.png
├── records/         family.*.jsonl、travel.*.jsonl 及其它插件事件流
├── visualization/   simulation_trace.json、latest_frame.json
├── work/            capabilities.json、queue.jsonl、market.jsonl
├── intervention/    intervention_metrics.csv
├── comparisons/     <事件名>/comparison_summary.md、comparison_metrics.csv
├── interviews/      <session_id>/session.json、report.md
├── parallel_worlds/ <实验名>/divergence_summary.md、divergence_metrics.csv
│                    report.json、experiment.json、worlds/<world_id>/
└── worlds/          多用户部署时每个世界一棵产物树
```

常用查看命令：

```bash
cat output/memory/agent_31.json | python -m json.tool        # 格式化 JSON
tail -f output/logs/run.log                                    # 跟运行日志
tail -n 20 output/environment/timeline.jsonl                    # 最近的事件时间线
ls -la output/state/                                            # 状态历史 CSV
```

## 20.4 术语表

| 术语 | 含义 |
|---|---|
| 智能体（Agent / 居民） | 平台里的一个模拟居民，由状态、档案、人格、家庭关系与记忆构成 |
| 仿真日 | 仿真内部的「一天」，与真实时间无关；一天内可含多个时刻 tick |
| 快进（fast-forward） | 把一个仿真日压缩成每人一条简报，跳过日内时刻循环 |
| 步长单位 | 快进时一步代表多长：按天、按月、按年 |
| 阶段（pipeline stage） | 认知管线的 12 个命名步骤之一，可消融、替换或插入 |
| 干预（intervention） | 运行中改变世界的动作：改状态、改配置、移除居民、注入事件 |
| 分叉（divergence） | 某个世界与基准世界从第几步开始不再重合 |
| 配对 ATE | 同一位居民在两个世界里的差值再求平均，比组间比较更抗个体差异 |
| 剂量—反应 | 同一事件取不同强度，看效应量怎么随强度移动 |
| 安慰剂（placebo） | 用一个不该有效应的事件当对照，测出噪声地板 |
| 群体（cohort） | 一组同时携带均值与离散度的居民，每群每天只花 1 次模型调用 |
| 实体化（materialize） | 把群体里的某个个体提升为完整保真度单独模拟 |
| 复制拟合度 | 让居民重做一项有真人对照的调查或实验，代码比对误差与效应对齐程度 |
| 预注册 | 在跑实验之前把假设、指标、条件与判定规则固定下来 |
| Epoch | 变更默认配置后追加的可比性版本号；跨 Epoch 的结果不可合并 |
| 城市包 | `data/cities/<slug>/` 下一座城市的地图、环境、人口与知识库 |
| 钩子语义 | 插件订阅事件的两种约定：`observe` 只看、`collect` 汇总贡献 |
| 审计 | 每次运行时干预自动留下的记录，插件无法悄悄改世界 |

## 20.5 文档地图

![文档面板：控制台内直接列出的项目文档，可在线阅读与检索](../images/30-docs-panel.jpg)

**图 20-2　控制台内置的文档面板**

控制台里带了一个文档面板，项目自己的文档不用离开浏览器就能读、也能搜。下面的表是「离线去哪里找」的对照。

| 你要解决的问题 | 去哪里 |
|---|---|
| 这个功能到底有没有、怎么配 | `docs/FEATURES.md`（能力目录） |
| 某个面板的完整用法 | `docs/RESEARCH_WORKBENCH_TUTORIAL.md` / `docs/PLAYGROUND_TUTORIAL.md` / `docs/CITY_TUTORIAL.md` / `docs/GROUP_INTERVIEW_TUTORIAL.md` |
| 所有 HTTP 接口 | `docs/API_REFERENCE.md`；`gaworld/client.py` 可按 operationId 直接调 |
| 插件怎么写 | `docs/PLUGIN_AUTHORING.md` |
| 怎么部署给一班学生用 | `docs/SERVER_DEPLOYMENT.md` |
| 方法论与经典案例 | `textbook/`（22 章 + 4 附录，另有 pdf / epub） |
| 中英对照的长指南 | `docs/PROJECT_GUIDE.zh-CN.md` / `docs/PROJECT_GUIDE.en.md` |
| 效度怎么评 | [GAWorld Bench](https://s2014628.github.io/gaworld-bench/) |
| 这个仓库怎么改 | `AGENTS.md`（项目结构与开发规则）、`CONTRIBUTING.md` |

## 20.6 本章小结

- 命令分五组：仿真主命令、城市、人口与群体、账号与部署、环境变量；每条都能加 `--help` 查全。
- 配置分两层：源码里的 `gaworld/settings/` 与面板写入的 `dashboard_config.json`；删掉后者就回到默认值。
- 产物全部落在 `output/`，`output/worlds/<id>/` 是多用户部署时每个世界的那一棵。
- 术语表里的「分叉」「配对 ATE」「安慰剂」「Epoch」是后面做实验时反复出现的词，值得记住。
- 遇到任何「这个参数在哪」的疑问，先查本页；查不到再查 `docs/FEATURES.md`，最后才去读代码。

## 20.7 动手练习

1. **把速查表变成你自己的**（约 30 分钟）
   照着 20.1 跑一遍 `run`、`reset`、`--help` 三类命令，在纸上记下你最常用的五条。
   **验收标准**：不看手册，你能在终端里敲出「跑 10 年、按年一步」和「造一座离线虚构城市」这两条完整命令。

2. **核对产物树**（约 20 分钟）
   跑一次 `python generative_city_sim.py run --sim-days 3`，然后按 20.3 的目录清单逐个检查 `output/` 下实际存在哪些文件。
   **验收标准**：能指出至少 5 个目录里各有什么、哪个目录是记忆、哪个是状态历史、哪个是事件流。
