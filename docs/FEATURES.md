# GAWorld 功能特性总览

> **先看全景**：打开 [`FEATURE_MAP.html`](./FEATURE_MAP.html) 查看按 **"使用者 × 能力子轴"** 重组的三级功能地图（5 主轴 / 21 子轴 / 79 功能点，独立 HTML，五色 Mermaid 分块渲染 + 可折叠三层索引）。
>
> 本表是图中每个叶子节点的详细展开：**功能 → 作用 → 访问方法**。命令均在项目根目录执行。
> 配置项默认入口为 `config.py`（实际分层在 `gaworld/settings/`），可被 `dashboard_config.json` 与 `GAWORLD_CONFIG_OVERRIDES` 覆盖。
>
> 维护约定：新增 / 移除功能时，请同步更新 `FEATURE_MAP.html` 的思维导图节点与折叠索引。

## 一、CLI 命令（直接可用）

| 功能特性 | 作用 | 访问方法 |
|---|---|---|
| 运行仿真 | 让一批智能体按天循环"生活"，产出日志、记忆、状态、经济等全部产物 | `python generative_city_sim.py run` |
| 长时段快进 | 把一步压缩成每个智能体一条简报（每 agent 每步 1 次 LLM 调用），跳过日内时刻循环，实现"快进+近似"，适合 60/600 天长期模拟；状态/目标/关系仍近似推进 | `python generative_city_sim.py run --sim-days 600 --fast-forward`；Dashboard 工具栏勾选「长时段快进」 |
| 大跨度模拟（以月 / 年为单位） | 一步 = 一个日历月或一年，压缩成每人一条「阶段简报」（含 2–4 条里程碑），让数年到数十年的模拟跑得起（10 年 × 50 人：按年 500 次调用 vs 按天 18.25 万次）；仿真日历仍按天推进，经济等日边界钩子按 ≤30 天区块补跑 | `python generative_city_sim.py run --sim-years 10` / `--sim-months 24` / `--time-unit month`；`CONFIG["long_run"]["unit"]`；Dashboard 工具栏「步长单位」下拉 + 随之变成「仿真月数 / 仿真年数」的时长字段 |
| 重置 | 清除有状态产物，从 Day 1 重新开始（改记忆 schema 后必做） | `python generative_city_sim.py reset` |
| 智能体采访 | 基于某 agent 当前记忆与状态向其提问 | `python generative_city_sim.py interview --agent-id 31 --question "..."` / `--questions-file q.txt` |
| 群体采访 | 一次问一群受访者同一套问题（个体居民 + cohort 群体智能体，**可跨城市**）；选择题/是非题会被统计，可附图片与网址，逐题作答时看得见自己前面的回答，可连续追问多轮，最后导出一份完整 Markdown | 控制台「群体采访」页签 → `/site/dashboard/survey.html`；某一座城市那一份可单独跑：`python -m gaworld.interview --spec round.json --out answers.json`；详见 [群体采访教程](GROUP_INTERVIEW_TUTORIAL.md) |
| 研究工作台 | 提出一个基于 GAWorld 的研究想法，或贴进一篇社会科学论文（可从 .txt / .md / .pdf 读入；论文先单独解读出理论 / 方法 / 变量 / 发现 / 假设，研究者审阅修改后再据此设计），选一个模型，由它对照本功能目录分析怎么用 GAWorld 实现这项研究：研究问题与假设、可行性、「研究需要 → 功能 → 用法 → 入口」映射、2–3 种思路不同的实验设计（城市 / 人口 / 时间跨度 / 条件 / 事件 / 指标 / 优劣，标出推荐的一种，转成研究时可任选其一）、逐步实施步骤、可信度检验、局限与替代、成本估算；方案存档并可下载 Markdown | 主页「研究工作台」入口 / 控制台「研究工作台」页签 → `/site/dashboard/research.html`；接口（论文）`POST /api/research/digest` →（带上改过的 `digest`）`POST /api/research/analyze` → `GET /api/research/jobs/<id>` → `GET /api/research/plans/<id>`；产物 `output/research/<id>.json`；详见 [研究工作台教程](RESEARCH_WORKBENCH_TUTORIAL.md) |
| AI 社会科学家（研究闭环） | 把一份方案**编译成预注册协议**（条件 = 平行世界、假设 = 指标 + 两个条件 + 方向 + 最小效应，指标只能选自可测量目录，选不到的假设被丢弃并注明原因）→ 跑前检查（处理条件、可评估假设、事件显形时间、调用量预算）→ **批准**（copilot 默认停在这里；autopilot 只在检查通过时自动批准）→ 每个种子跑一次平行世界实验（自动补安慰剂世界）→ 代码按固定规则判定每条假设（supported / contradicted / inconclusive / unmeasured，附判定依据、安慰剂噪声底线与种子层面 t 区间；对照条件是基准时还要求每个种子的居民配对检验同向显著，否则降为 inconclusive）→ 模型只解读给定数字（挂不上假设的结论标为不作数）→ 研究报告（预注册在前、结果在后）。两种设计：**平行世界**，或 **composite（先跑世界，再采访居民）**——方案要测态度（信任、满意度、支持与否）时编译出跑后问卷（量表 / 是非 / 开放题，最多 8 题），每个种子跑完后在每个世界里用该世界的记忆与最后状态采访居民，量表与是非题成为 0–1 指标 `survey.Q<n>` 进判定（同一批居民跨世界逐人配对检验；答不上的不算 0），开放题只进报告。**指标来源等级**：每个可测量指标带它依赖的机制里最弱的一级（(a) 真实数据校准 / (b) 文献标准机制 / (c) 自定或标定的旋钮）和一句「由什么驱动」；目前全部是 (c)——九维状态对事件的反应由一次模型调用给出。(c) 级指标的效应在结果和报告里标「只读方向，大小不作数」，模型解读给它写具体大小会被标出；判定规则不变。**两个模型分开选**：顶部「分析用的模型」编译协议与解读结果，预注册里的「仿真模型」决定居民跑在哪个模型上（留空 = 按配置路由；批准前可改，写进报告的元信息）。运行中可**暂停 / 继续**（挂起正在跑的世界进程，之后的世界排队等待）；跑完或中断后可**重置运行**（清空结果回到已批准，重跑另起一份实验产物）；被重启或崩溃打断的运行会在下次读取时标成「中断」，不再永远显示运行中 | 研究工作台方案下方「转成研究」→ 右栏「研究」列表；接口 `POST /api/research/studies` → `.../studies/<id>/update｜approve｜run｜pause｜resume｜stop｜reset｜delete`、`GET .../studies/<id>[/report]`；产物 `output/research/studies/<id>/{study.json,report.md}`，每个种子的世界在 `output/parallel_worlds/study_<id>_s<seed>/`（重跑为 `study_<id>_r<n>_s<seed>`；「平行世界」页签可直接打开；composite 的问卷在各世界目录的 `survey.json`）；设计见 [提案](proposals/2026-09-19-ai-social-scientist.md) §2.6、[教程 §4.5](RESEARCH_WORKBENCH_TUTORIAL.md#45-问卷先跑世界再采访居民) |
| 从社交内容创建智能体 | 用社媒页面或文本生成新 agent 画像 | `python generative_city_sim.py create-agent-from-social --url "..."` / `--file ... --name "..."` |
| RAG 外部知识注入 | 向某 agent 注入外部信息以改变其认知 | `python generative_city_sim.py rag-add --agent-id 31 --text "..."` / `rag-import --file ...` |
| 事件对照实验 | 在"有事件 / 无事件"两分支并行仿真并出对比报告 | `python generative_city_sim.py compare-event --event-name "..." --sim-days 3 --seed 42` |
| 平行世界实验 | 一次实验最多 8 个世界，共用同一批居民 / 种子 / 天数 / 模型，各带自己的事件表（或 `config` 补丁）；报告给出逐步偏离度、分叉点与逐人影响，而不只是终值差；并做反事实推断：每个世界 × 指标的配对平均处理效应（同一居民两个世界之差）、按居民 bootstrap 95% 区间、符号翻转随机化 p、BH-FDR q、事件前平衡检查与 DiD、安慰剂噪声底线、起效 / 峰值 / 持续度、剂量反应；可一次重复多个种子并按种子合并 | `python generative_city_sim.py parallel-worlds --spec worlds.json`；详见 [平行世界教程](PARALLEL_WORLDS_TUTORIAL.md) |
| 本地 Dashboard | 配置编辑、运行控制、记忆查看、访谈、日志查看 | `python generative_city_sim.py dashboard --port 8766` → `http://127.0.0.1:8766/dashboard` |
| Dashboard 智能体互动 | 对两位或更多居民建立双向好友关系；启动独立于主仿真的多轮讨论，并实时观察发言、摘要与完整记录 | Dashboard「智能体互动」面板；会话与事件写入 `CONFIG["collaboration"]["sessions_dir"]` |
| Dashboard 合作任务 | 多智能体按“规划 → 分工执行 → 同伴审阅/修订 → 汇总”完成任务，展示可观测事件与 Markdown 产物 | 控制台「合作任务」页签 → `/site/dashboard/collaboration.html`；产物位于 `<sessions_dir>/<session_id>/artifacts/` |
| Agent Studio | 单智能体 7 步可视化构建/查看：身份、九维状态（可编辑雷达）、技能、记忆、Dunbar 社交、行为、复核部署；写回 CSV+profile，可创建新 agent | 控制台工具栏「Agent Studio ↗」→ `http://127.0.0.1:8766/site/dashboard/studio.html` |
| 智能体工作台家庭编辑 | 逐人指定婚姻状态、伴侣（可指定名单里的另一位居民 / 场外人物）、子女与同住长辈；保存为覆盖项，**跨运行生效**并优先于自动抽样，可一键恢复自动生成 | 控制台「Agent Studio ↗」→ 第 5 步「社交 · 关系」；写入 `data/family_overrides.json` |
| 智能体工作台 Moltbook 开关 | 逐人把居民接到 Moltbook（AI 智能体的社交网络）：打开开关即为他注册账号并给出认领链接（认领在浏览器里完成，认领前 Moltbook 不接受发帖）；认领后每个仿真日结束把这一天写成一篇帖子（模型用他的口吻代笔，没模型就发原样摘要；遵守 30 分钟一帖的限制，赶不上的日子并进下一篇）并读一遍信息流；注册、状态、发帖、浏览、验证与失败逐条记录，卡片里直接看。关掉开关账号保留 | 控制台「Agent Studio ↗」→ 第 7 步「复核 · 部署」→ Moltbook 卡片；接口 `GET /api/moltbook/agent?id=` / `POST /api/moltbook/toggle` / `POST /api/moltbook/refresh`；账号与密钥 `data/moltbook_accounts.json`（不入库）；记录 `output/moltbook/agent_<id>/actions.jsonl` 与 `output/records/moltbook.actions.jsonl`；`CONFIG["moltbook"]`（配置面板「扩展与真实工作」分区） |
| 参数化人口合成 | 按人口学旋钮生成整座小镇（年龄金字塔、家庭结构、就业、收入基尼、社交图），产出与现有格式完全一致的状态 CSV + profile MD | `python -m gaworld.population --size 500 --seed 42 --out data/town`；`--check` 只预览不写文件 |
| 群体（cohort）模拟 | 把人口划分成群体，每群每天 1 次 LLM 调用 + 按预算实体化少数个体，实现大规模人群的低成本模拟 | `python -m gaworld.group --size 500 --days 7 --no-llm`；`--focal 7,42` 全程跟踪指定居民；`--network-coupling 0.7` 开社交图耦合（不开则验证门 L2 不通过）；不加 `--no-llm` 会真的调 LLM，运行前先打印预估次数；**主运行里的群体模式**：`simulation_mode: "group"` + `python generative_city_sim.py run --fast-forward`——群体推进大多数人，实体化与审计样本跑普通快进简报，产物与普通运行相同（全部居民的状态历史 + `group.day` 记录），审计残差超阈自动加审计样本；不能用于网络扩散类问题，见 [群体模拟教程 §6.5](GROUP_SIMULATION_TUTORIAL.md#65-主运行里的群体模式) |
| Rubric-Bench 人类锚点校准（Track R · P4） | 检验 LLM judge 给居民行为打的主观分是否和人一致：从一次运行按 R1–R4 维度分层抽 30 题（约三分之一用破坏算子改坏，盲标），两名标注者在标注页逐题按 rubric 打 0 / 1 / 2，judge 集成给同样的题打分，算人-人 α（≥ 0.7）与人-judge Spearman ρ / QWK（≥ 0.6），列出重写队列；没有通过的校准时 Track R 的 trust gate 停在 UNVERIFIED | 标注页 `/site/dashboard/rubric-calibration.html`；`cd benchmark && python rubric_calibrate.py --build｜--judge --set <id> --judges a,b｜--analyze --set <id>`；接口 `GET /api/bench/calibration[/<id>]`、`POST /api/bench/calibration/build｜<id>/label｜<id>/analyze`；产物 `benchmark/results/rubric_calibration/<id>/`；设计见 [GAWORLD_RUBRIC_BENCH §5.3](../benchmark/GAWORLD_RUBRIC_BENCH.md) |
| GAWorld-Bench Track B · 对局层规律 | 谣言扩散局、公投局、灾害模式每跑完一局存一份到 `output/games/<kind>/`（结果 + 路由到的 provider + 多人模式下谁玩的），`--track B` 合并同类对局检三条事先定好的规律：公投从众（不带口径、私下有严格多数的局里朝多数改的票显著多于背离的）、灾害中极度恐慌少见而互助常见、辟谣后相信度下降但不归零（持续影响效应，读谣言局新增的 `beliefs` 历史）。每条少于 5 局可用对局就弃权，弃权照样拉低分数；各条 (c) 级、附文献与**提示词线索**，混合模型时标出。是居民对提示词的一步回应，不是回路涌现 | `python benchmark/gaworld_bench.py --track B [--games-dir <目录>]`；`POST /api/bench/run`（`track: "B"`、`games_dir`）；见 [GAWORLD_BENCH_DESIGN](../benchmark/GAWORLD_BENCH_DESIGN.md) Track B |
| GAWorld-Bench Track D · 人类判别 | 读「谁是真人」的存档（`output/games/whois/`），把所有局的票合起来：`score_D = min(1, 居民被判为真人的比例 / 真人被判为真人的比例)`——以真人互判的通过率为分母，居民「和真人一样像真人」就是满分；另报判断正确率与按票算的 Wilson 区间（票不独立，偏窄）。少于 5 局、对居民少于 20 票或对真人少于 10 票时弃权（`n/a`）。说的是这个群聊格式下像不像同桌的真人，附格式与评委线索；设计里的四个 LLM 评审维度仍未实现 | `python benchmark/gaworld_bench.py --track D [--games-dir <目录>]`；`POST /api/bench/run`（`track: "D"`）；见 [GAWORLD_BENCH_DESIGN](../benchmark/GAWORLD_BENCH_DESIGN.md) Track D |
| 经典实验库（居民当被试） | 六个教科书范式交给城里的居民来答：框架效应、锚定效应、独裁者 vs 最后通牒、最后通牒回应方、信任博弈（同小区 vs 外地人）、公共品博弈（回报率高 vs 低）。每个居民答每个条件（各自一次无状态调用），按人配对，判定只看方向（配对符号翻转 p<0.05：复现 / 反向 / 未复现 / 样本不足）；人类结果并排对照、不进判定，按收入 / 年龄的分组是探索性的。原始回答落盘可续跑，默认 40 人六个范式 640 次调用 | `python -m gaworld.experiments.classics list｜run [范式…] [--subject-limit N] [--dry-run]｜analyze`；见 [CLASSIC_EXPERIMENTS](CLASSIC_EXPERIMENTS.md) |
| 群体模式验证门 | L1–L4 配对实验，量化 cohort 近似的代价并给出"能回答哪类研究问题"的结论；分水岭层不过时退出码为 1 | `python -m gaworld.group.validate --size 100 --days 14 --network-coupling 0.7` |
| Population Studio | 5 步可视化：选模板（预设带说明）→ 人口结构（目标 vs 实际 + 金字塔/洛伦兹/度分布）→ 心理状态（均值雷达 + P25–P75）→ 跑模拟（可选后端模型）→ 检查结果（白话判定 + 文件可直接点开）；指标统一中英文双标 | 控制台「人口与群体」页签 → `http://127.0.0.1:8766/site/dashboard/population.html` |
| 外部系统观测台 | 观察并编辑世界本身：货币系统（宏观周期、部门池、货币守恒审计、财富分布与基尼）、外部环境生成器（自然/经济/政策/科技事件时间线与生成参数）、对外服务（连通性即时探测、LLM 路由、外部信息源）。配置表单按配置自身的 JSON 形状生成，约 150 个旋钮可编辑；另可对**跑着的**仿真排一次货币干预（改宏观状态 / 给部门池注资），由仿真在下一个日边界消费。指标与旋钮几乎都带 hover 白话说明（`?` 悬停，说的是「改了会怎样」而非复述标题） | 控制台「外部系统」页签 → `http://127.0.0.1:8766/site/dashboard/external.html`；详见 [外部系统教程](EXTERNAL_SYSTEMS_TUTORIAL.md) |
| 平行世界 · 反事实推断（研究工作台页签） | 左边设计实验（世界、事件、模板、基准、世界角色「处理 / 安慰剂」、剂量、重复种子数；或用**参数扫描**选一个数值配置项、填几组取值，自动生成「基准（保持当前值）+ 每个取值一个世界（剂量 = 取值）+ 可选的基准副本作安慰剂」，基准世界的事件复制到每个世界，路径不存在 / 非数值 / 实验级设置直接报错），右边读结果：分叉图、逐指标走向对比（只看与基准的差时带逐步 95% 带）、偏离曲线与分叉点（有安慰剂时阈值按它校准）、**反事实推断**（效应森林图 + 估计表：ATE、区间、p、q、d_z、DiD、判定；可切换对照世界，不用重跑）、**机制线索**（各指标起效先后）、**异质性**（按性别 / 年龄段 / 户籍 / 事件前水平的条件效应与置换检验）、**跨种子重复**、**剂量反应**、**模型解读**（一次模型调用把这些表写成结论、局限与下一步实验；每条发现须对回估计表的一行并带上该行判定，对不上的标「不作数」，按对照世界缓存）、终局差异表、「谁被改变了」逐人表。每个世界的轨迹仍可逐帧回放；compare-event 旧结果与研究按种子跑出的实验都会出现在历史里 | 研究工作台「平行世界 · 反事实推断」页签 → `http://127.0.0.1:8766/site/dashboard/research.html?tab=worlds`（旧地址 `worlds.html`、`/console#worlds` 自动跳转）；接口 `GET /api/parallel-worlds/experiment?root=&baseline=`、`/api/parallel-worlds/heterogeneity`、`POST /api/parallel-worlds/sweep`；命令行 `python generative_city_sim.py parallel-worlds --sweep economy.shocks.layoff_base_prob=0.0005,0.002,0.004 [--placebo]`；详见 [平行世界教程 §13](PARALLEL_WORLDS_TUTORIAL.md#13-反事实推断效应区间异质性与重复) |
| 游戏场（斗兽场 · 说服游戏 · 灾害模式 · 谣言扩散局 · 双队竞赛 · 公投局 · 猜人局 · 谁是真人） | 拿真实居民当对手玩一局。**斗兽场**：一组居民同台答题（数学 / 常识 / 逻辑 / 阅读 / 翻译，内置题库或 LLM 现场出题），按正确率 + 中位耗时排座次，留存 Top-K，其余进淘汰名单，再从别的城市补人。**说服游戏**：挑一个居民问一个有立场的问题记下他的答案，在设定的最大轮数内跟他聊天试图说服；结束时复问同一个问题，裁判 LLM 比较首尾两个答案，**核心结论真的变了**才算说服成功（措辞变化、让步但结论不变不算）。**灾害模式**：勾一批居民（≤ 12 人）扔进一场灾难（地震 / 疫情 / 战争 / 洪水 / 大停电，或自己写的），分幕推演，每人每幕一次调用并返回结构化反应（六类行动 / 具体做法 / 恐慌值 1-5 / 是否顾得上别人 / 一句原话），汇成逐幕的行动分布、平均恐慌与互助率，最后一次调用写一段城市简报；第二幕起「身边人上一幕做了什么」进提示词，从众与分化才看得出来。**谣言扩散局**：写一条传闻交给两个居民，看它沿着熟人关系往外走。关系图从档案里确定性地推导（同小区＝邻居、同小区同姓＝亲属、同行 / 同学 / 同龄各一种，每人限 6 条边），勾人的时候就能免费看到图；每个人只回一个小 JSON（信任度 0-100 / 转发·私下求证·辟谣·不管 / 一句原话），**模型决定传不传，图决定传给谁**；每人只开口一次，只有「信了之后被当面辟谣」的人能再开口，所以开销封在 人数 × 2 + 1。产出传播树、逐轮扩散曲线、最大传播者与「防火墙」（听说了、不信、也没往下传的人）。他的职业 / 性格 / 价值观直接进提示词，所以同一套说辞对不同的人效果不同。对局只在内存里，不写回城市包（谣言 / 公投 / 灾害三种另存一份到 `output/games/` 供 Bench Track B 统计，谁是真人揭晓后存一份供 Track D 统计）。**双队竞赛**：把居民编成两个队，同一个任务、两条相反的路子（自上而下 vs 自下而上、罚与盯 vs 奖与带…），每人按自己的档案出一招，汇成一份方案；从第二轮起看得见对手的方案，但两队看的是同一份快照，免得赢在出手顺序上。评审拿到的是「方案一 / 方案二」——队名和顺序都被洗掉，四个维度各 0–10 分，**赢家由总分决定**，模型自己说的赢家只作旁证，对不上就标出来。**公投局**：一个有人吃亏的议案交给 ≤ 14 人，**先私下表态、再公开表决**——中间那一屏带着票数、两边最响的原话和你写的一句宣传口径（全部由已有数据拼出，不额外花调用），产出民意位移、改票名单、差额与极化度；票面是 `{支持/反对/弃权, 坚定度, 一句话}`，不需要裁判模型；一票解析失败会重问一次——表决里丢一张票会同时污染票数、差额和位移。**猜人局**：读一份档案猜这个人在两难里怎么选，一局一次调用、几秒一把，是唯一能随手玩两把的；「再问他一次」用同一题复问同一人（≤ 3 次），顺带量出这份 persona 稳不稳。**谁是真人**：1–5 个真人和 1–5 位居民匿名进同一个群聊（座位只显示「N号」、顺序打乱），按话题聊 2–5 轮，每个真人再给每个别人投「真人 / 居民」；房主把座位链接发给朋友，每人一个链接、互相看不到身份；居民的提示词只要求像在群里随口说话，不告诉他有人在猜；揭晓后看每个座位被判成真人的票数、谁猜得最准，开销 = 居民数 × 轮数次调用。 | 控制台「游戏场」页签 → `http://127.0.0.1:8766/site/dashboard/games.html`；接口 `/api/games/{persuasion,disaster,rumor,duel,referendum,guess,whois}/*` 与 `/api/arena/*`；详见 [游戏场教程](PLAYGROUND_TUTORIAL.md) · [斗兽场教程](ARENA_TUTORIAL.md) |
| 轨迹回放查看器 | 可视化回放智能体移动轨迹；顶部「运行」下拉可选择任意一次已记录的仿真：当前运行（实时）、历史归档运行（`output/visualization/runs/<run_id>/`）、compare-event 等场景运行；`?run=<id>` 可分享指定运行 | `python generative_city_sim.py serve-viz --port 8000` → `/site/simviz/index.html`（Dashboard 内为「仿真回放」页签） |
| 分布式 relay | 多机协同仿真，各节点处理本地 agent 子集 | `python generative_city_sim.py serve-distributed --host 0.0.0.0 --port 8877` |
| 城市地图生成 | 用自然语言描述生成城市地图（节点 / 道路 / 地铁），就地覆盖单一 `data/citymap.md` | `python scripts/generate_citymap.py --description "..."` |
| 从地名新建城市 | 给一个真实地名，造出一整座可仿真的城市：Nominatim 地理编码 → Overpass 抓真实 OSM 路网/POI/地铁/河流 → 地图 + 环境事件 + 背景提示词；抓不到（小村庄、虚构地名、无网络）时按地名**确定性**程序化生成。每座城市是 `data/cities/<slug>/` 下的独立包（`city.json` 清单 + `citymap.md` + `map.geojson` + `environment.json` + `agents.csv` + `profiles.md`），互不覆盖。城市自带投影锚点，非杭州纬度的东西向距离不再偏差 ~30% | `python -m gaworld.city create "绍兴柯桥" --size 200`；离线：`create "柳溪村" --offline --scale tiny`；`list` / `show` / `delete <city> --yes` |
| 往城市里加智能体 | 三条路径：批量合成居民（复用 `gaworld.population`，住所自动落在该城真实存在的行政区上）、追加单个指定画像的 agent、把已有 agent 迁入并重新分配住所；三者都写成仿真器原生可读的 CSV + profile MD | `python -m gaworld.city add-agents <city> --size 200`；`add-agent <city> --name 林素 --age 34 --job "社区医生"`；`migrate <city> --agent-id 31` |
| 切换当前城市 | 选中某座城市后，`map_path` / `csv_path` / `md_path` / `map_mode`、环境事件表与 `background` 提示词整体指向该城市包；下次运行生效，`GAWORLD_CONFIG_OVERRIDES` 仍然优先 | `python -m gaworld.city use <city>`（写 `dashboard_config.json` 的 `city` 字段）；`use --clear <city>` 恢复默认世界 |
| 跨城市查看居民（只读） | 任意一座城市的居民都可以**不切换就查看**：直接读城市包，列表可按姓名/职业/住所/编号搜索并分页（默认 200 条/页，上限 2000），单个居民给身份 + 九个状态变量 + profile 原文。**只有当前运行城市的居民可编辑**——编号在每座城市各自从 1 开始，而记忆/大五人格/社交/财务是按编号存放的一个扁平命名空间、属于当前运行那座城，跨城市编辑会写到别人身上。复用 `gaworld/interview/roster.py` 的人口解析，不新增第二份 | 「城市」页签左栏下部「城市居民」；Agent Studio 左上「选择城市」；接口 `GET /api/city/catalogue` / `agents?city=&q=&limit=&offset=` / `agent?city=&id=`（`city` 省略 = 默认世界）；详见 [城市教程](CITY_TUTORIAL.md) |
| 城市面板 | 可视化新建城市（地名 / 规模 / 初始人口 / 离线开关）、城市列表与详情（坐标、地图来源、行政区、智能体数）、批量加居民 / 加单个 agent / 迁入 agent、一键「用这座城市运行」与删除 | 控制台「城市」页签 → `http://127.0.0.1:8766/site/dashboard/city.html` |
| 大五人格生成与合入闸门 | 一次性离线**先采样** 51 位居民的大五（OCEAN）z 分、**再据此改写**人物设定里的行为描述（51 次调用），产出 `data/agents_big5.csv` 与新增的 `人格与行为倾向` 字段，旧语料备份到 `data/hangzhou_profiles_with_names.v1.md`；独立性由采样器保证，只保留开放性↔`risk_preference`、外向性↔`voice_propensity` 两条 r≈0.3 的真实相关。两个闸门脚本分别量给定幅度下人格与行为的相关上限、检查五个维度是不是已有状态变量的线性组合 | `python scripts/author_personality.py`（`--dry-run` 只看提示词与采样分数，`--agents 1-5` 试水写 `output/traits/authored_preview.md`，`--apply` 全量落盘）；`python scripts/big5_effect_ceiling.py`；`python scripts/big5_collinearity.py --annotate`（生成后必跑，把不合格维度写回 CSV，运行时会打印警告）。`python scripts/calibrate_big5.py` 保留用于给外部导入的 agent 打分、以及作对照组校验打分器 |

Dashboard 讨论与合作会话支持暂停、继续和终止。服务重启时，磁盘上仍标记为
`running` 的会话会恢复为 `interrupted`，保留此前事件、讨论记录和合作产物，
等待用户明确继续或终止；已完成会话可直接重新读取。

## 二、核心仿真特性（配置开关）

| 功能特性 | 作用 | 访问方法 |
|---|---|---|
| 多后端 LLM 路由 | Ollama / OpenAI 兼容 / Anthropic 兼容，可按任务分流模型 | `CONFIG["llm"]["routing"]["default"]` / `["tasks"]`；环境变量 `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` 等 |
| 记忆系统 | 短期 / 情景 / 长期总结 / 关系记忆 + 向量召回，跨天保持一致性 | 自动运行；`CONFIG["memory"]`；产物 `output/memory/` |
| 内生通胀（默认关） | 物价指数真的进账本：支出和房租按它计价，通胀率由居民的人均**实际**消费（不含房租和大病自付费）相对开头一个月的偏离决定（也可选按失业率的菲利普斯曲线，或沿用周期随机游走）；开启时周期相位自带的支出倍数按 1 计；月结时工资按上月物价涨幅的一半跟涨，预算按实际收入重做（跟涨不足 → 恩格尔系数上升）。关闭时通胀率和物价指数只是显示用的数字 | `CONFIG["economy"]["macro"]["inflation"]`；设计 [proposals/2026-10-03-endogenous-inflation.md](proposals/2026-10-03-endogenous-inflation.md) |
| 经济仿真 | 货币守恒闭环（企业/政府/银行部门池）、个税 + 五险一金真实代扣、恩格尔消费、现金约束 + 信贷、投资含共同市场因子、消费/房租路由到 agent、熟人借贷、宏观周期与冲击 | `CONFIG["economy"]`（子块 `sectors`/`credit`/`routing`/`friend_loans`）；产物 `output/economy/`（含 `conservation_audit.csv`、`sectors.json`） |
| 位置系统与交通 | 类别空间匹配、真实出行成本、高峰 / 天气影响、通勤记忆、区域价格 | 自动运行（依赖 `data/citymap.md`）；`gaworld/world/city_map.py` |
| 场所容量（满了就进不去） | 去商店 / 休闲场所时，若人数（一个居民按 `agents_represent` 个真人计）会超过该地点容量，就改去最近的、同类、开着门且有空位的场所；都满就去不成、原地不动，下一步感知里知道原因。同一时刻扎堆到达也卡得住：本 tick 已放进去的人也算数，居民的处理顺序每 tick 按种子洗牌，所以谁抢到最后一个位置是可复现的公平抽签。住宅、单位、学校、医院、车站永不受限。**默认关**（开启前后的 run 不可比）；参数全是 (c) 类，见机制来源表 | `CONFIG["local_physical"]["capacity"]["enabled"]`（配置面板「本地环境感知」分区）；产物 `output/records/venue.redirect.jsonl` / `action.denied.jsonl`；设计 [proposals/2026-10-03-venue-capacity.md](proposals/2026-10-03-venue-capacity.md) |
| 室内房间（同屋才算碰面） | 室内空间树（楼 → 房间 → 家具，18 种按地点用途选的布局）从像素小镇搬进后端 `gaworld/world/spatial_tree.py`，前后端由测试锁成同一份。打开后住宅 / 公寓里每个家庭分到一户（citymap 的 Floor/Flat，不够往上加层），每一步按正在做的事把人放进房间（睡觉在卧室、在外吃饭在就餐区；访客不进厨房、库房等员工房间；在家时与家居插件说的房间一致）；偶遇要同一户同一房间，同楼邻居在家不再「碰面」；场所容量也开着时按房间算（房间容量 = 场所容量 × 面积占比，(c) 级），拒绝理由写出哪个房间满了。轨迹记录房间，室内视图按它摆人、住宅楼一次显示一户。**默认关**（开启前后的 run 不可比） | `local_physical.rooms.enabled`；见 [室内房间设计](proposals/2026-10-04-indoor-rooms.md) |
| 动态行为系统 | 承诺度感知中断、情绪即兴行为、社交偶遇链、环境事件级联、需求中断与日程恢复 | `CONFIG["dynamic_behavior"]["enabled"]` |
| 兴趣爱好与技能成长 | 为每个 agent 派生成长画像并动态演化（幂律学习、里程碑、遗忘衰减、发展四阶段、社交兴趣传染），影响日程、动作权重与工作选择 | `CONFIG["interests"]["enabled"]`（日终机制见 `interests.decay` / `interests.evolution`）；产物 `output/memory/agent_<id>_growth.json` |
| 社交网络 | 关系衰减、Dunbar 分层、off-screen ghost 事件 | 自动运行；`gaworld/social/network.py`；产物 `output/network/` |
| 家庭与户 | 按年龄段 × 性别抽样婚姻状态（未婚/已婚/离异/丧偶），匹配得上的居民在仿真内配成夫妻并**共享同一个住处**，配不上的补场外家人；子女、同住长辈、合租室友随之生成。家庭进入日程（接送、陪写作业、照料老人、回家吃晚饭）、账本（育儿与赡养开销按收入分摊、伴侣互相补现金缺口，全程守恒）、事件（同一件事同一 tick 落到全家人身上）与户内情绪传染。**户结构在运行中会变**：结婚、添丁、亲人离世、离婚、分手改写户记录并同步到同住的每位家人，仿真内夫妻离婚时一方搬走。**可选：家人成为居民**（`members_as_agents`，默认关）——同住的学龄子女和 60 岁以上长辈开局时成为有日程和认知的居民，账本上仍是被抚养人 | `CONFIG["family"]`（配置面板「家庭与户」分区）；产物 `output/records/family.*.jsonl`；详见 [家庭系统设计](FAMILY_DESIGN.md) |
| 离开本市（出差 / 探亲 / 旅行） | 城市不再是封闭的盒子：居民会离开几天再回来。**三类出行各由一个系统里已有的量驱动**——出差看职业（销售 / 外贸 / 咨询远高于图书管理员）在工作日触发，活动仍是工作、收入照常；探亲由关系 `obligation` + 距上次联系的天数触发，这是 `decay_relationships` 每天都在抬高却本来无处可去的那个量的第一个出口，回去一趟会重置 `last_contact_day` 并让 obligation 回落；旅行要周末 + 够用的流动储蓄 + 大五开放性 + 累积压力。目的地是**真实距离**（复用孪生的 34 个省级中心点与 `haversine_km`，起点取地图自身的几何中心节点），按距离分高铁 / 飞机定时长与票价，探亲优先去 ghost 档案里写的那座城市。在外期间：不占本市任何地点的拥挤度、不与本市任何人构成共处、不上本市的路、本地环境快照转静默（否则会把本市的天气报给人在北京的居民），家庭责任改为明说「你不在家，家里的事这几天得由家人顶着」。往返票在出发当天一次性记账，在外每日住宿与外食按 `daily_surcharge` 结算，全部走守恒支出通道。**出行决定全程纯规则、按种子可复现，不调用 LLM**。探亲 / 旅行占用的工作日按带薪年假发一天工资（每年 `paid_leave_days_per_year` 天，默认 5，之后记无薪假；周末不算、出差是工作），人在外地时经济模块不会再把活动改成「工作」。在外的日子默认压缩（`compress_away_days`）：不生成当天日程、跳过逐步的感知 / 计划 / 选动作 / 反思，改为每天一次快进日摘要（一条记忆 + 有上限的状态变化）——内核为此新增 `day.routine.skip` 扩展点与按步的 `step["_skip_stages"]`。本市的天气和街面事件（`natural` / `social`）不再作用到在外的人（`env.events.reach`），经济 / 政治 / 技术事件与政策照旧 | `CONFIG["travel"]["enabled"]`（**默认 OFF**——它改变每天城里还剩多少人，开启前后的 run 不可比）；产物 `output/records/travel.depart.jsonl` / `travel.return.jsonl`；设计 [proposals/2026-09-19-agents-leaving-the-city.md](proposals/2026-09-19-agents-leaving-the-city.md) |
| 生命事件 | 生日、疾病、关系破裂等调度事件 | 自动运行；`gaworld/events/life.py` |
| 状态候选事件（一点即触发） | 面板「人生事件」顶部按**当前人物的处境**排出 10–20 个候选大事件标签（离婚、退休、平台规则突变、重新找到工作…），点一下即刻对该人物触发。42 条目录按门槛过滤（离婚只给已婚的、退休只给 55 岁以上的、创业失败只给自雇的），再按状态变量打分排序；人物状态变化后标签集合自动重排。**点过的标签立刻消失**（进入冷却，按事件尺度 30 / 180 / 730 仿真天），冷却结束后回到候选池，再由当时的可能性决定要不要露面 | 面板「人生事件」标签云；`gaworld/events/candidates.py`；`GET /api/life-events/candidates?agent_id=<id>`，点击回 `POST /api/life-events {"candidate_key": ...}` |
| 就业事件（换工作 / 失业） | 「换工作」「失业」两个模板会**真的改写 `agent["job"]` 与收入**，不只是感知文本：换工作按新岗位的收入带重抽时薪（可在面板指定「新职业」，留空则自动跨行业转岗）；失业沿用裁员冲击的形状——大幅砍收入 + 30–90 天恢复倒计时，并把职业改成待业、记下 `previous_job`，倒计时结束后按原岗位收入带的 85–100% 复职（留疤）。日程也跟着换成「办理入职交接 / 熟悉新工作」「办理离职交接 / 求职投递」——**求职不发工资**（活动名刻意避开 `INCOME_KEYWORDS` 命中的「工作」二字） | 面板「人生事件」选模板 + 可选「新职业」；`gaworld/economy/finance.py:apply_employment_event`；日志 `[JobChange Day N ...] 旧职业 → 新职业（时薪 a → b）`，同时写进 `economy.shock_log` |
| 政策 / 环境事件 | 政策冲击与环境扰动注入仿真 | `CONFIG["policy_events"]`；`gaworld/env/system.py`；产物 `output/environment/timeline.jsonl` |
| PolicySim 干预评估 | 本地无网络评估推荐 / 曝光，记录立场 / 毒性 / 误信息 / 跨观点 / 奖励指标 | `CONFIG["intervention"]["enabled"]`；产物 `output/intervention/intervention_metrics.csv` |
| 外部信息源与信息食谱 | 居民从**新闻 / 社交媒体 / 专业网站**三类信息源读外界：注册表登记 37 个免登录源（新闻站 RSS、微博 / 百度 / B站热榜、Reddit / Hacker News、arXiv / WHO / 机器之心 / 36氪 等），按**真实时间** TTL 抓进缓存；每位居民按职业 → 领域标签、兴趣词、`platform_dependence`（社交份额）、大五开放性（拓宽到不对口与外语源）分到一份确定性的「信息食谱」，主动检索先从食谱里抽，摘要太短就抓正文，记忆条目记下 `渠道：专业网站 · WHO News`。搜索引擎链新增免密钥的 `ddg` 与带密钥的 `brave` / `tavily`，爬结果页的三个退为兜底。顺手修掉源清单正则（此前 `https://news.baidu.com/` 被读成 `https://new`）并给首页缓存加真实时间门 | `CONFIG["news"]["sources"]`（默认 ON，插件 `infosources`）；注册表 `data/info_sources.json`；产物 `output/infosources/feed.json` / `diets.json`；`python -m gaworld.infosources list / refresh / show <id> / diet --job "社区医生"`；密钥 `BRAVE_SEARCH_API_KEY` / `TAVILY_API_KEY`；设计 [proposals/2026-09-19-agent-information-sources.md](proposals/2026-09-19-agent-information-sources.md) |

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
- [群体采访教程](GROUP_INTERVIEW_TUTORIAL.md)（跨城市问一群人、题型统计、图片/网址、连续追问、文档导出）
- [家庭系统设计](FAMILY_DESIGN.md)（婚姻抽样、共居、家庭日程与账目、覆盖层与工作台编辑面板）
- [大五人格子系统设计](proposals/2026-08-20-big-five-personality.md)（标定流程、三条通道、幅度与合入闸门）
- [外部系统教程](EXTERNAL_SYSTEMS_TUTORIAL.md)（货币系统 / 外部环境 / 对外服务的观察与编辑）
- [平行世界教程](PARALLEL_WORLDS_TUTORIAL.md)（多分支反事实实验：设计、读图、剂量反应与安慰剂对照）
- [研究工作台教程](RESEARCH_WORKBENCH_TUTORIAL.md)（论文解读 → 多种实验设计 → 预注册协议 → 平行世界运行 → 代码判定与报告）
- [经典实验库](CLASSIC_EXPERIMENTS.md)（居民当被试的六个教科书范式，按人配对、只读方向）
- [游戏场教程](PLAYGROUND_TUTORIAL.md)（斗兽场排座次与留存、说服游戏的判定规则、怎么加一个新游戏）
- [测试用例设计](TEST_CASES.md)（全功能详细测试 + 核心测试两套用例，`pytest --suite full` / `--suite core`）
- [项目结构](PROJECT_STRUCTURE.md) · [中文 README](../README.zh-CN.md) · [English README](../README.md)


## 持久组织主体（默认关闭）

社区资助与企业招聘共用持久身份、负责人、成员、版本化规则、有限账户和执行历史。名称与目标可修改，身份及既有账目保留。提供等额/困难优先资助、抽签/技能优先有限招聘、工资付款方路由、欠付及正常日边界续跑。控制台「组织」页与 CLI 都排队提交命令。支持单机逐 tick 与按日快进，启用时拒绝月/年和分布式组合；组织决策没有额外模型调用。

CLI 的 `compare` 可离线读取两个世界同一完成日的组织指标，生成中文 Markdown、JSON、CSV 规则对照报告，保留分母、未知群体、规则版本与来源哈希，并检查申请和账目一致性。结果属于描述性差异。

组织页可下载当前世界最近完成日的原始指标 JSON；只读查看者也可下载。导出接口支持指定旧世代和完成日，保留原始内容与 SHA-256，新世代不会误取旧的最新文件。

详见 [组织教程](ORGANIZATIONS_TUTORIAL.md)。尚未接入预注册多来源自动评分；没有自动生产销售收入。
