# 第 7 章　语言模型作为仿真引擎

> 这一章解决"LLM 怎么让仿真有'人味'"的问题。我们讨论四个主题:为什么 LLM 改变了社会仿真、提示词工程的实操、可靠性与裁判偏置、成本控制。读完本章,读者应该能把一个用规则系统做的智能体升级为用 LLM 做的智能体,并理解其中的关键工程取舍。

---

## 7.1　LLM 为什么改变社会仿真

社会仿真在 2023 年之前的"行为单调"问题,被 LLM 一举缓解。我们来看三个具体场景,对比规则系统和 LLM 系统。

**场景一:收到朋友借钱信息**

规则系统的反应:

```
IF intimacy > 0.5 AND cash > 5000:
    return "同意"
ELIF obligation > 0.7 AND cash > 1000:
    return "同意"
ELSE:
    return "拒绝"
```

LLM 系统的反应(同样输入):

```
"老张突然找我借 5000,我有点为难。他最近确实手头紧,但上次借
的还没还。借吧伤财,不借又怕伤感情。我想先问问他为什么急,
再决定要不要借。能拖几天最好拖几天。"
```

三个对比维度:

1. **行为丰富度**:规则系统输出"同意"或"拒绝",LLM 输出包含情绪、犹豫、策略、条件。
2. **真实性**:LLM 的反应像"真人在犹豫",规则系统的反应像"机器在判断"。
3. **可解释性**:规则系统的判断路径可以追,LLM 的判断路径在神经网络里。

> **教学要点**:LLM 改变了社会仿真,但没有替代规则系统。第 4 章的四象限分析仍然适用——日常行为用规则,关键决策用 LLM。

LLM 改变社会仿真有四个具体机制:

**机制一:行为涌现**。LLM 在大量对话数据上训练,本身已经隐含了"人在不同情境下的反应分布"。当我们用一个合适的人设 prompt 调用它,它的反应不再像"机器",而像"受过某种教育的某类人"。

**机制二:意义建构**。LLM 能处理"这件事对我意味着什么"这种问题——前面例子里"借吧伤财,不借又怕伤感情"是典型的意义建构,这是规则系统做不到的(2.3 节说"意义建构不可计算",LLM 逼近了它)。

**机制三:复杂推理**。LLM 能进行多步推理——"如果借,后果是……;如果不借,后果是……;综合权衡,我倾向于……"这是规则系统需要手工编码的复杂推理,LLM 自动完成。

**机制四:语言生成**。LLM 的输出是自然语言,可以直接被居民"说出"或"写下",这让"对话式仿真""采访式仿真"成为可能。

但 LLM 也有四个明确的局限:

**局限一:幻觉**(hallucination)。LLM 会编造事实——它说"我上周和老张吃过饭",但上周它根本不存在。这是仿真里最大的可信度问题,需要严格的解析校验。

**局限二:训练偏见**。LLM 的训练数据带偏见,主要是英语、北美、都市中产视角。仿真东亚、非洲、传统社区需要谨慎校正。

**局限三:行为不稳定**。同一 prompt、同一时刻,LLM 可能给出不同答案。这破坏了"可复现性"。

**局限四:成本高**。一次 LLM 调用比一次规则计算贵几个数量级。1000 个居民 × 24 小时 × 每小时几次决策 = 一万次 LLM 调用,成本可能上百元。

> **核心认识**:LLM 是仿真引擎的"升级",不是"替代"。读者需要把它当成"高级但昂贵的决策函数",在使用中权衡成本和真实感。

---

## 7.2　提示词工程:四段式

LLM 的决策质量,80% 取决于提示词(prompt)写得好不好。GAWorld 用的提示词模板经过长期迭代,总结为**四段式**:

```
[1] 身份(Identity):你是谁?
[2] 处境(Contention):你面对什么情况?
[3] 选项(Options):你能做什么?
[4] 格式(Format):你该怎么回答?
```

一个完整的提示词示例:

