# 访谈与群体采访

访谈用于查看居民如何回答问题。单人访谈便于追问某位居民的经历；群体采访使用同一套问题访问多位居民，并汇总选项与群体差异。

## 功能与准备

本章用于收集单个居民的回答，或用同一套问题比较多个居民与群体。准备受访城市、问题和可用模型；需要比较选项分布时，先明确题型和选项。

## 访问一位居民

在 Agent Studio 中打开居民的采访入口，输入问题并查看回答。命令行也支持单人访谈：

```bash
gaworld interview --agent-id 31 --question "今天有哪些事情影响了你的心情？"
```

将 `31` 替换为当前运行中的居民 ID。保存问题原文、模型与回答，便于后续比较。

## 发起群体采访

1. 打开控制台的 **群体采访**。
2. 选择城市，勾选个体居民或 cohort 群体智能体。
3. 检查受访者数、代表人数与预计模型调用次数。
4. 填写采访标题与背景，添加问题并设置题型。
5. 点击 **开始采访**，完成后查看摘要、统计与逐人回答。

群体采访从城市数据包读取名单，支持跨城市选人。需要采访仿真后的各条件居民时，可在 [研究工作台](research.md) 使用带跑后问卷的组合研究。

```{figure} _static/screenshots/interview.png
:alt: 群体采访的受访者选择界面，按城市显示个体和群体智能体
:figclass: guide-shot
:target: _static/screenshots/interview.png

群体采访示例。左侧选择城市与受访者，右侧核对受访者数、代表人数和模型调用次数。 点击图片查看完整尺寸。
```

## 选择题型与材料

| 题型 | 结果 |
| --- | --- |
| 开放题 | 原文回答与摘要 |
| 选择题 | 选项、理由与选项计数，可设置多选 |
| 是非题 | 是／否回答、理由与分类统计 |

问题可附网址或图片。网址正文会统一提取后提供给受访者；图片由支持视觉输入的模型处理。结果中的材料降级标记说明实际使用了哪些输入。

## 使用群体智能体

cohort 按年龄段、户籍、性别或片区等属性组织居民，一次回答代表该群体。选择维度后检查分组与成员，再勾选受访对象。

结果同时显示 **受访者数** 和 **代表人数**。例如一个代表 8 位居民的 cohort 产生一份回答，其代表人数为 8；分析时按界面给出的权重与有效回答口径读取统计。

## 继续追问

在结果页点击 **继续追问**，添加下一轮问题。每位受访者会看到自己在该会话中的前序问答。会话上下文保存于采访记录，群体采访保持居民长期记忆原状。

## 阅读与导出

先查看每题的有效回答与解析状态，再比较按城市、年龄段或户籍划分的分布。选择题中的未解析回答保留原文，并单独标记。

点击 **下载完整 Markdown**，获得采访信息、问题、材料、汇总统计、分组结果与逐人原话。会话记录保存在 `output/interviews/<session_id>/`。

批量调用与会话文件说明见仓库的 [群体采访说明](https://github.com/wuchaozju/GAWorld/blob/main/docs/GROUP_INTERVIEW_TUTORIAL.md)。

## 完成后检查

采访完成后核对受访者数、代表人数和有效回答数，再查看逐人原话与分组统计。追问时确认使用同一会话，导出 Markdown 后检查问题、材料与回答是否齐全。

## 代码结构与执行流程

### 模块分工

```{container} code-map

| 源码位置 | 职责 |
| --- | --- |
| [site/dashboard/survey.js](https://github.com/wuchaozju/GAWorld/blob/main/site/dashboard/survey.js) | 群体采访页面：选择受访者、编辑问题、查看与导出结果。 |
| [gaworld/apps/interview\_api.py](https://github.com/wuchaozju/GAWorld/blob/main/gaworld/apps/interview_api.py) | 提供名单、会话、运行任务与导出接口。 |
| [gaworld/interview/roster.py](https://github.com/wuchaozju/GAWorld/blob/main/gaworld/interview/roster.py) | 构造个体与 cohort 受访名单。 |
| [gaworld/interview/session.py](https://github.com/wuchaozju/GAWorld/blob/main/gaworld/interview/session.py) | 按城市分派采访进程，汇总回答、材料和会话记录。 |
| [gaworld/interview/runner.py](https://github.com/wuchaozju/GAWorld/blob/main/gaworld/interview/runner.py) | 组织单座城市中的问答；同一受访者按题目顺序回答。 |
| [gaworld/interview/aggregate.py](https://github.com/wuchaozju/GAWorld/blob/main/gaworld/interview/aggregate.py) | 计算选项计数、代表人数、分组结果和摘要。 |
| [gaworld/interview/report.py](https://github.com/wuchaozju/GAWorld/blob/main/gaworld/interview/report.py) | 将采访结果渲染为 Markdown。 |
| [gaworld/interview/store.py](https://github.com/wuchaozju/GAWorld/blob/main/gaworld/interview/store.py) | 保存和读取采访会话。 |

```

### 执行流程

```text
群体采访页面 → interview_api → session.run_round()
  → 按城市分进程 → runner 问答 → 合并逐人回答
  → aggregate 统计 → report 导出 → store 保存会话
```

会话层统一处理附件，保证各城市使用相同材料。每个城市的执行器先构造人物，再并发访问不同受访者；一位受访者内部按问题顺序保留上下文。统计同时记录回答人数和代表人数。单人访谈使用 `POST /api/interview` 或 CLI，群体采访接口位于 `/api/interview/` 的各子路径。

### 从哪里修改

修改题型时核对 `schema.py`、`prompt.py`、`runner.py` 与统计解析；修改分组统计查看 `aggregate.py`，修改导出文档查看 `report.py`。
