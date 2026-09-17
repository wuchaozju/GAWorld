# 2026-09-17 公网接入、代码整合与验收交接

## 结论与边界

`mo.zju.edu.cn` 由兆丰管理，本次没有它的 Nginx 登录权限。
不能把“13 号服务器已修好”写成“Mo 固定域名已修好”。
已建立独立 HTTPS 测试入口，Mo 的入口配置仍需管理员部署后重新验收。

- 临时统一控制台：<https://aud-generic-adjustment-riverside.trycloudflare.com/console>
- 临时 Relay 健康检查：<https://aud-generic-adjustment-riverside.trycloudflare.com/agent-relay/health>
- 手机孪生原入口保持不变：<https://sole-cant-microwave-ordinance.trycloudflare.com/site/mobile/?v=5>
- 原团队看板：<https://mo.zju.edu.cn/board>

控制台采用 HTTP Basic 登录，用户名为 `gaworld`。口令通过私密文件单独交付，
不写入文档或 Git。临时域名由服务器隧道提供，不依赖开发者电脑持续开机；
隧道重建后可能更换域名，不应作为长期固定地址。

## 给兆丰的信息

需要将 GAWorld 控制台、相关资源/API、Agent Relay 和手机孪生路由接到：

```text
http://10.72.74.13:8780
```

这是新增的统一网关：内部转发到 Dashboard 8766、Relay 8877、Twin 8767。
Relay 路径前缀由网关去掉；Nginx 不要再次剥离前缀。

请使用 [Nginx 路由片段](../deployment/public/mo-gaworld.locations.conf)，
按 [安装与验收说明](../deployment/public/README.md) 合入现有 HTTPS server。
检查是否存在优先级更高的旧 `location`，不要简单重复追加。
不要将 Mo 平台全部 `/api/` 或 `/site/` 转给 GAWorld。

实际发现的入口问题：`/dashboard` 返回 GAWorld HTML，但 `/api/config`、
`/api/agents`、`/api/run/status`、控制台脚本以及 `/agent-relay/health`
返回 200 + Mo 首页 HTML。这不是正确的成功响应，会造成 JSON 解析错误。

验收必须同时满足：

1. `/agent-relay/health` 是 200 JSON，不是 HTML。
2. 注册两个测试 Agent，发送一条消息，另一端轮询收到同一条消息。
3. 控制台登录后 API 返回 JSON，脚本与样式可加载。
4. 无令牌调用 `/api/twin/snapshot` 返回 401 JSON。
5. 在公网 HTTPS 页面验证操作，不能只在服务器上 curl 回环地址。

## 代码整合与冲突处理

本次目标分支是 **Dev，注意大小写**。保留已有团队改动，未强推。

- 合入远端 `0f6cb01`、`c9c30ae`、`8ebc709`、`5363f68`，包含手机选 Agent、
  地图外真实位置、文档，以及恢复此前合并丢失的配置/定时运行/就业代码。
- `gaworld/twin/backend.py` 冲突：同时保留 `has_location` 与上游 `place/loc`。
  前者排除无效位置，后者保留真实地点信息，两者不是二选一。
- `site/mobile/app.js` 冲突：保留上游选择/绑定 Agent 和 409 处理，
  轨迹仍使用有效位置过滤，不重新隐藏地图外 GPS。
- 手机缓存版本升为 v5，避免两边都使用 v4 时旧脚本继续生效。
- 公网验收另修复共享样式文件缺失、图片地址错误、首次运行前头像/轨迹 404。
  轨迹读取改由 API 按当前 visualization.output_dir 取数据，支持城市配置。
- 自动部署修复：显式虚拟环境 Python 路径不再 `.resolve()`，避免跳到系统
  Python 后触发 externally-managed-environment，导致拉代码后服务未重启。
- 实际运行发现 `_effective_config()` 遗漏城市配置层：补齐城市目录解析，
  保留环境变量最高优先级。否则仿真成功写入城市目录，控制台仍显示空白。
- 手机服务固定既有上报/绑定目录，避免 Dashboard 切换城市或升级配置层后
  读到另一个空目录。升级前做数据备份；旧代码改动保留在服务器 Git stash。