```
[1 身份]
你是林素,34 岁女性,绍兴柯桥的社区医生。本科毕业,已婚,有一个 5 岁的孩子。
你性格偏外向(N=2.1,E=2.5),社交活跃,做事有条理(C=3.1)。
当前月收入 18000 元,储蓄 12 万元,无车。丈夫是教师,孩子在上幼儿园。

[2 处境]
今天 2026-09-26,周六上午 9 点。你昨晚和朋友吃饭时收到一条消息:
"明天我们打算去杭州西湖一日游,我和老公两个孩子,要不要一起?"
发送者是你大学同学王萍,关系亲密度 0.7,你最近没怎么联系她。
你今天的天气是晴,温度 22℃,无风。

[3 选项]
- 接受邀请,明天去杭州
- 婉拒,说明最近忙
- 婉拒,但约改期
- 婉拒,不解释

[4 格式]
请按以下 JSON 输出你的决策:
{
    "decision": "接受"/"婉拒"/"婉拒并改期"/"婉拒不解释",
    "reasoning": "100 字以内的理由",
    "reply_message": "你要发给王萍的消息原文"
}
```

这段提示词做了几件关键事:

1. **身份具体化**:不只说"你是一个人",而是说"你是林素,34 岁,社区医生,外向性 2.5"。这让 LLM 在生成反应时有"具体的人"可参考。
2. **处境完整化**:不只是"你收到邀请",而是包括时间、天气、关系背景、近期互动史。这给 LLM 足够的决策信息。
3. **选项明确化**:不让 LLM 自由发挥,而是给出 4 个候选选项。这降低了"幻觉"概率。
4. **格式约束化**:强制 JSON 输出,让解析程序可以直接读。这避免了"自然语言返回难解析"的问题。

> **提示词调优经验**:改一个字段往往要重新测试。GAWorld 的提示词模板由一个 7 人的内容团队维护,每次改动都要跑 50+ 测试用例验证效果。

### 一个提示词的"最小 vs 最大"

最小提示词(适合快速实验):

```
你是林素,34 岁医生。收到朋友王萍的杭州一日游邀请。你决定怎么做?
```

最大提示词(适合生产环境):

```
你是林素,34 岁女性,绍兴柯桥的社区医生。本科毕业,已婚,有一个 5 岁的孩子。
你性格偏外向,社交活跃。收入 18000,储蓄 12 万。丈夫是教师,孩子上幼儿园。
今天是 2026-09-26 周六上午 9 点,昨晚收到大学同学王萍(亲密度 0.7,最近未联系)
的微信:"明天我们打算去杭州西湖一日游,我和老公两个孩子,要不要一起?"
天气晴,22℃。

请从以下选项中选择:
A. 接受 B. 婉拒 C. 婉拒并改期 D. 婉拒不解释
按 JSON 输出 {"decision": ..., "reasoning": ..., "reply_message": ...}
```

经验法则:**最小提示词用于验证假设,最大提示词用于生产环境**。读者做研究时,建议先写最小版验证"这件事仿真能不能做",再扩到最大版用于正式实验。

---

## 7.3　可靠性:温度、结构化输出、重试

LLM 决策不可靠,需要工程化处理。GAWorld 用四个机制:

**机制一:温度**(temperature)。LLM 的随机性控制。温度=0 给出最确定的答案,温度=1 给出最随机的答案。GAWorld 默认日常决策温度=0.3,采访决策温度=0(追求稳定),灾害反应温度=0.7(追求多样性)。

**机制二:结构化输出**(structured output)。强制 LLM 输出 JSON。OpenAI 的 function calling、Anthropic 的 tool use 都是这个机制。代码示例:

```python
# examples/llm_call.py
from openai import OpenAI
import json

client = OpenAI()

tools = [{
    "type": "function",
    "function": {
        "name": "make_decision",
        "description": "智能体决策函数",
        "parameters": {
            "type": "object",
            "properties": {
                "decision": {"type": "string", "enum": ["接受", "婉拒", "婉拒并改期"]},
                "reasoning": {"type": "string"},
                "reply_message": {"type": "string"}
            },
            "required": ["decision", "reasoning", "reply_message"]
        }
    }
}]

response = client.chat.completions.create(
    model="gpt-4",
    messages=[
        {"role": "system", "content": "你是林素,34 岁社区医生..."},
        {"role": "user", "content": "王萍邀请明天去杭州"}
    ],
    tools=tools,
    tool_choice={"type": "function", "function": {"name": "make_decision"}},
    temperature=0.3
)

# 解析结构化输出
decision = json.loads(response.choices[0].message.tool_calls[0].function.arguments)
print(decision)
# → {"decision": "婉拒并改期", "reasoning": "...", "reply_message": "..."}
```

