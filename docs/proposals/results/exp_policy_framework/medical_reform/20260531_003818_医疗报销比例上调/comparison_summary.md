# 事件影响对比报告

- 事件名称：医疗报销比例上调
- 事件时间：Day 3 08:00
- 事件描述：门诊报销比例从50%提升至70%，减轻医疗负担

## PolicySim 干预指标

- `cross_viewpoint_exposure`: baseline=0.0000, event=0.0000, Δ=0.0000，几乎无变化
- `intervention_reward`: baseline=0.3200, event=0.3200, Δ=0.0000，几乎无变化
- `misinformation_risk`: baseline=0.0000, event=0.0000, Δ=0.0000，几乎无变化
- `stance_score`: baseline=0.0000, event=0.0000, Δ=0.0000，几乎无变化
- `toxicity_score`: baseline=0.0000, event=0.0000, Δ=0.0000，几乎无变化

## 关键差异（按终值绝对差排序）

- `stress`: baseline=0.0946, event=0.0953, Δ=0.0008，压力上升（Δ=0.0008）
- `emotion`: baseline=0.8933, event=0.8926, Δ=-0.0007，情绪下降（Δ=0.0007）
- `risk_preference`: baseline=0.5929, event=0.5924, Δ=-0.0005，risk_preference下降（Δ=0.0005）
- `mobility_intent`: baseline=0.1401, event=0.1406, Δ=0.0005，流动意愿上升（Δ=0.0005）
- `city_identity`: baseline=0.7835, event=0.7830, Δ=-0.0005，城市认同下降（Δ=0.0005）

## 估计结论

事件对系统的主要影响表现为：压力上升（Δ=0.0008）；情绪下降（Δ=0.0007）；risk_preference下降（Δ=0.0005）。

- 指标明细：`docs/proposals/results/exp_policy_framework/medical_reform/20260531_003818_医疗报销比例上调/comparison_metrics.csv`
