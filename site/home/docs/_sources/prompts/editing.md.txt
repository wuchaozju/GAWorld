# 修改与验证

提示词修改通常从三个入口开始：调整传入的资料和任务、修改固定模板，或通过插件增加上下文。先离线查看最终文本，再验证回答解析，最后用固定条件的小规模运行比较效果。

(edit-inputs)=
## 修改输入内容

普通使用从对应功能页操作即可：在 [居民与 Agent Studio](../residents.md) 修改居民资料，在 [群体采访](../interviews.md) 设置背景和题目，在 [研究工作台](../research.md) 提供研究材料，在 [政策推演](../policy-games.md) 编辑政策文本。

例如，访谈中的 `context` 写共同背景，`Question.text` 写当前问题，`Question.options` 写可选答案。改变这些输入即可生成新题目，题型的固定格式由 `prompt.py` 自动补齐。

研究政策描述时，把实际措施、实施对象、时间和资源条件写清楚。将“提高居民幸福感”这样的研究目标放在研究问题中；给居民阅读的事件则描述具体措施，便于比较居民怎样理解和响应。

(edit-template)=
## 修改模板与输出约定

在源码安装的环境中，先搜索函数或任务名：

```bash
rg -n 'def build_turn_prompt|def _format_contract' gaworld/interview/prompt.py
rg -n 'def planning|def reflection' generative_city_sim.py
rg -n 'def .*prompt|_PROMPT' gaworld/research
```

以群体采访为例，`_format_contract()` 决定回答要求，`build_turn_prompt()` 决定各段顺序。将开放题的回答长度从“2-4 句话”改成“1-2 句话”，会改变长度要求，仍可以沿用 `answer` 字段。

如果将 `answer` 改名，或把选择题从数组改成其他结构，需要一起修改 `parse_answer()` 与消费返回值的代码。按以下顺序检查：

1. 构建函数实际使用了新模板。
2. 输出字段、类型和取值范围与解析器一致。
3. 正常回答、缺失字段和无法解析的回答都有对应处理。
4. 报告与统计读取的是修改后的结构。

源码编辑后，在 [安装章节](../installation.md) 所述的开发环境运行。正在运行的服务需要重新加载修改后的 Python 代码；检查实际启动的仓库与 Python 环境，确认使用的是这份源码。

(edit-plugin)=
## 通过插件添加上下文

要在感知中加入领域信息，可以注册 `perception.sections`。以下示例在日内感知时加入一条社区公告，保存为可导入的 `my_pkg/notice.py`：

```python
from gaworld.kernel import Plugin


class NoticePlugin(Plugin):
    id = "notice"

    def setup(self, ctx):
        ctx.bus.on("perception.sections", self.notice)

    def notice(self, hook_ctx):
        return "【社区公告】服务中心今天开放公交运营意见征集。"
```

按照 [编写插件](../plugins.md) 注册类路径 `my_pkg.notice:NoticePlugin`。日内管线收集返回的文本，并通过 `extra_sections` 交给 `perception()`。