**机制三:重试**(retry)。LLM 偶尔会返回格式不对的 JSON、给出"我无法回答"、或者其他异常。GAWorld 对每次调用最多重试 3 次,失败后用启发式回退(例如"如果 LLM 失败,默认接受,因为大部分情况下接受是合理选择")。

**机制四:解析校验**(validation)。即便 LLM 返回了 JSON,也要校验——决策是否在枚举里?reasoning 是否超过长度上限?reply_message 是否包含敏感词?GAWorld 的解析校验器有 20+ 条规则。

这四个机制让 LLM 决策从"魔法"变成"工程"——读者在自己的仿真里,至少要实现前两个(温度、结构化输出),否则结果会很乱。

---

## 7.4　LLM-as-judge 与裁判偏置

社会仿真里另一个常用模式是**让 LLM 做裁判**——比如采访结束后让 LLM 判断"这个回答是支持还是反对限行令"。这种用法便宜,但有明显偏置。

**裁判偏置**(judge bias)的四个常见来源:

**来源一:位置偏置**。LLM 倾向给"放在前面的"选项更高分。一个政策态度问卷,如果把"支持"放在选项第一位,LLM 评分时会偏向"支持",即使回答者本身是反对的。

**来源二:长度偏置**。LLM 倾向给"更长的"回答更高分。这对开放式采访很危险——受访者写得多,不一定意味着答得好。

**来源三:权威偏置**。LLM 倾向给"看起来更权威"的回答更高分。一个措辞职业化的回答,会得高分,即使内容空洞。

**来源四:确认偏置**。LLM 倾向给"和给定答案一致"的回答更高分。如果 prompt 里写"采访目的是了解居民支持率",LLM 评分时会偏向"支持",因为它在确认 prompt 的暗示。

代码示例:用 LLM 做裁判的一个简单实现。

```python
# examples/judge.py
from openai import OpenAI
client = OpenAI()

def judge_answer(question: str, answer: str) -> str:
    """LLM 裁判:判断回答是支持、反对、还是中立"""
    response = client.chat.completions.create(
        model="gpt-4",
        messages=[
            {"role": "system", "content": "你是一个中立的政策态度评估员。"},
            {"role": "user",
             "content": f"问题: {question}\n回答: {answer}\n"
                        f"请判断回答的态度是支持、反对、还是中立。"
                        f"只输出一个词:支持/反对/中立"}
        ],
        temperature=0,
    )
    return response.choices[0].message.content.strip()

print(judge_answer("你支持加征拥堵费吗?", "我觉得不行,会伤到中产"))
# → "反对"
```

### 应对裁判偏置的四个工程手段

**手段一:多裁判投票**。让 3 个 LLM(可以是不同模型或同模型不同 prompt)分别评分,少数服从多数。这能消除单一模型的随机偏置。

**手段二:打乱顺序**。如果 LLM 在评多个选项,随机化选项顺序。这能消除位置偏置。

**手段三:提供参考样例**。在 prompt 里给几个"标准答案—评分"对照,让 LLM 学习评分标准。这能减少确认偏置。

**手段四:人类抽样校验**。从 LLM 评分中抽 5%,让人工校验。这是最可靠的,但成本高。

GAWorld 的采访功能(`gaworld/interview/`)在评分时默认启用手段一(多裁判) + 手段三(参考样例)。第 14 章的群体采访案例会演示这套机制。

---

## 7.5　成本控制:路由、缓存、批处理、本地化

LLM 调用贵,大规模仿真必须控制成本。GAWorld 用四个手段:

**手段一:路由**(routing)。不同任务用不同模型。日常决策用便宜的小模型(gpt-4o-mini),采访分析用贵的强模型(gpt-4),灾害反应用中间模型。

```yaml
# config/llm_routing.yaml
tasks:
  daily_decision: gpt-4o-mini     # 便宜
  interview_analysis: gpt-4        # 强
  disaster_response: gpt-4o        # 中
```

