# GAWorld 测试用例设计

两套测试用例：

| 套件 | 目的 | 规模 | 运行 | 何时跑 |
|---|---|---|---|---|
| **A · 全功能详细测试** | 覆盖 [功能总览](FEATURES.md) 中的每一项功能，以及未列入总览的子系统（数字孪生、目标、居家环境等） | 全部 pytest（约 2,780 条）+ 第 2.19 节的手工 UI 验收 | `pytest --suite full`（等同 `pytest tests`） | 合并到 `main` 前、发版前、改动跨子系统时 |
| **B · 核心功能测试** | 验证仿真主干可用：配置 → LLM → 内核 → 一天仿真 → 产物 | 23 个用例 / 约 330 条 pytest，约 30 秒 | `pytest --suite core` | 每次提交前、改动核心模块后、CI 快速门 |

核心套件的清单在 [`tests/suites/core.txt`](../tests/suites/core.txt)，由 `tests/conftest.py` 的 `--suite` 选项读取。如果清单里某一条已经不存在（例如测试被改名），运行会直接报错，不会悄悄把它漏掉。

## 一、约定

**用例字段**

- **编号**：A 套件是 `A<域>-<序号>`（如 `A3-04`），B 套件是 `C-<序号>`。
- **步骤 / 输入**：怎么触发这个功能。自动化用例写的是测试构造的输入。
- **预期结果**：可以判定的断言，不写「运行正常」这类说法。
- **自动化**：对应的 pytest 文件或类（路径省略 `tests/`）。写 **手工** 的用例要在浏览器里验收，见 2.19。
- **级别**：P0 = 主干，坏了仿真跑不起来或产物错误；P1 = 主要功能；P2 = 边界、降级与体验。

**测试环境约束**（沿用 AGENTS.md）

- 一律 mock `call_llm`（`tests/fixtures/mock_llm.py`），不连真实模型，也不访问网络。
- `conftest.py` 会设置 `GAWORLD_IGNORE_LOCAL_CONFIG=1`，本机 `dashboard_config.json` 里的选择（城市、跨度等）不会影响测试。
- 标记为 `slow` 的用例（目前只有 `test_interview_end_to_end.py`）会起子进程，可以用 `-m "not slow"` 跳过。表中注明耗时的用例没有打标记，但单个文件就要十几秒以上。

---

## 二、套件 A · 全功能详细测试

### 2.1 CLI 与运行控制

| 编号 | 用例 | 步骤 / 输入 | 预期结果 | 自动化 | 级别 |
|---|---|---|---|---|---|
| A1-01 | `run --sim-days` 覆盖天数 | `run --sim-days 3` | `CONFIG["sim_days"]` 与 `SIM_DAYS` 都是 3，`run_simulation` 被调用一次 | `test_cli_run_sim_days.py` | P0 |
| A1-02 | 所有子命令都能解析 | run / reset / interview / rag-add / create-agent-from-social / serve-viz / dashboard | 每条 argv 都能解析，`command` 正确；`--time-unit week` 被拒绝 | `test_cli_commands.py::TestArgParser` | P0 |
| A1-03 | `reset` 清空有状态产物 | 执行 `reset` | memory / logs / state / environment 等目录被清空，向量库文件被删除，`sim_state` 写回 `last_day=0`、`agent_last_day={}` 和当前记忆 schema 版本 | `test_cli_commands.py::TestResetCommand` | P0 |
| A1-04 | 记忆 schema 闸门 | 磁盘上的记忆版本与代码版本不一致 | `run` 被拦截并提示先 reset；版本一致时放行 | `test_reset_gate_for_memory_model.py` | P0 |
| A1-05 | 单个智能体采访 CLI | `interview --agent-id 31 --question Q --questions-file f` | 两处来的问题按顺序合并（跳过空行）；一个问题都没有时报用法错误，不调用采访 | `test_cli_commands.py::TestInterviewCommand` | P1 |
| A1-06 | `rag-add` 注入外部知识 | `rag-add --agent-id 7 --text T --source s` | 以 `external_info` 类型写入向量库，并追加到该 agent 的记忆；文本为空时报 `ValueError`，什么都不写 | `test_cli_commands.py::TestRagAddCommand` | P1 |
| A1-07 | 按 agent 续跑 | 部分 agent 跑过，部分没跑过 | 从没跑过的 agent 从 Day 1 开始；混合时从最远的日期续跑；只记录本次参与的 agent；旧状态文件能迁移 | `test_resume_start_day.py` | P0 |
| A1-08 | 事件对照实验 | `compare-event` 读取状态 CSV；Ollama 连接被拒 | 能组出对比指标行；失败提示能提取出「连接被拒」 | `test_compare_event_metrics.py`、`test_compare_event_failure_hint.py` | P1 |
| A1-09 | 运行清单与报告 | 开始运行 → 结束 / 中途失败 | 开始时先写 partial 清单，成功后清理；API key 被脱敏；git 脏状态被标出；HTML 报告会转义配置里的恶意字符串 | `test_gaworld_run_manifest.py` | P0 |
| A1-10 | 定时运行 | Dashboard 设一个未来时间 | 状态显示待执行；过去的时间或无法解析的时间被拒绝；重新设定会替换原计时器；到点后用当时捕获的配置启动，启动失败会显示在状态里 | `test_dashboard_run_schedule.py` | P2 |
| A1-11 | 运行日志面板 | 增量读取日志 / 导出 | 首次读取返回全量，之后只返回追加部分；日志重启时强制全量重载；写到一半的多字节字符会等它写完；导出的 Markdown 里反引号不会打断代码块 | `test_dashboard_run_log.py` | P2 |
| A1-12 | 部署服务脚本 | 生成 systemd 服务规格 | dashboard 与 relay 的命令都正确；显式指定的 venv python 保留软链接 | `test_deploy_services.py` | P2 |

### 2.2 配置与 LLM

| 编号 | 用例 | 步骤 / 输入 | 预期结果 | 自动化 | 级别 |
|---|---|---|---|---|---|
| A2-01 | 分层配置 | 导入 `config`（兼容层）与 `gaworld.settings` | 兼容层用的是 settings 对象；默认配置每次返回新的 dict；深合并保留嵌套分区 | `test_gaworld_settings.py` | P0 |
| A2-02 | 类型化配置 | `SimulationConfig.from_legacy` | 标量会被强转；缺失路径用默认值；无效 provider 被过滤；路由表能解析出来 | `test_gaworld_config.py` | P0 |
| A2-03 | 跨 provider 降级链 | 主 provider 抛错或返回空 | 依次换下一个；全部失败时抛出最后一个异常；未知的降级名被跳过；可以关闭降级、只用一个模型；按任务路由优先于默认路由 | `test_gaworld_llm_fallback.py` | P0 |
| A2-04 | 推理预算耗尽 | 响应里只有 reasoning、没有正文 | 报告预算耗尽，不返回空串 | `test_gaworld_llm_fallback.py::TestEmptyCompletionIsAnError` | P1 |
| A2-05 | 被截断的 `actions` 输出 | 输出在半个 JSON 处断开 | 已闭合的活动被恢复，写了一半的列表被丢弃；合法 JSON 原样通过；截断会被计数；长的一天被拆成多次调用 | `test_llm_output_truncation.py` | P0 |
| A2-06 | 图像输入 | 分别走 OpenAI / Anthropic / Ollama 三种格式 | 各自的 wire 格式正确；没有图时 payload 不变；格式错误的图被丢弃；视觉能力按配置或模型名判定 | `test_llm_image_input.py` | P1 |
| A2-07 | 配置面板 | 读取来源、写补丁、重置 | 每个顶层键只出现在一个分区；显示来源层；补丁按原有形状强转；provider 凭据拒绝写入；reset 删除键而不是写回默认值 | `test_dashboard_settings.py` | P1 |
| A2-08 | HTTP 防护 | 同一主机连续请求；请求失败 | 同一主机限速，不同主机互不影响；失败结果按 TTL 缓存；传输失败的退避时间更长 | `test_gaworld_io_http_guard.py` | P1 |
| A2-09 | 网页抽取 | HTML、ld+json、article 标签 | 去掉脚本和标签；优先取正文；能拿到标题 | `test_gaworld_io_web_scrape.py` | P2 |
| A2-10 | MockLLM 夹具本身 | 按任务名取响应 | 已知任务有默认值；调用被记录；`install` 会替换 `call_llm` | `test_mock_llm_fixture.py` | P0 |

