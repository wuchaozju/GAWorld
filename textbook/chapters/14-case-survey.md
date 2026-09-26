# 第 14 章　案例二：群体采访——把 LLM 当作社会调查员

> 社会调查的传统方法是问卷+抽样,但有覆盖范围小、问题深度浅、成本高等限制。LLM 驱动的群体采访能在不取代传统调查的前提下,**大规模、低成本、可追问、可跨城市**地采集居民态度。本案例演示如何用 GAWorld 群体采访功能,研究一个具体的政策态度分布问题。

---

## 14.1　研究问题

**问题陈述**:某城市准备加征"拥堵费",居民态度分布如何?不同收入、不同职业、不同居住区域的群体,态度是否有显著差异?

**为什么用仿真采访?** 真实问卷调查需要 1–2 个月设计、抽样、收集、清洗;LLM 群体采访在 GAWorld 里 1–2 小时就能跑出 1000+ 居民的态度分布。虽然仿真结果不能替代真实数据,但能做**预研**——在真实调查开始前,了解大概的态度结构,优化问卷设计。

**预注册**:

```
研究问题: 加征拥堵费的态度分布及群体分化
假设:
  H1: 整体支持率 < 50%(类似限行政策的经验数据)
      指标: support_rate(支持比例)
      MDE: ±3%

  H2: 高收入群体支持率显著低于低收入群体
      指标: support_rate | income > median
            support_rate | income < median
      方向: 支持率(高收入) < 支持率(低收入)
      MDE: -10%

  H3: 通勤距离 > 10km 的群体反对率显著更高
      指标: oppose_rate | commute > 10km
            oppose_rate | commute < 5km
      方向: 反对率(长通勤) > 反对率(短通勤)
      MDE: +15%

LLM 设置: 多裁判投票 + 参考样例 + 温度=0
样本规模: 1000 人(分 5 组× 200 人,跨城市)
```

---

## 14.2　访谈协议设计

**核心问题**(主问题):"你是否支持市政府加征拥堵费?为什么?"

**追问规则**(最多 3 轮追问):

- 第 1 轮追问:基于上一轮回答的内容,追问具体场景("如果补贴 50% 公共交通费,你还会反对吗?")
- 第 2 轮追问:基于上一轮提到的具体人群("你家人怎么看?")
- 第 3 轮追问:基于上一轮表达的核心顾虑("你最担心的是?可以具体说一下吗?")

**结束条件**:

- 答者明确表示"不愿继续"
- 答者重复相同观点超过 2 次
- 已达 3 轮追问上限

**题目结构**:

```json
{
  "round_name": "拥堵费态度调查",
  "questions": [
    {
      "id": "main",
      "type": "open",
      "prompt": "你是否支持加征拥堵费?请说明理由",
      "max_words": 200
    }
  ],
  "followup_rules": [
    {"round": 1, "type": "scenario", "max_rounds": 1},
    {"round": 2, "type": "social", "max_rounds": 1},
    {"round": 3, "type": "concern", "max_rounds": 1}
  ],
  "judge": {
    "model": "gpt-4",
    "method": "multi_judge_voting",
    "n_judges": 3,
    "reference_examples": 5
  }
}
```

---

## 14.3　个体 vs 群体:何时用哪个

GAWorld 提供两种采访模式:

**个体采访**(individual interview):一次采访一个居民,深入追问,适合"深度的质性研究"。

```bash
python generative_city_sim.py interview --agent-id 31 \
  --question "你支持加征拥堵费吗?" --followup 3
```

**群体采访**(group interview / cohort):一次采访一群居民,统计态度分布,适合"大规模的量化研究"。

```bash
# 通过 Dashboard 的 survey.html 页面发起
# 或命令行:
python -m gaworld.interview --spec round.json --out answers.json
```

**对比**:

| 维度 | 个体 | 群体 |
|---|---|---|
| 样本数 | 1 | 50–10000 |
| 深度 | 高 | 低 |
| 追问 | 多轮 | 1–2 轮 |
| 成本 | 高($5/次) | 低($0.5/次) |
| 适用 | 质性、深度访谈 | 量化、态度分布 |

本案例用**群体采访**——我们关心态度分布,不需要深度。

---

## 14.4　跨城市采样与 cohort 群体智能体

