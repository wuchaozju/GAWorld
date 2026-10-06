# GAWorld 多用户服务器配置

适用于合并后的 main 服务器部署，不改变单人开发环境的默认行为。
账号数据库不能提交到 Git；只合并代码不会自动创建账号。

## 启用账号

先备份已有账号库、`output/worlds/`、看板和孪生数据。若已有账号库，继续使用其绝对路径，
不要新建一个空库来替代它。下面是首次部署的示例：

```bash
cd "$HOME/GAWorld"
umask 077
mkdir -p "$HOME/.local/share/gaworld"
export GAWORLD_ACCOUNTS_DB="$HOME/.local/share/gaworld/accounts.sqlite"
.venv-deploy/bin/python -m gaworld.accounts init --admin 老师
.venv-deploy/bin/python -m gaworld.accounts users
```

管理员密码在终端交互输入，不放进命令参数、仓库或部署说明。
已有用户时 `init` 会拒绝覆盖，忘记密码应使用 `reset --nickname`。
后续 `invite`、`users`、`reset` 命令都必须使用相同的 `GAWORLD_ACCOUNTS_DB`。

安装随仓库提供的 systemd 配置：

```bash
mkdir -p "$HOME/.config/systemd/user/gaworld-dashboard.service.d"
install -m 600 deployment/multi-user/gaworld-dashboard.conf \
  "$HOME/.config/systemd/user/gaworld-dashboard.service.d/multi-user.conf"
systemctl --user daemon-reload
systemctl --user restart gaworld-dashboard.service
curl -fsS http://127.0.0.1:8766/api/health
```

预期 JSON 为 `ok: true`、`service: gaworld-dashboard`、`accounts: true`、
`accounts_required: true`。未登录请求 `/api/config` 应返回 401，控制台应跳转 `/login`。
`GAWORLD_REQUIRE_ACCOUNTS=1` 是部署保护开关：数据库丢失、损坏或没有管理员时返回 503，
不会退回匿名可操作的单人模式。不开此开关的本机开发环境仍保留原有行为。

非 systemd 启动时，在同一进程环境设置上述数据库路径和
`GAWORLD_REQUIRE_ACCOUNTS=1`，再运行原来的 dashboard 命令。

## 教师和成员使用

1. 教师访问 `/login`，使用初始化的管理员账号登录。
2. 在教师控制台创建邀请码，发给成员 `/join?code=<一次性邀请码>`。
3. 成员注册后各自创建世界，在自己的世界内配置居民、启动仿真和查看结果。
4. 教师可设置并发上限、查看世界和停止运行。世界默认私有，共玩需要明确调整可见性。

已登录成员可以提交、认领和更新团队看板任务；清空和批量替换仍仅限管理员。
未登录访客不能提交。权限定义在 `gaworld/accounts/policy.py`。

## 正式版本和测试目录分离

正式目录 `%h/GAWorld` 部署 `main`。把 `gaworld-deploy-watch.conf` 安装为
`~/.config/systemd/user/gaworld-deploy-watch.service.d/main.conf`，替换旧的 Dev 监听命令。

测试目录先单独创建：

```bash
git -C ~/GAWorld worktree add -b testing/Dev ~/GAWorld-test origin/Dev
```

把 `gaworld-test-loop.conf` 安装为
`~/.config/systemd/user/gaworld-test-loop.service.d/isolated.conf`。
测试会在独立 worktree 快进到 `origin/Dev`，不会切换线上目录的分支；
有已跟踪文件修改、fetch 失败或不能快进时不运行混合版本。
安装完成后 `systemctl --user daemon-reload`，再重启对应服务。

`main` 的 push 权限必须限制给发布维护者；CLI 的健康检查不替代发布前的审查和测试。

## 公网入口

`deployment/public/Caddyfile` 包含 `/login`、`/join`、`/reset`、`/play/*` 和账号 API。
它保留原有网关 Basic Auth，浏览器可能先要求网关密码，再要求个人账号。
不要在账号库未就绪时移除网关认证。多用户账号不负责独立 Relay 和手机孪生服务的认证。

`mo.zju.edu.cn` 还需要入口管理员应用 `deployment/public/mo-gaworld.locations.conf` 中的
相应 location。它是共享站点，不能笼统接管整个 `/api/`。先检查已有同名路径，
执行 `nginx -t` 后再 reload；仅提交本仓库并不能修改 mo 的入口配置。

自动部署 CLI 已改用 `/api/health`，并校验 JSON 内容和服务标识；
登录页面、其他平台 HTML、401 或 503 均不会被当作部署成功。
完整校验仍应包含登录、创建私有世界、跨用户访问拒绝和一次短仿真，
健康检查并不证明 LLM、全部实验或外部服务可用。

## 回滚边界

回滚代码前保留数据库和所有世界目录的备份。不要通过删除数据库来恢复访问，
也不要直接运行旧版 main 读取新版世界数据。主线切换和服务器升级是两个独立动作，
必须分别核对 Git 提交号、运行进程和公网访问结果。