### 2.3 微内核与插件体系

| 编号 | 用例 | 步骤 / 输入 | 预期结果 | 自动化 | 级别 |
|---|---|---|---|---|---|
| A3-01 | EventBus | emit / collect / filter | 与 HookBus 兼容；collect 按优先级合并；filter 链式执行，返回 None 时保留原值；handler 出错被隔离，strict 模式下抛出 | `test_kernel.py::TestEventBus` | P0 |
| A3-02 | PluginRegistry | 按类路径加载、声明依赖 | 按依赖顺序 setup；缺依赖的插件被跳过；一个插件 setup 失败只停用它自己；teardown 逆序执行 | `test_kernel.py::TestPluginRegistry` | P0 |
| A3-03 | Controller 动作校验 | 多个 validator | 默认放行；第一个 deny 生效并被记录；rewrite 会传给下一个 validator；validator 自己出错视为不表态 | `test_kernel.py::TestController` | P0 |
| A3-04 | Recorder 与 Clock | 写记录 | JSONL 带 `_day`/`_time` 时间戳；`start_day` 重置 tick | `test_kernel.py::TestRecorder`、`::TestClock` | P0 |
| A3-05 | 内置插件全部可装配 | 构建内核 | 所有扩展钩子都能导入，没有被悄悄禁用；经济插件注册了生命周期钩子 | `test_extension_hooks_resolve.py` | P0 |
| A3-06 | 第三方插件端到端 | 在 `CONFIG["plugins"]` 里声明一个插件 | 它参与到认知阶段 | `test_kernel_plugin_e2e.py` | P1 |
| A3-07 | 认知管线定制与消融 | 去掉 reflect 阶段；按路径插入自定义阶段 | reflect 的 LLM 调用为 0；自定义阶段每一步都执行；未知阶段告警后跳过；零个阶段时报错 | `test_sim_pipeline.py`、`test_pipeline_ablation.py` | P0 |
| A3-08 | 运行时干预 | `set_agent_state` / `update_config` / `remove_agent` | 开箱即注册；点路径能改配置；移除操作排队到日边界，Day 1 移除的 agent 在 Day 2 不再行动；每次干预都有审计 | `test_interventions.py` | P0 |
| A3-09 | 动作校验门端到端 | 移动到一个不存在的地点 | 被拒绝，并在下一个 tick 回注到感知；正常运行没有任何拒绝 | `test_action_gate.py` | P0 |
| A3-10 | 干预与记录流的 HTTP 接口 | POST 干预；SSE 订阅 | 请求经 Controller 生效；参数错误不会让队列停住；新一次运行会丢掉上一次残留的请求；SSE 只推送所选表里新增的完整行 | `test_kernel_api.py` | P1 |
| A3-11 | Agent 适配器与并发 | dict / Agent 互转；`parallel_map` | 往返不丢字段；并行时保持顺序；异常能传出来；workers 小于等于 1 时退回串行 | `test_gaworld_core_agent.py`、`test_gaworld_core_runner.py` | P0 |

### 2.4 智能体认知、日程与行为

| 编号 | 用例 | 步骤 / 输入 | 预期结果 | 自动化 | 级别 |
|---|---|---|---|---|---|
| A4-01 | 一天端到端仿真 | mock LLM，2 个 agent，1 天，`stateful=False` | 不抛异常；每个 agent 的产物都生成；关键任务名都经过 `call_llm` | `test_e2e_smoke.py` | P0 |
| A4-02 | 日程上下文 | 情绪高 / 低；前一天的片段；关系 | 分出不同情绪档；挑出显著性最高的片段；第一天走回退；日程 prompt 包含所有新分区 | `test_daily_routine_context.py` | P1 |
| A4-03 | 日程改动与承诺度 | 触发强度不同 | 高承诺活动能抵住弱触发；LLM 的调整能保留到最终步骤；pre_step 钩子优先 | `test_routine_change_commitment.py`、`test_routine_change_mainline.py` | P1 |
| A4-04 | 日程随机性旋钮 | randomness 设为 0 或设高 | 0 时保持常规，调高后偏离常规；睡眠不受影响 | `test_routine_change_randomness.py` | P2 |
| A4-05 | 锚点匹配阈值 | 调整阈值 | 阈值放松后更容易接受偏离模板的一天；默认值与旧行为一致 | `test_schedule_anchor_threshold.py` | P2 |
| A4-06 | 动态行为系统 | 承诺度、中断、情绪冲动、偶遇、环境级联 | 高优先级中断能打断低承诺活动；饥饿、疲劳、社交需求能生成候选；雨天会级联；在途的 agent 不参与偶遇 | `test_dynamic_behavior.py`、`test_dynamic_behavior_plugin.py` | P1 |
| A4-07 | 需求影响动作选择 | 精力低、自控力低 | 更倾向休息或回避；高承诺活动仍然保持；睡眠恢复自控力 | `test_needs_influence_action_choice.py` | P1 |
| A4-08 | 习惯学习与动作空间 | 重复同一个动作；只有通用填充动作 | 重复的动作成为偏好；只有回退动作的条目不会存盘；一次性上下文不形成习惯 | `test_habit_learning_changes_action_distribution.py`、`test_action_space_fallback_guard.py` | P1 |
| A4-09 | 状态动力学 | 长时间运行 | 餐饮、社交措辞能被识别为需求；状态不会贴在 0 或 1 的边上 | `test_state_dynamics_rebalancing.py` | P1 |
| A4-10 | 意图生成预算 | 预算为 0 / 1 | 为 0 时不调 LLM；只消耗一次 | `test_intention_generation_budget_cap.py` | P2 |
| A4-11 | 好奇心驱动的信息搜寻 | 新事件 + 骰子点数低 | 生成四组信号；满足硬条件才触发；关键词解析失败回退到模板；搜寻结果写进 RAG | `test_curiosity_keywords.py`、`test_curiosity_integration.py` | P2 |
| A4-12 | 日终整合与日记 | 一天结束 | 整合只消耗一次预算；日记回退版本含必需分区；Markdown 文件落盘 | `test_day_end_consolidation_outputs.py` | P1 |
| A4-13 | 物理环境感知（P0） | 节点占用 / 营业时间 | 拥挤度分档；停留的 agent 被计数，陈旧的计数被清掉；在途时为空；地点未知时正常降级 | `test_local_physical.py`、`test_local_physical_plugin.py` | P1 |
| A4-14 | 异常作为一等信号（P2） | 高严重度事件、日内冲击、人流激增 | 标成 anomaly 并提高优先级；高分异常不可恢复；日常天气不算异常；关闭后什么都不标 | `test_anomaly_modeling.py`、`test_env_structured_signals.py` | P1 |
| A4-15 | 当日反应式重规划（P3） | 持续性异常 | 只重排受影响区间（顺延或就地改址）；日程保持有序且不重复；没有受影响的活动时不做任何事 | `test_replan_interval.py` | P1 |
| A4-16 | 结构化空间学习（P4） | 反复遇到某地异常 | 规避分数累积并衰减；超过阈值后改去同类别中更不讨厌的地点；偏好文件往返不丢 | `test_spatial_preferences.py`、`test_env_preferences_persistence.py` | P2 |
| A4-17 | 居家环境 | 按收入生成住宅；在家的活动 | 同一种子结果确定；房间与活动对应；做饭会污染空气，打扫后恢复；不在家时不向 prompt 贡献内容 | `test_home_environment.py`、`test_home_environment_plugin.py`、`test_home_api.py` | P2 |
| A4-18 | 日程网格对齐 | 开启 `time_grid_snap` | 所有时段落在网格上；tick 数不随人口规模增长；幂等；默认关闭 | `test_time_grid_snap.py` | P2 |
| A4-19 | 目标系统 | 三层目标；周回顾；事件回顾 | 持久化往返；每日进度有上限且不倒退；周回顾不能改人生目标；目标内容进入意图、日程、采访、日记的 prompt | `test_goals_module.py`、`test_goals_plugin.py`、`test_goals_prompt_injection.py`、`test_goals_dashboard.py` | P1 |

