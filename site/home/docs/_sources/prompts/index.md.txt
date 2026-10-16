# 提示词总览

GAWorld 用提示词把居民所处的环境、记忆和当前任务交给语言模型，再将回答接回仿真、访谈或研究流程。本模块从实际调用出发，说明每类提示词如何组成、在哪里修改，以及怎样检查修改后的结果。

```{raw} html
<div class="prompt-intro">
<p><strong>从一条提示词，读懂一次模型调用。</strong></p>
<p>先找到任务入口，再看上下文如何进入模板、模型要返回什么，以及代码如何使用这份回答。</p>
</div>
```

## 按任务查找

```{raw} html
<div class="prompt-routes">
  <div class="prompt-route"><a href="simulation.html">仿真认知 →</a><p>感知环境、规划行动、反思经历，以及日、月、年尺度的生活简报。了解居民如何接收信息并形成下一步行动。</p></div>
  <div class="prompt-route"><a href="interviews.html">访谈问答 →</a><p>开放题、选择题、是非题与连续追问。查看一段完整提示词，以及回答如何进入统计和摘要。</p></div>
  <div class="prompt-route"><a href="research.html">研究与实验 →</a><p>论文解读、研究方案、预注册协议、结果解释、政策推演与行为实验。定位各阶段的模板和输出字段。</p></div>
  <div class="prompt-route"><a href="editing.html">修改与验证 →</a><p>区分修改输入、修改模板和添加插件三种方式，离线预览提示词，再检查解析与实验可比性。</p></div>
</div>
```

## 一次调用的四个环节

```{raw} html
<ol class="prompt-flow" aria-label="提示词从输入到结果的流程">
<li><strong>1. 准备输入</strong><span>居民资料、环境、记忆，以及当前问题或研究材料。</span></li>
<li><strong>2. 组装提示词</strong><span>构建函数填入上下文，附上任务要求和输出格式。</span></li>
<li><strong>3. 调用模型</strong><span>调用层选择模型，并传递任务名、采样参数和输出预算。</span></li>
<li><strong>4. 处理回答</strong><span>解析字段、检查取值，再更新状态或生成研究记录。</span></li>
</ol>
```

构建函数通常位于各业务模块中，例如 `interview/prompt.py` 与 `research/protocol.py`。日常规划和反思的模板目前位于 `generative_city_sim.py`；模型调用公共入口是 `gaworld/llm/providers.py` 中的 `call_llm()`。

`task` 用于模型路由与调用记录，例如 `perception`、`planning`、`interview`。`prompt` 是主要文本；`system` 是调用方可单独指定的系统消息。具体调用是否设置 `system`，以该模块为准。需求估计实验显式构建 `system` / `user` 两段文本，感知和群体采访则将组装后的正文传入调用层。

## 拆开看一条访谈提示词

下面使用一位虚构居民和“公交末班车”教学场景。正文由仓库的 `build_turn_prompt()` 生成，右侧解释各段的作用。

```{raw} html
<div class="prompt-specimen" aria-label="访谈提示词及逐段注释">
<div class="prompt-specimen-head">开放题 · 单个居民 · 单次问答</div>
<div class="prompt-segment">
<pre>你是林悦，住在城西，每天乘公交去社区服务中心工作。

这是一次访谈。

回答要真实、具体，基于你自己的处境和经历，不要说教，也不要替别人代言。</pre>
<div class="prompt-annotation"><strong>身份与回答立场</strong>persona 提供受访者资料；模板规定以自己的处境和经历作答。实际群体采访由调用方准备居民或群体资料。</div>
</div>
<div class="prompt-segment">
<pre>【访谈背景】
社区正在征求公交末班车时间的调整意见。</pre>
<div class="prompt-annotation"><strong>本次访谈的共同背景</strong>context 交代受访者需要了解的情境。同一轮的共同说明可以放在这里。</div>
</div>
<div class="prompt-segment">
<pre>【问题】
目前的末班车时间对你的生活有什么影响？</pre>
<div class="prompt-annotation"><strong>当前问题</strong>question.text 决定这次问什么。每次调用处理一个问题；追问时另行加入此前的问答。</div>
</div>
<div class="prompt-segment">
<pre>【回答要求】
用 2-4 句话回答，说你自己的真实想法和经历，不要写成报告或列要点。
只输出 JSON：{"answer": "你的回答"}</pre>
<div class="prompt-annotation"><strong>输出约定</strong>question.kind 决定字段与题型。开放题读取 answer；选择题读取 choice；是非题读取 yes。</div>
</div>
<div class="prompt-specimen-caption">模板：gaworld/interview/prompt.py · 构建：build_turn_prompt() · 解析：parse_answer()</div>
</div>
```

[下载完整提示词](../_static/prompts/interview-open.txt) · [查看生成脚本](../_static/examples/preview-prompts.py) · [学习三种题型与连续追问](interviews.md)

## 从哪里修改

| 你想改变的内容 | 修改入口 | 继续阅读 |
| --- | --- | --- |
| 居民身份、问题、政策或事件内容 | 对应页面中的输入与资料 | {ref}`输入如何进入模板 <edit-inputs>` |
| 问答长度、角色要求、输出结构 | 业务模块中的提示词构建函数 | {ref}`模板与解析器一起检查 <edit-template>` |
| 感知阶段新增一段领域信息 | 插件的感知扩展钩子 | {ref}`通过插件添加上下文 <edit-plugin>` |
| 使用哪个模型、采样温度、输出预算 | 模型配置与调用参数 | [模型配置](../models.md) |

提示词调整会改变居民接收到的信息或模型作答方式。用于对照实验时，把模板版本、输入资料、模型和采样参数与实验记录一同保存，便于比较和复现。

## 本模块的源码入口

```text
generative_city_sim.py          规划、反思、单居民访谈及管线装配
gaworld/
├── sim/
│   ├── _cognition.py           环境感知
│   ├── _prompt.py              状态、历史与事件摘要辅助函数
│   └── _fastforward.py         日、月、年生活简报
├── skills/prompt_helpers.py    技能内容的提示词格式化
├── interview/prompt.py         群体采访的单题构建与解析
├── research/                   研究设计、协议、政策与推演
├── parallel/interpret.py       平行世界结果解读
├── experiments/                经典行为与需求估计实验
└── llm/providers.py            模型调用与路由
```

完整目录见 [代码结构](../code-structure.md)；要立即生成可阅读的提示词，进入 {ref}`离线预览 <offline-preview>`。
