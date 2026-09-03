# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased] — 2026-08-29 — 大跨度模拟：以月、以年为时间单位

### Added

- **`long_run.unit`：快进的步长单位可以是 `day` / `month` / `year`。**
  按天快进已经够跑一两年，但调用量随天数线性增长——50 人跑 10 年 = 18.25 万次。
  选 `month`/`year` 后，一整个月、一整年被压缩成**每人一条阶段简报**
  （新 task `fast_forward_period`），10 年 × 50 人降到 **500 次**。
  CLI：`run --sim-years 10` / `--sim-months 24` / `--time-unit month`，
  三者任一都会自动打开快进。
- **Dashboard 工具栏同步可用**：新增「步长单位」下拉；「仿真天数」字段跟着单位变成
  **「仿真月数」/「仿真年数」**，填 10 + 年就是跑十年。浏览器只发
  `sim_span: {unit, count}`，**日历换算留在服务端**（`span_days`）——
  否则前端会多出一份 30/365 的近似算法，和后端的真实日历对不上。
  回读时按 `plan_horizon` 反推步数，所以 3653 天会显示成「10 年」而不是一个没人输入过的天数。
- **`gaworld/sim/_fastforward.py` 里的 `Period` / `plan_horizon` / `span_days`。**
  主循环从「按天 range」改成「遍历 Period」，`unit="day"` 时每个 Period 就是一天，
  于是**这就是原来的日循环**，行为不变。月/年周期锚在本次运行的首日上
  （不是自然月初），所以 `--sim-months 6` 永远是 6 步；跨度按真实日历算，
  大小月、闰年、断点续跑的日期偏移都对。
- 阶段简报比日简报多要 `highlights`（2–4 条里程碑），逐条写进记忆——
  这样**每个仿真月的记忆密度**不随步长单位塌掉。状态增量上限按单位放宽
  （月 ×2、年 ×3，不是 `sqrt(天数)`：一个月能明显改变一个人，但远不是 30 天独立随机游走），
  突发事件的**期望个数**按跨度放大（上限 4 件/步）；`days=1` 时这两条都退化成原来的公式。
- **人生事件新增「换工作」「失业」两个模板，可从 Dashboard 手动触发。**
  这两件事**真的改 `agent["job"]`**，而不只是出现在感知文本里——作息、通勤地点、
  目标、收入档位读的都是这个字段。失业沿用裁员冲击的形状（时薪按 50–85% 砍、
  30–90 天复职倒计时），另外把职业改写成「待业中」并记下原岗位，倒计时走完
  按原行业**降薪复职**（`_rehire_after_unemployment`）；换工作按新岗位的收入档
  重新抽时薪，没填目标岗位时从**当前行业以外**的岗位池里抽一个（即转行）。
  Dashboard 选「换工作」时多出一个「新职业」输入框（留空=自动转行）。
  当天日程也会被改写：失业 → 办理离职交接 / 求职投递，换工作 → 入职交接 / 熟悉新工作。
- **「定时运行」：在运行仿真旁边指定一个开始时刻，到点自动启动。**
  定时器放在**服务端**（`/api/run/schedule`、`/api/run/schedule/cancel`），
  不是页面里的 `setTimeout`——所以关掉浏览器、切走标签页都不影响。
  提交时把当前表单配置一起存进这次定时里，到点按那份配置启动，等同于那一刻按下
  运行仿真。时间按**运行 dashboard 的机器的本地时钟**算，必须是将来的时刻。
  排期期间按钮变成「取消定时」，状态徽章显示「定时 …」；到点若启动失败
  （例如上一次运行还没结束），错误写进 `/api/run/status.schedule_error`，
  面板弹一次红色提示——定时器线程里没人接住的异常否则会悄悄消失。

- **粗粒度下的动作空间与事件空间**，不再沿用按日的那一套。
  - **动作空间**：月/年简报会拿到一份「人生动作」清单——直接读 `LIFE_EVENT_TEMPLATES`，
    所以菜单和执行它的机器不可能各说各话。模型选中的 key 会经
    `normalize_life_event` 变成真事件：状态效果、severity、余波，
    换工作/失业还会走 `apply_employment_event` 改写职业与收入。
    **清单之外的变化只进简报**——分清"改变了世界的"和"只是叙事的"。
    按天的步长**不提供**这份清单：一天的动作空间本来就是日内活动表。
  - **事件空间**：外部环境按整段跨度生成（新 task `external_environment_period`），
    要的是政策/行业/物价/人口流动/季节气候这类结构性驱动，
    而不是把"今天多云"当成一整年的背景。规则模式下跳过每日天气抽样，
    `intraday_rules` 直接丢弃——没有 tick 就没有东西可掷。

### Fixed

- **快进模式下整个人生事件子系统是死的。**
  `_drain_tick`(on_time_tick) → `_agent_events`(env.events.compose) →
  `_apply_state_effects`(state.effects) 全都挂在 tick 上，而快进不跑 tick。
  后果：从面板排进队列的人生事件永远不触发、`state_effects` 从不生效、
  换工作事件从不到达 `apply_employment_event`。这在**月/年尺度上最致命**——
  那个尺度上人生事件几乎就是事件空间的全部。
  新增 `life.step`：每步执行一次同样的流水线（复用 `_apply_state_effects`
  与 `_apply_job_change` 本身，避免两条路径漂移）。
  一次 drain 覆盖整个步长的天数区间——`_event_is_due` 本来就把早于当前日的事件算作到期。

- **选了「月」/「年」但没勾「长时段快进」时，实际仍按天逐日跑完整个跨度。**
  面板上这是两个独立控件，于是「仿真年数 = 2 + 步长单位 = 年」存下来的是
  `{"enabled": false, "unit": "year", "sim_days": 731}`，
  而 `step_unit` 是 `LONG_RUN_UNIT if LONG_RUN_ENABLED else "day"`——
  731 天全走日内 tick 循环，既不是用户要的，也贵得离谱。
  现在**粗粒度单位本身就意味着快进**：`long_run_enabled()` 与
  `generative_city_sim` 的导入期全局都这么解析，CLI 的
  `--sim-years → --fast-forward` 只是同一条规则的老写法。
  `unit=year, enabled=false` 不是一个有意义的组合——**没有按月的日内循环**。
  面板同步跟上：选月/年会自动勾上「长时段快进」，取消勾选则把单位退回「天」，
  存盘时也写入 `enabled: true`，免得下次打开时勾选框对配置撒谎。

### Changed

- **日边界钩子在粗粒度下按 ≤30 天区块补跑**（`plan_hook_chunks` /
  `long_run.hook_chunk_days`），而不是一个周期只发一次。否则跑一年只会扣一天房租。
  30 天上限是有意的：一个区块最多跨一次月结算，于是 `finance.py` 那段一百多行的
  月度结算逻辑**一个字都不用改**——`month_gross_income` 仍然只装一个月的工资。
- `economy/finance.py` 读 `context["period_days"]`：固定支出 × 天数、宏观周期推进
  × 天数、冲击（裁员/涨薪/医疗）**每天掷一次**（所以裁员恢复倒计时按天走——
  失业事件的 30–90 天复职倒计时同理，粗粒度下不会被拖成 30–90 *步*）。
  `is_month_end` 从 `sim_day % 30 == 0` 改成「这次发射是否跨过 30 天边界」，
  `days=1` 时两者等价。
- `goals_plugin` 的目标周回顾在粗粒度下**每步一次**（最后一个区块），
  而不是每个补跑区块一次——回顾是认知节拍，不是记账节拍。年步长下从 12 次降到 1 次。
- 两处认日志格式的地方跟着改：`benchmark/rubric/loader.py` 的 `detect_run_mode`
  改成匹配 `[FastForward ` 前缀（否则月/年运行会被判成 `unknown`，
  rubric 就不会在它该弃权的题上弃权）；`gaworld/parallel/runner.py` 的 `_DAY_RE`
  加上粗粒度横幅 `===== Month 3 · Day 90` 一支——所以粗粒度横幅里带上了该步的**末日号**，
  「Month 3」是步序号不是天数，直接拿去算进度会错。

### Fixed

- **快进模式下 agent 只付房租不挣钱。** 工资本来是逐时刻由 `on_agent_post_step`
  结算的，而快进根本不跑日内循环——于是每天扣房租水电、收入恒为 0，
  跑满一年全员破产。现在无 tick 的步骤按
  「宏观调整后的时薪 × 目标工时 × 工作日数（5/7）」补记一笔近似工资，
  从 firms 资金池支出（货币守恒），并计入当月计税基数。
  有 tick 跑过（`daily_income > 0`）时是 no-op，所以精细模式一位不变。
  这个洞按天快进时就存在，只是跑 600 天才显形；粗粒度让它变成必修项。

## [Unreleased] — 2026-08-29 — 配置面板读的是快照，重置看起来像没生效

### Fixed

- **`dashboard_server._effective_config()` 返回的是导入时的快照，会过期。**
  `settings/overrides.py:86` 在**导入时**就把 `dashboard_config.json` 合进了
  `CONFIG`，而 `_effective_config()` 做的是 `deepcopy(CONFIG)` + 再合一次
  dashboard 层。两者一致时看不出问题，但只要面板**写过**覆盖文件就会分叉：
  - 重置一个键 → 覆盖文件里删掉了，`CONFIG` 里还留着 → **面板显示旧值**，
    用户以为重置没生效；
  - 「默认值」那一层因此也不是 Python 默认，而是"已经被覆盖污染过的默认"。

  这正是这个面板存在的理由——"改了但看起来没改"——反向发生了一次。
  改成从 `build_default_config()` 重新叠加三层覆盖，顺序与
  `apply_runtime_overrides` 一致（env 叠两次，所以它压过 environment 文件）；
  dashboard 层取自 `_dashboard_config()`，让模块里的路径常量仍是唯一的注入点。

  与当前磁盘状态下的 `CONFIG` **逐键逐值完全一致**，所以进程刚启动、文件没动过时
  行为不变；只有在文件被改写之后才分叉——而那正是旧行为出错的时候。

- 顺带解释了那条一直红着的
  `test_reset_deletes_the_key_instead_of_writing_the_default_back`：
  它**不是**脆弱测试，而是真的抓到了这个 bug。它只在开发机的
  `dashboard_config.json` 恰好写过 `sim_days` 时才失败——因为断言里的"默认值"
  被真实文件污染了，所以看起来像环境问题。

## [Unreleased] — 2026-08-29 — 社交影响：关系有走向，圈子会重组

### Added

- **关系轨迹**（`relationships`）。`relationship_update` 记的是**一次互动**
  （亲密度 ±0.03）——这是 tick 的正确单位，放到一年就是噪声。
  粗粒度下简报报告的是这段时间关系的**净走向**，由
  `apply_closeness_delta()` 落地：单步上限 0.25，信任按一半速率跟随
  （更慢建立、也更慢失去）。
  **正的增量算作有来往，会重置衰减计时；负的刻意不重置**——
  疏远本来就是"没有来往"，让衰减继续跑才是它继续疏远的原因。
- **新关系**（`new_ties`）。此前社交图只会缩小（衰减 + Dunbar 剪枝），
  跑十年的结果是所有人都比开局更孤独——这是模型的假象，不是发现。
  现在搬家/换工作之后可以结识新的人，但**只能从运行中真实存在、且尚未认识的居民里选**
  （提示词里给候选名单，越界的一律丢弃），role 限定在 6 个可信角色内。
- **换工作会让同事变成前同事**（`retire_work_ties()`）。角色表里
  `coworker` 衰减 0.006/天、义务 0.42，`former_coworker` 是 0.015 / 0.20——
  语义一直都在，但**从来没有人执行这次切换**：换了工作的人会继续按"天天见面"
  的速率维系一家已经离开的公司的同事。
  `SOCIAL_NETWORK_DESIGN.md` §6 把它列为"当前需要外部触发"，
  就业事件正是那个触发器。注意光改 `role` 不够——
  `ensure_relationship_schema` 用 `setdefault` 填角色字段，
  衰减率必须显式改写，否则会永远保留旧值。

### Changed

- 阶段简报的社交输入从"熟人名字列表"换成**带当前亲密度、按亲密度排序的重要关系**。
  只给名字，模型只能报"见过面"，报不了"谁走近了、谁淡了"。

## [Unreleased] — 2026-08-29 — 大跨度模拟的对象是一生，不是一张作息表

粗粒度下要模拟的是**长时段的事件、状态变化、环境与社交影响、个体发展**，
而不是把日程表拉长。上一版补齐了事件与环境，这一版补齐**输入框架**与**个体发展**。

### Changed

- **阶段简报的输入框架换掉了。** 原来的锚点是「今天的作息骨架 + 最近 3 条记忆」——
  一天用时刻表描述是合适的，一年不是；三条记忆是一年里某一周的三句话，看不到弧线。
  现在给的是：
  - **处境**：年龄、职业、居住、家庭类型；
  - **阶段历史**：前几个阶段的简报（`agent["_period_briefs"]`，留最近 6 条），
    而不是日级记忆；
  - **成长档案**：每项技能/兴趣的当前水平与每周目标——没有基线就谈不上进展；
  - **重要关系**：带**当前亲密度**，按亲密度排序。原来只给名字，
    模型只能报"见过面"，报不了"谁走近了、谁淡了"。

  作息骨架保留为「生活底色」，并明确要求**不要逐日展开**。

### Added

- **`development`：简报要报告这段时间在成长档案各项上的实际投入**
  （`weekly_minutes` = 这段时间的平均每周分钟数）。新事件 `growth.step` 由
  `interests_plugin` 处理：按经过的周数**重放已有的幂律学习曲线**
  （`update_growth_from_episode`），而不是另写一套成长模型；
  日期按连续天推进，所以 streak 加成的行为和精细模式一致。
- **年龄会增长了。** `life.step` 上新增 `_advance_age`：累计天数，满 365 天涨一岁。
  按天累加而不是按步长除，所以由长短不一的步组成的运行，总增龄是一样的。

### Fixed

- **快进模式下技能只会衰减，永远不会成长。** 练习进度挂在 `episode.compose`
  （tick 事件）上，快进不产生 episode；而 `on_day_end` 的**衰减**照常执行。
  结果：模拟一年，阅读从 0.30 掉到 0.10，无论这一年怎么过——
  这与"个体发展"正好相反，而且恰恰坏在个体发展最重要的尺度上。
- **年龄在整个仿真里从来没有被写过**，只在读种子 CSV 时赋值一次。
  两周看不出来，十年就荒谬了：34 岁的人跑完十年还是 34 岁，
  而 `age` 是家庭分配、收入带、人生阶段推理的输入。

## [Unreleased] — 2026-08-29 — 环境模块去重：根目录那份变回 shim

### Changed

- **`environment.py`（根，705 行）不再是 `gaworld/env/system.py`（836 行）的副本，
  改成真正的 re-export shim（27 行）。** 仿真导入的一直是根目录那份，
  而 `AGENTS.md` 写的是"新代码只写进 `gaworld/`"——于是两份**双向漂移**：
  - 根目录那份长出了 `_safe_float`（容忍 list/None/字符串的配置值），包里没有；
  - 包里那份长出了 `_annotate_anomaly`，根目录没有。

  合并方向是让包成为严格超集：把 14 处 `float(...)` 换成 `_safe_float(...)`，
  逐符号 AST 比对确认除异常标注外**两份完全一致**，然后才换成 shim。

### Fixed

- **异常标注此前是死代码。** `gaworld/behavior/dynamic.py:876` 读
  `event.get("anomaly")`，但设置它的 `_annotate_anomaly` 只存在于**没被导入的那份**里，
  所以 `is_anomaly` 恒为 False——事件级联里的异常分支从未走到过，
  尽管 `anomaly.enabled` 默认就是 True。去重之后这条路径**开始真正生效**：
  普通天气仍不算异常，极端天气/突发/高严重度事件会被标记并触发更强的行为反应。
  **这是一次行为变化，不只是重构**：想回到旧行为把 `environment.anomaly.enabled` 置 false。

## [Unreleased] — 2026-08-29 — 就业事件：换工作和失业真的会换工作

### Added

- **「换工作」「失业」两个人生事件模板，会真的改写 `agent["job"]` 和收入**，
  而不只是往感知里塞一段文本。这是必须的：下游的日程、通勤、目标、收入带
  全都读 `agent["job"]`，只改感知等于什么都没发生。
  入口是 `gaworld/economy/finance.py:apply_employment_event`，
  由 `LifeEventsPlugin._apply_job_change` 在事件落到人身上时调用。
- **换工作**：转到 `event["new_job"]`（面板上的「新职业」字段），
  留空则自动跨行业转岗；时薪按**新岗位的收入带**重抽，
  并清掉可能正在跑的失业倒计时。
