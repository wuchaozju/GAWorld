# GAWorld 项目周报（2026-09-06）

## 一、本周工作概述

本周主要围绕 GAWorld 项目的团队协作、代码合并、测试环境和服务器部署做整理。核心目标是把目前分散在不同同学分支里的功能逐步统一到 `Dev` 分支，并让老师和同学可以在服务器上直接测试最新版本，而不是继续看到几个月前的旧服务。

目前已经完成了一版可运行、可测试、可持续迭代的集成环境：最新代码已合并并推送到 GitHub `Dev` 分支，13 号服务器已经切换到最新 `Dev`，看板、Dashboard、Agent Relay、长期测试循环和自动部署 watcher 都已经启动。

## 二、代码合并与分支管理

### 1. 建立合并流程

根据老师提出的要求，我整理了后续团队协作流程：

```text
每位同学个人分支
        ↓
先合并到 Dev
        ↓
服务器测试环境自动测试
        ↓
测试通过后再合并到 main
```

这样做的目的是避免所有人直接往 `main` 合并，降低主分支被冲突代码或未验证功能破坏的风险。`Dev` 作为集成测试分支，负责承接各个同学的功能；`main` 保持稳定版本，只在 `Dev` 经过测试和 Review 后更新。

### 2. 处理现有分支合并

本周先基于最新 `origin/Dev` 做了一轮集成，重点处理了非 `tf` 分支中可以判断并安全合入的内容，包括：

- 合入王思颖相关 Agent 资料与 profile 数据。
- 合入郭林峰相关关系阶段逻辑和 profile 数据。
- 合入 Personal Twin / Agent Relay 社交快照相关能力。
- 保留最新 `Dev` 中已经完成的新版 Dashboard、长期仿真和配置系统，避免用旧分支代码覆盖新结构。

这次合并没有采用简单覆盖文件的方式，而是逐项判断哪些内容应该进入统一版本，哪些内容可能造成回退或重复实现。冲突主要集中在 profile 文件尾部追加、Dashboard 旧实现与新实现差异、环境模块迁移等位置；能明确判断的冲突已经处理，无法确认的旧大块改动没有强行覆盖。

当前最新统一分支：

```text
GitHub 分支：Dev
最新 commit：d5894a0
```

## 三、团队看板与 Dashboard

### 1. 看板功能改造

本周把团队看板从前端本地存储改成服务器统一保存，解决了之前“不同人看到的数据不一致”“提交按钮没有反应”“刷新后数据丢失”等问题。

当前看板支持：

- 提交新任务或新想法。
- 认领任务负责人。
- 修改任务状态。
- 按状态筛选。
- 按标题、提出人、负责人、说明内容搜索。
- 服务器端持久化保存。

看板数据保存位置：

```text
output/dashboard/todo_board.json
```

主要接口：

```text
GET  /api/todos
POST /api/todos
POST /api/todos/create
POST /api/todos/create-form
POST /api/todos/update
POST /api/todos/clear
```

其中 `/api/todos/create-form` 是无 JavaScript 兜底接口，即使前端脚本异常，也可以通过普通表单提交写入服务器。

### 2. 页面风格

看板页面也按老师之前希望的方向做了调整，整体更接近苹果页面风格：界面更干净、留白更明确，任务卡片、输入区域、筛选区域和状态标签的视觉层级更清楚，方便大家日常使用和老师集中 Review。

当前访问地址：

```text
内网看板：http://10.72.74.13:8766/board
内网 Dashboard：http://10.72.74.13:8766/dashboard

公网看板：https://mo.zju.edu.cn/board
公网 Dashboard：https://mo.zju.edu.cn/dashboard
```

## 四、Agent Relay 与远程 Agent 测试

本周也检查并部署了 Agent Relay 服务，用于支持不同 Agent 以 Remote 的方式加入系统，进行注册、消息发送、消息轮询和社交状态同步。

当前 Relay 服务在 13 号服务器上运行：

```text
内网 Relay：http://10.72.74.13:8877/health
```

已经验证内网 Relay 健康检查正常返回：

```json
{"ok": true}
```

目前公网看板已经可用，但公网 Relay 子路由仍有一个平台侧反向代理问题：

```text
https://mo.zju.edu.cn/agent-relay/health
```

该地址目前返回的是 mo 平台 HTML，而不是 Relay 的 JSON，说明 `/agent-relay/` 还没有正确反代到 `10.72.74.13:8877`，或者没有剥掉路径前缀。服务器上的 Relay 本身是正常的，剩下需要平台侧继续调整 Nginx。

## 五、服务器部署与自动化测试

### 1. 13 号服务器部署

