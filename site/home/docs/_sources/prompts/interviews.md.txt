# 访谈问答提示词

群体采访将“一个受访者回答一个问题”作为一次模型调用。提示词包含受访者资料、背景、此前问答、随题材料和当前题目的输出要求。它适合问卷、连续追问，以及对不同居民群体的观点比较。

实际操作见 [访谈与群体采访](../interviews.md)。本章说明题目如何变成模型输入，以及回答怎样进入报告。

## 从问题到统计的代码结构

```text
interview/schema.py       Question 定义题型、选项与附件
         ↓
interview/local.py        准备居民或群体资料，连接模型
         ↓
interview/runner.py       按受访者与题目组织调用，传递问答历史
         ↓
interview/prompt.py       build_turn_prompt() → parse_answer()
         ↓
interview/aggregate.py    统计选项、覆盖率与分组结果；生成摘要
```

调用方通过 `persona` 传入资料。居民访谈的资料可包含档案和召回的记忆；群体受访者使用群体统计与描述。`build_turn_prompt()` 接收已经准备好的文本，按照题型组装当前问题。

## 三种题型与完整模板

以下均使用同一个虚构居民与公交末班车教学场景。示例文本直接由 `build_turn_prompt()` 生成，可复制或下载。

### 开放题：了解经历和理由

设置 `kind="open"`，模型以 `{"answer": "..."}` 返回回答。适合收集具体经历、解释和建议；报告展示回答并可生成摘要。

```{raw} html
<details class="prompt-details"><summary>查看开放题的完整提示词</summary>
```

```{literalinclude} ../_static/prompts/interview-open.txt
:language: text
```

```{raw} html
</details>
```

### 选择题：比较明确选项

设置 `kind="choice"` 并填写 `options`；`multi=False` 为单选，`True` 为多选。模型返回 `choice` 数组和 `reason`。解析器将回答与声明的选项匹配，统计使用匹配后的标签。

```{raw} html
<details class="prompt-details" open><summary>查看单选题的完整提示词</summary>
```

```{literalinclude} ../_static/prompts/interview-choice.txt
:language: text
```

```{raw} html
</details>
```

### 是非题：收集明确立场

设置 `kind="boolean"`，模型返回 `yes` 布尔值与 `reason`。这类题适合统计某项行为意愿或对明确命题的回答。

```{raw} html
<details class="prompt-details"><summary>查看是非题的完整提示词</summary>
```

```{literalinclude} ../_static/prompts/interview-boolean.txt
:language: text
```

```{raw} html
</details>
```

[下载开放题](../_static/prompts/interview-open.txt) · [下载选择题](../_static/prompts/interview-choice.txt) · [下载是非题](../_static/prompts/interview-boolean.txt)

## 连续追问如何保留上下文

`runner.py` 将同一受访者已经完成的问答传入 `history`。模板加入“这次访谈里你已经说过的话”，并要求当前回答与此前内容衔接。选择题的已选选项和是非题的立场也会写入这段历史。

可以在安装 GAWorld 的 Python 环境中运行下面的例子，直接查看第二题的提示词：

```python
from gaworld.interview.prompt import build_turn_prompt, parse_answer
from gaworld.interview.schema import Question

q1 = Question(id="q1", text="你通常怎样回家？")
a1 = parse_answer('{"answer":"我通常坐公交回家。"}', q1)
q2 = Question(id="q2", text="末班车延后半小时会怎样影响你？")

prompt = build_turn_prompt(
    persona="你是林悦，在社区服务中心工作。",
    context="社区正在征求公交运营时间的调整意见。",
    question=q2,
    history=[(q1, a1)],
    turn_no=2,
    total=2,
)
print(prompt)
```

这个例子只组装文本。`a1` 是教学用的固定回答。实际采访由运行器逐题得到回答，访谈历史作为独立记录传递，居民的情景记忆由仿真自身管理。

## 网页与图片材料放在哪里

附件先由 `attachments.py` 解析成 `ResolvedMaterial`，再进入 `build_turn_prompt(material=...)`。网页正文放入“随问题提供的材料”；图片内容随支持图像的模型调用发送，正文标明材料编号和说明。使用文字说明代替图像时，提示词会标明“图片，仅有文字说明”，采访记录保留这一情况。

对比材料效果时，保持题目、选项和受访者一致，再改变材料。查看完整记录，确认该轮实际使用了图像还是文字说明。

## 回答如何进入报告

`parse_answer()` 生成 `Answer`，包括文本、选项或布尔值，以及 `unparsed` 标记。选项或立场能够识别的回答进入对应统计；未解析的回答保留在记录中，供检查原文和覆盖率。

摘要由 `aggregate.py` 中的 `_summary_prompt()` 另行构建，输入是已有回答样本和已计算的统计结果。题目统计由代码计算，摘要负责概括观点与分歧。阅读时把摘要与选项分布、有效回答数量一起看。

## 实际修改步骤

1. 在群体采访中填写背景、题目与选项。一次只问一个明确问题，选项保持清楚且可区分。
2. 要调整固定回答要求，修改 `prompt.py` 的 `_format_contract()`；要调整整段排列与历史内容，修改 `build_turn_prompt()` 或 `_history_block()`。
3. 保持 `answer`、`choice`、`yes`、`reason` 与解析器对应。改变输出结构时，更新 `parse_answer()` 和使用该结构的统计逻辑。
4. 先运行 {ref}`离线预览脚本 <offline-preview>`，再运行 `tests/test_interview_group_core.py`。检查选项匹配、追问历史和无效回答处理。

**单居民 CLI 访谈的入口另在 `generative_city_sim.py::interview_agent()`**：它将一组问题放在一次调用中，要求返回问答数组。调整群体采访模板时，按具体入口定位对应函数。

```{raw} html
<div class="prompt-source">源码：<a href="https://github.com/wuchaozju/GAWorld/blob/main/gaworld/interview/prompt.py">prompt.py</a> · <a href="https://github.com/wuchaozju/GAWorld/blob/main/gaworld/interview/runner.py">runner.py</a> · <a href="https://github.com/wuchaozju/GAWorld/blob/main/gaworld/interview/local.py">local.py</a> · <a href="https://github.com/wuchaozju/GAWorld/blob/main/gaworld/interview/aggregate.py">aggregate.py</a></div>
```