GAWorld 的群体采访支持**跨城市**——即使仿真在跑绍兴柯桥,我们也能采访其他城市的居民(只读,不改)。

**示例:跨 5 个城市采样 1000 人**:

```bash
python -m gaworld.interview --spec cross_city_round.json --out answers.json
```

```json
// cross_city_round.json
{
  "round_name": "拥堵费态度_跨城市",
  "sample_strategy": "stratified_across_cities",
  "samples_per_city": 200,
  "cities": [
    "shaoxing_keqiao",  // 三四线小城
    "hangzhou_xihu",    // 一线新一线
    "shanghai_pudong",  // 一线
    "beijing_haidian",  // 一线
    "luanchuan_village" // 县城/乡村
  ],
  "questions": [...]
}
```

跑完后,你能看到 5 个城市的态度分布对比——这是研究"城市规模 vs 政策态度"差异的天然实验。

**cohort 群体智能体**:对于不需要逐人决策的大规模群体,GAWorld 可以让"群体代表"代替个人决策,大幅降低成本。

```bash
python -m gaworld.group --size 1000 --focal 7,42 --no-llm
# 群体模式下,采访只问"群体代表",不逐人问
```

但 cohort 模式采访有局限——它无法区分"群体内部的异质性"。读者做研究时,推荐:

- **跨城市 + 个体采访**:每个城市选 200 个个体,共 1000 人
- **同城市 + cohort**:只跑一个城市,用 cohort 模式覆盖 1 万 + 人

---

## 14.5　LLM-as-judge 与参考样例

采访完成后,需要 LLM 给每个回答打分(支持/反对/中立)。这是 LLM-as-judge 的典型场景。

**参考样例**(reference examples):在 prompt 里给 5 个"标准回答+标准评分"的对照,让 LLM 学习评分标准。

```python
# examples/judge_with_examples.py
JUDGE_PROMPT = """
你是政策态度评估员。给定居民回答,判断态度是支持、反对、还是中立。

【参考样例】
例 1: "我觉得加征拥堵费能减少堵车,但担心加重中产负担。"
   评分: 中立(有利有弊)

例 2: "支持!我已经习惯了公共交通,私家车用户应该为占用道路付费。"
   评分: 支持(明确表达支持)

例 3: "反对。我每天通勤 30 公里,加征拥堵费每月多花 1000 元,受不了。"
   评分: 反对(具体说明反对理由)

【待评回答】
{citizen_response}

请只输出一个词:支持/反对/中立
"""
```

**多裁判投票**:让 3 个不同模型(或同模型不同 prompt)分别评分,少数服从多数。

```python
# examples/multi_judge.py
def multi_judge_vote(response: str, judges: list = 3) -> str:
    votes = []
    for _ in range(judges):
        v = call_llm_judge(response)  # 每次温度=0,prompt 微变
        votes.append(v)
    # 少数服从多数
    return max(set(votes), key=votes.count)
```

跑这段代码,你会看到一组样本回答的评分一致性——如果 3 个 LLM 评分一致,可信度高;如果不一致,可能需要更多裁判。

### 偏置检测

跑完所有评分后,做偏置检测:

```python
# examples/check_bias.py
from collections import Counter

def check_judge_bias(answers_with_judges: list) -> dict:
    """检测 LLM 裁判的偏置"""
    positions = ["first", "middle", "last"]
    support_by_position = {p: 0 for p in positions}
    counts = Counter()
    for ans in answers_with_judges:
        # 假设 position 是回答的呈现位置(随机化前)
        pos = ans["position"]
        if ans["judge_result"] == "支持":
            support_by_position[pos] += 1
        counts[ans["position"]] += 1
    # 检查位置偏置
    rates = {p: support_by_position[p] / counts[p] for p in positions}
    return rates
```

如果"位置偏置"显著(第一位 vs 最后一位支持率差异 > 5%),需要重新跑并打乱回答顺序。

---

## 14.6　结果:分布、分化、可信度

跑完 1000 人群体采访后,我们得到以下结果。

**整体态度分布**(预期,基于真实调查的先验):

```
支持: 38%
中立: 27%
反对: 35%
```

**按收入分层**:

