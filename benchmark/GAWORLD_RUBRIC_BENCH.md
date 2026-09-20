# GAWorld-Rubric-Bench 设计文档

**版本**：v0.1.1 · **日期**：2026-08-13 · **状态**：P1–P3 已实现（`benchmark/rubric/` + `benchmark/rubric_bench.py`），P4/P5 未开始

---

## 0. 一句话

拟人性、演化能力这类属性**认得出但写不出公式**。本文档定义一套 **rubric-as-reward** 式的评测：
把"像不像人"拆成一批**互相独立、逐条可验证、必须给出证据引用**的判定项，由 LLM 作为主观评价者
逐条打分，再用**消融判别力**和**人类锚点一致性**反过来检验这些打分本身是否可信。

与现有 `GAWORLD_BENCH_DESIGN.md` 的关系：

- 本套件 = 现有 **Track D（可信度一致性）的完整化** + 新增 **演化 / 社会 / 世界一致性** 三个主观维度。
- 记作 **Track R（R1–R4）**，与 A/B/C/E 并列进同一张 scorecard，不合并成一个总分。
- 沿用现有两条规矩：**三态 gate**（OK / UNVERIFIED / UNTRUSTWORTHY）、**覆盖度折扣**。

---

## 1. 为什么是 rubric，而不是"让 LLM 打个 1–5 分"

直接问 "这个 agent 像不像真人，1–5 分" 会得到：分数集中在 3.8–4.2、对流畅文本系统性偏高、
换个模型排序就变。原因是这个问题没有可验证的判据，模型只能输出"语感"。

Rubric-as-reward 的三条要义：

1. **拆成 checklist。** 一个抽象属性 → 一组具体命题，每条只问一件能在样本里找到或找不到的事。
2. **证据绑定。** 每条打分必须附一段样本原文引用（`evidence`）。找不到引用 → 只能 `abstain`，
   不能靠印象给分。abstain 不计入分母，但 abstain 率本身作为指标上报。
3. **判据外置。** 每条 rubric 自带 0/1/2 的**行为锚定描述**（BARS）与"常见失败模式"，
   judge 是在做匹配，不是在做审美。

与 RLHF 偏好打分的区别：这里不问"A 和 B 哪个更好"，问"第 k 条标准是否被满足"。
偏好分只能排序同一批样本，rubric 分可以跨 run、跨版本比较——这是我们要的。

**核心防线：不是"让 LLM 打分更准"，而是"证明这套打分能区分真假"。**
见 §5.4 消融判别力——任何一条无法把被人为破坏的样本判低的 rubric，一律作废。

---

## 2. 评测单元与取样协议

### 2.1 五种评测单元

| 单元 | 内容 | 主要服务的维度 | 数据来源 |
|------|------|---------------|---------|
| **U1 Agent-Day** | 单 agent 单日全部 episodes + 当日 diary | R1 拟人性、R4 世界一致性 | `output/memory/agent_{i}_episodes.jsonl`、`output/diaries/agent_{i}/day_*.md` |
| **U2 Agent-Trajectory** | 单 agent 连续 N≥30 天的压缩轨迹（每日摘要 + growth 快照 + 关系快照） | R2 演化 | episodes + `agent_{i}_growth.json` + `agent_state_history.csv` |
| **U3 Dyad-Thread** | 一对 agent 全部共同出现的互动片段（双方各自视角并列） | R3 社会 | episodes 的 `social_partners` 双向连接 |
| **U4 World-Slice** | 某一天全城 agent 的横截面（同一公共事件下各人的感知与行为） | R4 世界一致性、R3 传播 | 全体 episodes 的 `env_events` / `policy_event` / `life_events` |
| **U5 Interview** | 标准化探针问答 | R1 记忆可溯源、人设贴合 | `interview --agent-id N --question ...` |

### 2.2 取样协议（防挑样偏差）

- **分层随机**：按 `persona 类型 × 生命阶段 × 活跃度三分位` 分层，层内固定 seed 随机抽。
  抽样 seed 与仿真 seed 分离并记录在结果里。
- **最小样本量**（v0.1 建议）：U1 = 40 个 agent-day（≥12 个不同 agent）；U2 = 12 条轨迹；
  U3 = 15 对；U4 = 5 天；U5 = 10 agent × 6 问题。