已有的 `SkillsPlugin` 使用同一钩子，将居民掌握的技能格式化后加入感知。`skills.inject_into_cognition` 决定是否注入，`skills.max_per_prompt` 控制数量；具体实现见 [skills/plugin.py](https://github.com/wuchaozju/GAWorld/blob/main/gaworld/skills/plugin.py) 与 [prompt_helpers.py](https://github.com/wuchaozju/GAWorld/blob/main/gaworld/skills/prompt_helpers.py)。

快进管线使用独立的 `fast_forward.perception.sections`。需要让同一公告出现在快进简报中时，在 `setup()` 另行订阅该事件。以对应运行模式生成的提示词为准，检查扩展内容是否出现。

(offline-preview)=
## 离线预览完整提示词

下载 [preview-prompts.py](../_static/examples/preview-prompts.py)，在已经安装 GAWorld 的 Python 环境中运行：

```bash
python preview-prompts.py --out prompts-preview
```

脚本使用文档中的虚构居民和公交场景，调用项目现有构建函数，生成六份文本：

```text
prompts-preview/
├── perception.txt           环境感知
├── daily-brief.txt          日简报
├── interview-open.txt       开放题
├── interview-choice.txt     选择题
├── interview-boolean.txt    是非题
└── policy-reaction.txt      政策反应
```

感知调用被本地函数截获，日简报通过注入函数返回固定教学回复，其余直接调用文本构建函数。运行结束显示 `model calls: 0`。再次运行会更新输出目录内同名的六份文件。

检查生成文本时，重点看居民资料、事件、题目和选项是否完整，追问历史是否属于当前受访者，以及 JSON 字段是否与解析器相同。正式实验使用的居民、上下文与运行参数应另外保存。

## 验证回答解析

先用一个固定回答检查结构，再决定是否开展模型试跑。例如：

```python
from gaworld.interview.prompt import parse_answer
from gaworld.interview.schema import Question

question = Question(
    id="q1",
    text="你希望末班车如何调整？",
    kind="choice",
    options=["保持现状", "延后半小时", "延后一小时"],
)
raw = '{"choice":["延后半小时"],"reason":"方便下班回家。"}'
answer = parse_answer(raw, question)
assert answer.choice == ["延后半小时"]
assert not answer.unparsed
```

已有测试覆盖选项匹配、是非判断、追问历史、附件，以及研究方案和协议处理。在仓库根目录选择与修改范围对应的测试运行：

```bash
# 群体采访的题型、提示词、解析与统计
python -m pytest tests/test_interview_group_core.py -q

# 研究方案与研究协议
python -m pytest tests/test_research_workbench.py tests/test_research_study.py -q

# 快进简报与技能注入
python -m pytest tests/test_fast_forward.py tests/test_skills_plugin.py -q
```

这些测试使用本地替身检查程序行为。真实模型的表达与选择，需要在选定模型上另做小规模运行并检查原始回答。

## 怎样比较两个提示词版本

先确定修改目标，例如“使居民提到具体的出行约束”或“提高选择题的有效解析率”。固定居民、输入场景、模型和采样设置，只改变要研究的模板部分，再记录两版的原始回答与解析结果。

| 检查项 | 记录什么 |
| --- | --- |
| 文本版本 | 源码提交、最终提示词、system/user 的实际内容 |
| 输入条件 | 居民资料、上下文、记忆、题目与附件 |
| 调用设置 | 提供商、模型、温度、输出预算与是否使用备用模型 |
| 结构质量 | 有效回答数、无法解析的比例、缺失或越界字段 |
| 行为表现 | 与研究问题直接相关的选择、理由和后续状态 |

`call_llm()` 支持 `system`、`temperature`、`max_tokens` 和 `allow_fallback` 等调用参数。实验需要固定模型时，可由调用方使用 `allow_fallback=False`，并记录失败的调用。调用约定见 [providers.py](https://github.com/wuchaozju/GAWorld/blob/main/gaworld/llm/providers.py)。

模型回答仍可能随采样变化。用多次重复观察差异，保存完整设置；改变默认仿真行为的代码修改，还需遵循仓库的可比性版本约定，见 [开发与贡献](../development.md)。

## 常见问题怎么定位

| 现象 | 优先检查 |
| --- | --- |
| 改了文本却看不到变化 | 服务使用的源码、运行模式与实际调用函数 |
| 回答经常无法解析 | 最终输出要求、字段名、模型原始回答和输出长度上限 |
| 居民忽略新增信息 | 上下文是否进入当前阶段，是否在篇幅很长的材料中被淹没 |
| 插件信息只在日内运行出现 | 是否订阅了快进对应的扩展事件 |
| 结果解释与数字不一致 | 假设或估计行 ID、结果判定，以及 `check_claims()` 的检查结果 |

返回 [提示词总览](index.md)，按任务找到对应模板。