### 2.5 记忆系统

| 编号 | 用例 | 步骤 / 输入 | 预期结果 | 自动化 | 级别 |
|---|---|---|---|---|---|
| A5-01 | 存储与缓存 | 追加日志后再读取 | 最近的日志块与缓存一致；向量库连接被复用 | `test_memory_store.py::TestMemoryStoreCaches` | P0 |
| A5-02 | 显著性加权召回 | `weighted` 与 `legacy` 两种模式 | legacy 是纯余弦；weighted 提升高显著性条目并累加召回次数 | `test_memory_store.py::TestSalienceWeightedRetrieval` | P1 |
| A5-03 | 向量化方式 | hash / llm 两种 embed | hash 维度保持不变；llm 模式会缓存，失败时回退到 hash | `test_memory_store.py::TestEmbedTextDispatch` | P1 |
| A5-04 | 片段跨天持久化 | Day 1 写入，Day 2 读取 | 追加后能重新加载 | `test_episode_persistence_across_days.py` | P0 |
| A5-05 | 整合与遗忘 | 开启 consolidation / decay | 生成高显著性的语义行；片段太少时跳过；删除低于下限的旧条目；语义和外部条目不被遗忘 | `test_memory_consolidation_decay.py`、`test_memory_lifecycle.py` | P1 |
| A5-06 | 召回影响行为 | 负面或正面的回忆 | 负面回忆抑制重复坏动作，正面回忆强化好动作；回忆会进入采访 prompt；记忆回顾生成元记忆 | `test_memory_recall_and_review.py` | P1 |
| A5-07 | 运行时吸收外部信息 | 开启 ingest | 优先按成长焦点检索，没有时退回按职业；配额限制写入次数；抓取出错不崩 | `test_memory_ingest.py`、`test_bootstrap_external_rag.py` | P2 |
| A5-08 | 成长匹配加权 | 有成长画像 | 与成长相关的条目排在不相关条目之前；关闭后排序不变 | `test_memory_growth_boost.py` | P2 |
| A5-09 | 线程安全 | 在 worker 线程里读写向量库 | 不报错，结果保持输入顺序 | `test_vector_db_threading.py` | P1 |
| A5-10 | 并行写缓存 | 多个进程同时写 | 临时文件名按进程唯一 | `test_cache_parallel_write.py` | P2 |

### 2.6 经济

| 编号 | 用例 | 步骤 / 输入 | 预期结果 | 自动化 | 级别 |
|---|---|---|---|---|---|
| A6-01 | 货币守恒 | 收入、支出、医疗、代扣，跑一整年 | 部门池与个人账户的总额守恒 | `test_economy_conservation.py` | P0 |
| A6-02 | 个税与五险一金 | 低、中收入；社保上限 | 低收入个税为 0；社保按上限封顶；可以分别关闭 | `test_economy_module.py` | P1 |
| A6-03 | 恩格尔系数与预算 | 高 / 低收入 | 低收入的恩格尔系数高、预算以食物为主；休闲支出随收入增长 | `test_economy_module.py` | P1 |
| A6-04 | 宏观周期与冲击 | 推进周期；裁员与医疗冲击 | 周期阶段会切换；收入乘子生效；RNG 与全局 random 隔离 | `test_economy_module.py`、`test_event_economy_shock.py` | P1 |
| A6-05 | 现金约束与信贷 | 流动性不足 | 先砍奢侈品再砍必需品；先动用储蓄再借贷；遵守额度；利息资本化，有盈余时偿还 | `test_economy_credit_market.py` | P1 |
| A6-06 | 支付路由与亲友借贷 | 本地消费、房租、困难户 | 钱流向商户或房东 agent；困难户向朋友借款并在月末还清；Gini 与守恒门可评分 | `test_economy_routing_loans.py` | P1 |
| A6-07 | 画像收入即账本收入 | 画像写明收入 | 账本按画像收入支付；没写收入时用职业档位；最低工资下限仍然生效 | `test_profile_income.py` | P1 |
| A6-08 | 失业率统计 | 退休、非劳动力人口 | 分母按 ILO 口径排除非劳动力；全就业时报 0，不用配置里的初值 | `test_unemployment_readout.py` | P1 |
| A6-09 | 车辆拥有 | 按收入决定 | 富人更常有车；同一种子结果相同；未成年人没有车；有车的人中程出行开车 | `test_vehicle_ownership.py` | P2 |
| A6-10 | 经济 API | `/api/economy/*` | 借贷图与银行负债一致；可以取单人账本 | `test_economy_api.py` | P2 |

### 2.7 地图、位置、交通与城市

