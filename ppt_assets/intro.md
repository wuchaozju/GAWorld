# GAWorld 项目介绍

**生成式城市社会仿真 · Generative Agent Simulation for Urban Social Behavior**
v2026.09 · 单机可复现 · 中英双语控制台

---

## 摘要

GAWorld 是一个开源的城市级多智能体仿真框架。它把人物画像、长期记忆、社会影响、环境扰动、政策冲击、闭环经济、地图移动和 LLM 决策过程整合到一条可回放、可对照的流水线里。同一群人在同一颗随机种子下，只换一件事——一场暴雨、一笔补贴、一条新地铁线——就能把"如果当初"变成可量化的对照实验。

13 个内置控制台视图覆盖从建模、运行到对照实验的完整链路。所有仿真、数据和面板都在本地运行，不依赖外部 SaaS。

---

## 第 1 页 · 项目是什么、不是什么

GAWorld 想回答的问题很窄：**"如果把这件事加到这座城市里，居民会怎么变？"** 它不做通用 agent demo，不做单角色角色扮演，不接 GPTs。它是一台城市的飞行模拟器。

四个判断标准决定它是不是 GAWorld 的目标场景：

1. 关心**一群人**在**一个地理环境**里的**跨天**变化
2. 同一批居民要在不同事件或政策下**反复**运行
3. 行为要能**回溯**到某条记忆、某条规则、某次外界扰动
4. 读者希望看到**实证**：分布、网络、因果，不是叙事

符合这四条，它就是 GAWorld 的主场。

---

## 第 2 页 · 微内核与十二阶段认知管线

整个运行时是一颗 society-centric 微内核。`gaworld/kernel/` 里只放通用部件：`Clock` 时钟、`EventBus` 事件总线（observe / collect / filter 三种钩子语义）、`PluginRegistry` 插件注册表、`Controller`（动作校验 + 可审计运行时干预）、`Recorder` 统一事件流、`SimContext` 运行时上下文。零领域逻辑。

每个智能体的每日 tick 跑一条十二阶段的流水线：

```
prepare → perceive → interrupts → plan → adjust_activity
       → move → select_action → reflect → update_state
       → broadcast → memorize → record
```

阶段名、顺序、每个阶段的插件都可以在 `CONFIG["pipeline"]` 里改。消融实验替换一个阶段只是一行配置。

九个内置子系统都以插件形式注册：干预、技能、兴趣成长、人生事件、经济、物理感知、真实工作、动态行为、空间偏好。第三方插件走 `CONFIG["plugins"]` 或 pip entry points，核心代码不用动。

<media src="../ppt_assets/screenshots/01_hero.png" />

---

## 第 3 页 · 把一个居民装进仿真

GAWorld 用一个七步 Agent Studio 把一个居民从头搭到位：身份、9 个 [0,1] 状态变量（可编辑雷达图）、技能、三层记忆、Dunbar 社交圈、行为转盘、复核与发布。每一步都回写到状态 CSV 与 profile Markdown。改 9 版的居民直接进入下一轮仿真。

<media src="../ppt_assets/screenshots/04_dashboard_studio.png" />

每位居民自带 OCEAN 大五人格（O / C / E / A / N z 分）。特质通过三条独立可关的通道影响行为：`rules`（确定性、零 token，加性风格分量 + 行为阈值倍率）、`prompt`（锚句注入日程/活动/目标/新闻提示词）、`voice`（仅注入日记）。通道分开是为了让实验区分"决策变了"和"文风变了"。特质一次性采样，成人 OCEAN 每十年只漂移 0.1–0.2 SD，所以仿真期不变。

家庭层级包括婚姻状态（按年龄段 × 性别采样）、共享家庭节点、子女与同住老人、家庭类型（独居 / 合租 / 与父母同住 / 同居 / 夫妻 / 核心家庭 / 单亲 / 多代同堂）。家庭类型是从配对结果里**读出来**的，不是预设配额。家庭反过来驱动日程（接送孩子、回家吃饭）、夜课、看护记账（按收入比例分摊，伴侣互相补现金缺口——钱守恒）、共享家庭事件（一个孩子发烧，两个父母同一 tick 撞上）和家庭内部情绪传染。

---

