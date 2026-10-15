# GAWorld 项目交接文档

交接人：郭林峰（Git 作者 glf）
接收人：项目接手同事及主线维护者
核验日期：2026 年 10 月 12 日，北京时间
仓库：https://github.com/wuchaozju/GAWorld
当前主线基准：`6214b8c5cd12537c554147237ace9131f576f6da`

## 1 交接结论

我主要完成了早期 Dashboard 数据接口与可视化、技能展示、LifeHistory 多层状态与人格上下文集成、关系演化机制，以及 A/B 规划实验和分析报告工具。关系阶段等机制已被团队选择性集成到当前主线；旧 LifeHistory 和规划 A/B 运行链按 10 月模型整合决策保存在历史归档中。当前研究路径是插件内核、连续状态、研究工作台和平行世界。

**已提交的历史已经过主线整合，不应再次整条合并旧 glf。** 本次新增交付是贡献说明、服务器现场清单、未提交源码保全、代码审查、接手指南，以及在最新 Dev 上准备的少量可迁移改动。候选内容已获提交和创建 PR 的授权；是否合并以 GitHub PR 的审查与检查结果为准，不能将“已准备”或“已发起 PR”写成“已合并”。

接手时先阅读第 2、4、7、10 节。继续旧研究前阅读第 5、9 节，避免把旧模型结果与当前模型混合。

## 2 版本与服务器现场

### 2.1 版本身份

| 对象 | 核验值 | 含义 |
| --- | --- | --- |
| GitHub `Dev` | `6214b8c` | 目标开发分支，注意大写 D |
| GitHub `main` | `6214b8c` | 核验时与 Dev 相同，后续发布分支 |
| GitHub `glf` | `cec3342` | 2026-09-20 的旧合并版本 |
| 郭同学服务器 checkout | `/home/glf/projects/GAWorld`，`glf`，`cec3342` | 有未提交内容，不能直接覆盖 |
| 旧 main 归档 | `archive/main-before-dev-2026-10-06`，`ebdad18` | 保留旧模型、实验、报告及历史 |
| 既有审计分支 | `review/glf-audit-2026-10-07`，`81083d9` | 三份历史审计/验收资料，尚未进入当前 Dev |
| 本次候选隔离目录 | `/tmp/gaworld-handoff-20261012-NmpPSx/repo` | 基于最新 Dev 的待审核文件；临时目录不能作为唯一备份 |

服务器旧缓存显示 `glf` 领先 `origin/glf` 182 次，这是陈旧引用造成的。实际 GitHub glf 与服务器 HEAD 一致；相对最新 Dev，glf 独有 1 个合并提交，落后 36 个提交，没有独有的非合并提交。

`cec3342` 的父提交 `ebdad18` 和 `8f45771` 都已进入当前 Dev。2026-10-07 北京时间，`840fac6` 完成旧 main 与 Dev 的审查整合。两条分支存在两个最佳共同祖先，因此三点比较列出的 101 个文件不能直接视为“尚未合并的新功能”。10 月 7 日既有审计进一步做过真实试合并，保留逐项审核的主线内容后没有净代码变化。本轮重新核验了远端引用和祖先关系，未冒充重新执行了该历史试合并。

### 2.2 连接方式

使用已配置的 `glf-proxy` SSH 别名，具体账号、主机和端口由管理员私下提供。该别名包含隧道用途配置，执行远程命令时需要覆盖：

```powershell
ssh -o BatchMode=yes -o ConnectTimeout=10 -o ClearAllForwardings=yes -o SessionType=default -T glf-proxy
```

接手同事需由管理员配置自己的 SSH 访问；不要复制他人的私钥。服务器地址属于内网，需要相应网络连通性。

### 2.3 开发目录与服务目录分开管理

本次进程检查未发现从 `/home/glf/projects/GAWorld` 运行的应用服务。实际服务属于 `ft` 用户：

