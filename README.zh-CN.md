# GAWorld

[English](./README.md) | [中文](./README.zh-CN.md)

GAWorld 是一个面向城市社会行为实验的生成式多智能体仿真项目。
它把人物画像、长期记忆、社会影响、环境扰动、政策事件、经济状态、地图移动、轻量平台干预评估和 LLM 决策过程组合到一个可回放、可对照、可扩展的模拟流程中。

## 项目概览

GAWorld 的目标不是简单地“跑一群 Agent”，而是提供一个可控制的社会实验场。你可以：

- 让同一批智能体在不同事件或政策条件下运行
- 并行比较有事件和无事件的反事实场景
- 保留跨天记忆、习惯、意图和关系变化
- 检查轨迹、日志、访谈结果和记忆文件
- 在不增加外部 API 的情况下评估 PolicySim 风格的推荐 / 曝光干预
- 通过本地 dashboard 修改配置、人物 profile 并控制运行

适用场景包括：

- 城市治理和政策影响模拟
- Agent 记忆架构与行为一致性实验
- 社会行为与风险传播研究
- 复杂系统或智能体仿真的课程演示

## 核心流程

每个智能体会循环经历：

1. 感知
2. 计划
3. 日程 / 动作生成
4. 动作执行
5. 反思与记忆更新

随着天数推进，系统会持续累积：

- episode 记忆
- 长期总结
- 基于上下文的习惯
- 日级意图
- 关系变化
- 收支与资产变化

## 微内核插件架构

