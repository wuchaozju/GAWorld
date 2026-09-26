# 收入有两个来源，而且对不上

日期：2026-09-19
状态：**已按方案 A 实施**（2026-09-19）
起因：做「拥车条件」时需要一个收入信号，发现有两个，而且不一致

---

## 一、现象

Agent 的收入同时存在于两处，互不相干：

1. **profile 文本**：`**教育与收入背景**：大专学历，月收入约 9,117 元。`
   由 `gaworld.population` 按人口规格采样生成，进入 agent 的 LLM 提示。
   但 `gaworld/sim/agents_loader.py::parse_profile` **不抽取这一项**——它只抽
   name / age / living / job / personality / behavior_tendencies / daily_life / values。
   所以这个数字只存在于提示文本里，代码从来读不到。

2. **economy 账本**：`_init_agent_economy`（`gaworld/economy/finance.py:1792`）按
   `_job_income_band(job)` 取区间、乘 `_rng.uniform` 与 `income_skill`，
   自行算出 `gross_monthly_salary`。**全程不看 profile 说了多少。**

## 二、实测差距（500 人种群，326 人有可解析的收入）

| | 中位 | 均值 | p10 | p90 | gini |
|---|---|---|---|---|---|
| profile 声称 | 4,918 | 7,228 | 2,221 | 14,761 | **0.468** |
| economy 实算 | 7,349 | 8,195 | 2,407 | 15,367 | **0.348** |

- 逐人比值 `economy / profile`：中位 **1.39**，p10 0.58，p90 **3.47**
- 相关系数 **r = 0.305**

r 不是 0（两者都与职业相关），但 0.305 意味着**账本上的工资和这个人自己简历上写的收入，基本是两回事**。有人的账本收入是简历的 3.5 倍。

## 三、为什么这件事重要

1. **提示和账本互相矛盾**。一个 profile 写着月入 2,275 元的人，消费行为按 7,900 元结算。LLM 读到的自我认知和经济系统给他的现金流不是同一个人。
2. **人口合成器的标定被丢掉**。`gaworld.population` 的 IPF 把 income_median / income_gini 拟到规格上（本次 manifest：gini 目标 0.420 → 实际 0.414），economy 一重摇就换成 0.348。**把不平等压掉了约 0.12。**
3. **打到 Track A 锚点**。`wealth_gini` 是 Track A 的锚点之一。初始收入分布的 gini 差 0.12，那条锚点量的就是 economy 自己重摇出来的分布，而不是被校准过的人口。

## 四、可选方案（未实施，需决策）

**A. economy 读 profile 的收入作为锚**
`parse_profile` 增抽 `monthly_income`；`_init_agent_economy` 在有值时以它为基准，
`income_skill` / RNG 只做小幅扰动，无值时回落到现行 job-band 逻辑。
- 优点：一处生成、一处消费；人口合成器的标定真正生效；提示与账本一致。
- 代价：**所有既有 run 的经济结果不可比**（与货币改造同级）。
- 风险：老的 hangzhou 51 人语料如果没有收入行，会走回落路径，两种 agent 的口径不同——需要检查。

**B. 反过来，让 profile 显示 economy 算出的数**
生成 profile 时不写收入，或改由 economy 回填。
- 优点：不动经济逻辑。
- 缺点：人口合成器的收入标定彻底作废，IPF 那一维白拟。

**C. 什么都不改，明确记录**
在 provenance 表里写明「profile 收入仅为叙事，经济以 job-band 为准」。
- 优点：零风险。
- 缺点：`wealth_gini` 锚点继续测的是重摇出来的分布；提示与账本的矛盾留在系统里。

倾向 A，但它动的是被仔细改造过的货币系统，且会让所有经济 run 重来，应由项目方决定。

## 五、与拥车条件的关系

拥车率按收入分层是标准做法（(b) 类机制），但**在收入口径统一之前做不了**：
按 profile 收入分层，和按 economy 收入分层，会得到差异很大的两个拥车人群
（逐人比值 p10 0.58 / p90 3.47）。所以这件事排在拥车之前。

---

相关：`docs/proposals/2026-09-19-endogenous-road-congestion.md` §11.4（公交占机动化 62.8% vs 锚点 47.6%，缺口在拥车条件）。

---

## 六、实施结果（方案 A）

- `gaworld/sim/agents_loader.py`：`parse_profile` 增抽 `monthly_income`（新增 `_extract_income`），
  吃得下两种语料的写法（`月收入约 9,117 元` / `目前月收入约12,000元`），
  `无固定收入` 正确返回 `None`。`build_agent` 是 `**text` 展开，字段自动流到 agent 上。
- `gaworld/economy/finance.py`：`_init_agent_economy` 在有 `monthly_income` 时以它为锚，
  乘 `±profile_income_jitter` 的扰动；**最低时薪地板之后重算 gross**，两者不会漂开。
  无值时原样回落 job-band。
- 配置：`economy.use_profile_income`（默认 **True**）、`economy.profile_income_jitter`（默认 0.08）。
  关掉即恢复 2026-09 之前的行为。

实测（500 人种群，326 人有收入行）：

| | r | 中位比值 | p10 / p90 | 账本 gini |
|---|---|---|---|---|
| 旧（重摇） | 0.305 | 1.39 | 0.58 / 3.47 | 0.348 |
| 新（读 profile） | **0.998** | **1.00** | 0.94 / 1.07 | **0.459** |

profile 自身 gini 0.468；账本 0.459 的差距就是 ±8% 抖动的平滑，可以用
`profile_income_jitter: 0` 消掉。

测试：`tests/test_profile_income.py` 10 项（含两种语料写法、无收入回落、开关复原、
最低时薪地板、高低收入者差距不被压缩）。全量 2445 passed，失败集与基线一致。

**⚠️ 旧 run 不可比**：所有经济量（工资、税、消费、储蓄、wealth_gini）都变了。

### 顺带发现，未处理

回落路径上，「无业，家庭照料为主」和「学生」也会拿到 1,888–3,219 元的月薪
——`_job_income_band` 对这些职业文本没有零收入分支。这是既有行为，不是本次引入，
但它会污染 `wealth_gini` 锚点，建议单独处理。
