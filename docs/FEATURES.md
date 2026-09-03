# GAWorld 功能特性总览

本表列出 GAWorld 的主要功能特性、作用，以及访问 / 启用方法。命令均在项目根目录执行。
配置项默认入口为 `config.py`（实际分层在 `gaworld/settings/`），可被 `dashboard_config.json` 与 `GAWORLD_CONFIG_OVERRIDES` 覆盖。

## 一、CLI 命令（直接可用）

| 功能特性 | 作用 | 访问方法 |
|---|---|---|
| 运行仿真 | 让一批智能体按天循环"生活"，产出日志、记忆、状态、经济等全部产物 | `python generative_city_sim.py run` |
| 长时段快进 | 把一步压缩成每个智能体一条简报（每 agent 每步 1 次 LLM 调用），跳过日内时刻循环，实现"快进+近似"，适合 60/600 天长期模拟；状态/目标/关系仍近似推进 | `python generative_city_sim.py run --sim-days 600 --fast-forward`；Dashboard 工具栏勾选「长时段快进」 |
| 大跨度模拟（以月 / 年为单位） | 一步 = 一个日历月或一年，压缩成每人一条「阶段简报」（含 2–4 条里程碑），让数年到数十年的模拟跑得起（10 年 × 50 人：按年 500 次调用 vs 按天 18.25 万次）；仿真日历仍按天推进，经济等日边界钩子按 ≤30 天区块补跑 | `python generative_city_sim.py run --sim-years 10` / `--sim-months 24` / `--time-unit month`；`CONFIG["long_run"]["unit"]`；Dashboard 工具栏「步长单位」下拉 + 随之变成「仿真月数 / 仿真年数」的时长字段 |
| 重置 | 清除有状态产物，从 Day 1 重新开始（改记忆 schema 后必做） | `python generative_city_sim.py reset` |
| 智能体采访 | 基于某 agent 当前记忆与状态向其提问 | `python generative_city_sim.py interview --agent-id 31 --question "..."` / `--questions-file q.txt` |
| 从社交内容创建智能体 | 用社媒页面或文本生成新 agent 画像 | `python generative_city_sim.py create-agent-from-social --url "..."` / `--file ... --name "..."` |
| RAG 外部知识注入 | 向某 agent 注入外部信息以改变其认知 | `python generative_city_sim.py rag-add --agent-id 31 --text "..."` / `rag-import --file ...` |
| 事件对照实验 | 在"有事件 / 无事件"两分支并行仿真并出对比报告 | `python generative_city_sim.py compare-event --event-name "..." --sim-days 3 --seed 42` |
| 平行世界实验 | 一次实验最多 8 个世界，共用同一批居民 / 种子 / 天数 / 模型，各带自己的事件表（或 `config` 补丁）；报告给出逐步偏离度、分叉点与逐人影响，而不只是终值差 | `python generative_city_sim.py parallel-worlds --spec worlds.json`；详见 [平行世界教程](PARALLEL_WORLDS_TUTORIAL.md) |
| 本地 Dashboard | 配置编辑、运行控制、记忆查看、访谈、日志查看 | `python generative_city_sim.py dashboard --port 8766` → `http://127.0.0.1:8766/dashboard` |
| Dashboard 智能体互动 | 对两位或更多居民建立双向好友关系；启动独立于主仿真的多轮讨论，并实时观察发言、摘要与完整记录 | Dashboard「智能体互动」面板；会话与事件写入 `CONFIG["collaboration"]["sessions_dir"]` |
| Dashboard 合作任务 | 多智能体按“规划 → 分工执行 → 同伴审阅/修订 → 汇总”完成任务，展示可观测事件与 Markdown 产物 | 控制台「合作任务」页签 → `/site/dashboard/collaboration.html`；产物位于 `<sessions_dir>/<session_id>/artifacts/` |
| Agent Studio | 单智能体 7 步可视化构建/查看：身份、九维状态（可编辑雷达）、技能、记忆、Dunbar 社交、行为、复核部署；写回 CSV+profile，可创建新 agent | 控制台工具栏「Agent Studio ↗」→ `http://127.0.0.1:8766/site/dashboard/studio.html` |
| 智能体工作台家庭编辑 | 逐人指定婚姻状态、伴侣（可指定名单里的另一位居民 / 场外人物）、子女与同住长辈；保存为覆盖项，**跨运行生效**并优先于自动抽样，可一键恢复自动生成 | 控制台「Agent Studio ↗」→ 第 5 步「社交 · 关系」；写入 `data/family_overrides.json` |
| 参数化人口合成 | 按人口学旋钮生成整座小镇（年龄金字塔、家庭结构、就业、收入基尼、社交图），产出与现有格式完全一致的状态 CSV + profile MD | `python -m gaworld.population --size 500 --seed 42 --out data/town`；`--check` 只预览不写文件 |
| 群体（cohort）模拟 | 把人口划分成群体，每群每天 1 次 LLM 调用 + 按预算实体化少数个体，实现大规模人群的低成本模拟 | `python -m gaworld.group --size 500 --days 7 --no-llm`；`--focal 7,42` 全程跟踪指定居民；`--network-coupling 0.7` 开社交图耦合（不开则验证门 L2 不通过）；不加 `--no-llm` 会真的调 LLM，运行前先打印预估次数 |
| 群体模式验证门 | L1–L4 配对实验，量化 cohort 近似的代价并给出"能回答哪类研究问题"的结论；分水岭层不过时退出码为 1 | `python -m gaworld.group.validate --size 100 --days 14 --network-coupling 0.7` |
| Population Studio | 5 步可视化：选模板（预设带说明）→ 人口结构（目标 vs 实际 + 金字塔/洛伦兹/度分布）→ 心理状态（均值雷达 + P25–P75）→ 跑模拟（可选后端模型）→ 检查结果（白话判定 + 文件可直接点开）；指标统一中英文双标 | 控制台「人口与群体」页签 → `http://127.0.0.1:8766/site/dashboard/population.html` |
| 外部系统观测台 | 观察并编辑世界本身：货币系统（宏观周期、部门池、货币守恒审计、财富分布与基尼）、外部环境生成器（自然/经济/政策/科技事件时间线与生成参数）、对外服务（连通性即时探测、LLM 路由、外部信息源）。配置表单按配置自身的 JSON 形状生成，约 150 个旋钮可编辑；另可对**跑着的**仿真排一次货币干预（改宏观状态 / 给部门池注资），由仿真在下一个日边界消费。指标与旋钮几乎都带 hover 白话说明（`?` 悬停，说的是「改了会怎样」而非复述标题） | 控制台「外部系统」页签 → `http://127.0.0.1:8766/site/dashboard/external.html`；详见 [外部系统教程](EXTERNAL_SYSTEMS_TUTORIAL.md) |
| 平行世界实验台 | 左边设计实验（世界、事件、模板、基准），右边读结果：分叉图（离主干的远近＝偏离程度）、逐指标走向对比（可只看与基准的差）、偏离曲线与分叉点、终局差异表、「谁被改变了」逐人表。图例可逐个世界开关；每个世界的轨迹仍可逐帧回放；已有的 compare-event 结果会被当场适配进同一视图 | 控制台「平行世界」页签 → `http://127.0.0.1:8766/site/dashboard/worlds.html`；详见 [平行世界教程](PARALLEL_WORLDS_TUTORIAL.md) |
| 轨迹回放查看器 | 可视化回放智能体移动轨迹；顶部「运行」下拉可选择任意一次已记录的仿真：当前运行（实时）、历史归档运行（`output/visualization/runs/<run_id>/`）、compare-event 等场景运行；`?run=<id>` 可分享指定运行 | `python generative_city_sim.py serve-viz --port 8000` → `/site/simviz/index.html`（Dashboard 内为「仿真回放」页签） |
| 分布式 relay | 多机协同仿真，各节点处理本地 agent 子集 | `python generative_city_sim.py serve-distributed --host 0.0.0.0 --port 8877` |
| 城市地图生成 | 用自然语言描述生成城市地图（节点 / 道路 / 地铁） | `python scripts/generate_citymap.py --description "..."` |
| 大五人格生成与合入闸门 | 一次性离线**先采样** 51 位居民的大五（OCEAN）z 分、**再据此改写**人物设定里的行为描述（51 次调用），产出 `data/agents_big5.csv` 与新增的 `人格与行为倾向` 字段，旧语料备份到 `data/hangzhou_profiles_with_names.v1.md`；独立性由采样器保证，只保留开放性↔`risk_preference`、外向性↔`voice_propensity` 两条 r≈0.3 的真实相关。两个闸门脚本分别量给定幅度下人格与行为的相关上限、检查五个维度是不是已有状态变量的线性组合 | `python scripts/author_personality.py`（`--dry-run` 只看提示词与采样分数，`--agents 1-5` 试水写 `output/traits/authored_preview.md`，`--apply` 全量落盘）；`python scripts/big5_effect_ceiling.py`；`python scripts/big5_collinearity.py --annotate`（生成后必跑，把不合格维度写回 CSV，运行时会打印警告）。`python scripts/calibrate_big5.py` 保留用于给外部导入的 agent 打分、以及作对照组校验打分器 |

