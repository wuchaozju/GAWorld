# Real Work Execution — 实施设计

> 让仿真 agent 根据其特点（职业/特长/兴趣）做**真实的工作**，产出可被人直接打开的文件（HTML 设计稿、Python 脚本、Markdown 文章、教案等），并保留与外部系统对接的扩展位。

设计原则：与项目 `AGENTS.md` 保持一致——最小改动、可关闭、不破坏现有 tick 行为；新代码优先放在 `gaworld/` 树下并写测试。

---

## 0. 关键决策（已确认）

| 决策项 | 选择 |
| --- | --- |
| 外部对接形态 | **本地适配器**：调用器把工作落盘到 `output/work/agent_<id>/` 真实文件；webhook / MCP 留接口位 |
| 首批职业 | **设计师 / 程序员 / 新媒体 / 教师研究**（4 类） |
| 执行模式 | **异步后台**：tick 内只投递任务，结果在后续 tick 收回写进记忆/反思 |
| 能力映射来源 | **LLM 解析 profile 自动产出**，结果落盘缓存，避免每次启动重算 |
| 工作来源 | **双路径**：① 自驱（活动+能力推断）② **mock 工作机会市场**（seed 任务池，agent 浏览-接单-结算） |

---

## 1. 现状锚点（不要假设，全是查到的）

### 1.1 主循环挂钩点
`generative_city_sim.py:6149` 当前：
```python
outcome = f"在【{activity}】中执行了【{act}】"
```
这一行就是占位字符串。新功能的注入点就在它**之前**——从 `choose_action` 返回的 `act, action_meta` 已经在手；之后还会跑 `reflection`、`update_state`、`update_needs`，不能错过。

外层调用上下文（`generative_city_sim.py:6080-6149`）已经准备好：`agent / activity / act / action_meta / time_str / resolved_location / step_env_context`，是否触发实际工作所需的所有材料都在。

### 1.2 Agent profile 当前形状
`generative_city_sim.py:1538-1551` 的 `parse_profile` 只抽取：
```
name, age, living, job, personality, daily_life, values, work_style
```
**没有结构化的 skills/interests/expertise**。已有的 `_extract_interest_keywords`（`generative_city_sim.py:498-525`）只是从 job/personality/daily_life 文本做关键词频次抽取，给"新闻推荐相关性"用的。

### 1.3 已有外部对接是「输入侧」
- `scripts/openclaw_bridge.py` + `gaworld/apps/distributed_comm_server.py`：让用户的 OpenClaw agent **接进来**当虚拟市民；relay 走 HTTP 长轮询。
- `gaworld/apps/external_environment_server.py`：让仿真**获取**外部环境（天气/新闻），是消费侧。

**没有**任何路径把 agent 的"工作产出"推到外部系统——这是要新建的能力。

### 1.4 行为/动作系统
- `DEFAULT_ACTIONS`（`generative_city_sim.py:4415`）：`{"工作": "继续处理手头工作", "时间": "发呆"}`，作为 fallback。
- `build_action_space_for_agent`（`generative_city_sim.py:4403`）：用 LLM 给每个 activity 生成具体动作清单，存在 `actions[agent_id]` dict。
- `choose_action`（`generative_city_sim.py:4440`）：基于权重打分选一个动作字符串，**返回的是中文文案，不是结构化指令**。

这意味着：动作侧需要一个轻量分类器，从中文文案识别出"这是不是该交给真实工作适配器"。

---

## 2. 总体架构

