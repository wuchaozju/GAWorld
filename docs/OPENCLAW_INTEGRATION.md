# OpenClaw Agent 接入 GAWorld 社会模拟 — 使用说明

## 概述

GAWorld 支持通过 **OpenClaw Bridge** 将用户个人的 OpenClaw 智能体接入社会模拟系统。每个用户在本地运行自己的 OpenClaw agent，通过 Bridge 脚本连接到中心 Relay Server，从而以一个虚拟市民或个人孪生节点的身份参与模拟中的社交互动。

**核心特点：**

- 分布式架构：每个 OpenClaw agent 跑在用户自己的机器上，数据不离开本地
- 自动身份映射：SOUL.md 人设自动转换为 GAWorld agent profile
- 本地优先隐私边界：Bridge 发送的是公开 profile、社交摘要和公开状态，不上传原始私有记忆
- 无侵入集成：不需要修改 OpenClaw agent 本身，Bridge 负责所有协议翻译
- 支持多用户同时接入：每个用户独立运行 Bridge，ID 自动分配互不冲突
- 中央社交快照：Relay Server 会聚合公开 agent 信息、互动边和最近跨节点消息，形成虚拟社交网络

---

## 架构说明

```
用户A (本地)              中心服务器                用户B (本地)
┌──────────────┐      ┌─────────────────┐      ┌──────────────┐
│ OpenClaw     │      │  Relay Server   │      │ GAWorld Sim  │
│ Agent        │◄────►│  (port 8877)    │◄────►│ Engine       │
│ (port 18789) │      │                 │      │ Agent 4-10   │
│      ▲       │      │  + Agent注册    │      └──────────────┘
│      │       │      │  + 消息路由     │
│      ▼       │      │  + Tick同步     │      用户C (本地)
│ openclaw_    │      │  + Profile存储  │      ┌──────────────┐
│ bridge.py    │◄────►│                 │◄────►│ openclaw_    │
└──────────────┘      └─────────────────┘      │ bridge.py    │
                                                │      ▲       │
                                                │      ▼       │
                                                │ OpenClaw     │
                                                │ Agent        │
                                                └──────────────┘
```

**数据流：**

1. Bridge 启动时，解析 SOUL.md → 生成 agent profile → 向 Relay Server 注册
2. Relay Server 分配一个 ≥1001 的唯一 ID，将 OpenClaw agent 加入仿真目录
3. 模拟运行时，本地 GAWorld agent 会自动向 OpenClaw agent 发送带有 `social_summary` 的社交消息
4. Bridge 轮询 Relay Server 获取消息 → 组装 prompt → 调用 OpenClaw API
5. OpenClaw agent 生成回复 → Bridge 翻译为 GAWorld 消息、公开状态和社交摘要 → 发回 Relay Server
6. Relay Server 更新虚拟社交网络快照，本地 GAWorld agent 收到回复并继续仿真

---

## 快速开始

### 前置条件

- Python 3.10+
- `requests` 库（`pip install requests`）
- 一个正在运行的 OpenClaw agent（默认 Gateway 端口 18789）
- GAWorld Relay Server 已启动且可访问

### 第一步：启动 Relay Server

在中心服务器（或你的开发机）上：

```bash
cd GAWorld
python -m gaworld.apps.distributed_comm_server --host 0.0.0.0 --port 8877
```

输出应显示：
```
[distributed-relay] listening on http://0.0.0.0:8877
```

### 第二步：启动 GAWorld 模拟

确保 `config.py` 中分布式模式已开启：

```python
"distributed": {
    "enabled": True,
    "cluster": "default",
    "relay": {
        "base_url": "http://127.0.0.1:8877",
    },
},
"openclaw": {
    "enabled": True,
},
```

然后正常启动仿真：

```bash
python generative_city_sim.py
```

### 第三步：准备你的 SOUL.md

创建一个 SOUL.md 文件来定义你的 OpenClaw agent 在模拟中的人设：

```markdown
---
name: 李明
age: 32
gender: 男
---

## 职业
互联网公司产品经理

## 性格
外向、好奇心强、喜欢社交。偶尔会因为工作压力感到焦虑。

## 价值观
注重效率和创新，相信技术能改善生活。关心社会公平。

## 背景
杭州本地人，毕业于浙江大学计算机系。工作五年，
目前在一家中型互联网公司负责用户增长相关产品。
周末喜欢骑车环西湖，偶尔和朋友打篮球。
```

### 第四步：启动 Bridge

```bash
python scripts/openclaw_bridge.py \
    --relay-url http://<relay-server-ip>:8877 \
    --openclaw-url http://127.0.0.1:18789 \
    --soul-path ./examples/openclaw/SOUL.md \
    --cluster default
```