Dashboard 讨论与合作会话支持暂停、继续和终止。服务重启时，磁盘上仍标记为
`running` 的会话会恢复为 `interrupted`，保留此前事件、讨论记录和合作产物，
等待用户明确继续或终止；已完成会话可直接重新读取。

## 二、核心仿真特性（配置开关）

| 功能特性 | 作用 | 访问方法 |
|---|---|---|
| 多后端 LLM 路由 | Ollama / OpenAI 兼容 / Anthropic 兼容，可按任务分流模型 | `CONFIG["llm"]["routing"]["default"]` / `["tasks"]`；环境变量 `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` 等 |
| 记忆系统 | 短期 / 情景 / 长期总结 / 关系记忆 + 向量召回，跨天保持一致性 | 自动运行；`CONFIG["memory"]`；产物 `output/memory/` |
| 经济仿真 | 货币守恒闭环（企业/政府/银行部门池）、个税 + 五险一金真实代扣、恩格尔消费、现金约束 + 信贷、投资含共同市场因子、消费/房租路由到 agent、熟人借贷、宏观周期与冲击 | `CONFIG["economy"]`（子块 `sectors`/`credit`/`routing`/`friend_loans`）；产物 `output/economy/`（含 `conservation_audit.csv`、`sectors.json`） |
| 位置系统与交通 | 类别空间匹配、真实出行成本、高峰 / 天气影响、通勤记忆、区域价格 | 自动运行（依赖 `data/citymap.md`）；`gaworld/world/city_map.py` |
| 动态行为系统 | 承诺度感知中断、情绪即兴行为、社交偶遇链、环境事件级联、需求中断与日程恢复 | `CONFIG["dynamic_behavior"]["enabled"]` |
| 兴趣爱好与技能成长 | 为每个 agent 派生成长画像并动态演化（幂律学习、里程碑、遗忘衰减、发展四阶段、社交兴趣传染），影响日程、动作权重与工作选择 | `CONFIG["interests"]["enabled"]`（日终机制见 `interests.decay` / `interests.evolution`）；产物 `output/memory/agent_<id>_growth.json` |
| 社交网络 | 关系衰减、Dunbar 分层、off-screen ghost 事件 | 自动运行；`gaworld/social/network.py`；产物 `output/network/` |
| 家庭与户 | 按年龄段 × 性别抽样婚姻状态（未婚/已婚/离异/丧偶），匹配得上的居民在仿真内配成夫妻并**共享同一个住处**，配不上的补场外家人；子女、同住长辈、合租室友随之生成。家庭进入日程（接送、陪写作业、照料老人、回家吃晚饭）、账本（育儿与赡养开销按收入分摊、伴侣互相补现金缺口，全程守恒）、事件（同一件事同一 tick 落到全家人身上）与户内情绪传染 | `CONFIG["family"]`（配置面板「家庭与户」分区）；产物 `output/records/family.*.jsonl`；详见 [家庭系统设计](FAMILY_DESIGN.md) |
| 生命事件 | 生日、疾病、关系破裂等调度事件 | 自动运行；`gaworld/events/life.py` |
| 就业事件（换工作 / 失业） | 「换工作」「失业」两个模板会**真的改写 `agent["job"]` 与收入**，不只是感知文本：换工作按新岗位的收入带重抽时薪（可在面板指定「新职业」，留空则自动跨行业转岗）；失业沿用裁员冲击的形状——大幅砍收入 + 30–90 天恢复倒计时，并把职业改成待业、记下 `previous_job`，倒计时结束后按原岗位收入带的 85–100% 复职（留疤）。日程也跟着换成「办理入职交接 / 熟悉新工作」「办理离职交接 / 求职投递」——**求职不发工资**（活动名刻意避开 `INCOME_KEYWORDS` 命中的「工作」二字） | 面板「人生事件」选模板 + 可选「新职业」；`gaworld/economy/finance.py:apply_employment_event`；日志 `[JobChange Day N ...] 旧职业 → 新职业（时薪 a → b）`，同时写进 `economy.shock_log` |
| 政策 / 环境事件 | 政策冲击与环境扰动注入仿真 | `CONFIG["policy_events"]`；`gaworld/env/system.py`；产物 `output/environment/timeline.jsonl` |
| PolicySim 干预评估 | 本地无网络评估推荐 / 曝光，记录立场 / 毒性 / 误信息 / 跨观点 / 奖励指标 | `CONFIG["intervention"]["enabled"]`；产物 `output/intervention/intervention_metrics.csv` |