| 编号 | 用例 | 步骤 / 输入 | 预期结果 | 自动化 | 级别 |
|---|---|---|---|---|---|
| A7-01 | 城市地图结构 | 加载 citymap | 有坐标、边和叠加层；空间索引的结果与暴力搜索一致；序列化往返后仍能路由；建筑内部结构能解析 | `test_city_map_system.py` | P0 |
| A7-02 | 出行规划与费用 | 各种出行方式、早晚高峰、雨天 | 步行免费；地铁按距离计价；出租车高峰加价；雨天电瓶车换成有遮蔽的方式；规划结果带费用和高峰标记 | `test_location_system.py` | P0 |
| A7-03 | 活动到地点的匹配 | 医疗、购物、职业 → 类别 | 解析出候选地点并遵守最大半径；不存在的类别返回空 | `test_location_system.py::TestResolveLocation`、`::TestCategoryMatching` | P0 |
| A7-04 | 重力模型分配住所与工作地 | 距离衰减参数 | 同一种子得到同一座城；衰减越陡越集中到最近的地点；容量上限生效 | `test_location_assignment.py` | P1 |
| A7-05 | 内生道路拥堵 | 开启拥堵层 | 自由流系数恰好为 1；流量大的边变慢；拥堵下一个 tick 才生效；开启后取代静态高峰代理 | `test_traffic_congestion.py` | P1 |
| A7-06 | 占用记录 | 开启记录 | 默认关闭；开启后记录分布；没人时不写文件 | `test_occupancy_recording.py` | P2 |
| A7-07 | 真实 OSM 地图 | real 模式 bundle | 与虚拟地图结构对齐；距离是真实公里数；图可路由；缺 bundle 时抛错 | `test_real_city_map.py` | P1 |
| A7-08 | 从地名建城 | 地理编码 → OSM → 回退 | 边界框顺序和范围修正正确；OSM 失败时仍能得到城市；离线模式可用；bundle 带投影原点 | `test_city_create.py`（约 45 秒） | P1 |
| A7-09 | 从描述或草图想象城市 | 设计 JSON 或草图 | 能渲染成可加载的地图；越界坐标被夹住；假类别回退为 mixed；没有描述也没有草图时报错 | `test_city_imagine.py` | P2 |
| A7-10 | 城市 bundle 与路径隔离 | 注册、切换、删除 | 两座城市永远不共享路径；删除时连同运行状态一起删；拒绝删除注册表以外的路径 | `test_city_bundle.py` | P0 |
| A7-11 | 往城市里加人、迁移 | add-agents / add-agent / migrate | 追加时续编号；替换时丢弃上一批；迁移时重新安家，也可以保留原住所 | `test_city_agents.py` | P1 |
| A7-12 | 城市命名与本地化 | locale 配置 | 按层回退；西式姓名名在前、用空格连接；缓存损坏不影响生成 | `test_city_locale.py` | P2 |
| A7-13 | 城市知识库 | 检索 → 画像 → 四条影响通道 | 搜索失败不致命；地图信息太少时拒绝声称有某种经济结构；缓存按真实时间刷新 | `test_city_knowledge.py` | P2 |
| A7-14 | 城市 API 与跨城只读 | `/api/city/*` | 列出非当前城市的居民；分页报告总数；未知城市返回 404；选择城市会保留配置里的其他键 | `test_city_api.py` | P1 |
| A7-15 | 离开本市（出差 / 探亲 / 旅行） | 开启 travel | 不在城里的 agent 不占地点、不产生路网负载；回来后恢复真实位置；行程时长随距离增长；被忽视的父母最终会把人拉回去 | `test_travel_away.py` | P1 |
| A7-16 | 室内房间（同屋才算碰面） | 布局、分户、摆放、偶遇、按房间计容量 | 后端布局、选布局规则与 spatial-tree.js 逐项一致，槽位规则与 indoor-view.js 一致；各布局面积占比和为 1；访客不进员工房间，上班的人退到员工房间，别名与家居插件的房间生效；按 citymap 分户、每户一个家庭、不够加层、后来的家庭不打乱已有分配；关着不放人；床不共用、房间合适就不换、在路上没有房间；同楼不同户、同场所不同房间不算碰面，没有房间时退回按地点；就餐区按面积占比满员后改去别家，另一个活动仍可进，拒绝理由写房间，放行的房间就是落座的房间，路上的人按放行房间计数；轨迹只在当前地点带房间；住宅楼一次显示一户（选中居民的，否则人最多的）；真实主循环每步放人 | `test_rooms.py`、`site/dashboard/indoor-view.test.js` | P1 |

### 2.8 社交与家庭

| 编号 | 用例 | 步骤 / 输入 | 预期结果 | 自动化 | 级别 |
|---|---|---|---|---|---|
| A8-01 | 关系 schema 迁移 | 旧版关系字典 | 补全默认值；已有值保留；亲属权重高于网友；摩擦会降低权重 | `test_social_network_schema.py` | P0 |
| A8-02 | 衰减与 Dunbar 分层 | 长期不联系；超过外层上限 | 亲属衰减慢得多；亲密度有下限；超过上限时剪掉最弱的关系，亲属受保护 | `test_dunbar_decay.py` | P0 |
| A8-03 | 关系加权的社交上下文 | 亲密度、义务感、摩擦 | 亲密的人被抽中得更多；义务感提升联系频率，摩擦抑制联系 | `test_relationship_weighted_social_context.py` | P1 |
| A8-04 | 背景故事与幽灵关系 | LLM 生成或启发式回退 | 能解析成记录；LLM 返回坏结果时回退；幂等；ghost id 冲突时去重 | `test_social_backstory.py` | P1 |
| A8-05 | 屏幕外幽灵事件 | 长期没联系 | 更新最近联系日；状态效果被夹在范围内；长时间空白后解锁重联模板 | `test_ghost_events.py`、`test_social_bridge_disclosure.py` | P2 |
| A8-06 | 社交集成链路 | 引导 → 仿真中更新 → 衰减 → ghost | 各环节共存；ghost 事件走完生命事件管线 | `test_simulation_social_integration.py` | P1 |
| A8-07 | 家庭抽样与分户 | 按年龄和性别抽婚姻状态 | 同一种子结果确定；未成年人不会已婚；配偶互指且同住；子女比父母年轻 | `test_family.py` | P1 |
| A8-08 | 家庭覆盖层 | 在工作台固定配偶、子女 | 固定的配对互指且同住；固定值优先于年龄差规则；覆盖文件损坏不会让仿真停下 | `test_family_overrides.py` | P1 |
| A8-09 | 家庭端到端 | 真实跑一次 `run_simulation` | 生成家庭，Dashboard 能读出来，家庭账单进入经济系统 | `test_family_integration.py`（约 37 秒） | P1 |
| A8-10 | 智能体互动与合作任务 | 结交好友、讨论、合作（规划 → 执行 → 审阅 → 汇总） | 好友关系双向且幂等，写入失败时回滚；可以暂停、继续、取消；重启后 running 会话变成 interrupted；产物路径拒绝穿越 | `test_collaboration_*.py`、`test_dashboard_collaboration.py` | P1 |

### 2.9 生命事件与就业

| 编号 | 用例 | 步骤 / 输入 | 预期结果 | 自动化 | 级别 |
|---|---|---|---|---|---|
| A9-01 | 事件调度 | 立即事件、定时事件 | 立即事件只触发一次；定时事件等到时间才触发；目标为空时作用于所有人 | `test_life_events.py`、`test_life_events_plugin.py` | P0 |
| A9-02 | 严重度影响当天 | 不同严重度 | 触发强度随严重度变化；严重事件能压过中等承诺的活动 | `test_life_event_severity_impact.py` | P1 |
| A9-03 | 重排当天剩余日程 | 10 点生病 | 高承诺活动被移到窗口内；没有空档时插入新块 | `test_life_event_reshape.py` | P1 |
| A9-04 | 跨天余波 | 严重事件 | 记下余波并逐日衰减；同一天内衰减是幂等的；prompt 反映剩余强度 | `test_life_event_aftermath.py` | P1 |
| A9-05 | 状态候选事件 | 面板标签云 | 离婚要先有婚姻；退休要满年限；已排队的事件隐藏自己的标签；冷却期结束后标签重新出现 | `test_life_event_candidates.py`、`test_dashboard_life_events.py` | P1 |
| A9-06 | 换工作与失业 | 选模板 + 新职业 | 改写 job、收入随新职业档位变化；失业进入恢复倒计时；随机裁员不改写职业；面板能显示就业块 | `test_employment_events.py` | P1 |

### 2.10 长时段快进与大跨度