**手段二:缓存**(caching)。同样的 prompt 多次出现时,缓存结果。但仿真里 prompt 几乎不会完全重复(状态、记忆在变),所以缓存命中率较低——通常 5–15%。

**手段三:批处理**(batching)。把多个智能体的决策请求合并成一次 LLM 调用。

```python
# 把 10 个智能体的决策合并
agents = [agent1, agent2, ..., agent10]
batch_prompt = "\n---\n".join([
    f"[{a.name}] {a.current_state}: 决定?"
    for a in agents
])
# 一次 LLM 调用返回 10 个决策
# → 大幅节省成本
```

**手段四:本地化**(local deployment)。用开源模型(Ollama、vLLM)在本地跑,边际成本为零。但本地模型的能力通常不如 GPT-4,行为真实性会下降。

> **成本现实**:一个 1000 人 × 30 天的中规模仿真,用 GPT-4 跑大约 1.5 万元;用 GPT-4o-mini 跑大约 1500 元;用本地 7B 模型跑大约 50 元(电费)。读者要根据自己的预算选择。

### 一个成本估算工作流

做仿真前,先估算成本:

1. 确定仿真规模:人数 × 天数 × 每 tick 决策数
2. 估算 LLM 调用总数
3. 估算单次调用 token 数(prompt + response)
4. 按模型定价计算总成本
5. 如果超预算,考虑:**减少决策频次**(每 4 小时决策一次)、**简化 prompt**(更短)、**用便宜模型**(小模型)

GAWorld 的 `--fast-forward` 和 `--sim-years` 都是为了压缩仿真规模、控制成本。

---

## 7.6　代码示例:一个最小 LLM 决策函数

把 7.1–7.5 节的内容整合起来,写一个"最小 LLM 决策函数"。这段代码没有真实调用 LLM(避免依赖),但展示了完整结构。

```python
# examples/mini_llm_decision.py
from dataclasses import dataclass
from typing import Optional
import json
import random

# 模拟 LLM 调用(没有真实 API)
def mock_llm_call(prompt: str, temperature: float = 0.3) -> dict:
    """模拟 LLM 返回。真实场景换成 OpenAI/Anthropic 调用"""
    decisions = ["接受", "婉拒并改期", "婉拒", "婉拒不解释"]
    reasonings = [
        "我本来就想去杭州走走,而且孩子也需要户外活动",
        "我最近在赶论文,但下周应该可以,改期更好",
        "今天太累了,周末想在家休息",
        "我和王萍好久没联系,不想太尴尬"
    ]
    return {
        "decision": random.choices(decisions, weights=[0.3, 0.4, 0.2, 0.1])[0],
        "reasoning": random.choice(reasonings),
        "reply_message": "我们改约下周末吧!",
        "_meta": {"temperature": temperature, "model": "mock"}
    }

@dataclass
class AgentForLLM:
    name: str
    age: int
    job: str
    personality: str
    cash: float
    intimacy_with_friend: float

def make_decision_with_llm(agent: AgentForLLM, situation: str,
                           options: list, temperature: float = 0.3) -> dict:
    """用 LLM 做决策的完整流程"""
    # 1. 构造提示词(四段式)
    identity = f"你是{agent.name},{agent.age}岁{agent.job}。" \
               f"性格:{agent.personality}。现金:{agent.cash}元。" \
               f"与邀请方亲密度:{agent.intimacy_with_friend:.2f}。"
    contention = f"情况:{situation}"
    option_str = "选项:" + " ".join([f"{chr(65+i)}. {o}" for i, o in enumerate(options)])
    format_str = '输出 JSON: {"decision": ..., "reasoning": "...", "reply_message": "..."}'

    prompt = f"{identity}\n{contention}\n{option_str}\n{format_str}"

    # 2. 调用 LLM
    response = mock_llm_call(prompt, temperature)

    # 3. 解析 + 校验
    assert response["decision"] in options, f"决策不在选项中: {response['decision']}"
    assert len(response["reasoning"]) < 200, "reasoning 太长"

    # 4. 重试机制(伪代码)
    # try:
    #     response = real_llm_call(prompt, temperature)
    # except:
    #     response = heuristic_fallback()
    #     log_warning("LLM 调用失败,使用启发式回退")

    return response

# 跑一个例子
agent = AgentForLLM("林素", 34, "社区医生",
                    personality="外向、社交活跃、做事有条理",
                    cash=12000,
                    intimacy_with_friend=0.7)
result = make_decision_with_llm(
    agent,
    situation="大学同学王萍邀请明天去杭州一日游",
    options=["接受", "婉拒", "婉拒并改期", "婉拒不解释"]
)
print(json.dumps(result, ensure_ascii=False, indent=2))
```