- **覆盖度折扣**：实际可评样本 / 目标样本量 = `coverage`，直接乘进维度分（同 Track A3）。
- **数据现状警告**：当前 `output/` 里 `diaries/` 只有 `agent_41` 的 2 天、episodes 只覆盖少数
  agent，coverage 会把分数压到无意义。演化维度（R2）在 <30 天的 run 上直接标 `unassessed`，
  不给分（与 B2 的慢 EMA 结论一致）。数据底座怎么造见 §2.4。

### 2.4 数据能力与两档 run（P0 方案）

不同 run 模式留下的产物不同，能回答的 rubric 条目也不同。每个 item 在 `rubrics.json` 里声明
`requires`，缺任一项则该 item **全部弃权**而非记 0 分——缺产物不是模型的失败。

| 能力 | 含义 | 全保真 | 快进 `--fast-forward` |
|------|------|--------|----------------------|
| `episodes` | 日内 episodes（时间戳/travel/需求/回忆/计划vs实做） | ✅ | ❌ |
| `series` | `agent_state_history.csv` | ✅（每 tick） | ✅（每天一点） |
| `growth` / `ledger` | 成长快照 / 经济流水 | ✅ | ✅（日边界 hook 仍触发） |
| `daily_narrative` | 日级叙事 | ✅ | ✅（日简报嵌在模板日记里） |
| `authored_diary` | 日记由 LLM 撰写 | ✅ | ❌（`_fallback_daily_diary` 模板） |
| `social_graph` | episodes 里可解析的 `social_partners` | ✅ | ❌ |

**为什么快进不能单独支撑 Track R**：`_run_fast_forward_step`（`generative_city_sim.py:3882`）
是独立分支，完全绕过日内 tick loop，而 `append_agent_episode` 在 tick loop 里（:3682）——
快进 run 一条 episode 都不写。R1 全部、R3 全部、R4 全部、R2.2/R2.4 因此不可评。
月/年步长（`long_run.unit`）走的是同一个分支，所以这条结论对粗粒度长跑同样成立，
只是"每天一点"的状态序列会变成"每步一点"。

**为什么 `fos_fast_mode`（`compare-event --fast`）也不行**：它保留 tick loop（episodes 照写），
但 `deterministic_cognition: True` 让 `planning` / `reflection` 走 `_fallback_*_struct`，
`plan_struct` 与 `reflection` 变成模板 → R1.2/1.5/1.6/1.7 实际是在评 fallback 模板的质量。
它适合 Track C 的对照实验，不适合 Track R。

**关键观察：R1/R3/R4 不需要 30 天。** 它们的评测单元是 agent-day / dyad / world-slice，
20 agent × 12 天 = 240 个候选 agent-day，远超 40 的取样目标。只有 R2 需要长 horizon。
所以 P0 拆成两档：

| 档 | 模式 | 建议规模 | 服务的维度 |
|---|---|---|---|
| **A 全保真** | 正常 tick loop | ≥20 agent × 12 天 | R1 全部、R3 全部、R4 全部、R2.2/R2.4 |
| **B 快进** | `run --fast-forward` | ≥20 agent × 60–90 天 | R2.1/R2.3/R2.5/R2.6/R2.7 |

两份 `output/` 分别评分，scorecard 按维度拼合。快进产物的 scorecard 会自动带
「⚡ 快进运行」横幅并列出缺失能力，避免把"因缺数据而弃权"误读成"模型表现差"。

### 2.3 样本渲染（Renderer）

原始 JSONL 不能直接喂给 judge，需要渲染成**去标识、统一长度**的可读文本：

- 去掉 `agent_id` / `episode_id` / "仿真" "agent" 等字样，换成"受访者 A"，避免 judge 一看就知道是 AI 生成从而压分或抬分。
- 每个单元截断到统一 token 预算（U1 ≈ 1500 tok，U2 ≈ 3000 tok），超出走摘要而非截尾。
- 保留判分必需的结构字段：`recollections`、`decision_driver`、`change_reason`、
  `need_snapshot`、`state_before/after`、`travel`、`social_partners`、`growth_matches`。

---

## 3. 四个维度的 rubric

计分：每条 `0 = 不满足 / 1 = 部分满足 / 2 = 满足 / abstain = 证据不足`。
`checker` 列表示由谁判：`rule` = 纯程序校验（不花 token、不会飘）、`llm` = judge、
`hybrid` = 程序先算出事实表，judge 只判语义合理性。**能用规则的绝不交给 LLM。**