| 编号 | 用例 | 步骤 / 输入 | 预期结果 | 自动化 | 级别 |
|---|---|---|---|---|---|
| A10-01 | 按天快进 | `--fast-forward` | 简报能解析并被夹住；没有 LLM 或无法解析时回退；randomness 为 0 时没有突发和抖动 | `test_fast_forward.py` | P0 |
| A10-02 | 月 / 年周期规划 | unit=month/year | 月份按日历对齐且首尾相接；年考虑闰日；最后一期截到跨度为止；钩子区块不超过 30 天；选粗单位时自动开启快进 | `test_long_horizon.py::TestHorizonPlanning` | P0 |
| A10-03 | 阶段简报 | 周期简报 | 用 period 任务和更宽的变化上限；day 单位退回按天简报；突发次数随跨度增加 | `test_long_horizon.py::TestPeriodDigest` | P0 |
| A10-04 | 粗粒度动作与事件空间 | 年单位 | 动作空间和事件空间跟着换档；事件目录来自生命事件模板 | `test_long_horizon.py::TestCoarseActionSpace`、`::TestCoarseEventSpace` | P1 |
| A10-05 | 大跨度社交与个体发展 | 多年运行 | 关系有走向；技能增长；年龄增加；家庭生命周期推进 | `test_long_horizon.py::TestSocialInfluence`、`::TestFamilyLifecycle`、`::TestLifeStageAndHousehold` | P1 |
| A10-06 | 粗粒度经济补跑 | 按月步进 | 日边界钩子按区块补跑，守恒不被破坏 | `test_long_horizon.py::TestEconomyCoarseStep` | P1 |
| A10-07 | 大跨度端到端 | 真实跑 year 单位 | 能跑完，产物齐全 | `test_long_horizon.py::TestLongHorizonE2E`（约 13 秒） | P1 |
| A10-08 | Dashboard 跨度字段 | 保存粗单位 | 跨度换算成 sim_days；同时勾上快进；跨度优先于陈旧的 sim_days | `test_long_horizon.py::TestDashboardSpanField` | P2 |

### 2.11 人格、兴趣、技能与真实工作

| 编号 | 用例 | 步骤 / 输入 | 预期结果 | 自动化 | 级别 |
|---|---|---|---|---|---|
| A11-01 | 大五人格中性回退 | 没有记录或全为 0 | 行为与无人格的 agent 完全一致 | `test_personality_big_five.py::TestNeutralFallback` | P0 |
| A11-02 | 人格可复现与幅度 | 残差、风格匹配、调制 | 每个 agent 的残差稳定，且不消耗全局 RNG；调制在幅度范围内；`strength=0` 关闭所有通道 | `test_personality_big_five.py` | P1 |
| A11-03 | 人格进 prompt | 场景选择维度 | 不写出具体分数；最多写 max_dims 行；叙事文本放在前面 | `test_personality_big_five.py::TestPromptWiring` 等 | P1 |
| A11-04 | Studio 人格面板 | 编辑分数 | 分数被夹住并持久化；来源标注不再声称是采样器生成的；翻转段落描述的维度时明确告警 | `test_dashboard_big_five.py` | P2 |
| A11-05 | 兴趣成长 | 练习、间断、里程碑 | 等级越高增益越小；连续练习有加成；越过阈值产生里程碑；宽限期后开始衰减；等级不低于下限 | `test_interest_growth_*.py`、`test_interests_plugin.py`、`test_interest_daily_routine_prompt.py` | P1 |
| A11-06 | Skill 库 | 全局与私有技能 | 能解析 frontmatter；私有技能优先于同 id 的全局技能；按触发词过滤；附加的技能进入感知 prompt | `test_skill_system.py`、`test_skills_plugin.py` | P1 |
| A11-07 | 真实工作任务 | 市场接单 → 产出 → 结算 | 接单后加锁，第二次接单被挡；每日配额生效；HTML/Python/MD 产物校验（语法错误判失败）；医生专属任务不会被设计师接走 | `test_real_work_*.py` | P1 |

### 2.12 信息源、政策与外部系统

| 编号 | 用例 | 步骤 / 输入 | 预期结果 | 自动化 | 级别 |
|---|---|---|---|---|---|
| A12-01 | 信息源解析 | RSS / Atom / Reddit / 微博 / B 站等 | 各格式能解析出条目；坏的 JSON 返回空；传输错误返回空，不抛异常 | `test_infosources.py` | P1 |
| A12-02 | 信息食谱 | 按职业和兴趣 | 医生读医学、程序员读技术；开放性越高越偏向境外源；对平台的依赖决定社交媒体占比 | `test_infosources.py::TestMediaDiet` | P1 |
| A12-03 | 注入与只读视图 | `/api/infosources` | 注入的条目置顶，刷新后仍在；错误请求被拒；读取行为被记录 | `test_infosources_api.py` | P2 |
| A12-04 | X MCP 搜索 | 握手、429、额度耗尽 | 429 或额度耗尽后进入冷却；认证失败进入长冷却而不是禁用；X 没结果时换下一个引擎 | `test_x_mcp.py` | P2 |
| A12-05 | PolicySim 干预评估 | 开启 intervention | 信息流混合了关系、个性化和头条；风险内容被抑制；立场按 EMA 更新；指标 CSV 落盘 | `test_intervention_policy.py`、`test_intervention_plugin.py` | P1 |
| A12-06 | 外部系统观测台 | 读取、编辑、干预 | 三个系统的配置与运行时状态齐全；未知键被丢弃；排队的干预在日边界生效；宏观值被夹住；LLM provider 不可编辑 | `test_dashboard_external_systems.py` | P1 |
| A12-07 | 环境兼容层 | 根目录 `environment` 模块 | 只转导出，自己不实现；事件带 anomaly 标注 | `test_environment_shim.py` | P2 |
| A12-08 | Moltbook 集成 | 开关、发帖、挑战题 | 公开视图不带 key；只有开了开关且有 key 的居民才发帖；被拒的帖子不会第二天重试；模型失败时回退到摘要 | `test_moltbook.py` | P2 |

### 2.13 人口与群体

| 编号 | 用例 | 步骤 / 输入 | 预期结果 | 自动化 | 级别 |
|---|---|---|---|---|---|
| A13-01 | 参数化人口合成 | 各种旋钮 | 越界值被夹住而不是拒绝；不可行的组合被标出，并给出可调的旋钮和建议；IPF 收敛；边际分布命中目标 | `test_population.py` | P1 |
| A13-02 | 人口可复现 | 同一规格同一种子 | 输出逐字节相同；换种子结果就变；网络旋钮不会重抽人口学属性 | `test_population.py::ReproducibilityTests` | P0 |
| A13-03 | 群体划分 | cohort 轴 | 每个 agent 恰好在一个 cohort；太小的格子被合并而不是丢弃；未知的轴报错 | `test_group_cohort.py` | P1 |
| A13-04 | 群体步进 | 群体 delta、LLM 回退 | 移动均值但保留离散度；delta 被夹住；LLM 失败或无法解析时回退 | `test_group_cohort.py` | P1 |
| A13-05 | 验证门 L0–L4 | 配对实验 | Wasserstein、KS、Moran's I 数值正确；传染产生正的社会自相关；参照组可复现 | `test_group_validate.py` | P1 |
| A13-06 | Population Studio | 预览、生成、导出 | 预览够快，适合按键即时刷新；任务失败会被报告；导出与写盘的产物一致 | `test_dashboard_population.py` | P2 |
| A13-07 | 批量导入与脱敏 | CSV / JSONL | 姓名换成确定性的化名，盐不同结果不同；联系方式被删掉；中英文列名同义词都能识别 | `test_import_api.py`、`test_enterprise_pack.py` | P1 |
| A13-08 | 主运行的群体模式 | `simulation_mode: group` + 按天快进 | 未开快进 / 按月步长 / 未知模式在开跑前被拒；普通运行不注册任何处理器；群体只平移非实体化成员、只动快进简报能动的状态变量，快进简报只给实体化的人；审计残差超阈次日该群体审计翻倍（有上限），连续不告警降回，不加倍时抽样逐位不变；居民档案无行业列时按职业推断；真实主循环里简报数 = 实体化人数、每个居民的状态历史长度一致、写出 `group.day` | `test_group_mode.py` | P1 |

### 2.14 采访、研究与实验

