# Tier B 运行手册（快进档，服务 Track R 的 R2 维度）

**日期**：2026-08-14 · **状态**：待在本机执行 · 配套设计见 `GAWORLD_RUBRIC_BENCH.md` §2.4

---

## 0. 前置：现有 output/ 已归档

旧的 438M `output/`（2026-06 的数据）已移到 **`output_archive_202606/`**，
其中 `comparisons/`（Track C 用）完整保留。当前仓库根目录**没有** `output/`，
Tier B 会从零写一份干净的。

> 跑完 Tier B 后立刻 `mv output output_tierB`，否则 Tier A 会写进同一个目录，
> 两次 run 的产物混进一张 scorecard 且不会报错——这是本项目最危险的失败模式。

---

## 1. 命令

```bash
cd /path/to/GAWorld

export GAWORLD_CONFIG_OVERRIDES='{
  "agent_ids": [1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20],
  "sim_days": 60,
  "random_seed": 42,
  "long_run": {"enabled": true, "randomness": 0.25},
  "concurrency": {"day_routine_workers": 8},
  "distributed": {"enabled": false},
  "visualization": {"enabled": false},
  "llm": {"routing": {"default": "minimax", "tasks": {"schedule": "minimax"}}}
}'

python3 generative_city_sim.py run --fast-forward --sim-days 60 2>&1 | tee /tmp/tierB.log

mv output output_tierB
```

参数依据：

| 参数 | 值 | 理由 |
|------|----|------|
| `agent_ids` | 1–20 | R2.5 群体分化要算跨 agent 方差，人少估计不稳。`data/hangzhou_profiles_with_names.md` 有 51 个可用 |
| `sim_days` | 60 | R2 的 `min_days=30` 是硬门槛，60 天留出余量给趋势检验 |
| `long_run.randomness` | **0.25**（原 0.9） | ⚠️ 关键。该值按设计注入突发事件+状态抖动；R2.1 的判据是「幅噪比 > 1 且 Mann-Kendall p < 0.05」，0.9 会把噪声底抬到淹没真实趋势，得到一个**假的**「演化能力不足」 |
| `concurrency.day_routine_workers` | 8 | 默认 **1（全串行）**。快进的每日 digest 是每 agent 一次独立调用，走同一个并发钮。串行 ≈ 5 小时，8 并发 ≈ 40 分钟 |
| `distributed` / `visualization` | false | 前者会去连 127.0.0.1:8877 并降级；后者对 Track R 无用，只增 IO |
| `random_seed` | 42 | 记录进 scorecard，便于复现 |

**成本量级**：20 agent × 60 天 = **1200 次 `fast_forward_day` 调用**（每 agent 每天一次），
外加日边界 hook。MiniMax 实测单次探针延迟 7.4s，真实 digest 更长，按 ~15s 估。

---

## 2. 跑完之后

```bash
cd benchmark
python3 rubric_bench.py --output-dir ../output_tierB --ablate N3,N4,N5
```

预期：`run 模式: fast_forward`，R1/R3/R4 全部标「本次运行无此数据」，
R2 给出 5 个适用 item 里的实际得分。**R2.1 与 R2.5 的判别力必须 ≥ 0.3**，
否则说明消融没咬住，分数不可用。

---

## 3. 沙盒验证到哪一步（2026-08-14）

能验证的都验证了，剩下的必须在本机跑：

| 项 | 结果 |
|---|---|
| MiniMax 可达 | ✅ `probe_provider` ok，延迟 7453ms，模型 MiniMax-M2.7 |
| 仿真能启动 | ✅ 人口合成、家庭结构、目标系统均正常初始化（2 agent） |
| 跑完 2×2 冒烟 | ❌ **沙盒做不到**：单次工具调用被硬限 ~180 秒，且调用结束时所有后台进程被杀。光启动阶段就超过 3 分钟 |
| 快进是否真的不写 episodes | ⚠️ **仍是代码推断，未在真实产物上验证**。见 §4 |

沙盒特有、**本机不会遇到**的问题（记录以免混淆）：
Python 3.10 vs 仓库要求 3.11（`datetime.UTC`）；FUSE 挂载上 SQLite 报 `disk I/O error`；
FUSE 不允许 unlink。

---

## 4. 跑完请顺手确认的两件事

我的能力门控（`requires` / `_n_days`）建立在读代码得出的两个推断上，**尚未被真实产物验证**。
Tier B 跑完后花两分钟确认，比全量跑完才发现要便宜得多：

```bash
# 推断 1：快进不写 episodes（append_agent_episode 在被绕过的日内 tick loop 里）
ls output_tierB/memory/*_episodes.jsonl 2>/dev/null | wc -l    # 期望 0

# 推断 2：state_history 每 agent 每天一点（_n_days 完全依赖这一条）
python3 - <<'PY'
import csv, collections
c = collections.Counter()
with open("output_tierB/state/agent_state_history.csv") as f:
    for r in csv.DictReader(f):
        c[(r["agent_id"], r["metric"])] += 1
print("每 (agent,metric) 的点数样本：", list(c.items())[:5])   # 期望 ≈ 60
PY
```

若推断 2 不成立（比如每天多点），`sampler._n_days` 会高估天数，
`min_days=30` 的门槛就形同虚设——需要改成按 `day` 列去重计数。

---

## 5. 跑之前值得知道的两个既有缺陷

在启动阶段实测到，**未擅自修改**（按项目规范只记录）：

### 5.1 `load_news_sources` 的正则把每个 URL 截断在第一个 `s`

`gaworld/sim/_news.py:107`

```python
urls.extend(re.findall(r"https?://[^\\s)]+", text))
```

`r"[^\\s)]"` 在正则里的含义是「非反斜杠、**非字母 s**、非右括号」，
所以 `https://news.baidu.com/` 只匹配出 `https://new` 就停了——
这正是运行时那条 `fetch_news_excerpt failed for https://new` 的来源。
上一行 `r"\\((https?://[^)\\s]+)\\)"` 同理，要求 URL 前有字面反斜杠。

后果：新闻源**从来没有真正加载成功过**，每个 agent 启动时白等一次 8 秒超时
（20 agent ≈ 160 秒），且环境信号里缺了新闻这一路。

代码上方有一条注释写着「Preserved verbatim from the legacy source… Do NOT "fix" this
during the extraction」——那条注释保护的是迁移过程的忠实性，但这个正则本身是错的。
**改不改由你定**，不改的话 Tier B 的 `env_events` 里不会有新闻来源的内容。

### 5.2 `generate_agent_rag_seed` 已移入 `legacy/`，但导入路径没跟着改

`generative_city_sim.py:1377` 仍 `import generate_agent_rag_seed`，
而该文件现在在 `legacy/generate_agent_rag_seed.py`（根目录只剩 `__pycache__` 里的旧 .pyc）。
每个 agent 启动时报一条 warning 后跳过 RAG 冷启动注入，非致命。
仓库根目录残留的 `__pycache__/generate_agent_rag_seed.cpython-31*.pyc` 是这次搬迁的孤儿。