- **失业**：沿用裁员冲击的形状——砍 50–85% 收入 + 30–90 天恢复倒计时，
  下限钉在 `min_hourly_income`（**结算路径没有零收入分支**，真给 0 会炸月结算）——
  额外把职业改写成待业并记下 `previous_job`。倒计时结束后按原岗位收入带的
  85–100% 复职：失业留疤，但不至于把人永久打落。
  只有**事件**造成的失业会复职；随机裁员冲击保持原行为（只砍收入、不动职业文本）。
- 日程接上 `_LIFE_EVENT_ACTIVITY_MAP`：失业 →「办理离职交接 / 求职投递」，
  换工作 →「办理入职交接 / 熟悉新工作」。
  用「求职投递」而不是「找工作」是**故意的**——`INCOME_KEYWORDS` 按子串匹配
  「工作」，叫「找工作」会让求职本身发工资。
- Dashboard 人生事件面板新增「新职业」输入框（仅「换工作」模板可见，留空 = 自动转行）。

### Notes

- 事件按 id 去重（`_applied_job_event_ids`），同一个事件不会把收入砍两次。
- 变更会打印 `[JobChange Day N HH:MM] 姓名: 旧职业 → 新职业（时薪 a → b）`，
  同时进 agent 日志和 `economy.shock_log`，方便操作者核对前后。
- 覆盖测试：`tests/test_employment_events.py`（20 条）。

## [Unreleased] — 2026-08-22 — 逐句归因标定器：建好、自检通过、等跑

### Added

- **`scripts/calibrate_big5_by_sentence.py`：标定器串味的输入端修法。**
  不再问"这段话里有没有 C"，改成对**每一句**问"它落在哪几个维度"，
  再按维度聚合——**没有任何一句落在它上面的维度就是 unstated**，
  于是"有没有证据"从模型的自我报告变成聚合的结构性事实。
  **480 次调用**（160 句 × 3），比一次性打分器的 765 还便宜。
  判据（写了的格子 r ≥ 0.79、精确率 ≥ 90%、召回 ≥ 85%、每维偏移 ≤ 0.20）
  写死在脚本里，开跑前先打印。
- 自检（假打分器，零调用）：干净打分器精确率 **100%**、召回 95%、r 0.962，四条全过；
  串味打分器（leak=0.5）精确率 **65%** 单独挂掉，r 和召回照过——
  **正是要抓的缺陷的形状**：串味不伤"写了的格子"，只污染"有没有证据"。

### Fixed

- **自检抓出了我自己写的对照里的毛病。** 第一版假打分器每句只挑一个真实维度，
  而每人平均 3.1 句、3.0 个写了的维度，覆盖不全 → **正对照召回只有 72%，被判 FAIL**。
  一个本该通过的方法会被我的对照判死。改成每个真实维度以 0.7 概率被注意到之后，
  正对照四条全过。和 A4 上限判据那次同一类教训：**对照本身也得先被证明是对的。**

### Fixed（前端）

- **`test_console_registers_persistent_cooperation_tab`：断言写死了 i18n 之前的字节序列。**
  合作 tab 一直都在，变的是 i18n 落地时把**每个** tab 的中文标签
  包进了 `<span data-i18n="nav.*">`，而这条断言 pin 的是包裹之前的原文。
  改成按结构断言：按钮带对的 `data-tab`、带 locale 文件所依据的 i18n key、
  中英两个标签都在。下次改 markup 不会再假红，而 tab 真被删或改名时仍然会红。

### Notes

- 提案 §3–4 新增了第四种输出端过滤的实测（证据须逐字出现在原文）：
  精确率 71%→89%，代价是丢掉 **80%** 的真信号；而且接地度几乎不区分真假
  （真写的中位 0.43，凭空的 0.36）——它测的是引用风格，不是真假。
- **机制这次是证出来的**：没写的维度里有 11 条证据接地度 **1.00**（逐字照抄），
  恰恰是最糟的几条——agent 49 的 A 打 7.0，引的是为 E 写的那句。
  **逐字接地度在最严重的编造上取到最大值**，所以任何输出端过滤都必然失败。
- 我的云端副本先前缺 `site/`（24 个文件）与部分 `benchmark/`，已从设备完整取回；
  此前两次把容器的问题报成了仓库基线，现在容器和设备是同一份。
  取回之后重跑：`test_replay_runs` 自己绿了（确实是副本残缺），
  但 **`test_collaboration_frontend` 仍然红——那条是真的**，
  我上一轮把两条都归给"副本问题"，说对了一半。

## [Unreleased] — 2026-08-22 — 存量失败清账：补丁打空了，测试在假绿

### Fixed

- **`test_memory_recall_and_review` 的两条失败，根因是补丁打不中。**
  `patch.object(sim, "retrieve_relevant_memories")` 只有在被测函数**也**从
  `generative_city_sim` 的全局里解析这个名字时才拦得住。重构把 `evoke_memory` /
  `maybe_review_memories` 搬进了 `gaworld.sim._memory_recall`，它们从**自己模块**
  查名字，于是打在再导出上的补丁**什么也没拦住**。
  这比测试挂掉更糟：调用真的落到了真实向量库和真实 LLM 上，
  而测试代码读起来像是打了桩。改打到被测函数查名字的那个模块
  （`_memory_recall` / `_diary` / `llm.providers`），并加断言**桩必须真的被调用过**
  ——否则下次搬家它还会悄悄失效（补丁没被用到不会报错，只会给出另一个答案）。
- **顺手扫了同一类缺陷：全仓库 5 个测试函数中招，其中 3 个当时是「绿」的。**
  `test_needs_influence_action_choice` ×2 与 `test_relationship_weighted_social_context`
  的补丁同样打空，只是桩的返回值（空记忆）恰好和真实调用的结果一致，
  所以一直过。已改打到 `_action`；同时记下：当前代码路径上 `choose_action`
  通过 `recall_context` 参数拿记忆，根本不调 `retrieve_relevant_memories`，
  这个桩两处都是空转的——**那三条测试过关的原因与它们声称的机制无关**。
- 新增 `scripts/dev/audit_patch_targets.py`：静态找出打不中的 patch 目标，
  任何把函数搬出顶层模块的重构之后都该跑一次（有发现时退出码 1，可进合并前检查）。
  当前输出：干净。

### Changed

- **`test_memory_consolidation_decay` 的两条：拆成「机制」和「默认值」两件事。**
  它们从来没绿过——测试和 `settings/runtime.py` 是**同一个提交**（aca2ce7）加进来的，
  加进来就互相矛盾：settings 写 `enabled: True`，而 `consolidation.py` 的兜底是
  `cfg.get("enabled", False)`。原来的用例把「默认是关的」和「关掉之后是空操作」
  混在一条里断言。现在拆开：`test_disabled_*` 显式关掉再验机制（无争议），
  `test_the_current_defaults` 只**钉住**当前默认值并写明它未经复核。

### Notes

- **⚠️ 需要你拍板的一件事**：`memory.consolidation` 和 `memory.decay` **都默认开着**。
  也就是说，从不改配置的使用者会得到定期摘要，以及定期**删除**
  30 天以上、显著性低于 0.20 的记忆。在一个以纵向行为为卖点的模拟器里，
  「默认删记忆」应当是有意选的——**目前没有任何记录显示它被选过**。
  测试只把现状钉住，没有替你决定。
- **纠正我自己报的基线数（第二次了）**：我一直说「基线 6 个失败」，
  其中 **2 个是我这边云端副本的问题，不是仓库的状态**——
  `site/simviz/` 整个目录（24 个文件）在我的副本里缺失，
  `site/console/index.html` 是旧版本、没有 collaboration tab。
  设备上两样都在（`replay.test.js` 存在；`data-tab="collaboration"` grep 命中）。
  **真实基线是 4，现在是 0。** 云端跑出来的 2 failed 全部是副本残缺造成的。
  教训同上一条：报数之前先确认自己手上的是不是完整的那一份。

## [Unreleased] — 2026-08-21 — 动作生成分批：上一条修复在生产规模上不够

### Changed

- **`_llm_generate_actions` 按 `action_space.activities_per_call`（默认 3）分批。**
  上一条我写的是"抢救 + 短重试已经接住了，分批等实测再说"——**N=4 时对，
  生产规模上错**。把两个实测数放一起就清楚了：单个活动块中位 **193** 字
  （p75 215，来自 499 条未触顶的完整响应），可用输出预算约 **916** 字
  （512 token 上限），而真实一天有 **10** 个不重复活动
  （`output/memory/agent_37_schedule.json`，真实运行产物）。
  10 个要 ~1936 字 → **那次不分批的调用从来就不可能成功**：最多救回 4 个，
  重试再问剩下 6 个又撞同一堵墙。批量路径在真实日程下一直是残的，
  而缓存看着正常是因为 `ensure_action_space_for_activity` 在后面
  一个活动一次地把它们买了回来。
- **分批不比原来贵**（最容易搞反的一点）：10 个活动分 4 次全部成功，
  对比原来 2 次失败 + 之后每个活动各补 1 次 ≈ 12 次。
  `seed_actions` 也按组裁剪，不把另外七个活动的参考白抬进提示词。
  单活动路径（`ensure_action_space_for_activity`）仍是 1 次调用，未受影响。
- §16 的抢救解析**没有变成多余**：分批大小按中位数定，啰嗦的智能体仍可能撑爆某一组，
  那时抢救接住它。两层互补，不是二选一。

### Notes

- **纠正另一个先前的猜测**：agent_37 缓存的 118 个活动全部含 3–4 条通用兜底动作，
  但这不是损伤指标——`_ensure_behavioral_action_balance` 对**任何**输出都会补齐
  缺失的类别，包括完全正常的输出。纯兜底条目 0 个。
  以"出现兜底动作"判断污染是错的。
- **教训**：§16.5 我写"等实测数据再说，不凭空拍"，态度对，但**当时手上就有那个数据**
  ——设备的 `output/memory/` 里躺着真实运行的日程，我没去拿。
  "不凭空拍"和"先看看有没有现成的数"是同一件事的两半。

## [Unreleased] — 2026-08-21 — 输出截断：解析器把"被切了"当成"没说话"

### Fixed

- **`_parse_action_space` 判死 41.7% 的真实响应。** 拿 A4 留下的 848 条真实
  `actions` 响应实测（不是猜）：354 条返回 `{}`，是两个不同的病——
  **318 条被 `max_tokens` 截断**（响应长度在 ~1000 字处断崖，对应
  `providers.py` 里 `cfg.get("max_tokens", 512)` 的默认值），
  **36 条完整但 JSON 语法错**（模型用 ASCII 引号写中文引语，
  `以"来不及"为由拒绝`，字符串提前闭合）。
  后果不是一个被接住的错误：返回 `{}` → 全部活动算 missing → 重试**用同一份列表**
  撞同一堵墙 → 全天每个活动 4 条通用兜底动作，**两次调用花掉什么都没拿到**。
  生产比这个样本更糟不会更好——`generate_actions` 传的是一整天所有不重复的活动。
- **`repair_inner_quotes` + `loads_tolerant`（`_schedule.py`）。**
  这个语法里字符串只在下一个非空白字符是 `, ] } :` 时结束，其余引号都是内容——
  规则可判定，不是猜。安全性验过：**494 条本来就能解析的响应修复后逐字节一致 494/494。**
  `loads_tolerant` 只跑在 `json.loads` 已经拒绝的输入上，所以今天能工作的调用
  行为一个都不变——正因如此才放到全部 5 个解析器后面，而不只是量过的那一个。
- **`_salvage_action_space`：从没写完的对象里取闭合了的活动。**
  半截列表**丢掉而不是当短列表交出去**（交出去会让重试以为这个活动已经有了）。
  合计效果：0/4 恢复从 41.7% 降到 **0%**，93.4% 拿到 3–4 个活动，过短碎片 0 条；
  剩下 1–2 个交给**本来就存在的重试**——今天它没用是因为 missing 永远是全部。
- **`providers.py` 把 API 已经给出的信息扔了。** 只在文本为空时才看 `stop_reason`；
  非空但被截断的响应原样当完整答案返回，下游分不清"说了句读不懂的"和"说到一半被切了"
  ——318 次全程无声。新增 `_note_truncated`：Anthropic 的 `stop_reason == "max_tokens"`
  与 OpenAI 的 `finish_reason == "length"` 都计数，第 1/10/100/之后每 500 次打一条 warning，
  `truncation_counts()` 可读。**不抛异常**——截断的答案往往仍可用，
  把降级变成硬失败是更差的交易。

### Notes

- **更正我自己上一轮的说法**：我担心的"部分填充的动作空间被永久缓存"**不成立**——
  `save_action_space` 的 `strip_fallback_only_activities` 会丢掉纯兜底条目。
  真正的损失是两次白花的调用和一整天的通用动作。
- **没去调 `max_tokens`**：512 是 provider 级的成本/延迟策略，不该由一个解析缺陷决定，
  何况上面的修复对任何上限都成立。现在它至少**看得见**了。
- **没把 `generate_actions` 按活动分批**：那要先知道真实日程活动数的分布，
  等 `truncation_counts()` 的实测再说，不凭空拍。
- 新增 `tests/test_llm_output_truncation.py`（13 条），fixture 是真实响应的缩短版；
  最关键的一条是「对合法 JSON 必须恒等」——整个修复都压在这条性质上。

## [Unreleased] — 2026-08-21 — A4 跑完：prompt 通道默认关

### Changed

- **`personality.channels.prompt` 默认 `True` → `False`**，依据是 A4 臂
  1,632 次调用（提案 §15）：主判据 48/87（判据 52，p=0.196）、
  判别臂 16/30（p=0.428）均不达标，上限判据达标。
  按 §14.6 事先写死的规则触发，不是事后判断。**一行可逆。**
  新增测试 `test_the_decided_channel_defaults`——要翻回去得改一条把证据写进名字的测试。
- 每位居民的「人格与行为倾向」段落**不在这条通道上，开关都会渲染**。
  关掉的只是"在那之上再加一句所有同极人共用的泛泛话"。

### Fixed

- **`extract_phrases` 丢掉了 354/1632 个样本。** 查出来全部集中在 action 场景
  （routine 0%、action 40%），且全部是 JSON 被输出长度上限**截断**
  （长度 618–993，零个空响应），不是格式错误。三条件失败率几乎一致
  （40.1/43.5/41.7%），所以它不会在条件之间造差异——但直接丢也不中立，
  那是在按输出长度做选择。改成抢救截断对象里前面完整的条目，1632 条全可用。
  **判据未动，两套数并列写：丢弃版 46/85，抢救版 48/87，结论不变。**

### Notes

- **模型确实读了锚句。** 与风格分类器无关的文本检验：跨条件（anchor–plain）
  的字符二元组 Jaccard 0.1108，低于同条件的 0.1240，**Cohen d = 0.29**。
  结论因此不是"锚句无效"，而是"**锚句改变了文本，但没把选择推到决策循环看得见的方向**"。
- **仪器灵敏度是个必须写出来的限制**：段落这个信号独立验到 r=0.79，
  而风格标签只读出 |r| ≈ 0.09–0.24。零结果严格说是"在这个分辨率下量不出来"。
- **但没有剂量效应**：强锚句档（|z|≥1.5）同向 48%，比弱句档的 58% **还低**；
  按 |z| 分档 62/53/47/73% 非单调。仪器要同时藏住效应和剂量排序，
  得瞎得很有针对性——这是零结果不只是分辨率问题的最强内证。
- **没测 O 与 A**（routine=(c,e)、action=(c,n)）；裁定按 C/E/N 的证据下。
- 另记一个存量缺陷：生产路径 `_llm_generate_actions` 同样会被输出上限截断，
  后果是动作空间缺项→兜底动作→被缓存。不在本提案范围。
- **纠正上一轮的一个说法**：我报的"基线 8 个失败"里有两条
  （`test_daily_routine_context`）不该算——今天不改相关代码也自己变绿。
  把 `channels.prompt` 强制改回 `True` 重跑全量验证过，它们没有回来，
  与本次改动无关，是依赖 `output/` 缓存状态的隔离缺陷（与之前修掉的
  `test_life_event_severity_impact` 同一类）。**稳定基线是 6。**

## [Unreleased] — 2026-08-21 — A4 消融臂：建好、自检通过、等跑

### Added

- **`scripts/big5_prompt_ablation.py`：D5 的配对提示词探针。** 87 格
  （routine 43 + action 44）× {plain, anchor, placebo} × K=8 = **1,632 次调用**。
  判据（符号检验 k ≥ 52/87、|r| 上限 0.30、反向锚句判别臂）写死在脚本里，
  **每次开跑前先打印**——写死的意义就在于不能事后挑。
  `--self-test` / `--dry-run` 都是零调用；逐条样本落 JSONL，可断点续跑与只重算。
- **三条守卫**：两版提示词必须逐字节只差锚句行（开跑前强制检查，当前 87/87 通过）；
  方向由 `_action_style_tags` + `STYLE_LOADINGS` 定义，都是生产代码里的同一份，
  不由我临时判断；正负对照用假 LLM 先演一遍（植入 strength=0.9 → 87/87 检出；
  strength=0 → 46/87，假阳率 2.2%）。