| 编号 | 用例 | 步骤 / 输入 | 预期结果 | 自动化 | 级别 |
|---|---|---|---|---|---|
| A14-01 | 群体采访引擎 | 题型、解析、统计 | 题目 id 稳定；选择题答案匹配已声明的选项，编造的选项判为未解析；中文否定能识别；追问时回放前面的回答 | `test_interview_group_core.py` | P0 |
| A14-02 | 多城市分发 | 每座城一个子进程 | 一座城失败不会丢掉其他城的结果；报告写明没问到的城；子进程固定所在城市且保留已有覆盖 | `test_interview_session_rounds.py` | P1 |
| A14-03 | 附件 | 图片、网址 | 不支持视觉时退化为图注并说明；过大的图被拒；死链回退到图注 | `test_interview_attachments_and_store.py` | P1 |
| A14-04 | 采访端到端 | 真实子进程 + 桩模型 | 能跑完一轮；跨进程保持连续性；图片以图片部件送达模型；当前选中的城市不泄漏到子进程 | `test_interview_end_to_end.py`（slow）、`test_interview_local_persona.py` | P1 |
| A14-05 | 采访 API | `/api/interview/*` | 先报告调用次数再真正花钱；同一时间只允许一轮；带路径穿越的 id 被拒；导出 Markdown | `test_interview_api.py` | P1 |
| A14-06 | 平行世界 | 规格、隔离、分歧 | 至少两个世界；世界补丁不能改实验控制量；每个世界的路径隔离；能找到分歧开始的步；每个世界一个进程，可暂停和继续 | `test_parallel_worlds.py` | P1 |
| A14-07 | 研究工作台 | 论文解读 → 分析 | 空材料被拒；确认过的 digest 会引导 prompt；推荐序号越界时回退到第一个；Markdown 表格里的竖线被转义 | `test_research_workbench.py` | P1 |
| A14-08 | AI 社会科学家 | 方案 → 协议 → 运行 → 判定 | 所有种子一致且超过噪声时判「支持」；种子之间不一致时判「不确定」；单种子又没有安慰剂对照时不能判「支持」 | `test_research_study.py` | P1 |
| A14-09 | 需求估计实验 | 价格网格与答题臂 | 上下文不依赖处理组价格；诱导问题里不含答案；需求曲线能还原生成它的概率 | `test_experiments_demand.py` | P2 |
| A14-10 | 基准任务 | `/api/bench/*` | 白名单；同一时间只跑一个任务；harness 失败被报告为失败 | `test_bench_api.py` | P2 |
| A14-11 | AI 社会科学家 · composite | 平行世界 + 跑后问卷 | 有可计分题时协议为 composite，开放题不成为指标；每个世界的采访带着该世界的覆盖与最后状态，被升级的家人不采访；问卷得分按 0–1 进判定，无法计分的不算 0；少数居民大幅变化撑不起「支持」（逐人配对检验降级） | `test_research_composite.py` | P1 |
| A14-12 | 平行世界 · 参数扫描 | 一个数值配置项 + 几组取值 | 基准保持当前值、每个取值一个世界、剂量 = 取值；不存在 / 非数值 / 实验级的路径、整数参数的小数、超过 8 个世界都报错，等于当前值的取值跳过；补丁在子进程里只改这一片叶子；剂量反应以当前值为起点；面板生成后补丁随运行请求发出 | `test_parallel_sweep.py`、`site/dashboard/worlds.test.js` | P1 |
| A14-13 | 指标来源分级 | 研究指标、问卷指标、Bench 指标 | 每个指标都有等级与依据，目前全为 (c)；(c) 级假设判定不变但标「只读方向」，旧协议按目录补等级；解读在结论里写了大小的被标出，依据里的种子效应不算；报告有「指标来源」节；Bench scorecard 列出最弱依赖并把恩格尔系数、储蓄率标为回显；Bench 与研究目录的九维状态等级一致 | `test_measure_provenance.py`、`benchmark/test_gaworld_bench.py` | P1 |
| A14-14 | Rubric-Bench 人类锚点校准 | 抽集 → 两人标注 → judge → 分析 | 按维度分层、约三分之一被改坏且题目里看不出；人人一致且 judge 一致才 `ok`，人人不一致先判 rubric 有歧义，judge 不一致单独失败，未标完或无 judge 为 `incomplete`；没有通过的校准时 Track R gate 到不了 OK，换了 rubric 或 judge 视为未校准；每位标注者只拿到自己的标注；非法分数、未知题目、未知集被拒 | `benchmark/test_rubric_bench.py`、`test_bench_api.py` | P1 |
| A14-15 | Bench Track B · 对局层 | 谣言 / 公投 / 灾害对局存档 → `--track B` | 三种游戏跑完即落盘（作业完成之前），带 provider 与玩家；未开启存档 / 空结果不写，写失败不影响结果；谣言局被辟谣的相信者留下辟谣前后两次信任度；从众只用不带口径、私下有严格多数的局，两个方向都计；灾害不计解析失败的「其他」；旧谣言存档（无历史）跳过；少于 5 局或样本不够弃权且拉低分数，全弃权为 n/a；混合模型、读不了的文件在报告里标出 | `test_game_archive.py`、`benchmark/test_gaworld_bench.py` | P1 |
| A14-16 | 经典实验库 | 六个范式 × 居民 × 两个条件 | 每个范式是有人类对照、出处与注意事项的两条件对比；提示词带居民、两个条件只差题面、不提实验；解析器认得常见回答、拒收超出 0–100 的金额与非正估计；网格 = 居民 × 题目 × 条件 × 采样，可续跑、拒绝第二个写入者、后端全挂即中止；判定只看配对方向（复现 / 反向 / 未复现 / 样本不足），采样在人内平均，读不出的计数；混合模型被标出 | `test_classic_experiments.py` | P1 |
| A14-17 | 谁是真人 + Bench Track D | 建房 → 聊几轮 → 互猜 → 揭晓 → `--track D` | 座位号随机且在人数上限内；居民的提示词不提有人在猜；一轮整轮出现、按座位号排；房主可以不等缺席的真人收轮，但居民没写完不收；揭晓前玩家看不到谁是谁；每张票覆盖除自己外的每个座位且只投一次；揭晓按票计数并存档，房主可以不等没投的人；座位链接只开自己的座位；消息从 JSON 或散文里读出并截断；Track D 以真人互判率为分母、封顶 1，少于 5 局 / 20 票（对居民）/ 10 票（对真人）弃权，混合模型与读不了的存档在报告里标出 | `test_whois_api.py`、`benchmark/test_gaworld_bench.py` | P1 |

### 2.15 游戏场

| 编号 | 用例 | 步骤 / 输入 | 预期结果 | 自动化 | 级别 |
|---|---|---|---|---|---|
| A15-01 | 斗兽场 | 出题、答题、淘汰 | 先按准确率再按延迟排名；淘汰末尾 top-k；从城市补人时跳过已淘汰的 | `test_arena_api.py` | P2 |
| A15-02 | 说服游戏 | 开局 → 对话 → 判定 | 轮次被夹住；最后一轮自动结算；答案没变判负；重复结算不再调 LLM | `test_games_api.py` | P2 |
| A15-03 | 灾害模式 | 分阶段反应 | 每个人对每个阶段都有反应；一条坏回复只影响那一条；恐慌值被夹住 | `test_disaster_api.py` | P2 |
| A15-04 | 谣言扩散 | 花名册推出的网络 | 邻居、亲属、同事、弱关系的推断正确；每人最多发言一次；孤立的人永远听不到 | `test_rumor_api.py` | P2 |

