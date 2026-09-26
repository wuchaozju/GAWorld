# 附录 A　术语对照表（中英双标）

> 本附录收录全书涉及的关键术语,按主题分类。每个术语给出中文、英文、缩写和一句话解释。读者写论文时,可以参考本表选用合适的术语。

---

## A.1　方法论基础术语

| 中文 | 英文 | 缩写 | 解释 |
|---|---|---|---|
| 多智能体仿真 | Multi-Agent Simulation | MAS | 由多个具有行为规则的智能体组成的仿真 |
| 基于智能体的建模 | Agent-Based Modeling | ABM | 用智能体构建模型的范式 |
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
| 智能体 | Agent | — | 仿真中的"假人",有身份、状态、决策 |
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
| GAWorld | Generative Agent World | GAWorld | 本书使用的社会仿真平台 |
| Persona Distillation | Persona Distillation | — | 从真人/网站生成居民 |
| Moltbook | Moltbook | — | AI 智能体的社交网络 |
| 群体模式 | Cohort Mode | — | 大规模仿真的成本优化模式 |
| 群体智能体 | Cohort Agent | — | 群体的代表决策 |
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
| Agent Studio | Agent Studio | — | 单智能体可视化构建工具 |
| 群体采访 | Group Interview | — | 一次采访一群居民 |
| 斗兽场 | Arena | — | 多居民答题竞赛 |
| 说服游戏 | Persuasion Game | — | 和居民聊到立场改变 |
| 仿冒考试 | Disaster Mode | — | 居民在灾害场景下的反应 |
| 真实工作 | Real Work | — | 居民接入真实劳动任务 |

---

## A.9　缩写速查

| 缩写 | 全称 |
|---|---|
| ABM | Agent-Based Modeling |
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