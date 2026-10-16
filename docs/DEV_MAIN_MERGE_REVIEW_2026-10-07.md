# Dev → main 合并审查与发布说明

## 目标与边界

- 让 `main` 包含截至 `a2111b6` 的全部 Dev 主线功能，避免同学 checkout main 后拿到数月前的版本。
- 正式部署跟踪 main；Dev 的长期测试使用独立 worktree，不再切换线上代码目录。
- 在 13 号服务器启用已有的邀请码注册、多用户登录、世界隔离及教师控制台。
- 本次不是全量重构，也不是一次真实 LLM 长周期实验验收。自动化测试主要使用 mock LLM。

## 合并依据

| 项目 | 版本 |
| --- | --- |
| 合并前远端 main | `ebdad18ce2e28cba030ded918641f7f3a324db83` |
| 合并前远端 Dev | `a2111b6`，2026-10-05，indoor |
| 共同祖先 | `e9b802af0ce2d169054f34b8ac73c47fd21b547c` |
| main 独有历史 | 61 个提交 |
| Dev 独有历史 | 211 个提交 |
| 旧 main 完整归档 | `archive/main-before-dev-2026-10-06`，指向 `ebdad18` |
| 本地审查工作区 | `/Users/michaelf/GAWorld-main-integration` |

在 Dev 基础上先提交多用户部署保护修复 `a4a9a86`，再进行普通双亲合并 `840fac6`；
不是强推覆盖 main，也不是把所有冲突简单选一边。归档保留旧模型、入口、测试、报告及完整 Git 历史。

用户已明确确认三个决定：

1. 以 Dev 连续情绪、新版社交模型作为新主线，旧 main 的离散情绪模型归档。
2. 旧 Personal What-if、规划 AB 入口一并归档，使用 Dev 的研究工作台 / 平行世界。
3. 原品牌图片无法提供，先移除失效图片引用、保留 GAWorld 文字品牌。

## 17 个文本冲突的处理

| 冲突文件 | 冲突性质与风险 | 合并决定 |
| --- | --- | --- |
| `README.md` | 旧实验说明与新版模块、命令目录不一致 | 保留 Dev 主线说明；旧实验见归档和本报告 |
| `README.zh-CN.md` | 同上，旧入口容易误导新用户 | 同上 |
| `config.py` | main 修改根模块，Dev 已移到 `gaworld.settings` | 保留 Dev 删除，避免两套配置源 |
| `dashboard_config.json` | 旧实验开关与新版城市 / 模型配置不同 | 保留 Dev 基线；服务器本地配置另做备份，不写入凭据 |
| `dashboard_server.py` | main 为大型旧实现，Dev 为兼容启动脚本 | 保留 Dev 入口，正式逻辑在 `gaworld/apps/` |
| `data/hangzhou_agents_state_init.csv` | 同一 Agent ID 指向不同人 | 保留 Dev：52 王思颖、53 郭林峰，不静默覆盖 |
| `data/hangzhou_profiles_with_names.v1.md` | 人物档案 ID 与 CSV 必须一致 | 跟随 Dev 的 52/53 映射 |
| `distributed_comm_server.py` | 旧 main 新增社交摘要，Dev 已迁移模块 | 根入口保留 Dev；main 的摘要、边、统计迁入正式模块，并兼容旧状态文件 |
| `gaworld/cognition/realism.py` | main 写入 0–4 整数情绪，Dev 使用连续值 | 按已确认的模型决策保留 Dev，禁止跨模型直接比较实验数值 |
| `generative_city_sim.py` | 生命周期、规划、关系衰减、旧 What-if 的语义冲突 | 保留 Dev 插件主线；旧实验运行路径归档，不复制回单体脚本 |
| `llm_providers.py` | 根模块与 `gaworld.llm` 的架构冲突 | 保留删除；不恢复第二套路由实现 |
| `news_cache.json` | 旧生成缓存与新版路径规则冲突 | 不恢复旧根缓存，避免实验缓存污染新版本 |
| `pyproject.toml` | 包结构、入口和测试标记差异 | 以 Dev 打包结构为准，保留 integration 测试标记 |
| `site/dashboard/app.js` | 旧面板与新版多用户、世界、研究工作台流程不兼容 | 保留 Dev 工作流，旧实验页面归档 |
| `site/dashboard/index.html` | 页面结构与脚本依赖成套变化 | 保留 Dev 页面；另修复缺失依赖和失效品牌引用 |
| `site/dashboard/styles.css` | 新旧布局类和结构不同 | 跟随 Dev 页面，不混搭旧版样式 |
| `tests/test_distributed_comm.py` | 两条分支各有有效 Relay 用例 | 合并两侧测试，改用正式模块导入；增加迁移和隐私边界测试 |

