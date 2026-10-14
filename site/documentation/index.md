# GAWorld 使用指南

GAWorld 是一个生成式多智能体社会仿真平台。你可以创建城市与居民，观察他们的行动、记忆和社会关系，并比较不同事件或政策下的仿真结果。

本页带你完成安装、模型配置和第一次仿真。后续章节介绍城市管理、运行设置、结果查看与开发接口。

## 安装 GAWorld

准备 **Python 3.11 或更高版本**和 **Git**。在终端中执行：

```bash
python -m pip install "git+https://github.com/wuchaozju/GAWorld.git@main"
```

安装完成后，启动控制台：

```bash
gaworld dashboard
```

在浏览器打开 <http://127.0.0.1:8766>。首次启动会创建默认工作区，保存运行所需的代码、网页、城市数据和仿真产物。

:::{admonition} 工作区位置
:class: note

默认工作区位于 `~/.local/share/gaworld/workspaces/default`。如需自行选择位置，可按下面的步骤创建。
:::

## 创建工作区

为项目选择一个空目录。在终端执行：

```bash
gaworld init ./my-world
cd my-world
gaworld dashboard
```

后续在这个目录中启动 GAWorld，即可继续使用该工作区的数据与配置。

## 配置模型

1. 在控制台打开 **配置 → 模型**。
2. 选择模型服务商，填写对应的 **我的 API Key**，保存并测试连通性。
3. 打开自己的世界，在仿真页面设置 **默认模型**和**日程模型**。
4. 保存配置。

密钥按账号、协议和完整 Base URL 绑定，每个服务商使用对应的密钥。模型调用通过所选服务商的 API 计费。配置字段与常见连接问题见 [模型配置](models.md)。

## 运行第一次仿真

1. 打开仿真页面，选择要运行的居民。首次运行可选少量居民，并把仿真时长设为 **1 天**。
2. 确认默认模型与日程模型已选好，保存运行配置。
3. 点击启动，查看日志中的运行进度与居民行动。
4. 运行结束后，进入轨迹回放或居民详情，查看位置、状态与记忆。

你也可以在工作区中使用命令行运行。命令行的模型接入与运行参数见 [命令行](cli.md)。

## 查看结果

在控制台中，可以从三个角度查看一次仿真：

| 你想了解什么 | 查看位置 |
| --- | --- |
| 居民去了哪里、做了什么 | 轨迹回放与运行日志 |
| 某位居民的状态与经历 | 居民详情、记忆与访谈 |
| 群体随时间怎样变化 | Analytics 中的状态、经济与社交分析 |

结果文件保存在当前世界或城市的输出目录。常用文件及其位置见 {ref}`仿真与结果 <outputs>`。

## 接下来

- [城市与居民](cities.md)：创建城市、选择地图、设置居民并切换城市。
- [仿真与结果](simulation.md)：设置时长和步长，查看日志、轨迹与数据文件。
- [功能总览](features.md)：了解记忆、社交、经济、技能和真实工作。
- [API 参考](api.md)：从自己的程序读取状态、调用服务和接入实验流程。

## 常见问题

### 终端找不到 gaworld

确认安装与运行使用同一个 Python 环境。激活安装时使用的虚拟环境后，检查包是否已安装：

```bash
python -m pip show gaworld
```

### 浏览器打不开控制台

确认启动控制台的终端仍在运行，并检查终端显示的地址与端口。默认地址为 `http://127.0.0.1:8766`。如 8766 已被占用，可以指定其他端口：

```bash
gaworld dashboard --port 8767
```

随后打开 <http://127.0.0.1:8767>。

### 运行时提示密钥或模型错误

回到 **配置 → 模型**，检查所选服务商的 API Key、模型权限与账户余额，再测试连通性。仿真页面的默认模型和日程模型都需要指向可用后端。

### 如何升级

升级安装包：

```bash
python -m pip install --upgrade "git+https://github.com/wuchaozju/GAWorld.git@main"
```

已有工作区保留初始化时的版本。用新目录初始化新版工作区，再迁移需要的数据：

```bash
gaworld init ./my-world-new
```

```{toctree}
:hidden:
:caption: 入门指南

self
models
```

```{toctree}
:hidden:
:caption: 使用平台

cities
simulation
features
```

```{toctree}
:hidden:
:caption: 开发参考

cli
api
development
```
