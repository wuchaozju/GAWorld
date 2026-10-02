# GAWorld 服务器部署与自动部署 CLI

本文档描述当前两个服务的服务器运行方式：

```text
Dashboard / Team Board: 8766
Agent Relay:            8877
```

## 一次性部署

在服务器仓库目录执行：

```bash
python scripts/deploy_services.py deploy \
  --repo "$HOME/GAWorld" \
  --branch Dev \
  --process-manager systemd-user \
  --host 0.0.0.0 \
  --dashboard-port 8766 \
  --relay-port 8877
```

如果要先部署本次集成分支，把 `--branch Dev` 改成：

```bash
--branch integration/latest-dev-2026-09-04
```

该命令会执行：

```text
git fetch origin
git switch <branch>
git pull --ff-only origin <branch>
创建或复用 .venv-deploy
pip install -r requirements.txt
重启 Dashboard 服务
重启 Relay 服务
检查 /api/config 和 /health
```

`--process-manager systemd-user` 适合当前团队服务器，因为 8766/8877 已经由
`gaworld-dashboard.service` 和 `gaworld-agent-relay.service` 托管。该模式会复用现有
systemd 服务，不会额外启动一组抢端口的进程。

如果是在没有 systemd 的普通机器上运行，可以去掉 `--process-manager systemd-user`，
CLI 会用 `runtime/services/*.pid` 自己管理进程。

## 状态检查

```bash
python scripts/deploy_services.py status \
  --repo "$HOME/GAWorld" \
  --process-manager systemd-user \
  --host 0.0.0.0 \
  --dashboard-port 8766 \
  --relay-port 8877
```

期望看到：

```text
dashboard: running=True healthy=True url=http://127.0.0.1:8766/api/config
relay:     running=True healthy=True url=http://127.0.0.1:8877/health
```

也可以直接 curl：

```bash
curl http://127.0.0.1:8766/api/config
curl http://127.0.0.1:8766/api/todos
curl http://127.0.0.1:8877/health
```

## 长期测试分支

测试循环脚本在：

```text
scripts/test_branch_loop.sh
```

服务器上的 `start_test_loop.sh` 应设置：

```bash
export TEST_BRANCH="Dev"
export TEST_INTERVAL_SECONDS="300"
export PYTHON_BIN="python3"
exec scripts/test_branch_loop.sh
```

这样服务器会持续拉取并测试 `Dev`，测试日志写入：

```text
output/test-logs/latest.log
```

## 自动部署

长期轮询远端分支，发现新 commit 后自动部署：

```bash
mkdir -p "$HOME/GAWorld/runtime/services"
nohup python "$HOME/GAWorld/scripts/deploy_services.py" watch \
  --repo "$HOME/GAWorld" \
  --branch Dev \
  --process-manager systemd-user \
  --host 0.0.0.0 \
  --dashboard-port 8766 \
  --relay-port 8877 \
  --interval 60 \
  > "$HOME/GAWorld/runtime/services/deploy-watch.log" 2>&1 &
```

watch 模式会在部署成功后记录：

```text
runtime/services/deployed-rev
```

后续是否需要部署以这个文件为准，而不是只看本地 `HEAD`。因此即使测试循环已经提前
`git pull Dev`，watch 仍然能识别“这个 commit 还没有重启到服务上”。

在团队服务器上建议用 user systemd 托管 watch：

```bash
mkdir -p "$HOME/.config/systemd/user"
cat > "$HOME/.config/systemd/user/gaworld-deploy-watch.service" <<'EOF'
[Unit]
Description=GAWorld Dev auto deployment watcher
After=network-online.target

[Service]
Type=simple
WorkingDirectory=%h/GAWorld
ExecStart=/usr/bin/python3 %h/GAWorld/scripts/deploy_services.py watch --repo %h/GAWorld --branch Dev --process-manager systemd-user --host 0.0.0.0 --dashboard-port 8766 --relay-port 8877 --interval 60 --skip-install
Restart=always
RestartSec=10

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now gaworld-deploy-watch.service
```