`main` 与 Dev 双方均有独有历史，试合并出现 16 个冲突文件：
`README.md`、`README.zh-CN.md`、`config.py`、`dashboard_config.json`、
`dashboard_server.py`、`data/hangzhou_agents_state_init.csv`、
`data/hangzhou_profiles_with_names.v1.md`、`data/news_cache.json`、
`distributed_comm_server.py`、`gaworld/cognition/realism.py`、
`generative_city_sim.py`、`llm_providers.py`、`site/dashboard/app.js`、
`site/dashboard/index.html`、`site/dashboard/styles.css`、`tests/test_distributed_comm.py`。

main 含有自己的功能，不应强行用 Dev 覆盖。本次不宣称 main 已统一；
后续单独审查其独有功能，再通过 Dev -> main 发布 PR 整合。
团队新开发应从最新 `origin/Dev` 拉个人分支，代码审查和测试后回到 Dev。

## 验收记录

在 13 号服务器隔离工作目录执行，不将测试输出提交 Git：

| 检查 | 已确认结果 |
| --- | --- |
| 合并代码完整 pytest | 1994 passed，1 skipped，249 subtests passed |
| 手机前端逻辑测试 | 37 passed |
| 全部前端测试入口 `node --test site/**/*.test.js` | 107 passed |
| 隔离预发布六个浏览器页面 | 控制台、总入口、Studio、配置、城市、协作均无脚本异常/HTTP 失败 |
| 统一 HTTPS 网关 API | config、agents、run/status、todos 返回 JSON |
| 统一 HTTPS Relay | health、注册、发送、轮询，确认消息实际到达 |
| 隔离环境实际 LLM 运行 | Ollama `qwen3:4b-instruct-2507-q4_K_M`，1 Agent / 1 天，退出码 0 |
| 实际结果可视化 | 长时快进模式生成 1 帧、1 Agent，finished=true；390/1440px 像素检查通过 |
| 原手机公网轨迹 | 原邀请码可登录，位置标记/连线/回放在 390/1440px 正常 |

pytest 的 1 个 skip 是翻译键排序检查；306 个 warning 主要是测试绘图缺中文字体。
这些结果不等于所有 LLM 后端、所有插件、多 Agent 长时间运行已验收。
每次正式发布应记录实际运行的模型、数据范围、输出产物与退出码。

实际运行验收使用独立目录 `/home/ft/GAWorld-release-final`，新闻联网与生产
Relay 已关闭后完成。首次尝试曾连接默认 Relay，已停止该进程；未发送测试对话。
该次中止进程的节点注册已按精确 node_id 清理，清理前保留状态备份，其他注册和消息未删除。
最终运行产物位于 `output/cities/wuzhen/`，不是正式环境的数据。
快进模式只有每日帧，这次结果不能证明分钟级行走、多 Agent 长期并行均已通过。
LLM 运行从内网预发布 API 发起；公网验证覆盖的是路由、页面/API 和 Relay 消息，
不是把这次内网仿真冒充为所有公网仿真场景验收。

## 运维位置

- 应用：`/home/ft/GAWorld`，Python：`.venv-deploy/bin/python`。
- 网关：`~/.config/gaworld/Caddyfile`，私密环境文件 `public-gateway.env`。
- 用户服务：`gaworld-public-gateway`、`gaworld-public-tunnel`。
- Twin 独立目录：`/home/ft/GAWorld-twin`，保留现有上报和绑定。
- 不要为更新 Python 应用而重启 HTTPS 隧道。
- Relay 当前是开放注册测试环境，正式用于私密交互前需增加认证/访问限制。
- 自动部署 watcher 已恢复，但服务器到 GitHub 偶发连接超时/TLS 错误，失败会
  在后续轮询重试；不能保证每次 push 后立即更新。用 `runtime/services/deployed-rev`
  与 GitHub 提交号核对实际部署版本，而不是只看 Git 工作目录的 HEAD。

旧记录 [2026-09-16 部署说明](TWIN_DEPLOYMENT_2026-09-16.md) 是当日快照；
其中“未 push”、旧基线和 v4 缓存不代表本次交付后的状态。