### R1 个体拟人性（单元 U1 / U2 / U5）

| ID | 命题 | checker | 0 / 1 / 2 锚点 | 常见失败模式 |
|----|------|---------|---------------|-------------|
| R1.1 | **记忆可溯源**：决策中引用的往事真实存在于此前 episodes，且未被篡改 | hybrid | 0=引用了不存在或与史实矛盾的往事；1=存在但引用牵强、与决策无关；2=存在、准确、且构成决策理由 | 泛化回忆（"最近一直挺忙"）冒充具体记忆 |
| R1.2 | **动机可解释**：`scheduled_activity → final_activity` 的偏离有具体理由，且与 `need_snapshot` / `state_before` 一致 | llm | 0=无理由或理由与状态矛盾；1=理由是套话（"根据实际情况调整"）；2=理由具体且能从需求/状态推出 | `change_reason` 模板化 |
| R1.3 | **人设贴合**：行为、消费档次、语言风格与 `profiles_with_names.md` 的人设不冲突 | llm | 0=明显冲突（低收入者高消费无解释）；1=不冲突但也看不出是谁；2=能反推出人设特征 | 所有 agent 说话一个腔调 |
| R1.4 | **情绪动力学合理**：`state_before→state_after` 的 delta 与事件强度匹配 | hybrid | 0=无因暴涨暴跌，或全天恒定平线；1=方向对但幅度不合理；2=幅度与事件量级匹配且有惯性 | 情绪是随机噪声 / 情绪是常数 |
| R1.5 | **非模板化**：跨天叙事在关注点、句式、细节颗粒度上有变化 | llm | 0=换名词的同一模板；1=结构相同但细节有变化；2=不同天的关注重心自然迁移 | diary 段落结构逐日雷同 |
| R1.6 | **有限理性**（反向）：存在拖延、后悔、次优选择、与自述目标不一致的行为 | llm | 0=全天最优化、无一失误；1=有一处不完美；2=有可解释的次优行为并留下后果 | "完美执行计划"是最强的 AI 味信号 |
| R1.7 | **内在张力**：同日冲突需求间做了取舍，且被牺牲的一方留下代价 | llm | 0=所有需求同时满足；1=有取舍但无代价；2=取舍+代价+后续影响 | 需求系统只加不减 |

> R1.6 / R1.7 是本套件相对 Park et al. believability 评分的主要增量：
> 传统 believability 奖励"连贯合理"，而**过度连贯本身就是不真实**。

### R2 演化能力（单元 U2，N≥30 天；R2.5 跨 agent）

| ID | 命题 | checker | 0 / 1 / 2 锚点 | 常见失败模式 |
|----|------|---------|---------------|-------------|
| R2.1 | **轨迹非平凡**：技能/关系/目标存在可辨识的方向性变化，而非围绕初值抖动 | rule | 由趋势检验给出（Mann-Kendall + 变化幅度 / 初值噪声比），阈值判 0/1/2 | 全部指标随机游走 |
| R2.2 | **因果链可追**：每次显著变化能追溯到具体事件、练习记录或互动 | hybrid | 0=凭空跳变；1=能找到时间上接近的事件但因果牵强；2=事件→机制→变化三段完整 | growth 数值按公式匀速上涨，与 episodes 无关 |
| R2.3 | **路径依赖**：早期选择约束了后期可行集 | llm | 0=前后期无关，任意时点可做任意事；1=有弱约束；2=能指出"因为第 k 天做了 X，所以后来才可能/不可能 Y" | 每天从同一分布重新采样 |
| R2.4 | **适应而非漂移**：对外部冲击（`policy_event` / `life_events`）有策略调整，且调整维持数日 | hybrid | 0=无反应或当日反应次日回弹；1=有反应但无策略性；2=形成新的稳定行为模式 | 事件只进感知文本、不改行为（参见既往 B1 缺陷） |
| R2.5 | **群体分化**：同一初始类型的不同 agent 随时间分化，而非趋同 | rule | 由类型内方差随时间的斜率判定 | 所有人最后活成同一个人 |
| R2.6 | **挫折与回退**：存在停滞、放弃、目标降级 | hybrid | 0=所有成长曲线单调上升；1=有停滞；2=有放弃/降级且有可解释的触发 | 单调递增的成长曲线不可信 |
| R2.7 | **时间尺度合理**：技能 level 的增量与投入分钟数的比例符合常识量级 | hybrid | 由 `total_minutes` vs `level` 增量算出速率，judge 判断该速率对该技能是否合理 | 一周从新手到专家 |