### Fixed

- **自检抓出了我自己写的上限判据的缺陷。** 第一版扫遍
  (条件 × 维度 × 风格) 取最大 |r|，结果**在按构造零效应的负对照里判了 FAIL**
  （`plain/n→avoidant`，n=33，|r|=0.331）。取 16 个相关系数的最大值不是效应量，
  是多重比较的产物。改成：预先指定每维载荷最大的那个配对逐维度报，
  且只在**单侧 95% 下界**越过 0.30 时才算超出——判据要求这次运行把超出量证出来，
  而不是仅仅没能排除。改完负对照全达标、正对照全越界。

### Notes

- **本臂只能回答 C/E/N**：routine=(c,e)、action=(c,n)，O 与 A 不在范围内。
  脚本在 dry-run 和结果表里都会印这句；D5 若据此拍板，就是按 C/E/N 的证据拍的。
- **可检出范围**：d ≥ 0.30 功效 99%，d = 0.15 功效 68%，更小的推动本臂看不见。
  这是结论要带的限制条件，不是失败。

## [Unreleased] — 2026-08-21 — prompt 通道补接线：两处让 A4 消融量不出东西的缺陷

### Fixed

- **9 处提示词仍在渲染那条已被裁定不再渲染的旧行。** 上一条的裁定是"提示词只渲染新段落"，
  理由是新旧两段在 9/51 份档案里互相矛盾；但裁定只落到了 6 个调用点。
  `sim/_action.py`（**主决策路径**）、`sim/_news.py`、`sim/_rag.py`、
  `cognition/realism.py`、`generative_city_sim.py` 里另外 9 处照旧拼旧标签，
  于是矛盾仍然每次都摆在提示词里，而 `SCENES["action"]` 在包内从没被调用过。
  最后两处是被检索范围漏掉的——第一遍只扫了 `gaworld/`，
  而根目录的历史顶层模块不在包里。**接线类改动的完备性判据只能是全仓库检索为空。**
- **`personality.prompt.*` 是个空转旋钮。** `render_midpoint / render_spread /
  strong_z / max_dims` 在配置里有值、有中文说明，而 `anchors.py` 的签名里写的是
  **同样数值的字面量默认参数**：行为是对的，配置是死的。日常使用完全看不见，
  对消融却是致命的——**消融就是拧旋钮**，拧不动的旋钮会让 A4 得出
  "怎么调都没差别"，而那是接线的结论、不是人格的结论。
  改法沿用既有架构约束（叶子模块不许读 CONFIG）：plugin 在 `agents.built` 时
  把旋钮拷到 agent 记录上，读侧从记录取默认值，显式关键字仍然优先。

### Added

- `personality.prompt.floor_z`（原先硬编码 0.25）提为配置项。它是 prompt 通道两种
  定位的分水岭：0.25 时锚句大多在重复段落已写过的维度，0.5 时只补段落没写的空档。
- 三组回归测试（58 → 71）：旧标签不许再出现在任何提示词模块里（含顶层模块）、
  每个旋钮改记录都要看得见变化且老记录能回落、关掉 prompt 通道只掉锚句段落留着。
  另加一条"死场景只许有 `social` 一个"——再有第二个场景变成死条目就会红。
- `scripts/big5_prompt_coverage.py`：零成本地量 prompt 通道还剩多少活干（重复／新信息拆分、模板多样性、token 成本），下面那组数字的生成器。

### Notes

- **零成本证据，直接改变了 D5 的问法**：51 人 × 5 个 prompt 场景共渲染 303 条锚句，
  其中 **272 条（89.8%）重复的是段落已经写过的维度**（生成器写 |z| ≥ 0.5，
  锚句门槛 |z| ≥ 0.25），只有 31 条（10.2%）是段落没有的信息；
  303 条只来自 **20 个模板句**，39 位居民拿到逐字相同的高尽责句。
  成本约 36 tokens／次决策提示词。
  「人格要不要进提示词」已被语料重写回答了（§12：r = 0.79，对照旧语料 r = 0.17）；
  剩下的 D5 是小得多的问题——**泛泛的场景强调，能不能在具体段落之上再推动结构化选择**。
  这个不能靠零成本推断，A4 配对探针约 1,400 次调用可测，判据已写在提案 §13.5。

## [Unreleased] — 2026-08-21 — 人格语料重写：把推断方向倒过来

### Added

- **`scripts/author_personality.py`：先采样 OCEAN，再据此写人物设定。** 原来的方向是
  从中文性格描述反推分数，在这份语料上必然失败——51 条「性格与情绪特征」中位数只有
  **20 字**（是标签不是描述），而五个人格级状态变量就写在同一份 profile 里、紧挨着它。
  两者是同一个作者对同一个人的两种写法，所以给散文打分只是把那五个数捞回来
  （开放性与 `mobility_intent` 相关 **0.90**）。把散文写长也没用：写手看到的还是同一个人。
  现在方向倒过来，独立性由采样器**在构造上**保证，而不是事后去测。
- **保留两处有文献依据的真实相关**（开放性↔`risk_preference`、外向性↔`voice_propensity`，
  r≈0.3）。把人格做成与状态变量严格正交反而不真实——问题从来不是"有相关"，
  是"是同一个东西"。C/A/N 与这五个变量之间没有可引用的既有结论，就独立采样，不编造配对。
  注入用残差化而非直接混合：n=51 下 r 的标准误约 0.14，直接混合换个种子实测会在
  0.16–0.44 之间跑，残差化之后**恰好**落在 0.30。
- **profile 新增 `**人格与行为倾向**` 字段**（解析为 `behavior_tendencies`），
  原「性格与情绪特征」一字未动——`dynamic.py` 的原型表与 `is_extrovert`、
  `finance.py` 的 wealth drive、`_heuristic_schedule` 的作息线索四处都在对它做关键词匹配，
  改写它等于同时改四个子系统的输入，效果就分不开了。
- **生成目标直接复用运行时锚句原文**（`anchors.py::ANCHORS`），并用主题标签
  （对新事物／做事方式／…）而非维度名。前者保证 profile 文本与运行时注入提示词的句子
  说的是同一个人，后者避免模型把标签原样写回去。

### Changed

- **`personality_line` 用新段落替代旧行，而不是并列。** 两段描述来源不同——旧行是当年与
  状态变量一起手写的，新段落来自独立采样——在 **9/51** 份里直接矛盾
  （28 号「外向、对不确定性耐受度较高」对上"客户没点头就翻来覆去地嚼，
  连晚饭吃什么都没心思定"；48 号「情绪波动与市场高度相关」对上"午盘跳水她订了份外卖，
  吃完午睡半小时"）。两者在提示词里是相邻两行，并列等于每次都把矛盾摆出来。
  **哪个该赢不是掷硬币**：采样分数驱动 rules 通道，新段落是与之一致的那份；
  若提示词显示旧标签，prompt 通道与 rules 通道就在描述两个不同的人，A3/A4 消融臂会失去意义。
  `agent["personality"]` 本身未动，四个关键词匹配的子系统行为完全不变。
- `data/agents_big5.csv` 的 `source` 从 `llm_median3` 变为 `sampled_authored`；
  `unstated` 与 `redundant` 两列清空。旧的 LLM 标定版留作对照臂。
- `scripts/calibrate_big5.py` 的用途从"主路径"变成"给外部导入的 agent 标定"
  以及"量标定器准不准的对照臂"。

### Notes

- **共线性闸门从 FAIL 变 PASS**：最差 adjusted R² **0.77 → 0.05**，五维全部 ok，
  `redundant` 列已清空。覆盖率从 N35/C26/O17/E13/A11 变成**五维全部 51/51**。
  人群 sd 从 0.45–0.74 回到 **1.00**，`style_fit_amplitude = 0.30` 仍然 PASS——
  「当前效应比闸门量到的弱一半」这个偏差随之消失。
- **旧语料备份在 `data/hangzhou_profiles_with_names.v1.md`。**
  这一步不可逆：**旧 run 与新 run 在人格维度上不可比**（情绪轨迹已因基线锚不可比，这是第二处）。
- 段落长度中位 148 字，范围 58–240，3 份超出 180 的上限。
- 四轮试水的一个通用教训：**字数不是提示词能控的**。明写「90–150 字，超过算不合格」+ 自动重试，
  五份重试全部仍超、两份更长；改成「写 4–5 句话」更长（最长 673 字）。
  有效的两招是**少要求它说点东西**（只写 |z| ≥ 0.5 的显著维度，平均 3.0 个）
  和**超长走压缩而不是重生成**（重采样一个写长的模型只会再得到一段长的）。

## [Unreleased] — 2026-08-21 — 大五人格：性格终于进了决策主循环

### Added

- **`gaworld/personality/`：OCEAN 五维作为一等特质。** 在这之前，`agent["personality"]`
  是一段中文散文，只出现在 prompt 里；**决策主循环 `choose_action()` 从头到尾没有读过它一次**
  ——二十多个权重项里有习惯、有地点偏好、有关系牵引，唯独没有人格。所以两个性格描述截然
  相反的居民，在同样的状态下做同样的选择。现在每位居民带五个 z 分，
  `choose_action` 多一个加性权重项 `trait_style_fit`，决策依据里显示为「性格倾向」。
- **三条通道，可以分别关。** `rules` 是确定性、零 token 的：动作选择、打断阈值、
  自发冲动基率、共处时的搭话概率、决策噪声、消费/储蓄倾向、情绪基准线。
  `prompt` 把人格写成第二人称的行为锚句，进日程、日内调整、目标、新闻四类提示词。
  `voice` 让同样的锚句只进日记。分成三条不是为了配置的丰富——是为了能回答
  「到底是决策变了还是文风变了」，全开成一个开关时这个问题无解。
- **锚句写行为，不写数字。** 「尽责性 0.62」在中文语料里没有稳定的行为先验，模型要么无视
  要么演成漫画人物。进 prompt 的是「你会提前把当天要做的事排好顺序，被打断后一定会补回来」。
  写不写按概率抽（`Φ((|z|-0.5)/0.4)`）而不是卡硬阈值，否则连续的人格会被切成高/中/低三类、
  还在阈值处留一个跳变；抽的结果按 agent 固定，同一位居民 Day 1 和 Day 300 的描述一致。
  每段最多两条：这些提示词本来就有十几段上下文，人格写多了会把当天的处境挤掉。
- **幅度是量出来的，不是拍出来的。** `scripts/big5_effect_ceiling.py` 拿**真实的**
  `choose_action` 做蒙特卡洛，报告给定幅度下人格与行为的相关能到多大，并按观测窗口
  自动选择验收档位（跨场合聚合会按构造抬高相关，用日级判据去卡聚合结果会误杀正常系统）。
  最初拟定的 ±0.6 被这道闸门否掉——5 天窗口下 E→社交 相关 0.53、200 次决策下 0.73，
  都超过实证上人格解释一到两成行为方差的量级。最终取 **0.30**。
- **`scripts/calibrate_big5.py`：一次性离线标定，运行时只读。** 从每位居民已有的
  「性格与情绪特征」段落反向打分。一次只问一个维度（一起问会产生光环效应——读起来正面的
  人物每一维都高），独立打三次取中位数，最后在 51 人内部做 z 标准化而不是让模型直接给
  z 分（模型不擅长产出校准过的标准分，擅长在两个描述好的锚点之间挑一个位置；
  标准化顺带消掉模型的常数刻度偏差）。材料里没提到的维度可以明确说「未提及」，
  不会被默认推到中点。结果冻结进 `data/agents_big5.csv`。
- **`scripts/big5_collinearity.py`：先证明这不是换个名字。** 居民本来就有
  `risk_preference` / `voice_propensity` 等五个人格级变量。把每个 OCEAN 维度对这五个做回归，
  R² > 0.5 就判定为冗余——那样的话每一个「人格效应」都是模型本来就能产出的效应。
- **人格在一次运行内不漂移。** 成年人 OCEAN 的实测变化量级是每**十年**0.1–0.2 个标准差，
  按天走的漂移项是把噪声包装成心理学。

### Fixed

- **情绪传染缺个人基准线（既有缺陷，`gaworld/sim/_cognition.py`）。** 原来的传染项
  只把人往邻居情绪的加权均值上拉，没有任何东西把他拉回自己——反复作用之后，
  连通的居民会收敛到同一个情绪值，个体差异被抹平。现在配一条回到个人基准线的回复项：
  基准线锚在**该居民自己的初始情绪**上（而不是一个人群常数，否则等于把一种抹平换成另一种），
  再由神经质下移、外向性上移；神经质越高回复越慢，于是一次冲击持续更久、情绪序列摊得更开
  ——这正是 N 可观测的行为签名。没有人格数据的 agent 仍走原来的纯传染路径。

- **两个改程测试实际上在测运气（测试隔离缺陷）。**
  `test_life_event_severity_impact::test_severe_event_beats_medium_commitment` 和
  `test_routine_change_commitment::test_high_commitment_activity_resists_weak_trigger`
  都断言"弱触发打不过承诺阻力，所以不该问 LLM"，但两者都没有钉住
  `ROUTINE_CHANGE_RANDOMNESS`。这个全局旋钮后来被调到了 0.85，
  在该设定下它把阻力压到约 0.40 倍、又给触发强度加上约 0.38 的无因由躁动
  ——足以让**任何**触发越过**任何**承诺等级。于是两个断言都掉到了下面那道
  `random.random()` 闸门上，成败取决于跑到它们时全局 RNG 恰好处在什么状态，
  也就是取决于前面跑了哪些测试。把旋钮钉成 0 之后，两者重新由
  `trigger <= resistance` 决定，也就是它们本来要断言的那件事。
  实测：修之前 400 个任意 RNG 起始状态里只有 49 个能通过，修之后 400/400。
  旋钮自身的行为本来就有 `test_routine_change_randomness` 覆盖，没有留下缺口。

- **标定把"不知道"变成了一个主张（`scripts/calibrate_big5.py`）。** 首次标定跑完后发现：
  人物设定里没写到的维度，模型按设计回了 `stated:false`，但转换步骤把这些人的中点分
  **当成数据一起做 z 标准化**，于是"我们不知道"变成了一个小的非零分
  （E 有 41/51 落在 −0.32，A 有 44/51 落在 −0.29，C 有 29/51 落在 −0.66）。
  这些值会进决策循环，还会越过锚句门槛——约三分之一的这类居民会被写上
  「你更喜欢小范围相处」之类的句子，而人物设定里从来没这么说过。
  现在改为锚在量表中点上（提示词里 4 分的定义就是「看不出来」，它是已知的中性点，
  不该从一份大半是弃权的样本里去估），尺度用有证据者偏离中点的均方根，
  于是未提及 ⇒ 恰好 0.0 ⇒ 无倾向、不写进提示词。原始打分都在审计文件里，
  所以重算零成本：`--from-audit output/traits/calibration_audit.csv`。
- **共线性闸门自己会低估重叠（`scripts/big5_collinearity.py`）。** 它原来在全部 51 人上
  算 R²，而未提及维度被钉在 0、没有方差可解释，会把重叠压低。改成只在有证据的子集上算、
  并报告调整后 R²（5 个自变量对 11–35 个样本，不调整的 R² 没法读）。
  差别不是四舍五入：开放性在全体上是 0.52，在有证据的 17 人上是 0.77。
### Changed

- `_classify_personality()` 与社交偶遇里的 `is_extrovert` 改为**特质优先、关键词兜底**。
  两套词表对「开放」的归类本来就冲突（关键词表把它算进 adventurous，而开放性同时喂 curious），
  所以是特质直接胜出而不是加权混合——同一个词有两套语义会让归类变得没法读。
  没有人格数据的 agent 走的还是原来的关键词路径。

### Notes

- **共线性闸门判定为 FAIL，按「照发 + 硬性标注」处理。** 在有证据的子集上，
  开放性（n=17，调整 R²=0.77，对 mobility_intent r=+0.90）、
  外向性（n=13，0.74，对 voice_propensity r=+0.76）、
  尽责性（n=26，0.53，对 platform_dependence r=−0.67）
  基本可由已有的人格级状态变量线性预测——因为那些变量本来就是从同一批
  `性格与情绪特征` 文字里写出来的。神经质（0.19）与宜人性（0.04）通过。
  处理方式是让标注跟着数据走而不是留在报告里：`--annotate` 把不合格维度写进
  `data/agents_big5.csv` 的 `redundant` 列，插件把它和 `unstated` 一起读进
  agent record、写进 `output/traits/agent_traits.csv` 和 recorder 载荷，
  **每次运行启动时都打印警告**。约束：O/C/E 的效应不得单独立论。
- **语料覆盖率**：人物设定实际描述到该维度的居民数为
  N 35/51、C 26/51、O 17/51、E 13/51、A 11/51。未描述的一律取 0
  （无倾向、不渲染锚句）。真正的修法是补写人物设定，不是改这个文件。

