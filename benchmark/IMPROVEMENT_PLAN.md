# GAWorld 改进计划（基于 GAWorld-Bench 上次运行）

**依据**：`benchmark/results/report.md`（运行于 2026-06-07，real-data `--all`）
**上次结果**：Track A = 0.38 FAIL · Track C = 0.25 FAIL · B/D/E 未实现 · trust gate = OK（实为**未验证**）
**范围**：本计划同时覆盖两条工作流——① benchmark 方法学修正，② 模型/仿真修正。
两者必须分开：上次的"失败"里有一部分是 **benchmark 配置/度量的假象**，不是模型缺陷。先修方法学，再据此定位模型。

> **执行状态（2026-06-15 更新）**：
> ✅ **A1 / A3 / A4 / A5 已实现并验证**（见 `gaworld_bench.py`，设计文档 v0.1.1）。
> 改用 `delta_final` 后 Track C 由 0.25→0.50（符号 2/4：traffic、tax 转正确；layoff 仍反向且 |Δ|≈0.13–0.19）。trust gate 现为 **UNVERIFIED**（确定性未测）。
> 🔴 **B0 发现并修复（阻塞 B1 生效的根因）**：30 天重跑后 layoff 符号仍没翻正——排查发现 `run.log` 里
> `Failed to load extension economy_module:on_simulation_start — No module named 'economy_module'`：
> 经济模块的 hooks 注册在已失效的扁平名 `economy_module` 下，**整个经济子系统在仿真里静默没跑**（连带 B1 也没生效）。
> 已把 `gaworld/settings/integrations.py` 的注册改为真实路径 `gaworld.economy.finance:<fn>`，并加回归守卫测试
> `tests/test_extension_hooks_resolve.py`。端到端验证（经注册的 hook 链）：裁员事件使 income 57→20。
> **影响**：经济子系统现在会在所有仿真里运行（之前是 dormant），Track A 的 wealth_snapshot 等会重新生成真实数据。
> ⚠️ 用户那次 30 天 run 因此**无效**，需在修复后重跑。
>
> 🔴 **B0.5 并行竞态修复**：开经济后重跑，又在 `gaworld/interests.py` 崩溃（`os.replace` FileNotFoundError）——
> compare-event 并行跑 with/without 两个子进程，二者把 growth/capabilities 缓存写到**同一个全局路径**，
> 共用的 `{path}.tmp` 被一个进程 rename 后另一个就找不到了。已把两处原子写（`interests.save_growth_cache`、
> `work/capabilities.save_cache`）的 tmp 改成进程唯一 `{path}.{pid}.tmp`，加守卫测试 `tests/test_cache_parallel_write.py`。
>
> ✅ **B1 已实现并验证**：在 `gaworld/economy/finance.py` 加了事件→经济冲击桥（`_active_event_layoff` + `_check_daily_shocks(event_layoff=...)` + `on_day_start` 接线 + `shocks.event_layoff_prob` 配置）。裁员事件现在**真正削减受影响 agent 收入**（之前只注入感知文本）。测试 `tests/test_event_economy_shock.py`（6 例全过），既有 30 例经济测试不回归。**注**：`econ_security` 是慢 EMA、`stress` 由行为层更新——二者在更长仿真（B2）才会跟随，本次只证明了缺失的因果链（事件→收入冲击）已接通。
> ✅ **B2 验证通过（2026-06-20，30 天实跑）**：经济跑起来后裁员符号全部翻正——`econ_security` delta_final
> **−0.050 ✓**（事件前 +0.133）、`stress` **+0.172 ✓**（事件前 −0.192）、`emotion` −0.157、`risk_preference` −0.078。
> harness **Track C = 1.0 PASS，符号 4/4**。从"benchmark 报错 → 4 个真 bug（delta_mean 稀释 / 事件未接经济 / hook 没加载 / 并行竞态）→ 因果信号正确"全链路打通。
> **诚实边界**：trust gate 仍 **UNVERIFIED**（确定性/安慰剂未测）；traffic、tax 两条仍是经济关闭时的旧 3 天 run（建议同样 30 天重跑取得干净证据）；单 seed，A2 显著性未做。
> ✅ **A2 已实现（多 seed 显著性）**：`--seeds 1,2,3,4,5` 模式，每个干预算 95%CI，只对显著项计分、不显著记 `ns`，
> 新增 `significance_coverage` 与 pass 门槛（显著覆盖 ≥0.5）。单元测试 `benchmark/test_gaworld_bench.py`（6 例）。
> ⏳ 待办：用 `--run --seeds` 对经济类干预实跑多 seed 拿置信区间、traffic/tax 30 天重跑、安慰剂+确定性补齐、清理失败遗留目录、**B3/B4**（Track A）。

---

## 0. 结论先行（TL;DR）