```
┌──────────────────────── 仿真主循环 (1 tick) ────────────────────────┐
│                                                                    │
│  planning → maybe_adjust_activity → choose_action(act)             │
│                                                                    │
│   ┌─────────── (新)  RealWorkRouter ──────────┐                    │
│   │  Path A: 自驱 — match(capabilities, act)   │                   │
│   │  Path B: 浏览市场 — JobMarket.browse(...)  │                   │
│   │  → adapter_id + work_brief                 │                   │
│   └─────────────────────┬──────────────────────┘                   │
│                         │ submit                                   │
│                         ▼                                          │
│                  ┌─────────────┐         ┌──────────────┐          │
│                  │ WorkQueue   │ ◄──────►│ JobMarket    │          │
│                  └──────┬──────┘  锁定/  │ (mock seed   │          │
│                         │        释放    │  jsonl 池)   │          │
│                         │                └──────────────┘          │
│  outcome = "投递工作任务: {brief.title}"  ← 同步只占位             │
│  reflection / update_state ... (照旧)                              │
│                                                                    │
└────────────────────────────────────────────────────────────────────┘
                           │
                           │  后台 worker 池（独立线程，按 adapter）
                           ▼
                    ┌───────────────┐
                    │ WorkerPool    │  调度 adapters/*.py
                    └──────┬────────┘
                           │
        ┌──────────────────┼──────────────────┐
        ▼                  ▼                  ▼
  WebDesignAdapter   CodeAdapter      ContentAdapter
  (LLM → HTML)       (LLM → .py+测试) (LLM → .md)
        │                  │                  │
        └──── 产物 → output/work/agent_<id>/<task_id>/ ────┘
                           │
                           ▼
                  WorkResultIngest（每 tick 检查完成的任务）
                           │
                           ▼
        把 outcome 改写为「完成了 X，产出位于 ...」
        作为下一次 reflection 的输入；写入 memory_store
```

---

## 3. 模块切分与文件清单

新代码全部放在 `gaworld/work/`（与 `gaworld/io/`、`gaworld/core/` 平级），保持与现有模块边界一致。

```
gaworld/work/
├── __init__.py
├── capabilities.py        # ProfileCapabilities：profile → skills/interests/deliverable_types
├── router.py              # RealWorkRouter：决定要不要触发真实工作 + 选 adapter
├── queue.py               # WorkQueue：jsonl 任务持久化，崩溃可恢复
├── worker.py              # WorkerPool：后台执行 + 心跳 + 超时
├── ingest.py              # WorkResultIngest：把完成任务回写 outcome / memory
├── market.py              # JobMarket：mock seed 任务池 + 浏览/接单/结算
├── market_seed.json       # 初始 mock 任务（≥15 条，覆盖 4 类 deliverable）
├── adapters/
│   ├── __init__.py
│   ├── base.py            # WorkAdapter 抽象基类
│   ├── web_design.py      # 设计师 → HTML/SVG
│   ├── code.py            # 程序员 → .py + pytest 测试
│   ├── content.py         # 新媒体 → .md 文章
│   └── teaching.py        # 教师/研究 → 教案/笔记
└── schemas.py             # WorkBrief / WorkResult / MarketJob dataclass

config 增量（`config.py` 增节）：
"real_work": {
    "enabled": False,                  # 默认关，灰度上线
    "queue_path": "output/work/queue.jsonl",
    "artifacts_dir": "output/work",
    "capabilities_cache": "output/work/capabilities.json",
    "max_concurrent_tasks": 2,
    "task_timeout_seconds": 600,
    "tick_ingest_limit": 5,            # 每 tick 最多回收几条结果
    "adapters": {
        "web_design": {"enabled": True},
        "code": {"enabled": True, "run_pytest": False},
        "content": {"enabled": True},
        "teaching": {"enabled": True},
    },
    "market": {
        "enabled": True,
        "seed_path": "gaworld/work/market_seed.json",
        "store_path": "output/work/market.jsonl",
        "browse_top_k": 5,             # 浏览时给 agent 看 top K 条
        "max_taken_per_agent_per_day": 2,
        "browse_probability_base": 0.15,  # 工作活动里基础接触概率
        "expire_after_sim_days": 5,    # 过期 job 自动 expired
        "auto_replenish": True,        # 池子见底时从 seed 重新洗牌补
    },
    "external_hooks": {                # 二期外部对接位
        "webhook_url": "",
        "mcp_server": "",
    },
}

profile_md_path 不变；但 capabilities 数据由 LLM 在首次启动时离线产出，缓存到 capabilities_cache。
```

主循环改动**仅 2 处**：
1. `generative_city_sim.py` 顶部 import：`from gaworld.work import router as real_work_router, ingest as real_work_ingest`。
2. `generative_city_sim.py:6149` 之前插入 ~6 行：调用 `router.maybe_dispatch(...)`，命中则改写 outcome；之前/之后再调用 `ingest.absorb_completed_for(agent, ...)` 把已完成结果灌进 reflection 输入。

---