如果后续依赖变化频繁，可以去掉 `--skip-install`，让每次部署都执行
`pip install -r requirements.txt`。

如果使用本次集成分支验证：

```bash
nohup python "$HOME/GAWorld/scripts/deploy_services.py" watch \
  --repo "$HOME/GAWorld" \
  --branch integration/latest-dev-2026-09-04 \
  --process-manager systemd-user \
  --host 0.0.0.0 \
  --dashboard-port 8766 \
  --relay-port 8877 \
  --interval 60 \
  > "$HOME/GAWorld/runtime/services/deploy-watch.log" 2>&1 &
```

## 无 Git 同步重启

如果只想用服务器当前 checkout 重启服务：

```bash
python scripts/deploy_services.py restart \
  --repo "$HOME/GAWorld" \
  --host 0.0.0.0 \
  --dashboard-port 8766 \
  --relay-port 8877
```

## 数据位置

需要保留的数据：

```text
output/dashboard/todo_board.json
output/distributed/relay_state.json
runtime/services/*.pid
runtime/services/*.log
```

看板页面：

```text
http://<server>:8766/board
```

Dashboard：

```text
http://<server>:8766/dashboard
```

Relay：

```text
http://<server>:8877/health
```

## 访问控制（对外暴露前必读）

Dashboard 以仓库根目录提供静态文件。以点开头的路径（`/.env`、`/.git/…`）一律返回 404，
无需配置——此前它们可以被直接下载，其中 `.env` 含真实 API key。

静态文件同时是白名单：只放行 `/site/`、`/docs/`、`/video/public/`、`/output/population/`、
任意 `output/…/visualization/` 目录（回放 trace 与头像）、文档面板列出的根目录文档（`README.zh-CN.md`、`AGENTS.md`、`CHANGELOG.md`）以及 `/`、`/console`、`/dashboard`、`/board` 等页面入口。
源码、`dashboard_config.json`、`data/`、`output/memory` 等其余路径一律 404，数据只经 `/api/` 读取。

以 `--host 0.0.0.0` 暴露时，务必再设置访问令牌。令牌只从环境变量读取
（不放进 `dashboard_config.json`，因为 `POST /api/config` 能改写那个文件）：

```bash
# nohup / 手动启动：启动前导出
export GAWORLD_DASHBOARD_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')"

# systemd-user：写进 gaworld-dashboard.service 的 [Service] 段
Environment=GAWORLD_DASHBOARD_TOKEN=<令牌>
```

设置后**所有**请求（API 与静态页）都需要令牌：

- 浏览器：打开一次 `http://<host>:8766/?token=<令牌>`，服务端写入 HttpOnly、SameSite=Strict 的
  cookie 并跳转去掉 URL 中的令牌，之后控制台正常使用（含 `/api/events/stream`）。
- 脚本：`Authorization: Bearer <令牌>`。
- 请求日志中的 `token=` 会被打码。

未设置时行为与以前相同（不鉴权），适合只绑 `127.0.0.1` 的本机使用。

### 多人账号（课堂 / 工作坊）

多人共用一台服务器时开启账号。账号库是开关：库不存在时一切照旧；创建后控制台需要登录。

```bash
python -m gaworld.accounts init --admin 老师                 # 建库 + 第一个管理员（交互输入密码）
python -m gaworld.accounts invite --count 30 --label 周三班  # 打印 30 个一次性邀请码（默认 14 天有效）
python -m gaworld.accounts invite --count 3 --can-create-city  # 这批人可以建立城市
python -m gaworld.accounts users
python -m gaworld.accounts reset --nickname 小王             # 打印一次性重置码（24 小时有效）
python -m gaworld.accounts city-permission --nickname 小王 --allow
```

- **教师控制台**：管理员登录后，控制台「系统」组里出现「教师控制台」页签——生成 / 作废邀请码、看名单（在线状态、
  今日与累计模型调用）、开关建城权限、重置密码、调整班级上限、查看并代为停止所有世界、向选定世界广播一个全员
  生活事件、导出多人共玩记录、看审计。下面的命令行和 `curl` 是同样功能的脚本入口。
