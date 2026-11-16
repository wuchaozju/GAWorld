# GAWorld 外部 API 令牌接入说明

交接对象：李兆峰及外部项目开发人员。版本日期：2026-11-16。

## 1. 先区分两种 Key

- 本文的 **GAWorld API 令牌**：让外部程序以某个 GAWorld 账号的身份访问接口。
- 账号设置中的 **模型 API Key**：调用 DeepSeek、GLM、MiniMax 等模型服务的凭据。两者不能互换。
- 不要把运维级 `GAWORLD_DASHBOARD_TOKEN` 分发给合作项目；它保留管理员能力。

本次个人令牌首批开放平行世界实验的预览、运行、进度查询、结果读取、停止与解读。
其他平台接口默认拒绝，不能认为拿到令牌就能调用所有 OpenAPI 接口。
这不是 OAuth，也不替代原有网页登录、邀请码注册和分布式节点令牌。

## 2. 从网页生成

1. 以自己的账号登录，先创建一个自己的仿真世界，配置居民和模型。
2. 打开“账号设置”，页面下方新增 **API 令牌**。
   公网挂载入口为 `https://mo.zju.edu.cn/GAWorld/console#account`；实际部署完成后生效。
3. 输入名称，例如“数字合伙人测试”；选择绑定的世界。
4. 勾选权限、设置 1–365 天有效期（默认 30 天），输入当前账号密码确认。
5. 点击“创建令牌”，立即复制完整值。完整值只在这次创建响应中返回，刷新后不能找回。
6. 将令牌放入调用方服务的环境变量或密钥管理系统，不写入 Git、网页 JavaScript、日志或 URL。

每个账号最多 20 个未过期且未撤销的令牌。管理员也只能为自己拥有的世界创建个人令牌；
这类令牌按普通成员权限处理，不继承管理员跨账号访问能力。

## 3. 权限与世界

| 权限 | 允许的接口 |
| --- | --- |
| `parallel:read` | GET/HEAD `/api/parallel-worlds/overview`、`experiments`、`experiment`、`heterogeneity`、`interpretation`、`job` |
| `parallel:run` | POST `/api/parallel-worlds/preview`、`sweep`、`start`、`stop`、`interpret` |
| 令牌基础自查 | GET/HEAD `/api/auth/me`、`/api/openapi.json` |

需要完成“创建、运行、读结果”的调用方，应同时选择 `parallel:read` 和 `parallel:run`。
“创建实验”由 `start` 完成：`preview` 仅校验，不落盘、不启动任务。

令牌绑定世界不能靠 Cookie、`/api/worlds/select` 或请求体改成另一个世界。
可选请求头 `X-GAWorld-World` 用于检查调用方预期世界，不是切换世界；不匹配返回 409。
读取实验还会检查创建账号和世界。不能查看、停止其他账号或同账号另一个世界的任务。
个人令牌不能修改账号、创建其他令牌、访问管理员接口或任意下载服务器文件。

实验的 `worlds[].config` 只接受已有安全策略允许的仿真参数，不能设置插件、模型地址、
凭据、文件路径或从任意服务器 checkpoint 导入。模型先在网页中配置，接口可指定已配置的提供商名称。

## 4. HTTP 调用示例

以下 URL 需要已上线本次版本。内网直接访问时，将 BASE 换成 `http://10.72.74.13:8766`。
公网必须使用 HTTPS；反向代理须保留 `Authorization` 请求头和 `/GAWorld/` 子路径。
外部项目应由自己的后端调用，不将令牌嵌入公开网页；本次没有开放任意跨域浏览器 CORS。
公网入口实测会拦截 Python 默认 User-Agent 并返回 HTML 403。本仓库 Python 客户端已发送
`User-Agent: GAWorldClient/1.0`；自写 urllib 客户端也应明确设置应用标识，不能将 HTML 403 当作 JSON 解析。

```bash
export GAWORLD_BASE_URL='https://mo.zju.edu.cn/GAWorld'
# GAWORLD_API_TOKEN 由调用方密钥系统注入，不在此处放真实值。
curl --fail-with-body "$GAWORLD_BASE_URL/api/auth/me" \
  -H "Authorization: Bearer $GAWORLD_API_TOKEN"
```

先预览一个最小实验：

```bash
curl --fail-with-body "$GAWORLD_BASE_URL/api/parallel-worlds/preview" \
  -H "Authorization: Bearer $GAWORLD_API_TOKEN" \
  -H 'Content-Type: application/json' \
  --data '{"name":"接口连通性测试","sim_days":1,"seed":123,"agent_ids":[1],
    "worlds":[{"id":"baseline","label":"基准"},
      {"id":"treatment","label":"干预","events":[
        {"day":1,"time":"09:00","name":"政策通知","description":"发布一项测试政策"}]}]}'
```

将路径的 `preview` 换成 `start` 即真正运行，会消耗模型额度或服务器算力。
居民 ID 必须来自绑定世界；示例 `1` 不保证适用于所有世界。响应为 202，例如：

```json
{"job_id":"pw-...","experiment":"output/parallel_worlds/...","job":{"status":"running"}}
```

查询进度和结果：