## 4. 数据契约

### 4.1 `AgentCapabilities`（`gaworld/work/capabilities.py`）
```python
@dataclass
class AgentCapabilities:
    agent_id: int
    job_label: str                    # 规范化后的职业（如 "ui_designer"）
    skills: list[str]                 # ["排版", "色彩搭配", "信息架构"]
    interests: list[str]              # ["展览", "插画"]
    deliverables: list[str]           # ["html_landing", "poster_svg"]
    adapter_priority: list[str]       # ["web_design", "content"]
    notes: str                        # LLM 给的自由文本说明
    source_hash: str                  # md5(profile.job + personality + daily_life)
                                      # → profile 改了自动重算
```

**初始化流程**（启动时一次）：
1. `gaworld/work/capabilities.py:bootstrap_all_agents(agents, cache_path)`
2. 比对 `cache_path` 里 `source_hash`，命中则跳过 LLM。
3. 未命中：`call_llm(profile_text, prompt=CAPABILITY_PROMPT)` → 解析 JSON。
4. 落盘 `output/work/capabilities.json`，主循环只读不改。

CAPABILITY_PROMPT（草稿）：
```
你是一个仿真社会的能力建模助手。读取下面这个虚构居民的 profile，输出一个 JSON：
{
  "job_label": "<规范英文标签，从枚举里选: ui_designer | algorithm_engineer | content_creator | teacher_researcher | other>",
  "skills":   [≤6 个具体可操作的中文技能词],
  "interests":[≤6 个兴趣词],
  "deliverables": [可交付物枚举的子集: html_landing, poster_svg, py_script, py_test, md_article, lesson_plan, research_note],
  "adapter_priority": [按可能性排序的 adapter 名: web_design / code / content / teaching],
  "notes": "<≤80 字解释>"
}
不在枚举里的 deliverables 不要输出。
```

枚举固定的好处：避免 LLM 漂移产出无法路由的 deliverable。

### 4.2 `WorkBrief`
```python
@dataclass
class WorkBrief:
    task_id: str               # uuid4
    agent_id: int
    sim_day: int
    sim_time: str              # "09:30"
    activity: str              # "上午工作"
    chosen_action: str         # "继续画订餐 app 首页"
    deliverable: str           # 来自 capabilities.deliverables
    adapter: str               # "web_design"
    brief_text: str            # 由 plan + recent memory 拼出的简短任务说明
    estimated_minutes: int     # 由 deliverable 类型固定（设计 30/代码 15/文章 20/教案 25）
    submitted_at: float        # epoch
```

### 4.3 `MarketJob`（新）
```python
@dataclass
class MarketJob:
    job_id: str                       # "mj_001"
    title: str                        # "为本地咖啡馆做一张海报"
    description: str                  # 任务说明，1-3 句
    deliverable: str                  # 复用 capabilities.deliverables 枚举
    required_skills: list[str]        # ["排版", "色彩搭配"] — 与 capabilities.skills 求交
    required_job_labels: list[str]    # ["ui_designer", "content_creator"]；空表示开放
    reward_econ: float                # 0~1 区间，结算时影响 econ_security 微调
    reward_text: str                  # "￥800 / 一次性"，仅作仿真叙事
    posted_sim_day: int
    deadline_sim_day: int             # 过期则 status=expired
    status: Literal["open", "taken", "done", "failed", "expired"]
    taken_by_agent_id: int | None
    taken_at_sim_time: str | None
    linked_task_id: str | None        # 接单后绑定的 WorkBrief.task_id
    source_tag: str                   # "mock_seed" / "llm_generated" / "external"
```

### 4.4 `WorkResult`
```python
@dataclass
class WorkResult:
    task_id: str
    agent_id: int
    status: Literal["ok", "failed", "timeout"]
    artifact_paths: list[str]  # 相对 output/work/agent_<id>/<task_id>/
    summary: str               # 1-2 句给反思用
    error: str | None
    finished_at: float
    duration_seconds: float
```

---

## 5. 路由与触发逻辑

`gaworld/work/router.py:maybe_dispatch(agent, activity, act, action_meta, ...) -> str | None`

路由分两条路径，**先尝试 Path B（市场）再退回 Path A（自驱）**——市场任务有 reward 和明确 brief，比"自己想画点什么"更具体，体验更好。