注意：旧 main 实验中的 Agent 52 是郭林峰。旧实验仍按原 ID 解释，不能把历史输出重新标成王思颖。

## 没有冲突标记，但需要处理的问题

### 环境配置语义回退

Git 自动合并 `data/environment_config.json` 时，会把旧实验关闭环境模块的设置带回新版。
这会改变 Dev 默认仿真行为，因此恢复 Dev 配置，而不是把“没有文本冲突”当成正确合并。

### 旧实验资产归档

旧 LifeHistory / Personal Twin 状态模型、规划 AB 引擎及配套评估脚本、报告、测试、
`sitecustomize.py`、旧 Dashboard 图表入口和运行产物保留在归档分支，不继续装配到新版运行时。
旧根配置备份、临时头脑风暴产物、生成图片 / PDF / SQLite 不带回新主线。
对应旧测试随其测试对象一起归档，不拿它们验证一个已经替换语义的模型。

独立可用的 Relay 社交摘要没有丢弃：迁入 `gaworld/apps/distributed_comm_server.py`，
配套客户端和 OpenClaw Bridge 一并整合。旧 Dev Relay 状态加载时重建边与统计，持久化后不重复计数。
保留 Dev 的 source / target 字段兼容性。摘要接口不再回退显示私信原文；private / ephemeral 消息不公开摘要。
账号系统不覆盖独立 Relay 和 Twin 服务，不能把 Dashboard 登录当作这两个服务的访问控制。

### 被忽略的前端文件

`.gitignore` 的 `/site/*` 排除了页面仍在引用的主题脚本、共享样式和 Phaser 引擎。
Git 历史和服务器均没有这些文件，导致页面可打开但部分功能仍不可用。

- 补齐 `theme.js`、主题测试、共享样式；原主题变量及页面布局仍沿用 Dev。
- `/` 进入现有 Console；旧 terminal 回放地址重定向到维护中的 simviz 页面。
- 将项目文档指定的 Phaser 3.90.0 本地化，保留 MIT 许可证、来源和 SHA-256。
- 增加页面脚本 / 样式 / 图片引用完整性检查，防止再次只提交 HTML、不提交依赖。
- 移除缺失的品牌 PNG 引用，保留文字品牌；不是另造一个未经确认的 Logo。
- 修复手机端多用户顶部栏溢出，并让管理世界、退出登录在手机上可操作。

另删除两个重复字典键中已被覆盖的旧条目，保留 Python 原本实际生效的后一个值，不改变模型结果。

## 用户注册如何开启

这版 Dev 不是靠 `dashboard_config.json` 中一个 `multi_user=true` 字段开启。
`gaworld.accounts` 使用账号数据库作为开关：创建管理员后才能生成邀请码，学生用邀请码注册。

生产部署配置见 `deployment/multi-user/`：

```ini
Environment=GAWORLD_REQUIRE_ACCOUNTS=1
Environment=GAWORLD_ACCOUNTS_DB=%h/.local/share/gaworld/accounts.sqlite
```

- 数据库放在 Git 工作区外，升级代码不会覆盖账号。
- required 模式在数据库丢失、损坏或没有管理员时返回 503，不会退回匿名可写模式。
- 管理员从教师控制台发邀请码；学生打开 `/join?code=...`，设置昵称和密码。
- 已注册用户从 `/login` 登录。普通成员可提交 / 认领 / 更新看板，清空仍需管理员权限。
- 个人世界隔离由 Dev 现有 accounts / worlds / ownership / cluster 机制执行。
- `/api/health` 为独立 JSON 健康接口，能区别登录要求、错误反代 HTML 和服务就绪。
- main 包含启用配置和操作说明，但不提交管理员密码或账号数据库；普通本地 clone 仍可使用单用户模式。

