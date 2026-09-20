# GAWorld-Bench 设计文档

**版本**：v0.1.1 ·  **日期**：2026-06-15 ·  **状态**：Track A + Track C 已实现 harness（A1/A3/A4/A5 已落地）

---

## 0. 一句话

GAWorld 没有单一的"成功分数"。它同时是一个**软件工件**和一个**科学仪器**，
因此衡量成功必须是一套**分层验证套件**，每一层检验一个不同的"它声称为真"的命题。
本文档定义该套件 **GAWorld-Bench**，并给出可运行的评分与聚合规则。

设计原则：

1. **不塌缩为单一标量。** 输出是一张按 track 分项的 scorecard / 雷达图，而非一个数字。
2. **区分"被参数化的"与"自发涌现的"。** 你亲手写进模型的分布（恩格尔曲线、税率表）
   再去验证它贴合现实，近乎循环论证；真正有说服力的是没有直接参数化、却涌现出来的结果。
3. **因果层优先。** GAWorld 的唯一卖点是"可控反事实实验"。如果对照实验不可信，
   它就只是一个"看起来合理的剧情生成器"，而不是科学仪器。
4. **地基是门槛，不是加分项。** 可复现性 / 确定性失败时，上层科学全部不可信，
   scorecard 直接标红，不论其他分数多高。

---

## 1. 有效性层级（成功的五个命题）

借用 ABM / 生成式智能体文献里的 validity hierarchy（Epstein 的 ABM 验证、
Park et al. 生成式智能体的 believability 评估、计算社会科学的 stylized-facts 传统）：

| 层级 | 命题 | 对应 Track |
|------|------|-----------|
| 微观·单体 | 单个 agent 的行为像不像一个连贯的人 | D |
| 微观·跨时间 | 同一 agent 跨天是否保持人设、记忆自洽 | D |
| 宏观·群体 | 聚合统计量是否贴近真实分布 | A |
| 动力学·机制 | 是否复现**已知社会规律**（涌现），而非静态快照对齐 | B |
| 因果·反事实 | 对照实验引擎本身可信吗 | C |
| 地基·工程 | 可复现、成本、解析失败率 | E |

---

## 2. 五条 Track

每条 track 产出：一个连续分 `score ∈ [0,1]`，以及一个 `pass/fail` 门槛。

### Track A — 宏观经验拟合

**命题**：仿真群体的聚合统计量落在真实世界分布附近。

**真实锚点**（城镇口径，因为 GAWorld 用杭州 profile）：

| 指标 | 真实锚点 | 来源 | 仿真数据源 | 误差度量 | 容差 |
|------|---------|------|-----------|---------|------|
| 恩格尔系数 | **28.8%**（城镇 2024；全国 29.8%，农村 32.3%） | 国家统计局 2024 国民经济和社会发展统计公报 | `economy/wealth_snapshot.csv:engel_coefficient` 均值 | 相对误差 | 0.15 |
| 居民储蓄率 | **~35%**（口径敏感，区间 30–43%） | 见 §6 局限 | `economy/wealth_snapshot.csv:savings_rate` 均值 | 相对误差 | 0.30 |
| 平均通勤时耗 | **34.5 min**（杭州单程 2024，备用 32.9） | 2024 年度中国主要城市通勤监测报告（中规院×百度地图） | 通勤记忆 `avg_travel_time` | 相对误差 | 0.25 |
| 公交机动化分担率 | **47.6%**（杭州；绿色出行 >70%） | 杭州市交通运输局 2024 | `state` 出行方式计数 | 相对误差 | 0.25 |
| 情绪分布 | mean 0.60 / std 0.15（**占位，无硬锚点**） | 主观先验，待替换 | `state:emotion` | Wasserstein | — |

**评分**：每个指标 `s_i = max(0, 1 − rel_err_i / tol_i)`；`score_A = mean(s_i)`。
**Pass 门槛**：`score_A ≥ 0.6` 且无单项 `s_i = 0`。