- **默认开启。** 向后兼容契约写成了测试：没有人格数据的 agent、或被关掉的通道，
  行为与加这个子系统之前**逐位一致**（`personality.enabled=false` 跑全量测试与基线同一组结果）。
- **`data/agents_big5.csv` 还没生成**——在跑 `scripts/calibrate_big5.py` 之前，
  51 位居民走的是人群先验采样，人格与他们的中文性格描述**对不上**。
- 设计与实施记录：`docs/proposals/2026-08-20-big-five-personality.md`。

## [Unreleased] — 2026-08-13 — 家庭系统：居民不再全员单身，生活开始发生在家里

### Added

- **`gaworld/family/`：户（household）作为一等实体。** 在这之前，51 个居民**事实上全是单身**：
  profile 文本里几乎没有婚育描述，`build_agent()` 没有任何家庭字段，而
  `social/network.py` 里的 `spouse` / `child` 角色只存在于每个 agent 各自 LLM 生成的
  场外名单里——它的确定性 fallback 只播种父母和老同学，**从不生成配偶或子女**，
  而且 A 的配偶和 B 毫无关系。现在婚姻状态按 `年龄段 × 性别` 的四类分布
  （未婚/已婚/离异/丧偶）采样，年龄和居住区匹配得上的 agent 在**仿真内**配成夫妻，
  配不上的补场外配偶；子女、同住长辈、不同住的父母、合租室友随之生成。
  八种户型（独居/合租/与父母同住/未婚同居/夫妻二人/核心家庭/单亲/三代同堂）是分配的
  **读数**而不是预设的配额——先定户型再填人正是 `population/network.py` 记录过的失效模式。
- **共居是分界线。** 同户的 in-sim agent 共享同一个 `locations["home"]` 节点。
  没有这一步，一对"夫妻"只是两个地址相同的陌生人；共享 home 之后，
  现有的 co-location 循环才会真的产生家庭互动。
- **家庭日程（`duties.py`）。** 接送幼儿园、陪写作业、照料同住老人、给父母打电话、
  和伴侣一起吃晚饭——按同住人口和工作日/周末生成，作为高承诺事项注入日程 prompt。
  `care_load()` 把照护负担折成 0..1 的标量供状态和财务层消费；有同住伴侣时负担乘 0.62，
  单亲全额承担。
- **家庭财务（`finance.py`），守恒。** 子女和长辈的开销按**收入**在同户挣钱的人之间分摊，
  走经济模块自己的支出路径（新增公开入口 `economy.finance.charge_external_expense()`），
  钱像普通消费一样进 firms 池；伴侣之间在一方现金见底时互相补窟窿，是纯转移。
  共享边界很讲究：夫妻**共享**子女和同住老人（重复计算会让学费翻倍），
  但**各自**赡养自己的父母。
- **家庭事件是共享的（`events.py`）。** 孩子发烧是**一个**事件，同一个 tick 同时落到父母
  两人身上——这正是按 agent 独立生成的 ghost 事件表达不了的东西，也是"家庭值得建模成户"
  的根本理由。事件投进现有人生事件队列，免费继承记忆写入、余波衰减和面板时间线；
  模板按家庭构成 gating，没有孩子的人抽不到"孩子发烧"。户内情绪传染作为**收敛项**
  `w × (对方 − 自己)` 施加，所以一个人人平静的家不会凭空漂移。
- **`CONFIG["family"]`**（`gaworld/settings/family.py`）：婚姻状态分布表、配对、生育、
  共居、责任、财务、事件七组旋钮，全部可覆盖，可做低生育率之类的政策实验。
  设计文档 `docs/FAMILY_DESIGN.md`；`tests/test_family.py`（47 项）+
  `tests/test_family_integration.py`（2 项，跑真实 `run_simulation`）。

### Changed

- `FamilyPlugin` 的钩子点是被排序约束逼出来的，不是随便挑的：建户必须在 `agents.built`
  （唯一能安全改写 `locations["home"]` 的时刻），但**亲属关系边只能在 `on_simulation_start`
  写入**——两者之间仿真会重置/重载 `agent["relationships"]` 再去问 LLM 要场外名单，
  写早了会被静默丢弃。日终结算挂 priority `-10`（经济插件是 0），并顺手算好**明天**的
  家庭责任，因为日程是在 `on_day_start` **之前**生成的。
- `social/network.py`：`ROLE_CONFIG` 增加 `roommate`（合租是杭州年轻租客的默认形态，
  室友是单身 agent 在家唯一会见到的人）；场外名单 prompt 现在会被告知已确定的家庭状况，
  并被要求不要另编配偶/子女。prompt 省 token，`ties.reconcile_ghost_kin()` 保证一致性——
  一个关系字典里有两个互相矛盾的配偶，比没有配偶更糟。
- `generative_city_sim.py` 三处 prompt 的角色资料各加一行「家庭状况」，
  daily-routine prompt 增加「今日家庭责任」段与相应约束，周末改写 prompt 增加家庭优先约束。

### Web 界面

- **配置 → 家庭与户。** 配置面板由 `gaworld/settings/config_docs.py` 的 `SECTIONS` 注册表
  生成，tooltip 从 settings 模块的注释里抽。**把片段加进 `defaults.py` 却不注册到这里，
  结果是整个子系统在浏览器里完全不存在**——从 Python 看却一切正常。七组旋钮现在都能在面板上调，
  操作者会去拧的那些配了中文说明；`in_sim_pair_share` 的说明里明写了它是建模取舍而非人口学事实，
  免得被当成实测值。新增的
  `test_every_config_fragment_has_a_panel_section` 是这条的回归闸：**任何**无人认领的顶层配置键
  都会让它失败。
- **主面板「家庭结构」卡片。** 概览（户数 / 仿真内夫妻 / 有子女 / 单身占比 + 户型分布条）
  加上跟随选中居民的详情（同住成员、不同住的家人、本轮养育与赡养支出）。
  数据走 `GET /api/family/overview`（`gaworld/apps/family_api.py`，沿用 `population_api`
  的委托模块惯例，`dashboard_server.py` 只加四行转发），读的是 recorder 落盘的
  `family.{summary,household,agent}.jsonl` 而**不在请求时重新推导**——
  配置在开跑之后改过的话，重新推导会显示一个 agent 并没有生活在其中的家。
  图表照例手写，这个目录没有构建步骤。
- **智能体工作台 → 社交·关系：家庭编辑面板。** 这里有个本质约束：家庭在每次运行开始时
  按 (名单, 配置, 种子) 重新推导，`on_simulation_start` 会覆盖 `relationships`——
  所以工作台里的编辑**不能是"改结果"**，那样的修改会在第二天早上凭空消失。面板写的是
  **覆盖项**（`gaworld/family/overrides.py` → `data/family_overrides.json`），
  分配器在分配过程中读取，因此户型、共居、日程、记账全都跟着走，和抽样出来的家庭走同一条路。
  可编辑：婚姻状态、伴侣（自动 / 无 / 指定一位仿真内居民 / 场外人物）、子女、同住长辈。
  **三态是承重的**：未勾选 = 抽样，勾选后空列表 = 固定为没有——合并两者会把"这对夫妻
  没有孩子"静默变成"给他们生几个"，前后端两侧都有测试锁着。
  指定仿真内配偶是对另一个人的声明：双向生效、共享住处、**绕过年龄差限制**（操作者是在
  故意覆盖人口学）、被抢走配偶的居民自动退回场外配偶、互相矛盾的指定按 id 解析并在面板上
  显式报出。修掉一个自己造的坑：指定场外配偶时 agent 仍留在贪心匹配池里，会被匹配给
  仿真内的另一个人，覆盖被静默忽略。
  面板读 `GET /api/family/preview`，它**故意重新推导**——和家庭卡片刚好相反，
  因为两者问的不是同一个问题：卡片问"这一轮跑的是什么家庭"，编辑器问"我保存之后下一轮会怎样"。
- **文档面板**列出 `FAMILY_DESIGN.md`。
- 测试：`tests/test_family_overrides.py`（25 项，覆盖层——重点不是"存下来了"而是
  **存下来的东西挺过了重新分配**）、`site/dashboard/studio-family.test.js`（10 项）、
  `tests/test_dashboard_family.py`（35 项）+ `site/dashboard/family-card.test.js`
  （6 项 `node --test`，把卡片切出来配桩 DOM 渲染，含一条 XSS 用例——居民名字来自可编辑的
  profile）+ 一条集成测试，真跑一轮再用 API 读回来，**把插件写出的形状和面板期待的形状对上**。
  两边各自的单元测试都绿、面板却空白，是这类改动最典型的失败方式。

### Known limits

- 没有独立的「家庭」console tab（户列表、关系图、事件时间线）；家庭卡片没有在真实浏览器里点过。
- 同性伴侣未建模；家庭结构在一次 run 内是静态的（没有结婚/离婚/生育真的改变户）；
  子女和长辈始终是 ghost，不进认知管线。
- `pairing.in_sim_pair_share`（默认 0.6）是**建模旋钮不是人口学事实**：
  从 1200 万人里抽 51 个人，他们互为夫妻的真实概率约等于 0。调到 0.0 可得人口学纯净的跑法。

## [Unreleased] — 2026-08-08 — Parallel worlds: change an event, watch the histories split

### Added

- **`gaworld/parallel/`: N-world counterfactuals.** `compare-event` could fork exactly two runs —
  one with an event, one without — and diff their last row. That is the degenerate case of the
  question worth asking: given the same city, the same residents and the same seed, *how far apart
  do histories drift when you change what happens to them, and when do they start to drift?* An
  experiment now holds up to eight worlds, each with its own event list, and a world may also carry
  a `config` patch — which is how you model a policy rather than an incident. `spec` validates the
  design and builds the per-world overrides, `runner` forks the worlds through a small pool (eight
  concurrent LLM-driven simulations starve a laptop and rate-limit a provider; a run that thrashes
  is worse than a run that queues), `analysis` turns the finished artifacts into a report.
- **Divergence over time, not only at the end.** The report reconstructs every world's per-step
  metric trajectory, measures its distance from the baseline at each step, and reports the step at
  which that distance first *stays* above a threshold — a single tick above the line is the LLM
  being non-deterministic, not two histories parting ways. It also measures the same distance per
  agent at the end, because a population mean averages away the residents an intervention actually
  landed on. Written out as `report.json`, `divergence_metrics.csv` and `divergence_summary.md`.
- **平行世界 / Parallel Worlds console tab** (`site/dashboard/worlds.html`). The left column designs
  the experiment — worlds, and the events inside them, with presets, copy-a-world, and a baseline
  picker; the right column reads one back: a branch diagram where distance from the trunk *is* the
  divergence, per-metric trajectories with the event days marked and a hover readout, the
  divergence curves with their split points, the end-state delta table, and a per-resident
  "who was changed" table. Worlds can be toggled in and out of every chart from the legend. Charts
  are hand-written SVG — this directory has no build step, and a CDN chart library would cost the
  dashboard its offline usability.
- **`GET/POST /api/parallel-worlds/*`** and `gaworld/apps/parallel_worlds_api.py`: overview,
  experiment listing, report, spec preview, and start/status/stop for the run job. One experiment
  runs at a time (a second start is a 409, not a silently oversubscribed machine), and progress is
  read per world out of its own `run.log` because the simulator writes the state history only at
  the very end of a run.
- **`parallel-worlds` CLI subcommand**, taking the same JSON spec the panel posts, so an experiment
  designed in the browser runs headless and vice versa.
- **Existing `compare-event` output is adapted, not migrated.** Every
  `output/comparisons/<ts>_<slug>/{without_event,with_event}` tree is presented as a two-world
  experiment built on the fly, so years of old counterfactuals open in the new visualiser with
  nothing rewritten on disk. Trees that never produced a state history are listed and flagged
  rather than hidden — `output/` accumulates the shells of runs that died, and opening on the
  newest one would show an empty page for no reason.

### Fixed

- **A forked world no longer wipes the operator's live diaries and life events.** `reset` clears
  `diary_output_dir` and the life-event directory too, and neither was redirected — at their
  defaults both point into the shared `output/` tree. The per-world overrides now isolate them
  along with memory, logs, state, network, environment and the vector DB. (`compare-event` has the
  same gap; it is untouched here because the benchmark reads its output layout.)

## [Unreleased] — 2026-08-02 — Analyse any recorded run, not just the current one

### Added

- **A run picker on 仿真结果分析.** `site/dashboard/analytics.html` read the live `output/` tree and
  nothing else, so every finished run's charts were gone the moment the next run started writing.
  The header now lists the current run, the per-run archives under `<visualization>/runs/` and the
  `compare-event` scenario runs — the same runs the replay page offers — and every section reloads
  against the picked one. The URL carries `?run=<id>`, so a past run's analysis is linkable.
- **`GET /api/analytics/runs`**, and a `?run=<id>` parameter on every `/api/analytics/*` section.
  Ids are validated against the served run list, so the parameter cannot reach outside the repo.
  Each entry reports which sections its artifacts can fill, and the page states up front which
  panels will be empty rather than leaving six "暂无数据" cards to be read as a broken page.
- **Exports name their run.** The picker sits in the page chrome the HTML report strips out, so the
  run label now rides in the JSON payload, the Markdown header and the report's scope banner.
- **仿真回放 reads out what the agents are doing and thinking, frame by frame.** The trace has always
  carried each agent's `perception` / `plan` / `action` / `outcome` / `reflection`, but the replay
  page drew only dots on a map — the reasoning behind a move was reachable only by opening the JSON.
  A panel beside the map now follows the playhead: one card per agent with its location, its action
  and its lead intent, and a 按计划 / 计划已改变 tag. Clicking a card (or an agent chip) expands the
  whole chain — 感知 → 想法 → 行动 → 结果 → 反思 — plus the route travelled, why the plan changed,
  and the state meters. The simulator writes plan and reflection as one template-filled line
  (`目标：…；顾虑：…`), so the panel splits them back into labelled rows and falls back to plain
  prose when a model ignored the template. `详情` hides the panel; the scroll position survives the
  frame-by-frame rebuild.

### Changed

- **The Analytics readers take the directory their artifacts live in** rather than the repo root
  with `output/` hard-coded inside each reader (`gaworld/apps/analytics.py`). Same data for the live
  run; a past run is the same code pointed at a different tree. An *archived* run is deliberately
  read as trace-only — its sibling `state/`, `economy/` and `memory/` dirs belong to whichever run
  overwrote them since, and showing those as its own would be a quiet lie.

---

## [Unreleased] — 2026-08-01 — External Systems: watch the world itself, and edit it

### Added

- **A console tab for the systems that are not agents.** `site/dashboard/external.html` — three
  panels, each pairing observation with editing: **货币系统** (cycle phase, inflation, unemployment,
  the firms/government/bank pools, the daily conservation audit, wealth distribution and Gini),
  **外部环境** (the generated natural/economic/political/technology timeline with severity and impact
  tags), and **对外服务** (the environment service, the distributed relay, the news source and LLM
  routing, with a live health probe). Until now each was readable only by opening a CSV under
  `output/` and editable only by hand-patching `dashboard_config.json`.
- **Config forms generated from the config itself.** The `economy` subtree alone has ~120 leaves; a
  hand-written form for each would be longer than the module and would rot the day a knob is added.
  The panel renders controls from the JSON shape and `external_systems_api._coerce_like` casts an
  incoming patch against the type already in the effective config, dropping unknown keys and
  reporting them. ~150 knobs are editable with no per-field backend code.
- **`gaworld/apps/external_systems_api.py`** — `GET /api/external-systems/{overview,health,
  interventions}` and `POST /api/external-systems/{config,interventions,interventions/cancel}`,
  delegated from `dashboard_server` in six lines, following the `population_api` precedent.
- **Mid-run monetary intervention that actually lands.** `output/economy/macro_state.json` is an
  *output* — the simulator rebuilds macro state from config at `on_simulation_start` and never reads
  it back, so editing it would look like it worked and change nothing. Instead the panel queues into
  `output/economy/interventions.json` and `gaworld.economy.finance` consumes it at each day boundary,
  applied *after* the cycle advance so an operator-set figure is the one that day uses. Sector
  injections move `initial_system_total` by the same amount, so the daily conservation audit reports
  a deliberate injection as an injection rather than as money leaking.
- **Plain-language hover help on ~126 elements.** Every metric, form field and config knob carries
  a `?` (or, for severity bars / type badges / the health column, a `cursor: help` region) that
  explains what the number *means* and what changing it does — "守恒漂移" says a non-zero value is a
  bug, not a setting; "失业率" says it does not actually make anyone lose their job. Reuses the
  existing `help.js` (`data-help` + dark popover, keyboard-focusable) rather than adding a second
  tooltip convention. Lookup is full-path-then-last-segment, so
  `economy.social_insurance.unemployment_rate` (a contribution rate) is not described as the macro
  unemployment indicator.