- 学生打开 `http://<host>:8766/join?code=<邀请码>`，填昵称并**必须设置密码**（至少 8 位）；之后在 `/login` 用昵称 + 密码登录。
  忘记密码：管理员发重置码，学生打开 `/reset?code=<重置码>`。
- 账号库在 `output/accounts/accounts.sqlite`（可用 `GAWORLD_ACCOUNTS_DB` 改路径），不会被当作静态文件提供。
- `GAWORLD_DASHBOARD_TOKEN` 持有者仍是管理员，运维脚本照常用 `Authorization: Bearer`。
- **世界**：每个学生在控制台顶栏「管理世界」里新建自己的世界（选一座有居民的城市），居民会复制一份进
  `output/worlds/<id>/`，之后在这个世界里改配置、启停仿真、编辑居民都只影响自己。世界默认私有；可设为
  「班级」或「开放」让别人只读查看。顶栏下拉框切换当前世界（全浏览器生效）。
- **多人共玩**：把世界设为「开放」后，其他人切到这个世界，在「多人共玩」页签认领一位居民，写下他这一步做什么、
  对谁说什么，下一个 tick 生效；没人扮演的居民照常由模型驱动，玩家离开两分钟后居民自动交还。世界属主可在
  「管理世界」里设「每个 tick 等玩家（秒）」让课堂讨论跟得上（默认 0 = 不等）。
- 共享的默认世界所有人可读、只有管理员能改。采访、游戏、研究分析、人物蒸馏任何人可用；有建城权限的人可以
  建城并只能修改自己建的城。模型设置、切换默认世界的城市、大五人格、生命事件、各类删除只限管理员。
  规则见 `gaworld/accounts/policy.py`，设计见 `docs/proposals/2026-10-01-multi-user.md`。
- **同时运行的仿真数**：全服默认 4 个、每人 1 个（管理员不受个人上限），超出的自动排队、空出名额后按先后启动。
  管理员随时调整，无需重启：

  ```bash
  curl -X POST -H "Authorization: Bearer $GAWORLD_DASHBOARD_TOKEN" -H "Content-Type: application/json" \
       -d '{"max_concurrent_runs": 6, "max_runs_per_user": 1}' http://127.0.0.1:8766/api/worlds/settings
  ```
- **结果归属**：采访、研究方案、人物蒸馏、严肃游戏、政策仿真和各类游戏的结果只有创建者（和管理员）能看到、
  删除；严肃游戏的席位链接仍可发给别人入座。账号开启前留下的旧结果只有管理员可见。
- **大模型用量与配额**：每次模型调用都记一笔（`output/accounts/usage.jsonl`），管理员看
  `GET /api/auth/usage`（每人今日 / 累计调用次数）。可设每人每日上限（默认 0 = 不限），用完后学生不能再发起
  仿真、采访、游戏等新的模型工作（已在跑的不受影响）：

  ```bash
  curl -X POST -H "Authorization: Bearer $GAWORLD_DASHBOARD_TOKEN" -H "Content-Type: application/json" \
       -d '{"daily_llm_calls_per_user": 2000}' http://127.0.0.1:8766/api/worlds/settings
  ```
- 每个写请求都记入审计；管理员可读 `GET /api/auth/audit`。

## 反向代理注意事项

`/board` 页面依赖这些路径都转发到 8766：

```text
/board
/dashboard
/api/todos
/api/todos/create
/api/todos/create-form
/api/todos/update
/api/todos/clear
/site/
/output/
/video/
```

如果 `/api/todos` 返回 HTML，浏览器会报 `Unexpected token '<'`；如果 `/api/todos/create-form` 返回 Nginx `405 Not Allowed`，说明 POST 没有代理到 8766。

Relay 如果走路径前缀，例如 `/agent-relay/`，反向代理需要把前缀剥掉后再转发到 8877，因为服务端实际路径是：

```text
/health
/register
/directory
/message/send
/message/poll
/social/snapshot
```
