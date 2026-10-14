# 居民与 Agent Studio

GAWorld 中的居民包含身份、人格、状态、日程、记忆和社会关系。你可以从城市数据创建居民，也可以导入已有数据，并在运行后回查个体经历。

## 查看与编辑居民

1. 在控制台确认当前世界和城市。
2. 打开 **Agent Studio**，选择一位居民。
3. 查看身份、状态与性格、技能、记忆、社会关系、行为目标和部署组织。
4. 保存修改，在仿真页面选择该居民参与运行。

查看其他城市的居民时，先确认当前操作针对的城市与世界，再进行编辑。

```{image} _static/screenshots/agent-studio.png
:alt: GAWorld Agent Studio
:width: 80%
```

## 人物数据

| 内容 | 用途 |
| --- | --- |
| 身份与人物档案 | 描述姓名、年龄、职业与背景 |
| 状态变量 | 表示精力、压力等随运行变化的状态 |
| 大五人格 | 为行为和表达提供人格特征 |
| 日程与目标 | 组织活动安排和长期方向 |
| 家庭与社会关系 | 表示家庭责任、朋友与社交连接 |
| 记忆与经历 | 保存过去行动及其结果 |
| 技能 | 提供可复用的操作知识 |

## 批量导入

在 Agent Studio 选择 **批量导入**，上传 CSV、XLSX 或 JSONL 数据。检查字段映射、匿名化与扩容选项后导入，再抽查居民档案和初始状态。

导入前保留原始数据与字段说明，便于核对居民构成。

## 从公开资料创建人物

在 Agent Studio 点击 **＋ 从真人蒸馏**，输入姓名或网址。系统检索资料并生成身份、状态、人格与思维框架。检查画像中的资料来源与证据强度，复核后选择 **填入表单** 继续编辑，或 **直接部署为居民**。

画像及来源保存在 `output/personas/`。详细字段见仓库的 [真人蒸馏说明](https://github.com/wuchaozju/GAWorld/blob/main/docs/PERSONA_DISTILL_TUTORIAL.md)。

## Python 数据接口

`Agent` 为居民字典提供属性访问，并与现有字典形式共享数据：

```python
from gaworld.core.agent import Agent, view_as_agent

record = {"id": 31, "name": "居民 31", "state": {"energy": 0.8}}
agent = view_as_agent(record)
print(agent.id, agent.name, agent.need("energy"))
agent.state["energy"] = 0.7
print(record["state"]["energy"])
```

该示例展示数据访问。完整居民由城市输入与仿真初始化流程构建。

## 记忆与日程

运行后进入居民详情，查看状态、记忆与行动。记忆、日程和位置等数据保存在当前输出目录中；路径见 [回放、分析与导出](results.md)。

## 挂载技能

全局技能需要挂载到居民，私有技能按居民目录读取。文件格式和操作见 [技能与真实工作](skills-work.md)。

## 访谈与群体比较

在 [访谈与群体采访](interviews.md) 中对居民提问，或跨城市选择受访者比较回答。群体采访支持个体居民与 cohort 群体智能体，结果分别保留受访者数量与代表人数。

## 参考

- [居民数据](api/agent.md)
- [Python 与 HTTP 接口](integration.md)
- [城市与地图](cities.md)