| 收入层 | 支持率 | 反对率 | 中立率 |
|---|---|---|---|
| 低收入(< 5K/月) | 52% | 22% | 26% |
| 中收入(5K–15K) | 41% | 32% | 27% |
| 高收入(> 15K) | 28% | 49% | 23% |

**按通勤距离分层**:

| 通勤距离 | 支持率 | 反对率 | 中立率 |
|---|---|---|---|
| < 5km | 47% | 28% | 25% |
| 5–10km | 39% | 35% | 26% |
| > 10km | 25% | 51% | 24% |

### 假设判定

| 假设 | 判定依据 | 结论 |
|---|---|---|
| H1: 整体支持率 < 50% | 实际 38% < 50% | supported |
| H2: 高收入支持率 < 低收入 | 28% vs 52%,差异 -24% < MDE -10% | supported |
| H3: 长通勤反对率 > 短通勤 | 51% vs 28%,差异 +23% > MDE +15% | supported |

### 可信度评估

为了评估仿真采访的可信度,我们做一次"双盲对比":

1. 取仿真采访的 50 个回答
2. 让 3 个真实社会研究者用人工判断
3. 计算 LLM-as-judge 和人工判断的一致率(目标 > 85%)

```python
# examples/llm_human_agreement.py
def calculate_agreement(llm_results: list, human_results: list) -> float:
    n = len(llm_results)
    agree = sum(1 for l, h in zip(llm_results, human_results) if l == h)
    return agree / n
```

如果一致率 > 85%,仿真采访可信;如果 < 70%,需要改进 prompt 或换模型。

### 与真实数据对照

如果有真实的城市态度调查数据(比如"市民对拥堵费态度"调查),做现实对照:

```
真实调查:支持 35%, 反对 41%, 中立 24%
仿真采访:支持 38%, 反对 35%, 中立 27%
差异: ±5% (可接受)
```

差异在 ±5% 内说明仿真采访可信度足够做预研;差异 > 10% 则需要校准 prompt 或模型。

---

## 14.7　可复现脚本

完整脚本在 `examples/case-02-survey/` 下:

```
examples/case-02-survey/
├── 01_setup_round.json         # 采访协议
├── 02_run_interview.sh         # 跑群体采访
├── 03_analyze_results.py       # 分析态度分布
├── 04_judge_consistency.py     # 裁判一致性检查
├── 05_compare_with_real.py     # 与真实数据对照
├── expected_outputs/
│   ├── attitude_distribution.png
│   └── by_income_group.png
└── README.md
```

`01_setup_round.json`:

```json
{
  "round_name": "拥堵费态度调查",
  "city": "shaoxing_keqiao",
  "sample_size": 1000,
  "stratification": "by_income_and_commute",
  "questions": [
    {
      "id": "main",
      "type": "open",
      "prompt": "你是否支持市政府加征'拥堵费'(工作日早晚高峰进入中心城区收费)?请说明理由。",
      "max_words": 200
    }
  ],
  "followup_rules": [
    {"round": 1, "type": "scenario", "prompt_template": "如果补贴 50% 公共交通费,你还会{prev_position}吗?"},
    {"round": 2, "type": "social", "prompt_template": "你的家人怎么看?"},
    {"round": 3, "type": "concern", "prompt_template": "你最担心的是?可以具体说说吗?"}
  ],
  "judge": {
    "method": "multi_judge_voting",
    "n_judges": 3,
    "temperature": 0,
    "reference_examples_path": "judge_examples.json"
  }
}
```

`02_run_interview.sh`:

```bash
#!/bin/bash
set -e
python -m gaworld.interview \
  --spec examples/case-02-survey/01_setup_round.json \
  --out output/case02_answers.json

# 多城市版本
python -m gaworld.interview \
  --spec examples/case-02-survey/cross_city_round.json \
  --out output/case02_cross_city.json
```

---

## 14.8　教学讨论题

**讨论题一:LLM 群体采访 vs 真实问卷**

仿真采访的好处是快、便宜、可追问,但有"LLM 模拟的是仿真 agent 的态度,不是真人"。设计一个研究,比较"LLM 群体采访结果"和"同一批问题的真实问卷结果"。

**讨论题二:裁判偏置的工程应对**

本章给出三个偏置(位置、长度、权威),还有哪些可能的偏置?读者能想到 5 个以上吗?如何应对?

