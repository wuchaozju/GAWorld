# 事件影响对比报告

- 事件名称：暴雨天气
- 事件时间：Day 3 07:00
- 事件描述：暴雨天气事件，出行受到影响

## PolicySim 干预指标

- `cross_viewpoint_exposure`: baseline=0.0000, event=0.0000, Δ=0.0000，几乎无变化
- `intervention_reward`: baseline=0.3200, event=0.3200, Δ=0.0000，几乎无变化
- `misinformation_risk`: baseline=0.0000, event=0.0000, Δ=0.0000，几乎无变化
- `stance_score`: baseline=0.0000, event=0.0000, Δ=0.0000，几乎无变化
- `toxicity_score`: baseline=0.0000, event=0.0000, Δ=0.0000，几乎无变化

## 关键差异（按终值绝对差排序）

- `time_pressure`: baseline=0.2004, event=0.1861, Δ=-0.0143，time_pressure下降（Δ=0.0143）
- `social_need`: baseline=0.5967, event=0.6110, Δ=0.0143，social_need上升（Δ=0.0143）
- `emotion`: baseline=0.9054, event=0.8923, Δ=-0.0131，情绪下降（Δ=0.0131）
- `city_identity`: baseline=0.7851, event=0.7813, Δ=-0.0039，城市认同下降（Δ=0.0039）
- `risk_preference`: baseline=0.5952, event=0.5922, Δ=-0.0029，risk_preference下降（Δ=0.0029）

## 估计结论

事件对系统的主要影响表现为：time_pressure下降（Δ=0.0143）；social_need上升（Δ=0.0143）；情绪下降（Δ=0.0131）。

- 指标明细：`docs/proposals/results/exp_transport_behavior/treatment_weather_rain/20260531_012722_暴雨天气/comparison_metrics.csv`
