# 事件影响对比报告

- 事件名称：住房补贴政策
- 事件时间：Day 3 08:00
- 事件描述：首次购房者可申请每月2000元补贴，持续6个月

## PolicySim 干预指标

- `cross_viewpoint_exposure`: baseline=0.0000, event=0.0000, Δ=0.0000，几乎无变化
- `intervention_reward`: baseline=0.3200, event=0.3200, Δ=0.0000，几乎无变化
- `misinformation_risk`: baseline=0.0000, event=0.0000, Δ=0.0000，几乎无变化
- `stance_score`: baseline=0.0000, event=0.0000, Δ=0.0000，几乎无变化
- `toxicity_score`: baseline=0.0000, event=0.0000, Δ=0.0000，几乎无变化

## 关键差异（按终值绝对差排序）

- `time_pressure`: baseline=0.2172, event=0.1861, Δ=-0.0311，time_pressure下降（Δ=0.0311）
- `social_need`: baseline=0.5799, event=0.6110, Δ=0.0311，social_need上升（Δ=0.0311）
- `stress`: baseline=0.1051, event=0.0966, Δ=-0.0086，压力下降（Δ=0.0086）
- `emotion`: baseline=0.8986, event=0.8930, Δ=-0.0055，情绪下降（Δ=0.0055）
- `mobility_intent`: baseline=0.1465, event=0.1433, Δ=-0.0032，流动意愿下降（Δ=0.0032）

## 估计结论

事件对系统的主要影响表现为：time_pressure下降（Δ=0.0311）；social_need上升（Δ=0.0311）；压力下降（Δ=0.0086）。

- 指标明细：`docs/proposals/results/exp_policy_framework/housing_subsidy/20260531_002817_住房补贴政策/comparison_metrics.csv`