这段代码展示了 LLM 决策的完整流程:身份 + 处境 + 选项 + 格式 → LLM 调用 → 解析校验 → 输出决策。真实的 GAWorld 在这个流程上还加了**多裁判投票、批处理、缓存、本地化路由**等机制。

---

## 7.7　本章小结

- LLM 改变了社会仿真,带来行为涌现、意义建构、复杂推理、语言生成四个机制,同时有幻觉、偏见、不稳定、成本四个局限。
- 提示词工程的核心是"四段式":身份、处境、选项、格式。最小提示词用于验证,最大提示词用于生产。
- LLM 决策的可靠性靠四个机制保障:温度控制、结构化输出、重试、解析校验。
- LLM-as-judge 有四个常见偏置:位置、长度、权威、确认,工程上用多裁判、打乱顺序、参考样例、人工抽样应对。
- 成本控制有四种手段:路由、缓存、批处理、本地化。1000 人 30 天仿真,GPT-4 约 1.5 万元,GPT-4o-mini 约 1500 元,本地 7B 约 50 元。
- 一个 LLM 决策函数 = 提示词构造 + LLM 调用 + 解析校验 + 重试回退。

---

## 7.8　思考题

1. **写一个最小提示词和一个最大提示词**,针对"今天要不要加班"这个决策。最小提示词 ≤ 50 字,最大提示词 ≥ 300 字。
2. **为限行令案例设计一个 LLM 决策函数**:智能体是 35 岁上班族,需要决定明天是否开车上班。提示词怎么写?温度设多少?选项怎么列?
3. **设计一个 LLM-as-judge 的校验方案**:评估 50 个居民对"加征拥堵费"的回答。用什么样的多裁判 + 参考样例 + 抽样比例?
4. (进阶)**估算你自己的仿真项目成本**:人数 × 天数 × 决策频次 × 单次成本。预算多少?用哪个模型?

---

## 7.9　延伸阅读

1. Park, J. S., et al. (2023). Generative Agents: Interactive Simulacra of Human Behavior. *arXiv:2304.03442*. —— LLM 智能体的范式论文。
2. Wei, J., et al. (2022). Chain-of-Thought Prompting Elicits Reasoning in Large Language Models. *NeurIPS 2022*. —— 思维链提示词,让 LLM 做多步推理。
3. Brown, T. B., et al. (2020). Language Models are Few-Shot Learners. *NeurIPS 2020*. —— GPT-3 的论文,讨论 few-shot prompting。
4. Zheng, L., et al. (2023). Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena. *NeurIPS 2023*. —— LLM-as-judge 的偏置研究。
5. Kojima, T., et al. (2022). Large Language Models are Zero-Shot Reasoners. *NeurIPS 2022*. —— 零样本推理,提示词里加"让我们一步一步思考"。
6. GAWorld 工程文档:`gaworld/llm/providers.py`、`gaworld/cognition/realism.py`。
7. Bubeck, S., et al. (2023). Sparks of Artificial General Intelligence: Early Experiments with Large Language Models. *arXiv:2303.12712*. —— GPT-4 的能力边界。
8. Anthropic 文档:Claude 的 tool use / function calling 规范。
9. OpenAI 文档:GPT-4o mini 的 cost optimization 指南。

---