| 服务 | 核验到的启动位置与端口 | 本次核验范围 |
| --- | --- | --- |
| Dashboard | `/home/ft/GAWorld/.venv-deploy/bin/python dashboard_server.py`，8766 | `/api/health` 返回 200 JSON |
| Relay | 同一 Python，`distributed_comm_server.py`，8877 | `/health` 返回 200 JSON |
| Twin | 同一 Python，`-m gaworld.apps.twin_server`，8767 | 仅核验进程与监听 |
| 统一网关 | `/home/ft/.config/gaworld/Caddyfile`，8780 | 核验进程与监听，未改配置 |
| 自动部署 watcher | `gaworld.apps.deploy_services watch --repo /home/ft/GAWorld --branch main` | 运行参数表明跟随 main |

`glf` 账号未能读取 ft 工作区的部署 SHA，因此**尚未确认实际运行代码等于当前 GitHub main**。200 JSON 只证明探针可用，不等于登录、手机轨迹、每种 LLM 或完整实验通过。由服务维护者核对 `runtime/services/deployed-rev`、进程、认证和实际运行版本。

仓库旧部署记录中的 `/home/ft/GAWorld-twin` 和临时公网域名是历史快照；接手时以实际进程及配置为准。不要把旧 trycloudflare 域名当作永久入口。

## 3 我完成过的工作

归属依据是具体作者及提交，而非“位于 glf 分支”。`cec3342` 可达历史中，作者 glf 有 55 个提交，其中 53 个非合并提交。其他别名是否属于同一人需本人确认，不据此扩大个人贡献。

| 工作 | 完成内容 | 代表提交 | 当前状态 |
| --- | --- | --- | --- |
| Dashboard 数据层 | 经济状态/历史接口、批量记忆、最新状态、性能信息 | `105c1fd`、`ced3c86`、`c849857`、`5225368` | 历史实现；当前前端已多轮改写 |
| Dashboard 可视化 | 经济趋势、多人雷达、杂志式样式、监控与工具分区、切换异常处理 | `28c65c4`、`8d9a840`、`5272a56` | 旧图表入口在主线整合时归档 |
| 初版技能面板 | 技能目录、初始技能分配、经验/等级落盘、接口和面板 | `ccbedf2` | 原型贡献；不等于后续完整技能插件 |
| 个人孪生资料 | 郭林峰 CSV/Profile、旧 Agent 52、本地 Qwen3 路由调整 | `4f6e51d`、`7b1b6df`、`f23c5f1` | 当前主线郭林峰为 Agent 53 |
| LifeHistory | 关系记忆、有限理性、情感记忆、持续学习、统一引擎、逐 Agent Profile 与上下文压缩、状态/关系同步 | `455b164`、`04e6989`、`48d90c6`、`9381424`、`9d43135`、`9a7f0fe`、`bf6636a` | 完整旧运行链归档 |
| 人格上下文 A/B | context tendency diversity、独立 seed/目录、规划差异评估、Markdown/PDF 报告 | `5197415`、`3d7ca30`、`0c2cb95`、`bf0e275`、`e41db97` | 保留为历史实验工具和证据 |
| 关系演化 | 阶段/阈值、关系衰减、高阶段变化加速、共址触发、情绪状态及关系/对话导出 | `4321ceb` | 部分机制已被当前主线吸收 |
| 规划层 A/B fork | 同输入双版本、人格约束、few-shot、JSON 输出、指标和报告 runner | `ebdad18` | 旧 pipeline 归档；未提交增强另列第 6 节 |

当前 `gaworld/cognition/realism.py` 保留关系阶段、0.7/0.3 阈值、高阶段两倍变化、关系衰减及辅助 `emotion_state`。原始开发来自 glf，Tao Feng 通过 `89d82ab` 选择性集成并适配当前连续情绪模型。辅助离散状态没有取代连续 `state['emotion']`。

Real Work 市场/队列/适配器、后续 Skills 插件、研究工作台与平行世界主要由 cw 等同事开发；原始 Personal Twin/What-if/Relay 整块代码作者为 Luciddreamzz；主线部署、权限与模型凭据整合包含 Tao Feng 的后续工作。这些属于团队能力，不能全部计入个人原创成果。

## 4 当前架构与维护入口

主路径为：城市与人物数据 → 配置 → Agent 构建 → 插件装配 → 时间步与认知管线 → 状态/记忆/记录 → Dashboard 与实验分析。

