# 附录 A　术语对照表（中英双标）

> 本附录收录全书涉及的关键术语,按主题分类。每个术语给出中文、英文、缩写和一句话解释。读者写论文时,可以参考本表选用合适的术语。

---

## A.1　方法论基础术语

| 中文 | 英文 | 缩写 | 解释 |
|---|---|---|---|
| 多智能体仿真 | Multi-Agent Simulation | MAS | 由多个具有行为规则的智能体组成的仿真 |
| 基于智能体的建模 | 智能体-Based Modeling | ABM | 用智能体构建模型的范式 |
| 生成性研究 | Generative Research | — | 用人工社会重演机制的方法论 |
| 涌现 | Emergence | — | 宏观模式从微观规则中非线性地产生 |
| 微观—宏观链接 | Micro-Macro Link | — | 微观行为与宏观模式的相互影响 |
| 计算社会科学 | Computational Social Science | CSS | 用计算方法研究社会科学的子学科 |
| 解释性鸿沟 | Explanatory Gap | — | 宏观现象与微观机制之间的解释差距 |
| 卢卡斯批判 | Lucas Critique | — | 政策评估不能只看历史数据的论断 |
| 准实验 | Quasi-Experiment | — | 用自然实验替代真实实验的方法 |
| 双重差分 | Difference-in-Differences | DID | 准实验方法之一 |
| 断点回归 | Regression Discontinuity | RDD | 准实验方法之一 |
| 合成控制法 | Synthetic Control | — | 准实验方法之一 |

## A.2　仿真的核心组件

| 中文 | 英文 | 缩写 | 解释 |
|---|---|---|---|
| 智能体 | 智能体 | — | 仿真中的"假人",有身份、状态、决策 |
| 身份 | Identity | — | 智能体不变的数据(姓名、年龄、职业等) |
| 状态 | State | — | 智能体可变的数据(心情、现金、关系等) |
| 决策 | Decision | — | 智能体从状态到行动的映射 |
| 行动 | Action | — | 智能体实际做的事 |
| 记忆 | Memory | — | 智能体保留的历史信息 |
| 情景记忆 | Episodic Memory | — | 具体事件的记忆 |
| 长期记忆 | Long-term Memory | — | 抽象总结的记忆 |
| 关系记忆 | Relational Memory | — | 对具体人物的印象 |
| 环境 | Environment | — | 智能体生活的世界 |
| 事件 | Event | — | 改变仿真状态的一次性触发 |
| 政策事件 | Policy Event | — | 政府/政策类事件 |
| 自然事件 | Natural Event | — | 地震、洪水等自然灾害 |
| 经济事件 | Economic Event | — | 通胀、衰退等经济变化 |
| 技术事件 | Technology Event | — | 平台变化、新技术等 |
| 社会网络 | Social Network | — | 智能体之间的关系图 |
| 关系 | Relation / Tie | — | 一条具体的社会连接 |
| 节点 | Node / Vertex | — | 网络中的智能体 |
| 边 | Edge / Link | — | 网络中的关系 |
| 度 | Degree | — | 一个节点的边数 |
| 聚类系数 | Clustering Coefficient | — | 朋友的朋友也是朋友的概率 |
| 路径长度 | Path Length | — | 两个节点间的最短路径 |
| 弱连接 | Weak Tie | — | 强度低但数量多的关系 |
| 强连接 | Strong Tie | — | 强度高但数量少的关系 |
| 小世界 | Small World | — | 平均路径短、聚类高的网络 |
| 无标度 | Scale-free | — | 度分布服从幂律的网络 |
| Dunbar 数 | Dunbar's Number | — | 人类能维持稳定关系的上限(约 150) |

## A.3　行为策略与认知模型