## 部署与后续协作

1. 同学从最新 `origin/main` 拉出自己的功能分支，功能先提交 PR 到 `Dev`。
2. Dev 在独立 `GAWorld-test` worktree 做测试；不要在正式目录里运行会切分支的测试脚本。
3. Review 检查文本冲突、模型语义、API / 数据契约、身份映射、依赖完整性和权限隔离。
4. 通过功能回归后由维护者合并到 main；本次发布会将集成修复同步回 Dev，避免下轮再出现分叉。
5. 正式 `GAWorld` 目录只跟踪 main。CLI 快进更新、重启 Dashboard / Relay、检查 JSON 健康并记录部署 SHA。
6. Twin 使用单独 worktree，单独更新并保留原绑定文件和报告路径。
7. 推送前保存旧 main 归档；部署前备份 systemd / Caddy 配置、看板、Relay 状态、Twin 绑定与报告。

CLI 的健康探针不等于所有仿真任务都成功，也不自动检查真实 LLM 供应商。
GitHub 分支保护需要仓库管理权限另行配置；本次不宣称仅凭仓库内文件就已强制所有人遵守流程。

## 验证记录

- 初次核心回归：473 通过，1 失败；失败为缺失品牌 PNG，已按用户确认修复。
- 初次完整回归：3675 通过，3 失败，1 跳过，947 子测试通过；失败均为缺失前端文件。
- 注册 / 登录 / 部署 / Relay 专项：52 通过。
- 缺失依赖修复及部署隔离专项复测：43 通过。
- 普通成员看板提交 / 认领及部署权限复测：23 通过，包含 JSON 和 HTML form 提交。
- 13 号服务器 Linux 隔离 worktree：账号、世界、部署、Relay、前端依赖及回放专项 79 通过。
- Node 前端测试：155 项通过，0 失败。
- 浏览器：真实填写邀请码注册，普通成员登录、退出再登录成功；390px 手机及 1440px 桌面截图检查，无静态资源加载错误，手机无横向溢出。
- 最终完整回归：3683 通过、1 跳过、947 子测试通过；耗时 611.37 秒。
  唯一跳过是翻译键未按字母排序的外观检查；没有跳过注册或仿真功能用例。
- 覆盖率（含分支统计）：83.45%，通过原有 80% 门槛。未缩减 coverage 统计范围。
- 最终回归使用无效的本机 HTTP 代理让外网请求快速失败，并对 loopback 放行，
  避免测试等待外部新闻服务；这不是实际 LLM 联网验收，也不是操作系统级断网隔离。

复现最终回归（先安装项目运行和测试依赖）：

```bash
HTTP_PROXY=http://127.0.0.1:9 HTTPS_PROXY=http://127.0.0.1:9 \
ALL_PROXY=http://127.0.0.1:9 NO_PROXY=127.0.0.1,localhost,::1 \
python -m pytest --suite full --cov=gaworld --cov-fail-under=80
```

原始本地记录：`/tmp/gaworld-main-final-offline.xml`、
`/tmp/gaworld-main-final-offline-coverage.json`。
服务器专项记录：`~/gaworld-backups/release-20261007/server-tests.xml`。
测试记录不等于部署完成凭据；上线后还需分别核对提交号、进程和认证。

## 仍需明确的限制

- Dev 基线存在大量 Ruff 存量问题：本次统计全库仍有 1055 项，未用大范围自动重写掩盖这些债务。
  未定义变量 / 重复定义 / 重复字典键等关键规则检查已通过，但不等于全库 lint 全绿。
- 原有 CI 的完整 Ruff / 格式门槛仍可能失败；没有悄悄关闭这些检查或降低覆盖率门槛。
- 自动化主要验证 mock LLM 路径，真实模型费用、长时运行和每个研究场景仍需专项实验。
- `mo.zju.edu.cn` 的入口 Nginx 由兆丰管理。本仓库只能提供配置，不能宣称已替他修改公网入口。
- 公网 Gateway 的共享 Basic Auth 暂保留；它与每个人的 GAWorld 账号是两层不同认证。
- 旧模型实验与新 Dev 模型不可直接合池比较；归档保证可追溯，不保证跨版本数值相等。