### Path A：自驱触发（保留原逻辑）
1. **关闭门**：`CONFIG["real_work"]["enabled"]` 为假 → 返回 `None`。
2. **活动门**：`activity` 含关键词 `["工作", "上班", "加班", "上课", "实验", "课题", "创作", "写作"]` 之一才继续。复用 `generative_city_sim.py:2585` 的关键词集。
3. **能力门**：`AgentCapabilities` 没有任何 `deliverables` → `None`。
4. **节流门**：当前 agent 在 `WorkQueue` 已有未完成任务且距上次 < `cooldown_minutes`（默认 60 仿真分钟）→ `None`。
5. **匹配 deliverable**：用 `act` 字符串 + `agent.capabilities.skills` 做轻量匹配：
   - `act` 含「设计/页面/海报/UI」→ `html_landing` / `poster_svg`
   - `act` 含「代码/脚本/调试/算法」→ `py_script`
   - `act` 含「文章/推文/案例/选题」→ `md_article`
   - `act` 含「备课/讲义/笔记」→ `lesson_plan` / `research_note`
   - 全不命中 → `capabilities.deliverables[0]` 兜底
6. **构造 brief**：`agent.name + job + chosen_action + 最近 1 条相关记忆 + 当前 plan` → ≤200 字 `brief_text` → `WorkQueue.submit(brief)`。

### Path B：浏览市场（新）
在 Path A 的 1-3 门之后，**优先**走这一条：
1. **浏览触发**：以 `browse_probability` 决定本 tick 是否浏览：
   ```
   browse_probability = base
       + 0.20 * agent.platform_dependence
       + 0.15 * (1 - agent.state.econ_security)
       - 0.10 * (1 - agent.state.energy)        # 累了懒得刷
   ```
   `base = CONFIG.real_work.market.browse_probability_base`，clip 到 [0, 0.6]。**确定性触发函数用 `random.Random(agent_id, day, tick)` 局部实例**，保留主仿真 random.seed 复现性。
2. **额度门**：当天该 agent 已接 ≥ `max_taken_per_agent_per_day` → 跳过浏览，回 Path A。
3. **筛选与打分**：`JobMarket.browse(agent, top_k)`：
   - 过滤：`status=="open"` 且未过期 且 `required_job_labels` 命中或为空。
   - 打分：`score = skills_overlap * 0.5 + interests_overlap * 0.2 + reward_econ * 0.2 + (1 - urgency) * 0.1`，其中 `urgency = (deadline - day) / max_window`。
   - 取 top K 条作为可见列表（写入 `transient_thought` 让 reflection 能看到"今天浏览了 5 条任务"）。
4. **接单决策**（轻量、无 LLM）：对 top 1 条用一个 logistic 决策：
   ```
   accept_p = sigmoid( score * 2.0
                      + 0.4 * (risk_preference - 0.5)
                      - 0.5 * (stress - 0.5) )
   ```
   `random < accept_p` 则接单。**不接也是合法结果**——只在记忆里留一条"看了任务但没接"。
5. **接单**：`JobMarket.take(job_id, agent_id, sim_time)` 把 status 改为 `taken`，把 `MarketJob.description + required_skills` 转写成 `WorkBrief`，`WorkQueue.submit(brief)`，把 `brief.task_id` 回写到 `MarketJob.linked_task_id`。
6. **返回 outcome 文案**：`"在工作平台接单：【为本地咖啡馆做一张海报】，task=wt_3f9a..."`。

### 路由决策树
```
enabled? ──no──► None
   │ yes
   ▼
活动/能力门 ──fail──► None
   │ pass
   ▼
market.enabled & browse_p 命中? ──yes──► JobMarket.browse → 接单? ──yes──► submit (Path B)
   │                                                        │ no
   │                                                        ▼
   ▼                                          (记忆"看了没接")回退 Path A
节流 + deliverable 匹配 ──► submit (Path A)
```

注意：`router.maybe_dispatch` 与 `JobMarket` 自身**不调用 LLM**——LLM 只在 adapter 内部跑。这样 tick 不被阻塞。

---

## 6. 异步执行：WorkQueue + WorkerPool