> ⚠️ **弱证据警告**：恩格尔曲线、税率、消费弹性是模型的**输入参数**。
> A 通过只说明实现无 bug，不证明模型有解释力。强证据看 B / C。

### Track B — Stylized-facts 复现（机制有效性）

**命题**：在没有被直接参数化的维度上，仿真自发涌现出**已知的定性+定量规律**。

| Stylized fact | 检验量 | 通过判据 |
|---------------|--------|---------|
| 情绪传染呈 S 曲线 | 注入情绪种子后，受影响 agent 占比时间序列 | 单调饱和、Logistic 拟合 R² ≥ 0.8 |
| 网络向社区结构演化 | 每日网络 modularity、homophily | 二者随天数显著上升（斜率>0，p<0.05） |
| 财富长尾 | 财富分布 Gini / 尾部拟合 | Gini ∈ [0.3, 0.6]，尾部近似对数正态/Pareto |
| 信息扩散呈 S 曲线 | 知晓某信息的 agent 占比 | Logistic 拟合 R² ≥ 0.8 |

**评分**：`score_B = 复现的 fact 数 / 总 fact 数`（在各自容差内）。
**Pass 门槛**：`score_B ≥ 0.5`。
**状态**：harness 中预留接口，v0.1 未实现（依赖更长仿真与更大 N，见 §6）。

### Track C — 因果 / 反事实有效性 ⭐ 核心

**命题**：`compare-event` 产出的处理效应（treatment effect）方向正确、显著、且无伪效应。

直接复用现有 `compare-event` 的产物 `output/comparisons/<...>/comparison_metrics.csv`
（列：`metric, baseline_mean, event_mean, delta_mean, ...`）。

**C1 符号正确性（known-sign 测试）**：

| 干预 | 目标指标 | 预期符号 | 理论依据 |
|------|---------|---------|---------|
| 临时交通限行 | `mobility_intent` / `platform_dependence` | ↑ | 出行摩擦上升 |
| 个税减税 | 消费支出 / `savings_rate` | 消费↑、储蓄↓ | 可支配收入↑ |
| 多样性推荐干预 | `stance_score` 方差 / `cross_viewpoint_exposure` | 方差↓、曝光↑ | 打破回音壁 |
| 裁员冲击 | `econ_security` / `stress` | econ_security↓、stress↑ | 收入骤降 |

`sign_score = 符号正确的干预数 / 总数`。

> **v0.1.1 关键修正（A1）**：符号检验按**事件后效应 `delta_final`** 打分，**不再用 `delta_mean`**。
> `delta_mean` 对整段仿真（含事件前）求平均，会把信号稀释 5–7 倍（实测 traffic 的 `mobility_intent`：
> `delta_mean +0.0068` vs `delta_final +0.3368`，49×）。`delta_mean` 仅作参考列保留。

**C2 安慰剂 / 空事件测试**（少有人做，但能戳穿"任何扰动都被讲成故事"）：
注入一个无意义事件（如"市图书馆闭馆时间微调 10 分钟"），期望所有指标 `|delta_final| < ε`（默认 ε=0.05）。
`placebo_score = 通过的指标占比`。

**C3 控制有效性 / 确定性**：同 seed 跑两次 baseline，对照轨迹应逐 step 完全一致（浮点容差 1e-9）。
`determinism_score = 一致的 (agent,step,metric) 占比`。三态：`ok`（=1.0）/ `fail`（<1.0）/ `unassessed`（未提供 baseline 对）。

**评分**：`score_C = (0.5·sign + 0.25·placebo + 0.25·det) × coverage`，
其中 `coverage = n_eval / 已配置项数`（A3 覆盖度折扣，防止只跑 1 项却看似满分）。
**Pass 门槛**：`sign_score ≥ 0.75` **且** `placebo_score ≥ 0.8` **且** `coverage ≥ 0.75`。
**Gate**（A4，三态）：`det=fail → UNTRUSTWORTHY`；`det=unassessed → UNVERIFIED`（不再白送 OK）；`det=ok → OK`。
**A5**：匹配到关键词但缺 `comparison_metrics.csv` 的运行标记为"未完成"并在报告提示重跑。