自 2026-07 起，GAWorld 运行在 society-centric 微内核架构上（参考
[Agent-Kernel](https://arxiv.org/abs/2512.01610)）：

- **内核**（`gaworld/kernel/`，零领域逻辑）：`Clock` 时钟、`EventBus`
  事件总线（observe/collect/filter 三种钩子语义）、`PluginRegistry`
  插件注册表、`Controller`（动作校验 + 可审计运行时干预）、`Recorder`
  统一事件流、`SimContext` 运行时上下文。
- **认知管线**（`gaworld/sim/pipeline.py`）：每个 agent step 是 12 个
  命名阶段的可配置序列（`prepare → perceive → interrupts → plan →
  adjust_activity → move → select_action → reflect → update_state →
  broadcast → memorize → record`）。消融、替换、插入阶段都只是改
  `CONFIG["pipeline"]`。
- **插件**：全部 9 个内置子系统（干预、技能、兴趣成长、人生事件、经济、
  物理感知、真实工作、动态行为、空间偏好）与第三方扩展走同一套插件
  接口——写一个 `Plugin` 子类 + `CONFIG["plugins"]` 一行声明（或 pip
  包的 `gaworld.plugins` entry point），主循环零改动。
- **运行时干预**：`Controller.intervene` 自带 `set_agent_state`、
  `update_config`、`remove_agent`（日边界生效）、`inject_life_event`
  四个标准干预，每次调用自动审计。

事件目录与完整示例见[插件作者指南](./docs/PLUGIN_AUTHORING.md)。

## 主要能力

- 微内核插件体系：子系统皆可插拔，扩展无需改核心；12 阶段可配置认知管线；可审计运行时干预（状态编辑 / 配置修改 / 移除智能体 / 注入事件）
- 从 CSV 状态种子和 Markdown profile 构建智能体
- 从社交媒体页面或提取文本创建新智能体
- 多后端 LLM 路由：Ollama、OpenAI 兼容、Anthropic 兼容
- 支持通过 CLI 或文件注入外部 RAG 信息
- 政策事件和环境事件模拟
- PolicySim 风格的推荐 / 曝光干预指标
- 货币守恒的闭环经济仿真（企业/政府/银行部门池、个税与五险一金真实代扣、现金约束消费 + 信贷、共同市场因子投资、智能体间支付路由与熟人借贷、宏观经济周期）
- 大五人格（OCEAN）：每位居民带一组 O/C/E/A/N 的 z 分数，通过三条可独立开关的通道影响行为——`rules`（确定性、零 token：动作选择里的加性 style-fit 分量，中断阈值 / 自发行为 / 社交偶遇概率 / 决策噪声 / 冲动绕过 / 财富驱动上的有界乘子，以及个人情绪基准点）、`prompt`（把人格锚句注入日程生成、活动调整、目标与新闻 prompt）、`voice`（锚句只进日记 prompt）。三条通道分开，才能让实验把「决策变了」和「文风变了」分开归因。特质在构建智能体时一次性种入——有 `data/agents_big5.csv` 就用离线生成的值（**先独立采样五维分数，再据此改写每个人 profile 里的行为描述**，而不是从 profile 文本反推分数），没有就从带相关结构的人口先验采样——且运行期间不漂移（成年人的 OCEAN 每十年只变 0.1–0.2 个标准差）。没有特质的智能体、或被关掉的通道，行为与加人格之前**逐位一致**
- 家庭与户：按年龄段 × 性别抽样婚姻状态（未婚/已婚/离异/丧偶），匹配得上的居民在仿真内配成夫妻并**共享同一个住处**，配不上的补场外家人；子女、同住长辈、合租室友随之生成。户型（独居/合租/与父母同住/未婚同居/夫妻二人/核心家庭/单亲/三代同堂）是分配结果的**读数**而不是预设配额。家庭进入日程（接送、陪写作业、照料老人、回家吃晚饭）、账本（育儿与赡养开销按收入分摊、伴侣互相补现金缺口，全程货币守恒）、事件（一件家事同一 tick 落到全家人身上）与户内情绪传染；可在配置面板调整整体分布，也可在 Agent Studio 里逐人精确指定并跨运行生效
- 真实位置系统：基于类别的空间匹配、出行成本计算、高峰时段和天气影响、通勤记忆
- 动态行为系统：情绪驱动的即兴行为、社交偶遇链、需求中断、环境事件连锁反应、承诺度感知的日程中断
- 物理环境感知与反应式重规划：节点级拥挤度 / 营业时间感知、异常检测、当日受影响区间重排、习得的地点规避偏好
- 兴趣爱好与技能成长系统：为每个智能体生成兴趣、计划发展的技能、练习时间、成长进度，并影响日程、行动、工作和生活选择——含幂律学习曲线、连击动量、里程碑事件、日终遗忘衰减、兴趣发展四阶段与社交兴趣传染
- 可复用 Skill 库：基于 Markdown 的全局 / 私有技能，可从经历自动提炼，并注入认知与工作 brief
- 真实工作任务系统：智能体在 mock 工作市场浏览、接单，按职业与技能产出真实产物（HTML、Python、文章、教案、研究笔记）
- 城市地图生成与轨迹回放
- 可视化 trace 导出
- 单智能体采访 CLI
- 本地 dashboard：配置编辑、profile 编辑、运行控制、记忆查看、访谈
- Agent Studio：面向单个智能体的 7 步可视化构建/查看器——身份、九个 [0,1] 状态变量（可编辑雷达）、技能、分层记忆、Dunbar 社交圈、行为拨盘、复核/部署；改动写回状态 CSV 与 profile Markdown，并可创建新智能体
- 参数化人口合成：把面板级旋钮（规模、年龄金字塔、就业率、收入基尼、家庭结构、社交图形态）变成一座完整的小镇——IPF 拟合联合分布（含结构性零）、最大余数法整数化让边缘精确命中、收入用秩变换使中位数与基尼严格成立同时仍与教育/行业相关、儿童优先建户、幂律规模的工作单位。产出与现有格式完全一致的状态 CSV + profile Markdown，`build_agent` 无需改动
- 群体（cohort）模拟：把居民划分成同时携带**均值与离散度**的群体，每群每天只花 1 次 LLM 调用，并按预算把一小批个体（focal / event / tail / audit）提升到完整保真度；群内零均值的社交图耦合项让邻居共变在聚合后依然存在。实体化预算 20 人/天时约比逐个体模拟省 25 倍
- 群体模式验证门（L1–L4）：配对实验，量化 cohort 近似的代价——分布距离、网络共变、尾部保留、政策冲击下的因果响应；判定阈值来自参照层自身的跨种子噪声，而不是拍脑袋的常数。分水岭层不通过时退出码非零，可直接进 CI
- Population Studio：5 步 dashboard 面板，生成人口 → 群体模拟 → 阅读验证结论，并带实时可行性预检（参数冲突时直接指出该动哪个旋钮）
- 外部系统观测台：观察并编辑世界本身——货币系统（宏观周期、部门池、每日货币守恒审计、财富分布与基尼）、外部环境生成器、对外服务连接。配置表单按配置自身的 JSON 形状生成（约 150 个旋钮，加旋钮不用改面板），并可对**跑着的**仿真排一次货币干预，由仿真在下一个日边界消费；给部门池注资会同步移动守恒基准，因此审计把有意的注资记成注资而不是漏钱
- 平行世界实验台：把一座城市分叉成 N 段历史——共用同一批居民、同一个随机种子、同一个天数与模型，唯一的区别是发生了什么。每个世界带自己的事件表（也可以带自己的 config 补丁，对应「政策」而非「事件」），跑在完全隔离的记忆 / 状态 / 日志目录里。报告逐步测量每个世界与基准的距离，因此能回答两段历史**从哪一步开始分叉**，而不只是终局差了多少，并指出这件事真正落在了哪些居民身上。在控制台的「平行世界」标签页里交互式设计与查看；每个世界的轨迹仍可逐帧回放，已有的 compare-event 结果也会被适配进同一个视图，无需在磁盘上改写
- 多机分布式 relay 通信模式

## 项目结构

```
GAWorld/
├── gaworld/                       # 核心包（所有功能的唯一正式实现）
│   ├── kernel/                    # 微内核：时钟、事件总线、插件注册表、Controller、Recorder、SimContext、标准干预
│   ├── plugins/                   # 内置插件装配点（builtin_plugins()，9 个插件）
│   ├── sim/pipeline.py            # 可配置的 12 阶段认知管线
│   ├── apps/                      # 应用服务：dashboard、visualizer、relay 服务器
│   ├── behavior/dynamic.py        # 动态行为（中断、自发行为、社交链）
│   ├── cognition/realism.py       # 真实感：意图、习惯、关系权重、记忆整合
│   ├── core/                      # Agent dataclass 适配层 + 并发执行器
│   ├── distributed/comm.py        # 多机 relay 客户端
│   ├── economy/finance.py         # 个人财务 + 宏观经济周期
│   ├── env/system.py              # 环境系统（天气、事件、干预 feed）
│   ├── events/life.py             # 生命事件调度
│   ├── family/                    # 家庭与户（婚姻抽样、共居、家庭日程与账目、家庭事件、手工覆盖层）
│   ├── io/                        # HTTP guard、头像生成、HTML 抽取
│   ├── llm/providers.py           # LLM 提供商封装与路由
│   ├── memory/                    # 记忆系统（store、experience、consolidation、decay、spatial_preferences）
│   ├── personality/               # 大五人格 OCEAN（traits、anchors + plugin.py，三通道默认开启）
│   ├── policy/intervention.py     # 干预指标与推荐
│   ├── settings/                  # 分层配置（LLM、运行时、行为、经济、环境）
│   ├── sim/                       # 仿真子模块（schedule、location、cognition、rag…）
│   ├── skills/                    # 可复用 Skill 库（registry、Markdown schema、提示注入、经验提炼）
│   ├── social/network.py          # 社交网络（衰减、Dunbar 分层、ghost 事件）
│   ├── work/                      # 工作任务系统（queue、market、router、adapters）
│   ├── world/city_map.py          # 城市地图（图结构、路线、出行成本、空间查询）
│   ├── world/local_physical.py    # 局部物理感知（占用 / 营业快照、人流骤增异常、感知注入）
│   ├── hooks.py                   # 生命周期钩子（HookBus）
│   ├── interests.py               # 兴趣与成长画像
│   └── logging_setup.py           # 日志配置
├── generative_city_sim.py         # CLI 入口（run / reset / interview）
├── legacy/                        # 旧版 flat 模块（已弃用，不参与构建）
│   └── README.md                  # 旧模块 → 新位置对照表
├── data/                          # 数据资产（agents CSV、profiles MD、citymap MD）
├── scripts/                       # 辅助脚本（generate_citymap 等）
├── tests/                         # 测试套件（pytest，全部使用 gaworld.* import）
├── docs/                          # 设计文档、重构记录
└── output/                        # 生成产物（日志、记忆、图表，不纳入版本控制）
```

**开发规则：新代码只写进 `gaworld/` 包，不添加新的根目录模块。**

主要子包说明：

- `gaworld/settings/`：分层配置片段（LLM、运行时、行为、经济、环境、覆盖项）
- `gaworld/core/`：类型化 `Agent` dataclass + 并发 `parallel_map` 执行器
- `gaworld/llm/providers.py`：Ollama / OpenAI 兼容 / Anthropic 兼容路由
- `gaworld/memory/`：向量库、记忆持久化、巩固与衰减
- `gaworld/world/city_map.py`：图结构、路线、出行成本、天气/高峰效应
- `gaworld/sim/`：从主仿真器拆分出来的子模块（持续细化中）
- `gaworld/work/`：real-work 任务系统（runtime、worker pool、queue、market）
- `gaworld/population/`：参数化人口合成——`schema`（旋钮契约 + 可行性预检）、`synth`（IPF + 条件采样 + 收入秩变换）、`network`（家庭、工作单位、同质性社交图）、`report`（校验门 + 复核图表）、`writer`（状态 CSV + profile MD + manifest）
- `gaworld/group/`：群体（cohort）模拟——`cohort`（划分、均值**与**离散度、群内零均值网络耦合）、`cohort_day`（每群每天 1 次 LLM 调用）、`materialize`（focal/event/tail/audit 选取与审计残差）、`driver`（日循环 + 成本核算）、`metrics` + `validate`（L1–L4 验证门）、`plugin`（观测型 cohort 遥测）
- `gaworld/apps/`：dashboard、外部环境服务器、分布式 relay，以及两个面板后端 `population_api`（Population Studio）与 `external_systems_api`（外部系统观测台）
- `gaworld/parallel/`：平行世界实验——`spec`（世界/事件校验 + 各世界磁盘隔离的配置覆盖）、`runner`（用小型进程池分叉 N 个世界并跟踪进度）、`analysis`（逐步偏离度、分叉点、逐人影响）
- `site/dashboard/`：dashboard 前端（控制台 `index.html` + Agent Studio `studio.html` + Population Studio `population.html` + 外部系统 `external.html` + 平行世界 `worlds.html`）
- `site/simviz/`：轨迹回放页面
- `output/`：生成结果

## 快速开始

安装依赖：

```bash
pip install -r requirements.txt
```

运行仿真：

```bash
python generative_city_sim.py run
```

**长时段快进**（把每天压缩成每个智能体一条日简报——每 agent 每天 1 次 LLM 调用——跳过日内时刻循环；状态/目标/关系仍近似推进）。配合较大的 `--sim-days`，或在 dashboard 工具栏勾选「长时段快进」：

```bash
python generative_city_sim.py run --sim-days 600 --fast-forward
```

**大跨度模拟**：把一步做成一整个月或一整年——每人每月/每年一条「阶段简报」，附 2–4 条里程碑写进记忆。这是数年到数十年模拟跑得起来的前提：50 个居民跑 10 年，按年约 500 次 LLM 调用，按天则是约 18.25 万次。底层仿真日历仍逐日推进（大小月、闰年都算对），经济结算、兴趣衰减、家庭开销等日边界钩子按 ≤30 天区块补跑，所以跑满一年会扣一年房租、走满 12 次月度结算，而不是只扣一天：

```bash
python generative_city_sim.py run --sim-years 10              # 一年一步
python generative_city_sim.py run --sim-months 24             # 一个月一步
python generative_city_sim.py run --sim-years 10 --time-unit month
```

`--sim-months` / `--sim-years` / `--time-unit` 任意一个都会自动打开快进。代价是彻底的：日内与逐日细节全部消失，一步只剩一条叙事简报和一组累计增量。适合看长期演化（生涯轨迹、政策的多年后效），不适合看日内行为。

重置状态：

```bash
python generative_city_sim.py reset
```

启动 dashboard：

```bash
python generative_city_sim.py dashboard --port 8766
```

然后打开：

```text
http://127.0.0.1:8766/dashboard
```

单独启动轨迹回放页面：

```bash
python generative_city_sim.py serve-viz --port 8000
```

然后打开：

```text
http://127.0.0.1:8000/site/simviz/index.html
```

## CLI 用法

查看帮助：

```bash
python generative_city_sim.py --help
```

运行仿真：

```bash
python generative_city_sim.py run
```

重置仿真：

```bash
python generative_city_sim.py reset
```

采访单个智能体：

```bash
python generative_city_sim.py interview --agent-id 31 --question "你今天为什么这样行动？"
python generative_city_sim.py interview --agent-id 31 --questions-file questions.txt
```

从社交内容创建新智能体：

```bash
python generative_city_sim.py create-agent-from-social --url "https://weibo.com/..."
python generative_city_sim.py create-agent-from-social --file output/source_page.txt --name "新智能体"
```

添加外部 RAG 信息：

```bash
python generative_city_sim.py rag-add \
  --agent-id 31 \
  --text "周末更喜欢骑行和逛书店" \
  --timestamp "2026-02-18 09:30" \
  --source "manual"
```

导入外部 RAG 信息：

```bash
python generative_city_sim.py rag-import \
  --agent-id 31 \
  --file output/test_extra_info.txt \
  --source "profile_notes"
```

执行事件对照实验：

```bash
python generative_city_sim.py compare-event \
  --event-name "临时交通限行" \
  --event-description "主干道限行导致通勤时间上升并影响出行决策" \
  --event-day 2 \
  --event-time 09:00 \
  --sim-days 3 \
  --llm-provider minimax \
  --seed 42
```

对照报告会同时包含常规城市状态指标和干预指标，例如 `stance_score`、`toxicity_score`、
`misinformation_risk`、`cross_viewpoint_exposure`、`intervention_reward`。

需要两个以上分支时（基准 + 若干干预强度 + 安慰剂对照），用一份 JSON 定义整场实验：

```bash
cat > worlds.json <<'JSON'
{
  "name": "限行强度对比",
  "sim_days": 3,
  "worlds": [
    {"label": "基准世界", "events": []},
    {"label": "轻度限行", "events": [
      {"day": 2, "time": "07:00", "name": "临时交通限行",
       "description": "早晚高峰单双号限行，通勤时间小幅增加。"}]},
    {"label": "重度限行", "events": [
      {"day": 2, "time": "07:00", "name": "全面交通管制",
       "description": "主干道全面管制，部分居民无法到岗。"}]}
  ]
}
JSON

python generative_city_sim.py parallel-worlds --spec worlds.json --seed 42 --fast
```

所有世界共用同一批居民、同一个随机种子、同一个天数与模型，各自跑在独立的记忆 / 状态 /
日志目录里。报告（`output/parallel_worlds/<id>/`）不只给终局差异，还会逐步测量每个世界与
基准世界的距离，因此能回答"两段历史是从哪一步开始分叉的"，并列出这件事真正落在了哪些居民
身上。世界之间除了事件，也可以用 `config` 补丁区分——那对应的是"政策"而不是"事件"。
同一套实验可以在控制台的 **平行世界** 标签页里交互式地设计与查看。
完整教程（面板导览、读图方法、剂量反应实验、安慰剂对照、API 速查）见[平行世界教程](./docs/PARALLEL_WORLDS_TUTORIAL.md)。

生成城市地图：

```bash
python scripts/generate_citymap.py --description "a small city with about 1000 residents, in east china"
```

启动分布式 relay：

```bash
python generative_city_sim.py serve-distributed --host 0.0.0.0 --port 8877
```

### 人口合成与群体模拟

参数化造一座小镇 → 按群体模拟 → 验证这个近似能回答哪类问题。三步都可以**零 LLM 成本**跑通。
完整教程见 [群体模拟教程](./docs/GROUP_SIMULATION_TUTORIAL.md)。

```bash
# 预览一座 500 人的小镇（不写文件）
python -m gaworld.population --preset cn_county_town --size 500 --seed 42 --check

# 写出文件（状态 CSV + profile Markdown + 可复现 manifest）
python -m gaworld.population --size 500 --seed 42 --name my_town --out data/town

# 按群体模拟 7 天
python -m gaworld.group --size 500 --days 7 --no-llm

# 跑 L1–L4 验证门（分水岭层不通过时退出码为 1）
python -m gaworld.group.validate --size 100 --days 14 --network-coupling 0.7
```

生成的文件与仿真器现有格式完全一致，可以直接填进 `CONFIG["csv_path"]` / `CONFIG["md_path"]`。

## Dashboard

本地 dashboard 支持：

- 编辑运行参数
- 选择 LLM 路由
- 编辑 profile
- 启动 / 停止仿真
- 查看轨迹回放
- 查看单个智能体记忆
- 执行访谈
- 查看运行日志

dashboard 会把本地覆盖参数写入 `dashboard_config.json`。
这个文件会在运行时覆盖 `config.py` 中的基础配置。

### Agent Studio

Agent Studio 是面向单个智能体的可视化构建/查看器，可从控制台工具栏
（**Agent Studio ↗**）进入，或直接访问
`http://127.0.0.1:8766/site/dashboard/studio.html`。它把一个智能体拆成
七步，全部绑定 GAWorld 的真实种子模型：

1. **身份** — 姓名、性别、年龄、户籍、居住地与叙事 profile
2. **状态 · 性格** — 九个归一化 `[0,1]` 状态变量（`emotion`、`stress`、`econ_security`、`city_identity`、`policy_sensitivity`、`platform_dependence`、`risk_preference`、`voice_propensity`、`mobility_intent`）作为实时滑块 + 可编辑雷达
3. **能力 · 技能** — 全局技能库
4. **记忆** — 情节 / 习惯 / 意图 / 日程计数与记忆图谱
5. **社交 · 关系** — 仿真产出后展示真实 Dunbar 分层（`inner`/`close`/`acquaintance`/`weak`）与按亲密度排序的关系列表
6. **行为 · 目标** — 驱动行为的状态拨盘
7. **复核 · 部署** — 完整摘要、可选 LLM 采访、保存、以及“用此居民运行仿真”

改动写回真实种子文件：状态变量与身份写入状态 CSV
（`data/hangzhou_agents_state_init.csv`），并同步进 profile Markdown 的状态行；
叙事编辑写入 profile 块；“创建”会同时追加一行 CSV 与一个 profile 块。社交与
财务面板读取 `output/memory`、`output/economy` 的运行产物，未跑仿真时优雅降级。

后端 API（新增于 `dashboard_server.py`）：

| 方法 | 端点 | 作用 |
|------|------|------|
| GET | `/api/agents/{id}/state` | 身份 + 九个状态变量 |
| GET | `/api/agents/{id}/detail` | 聚合：状态、profile、记忆计数、财务、社交、技能 |
| GET | `/api/skills` | 全局技能库 |
| POST | `/api/agents/{id}/state` | 写状态/身份到 CSV（并同步 profile） |
| POST | `/api/agents` | 创建新智能体（CSV 行 + profile 块） |

### Population Studio

Population Studio 是 Agent Studio 的群体版：Agent Studio 造一个居民，Population Studio 造一座
小镇并按群体模拟它。可从控制台 tab（**人口与群体**）进入，或直接访问
`http://127.0.0.1:8766/site/dashboard/population.html`。五个步骤：

1. **选模板** —— preset、规模、种子；选中的预设会给出白话说明和「什么时候用它」，不再只留一个标识符
2. **人口结构** —— 年龄/家庭/就业/收入旋钮，**目标 vs 实际对照表**，年龄金字塔、洛伦兹曲线、度分布
3. **心理状态** —— 九维状态变量，群体均值雷达 + P25–P75 包络（群体是分布，只画均值多边形会误报）
4. **跑模拟** —— 天数、实体化预算、审计比例、网络耦合强度、**后端模型**；跑完显示每日群体简报与实测 LLM 成本
5. **检查结果** —— L1–L4 判定的白话解读，以及写出的人口文件（可直接点开）

**中英文双标**：所有指标都写成「压力 stress」这样的双语标注，标签由 schema 端点下发，
面板不再自己抄一份中文名。

**验证结论说人话**：先给一句话结论，再给「这次结果可以用来 / 不要用来」两栏清单
（由通过的层自动推出）——读的人真正要的是「这次跑出来的能不能拿去下结论」，
而不是 z 值本身。完整技术输出折叠在下面，没有丢。

**写出的文件可直接打开**：状态表 / 人物志 / 生成记录三个文件各带「在新标签打开」「下载」
和一段前几行预览。dashboard 本来就静态托管仓库根目录，所以仓库内的文件点开即可查看。

右侧常驻**参数体检**：不生成任何人、瞬时返回、参数冲突时直接指出该动哪个旋钮并给出可达区间。

后端 API（由 `dashboard_server.py` 转发到 `gaworld/apps/population_api.py`）：

| 方法 | 端点 | 用途 |
|------|------|------|
| GET | `/api/population/schema` | 旋钮契约——由后端下发，不在 JS 里再抄一份 |
| POST | `/api/population/preview` | 纯数学可行性预检 |
| POST | `/api/population/generate` | 启动生成 → `job_id` |
| GET | `/api/population/jobs/{id}` | 轮询进度 / 结果 |
| POST | `/api/population/group-run` | 对上一次生成的人口跑群体模拟 |
| POST | `/api/population/validate` | 跑 L1–L4 验证门 |

生成与模拟都是异步 job，500 人的生成不会把浏览器卡住。

### 外部系统观测台

前两个面板对着 agent，这个面板对着**世界本身**。控制台 tab（**外部系统**）或
`http://127.0.0.1:8766/site/dashboard/external.html`。三个子面板，各自左边观察、右边编辑：

- **货币系统** —— 周期阶段、通胀、失业、累计物价指数、企业/政府/银行三个部门池、
  货币守恒曲线与漂移、财富分布与基尼、全体日收支；可改整棵 `CONFIG["economy"]`，
  也可对**跑着的**仿真排一次干预
- **外部环境** —— `timeline.jsonl` 里最近若干天的自然/经济/政策/科技事件（带严重度与影响标签）；
  可改生成器参数、天气池，以及 `policy_events` 里排定的政策冲击
- **对外服务** —— 外部环境服务与分布式中继的即时连通性探测、LLM 路由、新闻缓存；
  模型清单只读（密钥不暴露），路由可改

**配置表单是从配置自身长出来的**：`economy` 一棵子树就有约 120 个叶子，面板按 JSON 形状
渲染控件，后端按现有配置的类型把补丁强制成形（`"0.09"` → `0.09`），不认识的键丢弃并回报。
约 150 个旋钮因此可编辑，加新旋钮不需要动面板代码。

**两种"改"是不同的东西**：配置写进 `dashboard_config.json`，**下一次**运行生效，适合做
对照实验；干预写进 `output/economy/interventions.json`，跑着的仿真在**下一个日边界**消费它。
干预不去写 `macro_state.json` —— 那是 run 的*产物*，仿真从配置重建宏观状态、从不回读它，
改它会看起来生效而实际无效。给部门池注资会同步移动守恒基准，所以每日审计把有意的注资记成
注资，而不是报成漏钱。

| 方法 | 端点 | 用途 |
|------|------|------|
| GET | `/api/external-systems/overview` | 三个子系统的 config + runtime |
| GET | `/api/external-systems/health` | 对外服务连通性探测 |
| GET/POST | `/api/external-systems/interventions` | 读 / 排队货币干预 |
| POST | `/api/external-systems/config` | 保存配置补丁（白名单子树 + 类型强制） |

完整教程见 [外部系统教程](./docs/EXTERNAL_SYSTEMS_TUTORIAL.md)。

### 平行世界实验台

前面几个面板看的是一个世界，这个面板同时看好几个。控制台「**平行世界**」页签，或直接打开
`http://127.0.0.1:8766/site/dashboard/worlds.html`。页面是**左边设计、右边观测**。

左边定义世界之间差什么：实验设置（天数、种子、参与居民、统一模型、并发度——
它们**故意**不放进单个世界，因为保持一致才能把差异归因到事件头上），然后每个世界一张卡片：
名字、是否作为对照基准、事件列表（第几天 / 几点 / 名称 / 描述）。三个模板（裁员冲击、
交通限行强度、安慰剂对照）一键填好表单。世界可以连事件一起复制，也可以带一个 `config`
补丁——那对应的是「政策」而不是「事件」。

右边读一次实验的结果：

- **分叉图** —— 线离主干的远近**就是**它的偏离程度；空心节点标出这段历史分叉的那一步，
  实心点标出事件位置
- **走向对比** —— 某个指标在各世界的人群均值走向，标出事件日、鼠标悬停读数；
  勾「只看与基准的差」会减去基准世界，让微小的效应也看得见
- **偏离基准的距离** —— 逐步偏离曲线与分叉阈值线
- **终局差异** 与 **谁被改变了** —— 逐指标的差异表，以及人群均值本会抹平的逐人表

图例上点掉某个世界，四张图会同时把它藏起来。每个世界都是一次完整仿真，因此都能跳到
逐帧回放页面。

| 方法 | 端点 | 用途 |
|------|------|------|
| GET | `/api/parallel-worlds/overview` | 默认值、provider、模板、历史实验、当前任务 |
| GET | `/api/parallel-worlds/experiment?root=…` | 某次实验的完整偏离报告 |
| GET | `/api/parallel-worlds/job` | 任务状态，运行中带每个世界的实时快照 |
| POST | `/api/parallel-worlds/preview` | 只校验 spec 并回显计划，不跑任何东西 |
| POST | `/api/parallel-worlds/start` / `/stop` | 分叉世界 / 停止 |

同一时刻只允许一个实验在跑——第二次 `start` 返回 `409`，而不是让机器被超额占用；
某个世界失败也不会拖垮其它世界：报告照常生成，失败原因（配额、连不上模型）原样显示并给出日志路径。

⚠️ 下结论前先跑一个**安慰剂世界**。认知由 LLM 驱动，配置完全相同的两个世界也不会跑出相同的历史；
安慰剂的偏离度就是噪声底噪，真实效应必须明显高过它。

完整教程见 [平行世界教程](./docs/PARALLEL_WORLDS_TUTORIAL.md)。

## 配置说明

基础配置位于 `config.py`。

重点字段包括：

- `agent_ids`：参与仿真的智能体 ID
- `sim_days`：仿真天数
- `seconds_per_day`：每个模拟日对应的现实秒数
- `time_step_minutes`：可选固定时间步长
- `time_grid_snap`：把每个 agent 的日程对齐到该网格（默认 `False`）。**只设 `time_step_minutes` 不够**——主时间线是网格与每个 agent 的 LLM 自拟 `HH:MM` 时间的**并集**，而后者没有对齐逻辑，于是 tick 数（进而 LLM 成本）随 agent 数超线性增长。开启对齐后 tick 数恒等于 `1440 / step`，与人口规模无关。默认关闭是因为它会改变日内时序
- `llm.providers`：模型 provider 列表
- `llm.routing.default`：默认 provider
- `llm.routing.tasks`：按任务覆盖 provider
- `memory_dir`、`log_dir`、`vector_db_path`：持久化路径
- `visualization.output_dir`：轨迹输出目录
- `economy`：个人财务配置（税率表、社保费率、恩格尔曲线、投资参数含 `market_correlation`、宏观周期、冲击事件、部门池 `sectors`、信贷 `credit`、支付路由 `routing`、熟人借贷 `friend_loans`）
- `interests`：兴趣爱好与技能成长配置（启用开关、成长项上限、日程插入倾向、进度持久化、日终遗忘衰减 `decay`、兴趣集演化 `evolution`）
- `dynamic_behavior`：动态行为系统配置（启用开关）
- `environment.local_physical` / `environment.anomaly` / `environment.replan` / `environment.spatial_preferences`：物理感知与反应式重规划的开关与阈值
- `skills`：可复用 Skill 库配置（全局目录、认知 / work brief 注入、单提示上限）
- `memory.skill_consolidation`：经验 → Skill 提炼配置（启用、周期、回看天数、最少 episode 数）
- `real_work`：真实工作任务系统（启用开关、市场、并发、超时、adapter）
- `intervention`：轻量推荐 / 曝光控制和干预评估配置
- `policy_events`：政策事件
- `distributed`：多机通信配置
- `plugins`：第三方插件声明（`[{"class": "pkg.mod:Class", "enabled": true}, ...]`）
- `pipeline.agent_step`：认知阶段顺序（省略某阶段即消融；可插入 `"module:function"` 自定义阶段）
- `controller.validators`：动作校验器开关（`location_exists` 默认开、`venue_open` 默认关）
- `extensions.hooks`：用户扩展钩子（`{事件名: ["module:function", ...]}`）

### 日志模式

运行时终端输出由环境变量 `GAWORLD_LOG_MODE` 控制，支持两个级别：

| 模式 | 设置方式 | 说明 |
|------|----------|------|
| `simple` | 默认 | 每个 tick 只输出标题、地点、动作、反思，约 4 行；LLM 调用详情不打印；重复 WARNING（如环境服务连接失败）60 秒内只显示一次 |
| `verbose` | `GAWORLD_LOG_MODE=verbose` | 输出完整字段（感知、计划、记忆召回、需求状态等），适合调试 |

```bash
# 默认 simple 模式
python generative_city_sim.py

# 切换为 verbose 模式
GAWORLD_LOG_MODE=verbose python generative_city_sim.py
```

simple 模式示例输出：

```
── [王思远 @ 10:41] 上午工作 ──
Loc: 货运站
Act: 推进最重要的一项任务
Refl: 感受：情绪有一点波动；教训：下次要更早判断状态和代价；后续倾向：接下来会更偏向省力或稳妥的做法
```

终端日志同时写入 `output/logs/run.log`（完整结构化格式，不受 `LOG_MODE` 影响）。
日志级别可通过 `GAWORLD_LOG_LEVEL`（默认 `INFO`）单独调整，如设为 `DEBUG` 可查看每次 LLM 调用详情。

### PolicySim 风格干预评估

`CONFIG["intervention"]` 默认开启一个确定性、无网络依赖的干预层。每个智能体 step 会从关系动态、
个性化内容和公共议题中构造小型 feed，经过本地曝光控制启发式处理后注入感知，并记录立场、毒性、
误信息、跨观点曝光和干预奖励指标。

该功能不执行 SFT/DPO 模型训练，也不会调用外部内容审核 API。

### 大五人格（OCEAN）系统

每位居民带一组大五人格 z 分数（开放性 O / 尽责性 C / 外向性 E / 宜人性 A / 神经质 N），
存放在 `agent["ext"]["big_five"]`，统一经 `gaworld/personality/traits.py` 读取——包外任何模块
都不直接索引这个字段。`traits_of` 取特质，`style_fit` 给出加性分量，`trait_modifier` 给出
有界乘子；`anchors.py` 则把 z 分数翻译成第二人称的中文行为描述句，供 LLM prompt 使用。
两个模块都只依赖标准库。

人格通过**三条互相独立、默认全开**的通道生效（`CONFIG["personality"]["channels"]`）：

| 通道 | 影响什么 |
|---|---|
| `rules` | `choose_action` 里的加性 `trait_style_fit` 分量；中断阈值、自发行为、社交偶遇概率、决策噪声、冲动绕过、财富驱动上的**有界乘子**；以及个人情绪基准点。确定性，零 token |
| `prompt` | 把人格锚句注入日程生成、活动调整、目标与新闻 prompt |
| `voice` | 锚句只进日记 prompt |

分成三条通道而不是一个总开关，是因为这个子系统的价值就在于能把「**决策**变了」和
「**文风**变了」分开归因：只留 `rules` 得到的是零 token 的确定性调制，只留 `prompt` / `voice`
则改变的仅仅是措辞。

**特质从哪里来**

`BigFivePlugin`（id `big_five`）只挂 `agents.built` 一个钩子，并在 `builtin_plugins()` 里
**注册在第一位**——人格是只读的前置层，先种进去，后面任何一个 `agents.built` 处理器都能
直接读到特质，不用再调顺序。有 `data/agents_big5.csv` 就读离线生成的值，没有则从一个带相关结构的
人口先验采样，因此新克隆的仓库也能直接跑。51 位杭州居民的分数由 `scripts/author_personality.py`
离线跑一次，方向是**反过来的**：先采样五维 z 分数，再据此改写 profile 里的行为描述。

老做法是从每个人 profile 里的「性格与情绪特征」段落反推分数，在这份语料上不成立——
那段文字中位数只有 20 字（是标签不是描述），而 `policy_sensitivity` / `platform_dependence` /
`risk_preference` / `voice_propensity` / `mobility_intent` 五个状态变量就写在同一份 profile 里、
紧挨着它；散文和数字是同一个作者对同一个人的两种写法，反推出来的开放性与 `mobility_intent`
相关达 0.90，共线性闸门在 O、C、E 三维上判不合格。

先采样再写，独立性就由采样器保证，而不是事后测出来的。只保留两条有文献依据的真实相关——
开放性 ↔ `risk_preference`、外向性 ↔ `voice_propensity`，都是 r≈0.3；C / A / N 独立采样。
只有明显偏离均值的维度（|z| ≥ 0.5，平均每人 3.0 个）会被写进文字。改写后每份 profile
多出一个 `人格与行为倾向` 字段（原来的「性格与情绪特征」原样保留），旧语料备份在
`data/hangzhou_profiles_with_names.v1.md`。跑完 51 人后：五个维度**全部 51/51 有分**
（此前 N 35/51、C 26、O 17、E 13、A 11），共线性最差调整 R² 从 0.77（不合格）降到 0.05，
人群标准差从 0.45–0.74 变成 1.00，`style_fit_amplitude = 0.30` 仍然通过幅度闸门。
`scripts/calibrate_big5.py` 没有删：它现在负责给外部导入的 agent（社交媒体导入那条路）打分，
并作为对照组——重新给新语料打分、与采样真值比对，量一量打分器有多准。

**提示词渲染的是哪一段**

profile 里存在 `人格与行为倾向` 时，`personality_line` 渲染这一段，**而不是**旧的
「性格与情绪特征」行——两者在 51 人里有 9 人互相矛盾，而且原本就并排出现在每条提示词的
相邻两行。`agent["personality"]` 本身没动，所以按关键词匹配它的四处子系统
（`dynamic.py` 的原型表与 `is_extrovert`、`finance.py` 的财富驱动、`_heuristic_schedule`
的睡眠提示）行为与之前完全一致。

**人格不漂移**

成年人的 OCEAN 每十年只变化约 0.1–0.2 个标准差，因此特质在一次运行内是常量——没有「今天更
外向了」这回事。随时间变的是状态变量，不是人格本身。

**幅度不是拍脑袋定的**

两个脚本作为合入门槛：`scripts/big5_effect_ceiling.py` 用真实的 `choose_action` 跑蒙特卡洛，
报告给定振幅下隐含的特质—行为相关；`scripts/big5_collinearity.py` 把每个维度对已有的五个
个体级状态变量做回归，某一维如果基本冗余就直接判失败。

**向后兼容**

没有特质的智能体、或被关掉的通道，行为与加人格之前**逐位一致**；这条契约由
`tests/test_personality_big_five.py`（36 个测试）覆盖。详见
[大五人格设计](./docs/proposals/2026-08-20-big-five-personality.md)与
[人格语料反向生成](./docs/proposals/2026-08-21-personality-corpus-rewrite.md)。

### 家庭系统

在这个特性之前，仿真里**所有居民事实上都是单身**：profile 文本几乎不写婚育，
`build_agent()` 没有家庭字段，社交模块里的 `spouse` / `child` 角色只存在于每个 agent
各自 LLM 生成的场外名单里——它的确定性兜底**从不生成配偶或子女**，而且 A 的配偶和 B 毫无关系。

现在家庭是一等实体，顺序是**先状态、后结构**：先按 `年龄段 × 性别` 抽婚姻状态，
再把匹配得上的居民在仿真内配成夫妻（配不上的补场外配偶），最后生成子女与同住长辈。
**户型是读数不是配额**——先按户型占比规划再填人，一旦户型旋钮和年龄金字塔打架就会有一方静默输掉。

| 层 | 做了什么 |
|---|---|
| 关系 | 家庭边写成社交模块认识的普通关系记录，kin 角色继承衰减率、义务基线与 Dunbar 保护；与家庭矛盾的 LLM 编造配偶会被剪掉 |
| 共居 | 同户居民共享同一个 home 节点——这是"家庭"和"两个地址相同的陌生人"的分界线 |
| 日程 | 接送幼儿园、陪写作业、照料同住老人、给父母打电话、回家吃晚饭，区分工作日/周末 |
| 账本 | 育儿与赡养开销按**收入**在挣钱的人之间分摊，走经济模块自己的支出通道（守恒）；伴侣互相补现金缺口（纯转移） |
| 事件 | 孩子发烧是**一件**事，同一个 tick 同时落到父母两人身上 |
| 情绪 | 同住家人之间情绪/压力互相靠拢；全家都平静时不产生漂移 |

`family.pairing.in_sim_pair_share`（默认 `0.6`）是**建模旋钮不是人口学事实**：
从一座千万人口的城市里抽几十个人，他们互为夫妻的真实概率约等于 0；
在仿真内配对是为了买到"家庭内互动"。调到 `0.0` 即得人口学纯净的跑法。

整体分布在 Dashboard「配置 → 家庭与户」里调；逐人精确指定在 Agent Studio 第 5 步
「社交 · 关系」的家庭编辑面板里做，写成 `data/family_overrides.json` 的覆盖项，
分配器在分配过程中读取，因此**跨运行生效**且优先于抽样。详见
[家庭系统设计](./docs/FAMILY_DESIGN.md)。

### 经济模块

`CONFIG["economy"]` 驱动一套基于中国经济体系的真实个人财务仿真。每个智能体拥有完整的财务画像，
通过四个相互关联的子系统随仿真时间演进：

**个税与五险一金**

每个智能体有一个基于职业和能力推导的税前月薪。模块计算个人社保缴纳（养老 8%、医疗 2%、失业
0.5%、住房公积金 8%），缴费基数下限 4,462 元、上限 36,000 元。个人所得税使用中国 7 档累进
税率表（3%–45%），月免征额 5,000 元，支持专项附加扣除配置。完整的 `税前 → 社保扣除 → 个税
→ 到手工资` 流水线在初始化时运行，并在月结时根据薪资变化自动重算。

**恩格尔系数消费模型**

消费预算不再使用固定随机区间，而是根据收入水平查询恩格尔系数曲线：低收入者食品支出占消费的
~48%、储蓄率 ~5%；高收入者食品占 ~15%、储蓄率 ~40%。八大消费类目（食品、住房、交通、服装、
休闲、教育、医疗、杂项）按收入弹性系数加权分配——必需品（食品 0.5、医疗 0.6）随收入增长慢，
奢侈品（休闲 1.5、服装 1.2）增长快。月预算在薪资变动时自动重新计算。

**多账户体系与投资理财（含共同市场因子）**

每个智能体持有四个账户：活期、储蓄、投资和公积金。风险偏好映射到三种投资组合——保守型
（定期存款 70% / 基金 25% / 股票 5%）、稳健型（40/40/20）、激进型（15/35/50）。月度收益
= 全市场共同因子（每月抽取一次、所有智能体共享，市场级暴涨暴跌会同时波及所有人）+ 个体特质
噪声，系统性占比由 `investment.market_correlation`（默认 0.7）控制。超出缓冲阈值的活期
余额自动转入储蓄和投资账户。

**货币守恒与部门池**

所有资金流动均有对手方——企业池（发工资、收消费）、政府池（收税与社保、支付医保报销）、
银行池（结算投资盈亏、发放信贷）。税与社保按**实收**工资在月结时真实代扣。初始化后系统货币
总量守恒到分，每日审计写入 `output/economy/conservation_audit.csv`（|drift| ≤ 0.01 元），
GAWorld-Bench Track A 将守恒作为硬门槛。部门池允许为负（企业池为负即家庭部门净储蓄的镜像）。

**现金约束、信贷与熟人借贷**

支出按 活期 → 储蓄提取 → 银行信用额度（默认 2 倍月净薪、年息 18%、月度复利、盈余自动还款）
→ 截断 的顺序融资；流动性低于 1 个月开销时按收入弹性削减非必需消费。消费被截断的智能体进入
财务困境状态：压力上升，日终可按亲密度×信任度向社交网络上有盈余的好友无息借款，月结时优先
偿还熟人债务。

**支付路由到智能体**

本地消费的一部分（`routing.merchant_labor_share`，默认 35%）经企业池转付给工作地点匹配的
服务业/商贸智能体；房租路由给房东类智能体。货币因此在智能体之间循环，财富分布得以内生涌现。

**宏观经济周期与冲击事件**

仿真级别维护一个四阶段宏观周期——扩张、峰值、收缩、谷底——每个阶段持续 60–180 天。不同阶段
对收入、支出、裁员风险和加薪概率施加不同倍率。行业景气度（科技、金融、医疗、教育、服务、贸易）
独立波动。通胀按日累积，侵蚀购买力。个体层面有随机经济冲击事件：裁员（收入削减 50–85% 且月度
税基同步下调，恢复期 30–90 天）、涨薪/晋升、大病医疗（社保报销 50–85%，由政府池支付）、年终奖
（第13个月工资，奖金税入政府池）。经济模块使用独立随机流（由 `random_seed` 派生），其它模块
增删随机调用不影响经济轨迹的可复现性。

经济模块的输出包括 `output/economy/daily_ledger.csv`（含 `debt` 列）、每智能体账本、财富快照、
`macro_state.json`、`sectors.json` 和 `conservation_audit.csv`。

### 位置系统

`city_map_system.py` 提供了一套真实的空间层，用于智能体的移动决策。系统使用基于类别的
空间匹配来解析智能体在任意活动下应前往的地点，而不依赖硬编码的地点名称。

**出行成本计算**

每种交通方式都有基于中国城市公共交通的费率结构：公交固定票价（2 元）、地铁按距离计费
（起步 2 元 + 超过 4 公里后每公里 0.45 元）、出租车起步价加里程费（起步 13 元 + 超过
3 公里后每公里 2.5 元）、私家车按油耗和停车费计算。高峰时段检测（7:00–9:00、
17:00–19:00）对出行时间施加 1.45 倍乘数，出租车加收 1.3 倍附加费。出行成本从智能体
经济模块的交通支出类目中扣除。

**天气感知的出行方式选择**

当存在天气状况时，交通方式选择器会使用天气调整权重重新评估。在雨雪天气下，步行、自行车、
电动车等露天出行方式受到大幅惩罚，智能体会转向公交、地铁、出租车等有遮蔽的替代方式。

**基于类别的地点解析**

活动和职业通过关键词词典映射到地点类别（教育、医疗、商业、休闲、交通等）。空间解析器
从智能体当前位置出发，查找最近的匹配节点，并结合时间段偏好、智能体画像和习惯偏好进行
加权选择。这替代了之前硬编码地点名称列表的方式，使系统可以适配任意城市地图。

**通勤记忆**

智能体追踪常去地点、偏好交通方式和通勤路线统计（平均出行时间、出行次数）。这些数据
随仿真天数积累，并反馈到位置决策中——智能体会形成习惯性的出行模式，偏好熟悉的地点。

**区域价格水平**

不同区域类别带有价格水平乘数（商业区 1.35 倍、工业区 0.80 倍、教育区 0.85 倍等），
影响智能体在该区域内的消费行为。

### 兴趣爱好与技能成长系统

`gaworld/interests.py` 会根据智能体的职业、性格、日常生活和价值观，为每个智能体派生并持久化
`growth_profile`。成长画像包含兴趣爱好和计划发展的技能，每项记录名称、类别、动机、当前水平、优先级、
每周目标分钟数、偏好时段、可放入日程的活动模板、是否关联职业发展、社交属性、累计练习时间和连续天数。

主仿真会在四个环节使用这份画像：

- 生成基础日程和今日日程时，低承诺的“个人时间”可以自然替换为阅读、运动、创作、专业学习或表达练习等具体活动；
- 每日意图可以包含 `growth_focus`，让今天要发展的兴趣或技能进入计划、反思和次日整合；
- 动作选择时，匹配兴趣/技能的动作会获得额外权重，但不会硬性覆盖工作、上课、医疗、睡眠等高承诺活动；
- 每个 episode 会记录 `growth_matches` 和 `growth_progress`，并更新成长项的水平、累计分钟、最近练习日期和 streak。

练习收益遵循幂律学习曲线——水平越高、单次涨幅越小；连续不断的练习会带来动量加成。水平上穿
0.35 / 0.60 / 0.85 时会向 `growth_progress` 写入里程碑事件（入门/熟练/精通），日记和反思可以引用这些
可感知的进步。每个成长项还带有一个按 Hidi & Renninger 模型派生的发展阶段
（触发期 → 维持期 → 浮现期 → 成熟期），会展示在 prompt 上下文中，让智能体的自我认知随发展变化。

日终时成长画像本身也会演化（配置：`CONFIG["interests"]["decay"]` 与 `CONFIG["interests"]["evolution"]`）：
超过宽限期未练习的条目水平下降——保持率随累计练习量提高，且衰减阶段感知（脆弱的触发期条目掉得更快，
成熟期条目几乎不掉）——断练会打断 streak。停滞的浅尝辄止条目最终会被放下，同时可以从当日社交对象处
习得新兴趣（兴趣传染），因此兴趣集会持续周转，而不是在 bootstrap 后一成不变。以上全部为纯规则实现，
不新增 LLM 调用，落盘 schema 不变。

兴趣技能是运行时状态，不会写回原始 CSV 或 Markdown profile。全局推导缓存位于
`output/memory/growth_profiles.json`，单智能体进度位于 `output/memory/agent_<id>_growth.json`。

### Skill 系统（可复用技能库）

与「兴趣爱好与技能成长」并行的是 `gaworld/skills/`：一种可复用的小技能体系，思路与 Claude
Code 的 Skill 相近。每条 Skill 是一个 Markdown 文件（带 YAML frontmatter，含 `name` /
`description` / `triggers` / 正文），有两种来源：

- **全局库** `data/skills/*.md`：手写、所有 agent 都能挂载；
- **私有库** `output/memory/agent_<id>_skills/*.md`：agent 由自己的最近经历**自动总结**得到，
  默认关闭，通过 `CONFIG["memory"]["skill_consolidation"]["enabled"] = True` 打开，
  在 `run_daily_memory_lifecycle` 里按 `every_days` 周期触发。

运行时 Skill 会自动注入到 `perception` 提示词与 work brief 的 `【可用技能】` 块里，
影响 agent 的认知与工作产物。给某个 agent 挂载全局 Skill：

```python
from gaworld.skills import SkillRegistry
SkillRegistry().attach_to_agent(agent, "poster-grid")
```

完整设计与 API 见 [`docs/SKILL_SYSTEM.md`](docs/SKILL_SYSTEM.md)。

### 动态行为系统

`dynamic_behavior.py` 通过注入上下文感知的日程变更，让智能体的每日行程更接近真实人类。该系统
通过 `CONFIG["dynamic_behavior"]["enabled"]` 开关控制，每个智能体每个时间步执行一次，在
LLM 调用之前完成决策。

**承诺度感知的中断机制**

每种活动都有一个承诺度等级（考试/手术 0.95、工作 0.70、刷手机 0.15）。中断候选必须克服承诺度
壁垒和性格阈值（自控力、风险偏好）才能改变已安排的活动。即使净优先级为正的中断也会经过随机接受
门控，避免行为过于机械。

**情绪驱动的即兴行为**

智能体的情绪状态被分类为六种情绪类别（开心、压力、疲倦、无聊、焦虑、孤独）。每种情绪映射到一组
场景化的即兴行为池——压力大的智能体可能想独自散步，无聊的智能体可能拿起手机刷社交媒体。时段过滤
器阻止不合理的行为（深夜不会想去购物），性格缩放调节概率（外向型有更多社交冲动）。

**社交偶遇链**

当多个智能体处于同一地点时，系统根据关系亲密度和社交需求计算偶遇概率。亲密好友可能互相邀约吃饭
（感知午餐/晚餐时段），普通熟人交换简短寒暄，陌生人之间可能发生行为传染——跟着别人排队买奶茶、
围观街头事件。

**环境事件连锁反应**

天气、交通、商业、新闻和紧急事件被分类并转换为中断候选，优先级根据性格差异化调整（谨慎型对天气
+30% 敏感度，好奇型对商业活动 +40% 兴趣）。主事件可以触发连锁反应：下雨→打车排队+路面湿滑，
暴风→交通延误+快递延迟，交通拥堵→可能迟到+心情变差。连锁事件按概率触发并累积情绪效果。

**需求中断**

生理需求（饥饿、疲劳）和任务压力生成中断候选。饥饿中断在用餐时段获得额外加成。低能量触发休息
冲动。高时间压力推动智能体处理紧急事务。

**日程插入与恢复**

当中断胜出时，系统可以将新活动插入到日程中并支持恢复——被中断的活动在插入活动结束后自动恢复，
前提是日程中有足够的时间空隙。

### 物理环境感知与反应式重规划

`gaworld/world/local_physical.py` 与 `gaworld/memory/spatial_preferences.py` 把城市地图里早已
定义却从未被调用的节点级 `occupancy`（占用）与 `is_open`（营业）状态接入认知循环，让智能体真正
感知并反应**当下身边**的物理环境。该系统**全部配置门控、纯规则（无新增 LLM 调用）、向后兼容**——
缺数据时每一层自动空转。所有开关位于 `CONFIG["environment"]`。

**局部物理感知（P0）**

每个 tick 从"谁在哪"重算节点占用，并写入仿真时间使营业判断生效。每个智能体感知前生成当前位置
快照（拥挤度 / 是否营业 / 当地天气 / 异常标记），可选地以"身边的物理环境"片段注入感知上下文。

**结构化事件反应（P1）**

动态行为分类器优先读结构化信号（`type` / `topic` / `impact_tags`）而非关键词猜测，并把
`impact_tags`（mobility、stress、public_service…）作为中断优先级加成。局部物理状态也转为中断
候选：拥挤→"换个不那么挤的地方"，关门→"改去其他开门的地方"（不可恢复，必须换地点）。

**异常作为一等公民（P2）**

`env/system.py` 为每个事件打 `anomaly` / `anomaly_score`，代表对常态的偏离——日常天气与小波动
不算异常，极端 / 突发 / 应急 / 高严重度事件才算。异常会提升中断优先级、可强制不可恢复反应、并有
更强的情绪影响。局部"人流骤增"（占用率高且较上一 tick 跳变大）会涌现为 `crowd_anomaly` 中断。

**当日重规划（P3）**

`sim/_schedule.py` 新增 `replan_affected_interval`，只重排受影响的连续区间（改址 / 顺延 / 丢弃），
窗口外不动。当胜出中断为持续性异常（不可恢复的物理 / 应急反应）时，把窗口内被打断的后续活动顺延
到窗口之后，而非只修补当前单步。

**结构化空间学习（P4）**

`spatial_preferences.py` 把地点绑定的异常经历（拥挤、关门，不含全城宏观异常）累积为该地点的规避分，
按时段加权、按时间衰减。规避分超阈值后，`redirect_for_aversion` 把智能体引导到同类、规避更低的
替代地点。偏好按 agent 持久化到 `output/memory/agent_<id>_env_preferences.json`（仅 `stateful=True`
时），跨运行保留。

配置块（`gaworld/settings/environment.py`）：`local_physical`、`anomaly`、`replan`、
`spatial_preferences`。把任一块的 `enabled` 设为 `False` 即可回退该层，四个开关相互独立。完整设计
与参数表见 [`docs/physical_env_perception_changelog.md`](docs/physical_env_perception_changelog.md)。

### 真实工作任务系统

`gaworld/work/` 让居民根据职业 / 技能 / 兴趣去做**真实**的工作——产出 HTML 页面、Python 脚本
（可带 pytest）、Markdown 文章、教案、研究笔记——并能在一个 mock 工作机会市场上浏览、接单、结算。
职业能力由 LLM 按职业派生并缓存；任务在后台 `WorkerPool` 上运行；产物落在
`output/work/agent_<id>/<task_id>/`。

通过 `CONFIG["real_work"]["enabled"]` 配置门控，并与兴趣 / 技能成长系统、Skill 系统联动（计划发展
的技能拓宽能力匹配面；相关 Skill 自动追加进每条 work brief）。详见
[`docs/REAL_WORK_USAGE.md`](docs/REAL_WORK_USAGE.md) 与 [`docs/REAL_WORK_DESIGN.md`](docs/REAL_WORK_DESIGN.md)。

### LLM 后端

项目支持：

- `ollama`
- OpenAI 兼容接口
- Anthropic 兼容接口

对于中国区 Minimax 的 Anthropic 兼容接口，当前支持：

- `ANTHROPIC_BASE_URL=https://api.minimaxi.com/anthropic`
- `MINIMAX_API_KEY` 或 `ANTHROPIC_AUTH_TOKEN`

## 输出文件

主要输出位于 `output/`，包括：

- `output/logs/agent_<id>.log`
- `output/memory/agent_<id>.json`
- `output/memory/agent_<id>_episodes.jsonl`
- `output/memory/agent_<id>_growth.json`
- `output/memory/growth_profiles.json`
- `output/memory/agent_<id>_env_preferences.json`
- `output/memory/agent_<id>_skills/*.md`
- `output/memory/vector_db.sqlite`
- `output/economy/daily_ledger.csv`、`wealth_snapshot.csv`、`macro_state.json`
- `output/economy/agents/agent_<id>_ledger.csv`、`agent_<id>_snapshot.json`
- `output/environment/timeline.jsonl`
- `output/intervention/intervention_metrics.csv`
- `output/work/capabilities.json`、`queue.jsonl`、`market.jsonl`、`agent_<id>/<task_id>/`
- `output/visualization/simulation_trace.json`
- `output/visualization/latest_frame.json`
- `output/network/`
- `output/state/`

## 说明

- `dashboard_config.json` 会覆盖 `config.py`
- `stateful` 模式下会复用之前运行留下的记忆和日程
- 如果改了记忆 schema 相关配置，需要先执行 `reset`
- 如果运行时模型路由和预期不一致，同时检查 `config.py` 和 `dashboard_config.json`

## 更多文档

- [English README](./README.md)
- [完整教程（含全部特性）](./docs/TUTORIAL.v2.md)
- [快速上手教程](./docs/TUTORIAL.md)
- [插件作者指南](./docs/PLUGIN_AUTHORING.md)（不改核心扩展 GAWorld）
- [微内核架构设计](./docs/proposals/2026-07-11-microkernel-plugin-architecture.md)
- [Skill 系统设计与使用](./docs/SKILL_SYSTEM.md)
- [真实工作系统 — 使用](./docs/REAL_WORK_USAGE.md) · [设计](./docs/REAL_WORK_DESIGN.md)
- [物理环境感知与反应式重规划](./docs/physical_env_perception_changelog.md)
- [社交网络 — 设计](./docs/SOCIAL_NETWORK_DESIGN.md) · [教程](./docs/SOCIAL_NETWORK_TUTORIAL.md)
- [家庭系统 — 设计](./docs/FAMILY_DESIGN.md)（婚姻抽样、共居、家庭日程与账目、覆盖层与工作台编辑面板）
- [群体模拟 — 教程](./docs/GROUP_SIMULATION_TUTORIAL.md) · [设计](./docs/GROUP_AGENT_DESIGN.md)（人口合成、cohort 模式、L1–L4 验证门）
- [外部系统 — 教程](./docs/EXTERNAL_SYSTEMS_TUTORIAL.md)（货币系统、外部环境、对外服务的观察与编辑，以及运行时干预）
- [平行世界 — 教程](./docs/PARALLEL_WORLDS_TUTORIAL.md)（多分支反事实实验：设计实验、读分叉与偏离图、剂量反应设计，以及为什么要先跑安慰剂世界）
- [大五人格（OCEAN）— 设计](./docs/proposals/2026-08-20-big-five-personality.md)（三条独立通道、效应量与共线性两道合入门、离线特质标定）
- [项目结构](./docs/PROJECT_STRUCTURE.md)
- [仓库规范](./AGENTS.md)
- [更新日志](./CHANGELOG.md)