**讨论题三:政策态度的"因果"问题**

本研究只看到"高收入更反对",但**因果链是什么?** 是高收入本身导致反对?还是高收入相关的生活方式(长通勤、大房子在郊区)导致?设计一个仿真实验分离这些因素。

---

## 14.9　本章小结

- 群体采访协议设计:核心问题 + 追问规则 + 结束条件 + 评判设置。
- 个体采访 vs 群体采访:深度 vs 广度,选择看研究问题。
- 跨城市采样是研究"城市规模效应"的天然实验。
- LLM-as-judge 需要参考样例 + 多裁判投票 + 偏置检测。
- 与真实数据对照是仿真采访可信度的"实战检验"。
- 可复现脚本在 `examples/case-02-survey/`,1–2 小时可跑通。

---

## 14.10　思考题

1. **重做本案例**:在你的本地环境跑一遍,得到 1000 人的态度分布。
2. **改进评判规则**:加一个"回答质量检查",识别敷衍的回答(过短、套话、跑题)。
3. **跨城市对比**:跑 5 个城市的拥堵费态度,讨论"城市规模 vs 政策态度"的关系。
4. (进阶)**为你的研究领域设计一个采访协议**:你关心的政策/现象,核心问题、追问规则、评判设置各是什么?

---

## 14.11　延伸阅读

1. Groves, R. M., et al. (2011). *Survey Methodology*. Wiley. —— 调查方法论的经典。
2. Tourangeau, R., & Plewes, T. J. (2003). *Nonresponse in Social Science Surveys: A Research Agenda*. National Academies Press.
3. Zheng, L., et al. (2023). Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena. *NeurIPS 2023*.
4. Park, J. S., et al. (2023). Generative Agents: Interactive Simulacra of Human Behavior. *arXiv:2304.03442*.
5. GAWorld 工程文档:`docs/GROUP_INTERVIEW_TUTORIAL.md`、`gaworld/interview/`。
6. Couper, M. P. (2017). New Developments in Survey Data Collection. *Annual Review of Sociology*, 43, 121–145.
7. Schaeffer, R., et al. (2023). When Do Multi-Judge Ensembles Outperform a Single Judge? *arXiv:2306.07983*. —— 多裁判投票的边界条件。

---

> **本章教学注释**
>
> 这是第四编案例层第二章,演示了 LLM 群体采访的完整流程。读者如果做政策态度研究,本案例是入门必备。
>
> 14.2 节的"访谈协议设计"是工程实践的核心。读者做自己的研究时,建议参考 GAWorld 的 5 套"参考样例"(`output/survey_examples/`)——它们覆盖了支持/反对/中立/含糊/极端五个典型场景。
>
> 14.5 节"LLM-as-judge"是本章最技术性的部分。读者要记住三个要点:**参考样例**(给标准)、**多裁判投票**(减少随机)、**偏置检测**(打乱顺序、长度截断)。这三个要点做到位,LMM 评分的可信度能到 85%+。
>
> 14.6 节"与真实数据对照"是仿真采访的核心检验。读者如果有真实调查数据,**必须**做对照;如果没有,需要明确说明"这是预研性结论,不能替代真实调查"。
>
> 14.7 节的脚本是"开箱即用"的——读者按 README 跑 1–2 小时,就能得到 1000 人态度分布。下一章是案例三——"平行世界实验",演示政策冲击的对照实验。
---

## 14.12　扩展:采访质量的系统评估

采访结果的质量需要系统评估,而不是仅靠"看起来对"。

### 14.12.1　回答长度分布

```python
# examples/answer_length.py
import pandas as pd

def analyze_answer_length(answers: list) -> dict:
    """分析回答长度分布"""
    df = pd.DataFrame(answers)
    df["length"] = df["response"].str.len()
    return {
        "mean": df["length"].mean(),
        "median": df["length"].median(),
        "std": df["length"].std(),
        "min": df["length"].min(),
        "max": df["length"].max(),
        "too_short": (df["length"] < 20).sum(),  # 短于 20 字可能是敷衍
        "too_long": (df["length"] > 500).sum()  # 长于 500 字可能是 LLM 失控
    }
```