### Track D — 可信度与人设一致性

**命题**：单体行为连贯、跨天保持人设、由记忆驱动。

复用 interview CLI（`interview --agent-id N --question ...`）+ 一个 LLM-judge 评分卡：

| 维度 | 探针 | 评分 |
|------|------|------|
| 连贯性 | 标准化访谈问题 | judge 1–5 |
| 人设贴合 | 回答 vs `profiles_with_names.md` | judge 1–5 |
| 记忆可溯源 | "你昨天做了什么/为什么" vs episodes | 可溯源比例 |
| 跨天矛盾率 | 多天回答的逻辑冲突计数 | 1 − 矛盾率 |

**评分**：四维归一化均值。**Pass**：`score_D ≥ 0.7`。
**状态**：v0.1 未实现（需 LLM-judge，留接口）。

### Track E — 可复现性与成本（地基门槛）

| 指标 | 度量 | Gate |
|------|------|------|
| 跨 seed 稳健性 | headline 指标的变异系数 CV | 报告值，CV>0.5 警告 |
| 单 agent-day 成本 | 墙钟时间 + token 数 | 报告值 |
| LLM 解析失败率 | 失败调用 / 总调用 | >5% 警告 |
| 确定性 | 见 C3 | 失败=整体 gate |

**状态**：确定性已在 Track C 实现；成本/失败率从 `run.log` 解析（v0.1 留接口）。

---

## 3. Scorecard 聚合

```
GAWorld-Bench Scorecard
  Track A  宏观经验拟合      0.xx   [PASS/FAIL]
  Track B  Stylized-facts    n/a    (未实现)
  Track C  因果反事实         0.xx   [PASS/FAIL]   ⭐
  Track D  可信度一致性       n/a    (未实现)
  Track E  可复现/成本        gate   [OK/UNVERIFIED/UNTRUSTWORTHY]
  ----------------------------------------------------
  Headline: <weakest passing track>  ·  Trust gate: OK/UNVERIFIED/UNTRUSTWORTHY
```

聚合规则：

- **不计算单一总分。** 默认展示分项 + 雷达图。
- 可选 `composite = mean(已实现 track 的 score)`，仅用于追踪趋势，并始终附"弱证据"注记。
- **Trust gate（三态）**：确定性 `fail` → `UNTRUSTWORTHY`；从未测试 → `UNVERIFIED`（不白送 OK）；
  `ok` → `OK`。门槛失败时上层分数仅供参考。
- **Headline = 最弱的已通过 track**（木桶原理）：报告短板而非平均。

---

## 4. 与现有代码的映射 + 已发现的缺口

| Track | 复用的现有资产 | 缺口 |
|-------|---------------|------|
| A | `exp_abm_validation.py`、`ExperimentRunner.load_economy_data` | 锚点是占位值；提取器 schema 不匹配（见下） |
| B | `exp_emotion_contagion`、`exp_network_evolution`、`exp_misinfo_spread` | 缺统一的 stylized-fact 判据与聚合 |
| C | `compare-event` CLI、`comparison_metrics.csv` | **缺安慰剂测试、确定性测试、符号判据** |
| D | `interview` CLI、`exp_memory_consistency` | 缺 LLM-judge 评分卡 |
| E | `run.log`、`random_seed` 配置 | 缺成本/失败率解析与跨 seed 跑批 |

**实现期发现的两个 schema 不一致（建议单独修）**：

1. `exp_abm_validation.extract_engels_data()` 读 `food_expense` / `total_consumption` 两列，
   但真实 `daily_ledger.csv` 没有这两列，而是直接给了 `engel_coefficient` 列 →
   现有验证器在真实输出上会静默返回空。**GAWorld-Bench 改读 `engel_coefficient` / `savings_rate` 列。**
