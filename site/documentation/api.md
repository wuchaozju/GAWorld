# API 参考

GAWorld 提供 HTTP、命令行和 Python 三种接入方式。HTTP 适合外部应用与控制台集成；Python 客户端适合脚本与 Notebook。

## 连接 Dashboard

启动服务：

```bash
gaworld dashboard --host 127.0.0.1 --port 8766
```

本地服务地址为 `http://127.0.0.1:8766`。HTTP 请求与响应使用 UTF-8 JSON。启用账号或令牌的部署需要携带对应的会话或凭证。

## 查看 OpenAPI 描述

Dashboard 在 `/api/openapi.json` 提供 OpenAPI 3.1 描述，可导入 Swagger UI 或 Postman 查看参数和响应。

```bash
curl http://127.0.0.1:8766/api/openapi.json
```

每个接口具有 `operationId`。Python 客户端可通过该名称调用接口。

## 常用接口

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | `/api/config` | 读取当前运行配置 |
| GET | `/api/agents` | 读取居民摘要列表 |
| GET | `/api/agents/{id}/state` | 读取居民状态 |
| GET | `/api/run/status` | 读取运行状态和进度 |
| POST | `/api/run/start` | 在当前世界启动仿真 |
| POST | `/api/run/stop` | 停止当前世界的仿真 |
| GET | `/api/run/log/export` | 导出运行日志 |
| GET | `/api/analytics/overview` | 读取分析概况 |

## 使用 Python 客户端

```python
from gaworld.client import GAWorldClient

gw = GAWorldClient("http://127.0.0.1:8766")
status = gw.run_status()
print(status)
```

在开启账号的部署中，先登录，再查询当前账号的数据：

```python
import getpass
from gaworld.client import GAWorldClient

gw = GAWorldClient("http://127.0.0.1:8766")
gw.login(input("账号："), getpass.getpass("密码："))
print(gw.worlds())
```

令牌部署可以设置 `GAWORLD_DASHBOARD_TOKEN`，客户端会自动读取该环境变量。

## 处理响应状态

| 状态码 | 含义与处理 |
| --- | --- |
| 200 | 请求完成 |
| 202 | 已进入队列或创建后台作业，继续查询作业状态 |
| 400 | 检查请求字段与参数 |
| 401 / 403 | 检查登录状态、令牌与访问权限 |
| 404 | 核对资源 ID 与接口路径 |
| 409 | 当前运行或资源状态存在冲突，先查看运行状态 |
| 429 | 检查当前账号的调用额度 |

Twin、Agent Relay、External Environment 及更多 HTTP 和 Python 接口见仓库中的 [完整 API 参考](https://github.com/wuchaozju/GAWorld/blob/main/docs/API_REFERENCE.md)。