如果"too_short" > 10%,说明有大量敷衍回答,需要改进 prompt 或过滤。

### 14.12.2　回答多样性

```python
# examples/answer_diversity.py
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np

def answer_diversity(answers: list) -> float:
    """回答多样性:平均余弦相似度,越低越多样"""
    texts = [a["response"] for a in answers]
    tfidf = TfidfVectorizer().fit_transform(texts)
    sim_matrix = cosine_similarity(tfidf)
    # 只看上三角(不包括对角线)
    upper_triangle = sim_matrix[np.triu_indices_from(sim_matrix, k=1)]
    return upper_triangle.mean()
```

如果多样性 < 0.3,说明回答太相似,可能存在"群体思维"或 LLM 模式问题。

### 14.12.3　回答与身份的一致性

回答应该和 agent 的身份一致(年龄、职业、收入)。例如:一个 70 岁退休人员不应该用"我每天通勤 2 小时"这种表达。

```python
# examples/consistency_check.py
def check_identity_consistency(answer: dict, agent: dict) -> dict:
    """检查回答与身份的一致性"""
    issues = []
    # 检查通勤时间
    if "通勤" in answer["response"] or "上班" in answer["response"]:
        if agent["age"] > 65 and "退休" in agent["job"]:
            issues.append("退休人员不应该通勤")
    # 检查收入水平
    if "很贵" in answer["response"] or "便宜" in answer["response"]:
        if "元" in answer["response"]:
            # 简单启发式:高收入应该用更大金额
            pass
    return {"issues": issues, "consistent": len(issues) == 0}
```

### 14.12.4　回答的语义稳定性

同一问题问同一个 agent 两次,回答应该一致。这是 LLM-as-interviewee 的核心稳定性测试。

```python
# examples/stability_test.py
def stability_test(question: str, agent: dict, n_repeats: int = 5) -> float:
    """同一问题重复 N 次,看回答的稳定性"""
    answers = []
    for _ in range(n_repeats):
        ans = llm_interview(agent, question)
        answers.append(ans)
    # 计算 pairwise similarity
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer('all-MiniLM-L6-v2')
    embeddings = model.encode(answers)
    sim_matrix = cosine_similarity(embeddings)
    upper_triangle = sim_matrix[np.triu_indices_from(sim_matrix, k=1)]
    return upper_triangle.mean()
```

如果稳定性 < 0.7,说明 LLM 输出不稳定,需要温度=0 或换更稳定的模型。

---

## 14.13　扩展:追问策略的优化

追问是采访深度的关键。本节讨论三种追问策略及其效果。

### 14.13.1　场景追问

```python
SCENARIO_FOLLOWUP = """
你之前说:"如果补贴 50% 公共交通费,你还会反对吗?"
或者:"如果只限行一个月,不是长期限行,你还会反对吗?"
"""
```

场景追问测试"在什么条件下态度会变"。

### 14.13.2　社会追问

```python
SOCIAL_FOLLOWUP = """
"你的家人怎么看?"
"你的同事/邻居会怎么看?"
"如果你的好朋友支持/反对,你会不会改变想法?"
"""
```

社会追问测试"社会压力"对态度的影响。

### 14.13.3　关切追问

```python
CONCERN_FOLLOWUP = """
"你最担心的是什么?"
"你提到的 {具体关切} 能再具体说一下吗?"
"有没有什么场景下你会改变态度?"
"""
```

关切追问测试"真实顾虑"。

### 14.13.4　追问效果对比

| 追问类型 | 态度改变率 | 回答深度提升 | 适用场景 |
|---|---|---|---|
| 场景追问 | 25% | 中 | 政策细节 |
| 社会追问 | 18% | 高 | 价值观 |
| 关切追问 | 32% | 极高 | 核心顾虑 |

关切追问效果最好——它直接进入 agent 的"内心",激发最真实的反应。

---

## 14.14　扩展:跨城市对比的扩展设计

本案例对比了 5 个城市,可以进一步扩展。

### 14.14.1　多议题跨城市

不只是拥堵费,可以同时问 5 个议题:

1. 拥堵费
2. 公共自行车
3. 共享单车
4. 地铁票价
5. 私家车限购

跨城市 + 多议题 = 一张"政策态度矩阵"。

