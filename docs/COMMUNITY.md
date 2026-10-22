# 公开研究社区与个人工作空间

个人工作空间入口是 `/workspace`，公共发现页为 `/explore`，讨论广场为 `/plaza`。游客可以阅读已发布成果和讨论；账号注册、私人研究、成果发布及社区管理通过现有 Dashboard 服务提供。

## 部署

Dashboard 默认以单用户模式启动，即使已有账号库、配置了开放注册或旧的账号环境变量，也不会自动开启多用户限制。原有单用户研究、仿真、居民、游戏、设置等功能保持可用。

```bash
python generative_city_sim.py dashboard
# 显式关闭，与默认行为相同
python generative_city_sim.py dashboard --multi-user False
# 开启多用户登录与隔离
python generative_city_sim.py dashboard --multi-user True
```

`python dashboard_server.py` 与 `python -m gaworld.apps.dashboard_server` 支持相同参数；`--multi_user` 是兼容别名，单写 `--multi-user` 等同于 True。

开启后，游客仍可阅读首页、公共社区及登录注册页；研究、仿真、居民、游戏、设置等具体功能页及其接口均要求登录，直接输入 URL 也会校验。**多用户模式需要已初始化的账号库与管理员；缺失时启动报错，运行中账号库失效时返回 503，不会退回匿名模式。**

先备份现有账号库与 `output/`。

使用项目 Python 创建管理员，交互输入密码，不在命令中写密码：

```bash
python -m gaworld.accounts init --admin <管理员用户名>
```

完成管理员初始化后，为服务进程配置：

```bash
export GAWORLD_REGISTRATION=open
export GAWORLD_REQUIRE_ACCOUNTS=1
export GAWORLD_PUBLIC_URL=https://research.example.org
export GAWORLD_SMTP_HOST=smtp.example.org
export GAWORLD_SMTP_PORT=587
export GAWORLD_MAIL_FROM=research@example.org
export GAWORLD_SMTP_USER=<SMTP账号>
# GAWORLD_SMTP_PASSWORD 通过部署环境的秘密配置注入
python -m gaworld.apps.dashboard_server --multi-user True
```

通过 HTTPS 反向代理暴露服务，保留正确 Host。账号 Cookie 在 `GAWORLD_PUBLIC_URL` 为 HTTPS 时自动启用 Secure；SMTP 使用验证证书的 STARTTLS。确认代理层也限制请求体、连接超时和请求频率。

注册页需要唯一用户名、公开显示名、邮箱与密码。邮箱验证前允许查看自己的空工作空间，但不能提交模型任务、发布或评论。验证与找回密码链接一小时有效、只能使用一次；密码重置使旧会话失效。

邀请码仍可通过原有 CLI 创建，并可在开放注册模式下使用。旧账号保持原昵称登录，新显示名不改变登录用户名。纯邀请部署保留 `GAWORLD_REGISTRATION=invite`（默认）。

已有账号库首次升级时，会生成权限为 0600 的 `<账号库>.pre-community.sqlite`，随后添加扩展表和 schema 版本。备份只生成一次。回滚应先停止服务，再恢复账号库及同一时间点的产物；不要在运行中覆盖数据库。

## 开发验证

仅限本地开发，可配置显式邮件出口：

```bash
export GAWORLD_MAIL_MODE=outbox
export GAWORLD_MAIL_OUTBOX=/absolute/private/dev-mail-outbox
export GAWORLD_PUBLIC_URL=http://127.0.0.1:8766
```

邮件会写成仅当前用户可读的 JSON 文件，包含测试收件人和链接；服务端不假装发送外部邮件，也不把验证令牌放入注册 API 响应。出口目录不能放在公开静态目录。生产环境不要使用 outbox。

## 私人空间

