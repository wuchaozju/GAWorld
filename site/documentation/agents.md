# 使用智能体

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

运行后进入居民详情，查看状态、记忆与行动。记忆、日程和位置等数据保存在当前输出目录中；路径见 [存储与结果访问](storage.md)。

## 挂载技能

全局技能需要挂载到居民，私有技能按居民目录读取。文件格式和操作见 [Agent Skills](agent_skills.md)。

## 访谈与群体比较

对单个居民提问可结合其经历解释行动；群体采访可以对多位居民使用同一组问题。保存问题、居民选择和模型设置，比较回答时使用一致条件。

## 参考

- [Agent 模块](api/agent.md)
- [与 GAWorld 交互](interaction.md)
- [环境模块](env_modules.md)
