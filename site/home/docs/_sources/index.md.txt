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

## 按你的任务阅读

| 你要完成的任务 | 从这里开始 |
| --- | --- |
| 接入模型，完成第一次运行 | [模型与运行配置](models.md) → [第一次仿真](quickstart.md) |
| 搭建研究对象与空间环境 | [城市与地图](cities.md) → [居民与 Agent Studio](residents.md) |
| 观察日常行动或长期变化 | [仿真运行与时间尺度](simulation.md) → [回放、分析与导出](results.md) |
| 比较事件、政策或参数的影响 | [平行世界与对照实验](parallel-worlds.md) |
| 将研究问题整理为可执行协议 | [研究工作台](research.md) |
| 收集居民回答与群体差异 | [访谈与群体采访](interviews.md) |
| 让居民完成工作并生成文件 | [技能与真实工作](skills-work.md) |
| 共用服务器或扩展仿真机制 | [团队部署与世界管理](deployment.md) · [编写插件](plugins.md) |

源码阅读入口见 [代码结构与阅读路径](code-structure.md)，其中包含仓库目录、模块关系与仿真执行流程。

## 城市、居民与世界

**城市**保存地图、环境和初始人口。**居民**具有身份、人格、状态、记忆与社会关系。**世界**保存一组居民副本、运行配置和输出；一次**运行**按选定时间尺度推进居民行动。

在同一套城市与居民基础上，你可以跟踪一次日常仿真，也可以建立多个实验条件，比较事件或配置改变后的轨迹。概念之间的关系见 [工作区、城市与世界](concepts.md)。

## 文档目录

```{toctree}
:maxdepth: 1
:caption: 开始使用

installation
quickstart
concepts
models
```

```{toctree}
:maxdepth: 1
:caption: 城市与居民

cities
residents
skills-work
```

```{toctree}
:maxdepth: 1
:caption: 运行与观察

simulation
results
interviews
```

```{toctree}
:maxdepth: 1
:caption: 研究与实验

research
parallel-worlds
policy-games
```

```{toctree}
:maxdepth: 1
:caption: 扩展与部署

deployment
code-structure
architecture
plugins
development
```

```{toctree}
:maxdepth: 2
:caption: 接口参考

cli
integration
api/index
```

## 项目链接

- <a href="../index.html">GAWorld 项目主页</a>
- [GitHub 仓库](https://github.com/wuchaozju/GAWorld)
- [问题反馈](https://github.com/wuchaozju/GAWorld/issues)
- [贡献者](https://github.com/wuchaozju/GAWorld/graphs/contributors)
- <a href="read.doc" download>下载 Word 汇编</a>