### R3 社会真实性（单元 U3 / U4）

| ID | 命题 | checker | 0 / 1 / 2 锚点 | 常见失败模式 |
|----|------|---------|---------------|-------------|
| R3.1 | **互惠一致**：A 记录的互动，B 那边也存在且指向同一件事 | rule | 由双向匹配率给出 | 单向幻觉社交：A 记得和 B 聊过，B 无记录 |
| R3.2 | **关系有历史**：互动引用共同过去，亲密度随累积互动上升 | hybrid | 0=每次都像初次见面；1=有称呼上的熟悉但无共同事件；2=引用了具体共同经历 | 关系强度是静态属性 |
| R3.3 | **分寸与规范**：请求的强度、边界、称呼与关系强度匹配 | llm | 0=对陌生人提亲密请求；1=略失分寸；2=分寸自然 | 所有人一律热情友好 |
| R3.4 | **选择性与冲突**：存在拒绝、疏远、争执、社交回避 | llm | 0=零冲突零拒绝；1=有回避；2=有冲突且有后果（关系强度下降） | 无摩擦的乌托邦 |
| R3.5 | **传播有失真**：信息在转述链上有丢失、强调偏移或变形 | llm | 0=逐字复制传播；1=有措辞变化；2=有内容取舍与立场着色 | 广播式复制粘贴 |
| R3.6 | **结构成因可解释**：形成的小圈子有可解释成因（同事/同区/共同兴趣），而非随机 | hybrid | 由 modularity/homophily 算出簇，judge 判断簇内共性是否成立 | 社区结构与任何属性都不相关 |

### R4 世界一致性（单元 U1 / U4）

| ID | 命题 | checker | 0 / 1 / 2 锚点 | 常见失败模式 |
|----|------|---------|---------------|-------------|
| R4.1 | **时间预算守恒**：活动时长 + 通勤 + 睡眠 ≤ 24h 且睡眠合理 | rule | 直接算，超支即 0 | 一天干了 30 小时的事 |
| R4.2 | **空间可达**：location 变更均有对应 `travel`，距离/时长/方式自洽 | rule | 无 travel 记录的瞬移、速度超出交通方式上限即 0 | 瞬移 |
| R4.3 | **金钱可负担**：消费不超过可用资金，且与 `daily_ledger.csv` 对得上 | rule | 与既有守恒审计 `conservation_audit.csv` 联查 | 花了不存在的钱 |
| R4.4 | **环境响应一致**：天气/政策事件在当日多数 agent 行为中留下一致痕迹 | llm | 0=只有被注入文本的 agent 有反应；1=部分人反应；2=反应面合理且强度分层 | 事件只写进 perception，不改行为 |
| R4.5 | **公共事实无矛盾**：不同 agent 对同一公共事件的描述不互相打脸 | llm | 0=硬矛盾（同一天说店开着/关着）；1=细节出入；2=一致且视角不同 | 各人活在各自的世界 |
| R4.6 | **常识不越界**：无同时出现在两地、无违背基本物理/社会常识 | hybrid | 有硬冲突即 0 | 分身 |

---

## 4. 聚合规则

```
item_score ∈ {0,1,2} 或 abstain
dimension_score = Σ(w_i · item_score_i) / (2 · Σ w_i)      # 仅对非 abstain 项
                  × coverage                                # 样本覆盖度折扣
```

- **默认所有 `w_i = 1`**；权重只在有人类校准数据支撑时才调整，并在报告里写明依据。
- **不输出单一总分。** 输出 R1–R4 四个分 + 雷达图 + 每条 item 的分布直方图。
  可选 `composite_R = mean(R1..R4)` 仅用于版本间趋势追踪，且必须附弱证据注记。
- **Pass 门槛**（初值，跑过一轮后按人类锚点重标定）：
  `R1 ≥ 0.65`、`R2 ≥ 0.55`、`R3 ≥ 0.60`、`R4 ≥ 0.80`（世界一致性是硬约束，门槛应更高）。
- **abstain 率 > 30% 的维度** → 标 `unassessed`，不给分。这通常意味着数据字段缺失，不是模型不好。
- **三态 gate（Track R 专用）**：
  - 消融判别力检验未跑 → `UNVERIFIED`
  - 任一维度的判别力 < 0.15 → 该维度 `UNTRUSTWORTHY`（judge 分不出真假，分数无意义）
  - 人类一致性 α < 0.6 → `UNVERIFIED`（rubric 表述有歧义，需重写）