## 三、新特性（v2）

| 功能特性 | 作用 | 访问方法 |
|---|---|---|
| 物理环境感知（P0） | 接通节点级占用 / 营业状态，感知前生成"身边物理环境"快照 | `CONFIG["environment"]["local_physical"]["enabled"]` |
| 异常一等公民（P2） | 给事件打 `anomaly` / `anomaly_score`，区分常态波动与突发异常 | `CONFIG["environment"]["anomaly"]["enabled"]` |
| 当日反应式重规划（P3） | 持续性异常时只重排受影响区间（改址 / 顺延 / 丢弃） | `CONFIG["environment"]["replan"]["enabled"]` |
| 结构化空间学习（P4） | 累积地点规避偏好并改址，可跨运行持久化 | `CONFIG["environment"]["spatial_preferences"]["enabled"]`（+ 顶层 `stateful=True`）；产物 `output/memory/agent_<id>_env_preferences.json` |
| 可复用 Skill 库 | 全局 / 私有 Markdown 技能，注入认知与工作 brief 影响行为 | `CONFIG["skills"]`；全局库 `data/skills/*.md`；`SkillRegistry().attach_to_agent(agent, "id")` |
| 经验 → Skill 自动提炼 | agent 从最近经历自总结私有技能 | `CONFIG["memory"]["skill_consolidation"]["enabled"]`（默认 OFF）；产物 `output/memory/agent_<id>_skills/*.md` |
| 真实工作任务系统 | agent 按职业 / 技能产出真实产物（HTML / Python / 文章 / 教案 / 研究笔记）并接单结算 | `CONFIG["real_work"]["enabled"]`；产物 `output/work/agent_<id>/<task_id>/` |
| 长时段快进（fast-forward） | 一步压缩成每个智能体一条简报、跳过日内时刻循环，让 60/600 天长期模拟可行；状态/目标/关系仍近似推进，输出为每步一个 `Day N` / `Month N` / `Year N 简报` | `CONFIG["long_run"]["enabled"]`（或 `run --fast-forward`）；`long_run.randomness`(0–1) 越高突发事件越频繁、波动越大；Dashboard 工具栏勾选「长时段快进」+「随机性」滑杆 |
| 大跨度的社交影响 | 粗粒度下关系有**走向**而不只是一次互动：简报报告这段时间亲密度的净增量（单步上限 0.25，信任按半速跟随），**正增量算有来往会重置衰减计时、负增量刻意不重置**（疏远就是没来往）。可以结识新的人——但只能从运行中真实存在且尚未认识的居民里选。换工作时同事自动转为前同事，衰减率从 0.006 切到 0.015（`SOCIAL_NETWORK_DESIGN.md` §6 里等了很久的"外部触发"） | 自动随 `long_run.unit` 生效；日志 `[Social Year N] #id 0.72→0.85；+#7(coworker)` |
| 大跨度的个体发展 | 粗粒度下**技能会长、人会变老**。简报报告这段时间在成长档案各项上的平均每周投入（`development`），由 `growth.step` 按经过的周数重放已有的幂律学习曲线；年龄按累计天数推进，满 365 天涨一岁。修掉了两个洞：快进下练习进度挂在 tick 事件上从不触发（于是技能**只衰减不成长**，一年 0.30→0.10），以及年龄在整个仿真里从未被写过 | 自动随 `long_run.unit` 生效；日志 `[GrowthStep Day N ...]`、`[Birthday Day N ...]` |
| 大跨度的模拟框架 | 阶段简报的输入不是作息表，而是**人生处境**：年龄/职业/居住/家庭、前几个阶段的简报（弧线而非某一周的三句记忆）、成长档案的当前水平、重要关系的**当前亲密度**。作息骨架降格为「生活底色」，并明确要求不要逐日展开 | 自动随 `long_run.unit` 生效 |
| 大跨度的动作与事件空间 | 粗粒度下**动作空间和事件空间跟着跨度换档**，而不是沿用按日的那一套。**动作空间**：月/年步长的简报会拿到一份「人生动作」清单（取自人生事件模板：换工作 / 失业 / 升职 / 生病 / 中奖 / 被陷害 / 家庭急事 / 关系破裂），模型选中的动作会**被真正执行**（换工作会改写 `agent["job"]` 并按新岗位收入带重抽时薪），而不是只写进简报。**事件空间**：外部环境按整段时间生成结构性事件（政策、行业景气、物价房租、人口流动、季节气候），不再是「今天小雨」；`intraday_rules`（日内突发概率）在无 tick 的步长下被丢弃。此外**排队中的人生事件也终于会触发**——按 tick 走的那条链路在快进下从不执行 | 自动随 `long_run.unit` 生效；日志 `[JobChange Day N ...]`、`[LifeEvent ...]` |
| 时间单位：天 / 月 / 年 | 快进的步长单位。选 `month`/`year` 时一步压缩整月整年，简报带里程碑列表，状态增量上限自动 ×2/×3，突发事件个数按跨度放大；日边界钩子（经济结算、兴趣衰减、家庭开销）按 `hook_chunk_days` ≤30 天补跑，跑一年会走满 12 次月结算；无 tick 时按「宏观时薪 × 目标工时 × 工作日」补记近似工资（走 firms 池，货币守恒） | `CONFIG["long_run"]["unit"]`（`day`/`month`/`year`，**选 month/year 即自动打开快进**——没有按月的日内循环）、`period_brief_max_chars`、`hook_chunk_days`；CLI `--time-unit` / `--sim-months` / `--sim-years` |
| 日程网格对齐 | 把每个 agent 的日程对齐到固定时间网格，让 tick 数恒为 `1440/step` 而不随人口超线性增长。**只设 `time_step_minutes` 不够**——主时间线是网格与 LLM 自拟时间的并集 | `CONFIG["time_grid_snap"]=True` + `CONFIG["time_step_minutes"]=30`；默认 OFF（会改变日内时序） |
| Cohort 遥测插件 | 在个体运行中发布群体划分与逐日漂移到 recorder，只观测不改行为 | `CONFIG["group"]["enabled"]=True`；产物 `output/records/*.jsonl` 中的 `group.partition` / `group.cohort_stats` |
| 大五人格（OCEAN） | 每位居民带一组离线生成的五维人格分（五维全部 51/51 有分，运行内不漂移），经 `rules`（动作选择加性权重项「性格倾向」+ 打断阈值 / 冲动 / 搭话 / 决策噪声 / 消费储蓄倾向的乘性微调 + 个人情绪基准线，确定性、零 token）、`prompt`（第二人称行为锚句注入日程 / 日内调整 / 目标 / 新闻反应四类提示词）、`voice`（同样的锚句只进日记提示词）三条通道影响行为；profile 有 `人格与行为倾向` 字段时提示词渲染该段而非旧的「性格与情绪特征」行（`agent["personality"]` 本身不变，按关键词读它的子系统行为照旧）；无人格数据的 agent 或关掉的通道与加入前逐位一致 | `CONFIG["personality"]["enabled"]`（默认 ON，插件 `big_five`）；`channels` 分通道开关，`strength=0` 为对照组；数据 `data/agents_big5.csv`；产物 `output/traits/agent_traits.csv` |

