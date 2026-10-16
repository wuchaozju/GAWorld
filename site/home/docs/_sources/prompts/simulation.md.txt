# 仿真认知提示词

仿真提示词把居民的生活处境转成当前需要处理的任务：感知环境、形成计划、反思结果，或概括一段时间的生活。读这一章，可以找到各阶段的输入、输出与模板位置，并在扩展仿真时选择合适的入口。

## 日内认知如何衔接

`gaworld/sim/pipeline.py` 定义阶段顺序，`generative_city_sim.py` 装配各阶段。下图抽出与认知提示词直接相关的环节；完整管线还包括移动、动作选择、状态更新与记录。

```{raw} html
<ol class="prompt-flow" aria-label="日内认知流程">
<li><strong>感知</strong><span>将时间、社会环境、自然环境与政策转成居民的当下感受。</span></li>
<li><strong>规划</strong><span>结合感知、情绪、经验和现实约束，生成行动计划。</span></li>
<li><strong>行动</strong><span>后续阶段选择并处理动作，得到 outcome。</span></li>
<li><strong>反思</strong><span>结合行动结果和相关记忆，形成感受、经验与后续倾向。</span></li>
</ol>
```

各阶段按配置与运行分支执行。查看具体行为时，将当前模板与 [运行模式](../simulation.md) 一起核对。

## 环境感知

**用途。** `perception()` 让居民用一至两句话描述此刻对环境、他人和制度的感受，调用任务名为 `perception`。

| 输入 | 来自哪里 | 如何进入正文 |
| --- | --- | --- |
| `agent`、`time_str` | 当前居民与仿真时间 | 姓名与当前时间 |
| `social_context` | 社交上下文 | 居民感知到的社交环境 |
| `env_context` | 环境信息与插件贡献 | 自然与社会环境 |
| `policy_event` | 当前政策描述 | 政策环境 |
| `extra_sections` | `perception.sections` 钩子 | 附加段落，例如已掌握的技能 |

```{raw} html
<details class="prompt-details" open><summary>完整示例：18:00 的环境感知</summary>
```

```{literalinclude} ../_static/prompts/perception.txt
:language: text
```

```{raw} html
</details>
```

示例由真实 `perception()` 函数生成，居民和场景为教学输入。返回值是文本，随后作为规划阶段的 `perception_text`。

```{raw} html
<div class="prompt-source">源码：<a href="https://github.com/wuchaozju/GAWorld/blob/main/gaworld/sim/_cognition.py">_cognition.py · perception()</a><br>装配：<a href="https://github.com/wuchaozju/GAWorld/blob/main/generative_city_sim.py">generative_city_sim.py · _stage_perceive()</a></div>
```

## 行动规划

**用途。** `planning()` 以感知为起点，补入情绪、记忆提示、唤起的回忆、外部信息、当天意图与近期历史。与当前规划相关的物理环境、社会事件、位置、关系和临时念头作为可选段落加入。

模板要求返回以下五个字段，每个字段为 8–30 字的中文文本：

| 字段 | 表达什么 |
| --- | --- |
| `goal` | 当前想达成的目标 |
| `constraint` | 面临的现实约束 |
| `urge` | 内心冲动，或回避、社交、恢复等倾向 |
| `plan` | 在目标与约束之间形成的具体计划 |
| `expected_outcome` | 对结果的预期 |

模板中的要求摘录：

```text
2) constraint 必须是现实约束，urge 必须是内心冲动或偷懒/回避/社交/恢复倾向之一。
3) plan 要体现妥协，而不是完美理性答案。
4) 仅输出 JSON，不要其他文字。
```

`call_llm(..., task="planning")` 返回后，`_parse_structured_json()` 读取这五个字段；解析未得到可用结构时，`_fallback_plan_struct()` 提供后续阶段使用的结构。调整字段名时，同步检查解析列表、格式化函数与消费这些字段的阶段。

## 行动后的反思

**用途。** `reflection()` 读取刚发生的 `outcome` 和相关记忆，返回 `result`、`feeling`、`lesson`、`next_bias`。四个字段依次描述结果、情绪、获得的经验，以及接下来更偏向的做法，每个字段同样要求 8–30 字。

例如，要研究居民如何从失败的行动中学习，可以先检查进入 `outcome` 的内容，再查看 `lesson` 与 `next_bias`。模型能否得到具体的行动结果，会直接影响这两项回答。

规划与反思模板均在 [generative_city_sim.py](https://github.com/wuchaozju/GAWorld/blob/main/generative_city_sim.py)；字段格式化与回退结构在 [_schedule.py](https://github.com/wuchaozju/GAWorld/blob/main/gaworld/sim/_schedule.py)。

## 日、月、年尺度的生活简报

快进模式用一份简报概括居民在一个时间步内的生活。`simulate_agent_day()` 使用 `_DIGEST_PROMPT`；月、年模式由 `simulate_agent_period()` 使用 `_PERIOD_DIGEST_PROMPT`。周期长度、角色状态、目标、记忆和社会关系决定模型看到的上下文。

日简报经过处理后，主要提供以下内容：

- `brief`：这一日发生了什么。
- `memory` / `memories`：需要保存的经历。
- `state_changes`：指定状态变量的变化量。
- `goal_progress`、`social`、`intentions`：目标进展、社会信号与后续意图。

`_normalize_digest()` 整理返回值；状态变化按配置限制幅度，月、年模式另有时间尺度调整。扩展动作菜单时，`selected_action` 必须匹配传入的候选标识，随后由执行流程处理。

```{raw} html
<details class="prompt-details"><summary>展开完整日简报提示词</summary>
```

```{literalinclude} ../_static/prompts/daily-brief.txt
:language: text
```

```{raw} html
</details>
```

这份示例由 `simulate_agent_day()` 生成，`randomness=0`，使用本地固定回复完成解析。[下载文本](../_static/prompts/daily-brief.txt) · [查看源码](https://github.com/wuchaozju/GAWorld/blob/main/gaworld/sim/_fastforward.py)

## 修改时怎样选择入口

1. **调整居民看到的事实**：从事件、环境、居民资料或插件提供的上下文入手，先确认内容进入了目标阶段。
2. **改变规划与反思的作答方式**：定位 `planning()` 或 `reflection()` 的模板，保留后续代码需要的字段；需要增减字段时同步调整解析和消费端。
3. **给居民增加领域知识**：使用感知扩展钩子。技能插件已经提供可参考的实现，见 {ref}`通过插件添加上下文 <edit-plugin>`。
4. **修改长时段行为**：从日简报或周期简报的模板入手，并检查时间跨度、状态变化范围与动作菜单。

验证时先生成提示词，检查输入是否进入对应段落，再执行该模块的离线测试。完整步骤见 [修改与验证](editing.md)。