### 6.1 持久化
`output/work/queue.jsonl` 单文件，每行一条 brief。状态用 sidecar：`output/work/state.json`（pending/running/done/failed task_id 索引）。

为什么用 jsonl 不用 SQLite：与项目其它模块（`memory_store.py`、`output/distributed/` 都是文件型）一致，崩溃后重启好恢复，研究者好审计。

### 6.2 工作线程
启动一个 `ThreadPoolExecutor(max_workers=CONFIG["real_work"]["max_concurrent_tasks"])`。
**复用** `gaworld/core/runner.py:parallel_map`？**不**——那个是 tick 内并行；这里是跨 tick 的长生命周期。新写一个 daemon `WorkerPool.start()`，但 API 风格保持一致（`label` 日志、确定性序列化）。

每个 worker 取一条 pending brief → 调 `adapters[brief.adapter].run(brief)` → 写产物 → 写 result.json → 更新 state.json。

### 6.3 超时
adapter 调用包一层 `concurrent.futures.wait(timeout=task_timeout_seconds)`，超时标记 failed，不让 LLM 卡死阻塞队列。

### 6.4 与仿真随机种子的关系
`gaworld/core/runner.py:46-58` 的注释指出多线程会破坏 `random.seed` 的复现性。实际工作执行**与**仿真主循环的随机决策是**解耦**的——adapter 内部如果用 random，必须用 `random.Random()` 局部实例，不要触碰全局 random。在 `worker.py` 里加注释和 lint 检查（`B311` ruff 规则）。

---

## 6.5 JobMarket：mock 工作机会市场

### 6.5.1 存储模型
- `gaworld/work/market_seed.json`：版本受控的初始任务池（≥15 条，覆盖 4 类 deliverable + 不同薪酬/截止/技能要求组合，用于复现实验）。
- `output/work/market.jsonl`：运行时活态池，**每行一条 `MarketJob`**。状态变化追加新行（CRDT 风格 last-write-wins by `(job_id, ts)`）；启动时折叠成最终态。
- `output/work/market_state.json`：sidecar 索引（每个 agent 当天接单计数、过期清理时间戳）。

为什么不用 SQLite：与 §6.1 的 `WorkQueue` 选型一致，全文件型，研究者可以直接 `cat / jq` 审计。

### 6.5.2 Seed 任务示例（`market_seed.json` 截选）
```json
[
  {
    "job_id": "mj_001",
    "title": "为西湖文创咖啡馆做一张周末活动海报",
    "description": "目标客群：25-35 岁年轻人；要求：手绘风、暖色调、含活动时间地点。",
    "deliverable": "poster_svg",
    "required_skills": ["排版", "色彩搭配", "插画"],
    "required_job_labels": ["ui_designer", "content_creator"],
    "reward_econ": 0.15,
    "reward_text": "￥800 / 一次性",
    "deadline_window_days": 3,
    "source_tag": "mock_seed"
  },
  {
    "job_id": "mj_002",
    "title": "外卖配送时段统计脚本",
    "description": "给定 CSV，按小时聚合订单量并输出柱状图 PNG。",
    "deliverable": "py_script",
    "required_skills": ["数据处理", "matplotlib"],
    "required_job_labels": ["algorithm_engineer"],
    "reward_econ": 0.10,
    "reward_text": "￥500 / 一次性",
    "deadline_window_days": 2,
    "source_tag": "mock_seed"
  },
  {
    "job_id": "mj_003",
    "title": "撰写一篇杭州本地 Citywalk 推文",
    "description": "1500 字内，含 3 个推荐路线、个人化叙事。",
    "deliverable": "md_article",
    "required_skills": ["写作", "本地信息"],
    "required_job_labels": ["content_creator"],
    "reward_econ": 0.08,
    "reward_text": "￥400 / 千字",
    "deadline_window_days": 4,
    "source_tag": "mock_seed"
  }
]
```
正式 seed 至少 15 条：4 类 deliverable × 3-4 个变体（不同薪酬/技能组合），加 2-3 条**故意不匹配 hangzhou_profiles 任何 agent**的对照组（验证筛选确实在工作）。