| 中文 | 英文 | 缩写 | 解释 |
|---|---|---|---|
| 规则决策 | Rule-based Decision | — | IF-THEN 形式的决策 |
| 效用最大化 | Utility Maximization | — | 经济学理性决策 |
| 启发式 | Heuristic | — | 经验法则决策 |
| 累积前景理论 | Cumulative Prospect Theory | CPT | 行为经济学决策模型 |
| 有限理性 | Bounded Rationality | — | Simon 提出的非完全理性 |
| 大五人格 | Big Five Personality | OCEAN | O 开放性、C 尽责性、E 外向性、A 宜人性、N 神经质 |
| 开放性 | Openness | O | 好奇心、想象力 |
| 尽责性 | Conscientiousness | C | 自律、组织性 |
| 外向性 | Extraversion | E | 社交活跃度 |
| 宜人性 | Agreeableness | A | 合作、利他 |
| 神经质 | Neuroticism | N | 情绪不稳定性 |
| 决策温度 | Temperature | — | LLM 输出的随机性控制 |
| 提示词 | Prompt | — | 给 LLM 的输入文本 |
| 结构化输出 | Structured Output | — | 强制 LLM 输出特定格式 |
| 多裁判投票 | Multi-Judge Voting | — | 多个 LLM 投票决定结果 |
| 思维链 | Chain-of-Thought | CoT | 让 LLM 多步推理的提示词技术 |

## A.4　仿真运行与统计

| 中文 | 英文 | 缩写 | 解释 |
|---|---|---|---|
| 时钟 | Clock | — | 仿真的时间推进机制 |
| 步长 | Time Step | — | 每次推进的时间间隔 |
| 快进 | Fast-Forward | — | 压缩日内循环的仿真模式 |
| 大跨度 | Long-Run | — | 月/年步长的仿真模式 |
| 守恒定律 | Conservation Law | — | 仿真中不变量(如货币守恒) |
| 种子 | Seed | — | 随机数生成的起点 |
| 预注册 | Pre-Registration | — | 跑前固定假设、指标、判定规则 |
| 效应量 | Effect Size | — | 衡量差异大小的统计量 |
| Cohen's d | Cohen's d | — | 常用的效应量指标 |
| 最小可观测效应 | Minimum Detectable Effect | MDE | 愿意接受的最小真实效应 |
| 平行世界 | Parallel Worlds | — | 同时跑多个条件的世界 |
| 对照世界 | Control World | — | 无干预的基线世界 |
| 安慰剂世界 | Placebo World | — | 虚假干预的对照世界 |
| 分叉度 | Divergence | — | 世界间偏离的程度 |
| 分叉点 | Divergence Point | — | 世界显著偏离的时间点 |
| 噪声底线 | Noise Floor | — | 种子间变异的标准差 |
| Bootstrap | Bootstrap | — | 重采样统计推断方法 |
| 显著性 | Significance | — | 差异非偶然的概率 |
| 95% 置信区间 | 95% Confidence Interval | CI | 真实值的 95% 概率范围 |

## A.5　效度与可信度

| 中文 | 英文 | 缩写 | 解释 |
|---|---|---|---|
| 构念效度 | Construct Validity | — | 模型测量的"东西"是不是声称要研究的 |
| 内部效度 | Internal Validity | — | 因果推断是否排除了混淆 |
| 外部效度 | External Validity | — | 结论能否推广到真实世界 |
| 可复现性 | Reproducibility | — | 别人能否跑出同样的结果 |
| 鲁棒性 | Robustness | — | 改变参数后结论是否稳定 |
| 现实对照 | Benchmark | — | 与真实数据对比 |
| 偏置 | Bias | — | 系统性的偏差 |
| 幻觉 | Hallucination | — | LLM 编造事实的现象 |
| 位置偏置 | Position Bias | — | LLM 倾向给"放在前面"的选项高分 |
| 长度偏置 | Length Bias | — | LLM 倾向给"更长"的回答高分 |
| 权威偏置 | Authority Bias | — | LLM 倾向给"看起来权威"的回答高分 |
| 确认偏置 | Confirmation Bias | — | LLM 倾向给"和 prompt 一致"的回答高分 |

## A.6　社会经济学术语