- **`site/dashboard/external.test.js`** (43 checks, driven from `tests/test_dashboard_external_systems.py`)
  — the Python tests cover the endpoints but cannot see the panel; a typo'd id or a crashed renderer
  would leave every backend test green and the page blank. It also pins that LLM-authored event text
  is escaped before it reaches `innerHTML`.

### Fixed

- **One non-finite float no longer blanks the whole panel.** The top tax bracket is `float("inf")`;
  `json.dumps` emits a bare `Infinity` token and the browser's `JSON.parse` rejects the *entire*
  body, so a healthy backend rendered "无法加载". The API now sends it as the string `"Infinity"`,
  which stays visible, stays editable, and round-trips losslessly.

---

## [Unreleased] — 2026-07-31 — Replay any recorded run, not just the latest

### Added

- **The replay page lists every run on disk.** `/site/simviz/index.html` used to read one hard-coded
  path, so it could only ever show the run that happened to be writing at that moment. A run picker
  now groups the live trace, the per-run archives and the traces that `compare-event` scenarios leave
  in their own output trees; picking one loads it and the URL carries `?run=<id>` so a run is
  shareable. Only the live run polls and opens on its newest frame — a recorded run is fetched once
  and opens at frame 1, ready to play.
- **`site/simviz/replay.test.js`** (`node --test`, driven from `tests/test_replay_runs.py`) — the
  Python tests can only prove the run list is *served*. Loading the right trace, not polling a
  recorded one, opening at its first frame and handing the renderer a bounded window all live in the
  page and are invisible to every backend test.
- **Each run keeps its own trace.** `SimulationVisualizer` copies every flush into
  `<visualization>/runs/<run_id>/simulation_trace.json` (at most once every 15s, plus on finalize),
  so the next run no longer buries the previous one and a long run killed halfway is still replayable
  up to its last flush. The live `simulation_trace.json` path is unchanged, so the dashboard, the
  analytics readers and the existing tooling keep reading what they always read.
- **`GET /api/replay/runs`** — served by the dashboard and, so the standalone `serve-viz` page is not
  crippled, by that server too. Listing reads only the head of each trace: `meta` is the first key
  written, and parsing a hundred multi-megabyte traces in full would stall the endpoint (104 runs
  list in ~0.08s here).

### Fixed

- **Long runs no longer re-slice their whole trace on every rendered frame.** The map renderer only
  draws trails for its last 96 frames, so the replay page now passes that window instead of
  `frames[0..current]` — replaying a run with tens of thousands of frames is O(1) per frame again.

---

## [Unreleased] — 2026-07-31 — Population Studio: readable output (Phase 4c)

All of this is panel-side. The gate, the synthesiser and the cohort kernel are unchanged.

### Added

- **Written files are openable from the page.** `POST /generate` now returns, per file, a label, a
  one-line description of what it is, its size, a repo-relative URL and an inline preview instead of
  a bare absolute path. The dashboard already serves `REPO_ROOT` statically, so the URL is directly
  clickable; files written outside the repo are still listed but carry no link, because a link that
  404s is worse than none. The absolute path stays visible — that is what gets pasted into
  `CONFIG["csv_path"]`, and it must not depend on the working directory.
- **A verdict a non-specialist can act on.** Step 5 now leads with a one-line conclusion and a
  can-use / cannot-use checklist derived from which layers passed, because the question a reader has
  is "what may I conclude from this run?", not "what is the z-score". Each layer states the question
  it answers, quotes its numbers in context (including where the tolerance came from), and L2
  additionally says *which side* it missed on — under- and over-propagation are opposite defects
  that look identical in a z-score. The full CLI-style output stays behind a disclosure.
- **Bilingual metric labels.** All metrics render as `压力 stress`, with the labels served from
  `GET /api/population/schema`. The panel previously kept its own Chinese map alongside raw English
  identifiers, so the same quantity appeared under two different names in different cards.
- **`site/dashboard/population-verdict.test.js`** — drives the step-5 renderer with a verbatim
  validator payload. The plain-language copy reads a dozen nested fields (`by_key`,
  `heterogeneity_retained_ratio`, `discriminating_keys`, …); renaming one in Python would leave every
  Python test green while the panel throws and the card renders blank.

### Fixed

- **A `NaN` in the verdict made the browser discard the entire response.** L2 reports a ratio of two
  Moran's I values that is `NaN` whenever the reference signal sits under the noise floor. Python's
  `json.dumps` writes a bare `NaN` token, which is not valid JSON — `JSON.parse` rejects the whole
  document, so one field blanked the whole result. `job_status()` now maps non-finite floats to
  `null` via `parse_constant`.

## [Unreleased] — 2026-07-29 — Population Studio dashboard panel (Phase 4b)

Group mode is now drivable from the dashboard. Follows the delegate-module plan from
`docs/GROUP_AGENT_DESIGN.md` §6.3: `dashboard_server.py` gains **12 lines** of prefix forwarding and
nothing else.

### Added

- **`gaworld/apps/population_api.py`** — the panel's backend. Endpoints under `/api/population/*`:
  `GET /schema`, `POST /preview`, `POST /generate`, `GET /jobs/{id}`, `POST /group-run`,
  `POST /validate`. Generation and simulation are async jobs (worker + poll), matching the existing
  `RUN_STATE` precedent rather than inventing a third convention — 500 residents takes seconds and
  an inline handler would hang the browser.
  - The **schema is served, not duplicated in JavaScript**. The nine state variables are already
    declared twice in this repo (`dashboard_server.py` and `studio.js`) and hand-synced; tests
    assert the endpoint stays equal to `population/schema.py` and `group/cohort.py` so the
    population knobs never become a third copy.
  - Path constants are read from `dashboard_server` at *call* time, because the existing dashboard
    tests monkeypatch `ds.STATE_CSV_PATH` and a module-level `from … import` would capture the real
    path first and write into the user's `data/` during a test run.
- **`site/dashboard/population.{html,js,css}`** — five steps: 群体定义 → 人口结构 → 状态分布 →
  群体模拟 → 验证与复核. Charts are hand-written SVG (age pyramid, Lorenz curve, degree histogram,
  and a state radar with a P25–P75 envelope — a bare mean polygon would misreport a cohort in
  exactly the way the tier is designed to avoid). No build step, no CDN dependency, so the dashboard
  stays usable offline.
  - The **validation verdict is in the panel**, not just the CLI. Seeing "25× cheaper" without
    seeing whether L2 passed invites treating group mode as a free lunch.
  - Coupling at 0 renders an explicit warning that the run only supports distribution- and
    policy-level questions.
- **`site/dashboard/population.test.js`** — node headless render smoke test (10 checks), following
  the existing `collaboration-core.test.js` convention. The Python tests cover the endpoints but
  cannot see the panel; a typo'd element id would leave them all green and the UI blank.
- **`tests/test_dashboard_population.py`** — 28 tests, including ones that start the real
  `ThreadingHTTPServer` and drive `DashboardHandler`. The existing dashboard tests call helpers
  directly and never route, so a broken if/elif branch would otherwise go unnoticed.
- Console tab registration in `site/console/console.js` + `index.html`, with a test asserting both
  were updated — adding one without the other yields a dead tab.

### Fixed

- `out_dir` was validated *inside* the background job, so an out-of-repo path returned 202 and only
  failed on poll. Now resolved and checked during the request (400 on rejection). The dashboard
  serves `REPO_ROOT` statically and takes this value from the browser, so an unchecked path is an
  arbitrary-write hole.

### Not verified

The panel has not been clicked through in a real browser — the dashboard server runs in the sandbox
while the browser tooling runs on the host, with no route between them. Rendering, element wiring
and schema-driven UI are covered headlessly; the interactive paths (generate → progress → validate)
need a local `python -m gaworld.apps.dashboard_server` and a human.

## [Unreleased] — 2026-07-29 — Cohort network coupling (Phase 4a) — **gate now passes all four layers**

Fixes the Phase 3 L2 failure at its root: the cohort tier now has a real network mechanism instead
of a uniform within-cohort shift.

### Added

- **`gaworld.group.cohort.NetworkCoupling`** — on top of the uniform cohort shift, each member gets
  a graph term equal to `weight × (mean of their neighbours' moves yesterday − the cohort's own mean
  of that quantity)`. Subtracting the cohort mean is the load-bearing part: the term is **mean-zero
  within the cohort**, so ownership splits cleanly — the cohort layer keeps the aggregate it
  predicted, the social graph gets the within-cohort structure. Adding a raw neighbour term instead
  would let the graph silently override the cohort's prediction, i.e. gamble the already-passing L1
  and L4 to fix L2. Costs **zero extra LLM calls**.
- `GroupRunConfig.network_coupling` (default **0.0**, reproducing the previous behaviour bit for
  bit) and `run_group_simulation(..., neighbours=...)`. A positive coupling with no graph raises
  rather than silently degrading — it would otherwise look configured while doing nothing.
- `--network-coupling` on `python -m gaworld.group.validate`.

### Measured

N=100, 14 days, budget 20, 3 seeds. Worst L2 z-score by coupling strength:
0.0 → 3.87 (fail), 0.5 → 2.26 (fail), **0.7 → 0.88 (pass)**, 0.9 → 4.14 (fail, over-propagating).

At 0.7 **all four layers pass**, stable across three independent seed sets (z = 0.88 / 1.61 / 1.60),
and the previously-passing layers were not traded away — L4's ATE relative error *improved* from
3.8% to 2.0% and subgroup heterogeneity retention from 0.77 to 1.13.

0.7 is calibrated against this reference process (contagion weight 0.6) and is **not a universal
constant**; it needs re-calibrating against a real LLM-driven individual tier.

### Fixed — two methodology bugs in the gate itself

These matter more than the coupling term:

- **Single-seed verdicts were noise.** For one fixed configuration the L2 ratio ranged from 0.32 to
  2.66 across seeds, and `coupling=0.8` passed 1 of 5 seed sets. The first reading of "0.8 fixes L2"
  was a lucky draw. All four layers now aggregate across seeds (default 3). With averaging the
  coupling sweep becomes monotonic in |deviation| — the dose-response relationship was real all
  along and single-seed noise was hiding it.
- **L2's ratio band `[0.5, 2.0]` was exactly the arbitrary constant this module's own docstring
  criticises**, and at N=100 the ratio estimator's noise is comparable to the band width, so the
  verdict flipped with the seed set. L2 now uses the same baseline-relative logic as L1:
  `|group_I − reference_I| ≤ 2 × the reference tier's own cross-seed SD`. The tolerance widens
  exactly when the quantity is hard to measure. The ratio is still reported, as a readable
  diagnostic rather than the decision rule.

## [Unreleased] — 2026-07-29 — Group mode validation gate (Phase 3) — **L2 not passed (fixed in Phase 4a, above)**

The go/no-go gate from `docs/GROUP_AGENT_DESIGN.md` §5, and its verdict. Group mode is validated
for distribution-level and policy-effect questions and **structurally unusable for anything
network-mediated**. The `CONFIG["simulation_mode"]` switch stays unwired.

### Added

- **`gaworld/group/metrics.py`** — hand-rolled comparison metrics (no scipy): Wasserstein-1, KS,
  Moran's I, tail shares, first-passage timing, paired ATE, subgroup effect heterogeneity and sign
  agreement. Each is chosen for what its layer actually claims: L1 uses distributional distance
  because comparing means would pass an approximation that collapsed the distribution to a point at
  the right centre; L2 uses Moran's I rather than degree/clustering because those are properties of
  the *static* graph and identical in both tiers by construction.
- **`gaworld/group/validate.py`** — the L1–L4 gate. Thresholds are relative to a measured baseline
  (the reference tier run against *itself* across seeds) rather than absolute constants, because an
  absolute threshold on a quantity whose natural scale has not been measured is a guess wearing a
  number. The cohort delta is an **oracle** (the true within-cohort mean of what the reference
  process would do), so a failing layer indicts aggregation itself rather than prompt quality.
  `python -m gaworld.group.validate` exits 1 when a dividing line fails, so it can gate CI.
- **`tests/test_group_validate.py`** — 40 tests, mostly negative controls: each constructs a
  candidate broken in a known way and asserts the matching layer catches it. A gate that only ever
  passes is indistinguishable from no gate.

### Measured — the verdict

N=100, 14 days, materialisation budget 20:

| layer | verdict | key numbers |
|---|---|---|
| L1 distributional | pass | W1 = 0.021–0.030 across four variables, all inside 2× the reference's own cross-seed noise |
| **L2 network** | **fail** | reference Moran's I = +0.054…+0.104, group = **−0.017…−0.027**, ratio −0.26…−0.31 |
| L3 tails | pass | interdecile spread ratio 0.80–1.02; tail-share deviation < 0.10 |
| L4 causal response | pass | ATE −0.392 vs −0.407, same sign, 3.8% magnitude error; heterogeneity 77% retained, subgroup sign agreement 100% |

L2's failure is structural, not a tuning problem. Sweeping the materialisation budget:
0 → −0.56, 20 → −0.31, 50 → 0.41, 80 → 0.92, 100 → 0.84. L2 only passes once **>80% of the
population is materialised**, which is essentially full individual mode with the cohort layer's cost
advantage gone. The cause is direct: a cohort delta is a *uniform shift within the cohort*, and the
cohort partition is not the social graph, so neighbour-mediated co-movement is inexpressible at the
group tier — the group tier even produces slight negative graph autocorrelation.

### Fixed

- The gate's reference process used mean-reversion toward the neighbourhood level
  (`peer_mean − own_value`) as its "social influence". That makes neighbouring *changes*
  anti-correlated, pinning Moran's I near zero, so L2 was dividing two near-zero numbers and
  reporting ratios like −75.91 — a confident-looking figure made entirely of noise. Replaced with
  contagion on changes (today's move is partly the mean of neighbours' moves yesterday), which is
  what real social influence does and gives L2 a signal to detect.
- Added an `inconclusive` layer status plus a Moran's I noise floor. An inconclusive dividing-line
  layer does **not** count as a pass: "the approximation broke this" and "this experiment cannot
  tell" are different findings, and collapsing them is how a validation suite starts producing
  confident nonsense.

## [Unreleased] — 2026-07-29 — Group agent cohort tier (Phase 2)

The coarse simulation tier. **`generative_city_sim.py` is untouched**: group mode is a parallel
driver, not a modification of the tick loop, so individual runs are bit-identical by construction.
The `CONFIG["simulation_mode"]` switch is deliberately *not* wired yet — putting an unvalidated
approximation on the default path before the Phase 3 L0/L2/L4 gate would be backwards. Suite
failure set identical to `HEAD`.

### Added

- **`gaworld/group/`** — cohort ("group agent") simulation. 58 tests, all LLM calls mocked.
  - `cohort.py` — a cohort carries both `centroid` **and** `dispersion`. Keeping only the mean is
    the representative-agent error Kirman (1992) describes, so cohort prompts report spread
    ("约34%低于0.4") rather than a bare average, and a cohort delta is applied as a *common shift*
    to every member — which moves the group mean while leaving within-group spread intact.
    Partition defaults to `(age band × industry × hukou)`, giving ~38 cohorts for 500 residents;
    sub-minimum cells are merged into their nearest neighbour rather than dropped.
  - `cohort_day.py` — one LLM call per cohort per day, structurally the same shape as
    `simulate_agent_day`. Prompt explicitly frames the group as heterogeneous and asks for a
    `divergence` field naming the sub-group whose day differed; `share_affected` scales the
    per-person effect down to a group-mean shift. Uses all nine state variables, unlike the
    individual fast-forward's seven — freezing `voice_propensity` would leave the tier unable to
    represent the polarisation it exists to study.
  - `materialize.py` — per-day selection of individuals to run at full fidelity: focal (named by
    the researcher, never dropped), event, tail (diagonal-Mahalanobis distance in the cohort's own
    dispersion metric, so "far from the mean" is measured relative to how spread out the group
    already is), and a stratified **audit** sample held out to measure error rather than reduce it.
  - `driver.py` — the day loop, plus a cost accounting that reports measured group calls against
    the full-individual counterfactual.
  - `plugin.py` — `GroupPlugin`, observational: publishes cohort structure and daily drift to the
    recorder without altering agent behaviour, so it is safe to enable inside an individual run.
  - `__main__.py` — `python -m gaworld.group --size 500 --days 7 --no-llm`.

### Measured

500 residents × 30 days, mock LLM, calls counted (full-individual baseline 500 × 30 × 198 =
2,970,000):

| materialisation budget | cohort calls | individual calls | total | vs full-individual |
|---|---|---|---|---|
| 0 | 1,140 | 0 | 1,140 | 2605× cheaper |
| 10 | 1,140 | 59,400 | 60,540 | 49× |
| 20 | 1,140 | 118,800 | 119,940 | 25× |
| 50 | 1,140 | 297,000 | 298,140 | 10× |

The design doc predicted ~25× at a budget of 20; measured 25×. The more useful finding is the
shape: the cohort tier is nearly free, so **total cost is set almost entirely by the
materialisation budget**, not by cohort granularity. This answers design-doc open question 4 and
redirects Phase 3 to measure "how much materialisation is needed to pass L2/L4" rather than "how
fine should cohorts be".

