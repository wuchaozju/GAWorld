# GAWorld 文档

GAWorld 是生成式多智能体社会仿真平台。你可以创建城市与居民，让居民在环境中行动、工作和建立关系，再通过事件、政策与对照实验研究个体和群体的变化。

![版本 0.2.1](_static/badges/version.svg) ![Python 3.11 或更高版本](_static/badges/python.svg) [![GitHub 源码](_static/badges/source.svg)](https://github.com/wuchaozju/GAWorld)

## 从一次仿真开始

[安装 GAWorld](installation.md)，创建工作区并启动控制台：

```bash
python -m pip install "git+https://github.com/wuchaozju/GAWorld.git@main"
gaworld init ./my-world
cd my-world
gaworld dashboard
```

打开 <http://127.0.0.1:8766>，依次完成模型配置、城市与居民选择、运行和结果查看。[第一次仿真](quickstart.md) 给出完整操作步骤。

## 按照你选择你需要阅读的内容

### 入门指南

安装 GAWorld，理解工作区、城市与世界，完成第一次仿真。

[安装](installation.md) · [第一次仿真](quickstart.md) · [核心概念](concepts.md)

### 用户指南

按任务学习配置模型、创建城市与居民、运行仿真和分析结果，再开展访谈、对照实验与政策推演。各章说明用途、操作步骤和对应的代码结构。

- **准备仿真**：[模型配置](models.md) · [城市与地图](cities.md) · [居民与 Agent Studio](residents.md) · [技能与真实工作](skills-work.md)
- **运行与观察**：[仿真运行](simulation.md) · [回放与分析](results.md) · [访谈与群体采访](interviews.md)
- **开展研究**：[研究工作台](research.md) · [平行世界](parallel-worlds.md) · [政策推演与严肃游戏](policy-games.md)
- **管理与运行工具**：[团队部署](deployment.md) · [命令行](cli.md)

### 开发者指南

了解代码组织与运行架构，编写插件，通过 Python 或 HTTP 接入 GAWorld，并参与项目开发。

[代码结构](code-structure.md) · [系统架构](architecture.md) · [编写插件](plugins.md) · [接口集成](integration.md) · [API 参考](api/index.md) · [开发与贡献](development.md)

## 城市、居民与世界

**城市**保存地图、环境和初始人口。**居民**具有身份、人格、状态、记忆与社会关系。**世界**保存一组居民副本、运行配置和输出；一次**运行**按选定时间尺度推进居民行动。

在同一套城市与居民基础上，你可以跟踪一次日常仿真，也可以建立多个实验条件，比较事件或配置改变后的轨迹。概念之间的关系见 [工作区、城市与世界](concepts.md)。

```{toctree}
:hidden:
:maxdepth: 1
:caption: 入门指南

installation
quickstart
concepts
```

```{toctree}
:hidden:
:maxdepth: 1
:caption: 用户指南

models
cities
residents
skills-work
simulation
results
interviews
research
parallel-worlds
policy-games
deployment
cli
```

```{toctree}
:hidden:
:maxdepth: 1
:caption: 案例分析

cases/index
cases/simulation-records
cases/classics
cases/demand
```

```{toctree}
:hidden:
:maxdepth: 1
:caption: 开发者指南

code-structure
architecture
plugins
integration
api/index
development
```

## 项目链接

- <a href="../index.html">GAWorld 项目主页</a>
- [GitHub 仓库](https://github.com/wuchaozju/GAWorld)
- [问题反馈](https://github.com/wuchaozju/GAWorld/issues)
- [贡献者](https://github.com/wuchaozju/GAWorld/graphs/contributors)
- <a href="read.doc" download>下载 Word 汇编</a>