| 中文 | 英文 | 缩写 | 解释 |
|---|---|---|---|
| 基尼系数 | Gini Coefficient | — | 衡量收入不平等的指标 |
| 恩格尔系数 | Engel Coefficient | — | 食品支出占总支出比例 |
| 五险一金 | Social Insurance & Housing Fund | — | 中国社保体系 |
| 个税 | Individual Income Tax | IIT | 个人所得税 |
| 货币守恒 | Monetary Conservation | — | 经济系统中货币总量不变 |
| 部门池 | Sector Pool | — | 经济系统的资金池 |
| 信贷 | Credit | — | 借贷行为 |
| 通勤 | Commute | — | 居住地与工作地之间的出行 |
| 拥堵费 | Congestion Charge | — | 进入拥堵区域的收费 |
| 限行令 | License Plate Restriction | — | 按车牌限制出行 |
| 人口金字塔 | Population Pyramid | — | 年龄 × 性别的人口分布图 |
| 户籍 | Hukou | — | 中国户籍制度 |
| 居住隔离 | Residential Segregation | — | 不同群体在地理上分离 |
| 行为传染 | Behavioral Contagion | — | 行为通过社交网络扩散 |
| 信息传染 | Information Contagion | — | 信息通过社交网络扩散 |
| 情绪传染 | Emotional Contagion | — | 情绪通过社交网络扩散 |
| 规范传染 | Norm Contagion | — | 行为规范通过社交网络扩散 |

## A.7　LLM 与 AI 术语

| 中文 | 英文 | 缩写 | 解释 |
|---|---|---|---|
| 大型语言模型 | Large Language Model | LLM | 参数规模数十亿以上的语言模型 |
| 提示词工程 | Prompt Engineering | — | 设计 LLM 输入的技术 |
| Few-shot | Few-shot Learning | — | 给出少量示例让 LLM 学习 |
| Zero-shot | Zero-shot Learning | — | 不给示例让 LLM 直接做 |
| 训练数据 | Training Data | — | LLM 学习的数据 |
| 微调 | Fine-tuning | — | 在特定数据上继续训练 |
| 路由 | Routing | — | 不同任务用不同模型 |
| 缓存 | Caching | — | 存储重复结果减少调用 |
| 批处理 | Batching | — | 合并多个请求为一次调用 |
| Token | Token | — | LLM 输入输出的基本单位 |
| GPT | Generative Pre-trained Transformer | GPT | OpenAI 的 LLM 系列 |
| Claude | Claude | — | Anthropic 的 LLM 系列 |
| Ollama | Ollama | — | 本地运行 LLM 的工具 |
| vLLM | vLLM | — | 高性能 LLM 推理框架 |
| Function Calling | Function Calling | — | LLM 调用预定义函数 |
| Tool Use | Tool Use | — | LLM 使用外部工具 |

## A.8　GAWorld 特有术语

| 中文 | 英文 | 缩写 | 解释 |
|---|---|---|---|
| GAWorld | Generative 智能体 World | GAWorld | 本书使用的社会仿真平台 |
| Persona Distillation | Persona Distillation | — | 从真人/网站生成居民 |
| Moltbook | Moltbook | — | AI 智能体的社交网络 |
| 群体模式 | Cohort Mode | — | 大规模仿真的成本优化模式 |
| 群体智能体 | Cohort 智能体 | — | 群体的代表决策 |
| 平行世界实验台 | Parallel Worlds Dashboard | — | 平行世界结果可视化 |
| 灾害模式 | Disaster Mode | — | 灾害场景仿真 |
| 灾害分幕 | Disaster Stage | — | 灾害过程的多个阶段 |
| 城市孪生 | City Twin | — | 真实城市的仿真副本 |
| 仿真孪生 | Simulation Twin | — | 与真实系统同步的仿真 |
| 验证门 | Validation Gate | — | 群体模式的失真检测 |
| 验证门 L1 | L1 Gate | — | 行为分布对比 |
| 验证门 L2 | L2 Gate | — | 网络耦合对比 |
| 验证门 L3 | L3 Gate | — | 政策效应对比 |
| 验证门 L4 | L4 Gate | — | 长期动态对比 |
| 预注册协议 | Preregistration Protocol | — | 跑前固定的假设与判定规则 |
| 研究工作台 | Research Workbench | — | 预注册 + 实验 + 报告一体化工具 |
| 智能体 Studio | 智能体 Studio | — | 单智能体可视化构建工具 |
| 群体采访 | Group Interview | — | 一次采访一群居民 |
| 斗兽场 | Arena | — | 多居民答题竞赛 |
| 说服游戏 | Persuasion Game | — | 和居民聊到立场改变 |
| 仿冒考试 | Disaster Mode | — | 居民在灾害场景下的反应 |
| 真实工作 | Real Work | — | 居民接入真实劳动任务 |

