# 团队部署与世界管理

团队可以共用一套 GAWorld 控制台，每位成员在自己的世界中保存居民、配置与运行结果。管理员管理账号、建城权限、运行名额与模型后端。

## 功能与准备

本章用于把一套控制台提供给团队，并为成员管理独立世界、运行名额和模型密钥。准备可运行 GAWorld 的服务器与管理员账号；多人共玩和分布式运行在世界创建完成后配置。

## 启用团队账号

在服务器的 GAWorld 工作区初始化账号库，并按提示设置管理员密码：

```bash
python -m gaworld.accounts init --admin 老师
python -m gaworld.accounts invite --count 30 --label 周三班
```

将邀请链接交给成员注册。账号库创建后，控制台要求登录；服务器设置 `GAWORLD_REQUIRE_ACCOUNTS=1` 后，会持续要求账号模式。

账号、服务进程与反向代理的完整配置见仓库的 [服务器部署说明](https://github.com/wuchaozju/GAWorld/blob/main/docs/SERVER_DEPLOYMENT.md) 和 [多用户部署配置](https://github.com/wuchaozju/GAWorld/tree/main/deployment/multi-user)。

## 配置个人模型密钥

管理员在服务环境中设置 `GAWORLD_LLM_SECRETS_PATH`，指向仓库外的绝对路径，并按部署说明配置目录权限。每位成员登录后，在 **配置 → 模型** 保存自己的 API Key，测试连通性，再选择默认模型和日程模型。

服务商后端由管理员维护，个人密钥按账号、协议和完整 Base URL 保存。字段与排查步骤见 [模型与运行配置](models.md)。

## 创建自己的世界

1. 打开控制台顶部的 **管理世界**。
2. 选择一座已有居民的城市，创建世界。
3. 切换到该世界，检查居民副本、模型和运行配置。
4. 编辑居民、启动仿真，并在该世界中查看结果。

世界数据保存在 `output/worlds/<id>/`。共享默认世界由管理员修改；成员在自己的世界中运行与编辑。

## 组织多人共玩

世界属主将世界设置为 **开放** 后，参与者可以切换到该世界，在 **多人共玩** 中认领居民、提交动作和对话。操作在后续 tick 生效，未被认领的居民继续由模型驱动。

在 **管理世界** 中设置每个 tick 等待玩家的时间，配合课堂讨论节奏。手机参与者可使用该世界的 `/play/<世界编号>` 链接进入。

## 管理运行与用量

管理员通过 **教师控制台** 管理邀请码、成员、建城权限、并发运行名额与模型调用配额，也可以查看世界、停止运行和导出共玩记录。成员提交的运行超过名额时进入队列。

## 分配到多台机器

世界属主在 **管理世界 → 分布式节点** 中添加节点，指定它负责的居民编号。复制界面生成的加入命令，在已安装 GAWorld 并配置自身模型密钥的节点机器上执行。

节点主动连接控制台，接收世界数据并运行分配的居民。节点上的状态 CSV、记忆和轨迹保留在节点本机；汇总分析时同时收集相关节点的结果。节点配置与同步设置见 [服务器部署说明](https://github.com/wuchaozju/GAWorld/blob/main/docs/SERVER_DEPLOYMENT.md)。

## 完成后检查

使用一个普通成员账号完成注册、保存模型密钥、创建世界和短运行，核对结果目录与权限。共玩时检查玩家动作是否进入后续 tick；分布式运行时检查节点在线状态和分配的居民编号。

## 代码结构与执行流程

### 模块分工

```{container} code-map

| 源码位置 | 职责 |
| --- | --- |
| [gaworld/accounts/store.py](https://github.com/wuchaozju/GAWorld/blob/main/gaworld/accounts/store.py) | 保存账号、邀请、会话及管理设置。 |
| [gaworld/accounts/policy.py](https://github.com/wuchaozju/GAWorld/blob/main/gaworld/accounts/policy.py) | 判断账号可以访问和修改的操作。 |
| [gaworld/apps/worlds\_api.py](https://github.com/wuchaozju/GAWorld/blob/main/gaworld/apps/worlds_api.py) | 创建、切换、共享和管理世界。 |
| [gaworld/worlds/\_\_init\_\_.py](https://github.com/wuchaozju/GAWorld/blob/main/gaworld/worlds/__init__.py) | 创建世界目录、复制居民输入并构造运行路径覆盖。 |
| [gaworld/apps/world\_paths.py](https://github.com/wuchaozju/GAWorld/blob/main/gaworld/apps/world_paths.py) | 按当前世界解析控制台读写路径。 |
| [gaworld/apps/runs.py](https://github.com/wuchaozju/GAWorld/blob/main/gaworld/apps/runs.py) | 按世界和运行限额调度仿真进程。 |
| [gaworld/apps/cluster\_api.py](https://github.com/wuchaozju/GAWorld/blob/main/gaworld/apps/cluster_api.py) | 管理节点、居民分配、世界包与节点通信。 |
| [gaworld/cluster/node.py](https://github.com/wuchaozju/GAWorld/blob/main/gaworld/cluster/node.py) | 节点连接主机并运行分配给自己的居民。 |

```

### 执行流程

```text
登录会话 → 权限检查 → 选择世界 → world_paths 解析目录
启动运行 → runs 排队与启动 → 世界路径覆盖 → 仿真输出
分布式节点 → cluster_api 领取配置与干预 → node 启动本地进程
```

世界同时对应账号库中的记录与 `output/worlds/<id>/` 目录。控制台验证当前世界后，将请求上下文传给读写模块；后台任务通过 `accounts/ownership.py` 继承用户与世界。运行时把世界配置和路径作为覆盖项传给仿真。共玩动作由 `apps/play_api.py` 接收，经 `multiplayer/plugin.py` 在运行中处理。

### 世界目录结构

```text
output/worlds/<id>/
├── config.json       世界配置
├── seed/             居民初始数据副本
├── logs/             运行日志
├── memory/           居民记忆与运行状态
├── state/            状态历史
├── visualization/    轨迹与运行归档
└── records/          结构化事件
```

世界创建时准备配置与居民输入；各输出目录由相应运行过程写入。

### 从哪里修改

调整权限查看 `accounts/policy.py`，调整世界数据布局查看 `worlds/__init__.py` 与 `world_paths.py`，调整运行名额查看 `apps/runs.py`。节点调度与通信从 `cluster_api.py` 和 `cluster/` 开始。