### Fixed

- The audit residual was reporting 0.9–1.3 on a run in which *nothing changed*. It compared the
  audit sample's state *level* against the cohort centroid, so it measured the sampling gap
  between a few members and their group mean — large, non-zero even for a null run, and unrelated
  to approximation quality. Redefined on changes (`mean(after − before) − predicted delta`), which
  is exactly zero for a null run and invariant to which members were sampled. Both properties are
  now tested.

## [Unreleased] — 2026-07-29 — Group agent design + parameterised population synthesis (Phase 0 & 1)

Groundwork for group-level simulation ("a 500-person town"). Design doc and phased plan:
`docs/GROUP_AGENT_DESIGN.md`. This lands Phase 0 (timeline cost fix) and Phase 1 (population
generator); the cohort kernel and the dashboard panel are still to come.

No regressions, verified the reliable way: an otherwise-identical copy of the working tree with
only these changes reverted produces a **byte-identical failure set** (12 pre-existing failures —
2 in `test_daily_routine_context.py`, 10 across memory/pipeline/routine/skills). Comparing against
a `git archive HEAD` copy is *not* reliable here: it omits uncommitted modules such as
`gaworld/env`, so the suite fails collection and silently reports zero failures. Test outcomes here
also depend on `.env` and on whether a simulation is running concurrently, so both sides of any
comparison must share them.

### Added

- **`gaworld/population/`** — parameterised synthetic-population generator. Turns panel-level
  knobs (size, age pyramid, employment rate, income Gini, household structure, social-graph
  shape) into a state CSV and profile Markdown in exactly the formats `build_agent` already
  reads, so **no simulator code changes are needed to run a generated town**. Verified
  end-to-end: 500/500 generated agents load through `build_agent` with valid map locations.
  - `schema.py` — the single definition of the population contract (`PopulationSpec`,
    `normalize_spec`, 5 presets). `check_feasibility` is a pure-maths precheck the panel can run
    on every keystroke: it catches contradictory knob combinations *before* generating anyone
    (unreachable median age, two-sided household-size bounds, labour force over 100%, multigen
    households exceeding the elder supply) and reports which knob to move.
  - `synth.py` — IPF fit of an `age × sex × education × employment × industry` table onto the
    requested marginals, with structural zeros for impossible cells. Uses a joint
    `(age, employment)` marginal so the working-age employment rate cannot be satisfied by
    employing pensioners, largest-remainder integerisation so marginals land exactly rather than
    within ±√N, and a rank-transform for income so the requested median and Gini hold while
    income still correlates with education, industry and age. Every draw comes from a named
    seed sub-stream, so nudging the network sliders does not re-roll everyone's age.
  - `network.py` — households (child-first, so the age pyramid cannot starve family formation),
    power-law workplaces, and a homophily × geography social graph with Watts–Strogatz rewiring.
    Ties are emitted in the existing `ensure_relationship_schema` shape and passed through
    `enforce_dunbar`. Small-worldness is reported relative to a matched random graph rather than
    as absolute thresholds.
  - `report.py` — hard validation gate (underage workers, out-of-range states, unparseable
    residences, household coverage) plus a target-vs-achieved report for every knob and the
    review charts (age pyramid, Lorenz curve, degree distribution, state distributions).
  - `writer.py` / `generate.py` / `__main__.py` — serialisation (BOM-carrying CSV,
    `parse_profile`-compatible Markdown, reproducibility manifest) and a CLI:
    `python -m gaworld.population --size 500 --preset cn_county_town --out data/town`.
    `--check` previews a spec without writing.
- **`CONFIG["time_grid_snap"]`** (default **off**) — aligns every agent's daily schedule onto the
  `time_step_minutes` grid via `snap_schedule_to_grid` (`gaworld/sim/_utils.py`). Setting
  `time_step_minutes` alone does **not** bound the tick count: `build_master_timeline` unions the
  grid with every agent's LLM-authored `HH:MM` times, which have no alignment logic, so tick count
  — and therefore total LLM cost — grows super-linearly with the agent count. Snapping pins it at
  `1440 / step` regardless of population size. Off by default because it changes intra-day timing;
  existing runs stay bit-comparable until opted in.
- **`tests/test_time_grid_snap.py`** (20 tests) — helper semantics (midpoint rounding, late-time
  clamping instead of midnight wraparound, idempotence) plus the acceptance property: with
  snapping, tick count is constant at N=5/20/50/100; without it, it grows with the population.
- **`tests/test_population.py`** (52 tests) — marginal accuracy against every knob, reproducibility
  (byte-identical output for the same seed; network knobs do not perturb demographics), structural
  validity, social-graph properties, and a round-trip test proving generated job titles classify
  correctly through the economy module's `JOB_INDUSTRY_MAP`.

### Fixed

- Generated job titles are now a checked contract with `gaworld/economy/finance.py`. The economy
  matches job text by substring in a fixed industry order, so plausible titles could land in the
  wrong industry — "跨境电商运营" matched `运营` under *service* before `电商` under *trade*, and
  "菜市场摊主" matched nothing at all. Nothing crashed; the agents just silently got the wrong macro
  conditions and wage band. Titles were reworded and a test now pins the round trip.

## [Unreleased] — 2026-07-11 — Microkernel plugin architecture (K1 + K2-lite)

Society-centric microkernel inspired by Agent-Kernel (arXiv:2512.01610). Design doc: `docs/proposals/2026-07-11-microkernel-plugin-architecture.md`; author guide: `docs/PLUGIN_AUTHORING.md`. Behavior-preserving: full suite 551 passed / 6 pre-existing failures, identical to baseline.

### Added