> **本章教学注释**
>
> 这一章是技术层第四章,也是 GAWorld 最具特色的部分——LLM 路由是 GAWorld 的核心创新。如果读者在做仿真时遇到了"行为单调"问题,本章应该能提供解决思路。但要警惕:LLM 不是万能药,前面 4 章讲的规则系统、社会网络、经济机制仍然是仿真的"骨架",LLM 是"血肉"。
>
> 7.6 节的代码故意不依赖真实 LLM API,目的是让读者在没有 API key 的情况下也能理解完整流程。读者在生产环境里,只需要把 `mock_llm_call` 替换成真实的 OpenAI/Anthropic 调用即可。
>
> 7.5 节的成本现实非常重要——读者在规划仿真项目时,**必须**先估算成本。第 8 章会讲仿真运行系统(时钟、并行、守恒),那是降低成本的另一条路径。下一章我们进入"运行系统"。
---

## 7.10　扩展:LLM 仿真引擎的深度优化

LLM 调用是社会仿真里最贵的部分。本节讨论深度优化策略。

### 7.10.1　模型路由的精细化

不同任务用不同模型,而不是所有都用 GPT-4:

```python
# examples/model_routing.py
ROUTING = {
    "daily_decision": {
        "model": "gpt-4o-mini",
        "rationale": "日常决策量大、容错率高"
    },
    "interview_analysis": {
        "model": "gpt-4",
        "rationale": "采访分析需要细致理解"
    },
    "disaster_response": {
        "model": "gpt-4o",
        "rationale": "灾害反应需要平衡真实感和稳定性"
    },
    "summary_generation": {
        "model": "gpt-4o-mini",
        "rationale": "总结任务对模型要求低"
    }
}
```

### 7.10.2　批处理的极限优化

把多个请求合并为一次调用:

```python
# examples/batch_optimization.py
def batch_decide(agents: list, situation: str, options: list) -> dict:
    """批量决策:一次 LLM 调用返回所有 agent 的决策"""
    batch_prompt = "\n\n".join([
        f"Agent {i} ({a.name}): {a.state}\n请从 {options} 中选一个决策。"
        for i, a in enumerate(agents)
    ])
    response = call_llm(batch_prompt, n_expected=len(agents))
    return parse_batch_response(response, agents)
```

### 7.10.3　缓存的精细化

除了简单的 prompt 缓存,还可以:

```python
# examples/advanced_cache.py
import hashlib

def cache_key(prompt: str, model: str, temperature: float) -> str:
    """缓存键"""
    content = f"{model}|{temperature}|{prompt}"
    return hashlib.sha256(content.encode()).hexdigest()

def cached_llm_call(prompt: str, model: str, temperature: float) -> str:
    """带缓存的 LLM 调用"""
    key = cache_key(prompt, model, temperature)
    if key in CACHE:
        return CACHE[key]
    response = call_llm(prompt, model=model, temperature=temperature)
    CACHE[key] = response
    return response
```

### 7.10.4　异步与并行

多个 LLM 调用可以并行:

```python
# examples/async_llm.py
import asyncio

async def parallel_llm_calls(prompts: list) -> list:
    """异步并行 LLM 调用"""
    tasks = [call_llm_async(p) for p in prompts]
    return await asyncio.gather(*tasks)
```

并行能把 LLM 调用时间从 O(N) 降到 O(1)。

---

## 7.11　扩展:LLM 仿真的可信度建设

LLM 仿真的可信度需要系统建设。

### 7.11.1　多模型对照

不同 LLM 给出不同结果,但**一致性高**的部分可信:

```python
# examples/multi_model.py
def multi_model_consensus(prompt: str, models: list = ["gpt-4", "claude-3", "gemini-1.5"]) -> dict:
    """多模型对照"""
    results = {}
    for model in models:
        results[model] = call_llm(prompt, model=model)
    # 计算一致性
    common = intersection(*[set(r.split()) for r in results.values()])
    return {
        "results": results,
        "consistency": len(common) / max(len(r.split()) for r in results.values())
    }
```

### 7.11.2　一致性测试

同一 prompt 跑 10 次,看输出分布:

```python
# examples/consistency_test.py
def consistency_test(prompt: str, n_runs: int = 10) -> float:
    """一致性测试"""
    outputs = [call_llm(prompt, temperature=0) for _ in range(n_runs)]
    # 计算 pairwise similarity
    sims = []
    for i in range(n_runs):
        for j in range(i+1, n_runs):
            sims.append(string_similarity(outputs[i], outputs[j]))
    return sum(sims) / len(sims)
```

如果一致性 < 0.7,说明 LLM 输出不稳定,需要换模型或降低温度。

