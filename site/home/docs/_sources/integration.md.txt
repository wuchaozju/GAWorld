# Python 与 HTTP 接口

GAWorld 提供控制台、命令行与 Python 客户端。控制台适合设置和观察仿真，命令行适合本地运行与批量任务，Python 客户端适合接入分析脚本。

## 交互方式

| 方式 | 入口 | 常见用途 |
| --- | --- | --- |
| 网页控制台 | `gaworld dashboard` | 配置、运行、回放、访谈与研究 |
| 命令行 | `gaworld run` | 按指定时间尺度执行仿真 |
| Python | `GAWorldClient` | 查询状态、调用接口、等待后台任务 |
| HTTP | `/api/openapi.json` | 接入外部应用和接口工具 |

## 连接控制台

```python
from gaworld.client import GAWorldClient

gw = GAWorldClient("http://127.0.0.1:8766")
print(gw.run_status())
```

## 登录与选择世界

启用账号的部署使用自己的账号登录。客户端保留会话 Cookie，用于后续请求：

```python
import getpass
from gaworld.client import GAWorldClient

gw = GAWorldClient("http://127.0.0.1:8766")
gw.login(input("账号："), getpass.getpass("密码："))
print(gw.worlds())
```

令牌部署可设置 `GAWORLD_DASHBOARD_TOKEN`，客户端会自动读取。

## 查询居民

通过 `operationId` 调用 OpenAPI 中的操作：

```python
residents = gw.call("get_city_agents", city="wuzhen", limit=20)
print(residents)
```

将城市参数替换为当前部署中的实际城市。使用 `gw.operations()` 查看服务提供的操作名。

## 访谈

在控制台打开居民详情或群体采访，设置问题并查看回答。命令行也提供访谈入口：

```bash
gaworld interview --agent-id 31 --question "你今天为什么选择这个行动？"
```

将居民 ID 替换为当前世界中的对象，并保存问题、模型与回答以便比较。

## 施加干预

运行中的干预通过控制器执行。例如设置指定居民的状态：

```python
gw.intervene("set_agent_state", agent_id=3, key="stress", value=0.9)
```

该操作会改变当前运行。实验前确定居民、变量和取值，并记录干预条件。控制器接口见 [仿真内核](api/kernel.md)。

## 读取事件

```python
for table, row in gw.events(["agent.step"]):
    print(table, row)
```

事件记录和结果目录见 [回放、分析与导出](results.md)。

## 响应与错误

客户端将非成功 HTTP 响应转换为 `APIError` 及其子类。登录、资源、运行冲突和调用额度分别对应明确的异常类型，详见 [客户端 API](api/client.md)。