---

## A.9　缩写速查

| 缩写 | 全称 |
|---|---|
| ABM | 智能体-Based Modeling |
| LLM | Large Language Model |
| OCEAN | Openness / Conscientiousness / Extraversion / Agreeableness / Neuroticism |
| SIR | Susceptible-Infected-Recovered |
| MDE | Minimum Detectable Effect |
| CI | Confidence Interval |
| DID | Difference-in-Differences |
| RDD | Regression Discontinuity Design |
| DID | Difference-in-Differences |
| CSS | Computational Social Science |
| OSM | OpenStreetMap |
| POI | Point of Interest |
| GIS | Geographic Information System |
| GDP | Gross Domestic Product |
| API | Application Programming Interface |
| CLI | Command Line Interface |
| UUID | Universally Unique Identifier |
| FAIR | Findable / Accessible / Interoperable / Reusable |

---

## A.10　如何使用本附录

读者可以在以下场景使用本附录:

1. **写论文时**——选择合适的术语中英文。
2. **读论文时**——遇到陌生术语时查阅。
3. **设计研究时**——确认使用的概念符合本领域共识。
4. **教学时**——作为术语速查表分发给学生。

本附录保持更新——随着社会仿真领域的发展,会有新术语加入。建议读者把本附录与 GAWorld 的最新文档对照阅读。

---

> **本附录教学注释**
>
> 这个术语表不是"权威定义",而是"工作定义"——它反映的是 2026 年社会仿真领域的主流用法,可能随时间变化。读者在自己的研究中,如果某个术语有特定含义,应该在论文里明确说明。
>
> A.8 节"GAWorld 特有术语"对应该平台的功能。读者用 GAWorld 时,可以参考这一节核对功能名。
---

## A.11　扩展:行为与决策的细分术语

| 中文 | 英文 | 解释 |
|---|---|---|
| 决策树 | Decision Tree | 用树状结构表示决策过程 |
| 强化学习 | Reinforcement Learning | 通过奖励信号学习的算法 |
| 多臂赌博机 | Multi-Armed Bandit | 探索—利用权衡的经典问题 |
| 蒙特卡洛 | Monte Carlo | 随机采样统计推断方法 |
| 马尔可夫链 | Markov Chain | 无记忆随机过程 |
| 马尔可夫决策过程 | Markov Decision Process | 加决策的马尔可夫过程 |
| 部分可观测马尔可夫决策过程 | POMDP | 状态部分可观测的决策过程 |
| Q-Learning | Q-Learning | 强化学习算法之一 |
| 策略梯度 | Policy Gradient | 强化学习的策略优化方法 |
| 模仿学习 | Imitation Learning | 从示范中学习行为 |
| 逆强化学习 | Inverse RL | 从行为反推奖励函数 |
| 多智能体强化学习 | Multi-Agent RL | 多智能体的强化学习 |
| 博弈论 | Game Theory | 研究策略互动的数学 |
| 纳什均衡 | Nash Equilibrium | 没有玩家愿意单方面偏离的状态 |
| 囚徒困境 | Prisoner's Dilemma | 经典博弈论问题 |
| 演化博弈论 | Evolutionary Game Theory | 引入演化动力学的博弈论 |
| 机制设计 | Mechanism Design | 反向的博弈论 |
| 拍卖理论 | Auction Theory | 资源分配的博弈论 |

---

## A.12　扩展:经济学与社会科学的细分术语