2. `exp_abm_validation` 与 `run_experiment.compute_basic_statistics()` 假设
   `agent_state_history.csv` 是宽表（`df["emotion"]`、`df["activity"]`），
   但实际是长表 `agent_id,step,metric,value`。**GAWorld-Bench 按长表解析。**

（按项目规范，这两处属于"我的改动暴露出的既有问题"，文档记录、不擅自改动原文件。）

---

## 5. 用法

```bash
cd benchmark

# 合成模式：不调用 LLM/仿真，用结构正确的假数据跑通评分管线（用于验证 / 试用）
python gaworld_bench.py --synthetic

# 默认行为：无参数即用真实 output/ 数据打分
#   Track A 读 output/economy/wealth_snapshot.csv
#   Track C 关键词匹配 output/comparisons/ 下已有的 compare-event 运行
python gaworld_bench.py --all

# Track A：读指定经济输出
python gaworld_bench.py --track A --output-dir ../output

# Track C（实跑）：调 compare-event，需要配置好 LLM provider
python gaworld_bench.py --track C --run --days 3 --seed 42 [--llm-provider minimax]

# 快速档（本地模型友好）：确定性认知 + 跳过每日总结/日记 + 3 agent，LLM 调用大减、保真度降低
python gaworld_bench.py --track C --run --days 30 --fast --llm-provider ollama_gemma4

# Track C（A2 多 seed 显著性）：每个干预跨多 seed，输出 95%CI，只对显著项计分
python gaworld_bench.py --track C --run --seeds 1,2,3,4,5 --days 30 [--llm-provider minimax]

# 断点续跑：多 seed 实跑每完成一个 (干预,seed) 就存 checkpoint；若中途失败（如 API 用量超限），
# 配额恢复后用相同 --seeds/--days 加 --continue 续跑，已完成的单元自动跳过。
python gaworld_bench.py --track C --run --seeds 1,2,3,4,5 --days 30 --continue [--llm-provider minimax]

# Track C（离线）：评分已经跑出来的 comparison 目录，不再调仿真
python gaworld_bench.py --track C --comparisons-root ../output/comparisons \
    --placebo-dir <dir> --det-a <state_a.csv> --det-b <state_b.csv>

# 全部已实现 track
python gaworld_bench.py --all --run --days 3 --seed 42

# 产物（每次运行自动生成）
#   benchmark/results/scorecard.json
#   benchmark/results/scorecard.md
#   benchmark/results/report.md            ← 诊断 + 改进建议（最新）
#   benchmark/results/reports/report_<时间戳>.md   ← 历史归档
```

每次运行都会自动生成一份**报告** `report.md`：先复述 scorecard，再按 track 给出诊断
（具体到哪个指标/哪个干预、误差多大、Δ 多大），最后输出一个**按优先级排序的"下一步"建议清单**。
建议是**数据驱动**的（直接读当次分数与子指标），纯标准库、确定性、无 LLM 依赖。例如：
失败的符号检验若 |Δ| 与安慰剂同量级，会建议"延长仿真到 ≥30 天 + 加显著性检验"而非"方向接反了"。

> **说明（v0.1）**：`--days` / `--seed` / `--llm-provider` 只在 `--run`（实跑）下生效。
> Track C 的确定性子项需要显式提供两份同 seed baseline 状态文件（`--det-a/--det-b`），
> 否则该子项记为"未评估"而非伪造通过。
>
> **覆盖度透明**：scorecard 末尾会打印 Track C 的实际覆盖度（如"符号 1/1（共 4 项已配置）·
> 安慰剂 未评估 · 确定性 未评估"）。只跑了 1 个干预得到的 1.0 **不等于**完整验证——
> 看覆盖度，不要只看分数。要拿到全覆盖，需为 layoff/tax 等干预补 compare-event 运行（`--run`）。