### 6.5.3 生命周期
```
mock_seed.json ──load──► market.jsonl(open)
                              │
                              │ JobMarket.take(agent_id)
                              ▼
                          taken ──linked_task_id──► WorkQueue
                              │
              ┌───────────────┼────────────────┐
        adapter ok       adapter failed    deadline 过
              ▼               ▼                ▼
            done           failed          expired
                              │
                              └─► 释放回 open（最多重试 1 次）
```

每仿真日开始时：`JobMarket.tick_day(day)` 扫一遍：把 `deadline_sim_day < day` 且仍 `open/taken` 的标记 `expired`；若 `auto_replenish=True` 且 open 数 < 阈值，从 seed 池洗一批新 job 进来（`job_id` 加 `_d{day}` 后缀避免冲突）。

### 6.5.4 接单结算
当 `WorkResult` 回收时（在 `ingest.absorb_completed_for` 里），如果 `task.brief.market_job_id` 非空：
- `status==ok` → `MarketJob.status=done`；`agent.state.econ_security += 0.5 * reward_econ`（clip 0-1）；emotion +0.04；记忆里写"完成接单 X 获得 reward_text"。
- `status==failed/timeout` → `MarketJob.status=failed`；emotion -0.05；记忆里写"未能交付 X，订单作废"。

reward 是否进 `economy_module` 的月度收入**先不挂钩**——保持与 §13 待开放议题一致，等 economy 侧定 spec 再连。

### 6.5.5 与外部系统的关系（M4 留位）
`market.py` 暴露三个钩子：
- `register_external_source(name, fetch_fn)`：让外部系统可以**投递新 job**（webhook 接收端 / MCP 调用）。
- `register_external_sink(name, push_fn)`：把 done 的 job + artifact 推到外部系统（用户的项目管理工具/网盘）。
- `register_pricing_fn(fn)`：把 `reward_econ` 的算法外置（接真实费率）。

M1 这三个都不实现，仅留接口；可以用一个 `BUILTIN_NOOP` 占位。

---

## 7. Adapter 实现要点

所有 adapter 实现 `WorkAdapter`：
```python
class WorkAdapter(Protocol):
    name: str
    supported_deliverables: set[str]
    def run(self, brief: WorkBrief, *, ctx: AdapterContext) -> WorkResult: ...
```

`AdapterContext` 注入 `call_llm`（来自 `llm_providers.py`）、`artifacts_root`、`logger`，避免 adapter 直接依赖配置全局。

### 7.1 WebDesignAdapter（首发）
- `deliverable=html_landing`：用一个 LLM prompt 生成单文件 HTML（内联 CSS，`brief.brief_text` + 风格关键词 from `capabilities.skills`），写到 `<task_dir>/index.html`。
- `deliverable=poster_svg`：LLM 出 SVG 标签字符串，写到 `<task_dir>/poster.svg`。
- 验证：`html.parser.HTMLParser().feed(text)` 能跑通；SVG 检查 `<svg>` 起头。

### 7.2 CodeAdapter
- `deliverable=py_script`：LLM 产 .py，**不执行**（除非 `adapters.code.run_pytest=True`）。落盘后跑 `compile(source, fn, "exec")` 做语法检查。
- 可选：把 `brief.brief_text` 喂给 LLM，附加"同时输出 pytest 单元测试到 test_*.py"。

### 7.3 ContentAdapter
- `deliverable=md_article`：LLM 产 .md，写入头部 frontmatter（agent_id、sim_day、time）。

### 7.4 TeachingAdapter
- `deliverable=lesson_plan`：LLM 产含教学目标/活动/作业的结构化 .md。
- `deliverable=research_note`：LLM 产文献综述风格 .md。

每个 adapter 一个 prompt 模板，模板用 `f-string` + 一份 fewshot example 即可。**不要**做复杂的 chain-of-thought，单次调用够用——这是仿真，不是产品。

---

## 8. 结果回收

`gaworld/work/ingest.py:absorb_completed_for(agent, ...) -> list[WorkResult]`

每 tick 一次，`generative_city_sim.py:6149` 之前调用：
```python
finished = real_work_ingest.absorb_completed_for(agent, limit=CONFIG["real_work"]["tick_ingest_limit"])
for r in finished:
    # 写一条记忆
    add_to_memory(agent, day=day, time=time_str, kind="work_result",
                  text=f"完成{r.summary}，产物：{r.artifact_paths[0]}")
    # 触发一次 emotion 微调（成功 +0.02 / 失败 -0.03）
```
然后**这一 tick 的 outcome** 如果有刚完成的任务，把 outcome 文案改成包含产物路径的版本，让 reflection 看到。

