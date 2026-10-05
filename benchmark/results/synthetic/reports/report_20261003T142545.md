# GAWorld-Bench 运行报告

## 结果概览

> ⚠️ **合成夹具（--synthetic）**：数字是为让每条检查都通过而预设的，只证明评测代码能跑通，**不是 GAWorld 仿真结果**，不得引用。

- generated: 2026-10-03T14:25:45
- **trust gate: FIXTURE**（合成夹具：只验证评测代码路径）
- composite hint: 0.9361  _(trend only, 弱证据)_
- headline (weakest passing track): A
- 数据来源: `synthetic` · git `6c5740bf`（有未提交改动）

| Track | 命题 | score | pass |
|---|---|---|---|
| A | 宏观经验拟合 | 0.8721 | PASS |
| B | Stylized-facts | n/a | 未实现 (v0.3) |
| C | 因果反事实 ⭐ | 1.0 | PASS |
| D | 可信度一致性 | n/a | 未实现 (v0.4) |
| E | 可复现/成本 | n/a | 确定性见 Track C; 成本未实现 (v0.2) |

- Track C: 符号 4/4 正确（覆盖 1.0，按 `delta_final` 事件后效应） · 安慰剂 1.0 · 确定性 ok

**指标来源**（最弱一级依赖，定义见 MECHANISM_PROVENANCE.md；(c) 不得单独立论）
- `engel_coefficient` (c)：spending.engel_curve 按月净收入分五档查表（系数未注明出处） ⚠️ **回显**：快照里的值就是按收入查 engel_curve 得到的预算参数，不是从实际分类消费算出来的——拟合量的是这张表
- `savings_rate` (c)：spending.engel_curve 按月净收入分五档查表（系数未注明出处） ⚠️ **回显**：快照里的值就是按收入查 engel_curve 得到的计划储蓄率，不是从实际收支算出来的——拟合量的是这张表
- Track C 各项（econ_security、mobility_intent、stress） (c)：事件对九维状态的影响由一次模型调用直接给出（infer_event_effect），再经手写均值回归（update_state）——已知符号检验检的是模型对这件事的判断能否穿过状态动态传到指标上，不是对现实因果的独立检验

## 分项诊断与建议

### Track C — 因果反事实 ⭐ — 1.0 PASS
符号 4/4 正确（覆盖 1.0，按 `delta_final` 事件后效应）。
指标来源 (c)：事件对九维状态的影响由一次模型调用直接给出（infer_event_effect），再经手写均值回归（update_state）——已知符号检验检的是模型对这件事的判断能否穿过状态动态传到指标上，不是对现实因果的独立检验。
- `traffic_restriction/mobility_intent`: Δ=+0.0800 期望↑ ✓（delta_mean +0.0800）
- `layoff_shock/econ_security`: Δ=-0.1200 期望↓ ✓（delta_mean -0.1200）
- `layoff_shock/stress`: Δ=+0.0900 期望↑ ✓（delta_mean +0.0900）
- `tax_cut/econ_security`: Δ=+0.0600 期望↑ ✓（delta_mean +0.0600）

### Track A — 宏观经验拟合 — 0.8721 PASS
样本：5 个 agent 快照。
- `savings_rate`: sim 0.328 vs 锚点 0.35 (误差 6.3%) ✗  _2024 口径敏感, 区间30-43%_ · 来源 (c) · ⚠️ 回显
- `engel_coefficient`: sim 0.29 vs 锚点 0.288 (误差 0.7%) ✓  _国家统计局2024公报 (城镇28.8%)_ · 来源 (c) · ⚠️ 回显

建议：
1. 主要拖累项 `savings_rate`（误差 6.3%）：明确口径：『住户存款/收入』口径偏高(~43%)，『可支配收入流量储蓄』口径约30-35%，再校准锚点/容差。
2. 样本仅 5 个，统计不稳；增大 agent 数或延长仿真天数后再评估宏观拟合。
3. `engel_coefficient`、`savings_rate` 是输入回显：快照里记的是按收入查 engel_curve 的预算参数。改从实际分类消费（食品支出 / 总消费、1 − 支出 / 收入）计算之前，这几项拟合得再好也不是模型证据。
4. 提醒：Track A 属弱证据（验证的是写进模型的参数）。Track C 的指标同为 (c) 级——事件影响由模型判断给出，见「指标来源」。

### 未实现：Track B, D, E
这些有效性维度尚未评估，当前结论存在盲区（见设计文档路线图 §7）。

## 下一步（按优先级）

1. 【信任门槛】这是合成夹具，只验证评测代码路径 → 要评测模型请去掉 --synthetic 重跑。
2. 【Track A】主要拖累项 `savings_rate`（误差 6.3%）：明确口径：『住户存款/收入』口径偏高(~43%)，『可支配收入流量储蓄』口径约30-35%，再校准锚点/容差。
3. 【Track A】样本仅 5 个，统计不稳；增大 agent 数或延长仿真天数后再评估宏观拟合。
4. 【Track A】`engel_coefficient`、`savings_rate` 是输入回显：快照里记的是按收入查 engel_curve 的预算参数。改从实际分类消费（食品支出 / 总消费、1 − 支出 / 收入）计算之前，这几项拟合得再好也不是模型证据。
5. 【Track A】提醒：Track A 属弱证据（验证的是写进模型的参数）。Track C 的指标同为 (c) 级——事件影响由模型判断给出，见「指标来源」。