| 维护事项 | 入口 | 接手注意点 |
| --- | --- | --- |
| 配置与运行 | `gaworld/settings/`、`generative_city_sim.py` | 根脚本负责编排；旧文档的根 `config.py` 已过时 |
| 微内核与插件 | `gaworld/kernel/`、`gaworld/plugins/__init__.py` | 新子系统采用 Plugin，勿向单体入口堆逻辑 |
| 认知管线 | `gaworld/sim/pipeline.py`、`_cognition.py`、`_action.py` | 感知、计划、行动、反馈、记忆与记录 |
| 人格和关系 | `gaworld/personality/`、`gaworld/cognition/realism.py`、`gaworld/social/` | 保持连续状态语义及身份映射 |
| 记忆与学习 | `gaworld/memory/`、`gaworld/skills/`、`gaworld/interests.py` | 当前维护入口，不声称与旧 LifeHistory 一一等价 |
| Real Work | `gaworld/work/{plugin,runtime,router,queue,market,worker,ingest}.py` | 能力匹配 → 市场/队列 → adapter 执行 → 产物回收 |
| 研究与对照实验 | `gaworld/research/`、`gaworld/parallel/` | 协议、预检查、多 seed、配对估计、解释和报告 |
| Web 与 API | `gaworld/apps/`、`site/dashboard/` | 路由及 OpenAPI 同步更新；根 dashboard_server.py 为兼容入口 |
| 多用户与世界 | `gaworld/accounts/`、`gaworld/worlds/`、`gaworld/apps/world_paths.py` | 读取数据需按用户/世界解析，禁止硬编码共享 output 路径 |
| 模型调用 | `gaworld/llm/providers.py`、账号凭据/usage 机制 | 尊重个人密钥隔离及用量归属 |
| Relay 与 Twin | `gaworld/apps/distributed_comm_server.py`、`gaworld/twin/` | 独立服务的认证不自动继承 Dashboard 登录 |

重要规范：新 Python 功能进入 `gaworld/` 包；不恢复第二套根配置/LLM 路由；不绕过所有权和用户上下文；后台作业沿用 ownership 的启动机制；新 API 补 OpenAPI 和权限测试。

## 5 历史研究如何接手

### 5.1 旧代码定位

以下路径在旧 glf/归档中阅读，当前 Dev 不再装配这些运行链：

- `gaworld/core/life_history/`：类型、关系记忆、有限理性、情感记忆、学习和 `unified_engine.py`。
- `gaworld/work/ab_fork_engine.py`、`metrics.py`：单次规划 A/B、解析、指标和输出。
- `eval/run_mini_ab.py`、`life_history_eval.py`、`life_history_ab_report.py`：旧 A/B runner 与评估。
- `eval/relationship_drift_analysis.py`：关系漂移及导出。
- `docs/planning-fork-ab-design.md`、`docs/life_history_ab_report_20260527.md`：设计和历史结果。

LifeHistory 原设计路径为 `sync_from_gaworld` → `build_planning_context` → 执行动作 → `record_step_outcome` → 关系回写。当前旧 glf 现场也未找到主运行链调用 LifeHistory/fork 的装配证据，因此“文件存在”不等于开启了实验。复现需固定真正实验时的提交、配置和输入，不能只使用当前旧目录直接运行。

### 5.2 结果解释边界

旧报告记录了单 Agent、单日的行为差异。所谓五 seed 表中仅三个 seed 各有 8 对有效记录，另外两个没有配对；缺失不能当作零效应。有效数据中的动作差异是描述性证据，不能直接写成统计显著或当前主线效果。

旧 metrics 部分将阈值映射成固定数值并称为 p 值；这不能代替经过校准的统计检验。旧模型采用的情绪/身份/状态语义与新版不同，不能合池计算效果。新报告应记录提交号、模型、seed、Agent 集合、有效样本数、失败/缺失、时间范围、处理条件、输入与输出校验值。

旧 Agent 52 是郭林峰；当前杭州人物集 Agent 52 是王思颖、53 是郭林峰。历史结果按当时编号解释；跨城市 Agent ID 也不能作为全局唯一身份。

### 5.3 后续研究两条路径