memory_store 已有的 schema（`memory_store.py`）能直接吃 dict，无需改动。

---

## 9. 改动清单（diff 估算）

| 文件 | 改动 | 行数估计 |
| --- | --- | --- |
| `gaworld/work/__init__.py` | 新建 | 10 |
| `gaworld/work/schemas.py` | dataclass | 60 |
| `gaworld/work/capabilities.py` | LLM bootstrap + 缓存 | 120 |
| `gaworld/work/router.py` | 路由判定 | 90 |
| `gaworld/work/queue.py` | jsonl 持久化 | 80 |
| `gaworld/work/worker.py` | 后台线程池 | 110 |
| `gaworld/work/ingest.py` | 结果回收 + 市场结算 | 80 |
| `gaworld/work/market.py` | JobMarket：浏览/接单/过期/补货 | 130 |
| `gaworld/work/market_seed.json` | 15 条 mock 任务 | 80 |
| `gaworld/work/adapters/base.py` | Protocol | 30 |
| `gaworld/work/adapters/web_design.py` | HTML/SVG | 90 |
| `gaworld/work/adapters/code.py` | .py | 70 |
| `gaworld/work/adapters/content.py` | .md | 50 |
| `gaworld/work/adapters/teaching.py` | 教案/笔记 | 60 |
| `config.py` | 加 `real_work` 节 | 30 |
| `generative_city_sim.py` | 2 处 hook + 启动初始化 | ≤25 |
| `tests/test_real_work_router.py` | 单测（含 Path A/B 分流） | 110 |
| `tests/test_real_work_adapters.py` | 单测（mock LLM） | 120 |
| `tests/test_real_work_queue.py` | 持久化单测 | 70 |
| `tests/test_real_work_market.py` | 市场浏览/接单/过期/结算 | 130 |

总计 ~1400 行新代码，**主仿真改动 ≤25 行**——满足"surgical changes"。

---

## 10. 分阶段路线（goal-driven）

### M1：脚手架 + WebDesignAdapter + 自驱路径（1-2 天）
1. 新建 `gaworld/work/` 全套文件（含 `market.py` 但仅占位 stub），仅 WebDesignAdapter 真实实现，其他 adapter 抛 `NotImplementedError`。  
   **verify**：`pytest tests/test_real_work_router.py tests/test_real_work_adapters.py::test_web_design`
2. `config.real_work.enabled=True` 但 `market.enabled=False`，跑 `python generative_city_sim.py run` 1 仿真日，确认 `output/work/agent_2/<task>/index.html` 真的生成且能在浏览器打开。  
   **verify**：手工开 HTML 看一眼 + grep `index.html` 在 jsonl 中。
3. 关掉 `real_work.enabled` 跑一次基准，`pytest tests/` 全绿，证明开关有效。  
   **verify**：CI 全绿。

### M1.5：JobMarket 上线（1-2 天）
1. 实装 `gaworld/work/market.py` + `market_seed.json`（15 条 mock）；router 加 Path B 浏览分支。  
   **verify**：`pytest tests/test_real_work_market.py` —— 至少覆盖：浏览 top_k 排序、接单/释放/过期、结算 econ_security、`max_taken_per_agent_per_day` 上限。
2. `market.enabled=True` 跑 1 仿真日，预期：≥3 个 agent 接到任务、≥1 个完成结算、`market.jsonl` 末态包含 done/expired/open 三种状态。  
   **verify**：`jq` 命令统计 status 分布；TUI/dashboard 临时打印一次接单流水做人工核验。
3. 故意把 seed 里某条 `required_job_labels` 设成 `["doctor"]`（hangzhou_profiles 里没有医生），验证它一直没人接，证明筛选生效。  
   **verify**：1 仿真日后该 job 仍 `open`。

### M2：补齐 4 类 adapter（2-3 天）
Code/Content/Teaching adapter 实现；扩展 `CAPABILITY_PROMPT` 兜底；`market_seed.json` 扩到 4 类全覆盖。  
**verify**：50 个 hangzhou agent 跑 1 仿真日，`output/work/` 至少有 3 类不同产物且每类 ≥1 个；其中至少 50% 来自 market 接单。