1. **最重要的发现是一个度量 bug，不是模型 bug**：Track C 用 `delta_mean`（对**整段仿真**求平均，含事件发生前的步）打分，把信号稀释了 5–7 倍。改用**事件后窗口**（`delta_final` / post-event mean）后，效应量从 ~0.02 跳到 ~0.13–0.19，**结论会反转**。
2. 改正度量后，真正的模型问题浮现：**裁员干预方向是反的**——事件后 `stress`↓、`emotion`↑、`econ_security`↑，与现实相反，强烈提示**裁员事件没有接到经济冲击**（只注入了感知文本，没真正削减收入）。
3. **trust gate=OK 是假性安心**：确定性从未被测试；安慰剂 run 中断（没产出 `comparison_metrics.csv`）。在补齐这两项之前，任何 Track C 结论都只能算"未验证"。

优先级：**A1（修度量）→ 重跑 → B1（查裁员接线）** 是关键路径，先做这三件。

---

## 1. 上次运行结果回顾

| Track | 命题 | 分数 | 结论 | 备注 |
|---|---|---|---|---|
| A | 宏观经验拟合 | 0.38 | FAIL | `savings_rate` sim 0.25 vs 锚点 0.35（误差 28.6%）；样本仅 **1** 个 agent |
| B | Stylized-facts | n/a | 未实现 | 盲区 |
| C | 因果反事实 ⭐ | 0.25 | FAIL | 符号 1/4；安慰剂未评估；确定性未评估 |
| D | 可信度一致性 | n/a | 未实现 | 盲区 |
| E | 可复现/成本 | n/a | 未实现 | 确定性见 C |

---

## 2. 根因分析（均以上次运行的真实数据为证）

### R1 ⚠️【benchmark】Track C 度量稀释：用了 `delta_mean` 而非事件后窗口
事件在 Day 2 09:00 触发，3 天仿真。`delta_mean` 对**全部步**（含事件前的 Day 1 与 ramp）求平均，把效应摊薄。
证据（裁员 run `大规模裁员冲击`）：

| 指标 | `delta_mean`（现用） | `delta_final`（事件后） | 倍数 |
|---|---|---|---|
| `stress` | −0.033 | **−0.192** | 5.8× |
| `econ_security` | +0.020 | **+0.133** | 6.8× |
| `emotion` | +0.024 | +0.145 | 6.0× |

→ 上一轮"效应近乎为零、被噪声主导"的判断是**度量假象**。真实事件后效应是显著的。

### R2 🔴【model】裁员干预方向相反 → 疑似未接经济冲击
即便用 `delta_final`（大效应），裁员后：`stress` **−0.192**（应↑）、`emotion` **+0.145**（应↓）、`econ_security` **+0.133**（应↓）、`risk_preference` +0.124。
四个福祉相关指标**全部朝乐观方向**移动，与"裁员"现实相反。最可能的原因：`compare-event` 把事件文本注入了 agent 感知，但 **economy 模块的 layoff shock（收入 −50~85%）没有被真正触发**，于是看到的是 LLM 的乐观漂移而非真实冲击。**待验证**（见 B1）。

### R3 🔴【benchmark】安慰剂未评估：placebo run 中断
`图书馆闭馆时间微调/` 下只有 `with_event/` 与 `without_event/`，**没有顶层 `comparison_metrics.csv`** → 聚合步未完成。harness 据此正确地标"未评估"，但没提示"运行不完整"。

### R4 🔴【benchmark】确定性从未测试，trust gate 却显示 OK
`gate_determinism_ok` 在确定性"未评估"时默认 True → trust=OK。这是**假性安心**：我们其实不知道同 seed 能否复现。

### R5 🟡【benchmark】单 seed、点估计、无显著性
所有 Δ 都是单次运行的点值，没有置信区间。`|Δ|=0.02` 的"错符号"无法区分真实效应与采样噪声。

### R6 🟡【model/benchmark】Track A：样本 n=1 且 `savings_rate` 偏低
`output/economy/wealth_snapshot.csv` 只有 1 行 → 默认 run 没产出全体 agent 的财务快照。`savings_rate` 0.25 与锚点 0.35 差 28.6%，但锚点口径本身未锁定（住户存款/收入 ~43% vs 可支配收入流量储蓄 ~30–35%）。

---

## 3. 修改计划

格式：每项给出 **问题 → 改动 → 验收标准（可循环验证）**。

### 工作流 A — Benchmark 方法学修正（先做：会改变结论，且成本低）

**A1 ⚠️ Track C 改用事件后窗口（最高优先）**
- 问题：R1，`delta_mean` 稀释信号。
- 改动：`_delta_mean()` 改为读事件后窗口——优先 post-event 均值（事件步之后的 `value` 平均），无则回退 `delta_final`；保留 `delta_mean` 仅作参考。
- 验收：重跑后 `tax_cut/econ_security` 由 FAIL→PASS（`delta_final` +0.020，符号正确）；`layoff_shock` 仍 FAIL 但 `|Δ|>0.1`（大而反向，把问题甩给模型侧 B1）。

