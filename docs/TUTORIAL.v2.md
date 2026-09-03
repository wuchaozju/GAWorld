# GAWorld 教程 v2

**面向第一次到进阶使用 GAWorld 的用户 | 更新日期：2026 年 6 月**

> 这是 GAWorld 的**完整教程**——已并入原 v1.0 完全教程的全部内容，单文件自包含。更简短的快速上手见 [`docs/TUTORIAL.md`](TUTORIAL.md)。
> 在既有特性详解（第 5 节）之外，本版补全了三块**新特性**（物理环境感知与反应式重规划、可复用 Skill 库、真实工作任务系统）与**分布式 relay 多机通信**。

---

## 目录

1. [GAWorld 是什么](#1-gaworld-是什么)
2. [安装与 LLM 配置](#2-安装与-llm-配置)
3. [5 分钟跑通第一次仿真](#3-5-分钟跑通第一次仿真)
    - [3.1 长时段快进（Fast-forward）：跑 10 / 60 / 600 天](#31-长时段快进fast-forward跑-10--60--600-天)
    - [3.2 大跨度模拟：以「月」「年」为时间单位](#32-大跨度模拟以月年为时间单位)
4. [核心概念：智能体与仿真循环](#4-核心概念智能体与仿真循环)
5. [既有特性详解](#5-既有特性详解)
    - [5.7 家庭与户](#57-家庭与户)
    - [5.8 大五人格](#58-大五人格)
6. [新特性一：物理环境感知与反应式重规划](#6-新特性一物理环境感知与反应式重规划)
7. [新特性二：可复用 Skill 库](#7-新特性二可复用-skill-库)
8. [新特性三：真实工作任务系统](#8-新特性三真实工作任务系统)
9. [事件对照实验](#9-事件对照实验)
    - [9.1 平行世界：两个以上分支](#91-平行世界两个以上分支)
10. [访谈与 RAG 注入](#10-访谈与-rag-注入)
11. [分布式 relay：多机通信](#11-分布式-relay多机通信)
12. [Dashboard 使用指南](#12-dashboard-使用指南)
    - [12.1 Agent Studio（单智能体构建/查看器）](#121-agent-studio单智能体构建查看器)
    - [12.2 Population Studio（人口生成与群体模拟）](#122-population-studio人口生成与群体模拟)
    - [12.3 外部系统观测台（货币 / 环境 / 对外服务）](#123-外部系统观测台)
    - [12.4 平行世界实验台](#124-平行世界实验台)
    - [12.5 家庭：看板卡片与工作台编辑面板](#125-家庭看板卡片与工作台编辑面板)
13. [大规模人群：人口合成与群体模拟](#13-大规模人群人口合成与群体模拟)
14. [配置与开关总表](#14-配置与开关总表)
15. [输出文件地图](#15-输出文件地图)
16. [常见问题](#16-常见问题)
17. [命令速查表](#17-命令速查表)
18. [微内核插件架构：扩展 GAWorld](#18-微内核插件架构扩展-gaworld)

---

## 1. GAWorld 是什么

GAWorld（Generative Agent World）是一个**面向城市社会行为实验的生成式多智能体仿真系统**。它把人物画像、长期记忆、社会影响、环境扰动、政策事件、经济状态、地图移动、轻量平台干预评估和 LLM 决策组合成一个**可回放、可对照、可扩展**的模拟流程。

一句话：让一批虚拟城市居民在你的电脑上"生活"若干天——每个人都有工作、社交、财务、情绪、习惯和记忆——然后你通过实验观察社会现象。

适用场景：

| 场景 | 说明 |
|------|------|
| 城市政策模拟 | 交通限行、住房补贴、医疗改革等政策对居民行为的影响 |
| 社会行为研究 | 信息/误信息传播、情绪感染、极化、社交网络演化 |
| 智能体记忆实验 | 长期记忆、习惯养成对行为一致性的影响 |
| AI / 复杂系统教学 | 演示多智能体如何涌现复杂社会现象 |

`docs/proposals/` 下已有一批成型的实验方案与论文（记忆一致性、误信息传播、极化、宏观经济、网络演化、出行行为等），可作为设计参考。

---

## 2. 安装与 LLM 配置

### 2.1 环境要求

| 项目 | 要求 |
|------|------|
| Python | **推荐 ≥ 3.11**（3.10 可跑主流程，但完整测试套件依赖 3.11 的少数特性） |
| 操作系统 | macOS / Linux / Windows |
| 内存 | 推荐 16GB 以上 |
| 网络 | 访问云端 LLM API；用本地 Ollama 可离线 |

### 2.2 安装

```bash
pip install -r requirements.txt
python generative_city_sim.py --help   # 看到帮助即安装成功
```

### 2.3 配置 LLM（必须）

GAWorld 运行需要至少一个可用的 LLM Provider，三选一：

**① OpenAI 兼容（云端）**

```bash
export OPENAI_API_KEY="your_key_here"
```

**② Anthropic 兼容（云端 / 代理）**

```bash
export ANTHROPIC_API_KEY="your_key_here"
# 中国区 Minimax 的 Anthropic 兼容接口：
export ANTHROPIC_BASE_URL="https://api.minimaxi.com/anthropic"
export MINIMAX_API_KEY="your_key_here"   # 或 ANTHROPIC_AUTH_TOKEN
```

**③ 本地 Ollama（离线）**

```bash
brew install ollama        # macOS
ollama pull qwen2.5
ollama serve               # 默认 port 11434
```

然后在 `config.py` 中让 `llm.routing.default` 指向你已配置好的 provider（如 `openai_gpt` / `ollama_qwen`）。也可以用 `llm.routing.tasks` 给不同任务（planning / reflection 等）指定不同模型。

---

## 3. 5 分钟跑通第一次仿真

```bash
pip install -r requirements.txt
export OPENAI_API_KEY="your_key_here"
python generative_city_sim.py run
```

运行时终端输出（默认 `simple` 模式，约每 tick 4 行）：

```
── [李泽宇 @ 09:30] 上午工作 ──
Loc: 互联网公司
Act: 推进最重要的一项任务
Refl: 感受：情绪有一点波动；教训：下次要更早判断状态和代价；后续倾向：更偏向省力或稳妥
```

想看完整字段（感知 / 计划 / 记忆召回 / 需求状态）切换详细模式：

```bash
GAWORLD_LOG_MODE=verbose python generative_city_sim.py run
GAWORLD_LOG_LEVEL=DEBUG  python generative_city_sim.py run   # 含 token 计数与延迟
```

跑完后看 `output/`：

```
output/
├── logs/           运行日志（run.log 为完整结构化日志）
├── memory/         智能体记忆、成长进度、向量库
├── state/          状态时间序列 CSV
├── economy/        账本、财富快照、宏观状态、部门池与守恒审计
├── environment/    环境事件时间线
├── intervention/   PolicySim 风格干预指标
├── network/        社交网络图
├── work/           真实工作产物（启用后）
└── visualization/  轨迹回放数据
```

改了关键配置（尤其是记忆 schema 相关）或想从 Day 1 重来：

```bash
python generative_city_sim.py reset && python generative_city_sim.py run
```

### 3.1 长时段快进（Fast-forward）：跑 10 / 60 / 600 天

默认的精细模式每天要跑一遍**日内时刻循环**（每个 tick 每个 agent 一次认知
LLM 调用，约每 agent 每天数十次），几十上百天就跑不动了。**长时段快进模式**
把一整天压缩成**每个智能体一条「日简报」**（每 agent 每天仅 1 次 LLM 调用），
跳过日内时刻循环——实现一种「快进 + 近似」的效果，适合观察**长期**演化。

```bash
# 快进跑 600 天：每天每个 agent 生成一条日简报
python generative_city_sim.py run --sim-days 600 --fast-forward
```

- **输出不再按具体时刻**，而是每天一个 `Day N 简报` 块：每个 agent 一行 +
  当天世界事件提示。
- **状态仍会「近似推进」并持久化**：情绪/压力等状态按夹逼后的小幅增量更新，
  目标进度、关系亲密度、记忆与日记都照常写入，日终的成长/兴趣/经济钩子也照跑
  ——只是分辨率更粗。所以跑完 600 天后，智能体是被真实塑造过的。
- 关掉 `--fast-forward` 即回到逐时刻的精细模式（默认）。

调参（`config.py` / `dashboard_config.json` 的 `long_run` 段）：

| 字段 | 默认 | 作用 |
|---|---|---|
| `long_run.enabled` | `false` | 快进总开关（等价于 `--fast-forward`） |
| `long_run.brief_llm` | `true` | 用 LLM 写简报；置 `false` 则**零 LLM** 走确定性简报 |
| `long_run.randomness` | `0.3` | **随机性 0–1**：越高，快进期间**突发事件**越频繁、智能体**状态波动**越大；`0` = 完全确定（无突发、无抖动） |
| `long_run.max_state_delta` | `0.15` | 单步近似状态增量的夹逼上限（按月/按年自动 ×2 / ×3） |
| `long_run.brief_max_chars` | `240` | 每条日简报的软长度上限 |
| `long_run.unit` | `"day"` | **步长单位**：`day` / `month` / `year`，见 3.2 |
| `long_run.period_brief_max_chars` | `480` | 月度简报的软长度上限（年度简报按 1.5 倍） |
| `long_run.hook_chunk_days` | `30` | 粗粒度下日边界钩子的补跑区块，见 3.2 |

**随机性怎么起作用**：每个智能体每天按 `≈0.3×randomness` 的概率掷出一次
**突发事件**（意外开销/机会/冲突/健康/人际变故……），命中时简报里会自然带出这件
事、状态也随之明显波动（日志中以 `⚡` 标记）；此外每天都会给情绪/压力等状态叠加
一层幅度随 `randomness` 增大的零均值抖动（突发日抖动更大）。设 `random_seed` 可复现。

> Dashboard 上也能一键开启：工具栏勾选「长时段快进」、选择「步长单位」、拖动
> 「随机性」滑杆即可（见第 12 节）。

### 3.2 大跨度模拟：以「月」「年」为时间单位

按天快进已经够跑一两年，但调用量随天数线性增长：50 个居民跑 10 年 = 18.25 万次
调用。要跑**数年到数十年**，得把**一步**做大——把一整个月、甚至一整年压缩成
**每个智能体一条「阶段简报」**。

```bash
# 跑 24 个月，一个月一步：每人每月一条月度简报
python generative_city_sim.py run --sim-months 24

# 跑 10 年，一年一步：50 人 × 10 年 = 500 次调用（按天则是 182,500 次）
python generative_city_sim.py run --sim-years 10

# 也可以分开写：时长按年给，步长仍按月（10 年 = 120 步）
python generative_city_sim.py run --sim-years 10 --time-unit month
```

`--sim-months` / `--sim-years` / `--time-unit` 任意一个都会自动打开快进模式。

**一步里发生了什么**

| 环节 | 粒度 |
|---|---|
| 认知（简报、状态增量、目标推进、社交信号、意图） | **每步 1 次 LLM 调用/人**；月/年简报还会给出 2–4 条 `highlights` 里程碑，逐条写进记忆 |
| 状态增量上限 | 按 `max_state_delta × 2`（月）/ `× 3`（年）夹逼——一个月能明显改变一个人，但不会一步跳到极值 |
| 突发事件 | 期望个数 `≈0.3 × randomness × 天数`，上限 4 件/步，写进同一份简报 |
| 仿真日历 | **仍按天推进**：一步跨过的是真实日历月/年（闰年、大小月都算对），日号连续 |
| 关系衰减 | 按「距上次联系的天数」计算，天然吃满整段跨度 |
| 经济、兴趣衰减、家庭开销等日边界钩子 | 按 `hook_chunk_days`（≤30 天）**补跑**，所以跑一年会扣一年房租、走 12 次月度结算，而不是只扣一天 |
| 目标周回顾 | 每步一次（在最后一个区块），而不是每个补跑区块一次 |

**关于收入**：快进模式不跑日内时刻循环，而工资原本是逐时刻结算的。粗粒度下经济
模块会按「宏观调整后的时薪 × 目标工时 × 工作日数」补记一笔近似工资（从 firms
资金池支出，货币守恒，并计入当月计税基数）。否则跑满一年会出现「只付房租不挣钱」
的全员破产。

**代价**：日内细节、逐日轨迹全部消失，一步之内只剩一条叙事简报和一组累计增量。
适合做**长期演化**（生涯轨迹、代际、政策的多年后效），不适合看日内行为。

> 步长单位只在快进模式下生效——精细模式的日内时刻表对「一个月」没有意义。

**在 Dashboard 上跑**：工具栏勾选「长时段快进」，把「步长单位」切成月或年，
左边的「仿真天数」会跟着变成「仿真月数」/「仿真年数」——填 `10` + `年` 就是跑十年。
浏览器只提交 `{unit, count}`，天数由服务端按真实日历换算，和 CLI 的 `--sim-years 10`
得到完全相同的 `sim_days`。

---

## 4. 核心概念：智能体与仿真循环

每个智能体 = **基本信息 + 状态变量 + 记忆 + 财务 + 关系网络**。

状态变量（归一化到 [0,1]）：

| 变量 | 含义 | 0 → 1 |
|------|------|-------|
| emotion | 情绪 | 极消极 → 高度积极 |
| stress | 压力 | 无 → 极高 |
| econ_security | 经济安全 | 极不安全 → 极安全 |
| city_identity | 城市认同 | 强烈疏离 → 强烈认同 |

外加 `policy_sensitivity`、`platform_dependence`、`risk_preference`、`voice_propensity`、`mobility_intent` 等增强变量。

每个智能体每个时间步循环 5 步：

```
① 感知 → ② 计划 → ③ 日程/动作生成 → ④ 动作执行 → ⑤ 反思与记忆更新
                                                        ↓（回到 ①）
```

随天数推进累积：episode 记忆、长期总结、情境习惯、日级意图、关系变化、收支与资产变化、技能成长、地点偏好。

> **新特性接入点**：本版三块新特性都"挂"在这个循环上——物理感知发生在 ①感知之前、Skill 在 ①感知与工作 brief 处注入、真实工作在 ④动作执行时按职业触发。下面分别讲。

---

## 5. 既有特性详解

下面这些特性在更早的教程里就已存在，本节把要点、配置开关与文件位置整理在一处（原 v1.0 教程的完整说明已并入此节）。

### 5.1 记忆系统

多层记忆架构：

- **短期记忆**：当前 episode 与当天活动日志。
- **情景记忆（Episodic）**：每个行为决策的背景与结果，逐条写入 `output/memory/agent_<id>_episodes.jsonl`。
- **长期总结（Long-term）**：智能体对自身的认知与目标总结，跨天保持一致。
- **关系记忆**：与其他智能体的关系变化与社交互动历史。

| 文件 | 内容 |
|---|---|
| `agent_<id>.json` | 完整记忆状态 |
| `agent_<id>_episodes.jsonl` | 逐事件记录 |
| `agent_<id>_growth.json` | 兴趣 / 技能成长进度 |
| `growth_profiles.json` | 全局兴趣画像缓存 |
| `vector_db.sqlite` | 向量数据库（语义检索） |

**召回机制**：每个感知阶段按"当前情境 → 向量检索 → 召回最相关历史 → 注入感知"工作，让行为带上记忆一致性。

### 5.2 经济仿真

基于中国个人财务体系的闭环货币系统（配置见 `CONFIG["economy"]`，源文件 `gaworld/settings/economy.py`，实现 `gaworld/economy/finance.py`）：

- **个税与社保（真实代扣）**：7 档累进税率（3%→45%）、月免征额 5000 元；五险一金按个人缴费率扣缴（养老 8% / 医疗 2% / 失业 0.5% / 公积金 8%）。月末按**实收**工资从活期账户真实代扣，税款入政府部门池，公积金（个人 + 单位配缴）入公积金账户。
- **恩格尔系数消费**：低收入者食品支出占比高、储蓄率低，高收入者相反；8 大消费类目按收入弹性分配。
- **多账户投资 + 共同市场因子**：活期 / 储蓄 / 投资 / 公积金四账户，保守 / 稳健 / 激进三种组合。月度收益 = 全市场共同因子（每月抽取一次，所有 agent 共享，股灾会同时打击所有人）+ 个体特质噪声，系统性占比由 `investment.market_correlation`（默认 0.7）控制。
- **宏观经济周期**：扩张 → 峰值 → 收缩 → 谷底四阶段，行业景气独立波动，每日通胀累积。

**货币守恒与部门池**：所有资金流动都有对手方 —— 企业池（发工资、收消费）、政府池（收税、付医保报销）、银行池（结算投资盈亏、放贷）。初始化后系统货币总量守恒到分，每日审计写入 `conservation_audit.csv`（|drift| ≤ 0.01 元），GAWorld-Bench Track A 将其作为硬门槛。部门池允许为负（企业池为负 = 家庭部门净储蓄的镜像）。

**现金约束、信贷与熟人借贷**：支出按 活期 → 储蓄提取 → 银行信用额度（默认 2 倍月净薪、年息 18%、月度复利、盈余自动还款）→ 截断 的顺序融资；流动性低于 1 个月开销时按收入弹性削减非必需消费（奢侈类砍得更狠）。消费被截断的 agent 进入 distress 状态：stress 上升，日终可按 closeness×trust 向社交网络上有盈余的好友无息借款（`friend_debts` 双边记账，月结时优先于银行债务偿还）。

**支付路由到 agent**：本地消费的 `routing.merchant_labor_share`（默认 35%）经企业池转付给工作地点匹配的服务业 / 商贸 agent；房租路由给房东类 agent（职业关键词匹配），无房东则留在企业池。货币因此在 agent 之间循环，财富分布可以内生涌现。

个体随机触发的经济冲击事件：

| 事件 | 影响 |
|---|---|
| 裁员 | 收入削减 50–85%（月度税基同步下调），恢复期 30–90 天 |
| 涨薪 / 晋升 | 收入提升，税率重算 |
| 大病医疗 | 社保报销 50–85%（政府池支付），影响情绪与支出 |
| 年终奖 | 第 13 个月工资（企业池支付，奖金税入政府池） |

经济模块使用独立随机流（由 `random_seed` 派生），其它模块增删随机调用不影响经济轨迹的可复现性。

经济数据写入 `output/economy/`（`daily_ledger.csv` 含 `debt` 列、`wealth_snapshot.csv`、`macro_state.json`、`sectors.json`、`conservation_audit.csv`、`agents/agent_<id>_*`）。

> 这些数字不必靠翻 CSV 来读：控制台「**外部系统**」页签把宏观状态、部门池、守恒审计与
> 财富分布画成面板，并且可以直接改经济配置、或对**跑着的**仿真排一次货币干预。
> 见 [12.3](#123-外部系统观测台) 与[外部系统教程](EXTERNAL_SYSTEMS_TUTORIAL.md)。

### 5.3 位置系统与交通

用**类别匹配**而非硬编码地点决定移动："活动类型 → 地点类别 → 地图节点 → 最佳选择"。

| 活动 | 地点类别 |
|---|---|
| 工作 | industry / commerce / government |
| 上学 | education |
| 就医 | medical |
| 购物 | commerce |
| 休闲 | leisure |
| 通勤 | transit |

**真实出行成本**：公交固定 2 元；地铁起步 2 元 + 超 4 公里 0.45 元/公里；出租起步 13 元 + 超 3 公里 2.5 元/公里；私家车计油耗 + 停车费。**高峰**（7–9 / 17–19 点）出行时间 ×1.45、出租附加 ×1.3。**天气**：雨雪天惩罚露天方式，自动改走有遮蔽方式。**通勤记忆**：累积常去地点、偏好方式与路线统计，反馈为习惯性出行。

### 5.4 动态行为系统

开关 `CONFIG["dynamic_behavior"]["enabled"]`。在 LLM 决策前注入上下文感知的日程变更，六大引擎：中断 / 情绪 / 需求 / 社交 / 环境 / 日程。

- **承诺度感知中断**：每种活动有承诺度（考试 / 手术 0.95、工作 / 上课 0.70、社交 0.50、休闲 0.20、刷手机 0.15）；中断候选须克服"承诺度壁垒 + 性格阈值（自控力 + 风险偏好）"。
- **情绪驱动即兴**：开心 / 压力 / 疲倦 / 无聊 / 焦虑 / 孤独各有即兴行为池（发动态、独自散步、小憩、找朋友聊天…）。
- **环境事件级联**：如"下雨 → 打车排队 → 烦躁"、"拥堵 → 迟到 → 工作压力"、"促销 → 购物冲动"。
- 另含需求中断（饥饿 / 疲劳 / 时间压力）、社交偶遇链，以及中断后的日程插入与恢复。

> 第 6 节的"物理环境感知与反应式重规划"是动态行为系统的进一步增强——把节点级拥挤 / 营业状态也接入中断与重规划。

### 5.5 兴趣爱好与技能成长

开关 `CONFIG["interests"]["enabled"]`。为每个智能体派生 `growth_profile`（兴趣、计划发展的技能、练习进度），影响日程、动作权重与工作选择；进度落在 `output/memory/agent_<id>_growth.json`，全局画像缓存于 `growth_profiles.json`。

成长动力学（v2，纯规则、零额外 LLM 调用，设计文档见 `docs/proposals/2026-07-04-personal-growth-v2.md`）：

- **幂律学习**：练习收益随水平递减；连续练习（streak）有动量加成；水平上穿 0.35 / 0.60 / 0.85 时向 episode 的 `growth_progress` 写入里程碑事件（入门/熟练/精通）。
- **发展四阶段**：按 Hidi & Renninger 模型从水平 + 累计练习量派生"触发期 → 维持期 → 浮现期 → 成熟期"，进入 prompt 上下文。
- **日终遗忘衰减**（`interests.decay`：`grace_days` / `daily_rate` / `floor`）：超过宽限期未练则掉水平，保持率随累计练习量提高、且阶段感知（触发期 ×1.5、成熟期 ×0.5），断练归零 streak。
- **兴趣集演化**（`interests.evolution`：`retire_after_days` / `adopt_chance` / `max_new_per_day`）：停滞的触发期条目会被放下（至少保留 1 项）；可从当日社交对象处习得新兴趣（社交传染），仿真日志中以 🌱 行提示。

### 5.6 干预评估

PolicySim 风格的推荐与曝光评估，**本地完成、无额外 API、不训练模型**。每步构造 Feed（关系推荐 / 个性化推荐 / 公共议题）→ 曝光控制启发式（相似立场过滤 + 多样性促进）→ 记录五项指标：`stance_score`、`toxicity_score`、`misinformation_risk`、`cross_viewpoint_exposure`、`intervention_reward`，写入 `output/intervention/intervention_metrics.csv`。

---

### 5.7 家庭与户

在这个特性之前，仿真里**所有居民事实上都是单身**——profile 文本几乎不写婚育，
`build_agent()` 没有家庭字段，而社交模块里的 `spouse` / `child` 角色只存在于
每个 agent 各自 LLM 生成的"场外名单"里：它的确定性兜底**从不生成配偶或子女**，
而且 A 的配偶和 B 毫无关系。

现在家庭是一等实体。

**它是怎么定出来的**（`gaworld/family/assign.py`）：先按 `年龄段 × 性别` 抽婚姻状态
（未婚 / 已婚 / 离异 / 丧偶），再把匹配得上的居民在**仿真内**配成夫妻，配不上的补一个
场外配偶，最后才生成子女、同住长辈和不同住的父母。

顺序刻意是"先状态、后结构"，因为**户型是分配结果的读数，不是预先分配的配额**。
先按户型占比规划再往里填人，一旦户型旋钮和年龄金字塔打架，就会有一方静默地输掉
（要 26% 核心家庭、但镇上只有 80 个小孩）。八种户型——独居 / 合租 / 与父母同住 /
未婚同居 / 夫妻二人 / 核心家庭 / 单亲 / 三代同堂——是读出来的，因此不可能和任何东西矛盾。

**默认跑一遍 51 人的效果**：约 71% 已婚、27% 未婚、其余离异；40 户左右，
其中 10 对是仿真内夫妻。

**家庭怎么影响生活**：

| 层 | 做了什么 |
|---|---|
| 关系 | 家庭边写成社交模块认识的普通关系记录，kin 角色自动继承衰减率、义务基线与 Dunbar 保护；与家庭矛盾的 LLM 编造配偶会被剪掉 |
| 共居 | 同户居民**共享同一个 home 节点**——这是"家庭"和"两个地址相同的陌生人"的分界线，共享之后现有的同地点相遇循环才会真的产生家庭互动 |
| 日程 | 接送幼儿园、陪写作业、照料同住老人、给父母打电话、回家吃晚饭，区分工作日/周末，作为高承诺事项注入日程 prompt |
| 账本 | 育儿与赡养开销按**收入**在家里挣钱的人之间分摊，走经济模块自己的支出通道（守恒）；伴侣在一方现金见底时互相补窟窿（纯转移） |
| 事件 | 孩子发烧是**一件**事，同一个 tick 同时落到父母两人身上——这是按 agent 独立生成的事件表达不了的 |
| 情绪 | 同住家人之间的情绪/压力互相靠拢；全家都平静时不产生任何漂移 |

**一个必须知道的取舍**：`family.pairing.in_sim_pair_share`（默认 `0.6`）是
**建模旋钮，不是人口学事实**。从一座千万人口的城市里抽 51 个人，他们互为夫妻的
真实概率约等于 0；在仿真内配对是为了买到"家庭内互动"。要人口学纯净的跑法，
把它调到 `0.0`，所有配偶都会变成场外家人。

**常用旋钮**（配置面板 → 「家庭与户」分区，或直接改 `CONFIG["family"]`）：

```python
CONFIG["family"]["enabled"] = False                      # 整个关掉，回到全员单身
CONFIG["family"]["pairing"]["in_sim_pair_share"] = 0.0   # 人口学纯净：配偶全在场外
CONFIG["family"]["fertility"]["p_any_child"] = [...]     # 低生育率政策实验
CONFIG["family"]["events"]["contagion_weight"] = 0.0     # 关掉户内情绪传染
CONFIG["family"]["finance"]["enabled"] = False           # 只要关系和日程，不要记账
CONFIG["family"]["seed"] = 20260813                      # 换一批家庭
```

**怎么观察它生效**：

- 启动时控制台会打印一行 `👪 家庭结构已生成：…` 和每位居民的 `[Family] …`；
- 日程 prompt 里出现「家庭状况：…」和「今日家庭责任：…」；
- 产物 `output/records/family.{summary,household,agent,finance}.jsonl`；
- Dashboard 主面板的「家庭结构」卡片（见 [12.5](#125-家庭看板卡片与工作台编辑面板)）。

⚠️ **日程有缓存**。想看到家庭真的改变日程，先 `python generative_city_sim.py reset`
再 `run`，否则已有居民会直接复用上一次生成的基础日程。

设计取舍与踩过的坑见 [家庭系统设计](FAMILY_DESIGN.md)。

---

### 5.8 大五人格

开关 `CONFIG["personality"]["enabled"]`（**默认 ON**）。以插件形式提供——插件 id `big_five`，
在 `gaworld/plugins/builtin_plugins()` 里第一个注册，只挂 `agents.built` 一个钩子，
代码在 `gaworld/personality/`。

每位居民带一组**离线生成好的**大五（OCEAN）z 分，运行时只读 `data/agents_big5.csv`；
没有这份文件时按人群先验采样（`sampling.*`：`seed` / `correlations` / `rescale`）。
**人格在一次运行内不漂移**——它是这个人的底色，不是又一个会飘的状态变量。

**三条通道**（`personality.channels`，默认全开，可分别关掉）：

| 通道 | 做了什么 |
|---|---|
| `rules` | 确定性、零 token。`choose_action` 里加一个加性权重项 `trait_style_fit`（决策依据里显示为「性格倾向」）；对打断阈值、自发冲动概率、共处时的搭话概率、决策噪声、冲动绕过概率、消费 / 储蓄倾向做乘性微调；再给情绪加一条属于个人的基准线 |
| `prompt` | 把人格写成第二人称的**行为锚句**，注入日程生成、日内活动调整、目标推导、新闻反应四类提示词。每段最多两条，按概率渲染（越极端越必然被写），**永远不写数字和维度名** |
| `voice` | 同样的锚句只进日记提示词，用来把「文风变了」和「决策变了」分开归因 |

**常用旋钮**（`CONFIG["personality"]`，定义在 `gaworld/settings/personality.py`）：

```python
CONFIG["personality"]["enabled"] = False               # 整个关掉
CONFIG["personality"]["channels"]["prompt"] = False    # 只留规则通道（或只留 voice 做归因实验）
CONFIG["personality"]["strength"] = 0.0                # 对照组：数据还在，人格不起作用
CONFIG["personality"]["style_fit_amplitude"] = 0.30    # 人格在动作选择里的权重幅度
CONFIG["personality"]["modifier_band"] = 0.25          # 乘性调节的上下限
CONFIG["personality"]["residual_ratio"] = 0.6          # 每个人身上与人格无关的个体差异
CONFIG["personality"]["profile_path"] = "data/agents_big5.csv"   # 人格分数表，运行时只读
```

另有 `prompt.render_midpoint` / `prompt.render_spread` / `prompt.strong_z` / `prompt.max_dims`
控制锚句的渲染概率与每段条数；`emotion_baseline.*`（`contagion_weight` 0.06、
`recovery_rate` 0.08、`n_recovery_slope` 0.30、`n_baseline_slope` 0.12、
`e_baseline_slope` 0.04）控制个人情绪基准线。

**人格分从哪来：先采样 OCEAN，再据此写人物设定**

老流程是反过来的——读每个人 profile 里的「性格与情绪特征」段落，让 LLM 从中打分。
这在这份语料上不成立：那段文字中位数只有 **20 字**，是标签不是描述；而
`policy_sensitivity` / `platform_dependence` / `risk_preference` / `voice_propensity` /
`mobility_intent` 这五个个体级状态变量就写在同一份 profile 里、紧挨着它。
散文和数字本来就是同一个作者对同一个人的两种写法，从散文打分只是把数字读了回来——
开放性与 `mobility_intent` 的相关高达 **0.90**，共线性闸门在 O、C、E 三维上判不合格。

现在由 `scripts/author_personality.py` **先采样五维分数，再据此写行为描述**：
独立性由采样器保证，不再是事后测出来的。只保留两条有文献依据的真实相关——
开放性 ↔ `risk_preference`、外向性 ↔ `voice_propensity`，都是 r≈0.3；C / A / N 独立采样，
不编造配对。只有明显偏离均值的维度（|z| ≥ 0.5，平均每人 3.0 个）才会被写进文字。
profile 因此多出一个 `**人格与行为倾向**` 字段，原来的 `**性格与情绪特征**` 在文件里原样不动。

```bash
python scripts/author_personality.py --agents 1-5 --dry-run   # 看提示词与采样分数，不花钱
python scripts/author_personality.py --agents 1-5             # 试水，写 output/traits/authored_preview.md
python scripts/author_personality.py --apply                  # 全量，自动备份 .v1.md，写 md + CSV
python scripts/big5_collinearity.py --annotate                # 必跑
python scripts/big5_effect_ceiling.py                         # 复核幅度
```

`--apply` 会把旧语料备份到 `data/hangzhou_profiles_with_names.v1.md`。
两道闸门的含义不变：`big5_effect_ceiling.py` 蒙特卡洛真实的 `choose_action`，
报告给定幅度下人格与行为的相关能到多大；`big5_collinearity.py --annotate`
检查五个维度是不是已有状态变量的线性组合，把不合格维度写回 CSV。

`scripts/calibrate_big5.py` **没有删**，只是换了职责：一是给外部导入的 agent 打分
（社交媒体导入那条路），二是当对照组——用它重新给新语料打分，跟采样得到的真值一比，
就知道这个打分器到底有多准。

**两个溯源列，会跟着数据一路进到运行产物里。** 人物设定没描述到的维度会被记成 `unstated`
并取 **恰好 0**（无行为倾向、不写进提示词），共线性闸门判定不合格的维度会被 `--annotate`
记成 `redundant`。两者都会进 agent record、进 `output/traits/agent_traits.csv`、
进 recorder 载荷，并在**每次运行启动时打印出来**。反向生成之后这两列在当前语料上都是空的，
所以启动时只剩一行：

```
🧬 大五人格已就绪：51 人（标定 51 / 先验采样 0），启用通道 rules+prompt+voice
```

两列仍然有意义：外部导入的 agent 走的还是打分那条路，仍可能留下 `unstated`。

当前这份语料的实际情况（`--apply` 跑完 51 人之后）：

| | 反向生成前 | 反向生成后 |
|---|---|---|
| 覆盖率 | N 35/51、C 26、O 17、E 13、A 11 | **五维全部 51/51** |
| 共线性最差调整 R² | 0.77（不合格） | **0.05（合格）** |
| 人群标准差 | 0.45–0.74 | **1.00** |
| `style_fit_amplitude = 0.30` | PASS | 仍然 PASS |
| `data/agents_big5.csv` 的 `source` | `llm_median3` | `sampled_authored` |

五个维度现在都可以单独立论。

**一处行为变化**：profile 里有 `人格与行为倾向` 时，`personality_line` 渲染的是这一段，
**而不是**旧的 `性格与情绪特征` 行——两者在 51 人里有 9 人自相矛盾，而且本来就并排出现在
每条提示词的相邻两行。`agent["personality"]` 本身没动，所以按关键词匹配它的四处子系统
（`dynamic.py` 的原型表与 `is_extrovert`、`finance.py` 的财富驱动、`_heuristic_schedule`
的睡眠提示）行为与之前完全一致。

**怎么观察它生效**：

- 产物 `output/traits/agent_traits.csv`（`personality.output_dir`）：本次运行**实际生效**的五维分数、来源与启用通道；试水时另有 `output/traits/authored_preview.md`，打分那条路另有 `output/traits/calibration_audit.csv`；
- 决策依据里多出「性格倾向」一项；
- 日程 / 日内活动调整 / 目标推导 / 新闻反应的提示词里出现第二人称行为锚句。

**向后兼容**：没有人格数据的 agent、或被关掉的通道，行为与加这个子系统之前**逐位一致**。

设计文档见 [`docs/proposals/2026-08-20-big-five-personality.md`](proposals/2026-08-20-big-five-personality.md)，
反向生成语料的那次改动见 [`docs/proposals/2026-08-21-personality-corpus-rewrite.md`](proposals/2026-08-21-personality-corpus-rewrite.md)。

---

## 6. 新特性一：物理环境感知与反应式重规划

> 模块：`gaworld/world/local_physical.py`、`gaworld/memory/spatial_preferences.py`。
> 设计原则：**全部配置门控、纯规则（无新增 LLM 调用）、向后兼容**——缺数据时每一层自动空转。所有开关在 `CONFIG["environment"]`。
> 完整设计与参数表：[`docs/physical_env_perception_changelog.md`](physical_env_perception_changelog.md)。

它把城市地图里早已定义却从未被调用的节点级 `occupancy`（占用）与 `is_open`（营业）状态接入认知循环，让智能体真正感知并反应**当下身边**的物理环境。分五层（P0–P4）：

### P0 — 局部物理感知

每个 tick 从"谁在哪"重算节点占用，并写入仿真时间使营业判断生效。每个智能体感知前生成当前位置快照（**拥挤度 / 是否营业 / 当地天气 / 异常标记**），可选地以"身边的物理环境：…"片段注入感知上下文。

### P1 — 结构化事件反应

动态行为分类器优先读结构化信号（`type` / `topic` / `impact_tags`）而非关键词猜测，并把 `impact_tags`（mobility、stress、public_service…）作为中断优先级加成。局部物理状态也转为中断候选：拥挤 → "换个不那么挤的地方"；关门 → "改去其他开门的地方"（不可恢复，必须换地点）。

### P2 — 异常作为一等公民

`env/system.py` 给每个事件打 `anomaly` / `anomaly_score`，代表对常态的偏离——日常天气、小波动不算；极端 / 突发 / 应急 / 高严重度才算。异常会提升中断优先级、可强制不可恢复反应、情绪影响更强。局部"人流骤增"（占用率高且较上一 tick 跳变大）会涌现为 `crowd_anomaly` 中断。

### P3 — 当日重规划

`sim/_schedule.py` 的 `replan_affected_interval` 只重排**受影响的连续区间**（改址 / 顺延 / 丢弃），窗口外不动。当胜出中断是持续性异常时，把窗口内被打断的后续活动顺延到窗口之后，而不是只修补当前单步。

### P4 — 结构化空间学习（可持久化）

`spatial_preferences.py` 把**地点绑定**的异常经历（拥挤、关门，不含全城宏观异常）累积为该地点的规避分，按时段加权、按天衰减。规避分超阈值后，`redirect_for_aversion` 把智能体引导到同类、规避更低的替代地点。偏好按 agent 持久化到 `output/memory/agent_<id>_env_preferences.json`（仅 `stateful=True` 时），跨运行保留。

### 怎么开关 / 调参

四个独立开关，把任一块 `enabled` 设为 `False` 即回退该层：

```python
from gaworld.settings import CONFIG
env = CONFIG["environment"]
env["local_physical"]["enabled"]       # P0/P2 涌现异常
env["anomaly"]["enabled"]              # P2 检测
env["replan"]["enabled"]              # P3 区间重排
env["spatial_preferences"]["enabled"]  # P4 学习 + 持久化（还需顶层 stateful=True）
```

常用阈值（默认值）：`local_physical.crowd_busy_ratio=0.6` / `crowd_packed_ratio=0.9`、`anomaly.severity_threshold=0.65`、`replan.window_minutes=120`、`spatial_preferences.avoid_threshold=1.5` / `half_life_days=7.0`。

### 怎么观察它生效

1. 用 `verbose` 日志看感知里是否出现"身边的物理环境"片段；
2. 跑一个会造成拥挤 / 关门 / 突发的场景（见第 9 节 `compare-event`），看日志里有没有"换地方 / 顺延"类中断与重规划记录；
3. `stateful=True` 多跑几天，检查 `output/memory/agent_<id>_env_preferences.json` 里规避分是否累积、是否触发改址。

---

## 7. 新特性二：可复用 Skill 库

> 模块：`gaworld/skills/`。完整设计与 API：[`docs/SKILL_SYSTEM.md`](SKILL_SYSTEM.md)。

与"兴趣 / 技能成长"并行，Skill 库给智能体一批**可复用、可重排版的小技能**，思路接近 Claude Code 的 Skill。每条 Skill 是一个 **Markdown + YAML frontmatter** 文件（`name` / `description` / `triggers` / 正文），两种来源：

- **全局库** `data/skills/*.md`：手写，所有 agent 都能挂载（仓库已自带 `poster-layout-grid.md`、`structured-code-review.md`）；
- **私有库** `output/memory/agent_<id>_skills/*.md`：agent 从自己最近经历**自动提炼**得到。

运行时 Skill 会自动注入到 `perception` 提示词与工作 brief 的 `【可用技能】` 块里，影响认知与工作产物。

### 7.1 加一个全局技能

在 `data/skills/` 新建 `your-skill.md`：

```markdown
---
name: 海报网格排版
description: 用三栏网格 + 单一主色，快速给宣传海报定排版
triggers: [海报, 排版, 设计, poster]
source: global
---

1. 先选一个主色（占面积 ≥ 60%），再选 1 个对比色和 1 个中性色。
2. 把版面切成上 / 中 / 下三带，标题在上、主图在中、信息在下。
3. 留白边距 ≥ 8%；字号梯度按 4:2:1。
```

`skill_id` 就是文件名去掉 `.md`（支持中文）。重启仿真或 `registry.reload()` 后即可被发现。

### 7.2 挂载到某个 agent

```python
from gaworld.skills import SkillRegistry
SkillRegistry().attach_to_agent(agent, "your-skill")   # 全局技能挂到 agent
```

私有技能不需要挂载，`list_for_agent` 会自动算上；同 id 时**私有优先于全局**。

### 7.3 打开"从经历自动提炼私有技能"

默认**关闭**。打开：

```python
CONFIG["memory"]["skill_consolidation"]["enabled"] = True
# every_days=5 每 5 个仿真日跑一次；lookback_days=5；min_episodes=4
```

之后 `run_daily_memory_lifecycle` 会按周期给每个 agent 调一次提炼，写到其私有目录（同名覆盖、越改越准）。

### 7.4 注入开关

```python
CONFIG["skills"]["inject_into_cognition"]   # perception 提示词附 skill 列表（默认 ON）
CONFIG["skills"]["inject_into_work_brief"]  # 工作 brief 附【可用技能】（默认 ON）
CONFIG["skills"]["max_per_prompt"]          # cognition 注入上限（默认 4）
```

关掉开关或没有 skill 时，提示词不变——这是向后兼容的关键。

---

## 8. 新特性三：真实工作任务系统

> 模块：`gaworld/work/`。使用细节：[`docs/REAL_WORK_USAGE.md`](REAL_WORK_USAGE.md)；设计：[`docs/REAL_WORK_DESIGN.md`](REAL_WORK_DESIGN.md)。

让居民根据**职业 / 技能 / 兴趣**去做**真实**的工作，并能在一个 mock 工作机会市场上浏览、接单、结算。产物是真文件：

| deliverable | 产物 | 典型职业 |
|---|---|---|
| `html_landing` | `index.html` | 设计师 |
| `poster_svg` | `poster.svg` | 设计师 |
| `py_script` / `py_test` | `main.py` / `test_main.py` | 程序员 |
| `md_article` | `article.md` | 新媒体 |
| `lesson_plan` | `lesson_plan.md` | 教师 |
| `research_note` | `research_note.md` | 研究者 |

### 8.1 启用

通过配置门控（`gaworld/settings/integrations.py` 的 `real_work` 块）：

```python
CONFIG["real_work"]["enabled"] = True
CONFIG["real_work"]["market"]["enabled"] = True
```

也可用 `dashboard_config.json` / `GAWORLD_CONFIG_OVERRIDES` 等覆盖机制。启用后正常 `python generative_city_sim.py run`，会看到日志：

```
INFO gaworld.work.runtime derived capabilities for N agents (cache=output/work/capabilities.json)
INFO gaworld.work.worker  WorkerPool started (workers=2, timeout=600s)
```

### 8.2 产物在哪

```
output/work/
├── capabilities.json     职业 → 能力 映射缓存（LLM 派生）
├── queue.jsonl           任务队列事件日志
├── market.jsonl          市场事件日志
└── agent_<id>/<task_id>/ 该 agent 该任务的真实产物
```

`agent_<id>` 对应种子 CSV 里的 id，便于溯源。

### 8.3 与其它系统联动

- **兴趣 / 技能成长**：`growth_profile` 里计划发展的技能 / 兴趣会并入能力匹配面（不改 schema）；
- **Skill 库**：router 投递 brief 时用 `chosen_action + activity` 文本匹配 agent 持有的 Skill，最多取 3 个追加到 brief 末尾——**adapter 无需改动**，Skill 指导会自然进入工作上下文。

### 8.4 常用旋钮（`CONFIG["real_work"]`）

| 项 | 默认 | 作用 |
|---|---|---|
| `max_concurrent_tasks` | 2 | 后台并发的 LLM adapter 数（调高更快但更贵） |
| `task_timeout_seconds` | 600 | 单 adapter 超时（本地 ollama 慢可调到 1200） |
| `market.max_taken_per_agent_per_day` | 2 | 每 agent 每仿真日最多接单数 |
| `market.browse_probability_base` | 0.15 | 浏览市场基础概率 |
| `market.expire_after_sim_days` | 5 | 过期阈值 |

扩展任务池：往 `gaworld/work/market_seed.json` 加条目；写自定义 adapter 见 `REAL_WORK_USAGE.md` §6。

> **复现性提醒**：adapter 内不要碰全局 `random`，需要随机用 `random.Random(seed)` 局部实例，否则在 `max_concurrent_tasks > 1` 时会破坏 `random_seed` 复现性。

---

## 9. 事件对照实验

GAWorld 的招牌高级功能：在**有事件 / 无事件**两条分支并行跑并出对比报告。

```bash
python generative_city_sim.py compare-event \
  --event-name "临时交通限行" \
  --event-description "主干道限行导致通勤时间上升并影响出行决策" \
  --event-day 2 \
  --event-time 09:00 \
  --sim-days 3 \
  --llm-provider openai_gpt \
  --seed 42
```

结果写入 `output/comparisons/<时间戳_事件名>/`：

```
comparison_summary.md     ← 指标摘要（最重要）
comparison_metrics.csv    ← baseline / event / delta 全明细
with_event/    ...        ← 有事件分支（logs / memory / state / intervention）
without_event/ ...        ← 无事件分支（对照）
```

报告同时含常规状态指标（情绪 / 压力 / 经济安全 / 出行成本变化）与干预指标（stance / toxicity / misinformation / cross_viewpoint 差异）。`--seed` 保证可复现。

> 这是观察**新特性是否生效**的好入口：选一个会造成拥挤 / 关门 / 应急的事件，对比两分支的重规划与地点规避行为差异。

### 9.1 平行世界：两个以上分支

`compare-event` 固定分叉成两条支线并比较**最后一行**。当你要问的是别的问题——
几种强度哪个更狠、两段历史**从哪一步**开始分开、这件事究竟落在**谁**身上——
就用平行世界：一次实验最多 8 个世界，共用同一批居民、同一个种子、同一个天数和模型，
唯一的区别是发生了什么。

```bash
cat > worlds.json <<'JSON'
{
  "name": "限行强度剂量反应",
  "sim_days": 4,
  "seed": 42,
  "worlds": [
    {"label": "基准世界", "events": []},
    {"label": "轻度限行", "events": [
      {"day": 2, "time": "07:00", "name": "临时交通限行",
       "description": "早晚高峰单双号限行，通勤时间小幅增加。"}]},
    {"label": "重度限行", "events": [
      {"day": 2, "time": "07:00", "name": "全面交通管制",
       "description": "主干道全面管制，部分居民无法到岗。"}]}
  ]
}
JSON

python generative_city_sim.py parallel-worlds --spec worlds.json --fast
```

结果写入 `output/parallel_worlds/<时间戳_实验名>/`：

```
divergence_summary.md      ← 人读的结论（最先看这个）
divergence_metrics.csv     ← 逐世界 × 逐指标的 baseline / 本世界 / Δ 明细
report.json                ← 完整报告（面板读的就是它）
experiment.json            ← 清单：spec + 各世界路径 + 运行状态
worlds/<world_id>/ ...     ← 每个世界一棵完整的仿真产物树（含 run.log 与可回放 trace）
```

比 `compare-event` 多出来的三件事：

- **逐步偏离度**：每一步该世界与基准的平均绝对差，以及它第一次**稳定**越过阈值的那一步
  （只越一步就掉回去的算 LLM 随机性，不算分叉）。
- **逐人影响**：同一个居民在两个世界里的终局差距，按大小排序——人群均值会把个体抹平。
- **世界还能带 `config` 补丁**：改的是规则而不是事件，用来做税制 / 环境参数的对照。
  补丁深合并，只写要改的那片叶子；种子、天数、居民名单和各世界的输出目录是保留键，
  写了会直接报错（它们是让比较成立的对照基准和隔离边界）。

⚠️ **先跑安慰剂**。GAWorld 的认知由 LLM 驱动，配置完全相同的两个世界也不会跑出
完全相同的历史，偏离度里天然含一份与事件无关的噪声。加一个"发生了但没有实质影响"的
事件世界，它的偏离度就是噪声底噪；真实干预必须明显高过它，结论才成立。

完整教程（面板导览、读图方法、剂量反应实验、API 速查）见
[平行世界教程](PARALLEL_WORLDS_TUTORIAL.md)。

---

## 10. 访谈与 RAG 注入

**访谈单个智能体**（基于其当前记忆与状态回答）：

```bash
python generative_city_sim.py interview --agent-id 31 --question "你今天为什么选择这个行动？"
python generative_city_sim.py interview --agent-id 31 --questions-file questions.txt
```

**注入外部知识**（改变认知）：

```bash
python generative_city_sim.py rag-add --agent-id 31 \
  --text "周末更倾向于骑行和逛书店" --timestamp "2026-02-18 09:30" --source "manual"

python generative_city_sim.py rag-import --agent-id 31 \
  --file output/test_extra_info.txt --source "profile_notes"
```

**从社交内容创建新智能体**：

```bash
python generative_city_sim.py create-agent-from-social --url "https://weibo.com/..."
python generative_city_sim.py create-agent-from-social --file output/source_page.txt --name "新智能体"
```

---

## 11. 分布式 relay：多机通信

> 模块：relay 客户端 `gaworld/distributed/comm.py`（`DistributedRelayClient`）、relay 服务器 `gaworld/apps/distributed_comm_server.py`。
> 设计原则：**配置门控、连不上自动降级（`fail_fast=False` 时静默空转）、向后兼容**——不开启或单机运行完全不受影响。所有开关在 `CONFIG["distributed"]`。

当一次实验的智能体规模超过单机算力，或你想把不同人群放到不同机器上跑时，可以开启**分布式模式**：用一台 relay 服务器做"集合点"，每台机器（node）只跑自己负责的那部分智能体，跨机器的智能体之间通过 relay 交换消息（收件箱 / 跨机通信）。收到的远端消息会以「跨机器通信消息：…」片段注入对方的**感知上下文**，从而影响其后续 LLM 决策——这是一种规则化的轻量通信，发送侧不额外消耗 LLM。

### 11.1 架构

```
        ┌───────────────── relay 服务器 (HTTP, :8877) ─────────────────┐
        │     目录登记 · 消息收发 · 状态持久化 relay_state.json          │
        └────────▲──────────────────────────────────────▲──────────────┘
                 │ register / poll / send                │
        ┌────────┴────────┐                     ┌────────┴────────┐
        │  Node A (机器1)  │  ←──— 跨机消息 ——──→ │  Node B (机器2)  │
        │ local_agent_ids │                     │ local_agent_ids │
        │   = [1, 2, 3]   │                     │   = [4, 5, 6]   │
        └─────────────────┘                     └─────────────────┘
```

- **relay 服务器**：独立 HTTP 服务，默认 `0.0.0.0:8877`，把目录与消息持久化到 `output/distributed/relay_state.json`（最多保留 `max_messages` 条，默认 20000）。主要端点：`/health`、`/register`、`/directory`、`/message/send`、`/message/poll`、`/snapshot`。
- **relay 客户端**：每个仿真进程按 `CONFIG["distributed"]` 建一个 `DistributedRelayClient`，挂在仿真循环上——启动时 `register_agents` 登记本机智能体并换回**全集群目录**；每个 tick `poll_messages` 拉取发给本机智能体的来信（每人每步最多 `max_inbound_per_step` 条）；每个智能体动作后以 `send_probability` 概率 `send_agent_messages`，向某个远端智能体投递一条由其活动/反思/结果模板化而成的更新（每步最多 `max_outbound_per_step` 条）。
- **cluster（集群）**：逻辑分组，只有**同一 cluster** 的智能体能互相看见与通信；`node_id` 标识机器（留空自动用 `主机名-pid`）。
- **智能体分区**：每台机器用 `local_agent_ids` 指定自己负责的子集（开启分布式且非空时**覆盖**顶层 `agent_ids`）；远端对端默认从 relay 目录自动发现，也可用 `peer_agent_ids` 显式钉死。

> 同一台 relay 服务器也是 OpenClaw 外部智能体接入的后端（额外带 token 鉴权与 tick 时钟同步），那部分见 [`docs/OPENCLAW_INTEGRATION.md`](OPENCLAW_INTEGRATION.md)。

### 11.2 配置（`CONFIG["distributed"]`）

| 字段 | 默认 | 作用 |
|---|---|---|
| `enabled` | `True` | 本机是否参与分布式通信 |
| `cluster` | `"default"` | 集群名，**所有机器必须写一致** |
| `node_id` | `""` | 机器标识；留空自动 `主机名-pid` |
| `local_agent_ids` | `[]` | 本机负责的智能体子集；开启分布式且非空时覆盖 `agent_ids` |
| `peer_agent_ids` | `[]` | 显式远端对端；为空则从 relay 目录发现 |
| `send_probability` | `0.18` | 每次动作向远端发消息的概率 |
| `max_outbound_per_step` | `1` | 每步最多外发条数（设 `0` 则只收不发） |
| `max_inbound_per_step` | `3` | 每个智能体每步最多注入的来信条数 |
| `message_max_chars` | `160` | 单条消息截断长度 |
| `fail_fast` | `False` | relay 出错时抛异常，还是静默降级 |
| `relay.base_url` | `http://127.0.0.1:8877` | 客户端连接的 relay 地址 |
| `relay.timeout` | `3` | HTTP 超时（秒） |
| `server.host` / `server.port` | `0.0.0.0` / `8877` | `serve-distributed` 默认绑定 |
| `server.state_path` | `output/distributed/relay_state.json` | 服务器状态持久化路径 |
| `server.max_messages` | `20000` | relay 最多保留的消息条数 |

### 11.3 两台机器跑起来

**① 在其中一台（或单独一台）启动 relay 服务器：**

```bash
python generative_city_sim.py serve-distributed --host 0.0.0.0 --port 8877
# 看到 [distributed-relay] listening on http://0.0.0.0:8877 即成功
```

**② 在每个 node 上配置**（改 `config.py`，或用 dashboard / `GAWORLD_CONFIG_OVERRIDES` 覆盖）：

```python
CONFIG["distributed"]["enabled"]           = True
CONFIG["distributed"]["cluster"]           = "myexp"        # 所有机器写同一个
CONFIG["distributed"]["relay"]["base_url"] = "http://<relay-ip>:8877"  # 远端机器填 relay 的可达 IP
# 每台机器分到不重叠的子集：
CONFIG["distributed"]["local_agent_ids"]   = [1, 2, 3]      # Node A
# CONFIG["distributed"]["local_agent_ids"] = [4, 5, 6]      # Node B
```

**③ 每个 node 各自正常运行：**

```bash
python generative_city_sim.py run
```

Node A 的智能体触发外发时，消息按 `to_agent` 投到 relay；Node B 的智能体在下一次 poll 时收到，并在感知里看到「跨机器通信消息：…」。

> **想先在单机验证？** 启动 relay 后开两个终端，各自 `enabled=True`、`base_url=http://127.0.0.1:8877`、`local_agent_ids` 设成两个不重叠子集，即可在一台机器上模拟两个 node。

### 11.4 怎么观察它生效

```bash
curl http://<relay-ip>:8877/health                      # {"ok": true}
curl http://<relay-ip>:8877/snapshot                    # 集群数 / 已登记智能体数 / 消息总数
curl "http://<relay-ip>:8877/directory?cluster=myexp"   # 看到各机器登记的全部智能体
```

再配合 `GAWORLD_LOG_MODE=verbose` 跑，感知上下文里应出现「跨机器通信消息」片段；`output/distributed/relay_state.json` 里的消息数也会随运行增长。

### 11.5 常见坑

- **互相看不见** → 多半是 `cluster` 名不一致，或 `base_url` 还停在默认的 `127.0.0.1`（远端机器必须填 relay 的可达 IP，并在防火墙放行该端口）。
- **智能体重复** → 各机器的 `local_agent_ids` **不要重叠**，每个智能体只应活在一台机器上。
- **完全没有跨机消息** → 确认 relay 已启动且各 node `enabled=True`；调试期把 `fail_fast` 设为 `True`，连接问题会直接抛错而不是静默降级。
- **只想收不想发**（如某台机器只作观察）→ 把 `max_outbound_per_step` 设为 `0`。

---

## 12. Dashboard 使用指南

GAWorld 自带一个本地 Dashboard，用网页做配置、运行控制、记忆查看与访谈，适合不想敲命令行的场景。

启动：

```bash
python generative_city_sim.py dashboard --port 8766
# 浏览器打开 http://127.0.0.1:8766/dashboard
```

功能面板：

| 面板 | 作用 |
|---|---|
| 配置编辑 | 改仿真参数（天数、LLM 路由等） |
| 长时段快进 | 工具栏勾选「长时段快进」→ 每步一条简报的快进模式；旁边「随机性」滑杆控制突发事件频率与状态波动幅度（配合较大的仿真天数，见 [3.1](#31-长时段快进fast-forward跑-10--60--600-天)） |
| 步长单位 | 工具栏「步长单位」下拉：天 / 月 / 年。选月或年后，左边的时长字段会变成「仿真月数」/「仿真年数」，填 10 + 年就是跑十年（见 [3.2](#32-大跨度模拟以月年为时间单位)） |
| Profile 编辑 | 改智能体画像 |
| 运行控制 | 启动 / 停止仿真 |
| 轨迹回放 | 可视化查看智能体移动轨迹 |
| 记忆查看 | 检查单个智能体的记忆内容 |
| 访谈执行 | 对智能体提问并查看回答 |
| 日志查看 | 实时查看运行日志 |
| 人生事件 | 给指定居民排一件事（生日 / 疾病 / 换工作 / 失业 / 关系破裂……），可覆盖标题、描述、强度与发生时刻。**「换工作」「失业」不是纯文本事件**：它们会真的改写这个人的职业与收入——选「换工作」时会多出一个「新职业」输入框，留空则自动跨行业转岗（见 [FEATURES](FEATURES.md) 的「就业事件」一行） |
| 外部系统 | 观察并编辑世界本身：货币系统、外部环境生成器、对外服务连接（见 [12.3](#123-外部系统观测台)） |

**配置覆盖**：Dashboard 的修改写入 `dashboard_config.json`，运行时**覆盖** `config.py` 的基础配置（`config.py` ← 基础，`dashboard_config.json` ← 覆盖）。想恢复原始值，删除 `dashboard_config.json` 即可。

### 12.1 Agent Studio（单智能体构建/查看器）

控制台工具栏点 **「Agent Studio ↗」**，或直接打开
`http://127.0.0.1:8766/site/dashboard/studio.html`。它聚焦**一个**智能体，
分七步展示与编辑，字段全部对应 GAWorld 的真实种子模型：

| 步骤 | 内容 | 数据来源 |
|---|---|---|
| 1 身份 | 姓名、性别、年龄、户籍、居住地、叙事 profile | 状态 CSV + profile MD |
| 2 状态 · 性格 | 九个 `[0,1]` 状态变量（滑块 + 可编辑雷达） | 状态 CSV |
| 3 能力 · 技能 | 全局技能库 | `data/skills` |
| 4 记忆 | 情节/习惯/意图/日程计数 + 记忆图谱 | `output/memory` |
| 5 社交 · 关系 | 真实 Dunbar 分层（inner/close/acquaintance/weak）+ 亲密度排序；**家庭编辑面板**（婚姻状态 / 伴侣 / 子女 / 同住长辈） | `output/memory/*_relationships.json`；家庭见 [12.5](#125-家庭看板卡片与工作台编辑面板) |
| 6 行为 · 目标 | 驱动行为的状态拨盘 | 状态 CSV |
| 7 复核 · 部署 | 摘要、可选采访、保存、用此居民运行仿真 | — |

**写回规则**：状态变量与身份写入状态 CSV
（`data/hangzhou_agents_state_init.csv`）并**同步**进 profile MD 的
`**核心状态变量**` 与 `**研究增强变量初始化**` 两处（CSV 为权威源，避免漂移）；
叙事编辑写 profile 块；「创建」追加一行 CSV + 一个 profile 块（复用导入-agent 的
格式，保留 BOM）。社交与财务面板读运行产物，未跑仿真时优雅降级为占位。

**后端 API**（`gaworld/apps/dashboard_server.py`）：
`GET /api/agents/{id}/state`、`GET /api/agents/{id}/detail`、`GET /api/skills`、
`POST /api/agents/{id}/state`、`POST /api/agents`（创建）。测试见
`tests/test_dashboard_studio.py`。

---

### 12.2 Population Studio（人口生成与群体模拟）

Agent Studio 造一个居民，Population Studio 造一座小镇并按群体模拟它。
控制台「**人口与群体**」页签，或直接
`http://127.0.0.1:8766/site/dashboard/population.html`。

五个步骤：**选模板 → 人口结构 → 心理状态 → 跑模拟 → 检查结果**。

- 第 1 步选中预设后会显示它是什么人口、什么时候该用它；随机种子的说明是
  「换个数字就是另一批人，填回同一个数字还是原来那批人」。
- 第 2 步给出**目标 vs 实际对照表**：达不成的旋钮会显示相对偏差，而不是假装达成了；
  同时有年龄金字塔、收入洛伦兹曲线、社交网络度分布。
- 第 3 步的雷达图画的是**均值 + P25–P75 包络**——群体是一个分布，只画均值多边形会误报。
- 第 4 步可以选**后端模型**（`gaworld/llm/providers.py` 里配好的 provider，例如本地 ollama），
  跑完显示每日群体简报与**实测** LLM 调用数。
- 第 5 步把 L1–L4 判定翻译成一句话结论 + 「可以用来 / 不要用来」清单，
  并把写出的三个人口文件做成可直接点开的链接（附前几行预览）。

所有指标都是**中英文双标**（「压力 stress」），标签来自 `GET /api/population/schema`
的 `labels` 字段——面板不再自己抄一份中文名，同一个量在不同卡片里不会长成两个样子。

右侧常驻**参数体检**：不生成任何人、瞬时返回、参数冲突时直接指出该动哪个旋钮并给出可达区间。

**后端 API**（`dashboard_server.py` 转发到 `gaworld/apps/population_api.py`）：
`GET /api/population/schema`、`POST /api/population/preview`、
`POST /api/population/generate` → `job_id`、`GET /api/population/jobs/{id}`、
`POST /api/population/group-run`、`POST /api/population/validate`。
生成与模拟都是异步 job。测试见 `tests/test_dashboard_population.py`。

---

### 12.3 外部系统观测台

> 本节是**摘要**。完整教程（含干预机制原理、守恒记账、完整参数与 API）见
> [外部系统教程](EXTERNAL_SYSTEMS_TUTORIAL.md)。

前两个面板对着 **agent**；这个面板对着**世界本身**。控制台「**外部系统**」页签，
或直接 `http://127.0.0.1:8766/site/dashboard/external.html`。

三个子面板，每个都是左边观察、右边编辑：

| 子面板 | 观察 | 编辑 |
|---|---|---|
| **货币系统** | 周期阶段、通胀、失业、累计物价指数、企业/政府/银行三个部门池、货币守恒曲线与漂移、财富分布与基尼、全体日收支 | 对**运行中**仿真的干预（改宏观状态、给部门池注资）+ 完整 `CONFIG["economy"]` 树 |
| **外部环境** | `timeline.jsonl` 里最近若干天的自然/经济/政策/科技事件，带严重度与影响标签 | `external_environment`、`environment`、`policy_events`（排定的政策冲击） |
| **对外服务** | 外部环境服务与分布式中继的即时连通性探测、LLM 路由、新闻缓存状态 | 上述服务配置 + `external_rag`、`news`、`llm.routing`（模型清单只读，密钥不暴露） |

**配置表单是从配置自身长出来的**：`economy` 一棵子树就有约 120 个叶子，面板按 JSON
形状渲染控件，后端按现有配置的类型把补丁强制成形（`"0.09"` → `0.09`），不认识的键
丢弃并在响应里回报。约 150 个旋钮因此可编辑，且加一个新旋钮不需要动面板代码。

**不需要背名词**：几乎每个指标和旋钮旁边都有一个 **?**，鼠标移上去给一句白话说明，说的是
「这个数意味着什么、改了会怎样」——比如失业率会明确告诉你它并不会真的让谁丢工作。
说明存在 `external.js` 的 `HELP` 表里，按「完整路径 → 末段键名」两级查找，所以社保里的
`unemployment_rate` 和宏观里的失业率不会被解释成同一件事。复用的是 `help.js`
（`data-help` 属性 + 深色浮层，支持键盘聚焦）。

**两种"改"要分清**：

- **配置**写进 `dashboard_config.json`，**下一次**运行生效，适合做对照实验；
- **干预**写进 `output/economy/interventions.json`，跑着的仿真在**下一个日边界**消费它。

干预不去写 `output/economy/macro_state.json`——那是 run 的*产物*，仿真在
`on_simulation_start` 从配置重建宏观状态、从不回读它，改它会看起来生效而实际无效。
干预排在周期推进**之后**执行，所以你设的通胀率就是那天真正被使用的值。给部门池注资会
同步移动守恒基准 `initial_system_total`，因此每日审计把有意的注资记成注资，而不是
报成 drift（漏钱）。

**后端 API**（`dashboard_server.py` 转发到 `gaworld/apps/external_systems_api.py`）：
`GET /api/external-systems/{overview,health,interventions}`、
`POST /api/external-systems/{config,interventions,interventions/cancel}`。
测试见 `tests/test_dashboard_external_systems.py` 与 `site/dashboard/external.test.js`。

---

### 12.4 平行世界实验台

控制台「**平行世界**」页签 → `http://127.0.0.1:8766/site/dashboard/worlds.html`。
[§9.1](#91-平行世界两个以上分支) 的交互式版本：**左边设计，右边观测**。

左边定义世界之间差什么：实验设置（天数 / 种子 / 居民 / 模型 / 并发度，对所有世界一致）、
世界卡片（改名、设为基准、复制、删除）、每个世界的事件列表（第几天 / 几点 / 名称 / 描述）。
三个模板（裁员冲击 / 交通限行强度 / 安慰剂对照）可以直接点开就改。

右边回答于是差出了什么：

| 卡片 | 读什么 |
|---|---|
| 分叉图 | 线离主干的远近＝偏离程度；空心点＝分叉那一步；实心点＝事件位置 |
| 走向对比 | 某个指标的人群均值走向，可切换指标、可只看与基准的差、鼠标悬停读数 |
| 偏离基准的距离 | 逐步偏离曲线 + 分叉阈值线 |
| 终局差异 | 各世界每个指标相对基准的终值 / 均值差，按绝对差排序 |
| 谁被改变了 | 逐人偏离度，按大小排序 |

图例上点掉某个世界，四张图会同时把它藏起来。底部「逐帧回放」链接把任意一个世界的轨迹
送进[§12 的仿真回放页](#12-dashboard-使用指南)——每个世界都是一次完整仿真。

运行时底部逐个世界显示进度（`排队中 → 运行中 D2 → 完成`）。一个世界失败不影响其它世界，
失败原因（配额、连不上模型等）原样显示，完整日志在 `worlds/<world_id>/run.log`。
同一时刻只允许一个实验在跑。

历史下拉里能打开任何一次旧实验，包括**已有的 `compare-event` 结果**——它们会被当场适配成
两世界实验用新图表打开，磁盘上什么都不改；跑到一半死掉、没留下状态数据的目录会标成
「（无数据）」列出来，而不是藏起来。

---

### 12.5 家庭：看板卡片与工作台编辑面板

家庭在面板上有两个入口，读的东西**故意不一样**——因为它们问的不是同一个问题。

**主面板「家庭结构」卡片**（在「人物设定」旁边）问的是"这一轮跑的是什么家庭"，
所以它读 recorder 落盘的运行产物：户数 / 仿真内夫妻数 / 有子女人数 / 单身占比、
户型分布条，以及当前选中居民的同住成员、不同住的家人和本轮累计的养育赡养支出。
没跑过仿真时它是一张空卡片，不是报错。

**工作台第 5 步的家庭编辑面板**问的是"我保存之后，下一轮会变成什么"，
所以它**重新推导**一遍分配并把结果显示给你。

这里有个必须先说清楚的约束：**家庭在每次运行开始时按 (名单, 配置, 种子) 重新推导**。
所以工作台里的编辑**不能是"改结果"**——那样的修改会在下一次运行时被覆盖掉。
面板写的是**覆盖项**，落到 `data/family_overrides.json`，分配器在**分配过程中**读它。
因此你指定的家庭一旦保存，户型、共居、日程、账目会自动全部跟着走。

能改四项，每项都有"自动"这一档：

| 项 | 语义 |
|---|---|
| 婚姻状态 | 留空 = 按年龄段抽样；否则固定为未婚 / 已婚 / 离异 / 丧偶 |
| 伴侣 | 自动 / **无伴侣**（即使状态是已婚也不生成）/ 指定名单里的另一位居民 / 填一个场外人物 |
| 子女 | 不勾选 = 按生育率抽样；勾选后留空 = **固定为没有孩子**；否则逐个填姓名/性别/年龄/是否同住 |
| 同住长辈 | 同上 |

"不勾选"和"勾选后留空"是两件事，别搞混：前者是"你来抽"，后者是"我说了没有"。

**指定仿真内配偶是对另一个人的声明**：双向生效，两人自动共享住处，
原本和对方配对的居民会自动退回场外配偶，并且**绕过年龄差限制**
（你是在故意覆盖人口学，匹配器不该偷偷否决你）。两条互相矛盾的指定按居民编号
从小到大解析，冲突会直接显示在面板上。

点「保存并预览」写盘并立刻回显新结果；点「恢复自动生成」删掉这条覆盖。
两个动作都只影响**下一次运行**，正在跑的那一轮不受影响。

后端 `gaworld/apps/family_api.py`：`GET /api/family/overview`（卡片）、
`GET /api/family/preview?agent_id=N`（编辑器）、`POST /api/family/override`。

---

## 13. 大规模人群：人口合成与群体模拟

> 本节是**摘要**。完整教程（含全部参数、成本表、判定阈值的来龙去脉）见
> [群体模拟教程](GROUP_SIMULATION_TUTORIAL.md)。

个体模拟里每个 agent 每天要走多次完整认知流水线——500 人跑一天约 **10 万次 LLM 调用**。
群体模式加了一个更粗的层：把人口划分成 **cohort（群体）**，每群每天只花 **1 次** LLM 调用，
同时每天按预算把一小批个体提升到完整保真度。

### 13.1 三条命令

```bash
# 造一座 500 人的小镇（不写文件，只看结果）
python -m gaworld.population --preset cn_county_town --size 500 --seed 42 --check

# 按群体模拟 7 天（零 LLM 成本）
python -m gaworld.group --size 500 --days 7 --no-llm

# 验证这个近似能回答哪类研究问题（分水岭层不过时退出码为 1）
python -m gaworld.group.validate --size 100 --days 14 --network-coupling 0.7
```

写出文件用 `python -m gaworld.population --size 500 --name my_town --out data/town`，
产出的状态 CSV 与 profile Markdown **与现有格式完全一致**，可以直接填进
`CONFIG["csv_path"]` / `CONFIG["md_path"]`，`build_agent` 无需改动。

### 13.2 成本从哪来

500 人 × 30 天，逐次实测（全个体基准 297 万次）：

| 实体化预算 | cohort 层 | 实体化层 | 合计 | 相对全个体 |
|---|---|---|---|---|
| 0 | 1,140 | 0 | 1,140 | 2605× 省 |
| **20**（默认） | 1,140 | 118,800 | 119,940 | **25× 省** |
| 50 | 1,140 | 297,000 | 298,140 | 10× 省 |

**cohort 层几乎免费，成本几乎完全由 `--budget` 决定。** 调群体粒度对成本影响很小。

### 13.3 什么时候能用、什么时候不能

| 研究问题 | 适合？ |
|---|---|
| 人口分布级指标、政策处理效应与子群异质性、极端个体占比 | ✅ |
| 观点扩散、极化、少数派引爆 | ⚠️ 必须开网络耦合并跑验证门确认 |
| 单个居民的完整生活叙事 | ❌ 用个体模式，或把 TA 设为 `--focal` |

这不是猜的：验证门的四层判定会直接告诉你。**L2（网络级）与 L4（因果响应）是分水岭。**

关键实测：不开网络耦合时 L2 一定不通过，且**不是调参能解决的**——要过 L2 得实体化 80% 以上
人口，那已经等于放弃群体层。开启群内零均值的图耦合项（`network_coupling=0.7`）后四层全过。

> ⚠️ 0.7 是针对验证门内那个参照过程标定出来的，**不是普适常数**。换成真实 LLM 驱动的个体层
> 后必须重新标定。默认值是 `0.0`（关闭）。

### 13.4 顺带：一个与群体无关的性能修复

个体模式的 tick 数其实随 agent 数**超线性**增长：主时间线是固定网格与每个 agent 的
LLM 自拟日程时间的**并集**，而 LLM 生成的 `HH:MM` 没有对齐逻辑。

```python
CONFIG["time_step_minutes"] = 30
CONFIG["time_grid_snap"] = True    # 默认 False
```

开启后 tick 数恒等于 `1440 / step`，与人口规模无关。
**只设 `time_step_minutes` 不够**——那只给 tick 数加了个下界。默认关闭是因为它会改变日内时序。

---

## 14. 配置与开关总表

基础配置入口 `config.py`（实际分层在 `gaworld/settings/`）。常用字段：

| 配置 | 作用 |
|---|---|
| `agent_ids` / `sim_days` / `seconds_per_day` | 参与 agent、仿真天数、每日现实秒数 |
| `long_run` | **新**：长时段快进（每步一条简报、跳过日内时刻循环；`--fast-forward` 等价；`long_run.randomness` 控制突发事件与波动，见 [3.1](#31-长时段快进fast-forward跑-10--60--600-天)）；`long_run.unit` = `day`/`month`/`year` 决定一步多长，跑数年以上必须用月或年，见 [3.2](#32-大跨度模拟以月年为时间单位) |
| `llm.routing.default` / `llm.routing.tasks` | 默认 provider / 按任务覆盖 |
| `economy` | 个税、社保、恩格尔消费、投资、宏观周期、冲击、部门池守恒、信贷（`credit`）、agent 间路由（`routing`）、熟人借贷（`friend_loans`）；**可在控制台「外部系统」页签里可视化编辑**，见 [12.3](#123-外部系统观测台) |
| `family` | **新**：家庭与户——婚姻状态分布、配对（含 `in_sim_pair_share` 这个建模旋钮）、生育、共居、家庭责任、家庭财务、家庭事件与户内情绪传染；**可在配置面板「家庭与户」分区里可视化编辑**，逐人指定见 [12.5](#125-家庭看板卡片与工作台编辑面板) |
| `interests` | 兴趣 / 技能成长（开关、上限、插入倾向、持久化、日终衰减 `decay`、兴趣集演化 `evolution`） |
| `personality` | **新**：大五人格（OCEAN，插件 `big_five`，默认 ON）——`channels` 分 `rules` / `prompt` / `voice` 三条通道开关，`strength=0` 即对照组，另有 `style_fit_amplitude` / `modifier_band` / `residual_ratio`、锚句渲染 `prompt.*`、个人情绪基准线 `emotion_baseline.*`、无标定文件时的人群先验 `sampling.*`，见 [5.8](#58-大五人格) |
| `dynamic_behavior` | 动态行为系统开关 |
| `environment.local_physical` / `.anomaly` / `.replan` / `.spatial_preferences` | **新**：物理感知与反应式重规划 |
| `external_environment` | 外部环境生成器：四类事件的日概率、天气池、生成方式（`llm` / 规则）、日内突发（面板可编辑，见 [12.3](#123-外部系统观测台)） |
| `external_environment_service` / `environment_server` / `external_rag` / `news` | 对外服务连接：远端环境服务、外部信息注入、新闻源（面板可编辑并可即时探测连通性） |
| `skills` | **新**：Skill 库（全局目录、注入开关、单提示上限） |
| `memory.skill_consolidation` | **新**：经验 → Skill 提炼（默认 OFF） |
| `real_work` | **新**：真实工作任务系统 |
| `intervention` | PolicySim 风格干预评估 |
| `policy_events` / `distributed` | 政策事件 / 多机通信（relay，详见第 11 节） |
| `time_grid_snap` | **新**：日程对齐到 `time_step_minutes` 网格，tick 数恒为 `1440/step`（默认 OFF；只设 `time_step_minutes` 不够，见 [13.4](#134-顺带一个与群体无关的性能修复)） |
| `group.enabled` | **新**：`GroupPlugin` — 在个体运行中发布 cohort 划分与逐日漂移到 recorder，只观测不改行为 |

日志模式：`GAWORLD_LOG_MODE=simple|verbose`，`GAWORLD_LOG_LEVEL=DEBUG` 看 token / 延迟。

> Dashboard 的修改写入 `dashboard_config.json`，运行时覆盖 `config.py`；模型路由不符预期时同时检查这两处。

---

## 15. 输出文件地图

```
output/
├── logs/        run.log（完整）、agent_<id>.log
├── memory/      agent_<id>.json、agent_<id>_episodes.jsonl
│                agent_<id>_growth.json、growth_profiles.json
│                agent_<id>_env_preferences.json   ← 新：地点规避偏好
│                agent_<id>_skills/*.md            ← 新：私有 Skill
│                vector_db.sqlite
├── economy/     daily_ledger.csv（含 debt 列）、wealth_snapshot.csv、macro_state.json
│                sectors.json、conservation_audit.csv    ← 新：部门池 + 每日守恒审计
│                interventions.json                      ← 新：货币干预队列（面板写入，仿真在日边界消费）
│                agents/agent_<id>_ledger.csv、agent_<id>_snapshot.json
├── environment/ timeline.jsonl
├── intervention/intervention_metrics.csv
├── network/     social_network.png
├── records/     family.{summary,household,agent,finance}.jsonl  ← 新：家庭结构与家庭开支
│                （以及其它插件的统一事件流）
├── traits/      agent_traits.csv        ← 新：本次运行实际生效的五维人格分、来源与启用通道
│                calibration_audit.csv   ← 新：标定脚本产出的审计表
├── visualization/ simulation_trace.json、latest_frame.json
├── work/        capabilities.json、queue.jsonl、market.jsonl、agent_<id>/<task_id>/  ← 新
├── comparisons/ <事件名>/comparison_summary.md、comparison_metrics.csv
└── parallel_worlds/ <实验名>/divergence_summary.md、divergence_metrics.csv  ← 新：平行世界
                     report.json、experiment.json、worlds/<world_id>/（每个世界一棵完整产物树）
```

---

## 16. 常见问题

**Q: 报错 API key 缺失** — 检查环境变量是否设置，且 `config.py` 的 `llm.routing.default` 指向已配置的 provider。

**Q: 运行很慢** — 调小 `sim_days`、减少 `agent_ids`、关闭 `intervention` / `dynamic_behavior`、用更快的模型；启用了 `real_work` 可调低 `max_concurrent_tasks` 或先关掉它。

**Q: 改了配置后行为异常** — 仿真有状态记忆，先 `reset` 再 `run`。

**Q: 新特性看起来没生效** —
1. 物理感知：确认 `CONFIG["environment"]["local_physical"]["enabled"]=True`，用 `verbose` 看感知里有没有"身边的物理环境"；P4 还需顶层 `stateful=True` 才会落盘。
2. Skill 注入：确认 `CONFIG["skills"]["inject_into_*"]=True` 且该 agent 真的持有 / 已挂载 Skill。
3. 真实工作：确认 `CONFIG["real_work"]["enabled"]=True` 且看到 `WorkerPool started`；agent 接不到单多半是市场里没有匹配其 `job_label` 的 job 或当日配额用完。

**Q: 自动提炼私有 Skill 不产文件** — 默认 OFF，需要 `CONFIG["memory"]["skill_consolidation"]["enabled"]=True`；且最近 episodes 不足 `min_episodes`（默认 4）会跳过。

**Q: Dashboard 改了配置后想恢复原值** — Dashboard 的修改写在 `dashboard_config.json` 并在运行时覆盖 `config.py`；删除该文件即可回到 `config.py` 的原始配置。

**Q: 记忆文件看起来是乱码** — 它是 JSON 格式，用 `cat output/memory/agent_31.json | python -m json.tool` 格式化查看。

**Q: Python 完整测试套件报错** — 部分用例依赖 Python ≥ 3.11，建议在 3.11+ 跑 `pytest tests`。

---

## 17. 命令速查表

```bash
# 基本
python generative_city_sim.py run                  # 运行仿真
python generative_city_sim.py run --sim-days 600 --fast-forward  # 长时段快进：每天一条日简报
python generative_city_sim.py run --sim-months 24  # 大跨度：一个月一步，每人一条月度简报
python generative_city_sim.py run --sim-years 10   # 大跨度：一年一步（10 年 × 50 人 ≈ 500 次调用）
python generative_city_sim.py reset                # 重置（从 Day 1）
python generative_city_sim.py --help               # 帮助

# 服务
python generative_city_sim.py dashboard --port 8766
python generative_city_sim.py serve-viz --port 8000
python generative_city_sim.py serve-distributed --host 0.0.0.0 --port 8877

# 访谈 / RAG / 创建
python generative_city_sim.py interview --agent-id 31 --question "..."
python generative_city_sim.py rag-add --agent-id 31 --text "..."
python generative_city_sim.py rag-import --agent-id 31 --file ...
python generative_city_sim.py create-agent-from-social --url "..."

# 实验 / 地图
python generative_city_sim.py compare-event --event-name "..." --sim-days 3 --seed 42
python generative_city_sim.py parallel-worlds --spec worlds.json --fast   # N 个平行世界（第 9.1 节）
python scripts/generate_citymap.py --description "..."

# 人口合成与群体模拟（详见第 13 节 / GROUP_SIMULATION_TUTORIAL.md）
python -m gaworld.population --size 500 --seed 42 --check          # 预览，不写文件
python -m gaworld.population --size 500 --name my_town --out data/town
python -m gaworld.group --size 500 --days 7 --no-llm               # 群体模拟，零成本
python -m gaworld.group --size 500 --days 7 --focal 7,42 --no-llm  # 跟踪指定居民
python -m gaworld.group --size 500 --days 7 --network-coupling 0.7 --no-llm  # 开社交图耦合
python -m gaworld.group.validate --size 100 --days 14 --network-coupling 0.7

# 日志模式
GAWORLD_LOG_MODE=verbose python generative_city_sim.py run
GAWORLD_LOG_LEVEL=DEBUG  python generative_city_sim.py run
```

---

## 18. 微内核插件架构：扩展 GAWorld

自 2026-07 起，GAWorld 的所有子系统（干预、技能、兴趣成长、人生事件、
经济、物理感知、真实工作、动态行为、空间偏好）都运行在统一的微内核
插件接口上。这意味着三类以前需要改源码的操作，现在都是配置：

### 17.1 认知消融实验：改管线顺序

每个 agent step 是 12 个命名阶段的序列。想做"没有反思的 agent 会怎样"
这类消融实验，只需在配置里省略对应阶段：

```python
CONFIG["pipeline"]["agent_step"] = [
    "prepare", "perceive", "interrupts", "plan", "adjust_activity",
    "move", "select_action",              # 省略 "reflect" = 消融反思
    "update_state", "broadcast", "memorize", "record",
]
```

也可以在任意位置插入自定义阶段（`"my_pkg.stages:deliberate"` 形式的
导入路径），阶段签名为 `fn(agent, step, ctx)`。注意 `prepare` 与
`record` 是结构性阶段（钩子发射与日志落盘在其中），消融目标应是中间
的认知阶段。

### 17.2 编写插件：不改核心加子系统

一个最小插件——让 agent 在感知中听到谣言：

```python
# my_pkg/rumor.py
from gaworld.kernel import Plugin

class RumorPlugin(Plugin):
    id = "rumor"
    def setup(self, ctx):
        ctx.bus.on("perception.compose", self.inject)
    def inject(self, hook_ctx):
        return ["有人跟你提起：城东要修新地铁线（真实性存疑）"]
```

启用方式二选一：

```python
# 配置声明（路径可导入即可）
CONFIG["plugins"] = [{"class": "my_pkg.rumor:RumorPlugin"}]
```

```toml
# 或 pip 包的 entry point（安装即自动装配）
[project.entry-points."gaworld.plugins"]
rumor = "my_pkg.rumor:RumorPlugin"
```

事件目录（感知注入、中断征集、动作过滤、状态效果、episode 组装等
21 个事件）、三种钩子语义（observe / collect / filter）、状态与数据
所有权约定，见[插件作者指南](PLUGIN_AUTHORING.md)。内置的 9 个插件
本身就是最好的参考实现。

### 17.3 运行时干预：模拟跑着的时候改世界

`Controller.intervene` 提供可审计的运行时干预（每次调用都记录到
`output/records/controller.intervention.jsonl`）：

```python
sim.controller.intervene("set_agent_state", sim, agent_id=31, key="stress", value=0.8)
sim.controller.intervene("update_config", sim, path="economy.credit.apr", value=0.15)
sim.controller.intervene("inject_life_event", sim, event={"title": "老友来电", "day": 2, "time": "19:00", "agent_ids": [31]})
sim.controller.intervene("remove_agent", sim, agent_id=7)   # 下个日边界生效
```

在插件钩子、测试或 notebook 里都能调用（`sim` 即钩子上下文里的
`hook_ctx["sim"]`）。

### 17.4 动作校验

move 动作会经过 Controller 校验链：`location_exists`（默认开，拦截
幻觉地点）与 `venue_open`（默认关——硬拦关门场所会改变模拟动力学，
需要时 `CONFIG["controller"]["validators"]["venue_open"] = True` 开启）。
被拒绝的动作会审计落盘，且理由会出现在该 agent 下一个时间步的感知里
（"刚才的行动受阻：……"），agent 可以对此做出反应。

---

## 相关文档

- [English README](../README.md) · [中文 README](../README.zh-CN.md)
- [简明上手教程](TUTORIAL.md)（本教程已并入原 v1.0 完全教程的全部内容）
- [插件作者指南](PLUGIN_AUTHORING.md) · [微内核架构设计](proposals/2026-07-11-microkernel-plugin-architecture.md)
- [物理环境感知与反应式重规划](physical_env_perception_changelog.md)
- [Skill 系统设计与使用](SKILL_SYSTEM.md)
- [真实工作系统 — 使用](REAL_WORK_USAGE.md) · [设计](REAL_WORK_DESIGN.md)
- [外部系统教程](EXTERNAL_SYSTEMS_TUTORIAL.md)（货币系统 / 外部环境 / 对外服务的观察与编辑）
- [平行世界教程](PARALLEL_WORLDS_TUTORIAL.md)（多分支反事实实验：设计、读图、剂量反应与安慰剂对照）
- [群体模拟教程](GROUP_SIMULATION_TUTORIAL.md) · [设计](GROUP_AGENT_DESIGN.md)
- [项目结构](PROJECT_STRUCTURE.md) · [仓库规范](../AGENTS.md) · [更新日志](../CHANGELOG.md)