---

## 6. 局限与取舍（务必读）

- **Track A 近乎循环。** 你验证的分布正是你写进模型的参数。A 是卫生检查，不是科学证据。
- **储蓄率锚点口径敏感。** "居民储蓄率"有多种定义：居民部门可支配收入中的储蓄流量约 30–35%，
  而媒体常引的"住户存款/收入"口径可达 ~43%。本文用 ~35% + 宽容差（0.30），并标注此不确定性。
- **N=50 的尺度问题。** Track B 的某些规律（长尾、社区结构）在 50 个 agent 上统计不稳。
  benchmark 必须标注尺度适用范围，否则会把"样本太小"误判成"模型不对"。
- **Ground-truth 缺失。** 许多社会现象没有干净的真实数字，故 C 依赖**方向/相对**判据
  （符号、安慰剂）而非绝对拟合——这是有意的设计，不是妥协。
- **LLM 随机性。** C / D 对 prompt 敏感、采样有噪声，必须跨 seed 多次 + 报告置信区间，
  单跑不下结论。
- **优先级。** 若只做一条，做 **Track C**。A 易做但弱，C 难做但直接决定 GAWorld 是不是仪器。

---

## 7. 路线图

- **v0.1**：Track A（真实锚点 + schema 修正）、Track C（符号 + 安慰剂 + 确定性）、scorecard 聚合、合成模式。
- **v0.1.1（已落地）**：A1 事件后效应 `delta_final`、A3 覆盖度折扣、A4 确定性三态 gate（UNVERIFIED）、A5 未完成运行检测、每次运行自动报告。
- **v0.1.2（已落地）**：A2 跨 seed 显著性——`--seeds` 多 seed 模式，每个干预算 95%CI，**只对显著（CI 不含 0）的符号检验计分**，不显著记 `ns`；新增 `significance_coverage`。单 seed（每项 <2 样本）显示"样本不足"提示而非误导性的 0/0。快速点估计请用**单跑模式**（`--run` 不加 `--seeds`，按 `delta_final` 出 符号 X/4）。
- **v0.1.3（已落地）**：`--continue` 断点续跑——多 seed 实跑每完成一个 (干预,seed) 单元就存 checkpoint（`benchmark/results/checkpoint_multiseed.json`）；中途失败（API 用量等）保存进度并提示，配额恢复后续跑跳过已完成单元。
- **v0.1.4（已落地）**：`--fast` 快速档——透传给 `compare-event`，启用项目内置 `fos_fast_mode`（确定性认知 + 跳过每日总结/日记）并缩减到 3 agent，大幅减少 LLM 调用；为本地小模型跑更长 horizon 换速度、降保真度。
- **v0.1.5（已落地）**：`--fast` 自动标注——`compare-event` 在每个对照目录写 `run_meta.json`（含 `fast` 标记）；harness 读取后，scorecard/report 顶部显示"⚡ 低保真运行（--fast）"横幅，避免把快速档结果误当全保真结论。
- **v0.2**：Track E 成本/失败率解析、CV。
- **v0.3**：Track B stylized-facts 判据（接 emotion_contagion / network_evolution）。
- **v0.4**：Track D LLM-judge 评分卡（接 interview / memory_consistency）。

---

## 参考来源

- 国家统计局《2024 年国民经济和社会发展统计公报》（恩格尔系数 29.8%，城镇 28.8%）
- 中国城市规划设计研究院 × 百度地图《2024 年度中国主要城市通勤监测报告》（杭州 34.5 min）
- 杭州市交通运输局 2024（公交机动化分担率 47.6%，绿色出行 >70%）
- 居民储蓄率 2024 媒体与 CEIC/世界银行口径（区间 30–43%，见 §6）
- Epstein, J. M. (2006). *Generative Social Science*；Park et al. (2023). *Generative Agents*