1. 复现实验：在独立目录使用归档提交及相应旧输入，恢复明确的依赖和配置，输出放独立 run 目录。
2. 延续能力：把 LifeHistory 上下文或 diary 对照作为当前 plugin/research 的独立需求，先定义处理条件、因变量、失败标记与用户隔离，再实现并测试。当前 `research/evaluate.py` 和 `parallel/causal.py` 是优先阅读入口。

不能用“把旧模块复制回去”替代迁移设计。本次仅保全原型，没有替团队改变已确认的模型选择。

## 6 未提交工作及处理结果

以下均为本次开始前的用户工作，不归属为本次新增。原目录与原 Git index 保持原状。

| 文件 | 原状态 | 处理 |
| --- | --- | --- |
| `CLAUDE.md` | 修改，+145/-45 | 原样备份；不覆盖当前主线说明 |
| `gaworld/work/ab_fork_engine.py` | 修改，+212/-10 | 保全新 LH 上下文、日志及 diary fork 原型；暂不恢复归档子系统 |
| `gaworld/work/benchmark_report.py` | 未跟踪 | 保全；样本去重错误待修 |
| `eval/gen_report_v2.py` | 未跟踪 | 保全；一次性报告与硬编码结论待参数化 |
| `eval/generate_pdf_report.py` | 未跟踪 | 保全；日记键类型与统计传递待修 |
| `eval/generate_viz_report.py` | 未跟踪 | 保全；fork_counts 持久化待修 |
| `glf-ollama.sh` | 未跟踪 | 保全；默认网络暴露范围待调整 |
| `local_llm_server.py` | 未跟踪 | 保全；chat 响应契约和访问控制待修 |
| `tests/test_env_loader.py` | 未跟踪 | 迁入最新 Dev 候选，增加环境恢复 fixture，格式化后 21 项通过 |

附带源码归档保存上述九个文件、两个已跟踪文件的 HEAD 基底、原始补丁和 SHA-256 清单；不包含 `.env`、账号库、模型权重或 output 实验数据。

另有嵌套 worktree `.claude/worktrees/pre-merge-main`，detached HEAD `da2f5c4`，其中 `dashboard_config.json`、`news_cache.json` 已修改。本次只记录状态，不将其作为普通目录递归纳入候选，也未删除。接手者若需要其中配置，应在原服务器单独核验和私下备份。

还发现五个既有 stash。编号会随以后操作变化，应使用固定提交号定位：

| 当前编号 | 固定提交 | 主要内容 |
| --- | --- | --- |
| stash 0 | `cae33f0` | 9 月 20 日合并前备份；CLAUDE、A/B 引擎、旧配置及仿真入口 |
| stash 1 | `68b0636` | 旧 main 的模型和 Dashboard 配置 |
| stash 2 | `75869ea` | 配置、入口、模型路由、mock LLM 和记忆测试 |
| stash 3 | `cee5650` | 共址相遇与阈值修改、新闻缓存 |
| stash 4 | `e5a53ae` | 早期 Dashboard 配置 |

五个 stash 均未应用或删除，不能默认等同于最新工作；接手需要逐项与相应基底比较。为防止只备份工作区而遗漏历史，另生成并验证了含仓库引用和五个 stash 对象的 Git bundle，本机私有备份保存在本次工作目录中（约 87 MB），不随默认同事交接包发送。需要恢复历史时先在独立仓库读取，勿直接在服务目录应用旧 stash。

本次 Codex 新增/修改仅发生在隔离候选及交付文件：适配环境测试、添加 `.claude/worktrees/` 忽略项、修复 Linux 长命令下的仿真进程识别并补回归、编写交接/审查/集成文档及证据。没有修改 glf 原业务源码，没有改在线服务。

## 7 同事本地启动与验证

### 7.1 获取当前主线

在新的开发目录执行，勿在服务工作目录切分支：

```bash
git clone --branch Dev https://github.com/wuchaozju/GAWorld.git GAWorld-dev
cd GAWorld-dev
git rev-parse HEAD
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt -r requirements-dev.txt
python generative_city_sim.py --help
```

仓库要求 Python ≥3.11，CI 覆盖 3.11/3.12；本次借用服务器现有 `.venv` 为 3.13.9，测试结果需注明这一差异。requirements 采用版本范围而非完整锁定文件，不能称为完全可复现环境。

