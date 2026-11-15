# 人类相似度基准（Track H）设计规格

**日期**：2026-11-15 · **状态**：设计已定稿，实现未落地 · **入口**：[`docs/HUMANLIKE_BENCH_TUTORIAL.md`](../../HUMANLIKE_BENCH_TUTORIAL.md)

本规格只记录**决策与取舍**。完整说明（签名表、锚点清单、判据公式、CLI、待核清单）在入门文档里。

---

## 1. 问题

GAWorld 有两套基准，都不回答"像不像真人"：

- `benchmark/GAWORLD_BENCH_DESIGN.md`（Track A–E）：宏观统计拟合（**回显参数**，循环）、因果引擎、真人盲测（`谁是真人`）。
- `benchmark/GAWORLD_RUBRIC_BENCH.md`（Track R1–R4）：rubric-as-reward + 消融判别力。
  其 §7.2 明确留了一个洞：**消融只证明能识别人为损坏，不证明能识别"结构完好的假"**。

Track H 补这个洞：拿**已发表的真人统计规律**当绝对锚点，
用一把**必须能分开真人与"结构完好的假"**的尺子去量仿真行为。

## 2. 决策

| # | 决策 | 备选 | 理由 |
|---|---|---|---|
| D1 | 新增独立 Track H，**不并入** Track R | 并入 R 作为 R5 | 判据体系不同（规则 + 文献锚点 vs LLM judge + 消融）；合并会让 Track R 的 `UNVERIFIED` 传染 |
| D2 | 锚点用**文献现成值** | 自采本地人群 | 零成本、可引用、可复现；代价是人群多为西方样本，靠口径标注与敏感度分析兜底 |
| D3 | v1 五族 15 条：A 节律 / B 统计结构 / C 情绪 / D 自述—实做 / E 社会 | 含 F 语言表层统计 | F 留到后续；D1/C2/E1/E2 四条 provenance 低、锚点硬、产物齐备 |
| D4 | **双判据**：J1 带内 AND J2 分布 | 只 J1 / 只 J2 / J1 OR J2 | 只 J1 抓不到"中心对、形状错"（AI 味重灾区）；OR 会放松 J2 |
| D5 | 阈值 τ = **H 型对自身的抽样波动 95 分位** | 人工定阈值 | 真人之间本来就有波动，阈值不能比这更严；同 Track D「用真人自己的通过率做分母」 |
| D6 | **M 型负对照**：M 型必须判不合格，否则该签名作废 | 不设负对照 | 直接堵住 Rubric-Bench §7.2 的洞；尺子无效 = 所有分数无效 |
| D7 | **三档**：夹具 / 快档（门禁）/ 慢档（定论） | 单档 | token 花在造数据不在评分；两档差在样本量与结论强度，不在"调不调 LLM" |
| D8 | 锚点四要素（source / population / n / statistic）缺一 → `UNVERIFIED` | 缺一给个大概值 | 缺证据不是模型的失败；写个没核实的数等于用"查了个数"冒充"查清了" |
| D9 | 每条签名声明 **provenance**（是否被直接参数化），报告分栏 | 不分栏 | 照抄 `MECHANISM_PROVENANCE.md` 的教训：高 provenance 的通过只说明实现没 bug |
| D10 | 库放 `gaworld/humanlike/`，CLI 放 `benchmark/` | 全部放 `benchmark/humanlike/`（同 `benchmark/rubric/`） | AGENTS.md 规定新代码只进 `gaworld/`；CLI 与既有 `rubric_bench.py` 同构 |
| D11 | 慢档**必须 tick loop**，禁 fast-forward | 快进跑长 | 已核实：fast-forward 走 `_run_fast_forward_step`，episode 落盘在 `gaworld/sim/_stages.py` 的 tick 阶段 → 快进 run 一条 episode 都不写，A/B/D/E 全族不可评 |

## 3. 已知硬约束（已核实）

- **零 token**：五族签名与 surrogate 全是规则计算；token 成本全在造数据端。
- **快进 run 不可用**：见 D11。
- **现有产物太稀疏**：`output/` 仅 11 个 agent 有 episodes、9 个有日记 → 快档覆盖度必然低，只能当回归信号。
- **可复用**：`gaworld/group/metrics.py` 已有 `wasserstein1` / `ks_statistic` / `distribution_gap`（含 `sd_ratio`），不重写。
- **受控 run 的入口**：`run_simulation()` 无参数、读 `CONFIG`；设 `CONFIG["random_seed"/"agent_ids"/"sim_days"/"run_output_dir"]` 即可，与 `compare-event` 同一套路。

## 4. 主要风险

| 风险 | 缓解 | 残余风险 |
|---|---|---|
| 文献口径误读 | 出处必填 + 敏感度分析（`flip_rate`）+ 锚点变更断代 | 无法根治。锚点脆弱的签名不进 headline |
| H 型是合成的 | 措辞纪律：结论只能说"与文献描述的真人不可区分" | 永远不是图灵测试 |
| 样本量 | 12 agent × 14 天只支撑组级分布检验 | 长尾签名（B2/B3）只报区间，不报结论 |
| 与 Track A 同样的循环风险 | provenance 分栏 + 优先选低 provenance 签名 | 高 provenance 的族仍然只能算卫生检查 |

## 5. 落地顺序

`H0` 锚点清单骨架 → `H1` 观测量提取器 → `H2` surrogate + 判据 → `H3` 聚合 + CLI + 夹具自检
→ `H4` **锚点逐条核实** → `H5` 慢档受控 run → `H6` 敏感度 + provenance 分栏进报告。

**H4 之前产生的任何分数标 `UNVERIFIED`，不进对外材料**（同 Rubric-Bench 的 P4 之前）。

## 6. 待用户确认

- §3.2 签名表的具体取舍（A3 唤醒时长占比、B2 片段时长是否过细）。
- 慢档 12 agent × 14 天的规模，与 tick-loop 的 LLM 成本是否匹配（现有 run 的推进速度决定一周能跑几轮）。
- 锚点核对的执行者与期限（H4 是唯一的阻塞项）。