已经将 13 号服务器从旧 `tf` 分支切换到最新 `Dev` 分支。当前状态如下：

```text
服务器：10.72.74.13
代码目录：/home/ft/GAWorld
当前分支：Dev
当前 commit：d5894a0
Python 环境：.venv-deploy / Python 3.12.13
```

当前运行中的服务：

```text
gaworld-dashboard.service
gaworld-agent-relay.service
gaworld-test-loop.service
gaworld-deploy-watch.service
```

其中：

- `gaworld-dashboard.service` 负责 Dashboard 和团队看板。
- `gaworld-agent-relay.service` 负责远程 Agent Relay。
- `gaworld-test-loop.service` 负责长期测试 `Dev` 分支。
- `gaworld-deploy-watch.service` 负责监控 GitHub `Dev`，发现新 commit 后自动部署。

### 2. 自动部署机制

本周新增了可复用的部署 CLI：

```text
scripts/deploy_services.py
gaworld/apps/deploy_services.py
```

支持命令：

```text
deploy   拉取代码、安装依赖、重启服务、健康检查
restart  基于当前代码重启服务
status   查看服务状态
watch    轮询 GitHub 分支，有新 commit 自动部署
```

针对当前服务器已有 systemd 服务的情况，CLI 增加了 `systemd-user` 模式，避免重复启动进程抢占端口。自动部署 watcher 每 60 秒检查一次 `Dev` 分支，如果发现新版本，会自动拉取代码并重启 8766 和 8877 两个服务。

自动部署记录文件：

```text
runtime/services/deployed-rev
```

这样即使长期测试循环提前 `git pull Dev`，自动部署 watcher 仍然能根据 `deployed-rev` 判断当前 commit 是否已经真正重启到服务上。

## 六、测试与验证结果

本地完成过完整回归测试：

```text
1669 passed, 1 skipped
```

服务器切换到最新 `Dev` 后，也完成了第一轮服务器端全量测试：

```text
1671 passed, 1 skipped, 306 warnings
```

其中 skip 是 i18n key 排序的非阻塞项；warnings 主要是 matplotlib 中文字体缺字警告，不影响核心逻辑。

同时完成了服务端访问验证：

```text
内网 /board      200
内网 /dashboard  200
内网 /api/todos  JSON 正常
内网 /health     Relay 正常

公网 /board      200
公网 /dashboard  200
公网 /api/todos  JSON 正常
```

看板提交链路也已经实测，包括：

- JSON 接口 `/api/todos/create`
- 表单兜底接口 `/api/todos/create-form`

测试时创建了临时任务，验证成功后已经清理，没有污染团队看板数据。

## 七、本周工作意义

这部分工作的意义主要有三点。

第一，项目协作方式从“每个人分支各做各的”开始转向统一集成。后续大家可以基于最新 `Dev` 拉分支开发，避免长期分叉后一次性合并造成更大冲突。

第二，老师和同学现在可以通过服务器测试最新版本。之前线上页面和服务器还停留在旧 `tf` 分支，所以老师看到的是几个月前的内容；现在 13 号服务器已经切到最新 `Dev`，可以作为团队测试环境使用。

第三，自动部署和长期测试机制已经初步建立。以后 `Dev` 有新提交后，服务器可以自动拉取和重启服务，长期测试循环也会持续验证 `Dev`，这能让代码整合、测试和 Review 形成闭环。

## 八、后续计划

下一步建议继续推进以下工作：

1. 让同学统一基于最新 `Dev` 重新拉自己的开发分支。
2. 后续所有功能先合入 `Dev`，不要直接进入 `main`。
3. 老师 Review 通过并且服务器测试稳定后，再执行 `Dev -> main`。
4. 继续整理各同学分支中还未合并的功能，遇到功能级冲突时先本地测试，再决定合并方式。
5. 协调 mo.zju.edu.cn 平台侧补齐 `/agent-relay/` 的反向代理配置，让公网 Agent Relay 也能访问。

## 九、可给老师的简短汇报口径

本周已经把 GAWorld 的最新集成版本合并到 `Dev` 分支，并部署到了 13 号服务器测试环境。服务器当前运行的已经不是旧 `tf` 分支，而是最新 `Dev@d5894a0`。团队看板、Dashboard 和 Agent Relay 均已启动，内网访问和看板提交接口验证通过；服务器上也配置了长期测试循环和自动部署 watcher，后续 `Dev` 有新 commit 会自动拉取并重启服务。服务器端第一轮全量测试结果为 `1671 passed, 1 skipped`。目前剩余问题是公网 `/agent-relay/` 子路由还需要平台侧继续配置 Nginx 反向代理。