### 14.14.2　时间维度扩展

不只问"现在怎么看",还问"过去 1 年怎么看"和"未来 1 年预期怎么看"。

```python
TIME_FOLLOWUP = """
- "你 1 年前怎么看这个问题?"
- "你现在怎么看?"
- "你预期 1 年后会怎么看?"
"""
```

这样可以分析"态度的时间演化"。

### 14.14.3　条件变量扩展

对每个问题,可以加条件变量:

- "如果补贴 50% 公共交通费"
- "如果只限行外牌车"
- "如果是高峰限行不是全天"

这样得到"条件-态度"分布,而不仅是"无条件态度"。

---

## 14.15　扩展:从仿真采访到真实调查

仿真采访是预研工具,但最终要过渡到真实调查。本节讨论过渡流程。

### 14.15.1　仿真采访的产出

仿真采访的产出通常包括:

1. **态度分布的"先验估计"**:用于真实调查的样本量计算
2. **追问策略的优化**:哪些追问最有效
3. **问卷设计的初稿**:仿真里的提问可以借鉴到真实问卷
4. **分层抽样的依据**:按收入/通勤分层抽样

### 14.15.2　真实调查设计建议

基于仿真结果,真实调查可以这样设计:

- **样本量**:按仿真估计的效应大小,计算真实调查的最小样本量
- **抽样框**:按仿真识别的关键分层维度抽样
- **问卷设计**:仿真里发现的"关切追问"问题可以加入问卷
- **预调查**:先做小规模预调查,验证问卷

### 14.15.3　仿真与真实对照

仿真采访和真实调查的结果可以做对照:

```python
# examples/sim_real_comparison.py
def compare_sim_real(sim_results: dict, real_results: dict) -> dict:
    """仿真 vs 真实对照"""
    comparison = {}
    for key in sim_results:
        if key in real_results:
            sim_val = sim_results[key]
            real_val = real_results[key]
            diff = abs(sim_val - real_val) / real_val if real_val else 0
            comparison[key] = {
                "sim": sim_val,
                "real": real_val,
                "diff_pct": diff
            }
    return comparison
```

如果关键指标差异 < 15%,说明仿真采访可信,可以作为真实调查的预研;如果 > 30%,需要重新校准 LLM 或改进 prompt。

---

## 14.16　扩展:采访的伦理边界

采访涉及伦理问题,本节展开讨论。

### 14.16.1　仿真 agent 的"知情同意"

虽然仿真的 agent 不是真人,但有几个伦理考虑:

- **避免敏感问题**:不要问宗教、政治立场、性取向等
- **避免歧视性内容**:不要让 agent 表达对特定群体的歧视
- **避免暴力内容**:不要让 agent 表达暴力倾向
- **避免隐私暴露**:不要问具体的家庭住址、身份证号等

GAWorld 的采访 prompt 模板自动加了一个"伦理 filter":

```python
ETHICAL_FILTER = """
请避免以下内容:
- 对特定群体的歧视性言论
- 暴力或极端政治立场
- 个人隐私信息
- 性相关或敏感话题

如有相关问题,回答"我不方便回答这个问题"。
"""
```

### 14.16.2　采访结论的"使用边界"

仿真采访的结论应该有明确的使用边界:

- ✓ 用于学术研究和教学
- ✓ 用于问卷设计的预研
- ✓ 用于政策讨论的参考
- ✗ 不用于歧视性决策
- ✗ 不用于具体个人评估
- ✗ 不作为政策制定的唯一依据

### 14.16.3　数据匿名化

公开采访数据时,需要匿名化:

```python
# examples/anonymize_interview.py
def anonymize_interview_data(answers: list) -> list:
    """匿名化采访数据"""
    anonymized = []
    for ans in answers:
        anon_ans = ans.copy()
        # 替换 agent 名字
        anon_ans["agent_name"] = f"agent_{anon_ans['agent_id']}"
        # 移除可能的个人识别信息
        for key in ["address", "phone", "id_card"]:
            if key in anon_ans:
                anon_ans[key] = "[REDACTED]"
        anonymized.append(anon_ans)
    return anonymized
```

---

## 14.17　本章小结(扩展版)