**A2 加显著性 / 跨 seed 置信区间**
- 问题：R5。
- 改动：每个干预跨 ≥5 个 seed 重复，对 Δ 做单样本检验，输出 95% CI；符号检验**仅在 CI 不含 0** 时计分，否则记"不显著"。
- 验收：报告每个干预项出现 `Δ = x ± ci`，且"不显著"项不再误判为对/错。

**A3 覆盖度折扣**
- 问题：1/1 覆盖时 Track C=1.0 看起来像满分（见更早一次运行）。
- 改动：`score_C ×= (n_eval / 已配置项数)`，并在 scorecard 标注覆盖系数。
- 验收：1/4 覆盖时分数显著低于满分且显式标注覆盖度。

**A4 确定性 gate 修正 + 自动双跑**
- 问题：R4。
- 改动：确定性"未评估"时 trust 显示 **`UNVERIFIED`**（而非 OK）；`--run` 模式自动跑两遍同 seed baseline 并比对。
- 验收：不提供 `--det-a/--det-b` 且未自动双跑时 trust=`UNVERIFIED`；双跑一致时=OK。

**A5 不完整 run 检测**
- 问题：R3。
- 改动：任一对照目录缺 `comparison_metrics.csv` 时，报告显式标"运行未完成"并给出重跑命令。
- 验收：当前 `图书馆闭馆` placebo 触发该提示。

### 工作流 B — 模型/仿真修正（基于修正后的 benchmark 再定位）

**B1 🔴 核查裁员事件 → 经济冲击接线（关键）**
- 问题：R2。
- 改动：排查 `compare-event` 的事件是否真正调用 economy 的 layoff shock，还是仅注入感知文本；若未触发，把事件类型映射到 economy 的 shock 接口。
- 验收：写一个测试——注入裁员事件后，受影响 agent 当日 `income` 下降且 `econ_security` 下降、`stress` 上升（事件后窗口符号正确）。

**B2 经济类干预延长仿真到 ≥30 天**
- 问题：裁员恢复 30–90 天、税改按月结算，3 天看不全。
- 改动：Track C 对经济类干预默认 `--days 30`（出行类可保持短）。
- 验收：30 天 run 的事件后窗口效应方向正确且跨 seed 稳定。

**B3 让默认 run 产出全体 agent 的财务快照**
- 问题：R6，`wealth_snapshot.csv` 仅 1 行。
- 改动：核查 economy 输出为何只落 1 个 agent；修复为全体 agent。
- 验收：`wealth_snapshot.csv` 行数 = agent 数。

**B4 锁定 `savings_rate` 口径并校准**
- 问题：R6。
- 改动：在设计文档与 ANCHORS 注释里锁定"可支配收入流量储蓄"口径（~30–35%）；核对 economy 的 `savings_rate` 计算是否同口径。
- 验收：修正样本量后 sim `savings_rate` 落入锚点 ± 容差内。

---

## 4. 执行顺序（依赖关系）

```
A1 (修度量) ─┬─> 重跑 benchmark ──> B1 (查裁员接线) ──> B2 (延长仿真)
A4 (gate)   │
A5 (不完整) │
A3 (覆盖度) ─┘
A2 (显著性, 需多 seed 算力) ── 与 B2 并行
B3/B4 (Track A) ── 独立, 可随时插入
```

关键路径：**A1 → 重跑 → B1**。先用低成本的 harness 改动把结论摆正，再投算力查模型。

---

## 5. 验收总览（Definition of Done）

| ID | 验收标准 | 影响 |
|---|---|---|
| A1 | tax/econ_security 转 PASS；layoff 仍 FAIL 且 \|Δ\|>0.1 | Track C |
| A2 | 每项 Δ 带 95% CI；不显著项单列 | Track C |
| A3 | 覆盖系数纳入分数并标注 | Track C |
| A4 | 未验证确定性时 trust=UNVERIFIED | trust gate |
| A5 | 不完整 run 显式告警 + 重跑命令 | 报告 |
| B1 | 裁员后受影响 agent income↓/econ_security↓/stress↑（测试通过） | 模型 |
| B2 | 30 天 run 事件后符号正确且跨 seed 稳定 | 模型 |
| B3 | wealth_snapshot 行数 = agent 数 | Track A |
| B4 | sim savings_rate 落入锚点±容差 | Track A |

---

## 6. 备注与风险

- **算力**：A2 + B2（多 seed × 30 天 × 多干预）是主要成本，需要可用的 LLM provider；建议先在出行类（短仿真）上跑通流程。
- **LLM 随机性**：B1 的"方向反了"结论必须在 A1+A2 完成后复核——确认是接线问题而非采样噪声。
- **尺度**：当前 5 agent 子集统计不稳；Track A/B 的部分判据需要更大 N。
- **顺序纪律**：不要在 A1 之前据 `delta_mean` 去"修模型"，否则会按假信号瞎改（这正是上一轮差点发生的）。