## 四、微内核插件体系（2026-07）

| 功能特性 | 作用 | 访问方法 |
|---|---|---|
| 认知管线消融 / 定制 | agent step 是 12 个命名阶段的可配置序列，可消融（如去掉反思）、替换或插入自定义阶段 | `CONFIG["pipeline"]["agent_step"]`（内置名或 `"module:function"` 路径） |
| 第三方插件 | 不改核心为仿真加子系统（感知注入、中断源、动作过滤、状态效果等 21 个事件） | `CONFIG["plugins"] = [{"class": "pkg.mod:Class"}]` 或 pip 包 `gaworld.plugins` entry point；指南 [`PLUGIN_AUTHORING.md`](PLUGIN_AUTHORING.md) |
| 运行时干预 | 模拟运行中改 agent 状态 / 配置 / 注入人生事件 / 移除 agent（日边界生效），全部审计 | `sim.controller.intervene("set_agent_state" \| "update_config" \| "inject_life_event" \| "remove_agent", sim, ...)`；审计 `output/records/controller.intervention.jsonl` |
| 动作校验门 | move 动作过校验链，deny 审计落盘并在下一 tick 感知回注 | `location_exists` 默认开；`venue_open` 经 `CONFIG["controller"]["validators"]` 开启 |
| 统一事件流 | 跨插件时间线对齐的结构化记录（自动 `_day`/`_time` 戳） | 产物 `output/records/*.jsonl` |