## 第 4 页 · 城市、地图、现实

城市从地名创建。`python -m gaworld.city create "绍兴柯桥" --size 200` 会去拉真实的 OSM 路网作为底图。没有网络的离线场景下退回到程序化生成。

每个城市自带一份本地知识库：一份研究过的行业 / 劳动力画像 + 一份滚动的本地新闻缓存。它影响居民四个方面：认知提示词、技能成长选择、行业薪酬、长期记忆。城市大力发展旅游业，居民就更可能学酒店管理，相应的服务岗位薪酬也会更高。

地图驱动空间感知：每个节点的拥挤度 / 营业时间、异常检测、当日重规划、学到的"绕开"地点记忆。仿真甚至区分了**离开本市**的行为：出差按职业（销售、外贸、咨询比图书管理员出差多得多）在工作日触发；探亲按社会义务与距上次联系的天数触发；旅行按周末 + 流动性储蓄 + 开放性 + 累积压力触发。目的地是真实距离，省中心表 + 地图中心节点的 haversine，按距离切换火车 / 飞机。

<media src="../ppt_assets/screenshots/09_dashboard_city.png" />

---

## 第 5 页 · 闭环经济与真实工作

经济模块守恒。钱在部门池（企业 / 政府 / 银行）之间流动，居民、部门、池构成一个守恒系统。真实个税 + 社保代扣；现金约束的消费 + 信用额度；普通市场因子投资；居民之间支付路由 + 朋友借贷；宏观周期。

每天的守恒审计把"漏的钱"和"注入的钱"分开记账。外部系统面板上可以往运行中的仿真注入一笔货币扰动——它会被审计识别为 deliberate injection 而不是漏账。

<media src="../ppt_assets/screenshots/06_dashboard_external.png" />

每位在岗居民会被分配到一份真实的工作任务。他们浏览一份模拟职位市场，产出真实工件：HTML、Python、文章、教案、研究笔记。任务和岗位、技能匹配。每件工件落在 `output/work/<city>/<agent_id>/` 下，可读、可审、可复用。

---

## 第 6 页 · 仿真可回放

仿真面板把正在发生的事逐帧推出来：地图上的居民位置、当前活动、记忆写入、对话、外部事件触发。所有阶段都用真实时钟跑，但有 fast-forward 模式：一日一简报，跳过日内 tick 循环，配 `--sim-days 600` 跑两年；多年度还有 `--sim-months 24` 和 `--time-unit month`，每月一简报。

<media src="../ppt_assets/screenshots/13_simviz.png" />

回放文件存在 `output/environment/timeline.jsonl` 里，每行一个事件，按 agent 拆分的 `output/logs/agent_<id>.log` 里是动作级日志。state CSV 在 `output/state/agent_state_history.csv`——这是后续所有实证分析的事实底。

---

## 第 7 页 · 对照实验与平行世界

同一群居民、同一个种子、同一个时间窗、同一个模型，只换一件事。每个世界各自跑在隔离的 memory / state / log 树里。世界里可以注入事件列表，也可以注入配置补丁（政策变种而不只是事件变种）。

报告在每一步上测每个世界与基线的距离——它回答的是"两个历史从**哪一步**开始分叉"，而不是只看终点差多远，并指出政策真正落到哪些个人头上。`compare-event` 旧实验不用重写，自动适配到同一个视图里。

<media src="../ppt_assets/screenshots/11_dashboard_worlds.png" />

群体仿真把居民按群切分，每群一日一个 LLM 调用，然后在预算范围内把个体物质化为焦点 / 事件 / 长尾 / 审计四档。一个 20 人日物质化预算的群组比单人仿真便宜约 25 倍。L1–L4 验证门（分布距离、网络协同、长尾保持、政策因果响应）以参照层自身的跨种子噪声为阈值，CI 可直接用：任意一层不达标就让 CI 红。

---

## 第 8 页 · 群体采访与可问的居民

群体采访是对一群居民同时问一份问卷——单人居民和群组 agent 都行，**跨城市**同跑一场。题型可选（开放 / 单选 / 是非），选择 / 是非题的答案会被解析回选项标签并汇总成计数，而不是留在散文里。

