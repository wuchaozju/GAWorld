# 事件影响对比报告

- 事件名称：职业技能培训补贴
- 事件时间：Day 3 08:00
- 事件描述：失业人员参加培训可获得每月1500元生活补贴

## PolicySim 干预指标

- `cross_viewpoint_exposure`: baseline=0.0000, event=0.0000, Δ=0.0000，几乎无变化
- `intervention_reward`: baseline=0.3200, event=0.3200, Δ=0.0000，几乎无变化
- `misinformation_risk`: baseline=0.0000, event=0.0000, Δ=0.0000，几乎无变化
- `stance_score`: baseline=0.0000, event=0.0000, Δ=0.0000，几乎无变化
- `toxicity_score`: baseline=0.0000, event=0.0000, Δ=0.0000，几乎无变化

## 关键差异（按终值绝对差排序）

- `social_need`: baseline=0.6110, event=0.6209, Δ=0.0099，social_need上升（Δ=0.0099）
- `time_pressure`: baseline=0.1861, event=0.1761, Δ=-0.0099，time_pressure下降（Δ=0.0099）
- `mobility_intent`: baseline=0.1433, event=0.1401, Δ=-0.0031，流动意愿下降（Δ=0.0031）
- `stress`: baseline=0.0966, event=0.0946, Δ=-0.0020，压力下降（Δ=0.0020）
- `econ_security`: baseline=0.6864, event=0.6881, Δ=0.0017，经济安全感上升（Δ=0.0017）

## 估计结论

事件对系统的主要影响表现为：social_need上升（Δ=0.0099）；time_pressure下降（Δ=0.0099）；流动意愿下降（Δ=0.0031）。

- 指标明细：`docs/proposals/results/exp_policy_framework/job_training/20260531_005414_职业技能培训补贴/comparison_metrics.csv`