```bash
curl --fail-with-body --get "$GAWORLD_BASE_URL/api/parallel-worlds/job" \
  -H "Authorization: Bearer $GAWORLD_API_TOKEN" --data-urlencode "id=$JOB_ID"

curl --fail-with-body --get "$GAWORLD_BASE_URL/api/parallel-worlds/experiment" \
  -H "Authorization: Bearer $GAWORLD_API_TOKEN" --data-urlencode "root=$EXPERIMENT_ROOT"
```

`JOB_ID`、`EXPERIMENT_ROOT` 使用启动响应的原值。任务状态为 `running` / `done` / `error` / `stopped`。
HTTP 202 只代表任务受理，不代表仿真完成；应轮询并检查终态。
服务重启后内存中的 job 可能消失，应保留 `experiment` 路径，通过 `experiments` / `experiment` 查询磁盘记录。

停止本人在绑定世界中的当前平行实验：

```bash
curl --fail-with-body "$GAWORLD_BASE_URL/api/parallel-worlds/stop" \
  -H "Authorization: Bearer $GAWORLD_API_TOKEN" -H 'Content-Type: application/json' --data '{}'
```

## 5. Python 调用

现有标准库客户端可直接使用个人令牌，无须模拟浏览器 Cookie：

```python
import os
import time
from gaworld.client import GAWorldClient

client = GAWorldClient(os.environ["GAWORLD_BASE_URL"], token=os.environ["GAWORLD_API_TOKEN"])
design = {
    "name": "API smoke", "sim_days": 1, "seed": 123, "agent_ids": [1],
    "worlds": [{"id": "baseline", "label": "Baseline"},
               {"id": "treatment", "label": "Treatment"}],
}
client.post("/api/parallel-worlds/preview", design)
started = client.post("/api/parallel-worlds/start", design)
deadline = time.monotonic() + 600
while time.monotonic() < deadline:
    job = client.get("/api/parallel-worlds/job", id=started["job_id"])["job"]
    if job is None:
        raise RuntimeError("Job unavailable; inspect the saved experiment record")
    if job["status"] == "done":
        report = client.get("/api/parallel-worlds/experiment", root=started["experiment"])
        break
    if job["status"] in {"error", "stopped"}:
        raise RuntimeError(job.get("error") or job["status"])
    time.sleep(2)
else:
    raise TimeoutError("Still running; this does not automatically stop the experiment")
```

不要对 `start` 做无条件自动重试：目前没有调用方幂等键，超时后先查实验列表，避免重复启动。
服务保持现有“一次一个平行世界实验”的资源限制；忙时返回 409。

## 6. 生命周期与错误排查

| 状态 | 含义 |
| --- | --- |
| 400 | 输入不合法，或包含不允许的配置参数 |
| 401 | 未提供有效令牌、令牌过期/撤销、账号停用或绑定世界失效 |
| 403 | 缺少 scope、尝试访问未开放接口、停止其他人的任务，或跨站请求 |
| 404 | 实验不存在或不属于本账号/绑定世界 |
| 409 | 已有实验运行，或预期世界与绑定世界不符 |
| 429 | 账号调用额度用尽，或令牌管理请求触发频率限制 |

- 账号设置中可查看名称、前缀、权限、绑定世界、到期时间、最近使用时间，随时撤销。
- 改密、重置密码会撤销该账号现有个人令牌；单纯退出网页登录不会撤销令牌。
- 撤销阻止后续请求，不会自动中断已经受理的后台实验；需要时先停止实验再撤销。
- 账号停用、邮箱未验证、世界被删除或不再归本账号所有时，令牌不能鉴权。
- 每次请求校验状态；最近使用时间最多每分钟写入一次，不代表逐请求日志。
- 令牌创建/撤销及写操作有审计记录，包含令牌 ID，不记录完整密钥。
- 数据库存储 SHA-256 摘要，不保存完整个人令牌；认证响应禁止缓存。
- LLM 配额仍是平台已有的软配额，不是严格的预算预留机制。

## 7. 运维上线与验收

1. 先备份正在使用的账号 SQLite 数据库及世界数据。在线备份使用 SQLite backup API，不直接复制正在写入的文件。
2. 更新到包含本功能的经过测试提交，保持已有多用户模式、账号库路径和 `/GAWorld` 前缀配置。
3. 服务重新加载代码后，首次打开账号库自动以幂等方式创建 `api_tokens` 表，不清空旧账号、会话或邀请码。
4. 用测试账号执行“网页创建 → Bearer 自查 → preview → 小规模 start → 查询 → 撤销 → 再访问应 401”。
5. 再用第二账号验证不能读取/停止第一账号的实验。检查代理没有拦截或移除 Authorization。
6. 旧代码回滚不会删除令牌表；回滚期间个人令牌功能不可用，升级恢复后仍应重新验收。

代码合并、Git 推送、服务器部署、公网验收是四件独立的事。请以本次合并报告中实际完成状态为准，
不能仅凭本文存在就认定线上已经更新。本地自动测试不调用付费模型，不证明模型效果或真实实验结论。

## 8. 后续新增接口

不要新增“全部 API”通配 scope。每类接口先审查账号/世界归属、任意路径、外部 URL、
可执行插件和后台上下文，再添加到 `gaworld/accounts/api_token_guard.py` 的明确路由表。
同步补 OpenAPI、越权测试、子路径测试和本交接说明。未列入允许表的路由始终拒绝。
