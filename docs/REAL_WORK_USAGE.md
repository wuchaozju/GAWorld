# Real Work — 使用说明

让仿真居民根据其职业 / 技能 / 兴趣去做**真实**的工作（HTML 页面、Python 脚本、Markdown 文章、教案/研究笔记），并且可以从一个 mock 工作机会市场上**浏览、接单、结算**。本文档讲怎么打开它、怎么扩它、产物在哪、出问题怎么排查。

设计文档：[`docs/REAL_WORK_DESIGN.md`](REAL_WORK_DESIGN.md)。

---

## 1. 启用 / 关闭

默认是**关闭**的——`config.py` 里 `CONFIG["real_work"]["enabled"] = False`。关着的时候，整条新代码路径都是 no-op，仿真行为与之前完全一致。

打开它：

```python
# config.py
"real_work": {
    "enabled": True,          # ← 改成 True
    "market": {
        "enabled": True,       # 是否启用工作机会市场
        ...
    },
    ...
}
```

或者用项目已有的 JSON 覆盖机制（`dashboard_config.json`、`GAWORLD_CONFIG_OVERRIDE` 等）：

```json
{
  "real_work": {
    "enabled": true
  }
}
```

启用后第一次跑仿真：

```bash
python generative_city_sim.py run
```

会看到日志：

```
INFO  gaworld.work.runtime  derived capabilities for 50 agents (cache=output/work/capabilities.json)
INFO  gaworld.work.worker   WorkerPool started (workers=2, timeout=600s)
```

---

## 2. 产物在哪

```
output/work/
├── capabilities.json        # LLM 派生的「职业 → 能力」映射缓存
├── queue.jsonl              # 任务队列事件日志（submit / claim / result）
├── market.jsonl             # 市场事件日志（post / update）
└── agent_<id>/
    └── <task_id>/
        ├── index.html       # 设计师产出（html_landing）
        ├── poster.svg       # 设计师产出（poster_svg）
        ├── main.py          # 程序员产出（py_script）
        ├── test_main.py     # 程序员产出（带单测时）
        ├── article.md       # 新媒体产出（md_article）
        ├── lesson_plan.md   # 教师产出（lesson_plan）
        └── research_note.md # 研究者产出（research_note）
```

`agent_<id>/` 名字直接对应 `hangzhou_agents_state_init.csv` 里的 id，方便溯源。

如果启用了兴趣爱好与技能成长系统，真实工作路由会把 `agent["growth_profile"]` 中计划发展的技能和兴趣
合并进能力匹配表面，但不会改变 `AgentCapabilities` 的 JSON schema。运行中可同时查看：

- `output/memory/growth_profiles.json`：兴趣/技能画像推导缓存
- `output/memory/agent_<id>_growth.json`：单个智能体的成长进度

---

## 3. 检查市场状态

`market.jsonl` 是事件流；要看「当前活态」用 jq 就行：

```bash
# 折叠出每个 job 的最终状态
jq -s '
  reduce .[] as $e ({};
    if $e.event == "post" then .[$e.job.job_id] = $e.job
    elif $e.event == "update" then .[$e.job_id] += $e.patch
    else . end
  )
  | to_entries
  | map({id: .key, status: .value.status, taken_by: .value.taken_by_agent_id, title: .value.title})
' output/work/market.jsonl
```

或者直接用 Python：

```python
from gaworld.work.market import JobMarket
m = JobMarket(
    store_path="output/work/market.jsonl",
    seed_path="gaworld/work/market_seed.json",
)
print(m.status_counts())   # {"open": 8, "taken": 3, "done": 2, "expired": 1, ...}
for j in m.all_jobs():
    print(j.job_id, j.status, j.taken_by_agent_id, j.title)
```

---

## 4. 扩展 mock 任务池

往 `gaworld/work/market_seed.json` 加条目即可：

```json
{
  "job_id": "mj_017",
  "title": "新任务标题",
  "description": "≤200 字简报",
  "deliverable": "html_landing | poster_svg | py_script | py_test | md_article | lesson_plan | research_note",
  "required_skills": ["技能词1", "技能词2"],
  "required_job_labels": ["ui_designer | algorithm_engineer | content_creator | teacher_researcher"],
  "reward_econ": 0.10,
  "reward_text": "￥500 / 一次性",
  "deadline_window_days": 4,
  "source_tag": "mock_seed"
}
```

注意：

- `deliverable` **必须**在枚举内，否则启动时会被静默跳过。
- `required_job_labels` 留空数组 `[]` 表示开放给所有职业。
- `deadline_window_days` 是**相对天数**——市场加载时按 `posted_sim_day + window` 计算实际截止日，所以同一个 seed 在不同启动日都能用。
- `job_id` 必须唯一；当 `auto_replenish` 重新洗牌时，会自动加 `_d{day}` 后缀避免冲突。

加完直接重启仿真即可（市场会自动 replenish），不需要改代码。

### 对照组任务

`market_seed.json` 里有一条 `mj_016` 故意要求 `["doctor"]`——50 个杭州居民里没有医生，这条任务永远不会被接，作为筛选生效的反向证明。删它之前先想想要不要保留这个验证位。

---

## 5. 调几个旋钮

`config.py → real_work` 里几个常用：

