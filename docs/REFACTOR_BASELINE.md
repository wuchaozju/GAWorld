# 阶段 0 基线快照（2026-05-22）

记录重构前的客观指标。所有后续阶段都与这份基线比对。

## 环境

- 项目要求 Python ≥ 3.11（`generative_city_sim.py` 用了 `datetime.UTC`、`gaworld/__init__.py` 标注 py3.11）
- 本次基线用 `uv` 拉的 cpython-3.11.15-linux-aarch64
- pytest 9.0.3，pandas 2.3.3，networkx + matplotlib 已装
- 仓库分支：`Dev`，commit `df91d97` "new experiments and emotion->schedule"

## 1. 测试基线

```
$ pytest tests/ -q
337 passed, 4 failed, 12 warnings in 10.39s
wall time: 11s
```

**4 个失败是预先存在的，与重构无关**（diagnose: 2 个 prompt composition 断言走错分支、2 个 memory review 断言；运行的就是当前 Dev 头）：

- `tests/test_daily_routine_context.py::TestGenerateDailyRoutinePromptComposition::test_high_vs_low_stress_prompt_differs`
- `tests/test_daily_routine_context.py::TestGenerateDailyRoutinePromptComposition::test_prompt_contains_all_new_sections`
- `tests/test_memory_recall_and_review.py::TestMemoryRecallAndReview::test_memory_review_generates_meta_memory`
- `tests/test_memory_recall_and_review.py::TestMemoryRecallAndReview::test_positive_recall_reinforces_repeating_good_action`

**重构成功标准**：每阶段后保持 `≥ 337 pass / ≤ 4 fail`。若任一新失败出现，立刻停下来 root-cause。

## 2. Lint 基线

```
$ ruff check .
Found 544 errors (425 fixable, 69 hidden fixes)

$ ruff format --check .
73 files would be reformatted, 54 already formatted
```

错误 top 类别：

| 数量 | 规则 | 含义 |
|---:|---|---|
| 138 | P006 | （非标准 ruff 码，可能是自定义规则插件——待查） |
| 66 | F401 | unused import |
| 57 | P045 | （自定义） |
| 44 | I001 | import sort |
| 40 | P035 | （自定义） |
| 38 | P015 | （自定义） |
| 22 | F100 | （自定义；不是标准 ruff） |
| 19 | E001 | （自定义） |
| 16 | E402 | module-level import 不在文件头 |
| 13 | W292 | 文件末缺换行 |

> Note：P006/P045 等 P 开头的码不在 pyproject.toml 选中的标准 ruff 集（E/F/W/I/UP/B/C4/SIM/PIE/RUF）。这些大概率来自 ruff 9.x 引入的新规则在子集 selection 之外仍被报。我会在阶段 5 文档刷新前确认是否要把这些纳入 lint gate。

仅 `gaworld/`（新代码区）：85 errors  
仅 `generative_city_sim.py`（巨石）：78 errors

**重构成功标准**：阶段 5 末，`ruff check gaworld/` 与 `ruff check generative_city_sim.py` 的 errors 数**不增加**；总数因迁移可能波动，但 per-file ratio 应改善。

## 3. 性能基线（cProfile，e2e_smoke：1 天 × 2 agent，mock LLM）

```
$ python -m cProfile -o docs/perf/baseline.prof -m pytest tests/test_e2e_smoke.py -q
2 passed in 9.16s
wall: 9.59s
```

`run_simulation()` 累计 **8.488s**（占 wall 的 91%）。

### 最关键的发现：**热点在网络 I/O，不在 Python 计算**

| 项 | cum_t (s) | 备注 |
|---|---:|---|
| `_bootstrap_agent_external_rag` (gen_city_sim.py:3544) | **6.517** | 每 agent 一次外部 RAG 抓取，占 run_simulation 的 77% |
| ↳ `_collect_web_items` → `requests.get` | 6.234 | 实际网络往返 |
| `web_search` (gen_city_sim.py:1044) | **5.496** | 与 RAG bootstrap 共享 HTTP 时间 |
| `_distance_point_to_segment` (city_map_system.py:470) | 0.075 | 90,520 次调用，self 52ms |
| `_distance_to_polyline` (city_map_system.py:485) | 0.108 | 18,104 次 |
| `_build_tile_map` (city_map_system.py:523) | 0.134 | 一次性 |
| 整个 `gaworld/` + legacy 计算函数加起来 | < 0.5 | 计算量微不足道 |

### 战略含义

1. **真正的性能瓶颈是外部 HTTP / LLM I/O**，不是 Python 算法。所以阶段 3 的重点应该是：
   - **缓存 / 短路** `_bootstrap_agent_external_rag`（若 `external_rag` 配置为空或 mock 模式应该完全跳过）
   - **缓存 `web_search` 结果**（同样 query 复用）
   - **并行 LLM 调用**（用 `gaworld/core/runner.parallel_map`，已经有了）
2. **不要把时间花在微优化** `_distance_point_to_segment` 这种已经是 50ms/90k calls 的函数——投入产出比极低。
3. e2e smoke 在 mock LLM 下还在打真实网络，是一个**测试质量问题**：阶段 4 鲁棒性时一并修。

### 重构成功标准（性能维度）

阶段 3 结束时，**禁用外部 RAG 的纯模拟跑** 单 tick 时间下降 ≥ 20%（与基线同等输入），且测试结果不变。HTTP 路径的优化作为副产品（不是首要目标）。

## 4. 静态体量对比基线（重构前）

| 区域 | LOC | 状态 |
|---|---:|---|
| `generative_city_sim.py` | 8044 | 待拆 |
| 根目录其他 legacy `.py` | ~11,000 | 待迁入 `gaworld/` |
| `gaworld/` 子包 | ~3,800 | 目标家 |
| `run_simulation()` 单函数 | 1370 | 拆成 Pipeline + 5 个 phase |

阶段 5 结束时目标：

- `generative_city_sim.py` ≤ 100 行（薄壳 CLI 调用 `gaworld.sim.cli:main`）
- 根目录除 shim 外 ≤ 3 个 `.py`（`config.py` shim、`generative_city_sim.py` shim、可能保留某个一次性脚本）
- `gaworld/sim/` 任一文件 ≤ 800 行
- 任一函数 ≤ 100 行（`run_simulation` → `Pipeline.run` 应该是几十行调度逻辑）

## 5. 决策点

确认基线后，进入**阶段 1：拆 generative_city_sim.py 巨石**。

第一步会是 **阶段 1a：抽出 utils 段到 `gaworld/sim/_utils.py`**（最纯、依赖最少的段，作为热身验证 commit 流程是否平滑）。

完成 1a 后会回来汇报：
- 测试是否仍 `337 pass / 4 fail`
- ruff 数变化
- 文件行数对比

如无回归再继续 1b。