| 中文 | 英文 | 解释 |
|---|---|---|
| 一般均衡 | General Equilibrium | 所有市场同时出清的状态 |
| 帕累托最优 | Pareto Optimal | 没有帕累托改进的状态 |
| 比较优势 | Comparative Advantage | 相对成本优势 |
| 外部性 | Externality | 第三方未补偿的影响 |
| 公共物品 | Public Good | 非排他性、非竞争性的物品 |
| 搭便车 | Free Riding | 享受公共物品但不付出 |
| 信息不对称 | Information Asymmetry | 交易双方信息不对等 |
| 逆向选择 | Adverse Selection | 信息不对称导致的市场失灵 |
| 道德风险 | Moral Hazard | 隐藏行为导致的风险 |
| 委托代理 | Principal-智能体 | 委托人与代理人的激励问题 |
| 集体行动 | Collective Action | 多人合作的经典问题 |
| 公地悲剧 | Tragedy of the Commons | 共享资源被过度使用 |
| 社会资本 | Social Capital | 信任、规范、网络 |
| 弱连接 | Weak Tie | 强度低但数量多的关系 |
| 结构洞 | Structural Hole | 网络中两个群体之间的连接人 |

---

## A.13　扩展:技术与工程的细分术语

| 中文 | 英文 | 解释 |
|---|---|---|
| 数据库 | Database | 结构化数据存储 |
| 关系数据库 | Relational Database | 基于关系模型的数据库 |
| NoSQL | NoSQL | 非关系数据库 |
| 图数据库 | Graph Database | 基于图结构的数据库 |
| 缓存 | Cache | 高速数据存储 |
| 消息队列 | Message Queue | 异步通信机制 |
| 分布式系统 | Distributed System | 多节点协同系统 |
| 微服务 | Microservice | 小型独立服务 |
| 容器化 | Containerization | 应用打包和隔离 |
| Docker | Docker | 容器化平台 |
| Kubernetes | Kubernetes | 容器编排平台 |
| CI/CD | Continuous Integration/Deployment | 持续集成/部署 |
| 监控 | Monitoring | 系统运行状态观测 |
| 日志聚合 | Log Aggregation | 多源日志统一管理 |
| A/B 测试 | A/B Testing | 两个版本对比实验 |

---

## A.14　扩展:研究方法学的细分术语

| 中文 | 英文 | 解释 |
|---|---|---|
| 田野调查 | Field Research | 在自然场景下的研究 |
| 民族志 | Ethnography | 深入的文化描述 |
| 案例研究 | Case Study | 单一对象的深入研究 |
| 比较研究 | Comparative Research | 多对象的对比研究 |
| 历史分析 | Historical Analysis | 历史数据的分析 |
| 内容分析 | Content Analysis | 文本/媒体内容分析 |
| 话语分析 | Discourse Analysis | 话语结构和权力分析 |
| 扎根理论 | Grounded Theory | 从数据中涌现理论 |
| 三角化 | Triangulation | 多方法验证 |
| 同行评议 | Peer Review | 学术共同体评审 |
| 预注册 | Pre-Registration | 跑前固定假设 |
| 开放数据 | Open Data | 数据公开 |
| 开放代码 | Open Source Code | 代码公开 |
| 复现性 | Reproducibility | 别人能复现你的结果 |
| 可重复性 | Replicability | 在新数据上重复结果 |

---

## A.15　扩展:领域应用的细分术语

### A.15.1　公共政策

| 中文 | 英文 | 解释 |
|---|---|---|
| 政策评估 | Policy Evaluation | 评估政策效果 |
| 政策仿真 | Policy Simulation | 用仿真预测政策效果 |
| 政策周期 | Policy Cycle | 议程—制定—执行—评估 |
| 利益相关者 | Stakeholder | 政策影响的所有方 |
| 政策网络 | Policy Network | 政策制定的关系网络 |
| 政策学习 | Policy Learning | 从过去政策中学到的经验 |
| 多中心治理 | Polycentric Governance | 多层级多主体治理 |

### A.15.2　城市规划

| 中文 | 英文 | 解释 |
|---|---|---|
| 城市更新 | Urban Renewal | 老城改造 |
| 土地利用 | Land Use | 城市功能区划分 |
| 公共交通导向开发 | TOD | 以公交为中心的开发 |
| 智慧城市 | Smart City | 用技术提升城市治理 |
| 数字孪生城市 | Digital Twin City | 城市的数字副本 |
| 紧凑城市 | Compact City | 高密度、功能混合的城市 |
| 城市韧性 | Urban Resilience | 城市应对冲击的能力 |

