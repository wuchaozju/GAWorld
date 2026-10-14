# 示例

以下示例分别展示城市创建、仿真、访谈和结果读取。使用前完成 [安装](installation.md) 与模型配置。

## 创建离线城市

```bash
gaworld init ./example-world
cd example-world
python -m gaworld.city create "柳溪村" --offline --scale tiny --size 100
python -m gaworld.city list
```

从城市列表确认名称，再通过 `python -m gaworld.city use <城市名称>` 选择。

## 运行一天

```bash
gaworld run --sim-days 1
```

命令行的模型密钥和配置方式见 [命令行界面](cli.md)。

## 长期仿真

按天快进：

```bash
gaworld run --sim-days 60 --fast-forward
```

按月或年推进：

```bash
gaworld run --sim-months 24
gaworld run --sim-years 10
```

对照实验使用一致的时间尺度。

## 访谈居民

```bash
gaworld interview --agent-id 31 --question "今天有哪些事情影响了你的心情？"
```

将 `31` 替换为当前世界中的居民 ID。

## Python 查询

```python
from gaworld.client import GAWorldClient

gw = GAWorldClient("http://127.0.0.1:8766")
print(gw.run_status())
print(gw.operations())
```

## 编写技能

创建技能文件、挂载和检查的完整示例见 [Skill 编写指南](skill_guide.md)。

## 扩展仿真机制

订阅生命周期并写入结构化记录的示例见 [自定义模块](custom_modules.md)。

## 组织对照实验

在 [研究工作台](skills.md) 中设置共同基线、不同事件、测量指标与种子，运行后比较平行世界结果。将协议、居民输入、配置和结果保存在同一个研究记录中。