---

## 5. 信度机制（这一节是本设计的重点）

### 5.1 多 judge 集成

- 3 个**异质**模型（不同厂商/不同基座），每条 item 取**中位数**，不取均值（抗离群）。
- 上报 **Krippendorff α**（序数）与两两 **QWK**。α < 0.6 的 item 进入重写队列。
- **自评回避**：不使用与生成该 run 内容同族的模型作为 judge；若不可避免，
  必须额外上报 `self_preference_delta`（同族 judge 分 − 异族 judge 分）。

### 5.2 去偏

| 偏差 | 处置 |
|------|------|
| 位置偏好 | 配对判别任务中随机化 A/B 顺序，并做顺序翻转复评 |
| 长度偏好 | 所有样本渲染到统一 token 预算（§2.3） |
| 身份泄露 | 去标识渲染，禁用 "agent" "仿真" 等词 |
| 流畅度偏好 | rubric 明确写"文笔好坏不计分"；R1.5 / R1.6 反向奖励不完美 |
| 分数漂移 | temperature=0，n=3 自洽采样取众数，上报 item 级方差 |

### 5.3 人类锚点校准集

- 30 条黄金样本（跨四个维度分层），2 名标注者独立按同一 rubric 打分。
- 指标：人-人 α（标注者间信度，先要 ≥0.7，否则是 rubric 的问题）、
  人-机 Spearman ρ 与 QWK（要 ≥0.6）。
- 校准集固定并纳入版本控制；每次改 rubric 文案必须重跑校准。
- v0.1 用**合成/占位样本**（人工构造的"好样本 / 破坏样本"对）先把管线跑通，
  真人标注留接口。

### 5.4 消融负控制（判别力检验）⭐

**这是整套方法能不能立住的关键。** 每条 rubric 至少绑定一个"破坏操作"：
把真实样本人为损坏成理应被判低分的样本，如果 judge 判不出来，这条 rubric 就是废的。

| ID | 破坏操作 | 应当掉分的 item |
|----|---------|----------------|
| N1 | 打乱 `recollections`（换成其他 agent 的记忆） | R1.1 |
| N2 | 人设互换（A 的 profile 配 B 的行为） | R1.3、R1.2 |
| N3 | 时间打乱（把 30 天的顺序 shuffle） | R2.1、R2.2、R2.3 |
| N4 | 单日复制（day 1 复制成 30 天，只改日期） | R2.1、R2.5、R2.6、R1.5 |
| N5 | 合成随机游走替换真实 growth 曲线 | R2.2、R2.6、R2.7 |
| N6 | 社交线互换（把 A-B 的互动接到 A-C 上） | R3.1、R3.2、R3.6 |
| N7 | 注入预算破坏（超支的钱/时间/瞬移） | R4.1、R4.2、R4.3、R4.6 |
| N8 | 事件剥离（删掉 `policy_event` 后的行为变化） | R2.4、R4.4 |

**判别力**：

```
discrimination(item) = (mean_score_real − mean_score_ablated) / 2      # 满分归一
```

- `discrimination ≥ 0.30`：有效
- `0.15 ≤ d < 0.30`：弱，标注但保留
- `d < 0.15`：**该 item 作废**，从当次评分中剔除并进入重写队列

还需上报**假阳性方向**：把破坏样本判高分固然坏，把真实样本判低分同样坏 →
同时报 `mean_score_real`（应显著高于中位）。

### 5.5 配对判别（"图灵式"，留位）

盲测：给 judge 一条真人日记/访谈和一条仿真样本，判断哪个是真人。
**判别准确率越接近 50% 越好**（不是越高越好）。

- v0.1 无真人语料 → 先做**相对图灵**：GAWorld 早期版本 vs 当前版本配对，
  报"当前版本被判为更像真人的比例"，作为版本间进步的相对信号。
- 真人语料接入后替换为绝对指标 `|accuracy − 0.5|`，越小越好。

### 5.6 成本与可复现

- 记录每次评测的 judge 模型版本、prompt hash、rubric 版本、抽样 seed，全部写进结果 JSON。
- **rubric 版本变更即断代**：不同 rubric 版本的分数不可比，scorecard 显式标注。
- 成本预算：单次完整评测（含 3 judge × 3 采样 × 全部单元）应控制在可接受 token 量内；
  `rule` 类 item 不耗 token，是控本的主要手段。

