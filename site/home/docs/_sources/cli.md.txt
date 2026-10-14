# 命令行界面

安装后使用 `gaworld` 命令。它会在选定的工作区中调用仿真程序；在源码仓库中，等价入口为 `python generative_city_sim.py`。

## 查看帮助

```bash
gaworld --help
gaworld run --help
```

## 工作区与控制台

```bash
gaworld init ./my-world
cd my-world
gaworld dashboard --port 8766
```

可以通过环境变量 `GAWORLD_WORKSPACE` 指定已经初始化的工作区。运行产物保存在该工作区内。

## 运行仿真

命令行运行使用工作区的模型配置。基础配置位于 `gaworld/settings/`，`dashboard_config.json` 提供运行覆盖项。云端密钥按配置中的环境变量名读取；控制台保存的个人密钥由已登录的网页会话使用。

配置完成后，运行一天：

```bash
gaworld run --sim-days 1
```

按天快进：

```bash
gaworld run --sim-days 60 --fast-forward
```

按月或年运行：

```bash
gaworld run --sim-months 24
gaworld run --sim-years 10
```

`--sim-months` 和 `--sim-years` 会选择对应的快进步长。使用 `gaworld run --help` 查看运行参数。

## 访谈居民

将 `31` 替换为当前世界中要访谈的居民 ID：

```bash
gaworld interview --agent-id 31 --question "你今天为什么选择这个行动？"
```

也可以使用问题文件，每行一个问题：

```bash
gaworld interview --agent-id 31 --questions-file questions.txt
```

## 创建与切换城市

在工作区目录中执行城市子模块：

```bash
python -m gaworld.city create "绍兴柯桥" --size 200
python -m gaworld.city use 绍兴柯桥
```

## 从初始状态重新运行

`reset` 会重置当前运行产物。先保存需要保留的日志、记忆与结果，再执行：

```bash
gaworld reset
gaworld run --sim-days 1
```

日常观察与多人实验可直接使用控制台；命令行适合本地运行、批量任务和脚本流程。

## 完整工作流

```bash
gaworld init ./my-world
cd my-world
python -m gaworld.city create "柳溪村" --offline --scale tiny --size 100
python -m gaworld.city list
```

从列表确认城市名称，用 `python -m gaworld.city use <城市名称>` 选择城市。启动控制台完成模型设置，再按照上文的命令行配置方式运行仿真。结果读取见 [存储与结果访问](storage.md)。