<media src="../ppt_assets/screenshots/07_dashboard_survey.png" />

每道题可附**图片**或**URL**。图片在 OpenAI / Anthropic / Ollama 多模态可用时按真视觉内容块喂入，模型不支持视觉时降级成 caption 并明确标注。URL 由父进程取一次，所有受访者读同一份抓取。

受访者一题一答，之前的答案会被回放进下一题提示词里。会话可加追问轮次，追问连续性只在会话记录里，**不写进居民记忆**——调查不会污染被调查的总体。

报告自带：按选项计数（按受访者、按所代表的人数两层都报）、按城市 / 年龄段 / 性别 / 户口 / 区县的交叉表（只在确实能切分的轴上画）、一个自包含的 Markdown 文档（每条答复原文 + 哪些没跑通）。每城一个子进程，并行。

---

## 第 9 页 · 实证：跑过的事

仓库里有 17+ 个完整仿真实验落盘，state CSV 可读、可复算：

- **情绪传染对照**（EXP-EMO-001）：4 个处理（control / positive-bias / negative-bias / 全随机），Day 1 情绪曲线
- **ABM 校验**（EXP-VAL-001）：和参考基准对照的校准误差
- **群体模式 L1–L4 验证门**：分布、网络、长尾、政策响应
- **平行世界分叉点分析**：基线 vs 政策变种的逐步距离
- **state 时序图**：`output/state/agent_state_over_time.png` 直接画出居民状态曲线

<media src="../ppt_assets/screenshots/14_state_timeseries.png" />

实证的诚实标注写在 `benchmark/report.md` 里：哪些结果是代理 / 替代模型、哪些是真 LLM + GPU 跑出来的、哪些需要 V2 / V3 重跑才达到论文级。

---

## 第 10 页 · 上手与开源

依赖：

```bash
pip install -r requirements.txt
```

跑一次仿真（杭州 842 居民，5 天）：

```bash
python dashboard_server.py --port 8766 &      # 起控制台
python generative_city_sim.py run             # 命令行跑仿真
```

造一座新城市：

```bash
python -m gaworld.city create "绍兴柯桥" --size 200        # 真 OSM
python -m gaworld.city create "柳溪村" --offline --scale tiny   # 离线
```

采访一个居民：

```bash
python generative_city_sim.py interview --agent-id 31 \
  --question "如果下周小区停电两天你怎么办？"
```

代码组织（节选）：

| 路径 | 内容 |
| --- | --- |
| `gaworld/kernel/` | 微内核：时钟、总线、注册表、控制器、记录器、上下文 |
| `gaworld/sim/pipeline.py` | 12 阶段认知管线 |
| `gaworld/plugins/` | 9 个内置插件装配点 |
| `gaworld/personal/` | 9 状态 + OCEAN + 三层记忆 + Dunbar |
| `gaworld/family/` | 家庭 / 户 / 婚姻 / 看护 / 共享事件 |
| `gaworld/economy/` | 闭环经济、夜审计、宏观周期 |
| `gaworld/work/` | 真实工作市场 + 工件产出 |
| `gaworld/travel/` | 出差 / 探亲 / 旅行 |
| `gaworld/infosources/` | 新闻 / 社交 / 专业站 → 每人信息食谱 |
| `gaworld/interview/` | 群体采访（按城市分进程） |
| `site/` | 控制台前端：13 个视图 |

仓库：`/Users/cw/dev/GAWorld`
文档索引：`docs/`（CITY_TUTORIAL / GROUP_INTERVIEW_TUTORIAL / PERSONA_DISTILL_TUTORIAL / PLUGIN_AUTHORING）

---

## 致评审

GAWorld 已经在本机上跑通 842 居民 / 600 天 / 4 处理对照实验，state CSV、内存账本、回放轨迹、群体采访报告全套产出。它不是 demo，而是一台可以反复烧的样本机。

下一步要写论文而不是再加 feature：守恒审计的政策响应梯度、平行世界分叉点的统计推断、群体模式的 L1–L4 验证门阈值。L1 已经写进 CI，L2–L4 还需要 V2 真模型 + GPU 才能拿到论文级数据。当前 17 个实验里，凡是标 proxy / surrogate 的都在 `benchmark/report.md` 里注明。