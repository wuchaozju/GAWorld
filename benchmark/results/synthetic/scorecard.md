# GAWorld-Bench Scorecard

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
