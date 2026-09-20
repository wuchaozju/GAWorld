# 外部系统教程（External Systems）

> 看住世界本身，而不只是住在里面的人：货币系统、外部环境生成器、对外服务连接——
> 观察它们，然后直接改。
>
> 面板：控制台「**外部系统**」页签｜后端：`gaworld/apps/external_systems_api.py`
> 相关：[经济系统改进讨论纪要](./proposals/2026-07-04-currency-system-panel.md)

---

## 目录

- [0. 这是什么，什么时候该用](#0-这是什么什么时候该用)
- [1. 五分钟跑通](#1-五分钟跑通)
- [2. 货币系统面板](#2-货币系统面板)
- [3. 外部环境面板](#3-外部环境面板)
- [4. 对外服务面板](#4-对外服务面板)
- [5. 两种"改"：配置 vs 运行时干预](#5-两种改配置-vs-运行时干预)
- [6. 一个完整实验：财政刺激](#6-一个完整实验财政刺激)
- [7. API 速查](#7-api-速查)
- [8. 参数速查](#8-参数速查)
- [9. 常见问题](#9-常见问题)

---

## 0. 这是什么，什么时候该用

GAWorld 的大部分界面都对着 **agent**：这个居民是谁、他记得什么、他和谁是朋友。
但一次社会实验里真正被你操纵的，往往不是某个居民，而是**他们所处的世界**——
通胀到了几个点、政府池有没有钱、今天下不下雨、外部信息从哪来。

这些东西一直存在于 GAWorld 里，只是以前**只能读 CSV、只能手改 JSON**：

| 你想做的事 | 以前 | 现在 |
|---|---|---|
| 看这轮跑完钱去哪了 | `less output/economy/conservation_audit.csv` | 面板上一张守恒曲线 |
| 把个税起征点从 5000 改成 6000 | 手编 `dashboard_config.json` | 表单里改一个数字 |
| 让第 20 天开始进入经济衰退 | 改不了 | 排一条干预，到点自动生效 |
| 确认外部环境服务通不通 | `curl .../health` | 点一下「探测一次」 |

### 三个子系统

| 面板 | 管的是 | 底层 |
|---|---|---|
| **货币系统** | 宏观周期、通胀、失业、企业/政府/银行三个部门池、货币守恒、财富分布 | `gaworld/economy/finance.py`、`CONFIG["economy"]` |
| **外部环境** | 每天生成的自然 / 经济 / 政策 / 科技事件，天气池，政策冲击排期 | `gaworld/env/system.py`、`CONFIG["external_environment"]` |
| **对外服务** | 外部环境服务、分布式中继、外部信息注入、新闻源、LLM 路由 | `CONFIG` 里对应的连接配置 |

### 什么时候用它

| 场景 | 用外部系统面板？ |
|---|---|
| 想知道这轮仿真的钱守不守恒、财富分布长什么样 | ✅ 观察区就是为此 |
| 做税制 / 社保 / 消费结构的对照实验 | ✅ 改配置，下次运行生效 |
| 想在仿真跑到一半时制造一次衰退或财政刺激 | ✅ 用干预队列 |
| 想改某个居民的存款或压力 | ❌ 用 Agent Studio，或 `Controller.intervene` |
| 想做严格可复现的对照实验 | ⚠️ 用**配置**做两组，不要用干预队列（见 [§5](#5-两种改配置-vs-运行时干预)） |

---

## 1. 五分钟跑通

```bash
python generative_city_sim.py dashboard --port 8766
# 浏览器打开 http://127.0.0.1:8766/console，切到「外部系统」页签
```

三个页签从左到右：**货币系统 / 外部环境 / 对外服务**。每个都是左边「观察」、
右边「编辑」。

第一次打开如果观察区大面积显示「跑一次仿真后再看」，那是正常的——观察区读的是
`output/` 下**上一次运行的产物**，还没跑过就没有东西可读。先跑一次：

```bash
python generative_city_sim.py run --sim-days 5
```

跑完回面板点右下角「刷新观测」。

### 不用记这些名词

面板上几乎每个指标、每个旋钮旁边都有一个灰色的 **?**，鼠标移上去就会显示一句白话说明——
说的是**这个数字意味着什么、改了会发生什么**，不是复述标题。例如：

| 你看到的 | 移上去会说 |
|---|---|
| 守恒漂移 | 「今天的钱总量和开局差了多少。这个数不是 0 就是程序出问题了——钱应该只会转手，不会凭空出现或消失。」 |
| 失业率 | 「一个宏观景气指标。它并不会真的让谁丢工作——真正决定裁员的是各阶段的『裁员概率』。想精确地让**某个人**失业，用人生事件里的「失业」模板。」 |
| 月起征点 | 「月收入低于这个数不交税。中国现行 5000 元。调高 = 给所有人减税。」 |
| 企业池 ± | 「填的是『加减多少钱』，不是『改成多少钱』。填 50000 就是往这个池子里打 5 万……」 |

事件的严重度条、类型徽章、服务状态那一列虽然没有 **?**，但鼠标移上去（光标会变成问号）
同样有说明。键盘用户用 Tab 也能聚焦到这些提示。

所以下面各节可以当参考手册用——**日常使用不需要先读完它**。

---

## 2. 货币系统面板

### 2.1 观察区怎么读

顶部八块指标：

| 指标 | 含义 | 怎么算不正常 |
|---|---|---|
| 周期阶段 | 扩张 / 顶峰 / 收缩 / 谷底，四阶段轮转 | — |
| 通胀率（年化） | `macro.inflation_rate`，被钳在 0.1%–15% | — |
| 失业率 | `macro.unemployment_rate`，被钳在 2%–20%。**注意它是一个被更新的数字，不会真的让谁失业**——随机裁员概率来自 `phase_effects.layoff_risk`；要指名道姓地让某人失业或换工作，走人生事件的「失业」/「换工作」模板（会改写 `agent["job"]` 本身，见 [FEATURES](FEATURES.md)） | — |
| 累计物价指数 | 从 1.0 起按日通胀累乘，只作用在支出侧 | 长模拟里它会持续侵蚀实际收入 |
| 系统总货币 | agent 全部账户 + 三个部门池 | — |
| 守恒漂移 | 每日 `system_total − initial_system_total` 的最大绝对值 | **非 0 就是 bug**，不是设定 |
| 基尼系数 | 按流动资产（活期+储蓄+投资）算 | 少于 2 人或总额为 0 时显示 `—` |
| 负债 agent | 有未偿债务的人数 / 总人数 | — |

下面是**部门池余额**。三个池是所有资金流动的对手方：企业池发工资、收消费；
政府池收税、付医保报销；银行池结算投资盈亏、放贷。**池子允许为负**——
企业池为负就是家庭部门净储蓄的镜像，不是错误。

再往下两张手绘 SVG 曲线：**系统总货币**（应该是一条水平线）和**全体日收支**。

最后是**干预队列**：待生效的和已执行的各一份，已执行的那条会告诉你它在第几天落地、
实际改了什么。

### 2.2 编辑区：干预运行中的货币系统

右上角的表单往队列里排一条干预。留空的字段不改。

- **周期阶段**：直接把 `macro.phase` 设过去。
- **通胀率 / 失业率**：绝对值，不是增量。超出钳制区间会被截到边界。
- **企业池 / 政府池 / 银行池**：填的是**增减量**（正数注入、负数抽离），不是目标余额。
- **生效日**：留空 = 下一个日边界；填 N = 第 N 天及以后的第一个日边界。
- **备注**：只是给你自己看的，会记进 `interventions.json`。

注资会同步抬高守恒基准（`initial_system_total`），所以每日审计**不会**把你有意的注资
误报成漏钱；注入的累计额单独记在 `sectors.json` 的 `intervention_injected_total` 里。

### 2.3 编辑区：配置

下半部分是完整的 `CONFIG["economy"]` 树，约 120 个旋钮：个税表、社保费率、
恩格尔曲线、消费预算模板与收入弹性、投资组合与市场共同因子、信贷、宏观周期与各阶段效应、
冲击概率、支付路由、熟人借贷、部门池初始余额。

- 数字 → 数字输入框，布尔 → 勾选框，字符串 → 文本框；
- **列表退化成 JSON 文本框**（税率表、恩格尔曲线、天气权重都属于这类），
  解析不了会标红并挡住保存；
- 改过的字段会变绿并计数，顶部显示「N 项配置改动未保存」；
- 保存后底部会告诉你实际写进去了什么、有哪些键**被丢弃**了。

> 税率表最后一档的上限显示为 `"Infinity"`（带引号的字符串）。这是刻意的：
> `float("inf")` 在 JSON 里是裸 `Infinity`，浏览器会拒绝整个响应。写回时会还原成
> 数值无穷，直接编辑这个字符串是安全的。

**配置改动写进 `dashboard_config.json`，运行时覆盖 `config.py`，下一次运行生效——
不影响正在跑的这一轮。**

---

## 3. 外部环境面板

### 3.1 观察区

环境生成器每天抛出四类事件（自然 / 经济 / 政策 / 科技），进入每个 agent 的当日情境。
面板读 `output/environment/timeline.jsonl`：

- 顶部：最新一天、已生成天数、日内 tick 记录数、平均严重度、各类事件计数；
- 下面按天倒序列出最近 8 天，每天一句摘要 + 若干事件，每个事件带**类型徽章**、
  **严重度条**（≥0.6 转红）和**影响标签**（`mobility` / `stress` / `employment` …）。

严重度不是装饰：它进入 `routine_change` 的日程改变判定（按
`max(0, severity − severity_pivot)` 加权），高严重度事件会显著提高 agent 当天改计划的概率。

### 3.2 编辑区

三棵配置树：

- **`external_environment`**：生成器主体。`generator.mode` 选 `llm` 还是规则；
  `generator.description` 是喂给 LLM 的城市背景；各类事件的日概率
  （`natural.daily_weather_chance`、`economic.macro_event_chance`、
  `political.daily_policy_chance`、`technology.daily_tech_chance`）；
  天气状态与权重；日内突发概率。
- **`environment`**：旧版环境事件，保留兼容。
- **`policy_events`**：**排定的政策冲击**，一个 JSON 数组，每项形如
  `{"day": 2, "time": "10:00", "name": "...", "description": "..."}`。
  这是把一次政策事件精确投放到某天某时的方式，效果由 LLM 从描述里推断。

改完下次运行生效。要在**当前**这轮里加事件，用人生事件（`life_events`）或
`Controller.intervene("inject_life_event", ...)`。

---

## 4. 对外服务面板

### 4.1 连通性探测

列出仿真需要向外拨号的地方，点「探测一次」会真的发一次 `GET /health`：

| 状态 | 含义 |
|---|---|
| 通 | HTTP 2xx |
| 不通 | 连不上（附 errno） |
| 异常 | 连上了但状态码不对 |
| 未启用 | 配置里 `enabled: false`，没有发请求 |

探测是**按需**的，不会后台轮询；打开页面时显示「未探测」。

两个目标：
- **外部环境服务**（`external_environment_service.base_url`）——把环境生成挪到独立进程；
  用 `python -m gaworld.apps.external_environment_server` 起。
- **分布式中继**（`distributed.relay.base_url`）——多机通信，见
  [完整教程第 11 节](./TUTORIAL.v2.md#11-分布式-relay多机通信)。

### 4.2 LLM 路由与外部信息源

**模型清单只读**——provider 配置里带密钥，面板不展示也不允许编辑。可编辑的是
**路由**：`llm.routing.default`（默认模型）和 `llm.routing.tasks`（按任务覆盖，
例如把 `schedule` 单独指到一个便宜的本地模型）。

新闻缓存显示条目数与文件是否存在。可编辑的服务配置还包括
`external_rag`（外部信息注入的召回条数、冷启动、运行中持续吸收）、
`news`（源清单、缓存策略、主动检索 `info_seek`）、`environment_server`、`distributed`。

> 改了服务端配置（`environment_server`、`distributed.server`）之后，**服务进程要自己重启**——
> 它们不是仿真的一部分，不会因为你保存了配置就重新加载。

---

## 5. 两种"改"：配置 vs 运行时干预

这是这个模块唯一需要真正理解的地方。

|  | 配置 | 干预队列 |
|---|---|---|
| 写到哪 | `dashboard_config.json` | `output/economy/interventions.json` |
| 什么时候生效 | **下一次**运行 | 运行中的**下一个日边界** |
| 影响范围 | 整轮仿真的初始条件与规则 | 一次性地把宏观状态设过去 / 把钱打进池子 |
| 可复现 | ✅ 同 seed 同配置 = 同结果 | ⚠️ 取决于你什么时候点的按钮 |
| 适合 | 对照实验 | 探索、演示、临时制造冲击 |

### 5.1 为什么不是直接改 `macro_state.json`

因为那个文件是 run 的**产物**，不是输入。仿真在 `on_simulation_start` 里用
`_init_macro_state(cfg)` **从配置重建**宏观状态，全程不回读这个文件——
改它会看起来生效、实际什么都没发生。

而且 Dashboard 是把仿真当**子进程**启动的，经济运行时状态活在那个进程的
`context["extension_state"]` 里，网页碰不到。所以真正能用的通道只有一个：
**一个文件队列，由跑着的仿真在日边界主动来取**。这与已有的人生事件队列是同一个套路。

### 5.2 生效顺序

在 `on_day_start` 里，干预排在**周期推进之后**：

```
_advance_macro_cycle(...)      # 先按周期规则漂移
_consume_interventions(...)    # 再把你设的值盖上去
```

这样你设的通胀率就是**那天真正被使用的值**，不会刚写进去就被周期漂移乘掉。

### 5.3 守恒怎么保持诚实

给部门池注资 = 凭空造钱，系统总量变了。如果什么都不做，第二天的守恒审计就会报出
一个非零 drift——而 drift 的语义是「钱在某处漏了，这是 bug」。所以注资会：

1. 把 `initial_system_total` 移动同样的金额（审计基准跟着走，drift 仍为 0）；
2. 把累计注入额记进 `runtime["intervention_injected_total"]`，落盘到 `sectors.json`。

一次有意的注资因此被记成注资，而不是伪装成正常。

### 5.4 三个坑

- **仿真没在跑时排的干预不会丢**，它会等到下次开跑，然后在第 1 天落地。想清空用面板的
  「清空待生效」。
- **`reset` 不清 `output/economy/`**（它清的是 memory / logs / environment / visualization
  等目录），所以队列会跨 reset 存活。
- **干预不进对照实验**。要做 A/B，请用配置：跑两轮，第二轮改
  `economy.macro.initial_inflation_rate` 之类的初始条件，或者用
  `compare-event` 做事件对照。

---

## 6. 一个完整实验：财政刺激

问题：**在收缩期给政府池注入 5 万元，会不会通过消费回流改变财富分布？**

```bash
# 1) 基线：跑 20 天，记下结果
python generative_city_sim.py run --sim-days 20
cp -r output/economy /tmp/econ_baseline
```

打开面板「货币系统」，记下基尼系数、部门池余额、守恒漂移（应为 0）。

```bash
# 2) 重跑，跑起来之后在面板上排两条干预
python generative_city_sim.py run --sim-days 20
```

在面板右上角：

| 字段 | 值 | 意思 |
|---|---|---|
| 周期阶段 | 收缩 contraction | 第 5 天起进入衰退 |
| 生效日 | 5 | |
| 备注 | 衰退开始 | |

点「加入干预队列」。再排第二条：

| 字段 | 值 |
|---|---|
| 政府池 ± | `50000` |
| 生效日 | `8` |
| 备注 | 财政刺激 |

跑完之后：

```bash
# 3) 对比
python - <<'PY'
import csv
for tag, path in (("baseline", "/tmp/econ_baseline"), ("stimulus", "output/economy")):
    rows = list(csv.DictReader(open(f"{path}/wealth_snapshot.csv")))
    bal = sorted(float(r["balance"]) for r in rows)
    print(tag, "n=", len(bal), "total=", round(sum(bal), 2), "median=", bal[len(bal)//2])
PY
```

面板上要看的三件事：

1. **守恒漂移仍是 0** —— 注资被正确记账了，没有变成漏钱；
2. **`intervention_injected_total` = 50000** —— 部门池表格下方多一行「其中：人为注入累计」；
3. **干预队列的"已执行"** 显示两条，各自落在第 5 天和第 8 天。

> 提醒：这不是一个严格的对照实验——两轮的干预是你手点的，时点无法复现。要发表级的
> 对照，把刺激写成配置（例如提高 `economy.sectors.initial_government_balance`）
> 或走 `compare-event`。

---

## 7. API 速查

面板做的每件事都有对应的 HTTP 接口，可以直接调（`dashboard_server.py` 转发到
`gaworld/apps/external_systems_api.py`）。

```bash
BASE=http://127.0.0.1:8766

# 全量观测（三个子系统的 config + runtime）
curl -s $BASE/api/external-systems/overview | python -m json.tool | head -40

# 连通性探测
curl -s $BASE/api/external-systems/health

# 看干预队列
curl -s $BASE/api/external-systems/interventions

# 改配置（只接受白名单子树，其余键会被丢弃并在 dropped 里回报）
curl -s -X POST $BASE/api/external-systems/config \
  -H 'Content-Type: application/json' \
  -d '{"config": {"economy": {"tax": {"monthly_exemption": 6000}}}}'

# 排一条干预
curl -s -X POST $BASE/api/external-systems/interventions \
  -H 'Content-Type: application/json' \
  -d '{"macro": {"phase": "contraction", "inflation_rate": 0.09},
       "sector_delta": {"government": 50000},
       "day": 8, "note": "财政刺激"}'

# 清空待生效
curl -s -X POST $BASE/api/external-systems/interventions/cancel \
  -H 'Content-Type: application/json' -d '{"all": true}'
```

**可编辑的配置子树**（其它一律拒绝）：

| 面板 | 子树 |
|---|---|
| 货币系统 | `economy` |
| 外部环境 | `external_environment`、`environment`、`policy_events` |
| 对外服务 | `external_environment_service`、`environment_server`、`external_rag`、`news`、`distributed`、`llm.routing` |

补丁会**按现有配置的类型强制成形**：`"0.09"` → `0.09`，`"false"` → `False`，
不认识的键直接丢弃并在响应的 `dropped` 里列出。所以打错一个键名不会静默地在配置里
种下一个仿真永远不会读的字段。

---

## 8. 参数速查

### 干预可设的字段

```json
{
  "day": 8,                    // 留空 = 下一个日边界
  "note": "财政刺激",
  "macro": {
    "phase": "contraction",           // expansion | peak | contraction | trough
    "phase_day_counter": 0,
    "phase_duration": 90,
    "inflation_rate": 0.09,           // 钳制 0.001–0.15
    "unemployment_rate": 0.12,        // 钳制 0.02–0.20
    "cumulative_inflation": 1.05,
    "industry_conditions": {"tech": 0.8}   // 每项钳制 0.5–1.5
  },
  "sector_delta": {"firms": 0, "government": 50000, "bank": 0}   // 增减量
}
```

### 常改的配置项

| 键 | 作用 |
|---|---|
| `economy.tax.monthly_exemption` / `.brackets` | 起征点 / 税率表 |
| `economy.social_insurance.*_rate` | 五险一金个人缴费率 |
| `economy.macro.initial_inflation_rate` / `.initial_unemployment_rate` | 宏观初值 |
| `economy.macro.phase_effects.<阶段>.layoff_risk` | 各阶段裁员概率（真正让人失业的是这个） |
| `economy.sectors.initial_*_balance` | 三个部门池的初始余额 |
| `economy.credit.credit_limit_months` / `.annual_interest_rate` | 授信额度 / 年息 |
| `economy.routing.merchant_labor_share` | 消费经企业池转付给服务业 agent 的比例 |
| `external_environment.generator.mode` | `llm`（有文采、要花钱）或规则 |
| `external_environment.*.daily_*_chance` | 四类事件的日概率 |
| `policy_events` | 排定的政策冲击 |
| `llm.routing.default` / `.tasks` | 默认模型 / 按任务覆盖 |

### 相关文件

```
output/economy/
├── macro_state.json          最后一天的宏观状态（产物，仿真不回读）
├── sectors.json              部门池 + 守恒基准 + 人为注入累计
├── conservation_audit.csv    每日守恒审计（drift 应恒为 0）
├── daily_ledger.csv          每人每天的收支与余额
├── wealth_snapshot.csv       结束时的财富快照（基尼从这里算）
└── interventions.json        ← 干预队列（pending / applied）

output/environment/timeline.jsonl   每天的环境事件
dashboard_config.json               面板保存的配置覆盖
```

---

## 9. 常见问题

**面板显示「无法加载」怎么办？**
先看浏览器控制台。历史上这里出过一次：`economy.tax.brackets` 最后一档是
`float("inf")`，`json.dumps` 输出裸 `Infinity`，浏览器 `JSON.parse` 会拒绝**整个**
响应——后端一切正常、页面全白。现在这类值以字符串 `"Infinity"` 传输。如果你在配置里
新加了非有限数值，注意同样的坑。

**观察区一直是空的。**
观察区读的是 `output/` 下上次运行的产物。没跑过就没有；跑完点「刷新观测」。
另外 `economy.enabled` 关掉的话不会产出任何经济文件。

**保存后提示「被丢弃的键」。**
说明那些键在当前生效配置里不存在。多半是拼错，或者你在用一个已经改名的旧字段。
面板只允许你改**已经存在**的键——这是有意的，避免种下永远不被读取的死配置。

**排的干预一直不执行。**
三种可能：仿真没在跑（会等到下次开跑）；生效日还没到；或者 `economy.enabled` 是
`false`——经济模块整个关掉时 `on_day_start` 会提前返回，不消费队列。

**守恒漂移不是 0。**
如果你没做过部门池注资，那是真 bug，请带上 `conservation_audit.csv` 报告。
如果你注过资但基准没跟着动，检查是不是绕过面板手改了 `sectors.json`。

**某个旋钮不知道是干嘛的。**
鼠标移到它旁边的 **?** 上。说明写在 `site/dashboard/external.js` 的 `HELP` 表里，按
「完整路径 → 末段键名」两级查找——所以 `economy.social_insurance.unemployment_rate`
（社保缴费比例）和宏观里的失业率不会被解释成同一件事。想补充说明就往那张表里加一行。

**我想改某个居民的钱，不是整个系统。**
用 Agent Studio 的财务面板，或 `POST /api/agents/{id}/finance`，
或 `sim.controller.intervene("set_agent_state", ...)`。

**改了 `environment_server` 的端口，服务还在老端口上。**
配置保存不会重启服务进程。自己重启
`python -m gaworld.apps.external_environment_server`。

---

## 相关文档

- [完整教程](./TUTORIAL.v2.md)（[§5.2 经济仿真](./TUTORIAL.v2.md#52-经济仿真) ·
  [§12.3 外部系统观测台](./TUTORIAL.v2.md#123-外部系统观测台)）
- [经济/货币系统改进讨论纪要](./proposals/2026-07-04-currency-system-panel.md)——
  部门池、守恒、信贷、共同市场因子这些设计的来龙去脉
- [群体模拟教程](./GROUP_SIMULATION_TUTORIAL.md) · [项目结构](./PROJECT_STRUCTURE.md)
- [平行世界教程](./PARALLEL_WORLDS_TUTORIAL.md)（要做**严格可复现**的对照实验时用它，而不是干预队列）
- 测试：`tests/test_dashboard_external_systems.py`、`site/dashboard/external.test.js`