- **Long-horizon fast-forward mode** (`gaworld/sim/_fastforward.py`, `CONFIG["long_run"]`, `run --fast-forward`): compresses a whole day into a single per-agent "daily brief" (one LLM call/agent/day) instead of the intra-day tick megaloop, so 60/600-day horizons stay tractable — a "快进 + 近似" effect. The digest authors a short brief plus clamped approximate deltas (state, goal progress, a memory line, tomorrow's intentions, social signals); the main loop applies them so state / goals / relationships still evolve, and the day's log is a `Day N 简报` block rather than a per-tick trace. Day-boundary hooks (growth / interests / economy) still fire; diaries persist via the deterministic fallback (no extra LLM call). Off by default; `--fast-forward` pairs with a large `--sim-days`. A `long_run.randomness` (0–1) knob scales fast-forward volatility: per-agent-per-day burst events (marked `⚡`) at chance `≈0.3×r` plus zero-mean state jitter of amplitude `∝r` (amplified on burst days); `0` = fully deterministic. Enable + tune from the dashboard toolbar («Long-run Fast-forward» checkbox + «Randomness» slider), persisted to `dashboard_config.json`. Tests: `tests/test_fast_forward.py` (unit + randomness + a 3-day e2e proving the tick loop is bypassed).
- Goal-driven daily life: three-tier goal hierarchy (life / long-term / short-term) per agent, bootstrapped from profiles by LLM with heuristic fallback and persisted to `output/memory/agent_N_goals.json`. Goals drive daily intentions and routine prompts, real `goal_relevance` in episode salience, diary/interview context; day-end progress piggybacks on consolidation, weekly + severe-life-event reviews evolve the hierarchy (`GoalsPlugin`, `CONFIG["goals"]`). Dashboard goals panel with JSON editing (`GET/POST /api/agents/{id}/goals`). Design doc: `docs/superpowers/specs/2026-07-18-long-term-goals-design.md`.

- **`gaworld/kernel/`** — six kernel services (<800 lines total): `Clock` (deterministic sim time, advanced only by the main loop), `EventBus` (observe/collect/filter hook semantics with priorities; drop-in HookBus superset that loads the same `CONFIG["extensions"]` hooks), `PluginRegistry` + `Plugin` base (assembly from `CONFIG["plugins"]` class paths and `gaworld.plugins` entry points, dependency-ordered setup/teardown, trust-boundary error containment), `Controller` (priority-ordered action validator chain + audited named interventions — skeleton until K4 routes actions through it), `Recorder` (unified JSONL event stream under `output/records/`, auto `_day`/`_time` stamping), `SimContext` (single runtime source of truth; `plugin_state()` and `agent_ext()` namespace helpers replace bare agent-dict keys for plugin state).
- **`generative_city_sim.py`** — two cognition dispatch points inside the step loop, no-ops with zero subscribers: `perception.compose` (collect → snippets merged into the step env context) and `action.selected` (filter over the chosen action). Kernel bootstrap replaces the HookBus instance; all 7 legacy extension phases fire unchanged.
- **`tests/test_kernel.py`** — 23 unit tests for the six services; **`tests/test_kernel_plugin_e2e.py`** — end-to-end proof that a plugin declared only in `CONFIG["plugins"]` is assembled, injects perception that reaches an LLM prompt, and filters selected actions (zero simulator source edits).
- **`docs/PLUGIN_AUTHORING.md`** — plugin author guide (lifecycle, hook semantics, event catalog, state ownership, controller usage).

### Changed

- **`generative_city_sim.py::run_simulation`** — hook dispatch now goes through `gaworld.kernel.EventBus`; `sim_ctx.clock` is advanced at day start and each timeline tick; plugin `setup_all`/`teardown_all` wrap the simulation lifecycle. `gaworld/hooks.py` (HookBus) remains for legacy callers.

### K2 — cognition pipeline (configurable agent step)

- **`gaworld/sim/pipeline.py`** (`StagePipeline`, `DEFAULT_AGENT_STEP_ORDER`) — the ~770-line inline per-agent step body in `run_simulation` is now 12 named stages: `prepare / perceive / interrupts / plan / adjust_activity / move / select_action / reflect / update_state / broadcast / memorize / record`. Stage bodies are verbatim moves (closures over the loop's locals); cross-stage data rides the step dict — hook-visible keys keep their legacy names, working keys are underscore-prefixed, so pre/post-step hook consumers (economy, intervention plugin) are untouched.
- **Pipeline order is configuration**: `CONFIG["pipeline"]["agent_step"]` accepts builtin stage names, `"module:function"` import paths (custom stages), and `{"name", "call"}` dicts. Omitting a builtin name ablates that stage. Acceptance tests (`tests/test_pipeline_ablation.py`): removing `reflect` runs a full mock-LLM simulation with zero reflection LLM calls; a path-inserted custom stage runs once per agent-step with the step data bus and kernel clock visible.

### Fixed

- **Routine changes were silently disabled on the mainline path** (since commit `3f7edba`, ~5 months): the loop re-read `step_ctx["activity"]` unconditionally after `maybe_adjust_activity`, and the key was seeded with `scheduled_activity` at step start — so absent a pre-step hook override, the seeded value clobbered every LLM/dynamic activity adjustment. Fixed post-K2: a hook override wins only when it actually changed the seeded value. Red-green verified in `tests/test_routine_change_mainline.py`. **This changes simulation dynamics — agents now actually execute routine changes; re-baseline ongoing experiments.**

### K5 — runtime intervention API (migration complete)

- **`gaworld/kernel/interventions.py`** — every kernel ships three domain-free interventions, all audited: `set_agent_state` (immediate state write), `update_config` (dotted-path write into live CONFIG), and `remove_agent` (queued; the main loop applies removals at the day boundary and scrubs the removed ids from every remaining agent's `social_neighbors`). `LifeEventsPlugin` registers `inject_life_event`. The intervention API is the in-process programmatic surface — a dashboard HTTP bridge and `add_agent` (needs a seed-ingestion design) are tracked as follow-ups.
- `visualize_agent_state_changes` now plots each series against its own step range — state histories have unequal lengths once an agent is removed mid-run.
- Acceptance (`tests/test_interventions.py`): an agent removed via the API on day 1 no longer acts on day 2 of a real mock-LLM run.
- **This closes the K1–K5 microkernel migration** (design doc: `docs/proposals/2026-07-11-microkernel-plugin-architecture.md`).

### K4 — Controller validation gate wired into the move stage

- Structured moves now pass `Controller.validate` (an `ActionRequest("move", {to, activity})`) after location resolution. A denial keeps the agent where it is (move_agent falls back to the origin), is audited to `output/records/action.denied.jsonl`, and the reason surfaces in the agent's **next perception** as a "刚才的行动受阻：…" line — the structured feedback loop that catches hallucinated destinations.
- **`LocalPhysicalPlugin`** registers the first two validators: `location_exists` (**on by default** — `resolve_location` only yields map nodes, so it never fires in normal operation; it catches rogue rewrites from plugins/hooks, verified by a zero-denial control test) and `venue_open` (**off by default** — hard-blocking closed venues would change dynamics since the P0/P2 layers handle closures reactively; opt in via `CONFIG["controller"]["validators"]["venue_open"] = True`). An economy affordability validator is deferred until a concrete pre-move cost rule is defined.
- Acceptance (`tests/test_action_gate.py`): a config-declared plugin rewriting destinations to a nonexistent place gets denied, audited, and fed back into a subsequent perception prompt, end to end.

### K3i — dynamic behavior + spatial preferences migrated (K3 complete)

- **`gaworld/behavior/plugin.py`** (`DynamicBehaviorPlugin`) — interrupt/thought computation rides the new **`interrupts.compose`** filter. The engines return `{}` for "no change" (never `None`), so `None` flowing out of the filter means no producer ran — the interrupts stage then falls back to the legacy spontaneity path, exactly matching the old `dynamic_behavior.enabled` if/else. Third-party interrupt producers can pre-empt at higher priority. The `dynamic_result` *application* (activity change, mood delta, schedule insertion, P3 replanning) deliberately stays in the adjust_activity stage as the generic contract between interrupt producers and the pipeline; after application the stage emits the new **`interrupt.applied`** observe event.
- **`gaworld/world/plugin.py`** (`SpatialPreferencesPlugin`) — the P4 location-aversion layer: stateful load on `agents.built`, recency decay on `on_day_start`, aversion-aware redirection on the new **`location.resolve`** filter (move stage), anomaly-experience recording on `interrupt.applied` (with the pre-migration replan-gate nesting preserved as a documented parity quirk).
- With this, **all eight built-in subsystems ride the plugin surface**; `run_simulation` retains only the pipeline scaffolding, the legacy spontaneity fallback, and generic contract application.

### K3h — real-work task system migrated to a plugin

- **`gaworld/work/plugin.py`** (`RealWorkPlugin`) — owns the `RealWorkRuntime` lifecycle: create/start on `on_simulation_start`, job-market day tick on `on_day_start`, and dispatch/absorption on the new **`action.outcome`** filter event (fires in the select_action stage after the outcome line is built). Disabled runs store a `None` runtime and every hook no-ops, as before. Small improvement over the inline code: `teardown` now actually stops the worker pool (it previously leaked past simulation end).

### K3g — local physical perception migrated to a plugin

- **`gaworld/world/plugin.py`** (`LocalPhysicalPlugin`) — the P0 physical-perception layer rides the plugin surface: per-tick map refresh (sim time + occupancy) on `on_time_tick`, and the per-agent snapshot on `perception.compose` at priority 30 (stores `agent["_local_physical"]` for the interrupt engine and contributes the "身边的物理环境：…" line ahead of the life-event/intervention contributions — text order preserved exactly). `env_system` joins `city_map` in `sim_ctx.extras`. The spatial-preference layer (P4) deliberately stays inline: it is entangled with dynamic-behavior interrupt results and migrates together with that plugin.

### K3f — economy formalized as a plugin

- **`gaworld/economy/plugin.py`** (`EconomyPlugin`) — the six `gaworld.economy.finance` lifecycle handlers move from `CONFIG["extensions"]["hooks"]` declarations (`gaworld/settings/integrations.py`, now an empty user-extension map) to first-class builtin plugin assembly. Same handlers, same events, same self-gating and `extension_state["economy_module"]` runtime; ordering parity preserved (intervention post-step and interests day-end priorities still run first). The `test_extension_hooks_resolve` guard was re-expressed for the new wiring and now also verifies every builtin plugin sets up cleanly.

### K3e — life events migrated to a plugin (first event *producer*)

- **`gaworld/events/plugin.py`** (`LifeEventsPlugin`) — the life-event queue and its five consumers now ride dispatch points: ghost injection on `on_day_start` (human_realism-gated, same 0.18 dice), tick drain + env-timeline mirror on `on_time_tick` (priority 10), per-agent contribution/recording/`step["life_events"]` on the new **`env.events.compose`** collect event, the "人生事件：…" context line on `perception.compose` (priority 20), state deltas on the new **`state.effects`** observe event (emitted in the update_state stage before social influence), and the visualizer frame merge on the new **`env.events.tick`** collect event. Five inline sites and four helper functions removed from `run_simulation`.
- Behavior note: the perception context line now renders after the local-physical snippet instead of before it (same reordering class as the K3a intervention note).

### K3d — interest/skill-growth lifecycle migrated to a plugin

- **`gaworld/interests_plugin.py`** (`InterestsPlugin`) — owns the growth-profile lifecycle: bootstrap on `agents.built` (disabled runs still seed `{}` for schema parity), per-episode progress on the new **`episode.compose`** observe event (the memorize stage pre-sets empty `growth_matches`/`growth_progress` defaults, so the episode schema survives without the plugin), and day-end decay/evolution/🌱 line on `on_day_end` at priority 10 (ahead of the economy's config-registered settlement, matching the old inline order). Three inline blocks removed from `run_simulation`.
- Interim coupling documented in the plugin docstring: the profile stays at `agent["growth_profile"]` because two read-side consumers are still inline (schedule-prompt context via `format_growth_context`, location/action matching via `match_growth_items`); the key moves to `agent["ext"]["interests"]` when those migrate. Wiring pinned by `tests/test_interests_plugin.py`.

### K3c — Skill library migrated to a plugin

- **`gaworld/skills/plugin.py`** (`SkillsPlugin`) — skill injection moved from a hard-wired call inside `_cognition.perception` to the new `perception.sections` collect event (dispatched in the perceive stage; contributions render at the exact prompt position the old suffix occupied, so prompt structure is unchanged). Skill distillation moved from `memory/lifecycle.py` to the new `memory.consolidate` observe event emitted per agent at the day boundary, honoring the same `CONFIG["memory"]["skill_consolidation"]` cadence. `perception()` gained an `extra_sections` parameter; `_agent_skill_block` is gone and `gaworld/sim/_cognition.py` no longer imports the skills domain. Wiring pinned by `tests/test_skills_plugin.py` (inject / suppress / cadence).

### K3a — intervention subsystem migrated to a plugin

- **`gaworld/policy/plugin.py`** (`InterventionPlugin`) + **`gaworld/plugins/__init__.py`** (`builtin_plugins()`, the one domain-side aggregation point). The inline feed/metrics/init code is removed from `run_simulation`; the plugin rides `agents.built` (new pre-snapshot observe event), `perception.compose`, and `on_agent_post_step`. Metric state keys are still seeded when the feature is disabled (schema parity). `tests/test_intervention_plugin.py` pins the wiring both ways.
- **Behavior changes (intervention-enabled runs only)**: the feed snippet now *appends* to the step env context instead of rebuilding it from `env_context` — the inline version silently dropped the life-event context whenever a feed existed (latent bug); snippet ordering moved after the local-physical line; per-step metrics update happens at `on_agent_post_step` (after the step log/visualizer snapshot instead of before), so those auxiliary artifacts show metrics one step stale. Simulation dynamics are otherwise unchanged; `intervention_metrics.csv` schema is identical.

## [Unreleased] — 2026-07-04 — Personal Growth v2 (learning dynamics + interest evolution)

Multi-disciplinary redesign of the interest/skill-growth system (design doc: `docs/proposals/2026-07-04-personal-growth-v2.md`). All new mechanics are pure rules — no extra LLM calls; the persisted `agent_N_growth.json` schema is unchanged and backward compatible.

### Added

- **`gaworld/interests.py`** — learning dynamics: power-law diminishing returns (gains shrink with mastery), streak momentum (unbroken practice compounds), and milestone events (入门/熟练/精通 threshold crossings surfaced in `episode["growth_progress"]["milestones"]`). New `growth_phase()` derives the Hidi & Renninger four-phase label (触发期/维持期/浮现期/成熟期) from level + practice volume; `format_growth_context` now shows it, so prompt self-image evolves with development.
- **`gaworld/interests.py::apply_daily_growth_decay`** — day-end forgetting tick: unpracticed items lose level after a grace period, retention rises with accumulated practice (consolidated skills barely decay), decay is phase-aware (triggered ×1.5, well-developed ×0.5), idle gaps break streaks.
- **`gaworld/interests.py::evolve_growth_profile`** — day-end interest-set turnover: stale triggered-phase items are retired (never below 1 item); new interests are adopted by social contagion from the day's social partners (bounded by `adopt_chance`, `max_new_per_day`, `max_items`; deterministic via injectable rng).
- **`generative_city_sim.py`** — day-end growth tick wired into PHASE 3c: gathers partner growth focus from the day's episodes, runs decay + evolution, persists when stateful, prints a 🌱 change line.
- **`gaworld/settings/behavior.py`** — `interests.decay` and `interests.evolution` config blocks (both enabled by default, individually switchable).
- **`tests/test_interest_growth_dynamics.py`** — 18 cases: diminishing returns, streak momentum, milestones, decay (grace/retention/floor/streak-break/disabled), phase boundaries, evolution (retire/keep-last/adopt/chance/dedupe/caps/disabled).

### Fixed

- **`gaworld/sim/_summary.py::_growth_diff`** — read the actual `GrowthProfile` schema (`items` / float `level` / `total_minutes`) instead of the never-existing `interests` / int level / `minutes`, so end-of-run growth diffs are no longer always empty.

### Docs

- **`README.md` / `README.zh-CN.md`** — feature bullet, `interests` config note, and an expanded **Interest And Skill Growth / 兴趣爱好与技能成长系统** section covering the v2 dynamics, bilingual.
- **`docs/TUTORIAL.v2.md`** — §5.5 expanded with the v2 mechanics and their config keys; config-table row updated.
- **`docs/FEATURES.md`** — feature-table row updated with the day-end mechanics and config pointers.
- **`docs/PROJECT_STRUCTURE.md`** — `gaworld/interests.py` entry now mentions decay and interest-set evolution.
- **`docs/proposals/2026-07-04-personal-growth-v2.md`** — the design document (four-perspective expert review, mechanism specs, non-goals, validation).

## [Unreleased] — 2026-07-04 — Agent Studio (single-agent builder/inspector)

A visual builder/inspector for a single agent, integrated into the local dashboard. Seven steps bound to GAWorld's real seed model — identity + the nine `[0,1]` state variables, skills, tiered memory, Dunbar social circles, behavior dials, and review/deploy — with read/write back to the state CSV and profile Markdown.

### Added

- **`site/dashboard/studio.html` / `studio.css` / `studio.js`** — the Agent Studio front-end: a 7-step wizard (Identity, State & Personality, Abilities & Skills, Memory, Social & Relationships, Behavior & Goals, Review & Deploy) with an editable state radar, dependency-free SVG visualizations, an optional LLM interview hook, and a create-new-agent flow. Reachable from the console toolbar (**Agent Studio ↗**) or directly at `/site/dashboard/studio.html`.
- **`gaworld/apps/dashboard_server.py`** — Studio backend endpoints: `GET /api/agents/{id}/state`, `GET /api/agents/{id}/detail` (aggregate state + profile + memory counts + finance + social + skills), `GET /api/skills`, `POST /api/agents/{id}/state` (write to the state CSV), `POST /api/agents` (create agent). State writes are mirrored into the profile Markdown's `**核心状态变量**` / `**研究增强变量初始化**` lines so the CSV and MD don't drift; creation reuses the imported-agent format and preserves the CSV BOM. Social/finance readers pull from `output/memory` and `output/economy` and degrade gracefully before a run.
- **`site/dashboard/index.html`** — console toolbar link to the Studio.
- **`tests/test_dashboard_studio.py`** — 8 unittest cases: state round-trip + profile sync, identity edit, `[0,1]` clamping, create-agent (CSV row + profile block + BOM preserved), and social-snapshot parsing.

### Docs

- **`README.md` / `README.zh-CN.md`** — feature bullet, structure note, and a new **Agent Studio** subsection (7 steps, write-back rules, API table), bilingual.
- **`docs/FEATURES.md`** — feature-table row with the entry URL.
- **`docs/TUTORIAL.v2.md`** — new §12.1 Agent Studio (steps × data sources, write-back rules, API, tests) plus TOC anchor.
- **`docs/PROJECT_STRUCTURE.md`** / **`AGENTS.md`** — `site/dashboard/` studio note and `site/` tree entry.

## [Unreleased] — 2026-05-22 — Robustness Audit (S4)

Static-analysis sweep over the post-S3 codebase. Confirmed that the LLM provider retry framework, worker-pool fault chain, and per-adapter LLM guards were already production-ready; identified and closed 5 surviving silent-failure spots.

### Fixed

- **`generative_city_sim.py` L155 + L4889**: `print("⚠️  ...")` warnings during ghost event injection and off-screen social roster bootstrap now go through `_LOG.warning(...)` so they show up in structured logs.
- **`generative_city_sim.py` L4727**: Invalid `RANDOM_SEED` config no longer silently runs unseeded — emits `_LOG.warning(...)` so the user knows reproducibility was lost.
- **`gaworld/memory/store.py` L99**: Log-cache warm-up `OSError` no longer silently swallowed; emits `_LOG.debug(...)` breadcrumb. Behaviour unchanged (still falls back to whatever lines were already ingested).
- **`gaworld/memory/store.py` L418**: Vector DB close errors during teardown no longer silently swallowed; emits `_LOG.debug(...)` breadcrumb. First logger in that module.

### Docs

- **`docs/PHASE4_AUDIT.md`** — written. Documents every `except Exception` (27), silent `except: pass` (13), and live HTTP call (9) in the post-S3 repo, explains why each is either correct or was fixed, and records *why* the phase-0 "fragile error handling" baseline overstated the problem.

## [Unreleased] — 2026-05-22 — Architecture Refactor (S3)

Module reorganisation, monolith decomposition, performance fix, and bilingual docs refresh.

### Added

- **`gaworld/<sub>/` package homes for 11 previously top-level modules.** Each legacy file is now a 16-line `sys.modules` aliasing shim — the legacy import path keeps working, but new code should use the canonical `gaworld.<sub>.<module>` path.

  | Legacy import path | New canonical path |
  | --- | --- |
  | `memory_store` | `gaworld.memory.store` |
  | `social_network` | `gaworld.social.network` |
  | `city_map_system` | `gaworld.world.city_map` |
  | `environment` | `gaworld.env.system` |
  | `economy_module` | `gaworld.economy.finance` |
  | `dynamic_behavior` | `gaworld.behavior.dynamic` |
  | `llm_providers` | `gaworld.llm.providers` |
  | `human_realism` | `gaworld.cognition.realism` |
  | `intervention_policy` | `gaworld.policy.intervention` |
  | `life_events` | `gaworld.events.life` |
  | `distributed_comm` | `gaworld.distributed.comm` |

  Aliasing uses `sys.modules[__name__] = _module` so the legacy and canonical names resolve to the *same* module object — module-level state, private attribute reassignment, and monkey-patching all propagate transparently.

- **`gaworld/sim/` — extracted sub-modules from the `generative_city_sim.py` monolith.** Pulled out as cohesive groups rather than line-count slices, with re-exports left at the original locations so importers keep working:
  - `_utils.py` (~300 lines) — pure helpers (time, dates, env-context cleanup, weekday/weekend logic, JSON markers, path utilities).
  - `agents_loader.py` (~180 lines) — profile parsing (`parse_profile`, payload coercion/normalisation, profile-block formatting).
  - `_schedule.py` (~450 lines) — schedule plumbing (`_parse_schedule`, `_heuristic_schedule`, `ensure_sleep_in_schedule`, `format_plan_text`, `_compact_text`, recall labels).
  - `_location.py` (~370 lines) — agent movement (`_infer_workplace`, `_infer_home`, `assign_agent_locations`, `_update_commute_memory`, `_update_transit_progress`, `move_agent`).
  - `_rag.py` (~60 lines) — external-RAG hint helpers (`_agent_has_external_rag`, `_external_rag_hint`).
  - `_cognition.py` (~130 lines) — `get_social_context`, `perception`, `social_influence`. Uses the module-attribute LLM dispatch pattern so test mocks propagate.
  - `_diary.py` (~230 lines) — long-term memory + daily diary (`_append_memory_record`, `daily_summary`, `generate_daily_diary`, `save_daily_diary`, `_top_day_episode_lines`, `_fallback_daily_diary`).
  - `_news.py` (~760 lines, 20 names) — external information acquisition: source plumbing (`fetch_social_page_profile_source`, `load_news_sources`, `load_news_cache`, `update_news_cache`), interest scoring (`_extract_interest_keywords`, `_score_news_relevance`, `choose_news_for_agent`, `_domain_from_url`, `_build_agent_preferred_sites`, `_choose_info_target`), acquisition pipelines (`info_seek_and_store`, `search_web_and_store`, `read_news_and_store`), search-engine plumbing (`web_search`, `_extract_google_results`, `_extract_baidu_results`, `_extract_bing_results`, `_extract_generic_results`, `_build_search_query`, `_estimate_curiosity`). Kept the legacy `re.findall(r"\\(...)\\)"` over-escape verbatim — looks like a bug in source, but per Surgical Changes we don't "fix" it during extraction.
  - `_prompt.py` (~280 lines, 5 names) — prompt-fragment builders that turn agent state into Chinese prompt sections: `_band_label` (3-tier scalar → label), `_state_brief_for_prompt` (emotion/stress/energy/hunger/fatigue/time-pressure/self-control/social-need summary), `_yesterday_recap_for_prompt` (top-k prior-day episodes), `_recent_life_events_for_prompt` (consumed life events in window), `_social_pulse_for_prompt` (top-weighted relationships with recent interaction).
  - `_schedule.py` extended (+170 lines, +8 names) — six normalisation helpers (`_jitter_schedule_times`, `normalize_schedule_to_base`, `_dedupe_schedule_items`, `_enforce_schedule_min_gap`, `_has_enough_schedule_anchors`, `normalize_flexible_schedule`) plus the JSON-block extractor / schedule-change parser pair (`_extract_json_block`, `_parse_schedule_change`). `normalize_flexible_schedule` now reads its six `DAILY_PLAN_*` knobs at *call time* via `CONFIG.get(...)` — module-load snapshots break under tests that replace `CONFIG[section]` wholesale (same lesson as the S3 Phase 3 `_bootstrap_agent_external_rag` perf-fix).
  - `_rag.py` extended (~180 lines, +5 names) — `_append_external_payload_to_agent`, `_heuristic_bootstrap_external_items`, `_parse_bootstrap_external_items`, `_llm_bootstrap_external_items`, `_summarize_bootstrap_web_item`. The `_bootstrap_agent_external_rag` orchestrator stays in gen_city_sim because tests do `patch.object(sim, "_llm_bootstrap_external_items", ...)` and the orchestrator's bare-name lookups must resolve in `sim`'s globals.
  - `_action.py` (new, ~100 lines, 3 names) — pure JSON parsers used by `choose_action` and friends: `_parse_action_space`, `_parse_location_bias`, `_parse_policy_effect`. The `choose_action` orchestrator itself is deferred — see `docs/RUN_SIMULATION_EXTRACTION_PLAN.md` for the dependency-graph reasoning.
  - `_utils.py` extended (+1 name) — `_sanitize_extra_text` lifted here as a prerequisite for the RAG bootstrap extraction (was a 4-line helper used 19 times in gen_city_sim).

  Net: `generative_city_sim.py` shrank from 7,032 → 5,753 lines after the news + prompt + schedule + RAG + action extractions (≈18% in five slices); total monolith decomposition since S3 began: ~3,000 lines lifted out (≈42%) without breaking the legacy import surface.

### Deferred (with plan)

- **`run_simulation` orchestrator (1,380 lines).** Not extracted in this round — dependency graph too tangled, and lifting it without first migrating the per-step helpers (`evoke_memory`, `_social_relationship_snapshot`, `_activity_matches_keywords`, `_build_recall_context_labels`) would silently break the `patch.object(sim, ...)` test rig. Instead: inserted phase-section banners inside the function body (PHASE 1 init, PHASE 2 social network, PHASE 3 day loop with 3a/3b/3c sub-phases) as a navigation aid for a future lift. Full prerequisites + ordering recorded in `docs/RUN_SIMULATION_EXTRACTION_PLAN.md`.

### Extraction discipline notes

- **Surgical Changes preserved verbatim where it counts.** Spotted two source-code quirks during the news extraction — `r"\\(...)\\)"` over-escaped regex and `"\\n".join(...)` (literal backslash-n instead of newline). Both look like upstream bugs, but per the project rule we restored them byte-for-byte with a comment, rather than "fixing while we're here". Behaviour-preserving refactors should never silently change behaviour.

### Fixed

- **External-RAG bootstrap was firing real network calls during the e2e smoke test.** `_bootstrap_agent_external_rag` was reading the module-load snapshot `EXTERNAL_RAG_CONFIG`, but test fixtures replace `CONFIG["external_rag"]` *wholesale* (a new dict) — so the snapshot kept pointing at the original, fully-enabled config and the disable never took effect. Switched to a runtime lookup `CONFIG.get("external_rag", {}).get("bootstrap", {})`. **Result:** `test_e2e_smoke` went from 9.59 s → 1.50 s (6.4× faster); full unit suite went from 11 s → 3.34 s (3.3× faster).

- **`gaworld/world/city_map.py` path resolution after relocation.** `PROJECT_ROOT = Path(__file__).resolve().parent` evaluated to `gaworld/world/` instead of the repo root once the file moved out of the project root, breaking 15 city-map tests with `IndexError`. Corrected to `Path(__file__).resolve().parents[2]` with a comment explaining the depth.

- **`gaworld/llm/__init__.py` had a reverse-pointing import** (`from llm_providers import …`) that became a circular import the moment the root `llm_providers.py` was turned into a shim importing back into `gaworld.llm`. Rewrote `__init__.py` to import from the `.providers` sibling instead.

### Docs

- **`docs/REFACTOR_PLAN.md`** — full six-phase refactor plan with goal/risk analysis per phase.
- **`docs/REFACTOR_BASELINE.md`** — pre-refactor metrics baseline (337 pass / 4 fail / 11 s; ruff 544 errors; e2e_smoke 9.59 s with the bootstrap hot-spot).
- **`docs/PROJECT_STRUCTURE.md`** — rewritten to reflect the 13 `gaworld/` sub-packages, the 11 shim mapping table, the `gaworld/sim/` sub-modules, the path-resolution gotcha, and the post-S3 test baseline.
- **`README.md` / `README.zh-CN.md` — Project Structure sections rewritten** to list canonical `gaworld.<sub>.<module>` paths and explain the legacy-shim compatibility story.

### Internal patterns established

- **`sys.modules`-aliasing shim** as the standard pattern for legacy import paths — preserves module-level state, monkey-patching, and private attribute access; the alternative (`from X import *`) silently loses all of these.
- **Module-attribute LLM dispatch** (`from gaworld.llm import providers as _llm_providers; _llm_providers.call_llm(...)`) instead of `from gaworld.llm.providers import call_llm`. The test mock installer reassigns the module attribute, which is invisible to `from`-bound names.
- **CONFIG runtime lookup, not module-load snapshot.** Test fixtures replace `CONFIG[section]` wholesale — module-level snapshots like `_THING_CONFIG = CONFIG["thing"]` capture a now-stale dict reference. Always read via `CONFIG.get("thing", {})...` at call sites.
- **Migration pre-check** — before relocating a file, grep for `__file__`, `PROJECT_ROOT`, `Path(...).parent`, and check for pre-existing placeholder `__init__.py` files (which may contain reverse-pointing imports that need to be flipped to siblings).

### Test status

339 pass / 2 pre-existing flaky failures, full suite 3.34 s.

## [Unreleased] — 2026-05-01 — Economy + Location + Dynamic Behavior

### Added

- **`gaworld/interests.py` — interest and skill-growth system**
  - Derives persistent per-agent `growth_profile` data from profile fields, with LLM JSON parsing, hash-based cache reuse, and heuristic fallback when the LLM is unavailable.
  - Tracks hobbies and planned skills with motivation, priority, level, weekly target minutes, preferred time blocks, activity templates, career relevance, sociality, total practice minutes, last practiced day, and streak counters.
  - New runtime artifacts: `output/memory/growth_profiles.json` and `output/memory/agent_<id>_growth.json`.
  - Daily schedule and daily routine prompts now include growth context so low-commitment personal time can become concrete hobby or skill-development activity.
  - Daily intentions can include `growth_focus`; episode records now include `growth_matches` and `growth_progress`.
  - Action choice gives matched hobby/skill actions additional weight while preserving high-commitment activity guardrails.
  - Real-work capability matching can incorporate planned growth skills/interests without changing the `AgentCapabilities` schema.
  - Added unit tests for profile derivation, fallback/cache, progress updates, daily-intention budget behavior, mock LLM coverage, and daily routine prompt integration.

- **`dynamic_behavior.py` — dynamic behavior system** (new module, ~550 lines)
  - **InterruptEngine**: priority queue of potential schedule interruptions. Each candidate is scored against the current activity's commitment level (0.95 for exams/surgery down to 0.05 for personal time). Personality-dependent threshold with stochastic acceptance gate.
  - **SpontaneityEngine**: mood-classified urge pools (happy/stressed/tired/bored/anxious/lonely), each with 4 context-aware activities. Time-of-day filtering (no shopping at 23:00), personality scaling (extroverts more social urges, introverts more solitary), duration estimation by activity type.
  - **Need-based interrupts**: hunger (with meal-time bonus), fatigue/energy recovery, time-pressure urgency. Ported and improved from the old `maybe_generate_transient_thought` inline logic.
  - **Inbox/social-message triggers**: detects unread messages and social pings via keyword matching, produces interrupt candidates weighted by social need.
  - **SocialChainResolver**: co-location detection (same node, excluding in-transit agents), relationship-closeness-based encounter probability, three interaction types — invitation (close friends, meal-time aware), brief chat (acquaintances), behaviour contagion (strangers doing interesting things).
  - **EnvironmentResponsePipeline**: event classification (weather/traffic/commercial/news/emergency → sub-types), personality-differentiated response modifiers (cautious +30% weather sensitivity, curious +40% commercial interest), severity-scaled priority.
  - **Event cascade chains**: knock-on effects (rain → taxi queues + slippery roads, storm → transit delays + delivery delays, congestion → possible lateness + mood drop, fire → road closures + building evacuation). Probability-gated secondary interrupts.
  - **Schedule insertion**: insert new activities into `(time, activity)` tuple schedules with resumable support — interrupted activities resume after the insertion's duration if there's room.
  - **`evaluate_step_dynamics()`**: single entry point running all six sub-engines per agent per time-step. Returns final activity, change reason, interrupt details, social encounters, cumulative mood delta, schedule insertion info, candidate count, and cascade events.
  - **`dynamic_transient_thought()`**: bridge function matching the old `maybe_generate_transient_thought` return format while using the new engines internally.
  - 55 unit tests covering commitment levels, interrupt evaluation, spontaneous urges, need-based interrupts, inbox triggers, co-location detection, social encounters, environment responses, cascades, schedule insertion, full pipeline, and bridge API.

- **`generative_city_sim.py`** — dynamic behavior integration
  - Main simulation loop now calls `dynamic_transient_thought()` (when `CONFIG["dynamic_behavior"]["enabled"]` is true) instead of the old `maybe_generate_transient_thought()`, with fallback to the legacy path.
  - If the dynamic system decides on an activity change but the LLM-based `maybe_adjust_activity()` doesn't, the dynamic system's decision is used as a fallback.
  - Mood deltas from the dynamic system are applied to agent state after each step.
  - Schedule insertions from the dynamic system are applied with resumable support.
  - Social encounters are logged at DEBUG level.

- **`config.py`** — new `dynamic_behavior` section with `enabled` flag.

- **`economy_module.py` — realistic personal finance simulation** (major refactor)
  - **Tax & social insurance**: China 7-bracket progressive income tax (3%–45%), monthly exemption 5,000 CNY with configurable special deductions. Social insurance: pension 8%, medical 2%, unemployment 0.5%, housing fund 8% (+ employer match), with base salary floor/cap.
  - **Engel-coefficient spending**: income-indexed consumption curve (food 48% at low income → 15% at high income). Eight categories weighted by income elasticity (necessities 0.5–0.6, luxuries 1.2–1.5). Dynamic savings rate (5%–40%).
  - **Multi-account system**: checking / savings / investment / housing fund. Three portfolio profiles (conservative/moderate/aggressive) based on risk preference. Monthly Gaussian investment returns (deposits ~2.5%, funds ~6%±8%, stocks ~8%±22%). Auto-save excess checking.
  - **Macro-economic cycles**: four-phase cycle (expansion → peak → contraction → trough, 60–180 days each) with income/expense/layoff/raise multipliers. Industry-specific conditions. Daily inflation accumulation.
  - **Shock events**: layoff (income cut 50–85%, recovery 30–90 days), raise/promotion, medical emergency (50–85% SI reimbursement), year-end bonus (13th-month salary).
  - New output files: per-agent ledger CSVs, wealth snapshots, `macro_state.json`.
  - 30 unit tests covering tax calculation, Engel allocation, investment returns, macro cycle transitions, shock events, and full lifecycle integration.

- **`city_map_system.py` — realistic location & transport system** (major refactor)
  - **Transport cost calculation**: per-mode fare structures (bus flat 2 CNY, metro distance-based, taxi base+per-km, car fuel+parking). Rush-hour detection (7:00–9:00, 17:00–19:00) with 1.45× time multiplier and 1.3× taxi surcharge.
  - **Weather-aware mode selection**: weather adjustment weights penalise open-air modes (walk/bike/e-bike) in rain/snow/hot/cold, auto-upgrade to sheltered alternatives (bus/metro/taxi).
  - **Category-based spatial queries**: `nearby_nodes()`, `nodes_by_category()`, `nearest_by_category()`, `resolve_best_location()` replace hardcoded location name lists. Works with any city map.
  - **Activity & job category mapping**: `activity_to_categories()` and `job_to_workplace_categories()` map Chinese/English keywords to location categories (education, medical, commerce, leisure, transit, etc.).
  - **Area price levels**: per-category price multipliers (commerce 1.35×, industry 0.80×, education 0.85×) for spending adjustment.
  - 40 unit tests covering transport cost, rush hour, weather effects, spatial queries, category matching, and travel plan integration.

- **`generative_city_sim.py` — location decision refactor**
  - `_infer_workplace()` and `_infer_home()` now use category-based spatial matching instead of hardcoded location name lists.
  - `resolve_location()` uses `activity_to_categories()` + `resolve_best_location()` for generic map-independent activity resolution.
  - `move_agent()` passes `time_str` and `weather` to `travel_plan()`, returns `cost` and `rush_hour` in travel dict.
  - **Commute memory**: agents track `frequent_places`, `preferred_modes`, and `commute_route` stats; habitual bonus feeds back into location decisions.
  - `daily_travel_cost` accumulator resets at day start.

- **`economy_module.py`** — transport expense now uses real fare from `travel_plan()` when available, falling back to budget-based estimate.

- **`config.py`** — expanded `economy` section with `tax`, `social_insurance`, `spending`, `investment`, `macro`, and `shocks` sub-configurations.

---

## [Previous] — 2026-04 — S1 + S2 refactor

### Added

- **Project tooling**
  - `pyproject.toml` with ruff / black / mypy / pytest / coverage configuration.
  - `.github/workflows/ci.yml` — lint + format check + mypy (advisory) + pytest with coverage on Python 3.11 and 3.12.
  - `requirements-dev.txt` for development extras (`pytest`, `pytest-cov`, `ruff`, `black`, `mypy`).
  - `.env.example` documenting required environment variables (LLM API keys, log level, config overrides).

- **`gaworld/` package** as the new home for cross-cutting concerns:
  - `gaworld.logging_setup` — central rotating logger with structured context (`agent_id`, `day`, `stage`, `provider`, `task`).
  - `gaworld.env_loader` — zero-dependency `.env` loader.
  - `gaworld.config` — typed `SimulationConfig` / `LLMConfig` / `PathsConfig` dataclasses with `from_legacy(CONFIG)` factory; pydantic-free.
  - `gaworld.core.agent` — `Agent` dataclass adapter that owns the legacy ``dict`` agent layout while exposing typed accessors (`a.id`, `a.state`, `a.need(...)`).
  - `gaworld.io.web_scrape` — extracted HTML / news content extraction (used to live inline in the main simulator).
  - `gaworld.llm` — re-exports the existing provider router; provides a stable import path for new code.

- **New tests**
  - `tests/test_gaworld_core_agent.py`
  - `tests/test_gaworld_config.py`
  - `tests/test_gaworld_io_web_scrape.py`

### Changed

- **`llm_providers.py`**
  - Replaced the private `requests.models.complexjson.loads(...)` API with stdlib `json.loads`.
  - Added bounded exponential-backoff retry around all three providers for transient errors (timeouts, connection errors, 408/425/429/5xx).
  - Every `call_llm` invocation is now logged with provider / task / agent / prompt size / latency / outcome under the `gaworld.llm` logger.

- **Bare `except Exception` clean-up** — collapsed silent broad catches to specific exception types in:
  - `dashboard_server.py` (HTTP 500 boundary still broad, but now `_LOG.exception` traces are emitted)
  - `distributed_comm.py`
  - `environment.py`
  - `extensibility.py` (third-party hook trust boundary, now logged)
  - `human_realism.py`
  - `generative_city_sim.py` (8 callsites)

- **`generative_city_sim.py`** now imports HTML helpers (`_strip_html`, `_extract_title`, `_normalize_text`, `_extract_meta_content`, `_extract_news_main_content`, `fetch_news_excerpt`, etc.) from `gaworld.io.web_scrape`. The legacy regex bodies were removed; the public names remain available as module-level aliases.

- **`requirements.txt`** — pinned with conservative `>= … , < …` ranges instead of unpinned `pandas / numpy / requests / matplotlib / networkx`.

### S3 (high-risk items, opt-in)

- **`gaworld.core.runner.parallel_map`** — opt-in concurrency primitive that preserves input order, falls back to a fully serial loop when ``max_workers <= 1``, and re-raises the first task exception. Used by:
  - the **daily routine generation loop** in ``generative_city_sim.run_simulation`` (one LLM call per agent per day; previously the largest serial LLM bottleneck). Behaviour is unchanged unless the user opts in.
- **CONFIG knob ``concurrency.day_routine_workers``** — defaults to ``1`` (serial). Setting it ``> 1`` (and ``concurrency.enabled = true``) parallelises the routine generation. The serial merge phase keeps SQLite + per-agent log writers single-writer.
- **MockLLM fixture** (``tests/fixtures/mock_llm.py``) — deterministic, thread-safe stand-in for ``call_llm``; covers the 20+ task names dispatched by the simulator. Patches both ``llm_providers.call_llm`` and the legacy module binding via ``install()``.
- **End-to-end smoke** (``tests/test_e2e_smoke.py``) — runs ``run_simulation()`` with ``sim_days=1``, two agents, mocked LLM, isolated tempdir, against the seeded fixture data. Asserts the routine + per-step LLM tasks were dispatched and that the per-agent log artefacts were produced. Skips cleanly when ``networkx``/``matplotlib`` are unavailable.
- **New tests** — ``tests/test_gaworld_core_runner.py`` (11), ``tests/test_mock_llm_fixture.py`` (7), ``tests/test_e2e_smoke.py`` (2). 20 new tests bring the total runnable suite from 55 to 74 + 1 skipped.

### S3 (safe items)

- **SQLite WAL** — `memory_store._vector_db_connect()` now applies `PRAGMA journal_mode=WAL` + `synchronous=NORMAL` + `temp_store=MEMORY`. Concurrent agent writes no longer block readers. Failure is logged at WARNING and falls back to default journaling.
- **HTTP guardrails** — new `gaworld.io.http_guard` provides:
  - `HostRateLimiter` (per-host minimum interval + jitter)
  - `UserAgentRotator` (round-robin over a configurable pool, with sensible defaults)
  - `FailureCache` (sliding-window cache keyed on URL × status, with separate TTLs for permanent (401/403/404/410/451), transient (408/425/429/5xx), and other statuses)
  - `GuardedSession` (combines all three on top of `requests.Session`)
- `gaworld.io.web_scrape.fetch_news_excerpt` is now wired through `get_default_session()` so all news fetching honours the guards automatically.
- **LLM cross-provider fallback** — `LLMRouter` resolves a chain (primary + `llm.routing.fallback`) and retries the next provider when the previous raises. Each provider attempt logs its `fallback_index` for postmortem analysis.
- **CI coverage floor** — `pytest --cov=gaworld --cov-fail-under=80`; mirrored as `[tool.coverage.report] fail_under = 80` in `pyproject.toml`.
- **New tests** — `tests/test_gaworld_io_http_guard.py` (10 tests) and `tests/test_gaworld_llm_fallback.py` (6 tests).

### Notes

- **Python ≥ 3.11** is now required (the existing `from datetime import UTC` import in `simulation_visualizer.py` already required it; the build metadata now declares it).
- The HTML extraction port silently fixes a pair of double-escape bugs in the original regex (`</\\1>` and `\\s+`); behaviour on real HTML pages is unchanged or improved.
- All 18 sandbox-runnable legacy tests continue to pass; coverage of new code is tracked by 19 new tests across the three `gaworld/` subpackages.
- The full migration plan (S3 — concurrency, S4 — research-grade observability) is documented in `GAWorld_改进建议.docx`.

### Migration tips for downstream code

```python
# Old:                                    # New (preferred):
from generative_city_sim import (         from gaworld.io.web_scrape import (
    _strip_html, _extract_title,              strip_html, extract_title,
    fetch_news_excerpt,                       fetch_news_excerpt,
)                                         )

# Old (legacy dict):                      # New (typed adapter, same dict under the hood):
agent["state"]["energy"]                  agent.state["energy"]
                                          agent.need("energy", default=0.5)

# Old:                                    # New (typed view of CONFIG):
from config import CONFIG                 from gaworld.config import load_simulation_config
sim_days = CONFIG["sim_days"]             cfg = load_simulation_config()
                                          sim_days = cfg.sim_days
```