---

## 6. 实现映射与 CLI 草案

### 6.1 模块划分（`benchmark/rubric/`）

| 模块 | 职责 |
|------|------|
| `sampler.py` | 分层随机抽取 U1–U5 单元，输出 manifest（含 seed、覆盖度） |
| `renderer.py` | 单元 → 去标识、定长的 judge 输入文本 |
| `rules.py` | 所有 `rule` / `hybrid` 类 item 的程序化事实计算 |
| `judge.py` | 调用 LLM（复用 `gaworld/llm/providers.py`），强制结构化输出 |
| `ablate.py` | N1–N8 破坏算子 |
| `aggregate.py` | item → 维度 → scorecard，含信度指标 |
| `loader.py` | 读 `output/` 的各类产物，缺文件一律降级为空而不是报错 |
| `runner.py` | 编排：取样 → 打分 → 消融 → 聚合；含离线 stub judge |
| `synth.py` | 合成夹具（`--synthetic` 的正样本，同时是消融算子的自检基准） |
| `rubrics.json` | rubric 条目定义（命题、锚点、失败模式、权重、checker、绑定的消融） |

**rubric 存独立数据文件而非硬编码**，修订 rubric 不需要改代码，且对文件做 sha256 得到版本 hash
（写进每次 scorecard 的 `manifest.rubric_hash`）。

> 实现期偏离设计：原计划用 YAML，实际改用 **JSON**。仓库 `requirements.txt` 无 PyYAML，
> 且 `benchmark/gaworld_bench.py` 是刻意的 stdlib-only。为一份配置文件引入运行时依赖不划算；
> JSON 同样能做版本 hash，代价是不能写注释（已用 `note` 字段替代）。

### 6.2 judge 输出契约

```json
{
  "item_id": "R1.1",
  "score": 2,
  "evidence": ["day 12: 想起上周在便利店...", "day 5 episode: 便利店打工"],
  "reasoning": "≤60 字",
  "abstain": false
}
```

- `evidence` 为空 → 强制 `abstain=true`，`score` 作废。这是防脑补的硬约束。
- `reasoning` 限长，避免 judge 用长篇论证自我说服。

### 6.3 CLI

```bash
cd benchmark

# 合成自检：不调 LLM，构造样本 + stub judge，跑通全管线并验证消融算子
python3 rubric_bench.py --synthetic --ablate all

# 合成自检（快进态）：验证无 episodes 时 R1/R3/R4 弃权、R2 仍可评
python3 rubric_bench.py --synthetic --synthetic-mode fast_forward --ablate N3,N4,N5

# 规则项评测真实 run（零 token）
python3 rubric_bench.py --output-dir ../output

# 全量评测（多 judge 集成）
python3 rubric_bench.py --output-dir ../output --judges minimax,ollama_gemma4 --sample-seed 42

# 判别力检验 —— 这一步才能把 Track R 从 UNVERIFIED 抬出来
python3 rubric_bench.py --output-dir ../output --judges minimax --ablate N1,N3,N7

# 只跑某维度
python3 rubric_bench.py --dim R2 --min-days 30

# 单测
python3 -m unittest test_rubric_bench
```

输出：`benchmark/results/rubric_scorecard.{json,md}`，并合入主 scorecard 的 Track R 行。

### 6.4 已验证的行为（v0.1.1）

- `--synthetic --ablate all`：6 个 `rule` 类 item 的判别力全部 ≥ 0.5（R4.1/4.2/4.3 = 1.00，
  R2.1 = 0.81，R2.5 = 0.50，R3.1 = 0.50）→ 规则实现与破坏算子互相验证通过。
- 合成模式下 LLM 条目被 stub judge 判为低判别力并剔除，这是 **stub 的性质而非 rubric 的性质**，
  报告里已加显著警告；stub 只能识别结构性破坏（重复日、瞬移、外来记忆），识别不了人设互换与社交改线。
- 未配置 judge 时，LLM 条目一律 `abstain`（弃权率 1.0、均分 `n/a`），**不会**被记成 0 分。
- 快进态自检（`--synthetic-mode fast_forward`）：R1/R3/R4 全部因缺 `episodes` / `authored_diary` /
  `social_graph` 弃权；R2.1 与 R2.5 仍可评，且在 N3/N4 下判别力 0.75 / 0.50——
  即消融算子在"只有状态序列"的产物上同样有效，不会静默变成空操作。