配置按 `.env.example` 填写自己的值，并结合 `gaworld/settings/`、当前 `docs/MODEL_PROVIDERS.md`。不要在聊天或 Git 中交付密钥。共享实例通过账号系统及个人模型配置使用，不复制服务器账号数据库。

### 7.2 优先跑无真实模型的测试

```bash
export GAWORLD_IGNORE_LOCAL_CONFIG=1
export HTTP_PROXY=http://127.0.0.1:9
export HTTPS_PROXY=http://127.0.0.1:9
export ALL_PROXY=http://127.0.0.1:9
export NO_PROXY=127.0.0.1,localhost,::1
python -m pytest tests/test_env_loader.py -q
python -m pytest --suite core -q
```

`test_env_loader.py` 属于本次待发布候选；候选尚未合入时，普通 Dev clone 没有该文件。无效代理用于让意外外网请求快速失败，loopback 留给本地测试；这不是操作系统级断网隔离。真实模型运行使用独立终端/环境，避免沿用无效代理。

完整发布回归依仓库 CI 执行 Ruff、格式、pytest coverage（80%）及对应前端测试。先阅读 `docs/TEST_CASES.md`；测试数量随版本变化，不照抄旧文档规模。

### 7.3 启动本地界面

```bash
python dashboard_server.py --host 127.0.0.1 --port 18766
```

浏览器访问 `http://127.0.0.1:18766/console`。首次只检查配置、人物及页面资源，再在自己的隔离世界选择模型和小规模试运行。不要直接沿用旧目录 `sim_days=365` 的配置发起任务，也不要运行 reset 清理共享输出。旧目录选择的城市是 `wuzhen`，不代表接手者应该使用同一运行数据。

## 8 数据与运维交接

| 资产 | 位置或获取方式 | 规则 |
| --- | --- | --- |
| 城市和人物模板 | `data/cities/<slug>/` 及仓库人物数据 | 固定版本；不要静默改变历史 Agent 身份 |
| 世界运行结果 | `output/worlds/<id>/` 等实际配置路径 | 通过当前 world_paths 解析；与代码分开备份 |
| 旧实验产物 | glf 目录的 `output/`、`output_ab/`、历史报告资产 | 本次未搬运；需选定 run 后另行传输及核验 |
| 看板/Relay 状态 | 实际服务目录对应 output 路径 | 升级前单独备份；本次未读取内容 |
| Twin 绑定与上报 | 由实际 Twin 启动环境和配置确定 | 不根据旧文档盲猜目录，不清空旧绑定 |
| 账号和个人密钥 | 服务维护者管理的工作区外私有位置 | 不纳入 Git，不经本文传递 |
| 部署配置 | ft 用户服务、Caddy 配置、部署记录 | 需维护者权限核实；glf 开发副本不等于生产 |

部署按当前 `docs/SERVER_DEPLOYMENT.md` 和 `deployment/multi-user/` 执行。账号 required 模式应在账号库缺失/损坏时保持拒绝服务，不能退回匿名可写。主线更新、服务重启、健康探针及部署 SHA 分别核验；不要为更新 Python 应用随意重启公网隧道。

回退应保留代码版本与数据快照：发生发布问题先停止后续发布，核对上一个部署 SHA，再由服务维护者从已知版本重新部署；账号、世界、Relay、Twin 数据独立恢复。不要用对用户工作区的破坏性重置替代回退。

## 9 已知问题与下一步

| 优先级 | 问题 | 接手动作 |
| --- | --- | --- |
| P1 | 旧本地模型 helper 默认对所有网卡暴露无认证推理 | 维持不合入；改为 loopback 默认，明确认证/资源限制后评审 |
| P2 | benchmark 按指标三元组去重，吞掉不同 Agent/时点的相同分数样本 | 改用 run/agent/timestep 唯一标识并加入重复来源测试 |
| P2 | PDF 用整数读取 JSON 字符串日记键；可视化摘要漏存 fork_counts | 统一 schema，补生成器到报告的端到端用例 |
| P2 | 报告写死人数、天数、步数、结果叙述 | 参数化输入，结论由数据计算；缺失与零值分开 |
| P2 | 旧 helper 返回 choices.text，chat provider 读取 message.content | 定义接口版本、请求模板及契约测试 |
| P2 | LH 失败时静默退回通用人格上下文，实验处理条件不可追溯 | 记录 treatment_used、失败原因及模型/配置来源 |
| P2 | 旧同日同 Agent/step 的结果可覆盖，summary 却继续追加 | run_id 进入路径，重跑与断点恢复语义明确 |
| P2 | 旧“显著性”部分是启发式分数 | 不作统计 p 值使用；按当前研究协议设计估计与有效样本 |
| 待核验 | 当前服务部署 SHA、Twin 权限与路径、固定公网入口 | 由 ft/网关维护者完成实际核验 |