### 2.16 Dashboard 后端

| 编号 | 用例 | 步骤 / 输入 | 预期结果 | 自动化 | 级别 |
|---|---|---|---|---|---|
| A16-01 | 访问控制 | 点开头的路径、token | 点文件永远不对外提供；没设 token 时和以前一样全开放；设了 token 后 API、静态文件和 POST 都受保护；浏览器登录设置 strict cookie | `test_dashboard_auth.py` | P0 |
| A16-02 | OpenAPI 契约 | `/api/openapi.json` | 文档合法；与模块里的一致；文档里的每个 GET 都已注册、每个 POST 的路径段都在代码里；代码与控制台用到的每个 `/api/` 路由都在文档里；已知路由换了方法返回 405 + `Allow`；未知路由各模块统一 `{"error": "Unknown endpoint"}`；重复启动运行返回 409 | `test_openapi.py` | P1 |
| A16-09 | Python 客户端 | `gaworld.client` | 按 operationId 调用任意接口；错误按状态码抛对应异常；作业轮询到结束、失败抛 `JobFailed`；事件流按表名产出记录；Bearer token 与账号登录的 cookie 都能用 | `test_client.py` | P1 |
| A16-03 | Agent Studio | 状态、身份、关系、记忆、财务编辑 | 写入 CSV 并同步画像 Markdown；取值被夹住；保留 BOM；RAG 条目只打一次标签 | `test_dashboard_studio.py` | P1 |
| A16-04 | agent 列表去重 | `/api/agents` | 每个 id 一条；CSV 与 Markdown 覆盖同一批 id；表头重复时显示出来 | `test_dashboard_agents_unique.py` | P1 |
| A16-05 | 分析面板 | 各类读取 | 产物损坏时降级为空；归档的运行不借用正在运行的产物；不在列表里的 run id 被拒 | `test_dashboard_analytics.py` | P1 |
| A16-06 | 家庭卡片 | 预览与覆盖 | 保存覆盖后预览变化并标为固定；非法编辑返回可读的错误信息 | `test_dashboard_family.py` | P2 |
| A16-07 | 公开部署可用 | 首次运行之前 | 空轨迹返回 JSON 而不是缺文件；头像不依赖已有运行；CSS 资源存在 | `test_dashboard_public_resources.py`、`test_public_smoke.py` | P1 |
| A16-08 | 文档面板与待办 | 列出的文档、todo 表单 | 列出的每篇文档都存在且可访问；待办的增删改能持久化 | `test_dashboard_docs.py`、`test_dashboard_todos.py` | P2 |
| A16-09 | 真人蒸馏 | 检索 → 蒸馏 → 部署 | 检索失败不会中止；证据少时在边界里标出；部署时写种子、画像和大五；操作员覆盖优先 | `test_persona_distill.py`、`test_persona_api.py` | P1 |
| A16-10 | 回放与可视化 | 回放列表、帧 | 从大文件头部读取元信息；损坏的轨迹返回空元信息；多次运行各自归档 | `test_replay_runs.py`、`test_simulation_visualizer.py` | P2 |

### 2.17 数字孪生、分布式与部署

| 编号 | 用例 | 步骤 / 输入 | 预期结果 | 自动化 | 级别 |
|---|---|---|---|---|---|
| A17-01 | 孪生绑定 | 发码 → 兑换 token | 明文的码和 token 都不落盘；撤销码会让它已发出的 token 失效；已被认领的 agent 能列出来 | `test_twin_binding.py` | P1 |
| A17-02 | 孪生上报与存储 | 上报、修改、快照 | 去重；只能改自己的上报；不能改位置；删掉最新一条后前一条补上 | `test_twin_store.py`、`test_twin_backend.py` | P1 |
| A17-03 | 孪生服务 | HTTP 路由 | 所有读路由都要 token；Dashboard 接口不对外；仓库文件和路径穿越不可访问；软链接不能逃出资源目录 | `test_twin_server.py` | P0 |
| A17-04 | 孪生进入仿真 | mirror / perceive 阶段 | 快照陈旧时跳过；地图外的位置标记为离开本市，不吸附到最近节点；在真实 tick 里触发 | `test_twin_stages.py`、`test_twin_e2e.py`、`test_twin_geo.py`、`test_twin_places.py` | P1 |
| A17-05 | 孪生标定 | 聚合 → 补丁 | 不批准就不写入；只包含超过阈值的地点 | `test_twin_calibrate.py`、`test_twin_life.py` | P2 |
| A17-06 | 分布式 relay | 发送与轮询 | 消息能送达；收件箱格式正确；公开冒烟必须确认消息真的送达，而不只是 HTTP 成功 | `test_distributed_comm.py`、`test_public_smoke.py` | P2 |

### 2.18 国际化

| 编号 | 用例 | 步骤 / 输入 | 预期结果 | 自动化 | 级别 |
|---|---|---|---|---|---|
| A18-01 | 语言文件一致 | en / zh | 键集合相同且顺序一致；HTML 和 JS 引用的键都存在 | `test_i18n.py`、`test_i18n_js.py` | P2 |
| A18-02 | 配置文档中英对照 | 标签与帮助文字 | 每条都有英文版，且不是中文原样复制；没有孤立的英文条目 | `test_i18n.py::TestConfigDocsBilingualParity` | P2 |

### 2.19 手工 UI 验收（浏览器）

后端测试覆盖了接口，但页面渲染和交互要在浏览器里确认。先启动 `python generative_city_sim.py dashboard --port 8766`，再逐页检查：

| 编号 | 页面 | 步骤 | 预期结果 | 级别 |
|---|---|---|---|---|
| M-01 | 控制台 `/dashboard` | 打开页面，逐个切换页签 | 所有页签都能加载，控制台无报错；中英文切换后文案都换掉 | P1 |
| M-02 | 运行控制 | 设 sim_days=1，点运行 | 运行日志持续增加；结束后分析面板有数据 | P0 |
| M-03 | Agent Studio | 选一个 agent，改九维状态并保存 | 刷新后值还在；非当前城市的居民只能看不能改 | P1 |
| M-04 | 城市面板 | 离线新建一座 tiny 城并切换过去 | 列表出现新城；切换后 Studio 列出新居民 | P1 |
| M-05 | 群体采访 | 选两座城，出一道选择题 | 执行前显示预估调用次数；完成后有统计图，可以导出 Markdown | P1 |
| M-06 | 平行世界实验台 | 两个世界，一个带事件 | 分歧曲线从事件日开始分开 | P1 |
| M-07 | 研究工作台 | 贴一段论文 → 解读 → 分析 | 生成 2–3 种设计，并标出推荐的一种 | P2 |
| M-08 | 游戏场 | 各玩一局说服游戏和谣言扩散 | 判定结果和扩散树都能显示 | P2 |
| M-09 | 仿真回放 | 选一次运行 | 轨迹能在地图上动起来 | P2 |
| M-10 | 移动端孪生 | 手机宽度打开孪生页 | 能绑定、上报；在地图外的位置显示地名 | P2 |

---

## 三、套件 B · 核心功能测试

选取原则：只选仿真主干，也就是一旦坏了仿真就跑不起来、或者产物会出错的部分。全部 mock LLM，不访问网络，不起子进程，约 30 秒跑完。每个用例对应 [`tests/suites/core.txt`](../tests/suites/core.txt) 中的同名分组。