- 总览聚合本人各世界的研究摘要；详情、运行、日志和导出继续检查用户和世界。
- 仿真世界使用独立居民副本、配置和输出目录。页面保留初始世界上下文；另一个标签页切换 Cookie 后，旧页面提交操作得到 409，需要刷新。世界上下文初始化失败时，浏览器拒绝后续变更请求。
- 个人工作空间可创建世界，进入已有研究/仿真工作台，配置模型，并查看发布、收藏和消息。
- 复制公开方案只创建私人草稿，保留版本与许可来源，清除原模型配置；用户选择自己的城市、居民和模型后再编译、启动。
- 现有无属主历史记录不会自动交给注册用户。认领或迁移历史资料仍需管理员单独处理。

## 发布与复用

在研究工作台或个人研究列表选择「发布成果 / 分享研究方案」，选择来源，编辑公开正文、方法、局限、引用与标签，选择许可及附件，检查预览后确认发布。

成果包含不可变版本；新修改创建新版本，讨论绑定对应版本。运行状态由来源确定，无运行来源的手工内容标记为方案。系统不会把未运行方案或失败研究升级为「已完成」。

**可复用方案单独选择公开。** 勾选后，下方及最终预览会展示完整的脱敏方案结构；这些字段可以被读者查看并按许可复制。未勾选时不会暗中通过复制功能共享私人设计。只选择 CC BY 或 CC0 许可，不会自动公开原方案。

首版附件支持显式上传 `.md`、`.txt`、`.csv`、`.json` 文本，每次最多八个、总内容最多 1 MB；不读取用户提交的服务器文件路径。研究正文以安全文本展示。当前仿真案例发布的是选定的说明与方法，私人实时世界和原始回放不会随之自动公开。

撤回使公开页面、附件、发现列表、收藏和关联通知停止返回内容；已经被别人下载的副本无法收回。管理员可以隐藏公开内容，不能替作者重新发布已撤回内容。私人源研究删除后，公开快照仍独立保存。

## 讨论与管理

广场支持研究问题、方法讨论和引用公开成果的分享帖。评论支持一级回复、编辑标记与历史存储、删除占位、收藏、举报、讨论锁定和站内消息；消息采用轮询读取。

管理员在 `/workspace?view=moderation` 查看举报、下架/恢复公开内容、锁定/解锁讨论、设置精选、禁用普通账号及授予社区版主。版主只能管理社区，不能因此访问其他人的私人研究。管理操作写入审计。

运维 Bearer token 仍可通过 API 管理社区；创作、私人工作空间和署名发布要求真实账号登录，避免将成果归入没有账号行的 id=0。

资源设置通过管理页或 `/api/community/settings`：

| 配置项 | 开放社区默认 | 语义 |
| --- | --- | --- |
| `max_worlds_per_user` | 20 | 每人世界数量，创建事务内检查 |
| `max_storage_mb_per_user` | 512 | 本人世界、研究与平行实验产物，提交新的模型任务前检查 |
| `max_community_storage_mb_per_user` | 50 | 草稿、版本、帖子、评论及编辑历史，写入事务内检查 |
| `max_pending_publications_per_user` | 100 | 未发布草稿数量，可删除不要的草稿 |
| `daily_llm_calls_per_user` | 沿用现有设置，未设置为 0 | 调用前原子预留，每次尝试结算，跨进程生效 |

0 表示不限制。**公网上线前，管理员应明确配置每日模型额度**，避免沿用不限额设置。私人文件存储限制是任务启动前的准入检查，已经运行的任务不会被此限制中途终止。社区大小统计是内容字节预算，不是 SQLite 文件物理大小；索引、通知和管理元数据还占用额外空间，应配合磁盘监控和部署级配额。

## 验证边界

自动测试与浏览器验收使用隔离账号库、测试邮件出口和确定性研究素材；没有启动真实模型研究，没有初始化生产管理员或把现有私人研究公开。邮件协议与失败处理经过替身测试，生产 SMTP 连通性需部署时验证。

后续组织协作、私信、实时群聊、共同编辑，以及图片/原始回放的专门发布体验，不属于本次社区首版。