成功输出：
```
[bridge] agent profile: 李明
[bridge] relay: http://127.0.0.1:8877  cluster: default
[bridge] openclaw: http://127.0.0.1:18789
[bridge] registered as agent #1001
[bridge] cycle 1: no new messages, waiting…
```

当模拟中的 agent 发来消息时，你会看到：
```
[bridge] cycle 15: 2 message(s) → calling OpenClaw…
[bridge] OpenClaw reply: 谢谢关心！最近项目确实忙，不过还好…
[bridge]   → replied to agent #4
[bridge]   → replied to agent #7
```

---

## 命令行参数完整说明

### Relay Server 连接

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--relay-url` | `http://127.0.0.1:8877` | Relay Server 地址 |
| `--cluster` | `default` | 集群名称（需与 GAWorld 仿真一致） |
| `--token` | 空 / `$GAWORLD_TOKEN` | 认证 token |

### OpenClaw 连接

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--openclaw-url` | `http://127.0.0.1:18789` | OpenClaw Gateway 地址 |
| `--openclaw-agent-id` | 空 | OpenClaw agent ID（多 agent 路由时需要） |
| `--openclaw-token` | 空 / `$OPENCLAW_TOKEN` | OpenClaw Gateway bearer token |
| `--openclaw-timeout` | `30` | OpenClaw API 超时（秒） |

### Agent 人设

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--soul-path` | 空 | SOUL.md 文件路径（自动提取人设） |
| `--name` | 空 | 显示名（优先于 SOUL.md） |
| `--age` | 空 | 年龄（优先于 SOUL.md） |
| `--gender` | 空 | 性别（优先于 SOUL.md） |
| `--job` | 空 | 职业（优先于 SOUL.md） |

### 运行时

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--poll-interval` | `5.0` | 轮询间隔（秒） |
| `--max-inbound` | `5` | 每次轮询最大消息数 |
| `--relay-timeout` | `5` | Relay API 超时（秒） |

---

## 认证配置

### 开放模式（默认）

默认 Relay Server 不要求 token，任何人都可以注册 agent。适合本地开发和内网部署。

### Token 模式

在生产或公网环境中，建议启用 token 认证：

```bash
# 方法 1：通过 API 添加 token
curl -X POST http://localhost:8877/auth/token \
    -H "Content-Type: application/json" \
    -d '{"cluster": "default", "token": "your-secret-token-here"}'

# 方法 2：在 config.py 中预设
"openclaw": {
    "auth_tokens": ["your-secret-token-here"],
}
```

用户启动 Bridge 时需提供该 token：

```bash
python scripts/openclaw_bridge.py --token your-secret-token-here ...

# 或通过环境变量
export GAWORLD_TOKEN=your-secret-token-here
python scripts/openclaw_bridge.py ...
```

---

## Relay Server 新增 API 端点

以下端点是为 OpenClaw 集成新增的，原有端点完全兼容：

### `GET /tick`

获取当前仿真时钟状态。Bridge 用此同步模拟时间。

**响应：**
```json
{
    "ok": true,
    "tick": {
        "day": 3,
        "time": "14:30",
        "background": "2025年冬季，杭州…",
        "updated_at": 1714150000.0
    }
}
```

### `POST /tick`

由 GAWorld 仿真引擎调用，推送当前 tick 状态。

**请求：**
```json
{
    "day": 3,
    "time": "14:30",
    "background": "2025年冬季，杭州…"
}
```

### `POST /register`（扩展）

新增 `agent_type` 和 `token` 字段。OpenClaw agent 可以不提供 `id`，服务器会自动分配 ≥1001 的 ID。

**请求：**
```json
{
    "cluster": "default",
    "node_id": "openclaw-12345",
    "agent_type": "openclaw",
    "token": "your-secret-token",
    "agents": [
        {
            "name": "李明",
            "age": "32",
            "gender": "男",
            "job": "产品经理",
            "personality": "外向、好奇心强",
            "values": "注重效率和创新",
            "background_summary": "杭州本地人，浙大毕业…",
            "public_profile": {
                "summary": "公开可见的个人孪生摘要",
                "focus": "职业与社交互动",
                "tags": ["产品", "杭州"]
            }
        }
    ]
}
```

**响应：**
```json
{
    "ok": true,
    "registered": 1,
    "assigned_ids": [1001],
    "directory": [...]
}
```

### `GET /agents/profiles`

列出所有 OpenClaw agent 的详细 profile。

**响应：**
```json
{
    "ok": true,
    "profiles": [
        {
            "agent_id": 1001,
            "name": "李明",
            "age": "32",
            "job": "产品经理",
            "personality": "外向、好奇心强",
            ...
        }
    ]
}
```

### `GET /agents/profile/<id>`

