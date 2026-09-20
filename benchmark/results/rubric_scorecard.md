# GAWorld-Rubric-Bench Scorecard

- rubric 版本：`0.1.0`（hash `56523e783e28`）
- 抽样 seed：`42`｜judges：`（无，仅规则项）`｜消融：`['N1', 'N3', 'N4', 'N6', 'N7']`
- run 模式：`full`｜缺失能力：`social_graph`
- Trust gate：**UNVERIFIED**（没有任何维度达到可评状态（数据不足或全部弃权））

## 维度分

| 维度 | 分数 | 门槛 | 覆盖度 | 弃权率 | 计分/适用/总 item | 状态 |
|------|------|------|--------|--------|-------------------|------|
| R1 个体拟人性 | n/a | None | 0.0 | - | 0/7/7 | unassessed |
| R2 演化能力 | n/a | None | 0.0 | - | 0/7/7 | unassessed |
| R3 社会真实性 | n/a | None | 1.0 | - | 0/1/6 | unassessed |
| R4 世界一致性 | 0.441 | 0.8 | 0.475 | 0.737 | 3/6/6 | unassessed |

## Item 明细

| item | checker | 已评/总数 | 弃权率 | 均分 | 判别力 | 状态 |
|------|---------|-----------|--------|------|--------|------|
| R1.1 | hybrid | 0/19 | 1.00 | n/a | 未测 | unverified_no_ablation |
| R1.2 | llm | 0/19 | 1.00 | n/a | 未测 | unverified_no_ablation |
| R1.3 | llm | 0/19 | 1.00 | n/a | 未测 | unverified_no_ablation |
| R1.4 | hybrid | 0/19 | 1.00 | n/a | 未测 | unverified_no_ablation |
| R1.5 | llm | 0/0 | 1.00 | n/a | 未测 | unverified_no_ablation |
| R1.6 | llm | 0/19 | 1.00 | n/a | 未测 | unverified_no_ablation |
| R1.7 | llm | 0/19 | 1.00 | n/a | 未测 | unverified_no_ablation |
| R2.1 | rule | 0/0 | 1.00 | n/a | 未测 | unverified_no_ablation |
| R2.2 | hybrid | 0/0 | 1.00 | n/a | 未测 | unverified_no_ablation |
| R2.3 | llm | 0/0 | 1.00 | n/a | 未测 | unverified_no_ablation |
| R2.4 | hybrid | 0/0 | 1.00 | n/a | 未测 | unverified_no_ablation |
| R2.5 | rule | 0/1 | 1.00 | n/a | 未测 | unverified_no_ablation |
| R2.6 | hybrid | 0/0 | 1.00 | n/a | 未测 | unverified_no_ablation |
| R2.7 | hybrid | 0/0 | 1.00 | n/a | 未测 | unverified_no_ablation |
| R3.1 | rule | — | — | — | — | 本次运行无此数据（缺 social_graph） |
| R3.2 | hybrid | — | — | — | — | 本次运行无此数据（缺 social_graph） |
| R3.3 | llm | — | — | — | — | 本次运行无此数据（缺 social_graph） |
| R3.4 | llm | — | — | — | — | 本次运行无此数据（缺 social_graph） |
| R3.5 | llm | 0/5 | 1.00 | n/a | 未测 | unverified_no_ablation |
| R3.6 | hybrid | — | — | — | — | 本次运行无此数据（缺 social_graph） |
| R4.1 | rule | 14/19 | 0.26 | 1.57 | 0.64 | ok |
| R4.2 | rule | 14/19 | 0.26 | 2.00 | 0.86 | ok |
| R4.3 | rule | 2/19 | 0.90 | 2.00 | 1.00 | ok |
| R4.4 | llm | 0/5 | 1.00 | n/a | 未测 | unverified_no_ablation |
| R4.5 | llm | 0/5 | 1.00 | n/a | 未测 | unverified_no_ablation |
| R4.6 | hybrid | 0/19 | 1.00 | n/a | 未测 | unverified_no_ablation |

## 读数须知

- 分数按 rubric 版本断代，跨版本不可比。
- `unverified` = 未做判别力检验，分数仅供参考，不得进对外材料。
- 弃权率高通常意味着数据字段缺失，而不是模型差——见 item 明细。
- 「计分/适用/总 item」：适用 < 总 = 本次运行缺对应数据；计分 < 适用 = 有条目被弃权或因判别力不足剔除。计分数很小的维度分要当窄口径读。