| 项 | 默认 | 调它做什么 |
| --- | --- | --- |
| `max_concurrent_tasks` | 2 | 后台同时跑几个 LLM-驱动的 adapter；调高会更快但 LLM 账单飙升 |
| `task_timeout_seconds` | 600 | 单个 adapter 运行超时；本地 ollama 慢的话可以调到 1200 |
| `tick_ingest_limit` | 5 | 每个 agent 每个 tick 最多回收几条结果 |
| `market.browse_top_k` | 5 | agent 浏览市场时看 top 几条 |
| `market.max_taken_per_agent_per_day` | 2 | 单个 agent 每仿真日最多接几单 |
| `market.browse_probability_base` | 0.15 | 浏览市场基础概率（会再叠加 platform_dependence / econ_security） |
| `market.expire_after_sim_days` | 5 | 过了截止日的 open/taken 任务会被标 expired |

---

## 5.5 Skill 注入（自动）

启用 `CONFIG["skills"]["inject_into_work_brief"]`（默认 ON）后，router 会在投递 brief 时
自动匹配 agent 持有的 Skill：用 `chosen_action + activity` 文本与每个 Skill 的 `name` /
`triggers` 做子串匹配，最多取 3 个最相关的，追加到 brief 末尾：

```
【可用技能】
- 海报网格排版：用三栏网格 + 单一主色，快速给宣传海报定排版
  · 1. 先选一个主色（占面积 ≥ 60%）...
- 结构化代码评审：...
```

adapter（`CodeAdapter` / `WebDesignAdapter` 等）原本就把 `brief_text` 整段拼进 LLM
prompt，所以 **adapter 代码不需要改**——Skill 的指导内容会自然出现在工作产物的上下文里。

调用侧：

```python
from gaworld.skills import SkillRegistry
from gaworld.work.router import RealWorkRouter

router = RealWorkRouter(
    queue=queue, market=market,
    capabilities=caps_by_agent,
    config=CONFIG["real_work"],
    skill_registry=SkillRegistry(),   # 不传则用默认实例
)
```

要给 agent 挂载技能或让 agent 从经历中自总结 Skill，见
[`docs/SKILL_SYSTEM.md`](SKILL_SYSTEM.md)。

---

## 6. 写自定义 Adapter

继承 `WorkAdapter` Protocol：

```python
# my_app/my_adapter.py
from gaworld.work.adapters.base import AdapterContext, make_failed, make_ok
from gaworld.work.schemas import WorkBrief, WorkResult


class VideoStoryboardAdapter:
    name = "video_storyboard"
    supported_deliverables = frozenset({"video_storyboard"})

    def run(self, brief: WorkBrief, ctx: AdapterContext) -> WorkResult:
        import time
        started = time.time()
        # 调 LLM 生成分镜脚本
        body = ctx.llm(f"生成视频分镜：{brief.brief_text}")
        out_path = f"{ctx.task_dir(brief)}/storyboard.md"
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(body)
        return make_ok(brief, [out_path], summary=f"完成分镜：{brief.chosen_action}", started_at=started)
```

接入：在 `gaworld/work/adapters/__init__.py:build_default_adapters` 里加一行，并在 `gaworld/work/schemas.py:DELIVERABLES` 里追加 `video_storyboard`。最后在 `gaworld/work/router.py:_DELIVERABLE_TO_ADAPTER` 里加映射。三处加完就能跑。

---

## 7. 排查清单

| 现象 | 看哪 |
| --- | --- |
| 启动时长，capabilities 反复算 | `output/work/capabilities.json` 是否被每次都覆盖；profile 字段 hash 变了会触发重算 |
| agent 技能看起来和真实工作不匹配 | 同时检查 `output/work/capabilities.json` 和 `output/memory/agent_<id>_growth.json`；职业能力来自 profile，计划发展技能来自 growth profile |
| agent 永远不接单 | `market.jsonl` 里有没有匹配 agent `job_label` 的 job；`browse_probability_base` 是不是 0；agent 是不是当天已用完 quota |
| 任务一直 pending 不 done | WorkerPool 是否启动（看日志 `WorkerPool started`）；adapter 是不是抛了未捕获异常（看 `adapter crashed` 日志） |
| 产物文件存在但内容不对 | adapter 的 LLM prompt 在各自 `gaworld/work/adapters/*.py` 顶部，按需调 |
| 仿真随机性变了 | router/market 用的是 `deterministic_random(agent_id, day, salt)` 局部 Random，不该影响全局；如果还是变了，看是不是 adapter 内部用了全局 `random`（见 §8） |

---

## 8. 与仿真复现性

`gaworld/core/runner.py` 那条规则在这里同样适用——**adapter 不要碰全局 `random`**。如果你写的 adapter 需要随机，请用 `random.Random(seed)` 局部实例。否则在 `max_concurrent_tasks > 1` 时会破坏 `random_seed` 复现性。

router 和市场的所有概率判定都已经走 `deterministic_random(agent_id, sim_day, salt)`，不动全局状态。

---

## 9. 关掉它

```python
"real_work": {"enabled": False}
```

或者整个 `real_work` 节删掉。改后跑 `pytest tests/`，应该与 baseline 100% 一致——这是设计的硬约束。

---

## 10. 跑测试

新单测在 `tests/test_real_work_*.py`：

```bash
python -m unittest tests.test_real_work_queue tests.test_real_work_market tests.test_real_work_router tests.test_real_work_adapters
```

或者跑完整套：

```bash
pytest tests/
```

---

## 11. 后续路线（M3 / M4 待做）

- **M3**：WorkerPool 增加更强的崩溃恢复语义（处理"claim 后未完成就 kill"的悬挂任务），以及对超时任务真正发杀鸡信号（当前是只标记 timeout 不杀线程）。
- **M4**：HTTP webhook 出口（push artifact 到外部）+ 让外部往市场塞 job + 把仿真侧暴露为 MCP server。预留位在 `gaworld/work/runtime.py` 的 config `external_hooks` 里。
- **economy 联动**：把 market reward 接入 `economy_module` 的月度收入波动（见设计文档 §13）。
