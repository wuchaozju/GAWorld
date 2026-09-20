# 事件影响对比报告

- 事件名称：临时交通限行
- 事件时间：Day 3 09:00
- 事件描述：主干道限行导致通勤时间上升并影响出行决策

## PolicySim 干预指标

- `cross_viewpoint_exposure`: baseline=0.0000, event=0.0000, Δ=0.0000，几乎无变化
- `intervention_reward`: baseline=0.3200, event=0.3200, Δ=0.0000，几乎无变化
- `misinformation_risk`: baseline=0.0000, event=0.0000, Δ=0.0000，几乎无变化
- `stance_score`: baseline=0.0000, event=0.0000, Δ=0.0000，几乎无变化
- `toxicity_score`: baseline=0.0000, event=0.0000, Δ=0.0000，几乎无变化

## 关键差异（按终值绝对差排序）

- `social_need`: baseline=0.6110, event=0.6209, Δ=0.0099，social_need上升（Δ=0.0099）
- `time_pressure`: baseline=0.1861, event=0.1761, Δ=-0.0099，time_pressure下降（Δ=0.0099）
- `mobility_intent`: baseline=0.1437, event=0.1401, Δ=-0.0036，流动意愿下降（Δ=0.0036）
- `stress`: baseline=0.0970, event=0.0946, Δ=-0.0024，压力下降（Δ=0.0024）
- `city_identity`: baseline=0.7813, event=0.7835, Δ=0.0021，城市认同上升（Δ=0.0021）

## 估计结论

事件对系统的主要影响表现为：social_need上升（Δ=0.0099）；time_pressure下降（Δ=0.0099）；流动意愿下降（Δ=0.0036）。

- 指标明细：`docs/proposals/results/exp_policy_framework/traffic_restriction/20260531_001140_临时交通限行/comparison_metrics.csv`