### M3：异步队列 + 超时 + 崩溃恢复（2 天）
`WorkerPool` 并发、超时杀任务、重启读 state.json 续跑；market.jsonl 折叠重建末态。  
**verify**：人工 `kill -9` 仿真进程后重启，pending 任务能恢复执行；进行中的 `taken` 状态不丢失。

### M4：webhook / MCP 出口 + 外部投递 job（可选，按需排期）
- `adapters/external_webhook.py`：把 brief POST 出去，把 webhook 返回的 artifact url 当作产物。
- `market.register_external_source` 真实实现：HTTP endpoint 让外部往市场塞 job。
- `adapters/mcp_server.py`：仿真侧暴露 MCP server，外部可调用 `submit_work(...)` 或 `post_job(...)`。

---

## 11. 风险 & 取舍

| 风险 | 缓解 |
| --- | --- |
| LLM 产出的 HTML/代码不可用 | adapter 内有最小验证（HTMLParser / `compile`）；失败标记 `failed`，不污染 reflection |
| 任务堆积爆磁盘 | `output/work/` 加 retention：默认保留 7 仿真日，老任务归档到 `.tar.gz` |
| 50 agent × 多 tick 触发 → LLM 账单飙升 | router 的"节流门 + 工作活动门"是关键；初期再额外加全局 `daily_task_budget` 上限（默认 200/日） |
| 多线程破坏仿真复现性 | 严禁 adapter 触碰全局 random；在 worker.py 顶部 `random` import 加 noqa 注释提示；新单测 `test_determinism.py` 跑两遍仿真比对状态轨迹 |
| profile 解析不出 deliverables（如老人/学生） | `capabilities.deliverables=[]` 走"无能力"分支，与现状等价；不会回退到旧占位以外的行为 |
| 市场任务永远没人接（标签太严或薪酬太低） | M1.5 验收第 3 步专门测；运行时 `JobMarket.tick_day` 把超过 `expire_after_sim_days` 的标 expired，避免堆积 |
| 多 agent 并发抢同一条 job | `JobMarket.take` 用文件锁（`fcntl.flock` on `market_state.json`）+ 状态校验，第二个抢的会得到 `JobAlreadyTaken`，router 静默回退 Path A |
| seed 里 `required_skills` 与 LLM 产出的 `skills` 写法不一致（"排版" vs "版式设计"） | `market.py` 内做归一化（小写 + 去标点 + 同义词表 `_SKILL_ALIASES`，初版手工维护 ~30 条），单测覆盖 |

---

## 12. 验收标准（上线前）

- [ ] `CONFIG["real_work"]["enabled"]=False` 时，`pytest tests/` 与基线 100% 一致（同一 seed，同一状态轨迹）。
- [ ] `enabled=True` 跑 1 仿真日，至少 5 个不同 agent 各产出一份真实可打开的 artifact。
- [ ] 4 类 adapter 各有专门 mock-LLM 单测，覆盖产物落盘 + 失败路径。
- [ ] `WorkQueue` 崩溃重启可恢复（专门单测）。
- [ ] `output/work/capabilities.json` 由 LLM 一次产出后被复用（hash 命中跳过）。
- [ ] 主循环改动 diff ≤ 25 行。
- [ ] **市场专项**：M1.5 跑完后 `output/work/market.jsonl` 同时存在 `done`、`failed/expired`、`open` 三类状态；`max_taken_per_agent_per_day=2` 在仿真日内严格生效；高 `platform_dependence` agent 的接单频次显著高于低值 agent（专门统计脚本验证）。

---

## 13. 待开放议题（不阻塞 M1）

1. agent 之间的"协作工作"（设计师 + 程序员合作落地一个网页）：先不做；M2 之后再讨论是否引入 multi-agent task。
2. 工作产物对仿真状态的反作用：当前只影响 emotion 微量；要不要让"被采纳的设计"提升 econ_security？需要研究侧定 spec。
3. 实际工作触发 vs profile.economy 模块的关系：`economy_module.py` 已有"收入"概念，是否把 work 完成挂钩月度收入波动？M3 之后联调。
