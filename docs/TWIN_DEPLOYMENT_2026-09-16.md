# 手机数字孪生部署与测试记录

检查日期：2026-09-16。服务器：10.72.74.13。

## 访问地址

- 原团队看板：https://mo.zju.edu.cn/board
- 手机孪生 HTTPS 测试入口：https://sole-cant-microwave-ordinance.trycloudflare.com/site/mobile/
- 校园网内入口：http://10.72.74.13:8767/site/mobile/

公网孪生入口已用浏览器验证。手机请优先使用 HTTPS；校园网 HTTP 页面可以手动选择地点，但不能正常申请 GPS 定位。
测试邀请码在本次对话中单独交付，绑定 Agent 1，未写入仓库文档。

操作：打开入口，点“开始”，输入邀请码，点“连接”；选择行为，点“上报”。允许定位即可带上 GPS，拒绝定位后可以手动选择地点或“仅上报行为”。“今日上报”支持更正行为与删除。

临时 HTTPS 入口由 13 号服务器上的 Cloudflare Tunnel 提供，不依赖本地电脑持续开机。
隧道进程重建时可能分配新域名，不能当作固定生产地址。
参考：[Cloudflare Quick Tunnels 官方说明](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/trycloudflare/)。

## 已启用的功能与范围

已启用：邀请码绑定、位置及行为上报、手动地点选择、历史更正与删除、轨迹展示与回放。
本次没有启动长期 LLM 仿真；新测试环境没有日记和仿真状态时，“智能体的今天”显示空状态。
要持续产生仿真日记，还需要在同一工作目录配置并运行启用了 twin stages 的仿真。

## 部署位置

- 独立工作目录：`/home/ft/GAWorld-twin`
- 基础代码：服务器 `Dev` 的 `027da0f`，另应用本次静态文件访问修复。
- Python：`/home/ft/GAWorld/.venv-deploy/bin/python`
- 服务：`gaworld-twin.service`，监听 `0.0.0.0:8767`。
- HTTPS 隧道：`gaworld-twin-tunnel.service`，回源 `127.0.0.1:8767`。
- 两个 systemd 用户服务均已启用，用户 linger 已开启。
- 数据：工作目录下的 `output/twin/`、`data/twin_bindings.json`。
- 本次代码和配置保留在本地及测试部署目录，未进行 GitHub push。

```bash
systemctl --user status gaworld-twin gaworld-twin-tunnel
systemctl --user restart gaworld-twin
journalctl --user -u gaworld-twin -n 50 --no-pager
journalctl --user -u gaworld-twin-tunnel --no-pager | grep 'https://.*trycloudflare.com'
```

不要为了重启应用而重启隧道，避免临时域名变化。独立工作目录暂未接入原 Dev 自动部署。

## 固定 mo 域名接入

检查时 `https://mo.zju.edu.cn/site/mobile/` 和 `/api/twin/snapshot` 仍返回 Mo 平台 HTML，尚未转发孪生服务。
固定入口仍需 mo 域名管理员部署 [Nginx 配置](../deployment/twin/mo-twin.locations.conf)：

- `/site/mobile/` → `http://10.72.74.13:8767`，保留原 URI。
- `/api/twin/` → `http://10.72.74.13:8767`，保留原 URI 及 Authorization。
- `/m` → 跳转 `/site/mobile/`。

在现有 HTTPS server 块加入配置后，管理员运行 `nginx -t`，通过后 reload。
验收：手机页面返回 GAWorld 页面；无令牌访问 `/api/twin/snapshot` 应返回 **401 JSON**，而非 200 HTML。

## 实测结果

- 原公网 `/board`：200，页面标题为 GAWorld Feature Board。
- 原公网 `/api/todos`：200，Content-Type 为 application/json。
- 手机孪生公网入口：200，页面标题为 GAWorld · 我的孪生。
- 服务器后端测试：45 passed、47 subtests passed。
- 手机前端逻辑测试：29 passed。
- 内网与公网各验证 390×844、1440×1000：邀请码登录、上报、修改、删除均通过，无页面脚本异常或横向溢出。
- 浏览器验证使用独立测试 Agent 999001，测试上报已通过接口删除，测试邀请码已撤销。
- 静态文件路由已限制为手机页面资源；GET/HEAD 访问项目文件、绑定文件、目录穿越和越界软链接的回归测试通过。

服务模板位于 [deployment/twin](../deployment/twin/)。

## 轨迹空白修复

2026-09-16 用户实测发现：GPS 上报已保存，但位置都在仿真地图范围之外。
旧前端用 `!out_of_map` 过滤轨迹，误将有效的真实位置全部隐藏。

已部署修复：轨迹 API 新增 `has_location`，区分有效 GPS 与“仅上报行为”的空位置；
前端展示所有有效位置点，地图外位置仍然不覆盖智能体的仿真地点。
新增位置点数量提示，并升级 PWA 缓存至 v4。

已有页面可直接打开此链接更新脚本：
https://sole-cant-microwave-ordinance.trycloudflare.com/site/mobile/?v=4

验证：前端 32 项测试、服务器后端 37 项测试及 47 个子测试通过。
用现有用户数据进行只读公网浏览器验证，390px 与 1440px 下均显示 4 个有效位置点；
通过画布像素检查确认标记和连线已绘制，回放正常。没有修改用户已有上报。