### A.15.3　公共卫生

| 中文 | 英文 | 解释 |
|---|---|---|
| 流行病学 | Epidemiology | 疾病分布与决定因素 |
| 基本传染数 | Basic Reproduction Number | R0,每个感染者传染的人数 |
| 群体免疫 | Herd Immunity | 群体对传染病的整体抵抗力 |
| 接触追踪 | Contact Tracing | 追踪感染者接触的人 |
| 健康不平等 | Health Inequality | 健康状况的人群差异 |
| 健康的社会决定因素 | Social Determinants of Health | 影响健康的社会因素 |

---

## A.16　扩展:GAWorld 内部模块的术语

| 中文 | 英文 | 解释 |
|---|---|---|
| 智能体循环 | 智能体 Loop | agent 主循环 |
| 认知管线 | Cognition Pipeline | agent 的认知处理流程 |
| 行动选择 | Action Selection | agent 选择行动 |
| 状态更新 | State Update | agent 状态变化 |
| 事件触发器 | Event Trigger | 触发事件的机制 |
| 事件队列 | Event Queue | 待处理事件的队列 |
| 仿真时钟 | Simulation Clock | 仿真时间推进 |
| 仿真循环 | Simulation Loop | 仿真的主循环 |
| 持久化层 | Persistence Layer | 数据存储抽象 |
| LLM 路由器 | LLM Router | 不同任务路由到不同模型 |
| 多裁判 | Multi-Judge | 多个 LLM 投票 |
| Persona 蒸馏 | Persona Distillation | 从真人生成居民 |
| 智能体 Studio | 智能体 Studio | 单智能体可视化构建 |
| 研究工作台 | Research Workbench | 预注册 + 实验 + 报告 |
| 平行世界实验台 | Parallel Worlds Dashboard | 平行世界可视化 |
| 灾害分幕 | Disaster Stage | 灾害过程的阶段 |

---

## A.17　扩展:学术写作的细分术语

| 中文 | 英文 | 解释 |
|---|---|---|
| IMRaD | IMRaD | Introduction/Methods/Results/Discussion |
| 摘要 | Abstract | 论文的简短总结 |
| 引言 | Introduction | 论文的背景与目的 |
| 方法 | Methods | 论文的研究方法 |
| 结果 | Results | 论文的发现 |
| 讨论 | Discussion | 结果的解释与意义 |
| 结论 | Conclusion | 论文的最终结论 |
| 局限 | Limitations | 研究的弱点 |
| 未来工作 | Future Work | 后续研究方向 |
| 致谢 | Acknowledgments | 感谢贡献者 |
| 利益冲突 | Conflict of Interest | 作者的利益披露 |
| 数据可获得性 | Data Availability | 数据公开声明 |
| 代码可获得性 | Code Availability | 代码公开声明 |
| 引用 | Citation | 文献引用 |
| 参考文献 | References | 引用的文献列表 |

---

## A.18　本附录教学注释(扩展版)

- 行为与决策术语覆盖了主要的 AI/RL/博弈论概念。
- 经济学与社会科学术语是社会仿真研究的核心词汇。
- 技术与工程术语帮助读者读懂工程实现。
- 研究方法学术语是论文写作的必备。
- 领域应用术语:公共政策、城市规划、公共卫生。
- GAWorld 内部模块术语帮助读者理解平台实现。
- 学术写作术语是论文结构的标准词汇。


---

## A.19　扩展:仿真理论的细分术语