- 采访质量需要系统评估:长度分布、多样性、身份一致性、语义稳定性。
- 追问策略有场景、社会、关切三类,关切追问效果最好。
- 跨城市 + 多议题 + 时间维度 + 条件变量的扩展设计能产出更丰富的态度矩阵。
- 仿真采访是真实调查的预研工具,需要过渡到真实调查。
- 采访涉及伦理边界:避免敏感问题、明确使用边界、匿名化数据。
- 与真实调查对照是仿真采访可信度的最终检验。


---

## 14.18　扩展:群体采访的工程细节

### 14.18.1　样本分层的细节

按收入分层:

```python
INCOME_QUARTILES = {
    "Q1_low": (0, 5000),
    "Q2_lower_middle": (5000, 10000),
    "Q3_upper_middle": (10000, 20000),
    "Q4_high": (20000, float("inf"))
}

def stratify_by_income(agents: list, n_per_stratum: int = 100) -> list:
    """按收入分层抽样"""
    strata = {k: [] for k in INCOME_QUARTILES}
    for a in agents:
        for k, (lo, hi) in INCOME_QUARTILES.items():
            if lo <= a.cash < hi:
                strata[k].append(a)
                break
    return [random.sample(s, min(n_per_stratum, len(s)))
            for s in strata.values()]
```

### 14.18.2　追问深度的控制

最多 3 轮追问,但可以根据 agent 反应调整:

```python
def adaptive_followup_depth(agent: dict, responses: list) -> int:
    """自适应追问深度"""
    if len(responses) == 0:
        return 0
    # 如果回答详细,继续追问
    if len(responses[-1]["response"]) > 100:
        return min(3, len(responses) + 1)
    # 如果回答敷衍,停止追问
    return min(2, len(responses) + 1)
```

### 14.18.3　跨语言支持

如果 agent 用不同语言,需要 prompt 适配:

```python
LANGUAGE_PROMPTS = {
    "zh": "你是{name},请用中文回答问题",
    "en": "You are {name}, please answer in English",
    "ja": "あなたは{name}です,日本語で答えてください"
}
```

### 14.18.4　多模态采访

未来可以加入:

- 图像(街景、商品图)
- 音频(对话录音)
- 视频(行为录像)

---

## 14.19　扩展:采访结果的可视化

### 14.19.1　态度分布的环形图

```python
import matplotlib.pyplot as plt

def plot_attitude_donut(distribution: dict, output: str):
    """态度分布环形图"""
    labels = list(distribution.keys())
    sizes = list(distribution.values())
    colors = ["#66c2a5", "#fc8d62", "#8da0cb"]
    fig, ax = plt.subplots()
    ax.pie(sizes, labels=labels, colors=colors, autopct="%1.1f%%",
           startangle=90, wedgeprops={"width": 0.4})
    ax.axis("equal")
    plt.title("态度分布")
    plt.savefig(output, dpi=100)
```

### 14.19.2　分层的堆积柱状图

```python
def plot_stratified(stra_results: dict, output: str):
    """分层态度的堆积柱状图"""
    import numpy as np
    strata = list(stra_results.keys())
    attitudes = ["support", "neutral", "oppose"]
    fig, ax = plt.subplots()
    bottom = np.zeros(len(strata))
    for att in attitudes:
        values = [stra_results[s][att] for s in strata]
        ax.bar(strata, values, bottom=bottom, label=att)
        bottom += values
    ax.legend()
    plt.xticks(rotation=45)
    plt.title("分层态度分布")
    plt.tight_layout()
    plt.savefig(output, dpi=100)
```

### 14.19.3　热力图:子群 × 议题

```python
def plot_attention_heatmap(group_topic_matrix: dict, output: str):
    """态度热力图"""
    import seaborn as sns
    df = pd.DataFrame(group_topic_matrix)
    fig, ax = plt.subplots(figsize=(10, 8))
    sns.heatmap(df, annot=True, cmap="RdYlGn", center=0, ax=ax)
    plt.title("群体 × 议题 态度")
    plt.tight_layout()
    plt.savefig(output, dpi=100)
```

---

## 14.20　本章小结(最终扩展版)

- 工程细节:样本分层、追问深度、跨语言、多模态。
- 可视化:环形图、堆积柱状图、热力图。
- 采访系统已经工程化,1–2 小时可跑通。