- 34 条单测覆盖规则判据、judge 解析的证据强约束、消融不污染原样本、能力门控的两种 run 形态、
  聚合的覆盖度折扣与剔除逻辑。

---

## 7. 局限与已知风险

1. **rubric 只能测"写得下来的"。** 真人的不可名状之处，这套方法系统性测不到；
   分数高不等于像人，只等于"没被这批 checklist 抓到破绽"。
2. **消融是必要不充分。** 通过判别力检验只证明 judge 能识别人为损坏，
   不证明它能识别"生成式模型特有的、结构完好的假"。§5.5 的真人配对是唯一能补这一块的手段。
3. **LLM judge 对流畅中文有正偏**，且中文语料上 judge 的稳定性弱于英文，
   α 需实测，不能照搬英文文献的经验值。
4. **R2 依赖长 run**，成本高；<30 天的 run 上 R2 一律 `unassessed`，不要用短 run 的 R2 分做决策。
5. **R1.6 / R1.7 与模型对齐目标天然冲突**——LLM 倾向生成"合理、完整、积极"的行为，
   这两条大概率是初期最低分项。低分是真实信息，不要通过改 rubric 去粉饰。
6. **与 Track A 同样的循环论证风险**：如果 rubric 是照着 GAWorld 现有输出字段写的，
   就只是在验证"我们输出了我们打算输出的东西"。缓解手段是 rubric 先独立于实现写出来，
   再看有多少条因为缺字段而 abstain——**abstain 清单本身就是一份功能缺口报告**。

---

## 8. 落地顺序

| 阶段 | 内容 | 产出 |
|------|------|------|
| **P0** | 两档 run（见 §2.4）：A 全保真 20×12 天 + B 快进 20×60 天 | 可评测的数据底座（**未做，当前唯一阻塞项**；harness 侧的能力门控已就绪） |
| **P1** ✅ | `rules.py` + R4 全部 + R2.1/R2.5 + R3.1（纯规则项，零 token） | 不依赖 LLM 的硬指标 |
| **P2** ✅ | `judge.py` + `rubrics.json` + 多 judge 集成 + 证据强约束 | 主观分管线 |
| **P3** ✅ | `ablate.py` + 判别力检验 → 剔除无效 item | 机制就位；**rubric 表待真实 judge 跑过一轮后定稿** |
| **P4** | 人类锚点 30 条 + α/QWK 校准 | Track R 从 UNVERIFIED 转 OK |
| **P5** | 真人语料接入 + 配对判别 | 绝对图灵指标 |

**P4 之前产生的任何 Track R 分数都标 UNVERIFIED，不进对外材料。**

### 8.1 P0 的实测缺口（2026-08-13 在当前 `output/` 上跑出）

```
R1 个体拟人性  n/a  覆盖度 0.00  unassessed
R2 演化能力    n/a  覆盖度 0.00  unassessed   ← 无 ≥30 天轨迹
R3 社会真实性  n/a  覆盖度 0.00  unassessed   ← social_partners 全为空，无可双向核对的互动
R4 世界一致性  0.441 覆盖度 0.475 弃权率 0.74 unassessed
```

弃权清单即功能缺口清单（§7.6）：当前 `output/` 只有 11 个 agent 的 episodes、
`diaries/` 只有 1 个 agent，`daily_ledger.csv` 只覆盖 2 天 → R4.3 弃权率 0.90。

**R4.1 在真实数据上发现的疑似不一致**（3/14 个可评 agent-day 判 0）：

```
AD:41:49  06:39 在“湖滨银泰in77 E区”，06:40 在 2.961 km 外的“工联CC二期”，中间 e-bike 10 分钟
AD:39:4   08:57 通勤 36 分钟 > 与上一事件间隔 20 分钟
AD:40:5   08:42 通勤 29 分钟 > 与上一事件间隔 20 分钟
```

两种解释，需要看调度器才能定：(a) episode 的 `time` 是活动时刻，通勤时长未从时间网格里扣除；
(b) `time` 是出发时刻，则本判据的口径需要改成"到达时刻 = time + travel.minutes"。
后两例正好落在 20 分钟的固定网格上，倾向 (a)。**未擅自改动仿真代码，仅记录。**