### 7.11.3　偏置检测

LLM 的偏置需要系统检测:

```python
# examples/bias_detection.py
def detect_position_bias(answers: list) -> float:
    """位置偏置检测"""
    first_support = sum(1 for a in answers if a["position"] == 0 and a["judgment"] == "support")
    last_support = sum(1 for a in answers if a["position"] == -1 and a["judgment"] == "support")
    return abs(first_support / sum(1 for a in answers if a["position"] == 0) -
               last_support / sum(1 for a in answers if a["position"] == -1))
```

### 7.11.4　prompt 版本管理

LLM 仿真里 prompt 的微小变化可能导致结果差异巨大:

```python
# examples/prompt_versioning.py
PROMPT_VERSIONS = {
    "v1.0": "你是{agent_name},请决定...",
    "v1.1": "你是{agent_name},{age}岁,请决定...",
    "v2.0": "身份:{identity}\\n\\n处境:{situation}\\n\\n选项:{options}",
}

# 每次跑仿真都用同一个 prompt 版本
PROMPT_VERSION = "v2.0"
```

---

## 7.12　扩展:LLM 仿真的伦理与责任

LLM 仿真带来新的伦理问题,本节展开讨论。

### 7.12.1　幻觉的责任

LLM 可能编造事实:

- "我上周和老张吃饭"——但上周它不存在
- "我的家在绍兴"——但实际住址可能是杭州

应对:

- 在 prompt 里明确"这是仿真,不是真实"
- LLM 输出加事实校验
- 对编造的回答降权或过滤

### 7.12.2　训练偏见的责任

LLM 训练数据带有偏见:

- 地域(北美主导)
- 文化(西方主流)
- 价值观(自由主义)

应对:

- 在 prompt 里强调本地化背景
- 用文化特定的模型
- 明确说明"这是基于通用训练的输出,可能不完全符合本地情况"

### 7.12.3　决策透明性

LLM 决策不可解释:

- 用户问"为什么这样决定",LLM 给不出真实理由
- 仿真结果可能被解读为"有理由",但实际上没有

应对:

- 在论文里明确"这是 LLM 决策,不是基于规则的推理"
- 提供 prompt 模板,让读者能复现
- 用多模型对照,提供决策的"区间估计"而不是"点估计"

### 7.12.4　使用边界

LLM 仿真结论的使用边界:

- ✓ 用于学术研究和教育
- ✓ 用于预研和方向探索
- ✗ 不用于歧视性决策
- ✗ 不用于关键政策制定
- ✗ 不替代真实数据研究

---

## 7.13　扩展:LLM 仿真的未来方向

### 7.13.1　更大的上下文窗口

2026 年 LLM 上下文窗口已达到 1M+ token。这让仿真可以做更复杂的决策:

- 一次性输入整个城市的 1000 个 agent 状态
- 长时段记忆(过去 1 年的事件)
- 复杂的社会情境

### 7.13.2　多模态融合

多模态 LLM 让仿真能处理:

- 图像(街景、商品图)
- 音频(对话录音)
- 视频(监控画面)

### 7.13.3　Agent-as-Tool

未来可能的方向:

- LLM 调用其他 LLM
- LLM 调用外部数据库
- LLM 调用物理设备(机器人)

### 7.13.4　联邦学习 + 隐私

如果要做"基于真实数据的 LLM 训练":

- 联邦学习避免数据集中
- 差分隐私保护个体隐私
- 同态加密保护数据安全

### 7.13.5　可解释 LLM

未来 LLM 可能自带"决策解释":

- 不只给决策,还给出"为什么"
- 类似思维链(Chain-of-Thought)
- 让用户能审计每个决策

---

## 7.14　本章小结(扩展版)

- LLM 仿真引擎的深度优化包括模型路由、批处理、缓存、异步并行。
- 可信度建设需要多模型对照、一致性测试、偏置检测、prompt 版本管理。
- 伦理与责任:幻觉、训练偏置、决策透明性、使用边界。
- 未来方向:更大上下文窗口、多模态、Agent-as-Tool、联邦学习、可解释 LLM。
- LLM 是社会仿真的"血肉",但规则系统仍然是"骨架",两者缺一不可。