## 五、运维与调试

| 功能特性 | 作用 | 访问方法 |
|---|---|---|
| 日志模式 | 切换终端输出详略（simple ~4 行/tick，verbose 全字段） | `GAWORLD_LOG_MODE=simple\|verbose`（默认 simple） |
| 日志级别 | DEBUG 下显示每次 LLM 调用的 token 与延迟 | `GAWORLD_LOG_LEVEL=DEBUG` |
| 配置覆盖 | 不改源码即可覆盖基础配置 | `dashboard_config.json` / `GAWORLD_CONFIG_OVERRIDES` |
| 可复现性 | 固定随机种子复现实验 | `--seed`（CLI）/ `CONFIG["random_seed"]` |

---

## 相关文档

- [完整教程](TUTORIAL.v2.md)
- [插件作者指南](PLUGIN_AUTHORING.md) · [微内核架构设计](proposals/2026-07-11-microkernel-plugin-architecture.md)
- [物理环境感知与反应式重规划](physical_env_perception_changelog.md)
- [Skill 系统](SKILL_SYSTEM.md) · [真实工作系统使用](REAL_WORK_USAGE.md)
- [群体模拟教程](GROUP_SIMULATION_TUTORIAL.md) · [群体模拟设计](GROUP_AGENT_DESIGN.md)
- [家庭系统设计](FAMILY_DESIGN.md)（婚姻抽样、共居、家庭日程与账目、覆盖层与工作台编辑面板）
- [大五人格子系统设计](proposals/2026-08-20-big-five-personality.md)（标定流程、三条通道、幅度与合入闸门）
- [外部系统教程](EXTERNAL_SYSTEMS_TUTORIAL.md)（货币系统 / 外部环境 / 对外服务的观察与编辑）
- [平行世界教程](PARALLEL_WORLDS_TUTORIAL.md)（多分支反事实实验：设计、读图、剂量反应与安慰剂对照）
- [项目结构](PROJECT_STRUCTURE.md) · [中文 README](../README.zh-CN.md) · [English README](../README.md)
