<p align="center"><img src="docs/assets/github-cover.svg" width="100%" alt="GAWorld — Generative agents, culture and everyday life" /></p>

<p align="center">
<a href="https://s2014628.github.io/gaworld-bench/world/">项目主页 / Website</a> ·
<a href="https://s2014628.github.io/gaworld-bench/">GAWorld Bench</a> ·
<a href="docs/FEATURES.md">能力目录 / Features</a> ·
<a href="README.en.md">English</a> · <a href="README.md">GitHub 首页</a>
</p>

<p align="center">
<img src="https://img.shields.io/badge/Python-3.11%2B-376556?style=flat-square" alt="Python 3.11+" />
<img src="https://img.shields.io/badge/Install-pip%20from%20GitHub-a34533?style=flat-square" alt="Install with pip from GitHub" />
<a href="https://github.com/wuchaozju/GAWorld/graphs/contributors"><img src="https://img.shields.io/github/contributors/wuchaozju/GAWorld?color=376556&amp;style=flat-square" alt="GitHub contributors" /></a>
</p>

# GAWorld · 人间实验室

**让记忆、关系与日常文化，进入一个可以研究的世界。**

GAWorld 是生成式多智能体社会仿真平台。人物档案、人格、家庭责任与过往经历共同构成居民的情境；城市、经济、天气与社会网络让行动产生后果。研究者可以观察轨迹、访谈居民，也可以在平行世界中比较不同事件与政策。

文化情境是设计的起点，是否真实则需要实验验证。

## Contributors · 一起构建这个世界的人

<p align="center">
<a href="https://github.com/wuchaozju"><img src="https://avatars.githubusercontent.com/u/597007?v=4&amp;s=128" width="64" height="64" alt="wuchaozju" /></a>
<a href="https://github.com/s2014628"><img src="https://avatars.githubusercontent.com/u/71760715?v=4&amp;s=128" width="64" height="64" alt="s2014628" /></a>
<a href="https://github.com/justinmiller1104"><img src="https://avatars.githubusercontent.com/u/30886201?v=4&amp;s=128" width="64" height="64" alt="justinmiller1104" /></a>
<a href="https://github.com/G-luckily"><img src="https://avatars.githubusercontent.com/u/189572350?v=4&amp;s=128" width="64" height="64" alt="G-luckily" /></a>
<a href="https://github.com/Luciddreamzz"><img src="https://avatars.githubusercontent.com/u/102663609?v=4&amp;s=128" width="64" height="64" alt="Luciddreamzz" /></a>
</p>

<p align="center"><a href="https://github.com/wuchaozju">wuchaozju</a> · <a href="https://github.com/s2014628">s2014628</a> · <a href="https://github.com/justinmiller1104">justinmiller1104</a> · <a href="https://github.com/G-luckily">G-luckily</a> · <a href="https://github.com/Luciddreamzz">Luciddreamzz</a></p>

感谢每一份代码、审阅与反馈。以上账号来自 GitHub 的真实贡献记录，不额外推断个人角色。
[查看全部贡献者](https://github.com/wuchaozju/GAWorld/graphs/contributors) · [协作流程](CONTRIBUTING.md) · [提交问题](https://github.com/wuchaozju/GAWorld/issues)

## 一条 pip 命令安装

需要 **Python 3.11+** 与 **Git**。推荐在虚拟环境中安装：

```bash
python -m pip install "git+https://github.com/wuchaozju/GAWorld.git@main"
```

打开本地控制台：

```bash
gaworld dashboard
```

浏览器访问 **http://127.0.0.1:8766**。首次运行会准备独立、可写的默认工作区 `~/.local/share/gaworld/workspaces/default`，包含网页、默认城市与运行代码。已有工作区和居民数据不会被覆盖。

想自己选择目录：

```bash
gaworld init ./my-world
cd my-world
gaworld dashboard
```

在控制台的 **配置 → 模型** 中选择服务商，填写自己的模型接口与 API Key，并测试连通性，再启动仿真。模型调用可能产生服务商费用；安装和浏览控制台不需要共享密钥。

当前通过 GitHub 分发，尚未发布 PyPI 包，因此安装命令使用项目地址。已初始化的工作区保留原版本；升级安装包后可用新目录初始化新版本，并单独迁移自己的数据。

## 从人，到城市，到问题

| 视角 | 能做什么 | 入口 |
| --- | --- | --- |
| **有来处的人** | 居民画像、大五人格、情景记忆、长期目标与家庭责任 | [Agent Studio 与完整指南](docs/PROJECT_GUIDE.zh-CN.md) |
| **会发生生活的城市** | 从地名创建城市，连接空间、通勤、天气、工作与经济系统 | [城市教程](docs/CITY_TUTORIAL.md) |
| **可以走进去的世界** | 创建人群、访谈居民、开展社会游戏、共享与分布式参与 | [群体访谈](docs/GROUP_INTERVIEW_TUTORIAL.md) · [游戏场](docs/PLAYGROUND_TUTORIAL.md) |
| **可以检验的问题** | 平行世界、政策与事件干预、配对结果和不确定性分析 | [研究工作台](docs/RESEARCH_WORKBENCH_TUTORIAL.md) · [平行世界](docs/PARALLEL_WORLDS_TUTORIAL.md) |

## GAWorld Bench · 两个问题，两条轴

- **功能效度**：任务是否完成？记忆、工具与平台机制是否发挥作用？
- **人类效度**：回答和行为是否接近匹配的真实人类参照？

[查看评测主页与评分方法](https://s2014628.github.io/gaworld-bench/)。两条轴分别报告，不混合成一个总分。当前 A35/A37 原生问答每项使用一个 agent；其成绩不能直接证明完整多 agent 协作或长期城市仿真效度。历史 FOS 机制与多角色实验保留独立协议和分母。

## 开发与扩展

```bash
git clone https://github.com/wuchaozju/GAWorld.git
cd GAWorld
python -m pip install -e ".[dev]"
python -m pytest --suite core
```

新的子系统通过微内核插件接入。[插件开发](docs/PLUGIN_AUTHORING.md) · [团队协作](CONTRIBUTING.md) · [部署指南](docs/SERVER_DEPLOYMENT.md)

## 文档与使用边界

[中文完整使用指南](docs/PROJECT_GUIDE.zh-CN.md) · [English guide](docs/PROJECT_GUIDE.en.md) · [完整能力目录](docs/FEATURES.md)

原有命令、配置项、模型接入和实验说明保留在完整指南中。仿真输出是模型与配置共同产生的研究材料，不应直接当作真实人群的预测。仓库现有包元数据标为 `Proprietary`；本次未更改授权条款。
