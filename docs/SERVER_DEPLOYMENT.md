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

## 状态检查

```bash
python scripts/deploy_services.py status \
  --repo "$HOME/GAWorld" \
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

## 自动部署

长期轮询远端分支，发现新 commit 后自动部署：

```bash
mkdir -p "$HOME/GAWorld/runtime/services"
nohup python "$HOME/GAWorld/scripts/deploy_services.py" watch \
  --repo "$HOME/GAWorld" \
  --branch Dev \
  --host 0.0.0.0 \
  --dashboard-port 8766 \
  --relay-port 8877 \
  --interval 60 \
  > "$HOME/GAWorld/runtime/services/deploy-watch.log" 2>&1 &
```

如果使用本次集成分支验证：

```bash
nohup python "$HOME/GAWorld/scripts/deploy_services.py" watch \
  --repo "$HOME/GAWorld" \
  --branch integration/latest-dev-2026-09-04 \
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