新候选的环境变量测试污染问题已修复：每个用例前清理所用变量，并通过 monkeypatch 在结束后恢复原值；独立哨兵检查确认八个既有值均恢复。

本次主干回归发现并修复另一个主线已有问题：`gaworld/apps/runs.py` 使用默认宽度的 `ps` 输出，在较长 Python 路径下截掉仿真脚本名，可能漏认残留仿真并允许重复启动。候选增加 `ps -ww`，并以超过 256 字符的真实进程命令和 80 列输出环境验证。定向三个用例通过；完整核心复测结果见审查记录。

历史真实 LLM 验收报告仍记录地图尺寸/异步加载、天气分类、计划时间等问题。本次没有重跑这些场景，不把旧缺陷当作本次已修复。最新代码审查和本次测试记录详见随附《审查与验证记录》。

## 10 交接验收清单

- 接收方有自己的仓库权限和服务器账号，明确谁审批 Dev、谁维护 main/在线服务。
- 能说明 `Dev/main=6214b8c`、旧 glf、历史归档和本次候选四者关系。
- 下载并校验未提交源码归档，确认原始九个文件没有遗失；嵌套 worktree 有单独保全安排。
- 五个 stash 的固定提交号已记录，需要的旧实验入口增量从私有备份或原仓库独立审查。
- 在新目录安装依赖、运行核心测试，记录 Python、依赖版本、完整结果及跳过原因。
- 能从模块表定位关系、记忆、研究、世界权限、模型调用的修改入口。
- 以自己的账号/世界完成一个小规模运行，核对真实模型、产物路径、日志和退出状态。
- 报告区分历史结果、可复现结果和待验证假设；不混淆旧 Agent 52 与当前 Agent 53。
- Dev 的候选经过确认、审查和 CI；主线发布另行走维护者流程，记录最终提交及 PR。
- 服务维护者补齐部署 SHA、数据备份位置、访问入口和故障回退演练记录。

建议接手顺序：第一天建立版本与访问基线、跑测试；第二天按当前研究体系完成最小实验；之后分别排期处理报告正确性、旧能力迁移及发布验收。此顺序为建议，不代替接手人的排期承诺。

## 11 可追溯资料

- [当前主线整合记录](https://github.com/wuchaozju/GAWorld/blob/6214b8c5cd12537c554147237ace9131f576f6da/docs/DEV_MAIN_MERGE_REVIEW_2026-10-07.md)
- [旧 glf 分支审查](https://github.com/wuchaozju/GAWorld/blob/81083d96386d0155f212b6e7e9a20a1469f676fc/docs/GLF_BRANCH_REVIEW_2026-10-07.md)
- [历史真实模型验收](https://github.com/wuchaozju/GAWorld/blob/81083d96386d0155f212b6e7e9a20a1469f676fc/docs/REAL_LLM_ACCEPTANCE_2026-10-07.md)
- [研究工作台教程](https://github.com/wuchaozju/GAWorld/blob/6214b8c5cd12537c554147237ace9131f576f6da/docs/RESEARCH_WORKBENCH_TUTORIAL.md)
- [平行世界教程](https://github.com/wuchaozju/GAWorld/blob/6214b8c5cd12537c554147237ace9131f576f6da/docs/PARALLEL_WORLDS_TUTORIAL.md)
- [测试用例与核心套件说明](https://github.com/wuchaozju/GAWorld/blob/6214b8c5cd12537c554147237ace9131f576f6da/docs/TEST_CASES.md)

本文不包含账号口令或模型密钥。源码归档是未合入的实验资料，不能作为已验证的生产发布包。