| 中文 | 英文 | 解释 |
|---|---|---|
| 计算社会科学 | Computational Social Science | 用计算方法研究社会科学 |
| 智能体建模 | 智能体-Based Modeling | 用智能体构建模型 |
| 离散事件仿真 | Discrete Event Simulation | 离散时间点的仿真 |
| 连续仿真 | Continuous Simulation | 连续时间的仿真 |
| 蒙特卡洛仿真 | Monte Carlo Simulation | 随机采样仿真 |
| 系统动力学 | System Dynamics | 反馈循环建模 |
| 演化仿真 | Evolutionary Simulation | 模拟演化过程 |
| 涌现 | Emergence | 微观到宏观的自组织 |
| 共演化 | Co-evolution | 多个系统相互影响 |
| 自适应 | Adaptation | 系统对环境变化的调整 |
| 鲁棒性 | Robustness | 系统抗干扰能力 |
| 韧性 | Resilience | 系统恢复能力 |
| 相变 | Phase Transition | 系统的突然变化 |
| 临界点 | Critical Point | 相变发生的临界状态 |
| 自组织临界 | Self-Organized Criticality | 系统自然演化到临界状态 |
| 复杂适应系统 | Complex Adaptive System | 由多个相互作用的 agent 组成的系统 |
| 涌现行为 | Emergent Behavior | 系统涌现的个体行为 |
| 多智能体系统 | Multi-Agent System | 多个智能体协同的系统 |
| 集体智能 | Collective Intelligence | 群体涌现的智能 |
| 群体决策 | Group Decision Making | 群体共同做决策 |

---

## A.20　扩展:统计与方法的细分术语

| 中文 | 英文 | 解释 |
|---|---|---|
| 假设检验 | Hypothesis Testing | 检验统计假设 |
| 零假设 | Null Hypothesis | H0:无效应假设 |
| 备择假设 | Alternative Hypothesis | H1:有效应假设 |
| 显著性水平 | Significance Level | α,通常 0.05 |
| p 值 | p-value | 观测到该结果或更极端的概率 |
| 第一类错误 | Type I Error | 错误拒绝真零假设 |
| 第二类错误 | Type II Error | 错误接受假零假设 |
| 功效 | Statistical Power | 1 - β,正确拒绝假零假设的概率 |
| 效应量 | Effect Size | 衡量效应大小 |
| Cohen's d | Cohen's d | 标准化的均值差 |
| eta 平方 | Eta Squared | 方差解释比例 |
| R 平方 | R-squared | 回归方差解释比例 |
| 置信区间 | Confidence Interval | 参数估计的区间 |
| 自助法 | Bootstrap | 重采样统计方法 |
| 置换检验 | Permutation Test | 重排样本做检验 |
| 贝叶斯统计 | Bayesian Statistics | 基于先验和似然的统计 |
| 先验分布 | Prior Distribution | 贝叶斯统计的先验 |
| 后验分布 | Posterior Distribution | 贝叶斯统计的后验 |
| 最大似然估计 | Maximum Likelihood Estimation | MLE |
| 最小二乘 | Ordinary Least Squares | OLS |

---

## A.21　扩展:技术与工具的细分术语

| 中文 | 英文 | 解释 |
|---|---|---|
| Git | Git | 分布式版本控制 |
| GitHub | GitHub | 代码托管平台 |
| GitLab | GitLab | 自托管代码平台 |
| Docker | Docker | 容器化平台 |
| Kubernetes | Kubernetes | 容器编排 |
| Jenkins | Jenkins | 持续集成工具 |
| GitHub Actions | GitHub Actions | CI/CD 平台 |
| pytest | pytest | Python 测试框架 |
| unittest | unittest | Python 标准测试框架 |
| tox | tox | Python 测试工具 |
| Sphinx | Sphinx | Python 文档生成 |
| MkDocs | MkDocs | Markdown 文档生成 |
| Read the Docs | Read the Docs | 文档托管平台 |
| PyPI | PyPI | Python 包索引 |
| conda | conda | Python 包和环境管理 |
| pip | pip | Python 包管理 |

---

## A.22　本附录教学注释(最终扩展版)

- 仿真理论的细分术语覆盖了涌现、共演化、相变、复杂适应系统等核心概念。
- 统计与方法的细分术语是社会仿真研究的方法学基础。
- 技术与工具的细分术语帮助读者选择合适的工具。


---

## A.23　附录尾声

本附录覆盖了社会仿真研究中常用的术语,按主题分类。每个术语给出中文、英文和解释。

读者在使用本附录时:

- 写论文时:选择合适的中英文术语
- 读论文时:遇到陌生术语查阅
- 设计研究时:确认术语符合领域共识
- 教学时:作为术语速查表分发

本附录会随着领域发展更新。建议读者关注 GAWorld 文档以获取最新术语表。