| 编号 | 核心功能 | 验证点 | 自动化 |
|---|---|---|---|
| C-01 | 配置分层与覆盖 | 兼容层 `config` 指向 settings；默认配置不共享可变对象；深合并保留嵌套；类型化配置能强转标量并过滤无效 provider | `test_gaworld_settings.py`、`test_gaworld_config.py` |
| C-02 | LLM 路由与降级 | 主 provider 失败时切到下一个；全部失败时抛出最后一个错误；按任务路由生效；空响应算失败；截断的 JSON 能恢复出已闭合的部分，合法 JSON 原样通过；MockLLM 夹具可用 | `test_gaworld_llm_fallback.py`、`test_llm_output_truncation.py`（两个类）、`test_mock_llm_fixture.py` |
| C-03 | 微内核六服务 | 总线的优先级和过滤链、插件依赖顺序与故障隔离、校验门 deny/rewrite、记录带时间戳、上下文命名空间 | `test_kernel.py` |
| C-04 | 插件装配 | 所有内置插件都能 setup；配置里声明的第三方插件参与认知 | `test_extension_hooks_resolve.py`、`test_kernel_plugin_e2e.py` |
| C-05 | 认知管线 | 默认阶段顺序；消融 reflect 后没有反思调用；按路径插入的自定义阶段每一步都执行 | `test_sim_pipeline.py`、`test_pipeline_ablation.py` |
| C-06 | Agent 与并发 | dict/Agent 适配往返；并行执行保持顺序并传出异常 | `test_gaworld_core_agent.py`、`test_gaworld_core_runner.py` |
| C-07 | 记忆 | 追加后缓存一致；向量库连接复用；显著性加权召回；embed 失败回退；片段跨天能重新加载 | `test_memory_store.py`、`test_episode_persistence_across_days.py` |
| C-08 | 一天端到端 | 2 个 agent 跑 1 天不报错；产物齐全；关键 LLM 任务都被调用 | `test_e2e_smoke.py` |
| C-09 | CLI | `run --sim-days` 覆盖天数；子命令都能解析；`reset` 清空产物并回到 Day 0；`rag-add` 写入外部知识；`interview` 合并问题 | `test_cli_run_sim_days.py`、`test_cli_commands.py` |
| C-10 | 续跑与闸门 | 按 agent 的日期游标续跑；记忆 schema 不一致时拦截 | `test_resume_start_day.py`、`test_reset_gate_for_memory_model.py` |
| C-11 | 经济守恒 | 收入、支出、代扣、医疗在一年内守恒 | `test_economy_conservation.py` |
| C-12 | 地图与出行 | 地图结构和路由；出行规划的距离、方式和费用；活动能解析到地点 | `test_city_map_system.py`、`test_location_system.py`（三个类） |
| C-13 | 社交网络 | schema 迁移；按角色衰减；Dunbar 剪枝时保护亲属 | `test_social_network_schema.py`、`test_dunbar_decay.py` |
| C-14 | 生命事件 | 立即事件只触发一次；定时事件等到时间；目标为空时作用于所有人 | `test_life_events.py` |
| C-15 | 干预与校验门 | 状态、配置、移除三种干预及审计；去不存在的地点被拒绝并回注到感知 | `test_interventions.py`、`test_action_gate.py` |
| C-16 | 长时段 | 按天快进的简报与回退；月/年周期切分正确；阶段简报 | `test_fast_forward.py`、`test_long_horizon.py`（两个类） |
| C-17 | 大五人格 | 没有人格数据时行为不变；残差稳定 | `test_personality_big_five.py`（两个类） |
| C-18 | 运行清单 | 清单结构与版本；key 脱敏；partial 清单的写入与清理；HTML 转义 | `test_gaworld_run_manifest.py` |
| C-19 | 城市隔离 | 运行路径都在各自城市下；两座城不共享路径；删除时连同运行状态 | `test_city_bundle.py` |
| C-20 | 群体采访引擎 | 题型校验、答案解析、否定识别、追问连续性、统计 | `test_interview_group_core.py` |
| C-21 | 人口合成 | 结构合法；同一种子逐字节可复现 | `test_population.py`（两个类） |
| C-22 | 平行世界规格 | 至少两个世界；事件时间合法；不能改实验控制量；路径隔离 | `test_parallel_worlds.py::SpecTests` |
| C-23 | Dashboard 安全与契约 | 点文件不对外；token 门控；OpenAPI 与路由双向一致；Python 客户端；分布式世界的节点令牌只到自己的世界 | `test_dashboard_auth.py`、`test_openapi.py`、`test_client.py`、`test_cluster.py` |

**核心套件准入规则**

1. 核心套件必须全绿，才能提交到 `Dev`。
2. 往 `core.txt` 加用例前，先确认它的依赖（mock LLM、无网络、单条耗时低于 2 秒）；超过这个标准的放到全量套件。
3. 核心模块（`gaworld/kernel`、`gaworld/sim`、`gaworld/llm`、`gaworld/memory`、`gaworld/settings`、`generative_city_sim.py`）改动后，要同时检查对应的 C 用例是否需要补充。

---

## 四、执行

```bash
pytest --suite core
```

```bash
pytest --suite full
```

```bash
pytest --suite full -m "not slow"
```

```bash
pytest --suite core tests/test_kernel.py
```

最后一条会在单个文件里取与核心清单的交集，适合改某个模块时快速自查。

## 五、基线（2026-09-26，`Dev` 分支加上工作区里未提交的改动）

| 套件 | 结果 | 耗时 |
|---|---|---|
| 核心 | 330 通过，1 跳过（`openapi-spec-validator` 没装） | 约 31 秒 |
| 全量 | 2,773 通过，12 失败，2 跳过 | 约 4.5 分钟 |

全量里 12 个失败都已经存在，与核心套件无关：

| 测试 | 原因 |
|---|---|
| `test_arena_api.py::HttpDelegationTest::test_generate_endpoint_returns_tasks` | 真的去连本地 Ollama（`localhost:11434`），没有 mock |
| `test_i18n.py::TestConfigDocsBilingualParity`（2 个失败 + 4 个子用例） | 新增的 `home.*` 配置项缺少英文标签和帮助文字 |
| `test_dashboard_life_events.py::PanelHeadingTest`（子用例 `home.kicker`） | 同上，`home.kicker` 与标题冲突 |
| `test_infosources.py::TestMediaDiet::test_doctor_reads_medicine_programmer_reads_tech`、`::TestPlugin::test_agents_built_refreshes_feed_and_builds_diets` | 信息食谱的断言与当前注册表不一致 |
| `test_collaboration_frontend.py::test_cooperation_layout_and_console_tabs_are_responsive` | 前端布局断言 |
| `test_dashboard_big_five.py::TestPluginStillReadsWhatThePanelWrites` | 插件加载器与面板新增的列 |

## 六、覆盖缺口（后续可以补）

| 功能 | 现状 | 建议 |
|---|---|---|
| `create-agent-from-social` | 只测了参数解析 | mock 抓取和 LLM，断言新 agent 同时写进 CSV 和画像 |
| `rag-import` | 没有测试 | 用目录和文件两种输入，断言 source 标签与插入条数 |
| `serve-viz` / `serve-distributed` 启动 | 只测了参数解析和服务规格 | 起在临时端口上，做一次健康检查 |
| 日志模式与级别（`GAWORLD_LOG_MODE` / `GAWORLD_LOG_LEVEL`） | 没有测试 | 断言 simple 模式下每个 tick 的行数上限 |
| `--seed` 端到端可复现 | 人口、地点、经济各自测过，整次运行没测 | 同一种子跑两次 1 天仿真（mock LLM），比较状态 CSV |
| `python -m gaworld.city` 与 `python -m gaworld.group` 的 CLI 入口 | 测了库函数，CLI 包装层没测 | 用 `main(argv)` 跑 `--offline` / `--no-llm` 的最小参数 |