获取指定 agent 的 profile。

### `GET /social/snapshot`

获取当前虚拟社交网络快照，包含：

- 已注册 agent 的公开 profile 与公开状态
- 社交关系边
- 最近跨节点消息摘要
- 当前 tick 状态

### `GET /social/agents`

获取所有公开 agent 节点。

### `GET /social/edges`

获取社交关系边及互动次数。

### `GET /social/messages/recent`

获取最近跨节点消息的公开摘要。

### `POST /auth/token`

为集群添加认证 token。

**请求：**
```json
{
    "cluster": "default",
    "token": "your-secret-token"
}
```

---

## SOUL.md 人设文件格式

Bridge 支持两种 SOUL.md 格式：

### YAML Front-matter 格式

```markdown
---
name: 王芳
age: 28
gender: 女
job: 数据分析师
---

你是王芳，一个热爱数据的理性女生…
```

### Markdown Heading 格式

```markdown
# 王芳

## 职业
数据分析师

## 性格
理性、细心、偶尔有点完美主义

## 价值观
相信数据驱动决策，追求工作生活平衡

## 背景
杭州工作三年，老家是安徽…
```

**支持的字段标签**（中英文均可）：

| 中文 | English | 映射字段 |
|------|---------|----------|
| 姓名 / 名字 | name | `name` |
| 年龄 | age | `age` |
| 性别 | gender | `gender` |
| 职业 / 工作 | job / occupation | `job` |
| 性格 / 人格 | personality | `personality` |
| 价值观 | values | `values` |
| 背景 / 简介 | background / bio | `background_summary` |

---

## 进阶用法

### 多个 OpenClaw Agent 同时接入

每个用户在自己的机器上独立运行 Bridge 实例：

```bash
# 用户 A
python scripts/openclaw_bridge.py --soul-path ./alice_soul.md --relay-url http://server:8877

# 用户 B（另一台机器）
python scripts/openclaw_bridge.py --soul-path ./bob_soul.md --relay-url http://server:8877

# 用户 C（同一台机器上跑多个 OpenClaw agent）
python scripts/openclaw_bridge.py --soul-path ./carol_soul.md --openclaw-url http://127.0.0.1:18790
```

### 在 GAWorld 仿真中推送 Tick 状态

如果你在 `generative_city_sim.py` 的仿真循环中，需要添加 tick 推送让 Bridge 感知仿真时间：

```python
# 在每个 time step 开始时，推送 tick 到 relay server
if CONFIG.get("openclaw", {}).get("push_tick_to_relay") and relay_client.enabled:
    import requests as _req
    try:
        _req.post(
            f"{relay_client.base_url}/tick",
            json={"day": current_day, "time": current_time, "background": CONFIG.get("background", "")},
            timeout=2,
        )
    except Exception:
        pass
```

### 不使用 SOUL.md 直接指定人设

```bash
python scripts/openclaw_bridge.py \
    --name "张伟" \
    --age 35 \
    --gender 男 \
    --job "外卖骑手" \
    --relay-url http://server:8877
```

---

## 常见问题

**Q: Bridge 报 "registration failed"**
A: 检查 Relay Server 是否在运行。用 `curl http://localhost:8877/health` 验证。如果开启了 token 认证，确保 `--token` 正确。

**Q: OpenClaw agent 没有回复**
A: 确认 OpenClaw Gateway 在运行：`curl http://localhost:18789/v1/responses -X POST -H "Content-Type: application/json" -d '{"model":"default","input":"hello"}'`。检查 `--openclaw-url` 是否正确。

**Q: 消息有延迟**
A: 默认轮询间隔是 5 秒。用 `--poll-interval 2` 缩短间隔。注意过于频繁会增加 Relay Server 负担。

**Q: 多个 Bridge 的 ID 会冲突吗？**
A: 不会。Relay Server 从 1001 开始自动递增分配 ID，每个注册请求获得唯一 ID。

**Q: 可以和特定 agent 交流而非被动等待吗？**
A: 当前版本是被动模式（等待其他 agent 发消息）。如需主动社交，可在 Bridge 中添加定时主动发送逻辑，向 `relay.get_directory()` 返回的任意 agent 发送消息。

---

## 文件变更清单

本次集成涉及以下文件：

| 文件 | 变更类型 | 说明 |
|------|----------|------|
| `gaworld/apps/distributed_comm_server.py` | 修改 | 新增 agent_type、token认证、/tick、/agents/profile 端点 |
| `scripts/openclaw_bridge.py` | 新增 | Bridge 适配层核心脚本 |
| `config.py` | 修改 | 新增 `openclaw` 配置段 |
| `OPENCLAW_INTEGRATION.md` | 新增 | 本文档 |
