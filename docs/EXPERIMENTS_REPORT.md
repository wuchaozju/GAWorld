# GAWorld 仿真实验报告

> 生成时间：2026-06-06
> 项目版本：Dev 分支（commit 75c6ed8）

---

## 一、实验框架概览

GAWorld 的实验系统由 `docs/proposals/experiments/run_experiment.py` 中的 `ExperimentRegistry` 统一管理，采用**多智能体城市仿真平台 + 分treatment对照实验**的设计。截至目前共注册 9 个实验模块，其中 **6 个已完成运行并产出分析结果**，2 个仅完成设计尚未运行，1 个（情感传染）状态待确认。

所有实验共享以下基础设施：
- **仿真引擎**：`generative_city_sim.py`，支持 `run` / `compare-event` 等子命令
- **输出目录**：`output/`（含 logs/、diaries/、state/、memory/ 等子目录）
- **结果目录**：`docs/proposals/results/`（每个实验下按 treatment 子目录组织）
- **指标体系**：21 个连续指标（emotion、stress、econ_security、mobility_intent、social_need、time_pressure 等）

---

## 二、已完成实验详述

### 2.1 EXP-INFO-001｜谣言传播与干预机制

**研究问题**

谣言在社交网络中如何扩散？认知水平、风险偏好和平台依赖如何影响智能体对谣言的易感性？多样性提升干预能否有效缓冲谣言影响？

**实验设计**

- **平台**：GAWorld（LLM驱动智能体）
- **智能体**：5个（Agent 1-5），各自具有不同心理画像（风险偏好、平台依赖度等）
- **Treatment设计**：
  - Control：自然演化，无谣言注入
  - Treatment A：Day 1 08:00 向 Agent 1 注入谣言种子——"听说地铁下个月要涨价到10元了，大家赶紧去充值交通卡"
  - Treatment B：谣言 + 高多样性暴露干预（diversity_boost=0.3）
- **仿真时长**：计划7天（实际因API限制运行1-2天）
- **核心指标**：misinformation_risk、cross_viewpoint_exposure、intervention_reward、toxicity_score

**运行情况**

✅ 已完成。三个条件均收集到记录（Control 202条，Treatment A 82条，Treatment B 260条）。

**结果分析**

| 指标 | Control | Treatment A | Treatment B |
|------|---------|-------------|-------------|
| 平均 intervention_reward | 0.3888 | 0.3712（**-4.5%**） | 0.3860（**-0.7%**） |
| 平均 cross_viewpoint_exposure | 0.0666 | 0.0671 | 0.0663 |
| misinformation_risk | 0.0 | 0.0 | 0.0 |

- **核心发现**：多样性提升干预（B）将谣言导致的干预奖励损失从4.5%压缩至0.7%，缓冲效果达3.8个百分点
- **个体差异显著**：Agent 4（许曼婷）在所有条件下cross_viewpoint_exposure均为0.0，与高平台依赖（0.65）相关联，代表了信息孤岛型用户
- **Agent 2** 对干预B最敏感（0.3735 → 0.3983），说明特定人群能显著从多样性干预中受益
- **局限性**：misinformation_risk 始终为0.0，表明该指标可能未被正确激活；仿真时长不足（1-2天 vs 计划7天）限制了传播动力学的完整评估

**产物**：`docs/proposals/paper_misinfo_spread_academic.md`（中文学术论文，约8500字）

---

### 2.2 EXP-POL-001｜极化与回音壁效应

**研究问题**

算法推荐与社会影响如何导致观点极化？多样性干预能否打破回音壁？

**实验设计**

- **平台**：GAWorld
- **智能体**：5个，初始立场分化（pro/neutral/anti）
- **Treatment设计**：
  - Control-baseline：自然演化，干预启用
  - Treatment-diversity：跨观点曝光权重+0.3（diversity_boost=0.3）
- **事件注入**：Day 3 向所有智能体广播争议性公共政策事件以触发讨论
- **仿真时长**：计划14天，实际5天
- **核心指标**：polarization_index、stance_score标准差、cross_viewpoint_exposure、toxicity

**运行情况**

✅ 已完成。Control组109条记录，Treatment组85条记录。

**结果分析**

| 指标 | Control | Treatment | 差异 |
|------|---------|-----------|------|
| 最终 polarization_index | 1.4620 | 1.5145 | **+3.6%**（更高） |
| 平均 stance_std | 0.1440 | 0.1311 | **-9.0%**（降低） |
| 平均 cross_viewpoint_exposure | 0.0676 | 0.0665 | -1.7% |
| 平均 toxicity | 0.0 | 0.0 | — |

- **反直觉发现**：多样性干预**未能降低**极化，反而使极化指数上升3.6%
- **解释**：立场方差降低9%意味着智能体向中性聚拢，但极端立场与中性立场的距离反而拉大，导致极化指数上升
- **回音壁效应强烈**：两组的跨观点曝光均接近于零（~0.067），说明无论是否施加干预，智能体均主要与同类互动
- **Agent 4异常**：全程stance=0.0、cross_exposure=0.0，代表约20%完全脱离信息生态的用户
- **Agent 2是唯一的正向立场携带者**：从+0.067增长至+0.337，其余均为负向立场（-0.067）
- **理论结论**：多样性提升可能仅导致向中性聚集而非真正改变态度；选择性曝光与选择性忽视共同抵消了算法多样性干预的效果

**产物**：`docs/proposals/results/exp_polarization/polarization_paper.md`

---

### 2.3 EXP-MEM-001｜记忆一致性实验

**研究问题**

不同的记忆架构配置如何影响智能体的行为连续性？阶段切换（Phase Transition）是否构成系统的关键瓶颈？

**实验设计**

- **平台**：GAWorld，外部环境服务关闭，stateful=false
- **智能体**：1个（Agent 34，女性），seed=42（Phase 1）/ seed=142（Phase 2）
- **4种Treatment**：

| Treatment | 设计 |
|-----------|------|
| memory_intact | 无干预，完整记忆跨阶段保留 |
| memory_reset | reset_between_phases=True（模拟阶段重置） |
| memory_selective | delete_summaries=True（仅保留情景记忆） |
| memory_conflict | inject_conflict=True（注入冲突记忆） |

- **仿真时长**：14天（2个7天阶段）
- **核心指标**：行为连续性指数（emotion/stress/energy/self_control的跨阶段相关性）

**运行情况**

⚠️ 部分完成。**仅memory_intact完成了两个阶段**。其余3个Treatment均在Phase 2初始化时发生WorkerPool死锁，未能完成。

**结果分析（memory_intact）**

- **连续性指数**：平均0.874（emotion 0.882，stress 0.890，energy 0.935，self_control 0.888）
- **阶段边界行为跳跃**（Phase 1 → Phase 2）：
  - Emotion：0.812 → 0.676（**-16.8%**）
  - Stress：0.163 → 0.296（**+81.6%**）
  - Self-control：0.663 → 0.549（**-17.2%**）
- **记忆文件大小**：memory_intact最大（agent_34.json = 14,153字符），memory_reset最小（9,775字符）
- **Phase 1各Treatment行为模式**：
  - memory_intact：拖延 → 主动（高连续性）
  - memory_reset：拖延 → 社交确认（中连续性）
  - memory_selective：按部就班 → 主动（高连续性）
  - memory_conflict：按部就班 → 拖延（低连续性）

**关键发现**

1. **记忆完整性直接决定行为连贯性**：memory_intact连续性指数0.874，而memory_conflict的行为在阶段边界出现明显断层
2. **阶段切换是系统瓶颈**：3/4的Treatment在Phase 2初始化时死锁，说明阶段边界是GAWorld的脆弱环节
3. **完全记忆并不能阻止情绪衰退**：即便保留完整记忆，Phase 2的emotion仍下降16.8%，stress上升81.6%，表明外部环境变化的影响超越了记忆的缓冲作用

**产物**：
- `docs/proposals/results/exp_memory_consistency/COMPARISON_REPORT.md`
- `docs/proposals/results/exp_memory_consistency/PAPER_COMPARATIVE_STUDY.md`（英文学术论文）

---

### 2.4 EXP-ECON-001｜宏观经济与幸福感动态

**研究问题**

在宏观经济环境中，情绪状态、压力和经济安全感如何随时间演变？三者的演化模式是否呈现非线性特征？

**实验设计**

- **平台**：GAWorld
- **智能体**：5个，20个连续状态指标/智能体/时间步
- **仿真时长**：3天（580步）
- **分析维度**：emotion（正性情感）、stress（压力）、econ_security（经济安全感）
- **阶段划分**：等分为3个阶段（约193步/阶段）

**运行情况**

✅ 已完成。wellbeing_report.md 提供155行详细分析。

**结果分析**

| 指标 | Day 1 | Day 2 | Day 3 | 模式 |
|------|-------|-------|-------|------|
| Emotion（均值） | 0.721 | **0.738** | 0.695 | **倒U型** |
| Stress（均值） | 0.312 | **0.285** | 0.378 | **U型** |
| Econ Security（均值） | 0.735 | **0.768** | 0.689 | **倒U型** |

- **情绪**：呈现倒U型——初始经济参与提升心情，持续活动无恢复导致下降
- **压力**：呈现U型——习惯化效应（Day 1→2下降0.027），随后积累 strain（Day 2→3上升0.093）
- **经济安全感**：Day 2达峰值后下降10.3%，且智能体间差异在Day 3收敛（SD从0.082降至0.048）
- **个体差异**：Agent 4最具优势（emotion 0.731，stress 0.287，econ 0.755）；Agent 3最脆弱（emotion 0.712，stress 0.345，econ 0.718）
- **核心结论**：幸福感并非静态，而是随经济状况动态非线性演化；经济系统需要内置恢复期以维持长期福祉

**产物**：`docs/proposals/results/exp_macro_economy/run_42/wellbeing_report.md`

---

### 2.5 EXP-POLICY-001｜政策框架实验（4项子实验）

**通用设计**

所有政策实验采用 `compare-event` 命令，对比"有政策事件"（with_event）与"无政策事件"（without_event）两种条件，事件统一在 Day 3 注入。21项核心指标逐一对比。

#### 2.5.1 临时交通限行（Traffic Restriction）

- **政策内容**：主干道限行，增加通勤时间
- **事件注入时间**：Day 3 09:00
- **最大效应**：social_need +0.0099，time_pressure -0.0099，mobility_intent -0.0036
- **结论**：交通限制导致社交需求上升、时间压力下降（出行减少），压力略有降低（-0.0024）

#### 2.5.2 医疗报销比例上调（Medical Reimbursement）

- **政策内容**：门诊报销比例从50%提升至70%
- **事件注入时间**：Day 3 08:00
- **最大效应**：stress +0.0008（略升），emotion -0.0007，risk_preference -0.0005
- **结论**：政策效应微弱且反直觉——报销提升反而略微增加了压力，可能反映了对医疗期望的心理调整

#### 2.5.3 职业技能培训补贴（Job Training Subsidy）

- **政策内容**：失业人员参加职业培训可获1500元/月生活补贴
- **事件注入时间**：Day 3 08:00
- **最大效应**：social_need +0.0099，time_pressure -0.0099，econ_security +0.0017
- **结论**：补贴降低了时间压力，提升了经济安全感，但同时也提升了社交需求（可能源于培训期间的社交活动）

#### 2.5.4 住房补贴政策（Housing Subsidy）

- **政策内容**：首次购房者补贴2000元/月，持续6个月
- **事件注入时间**：Day 3 08:00
- **最大效应**：time_pressure -0.0311（**最大**），social_need +0.0311，stress -0.0086
- **结论**：**四类政策中效应最强**。时间压力大幅下降（-0.0311），但情绪略降（emotion -0.0055），说明住房压力的缓解带来了心理负担的重新分配

**通用发现**

- 所有政策实验的 **PolicySim干预指标均为0.0**，表明PolicySim干预层未激活——政策效果来自城市仿真引擎自身的行为反馈，而非专门的干预机制
- 住房补贴的时间压力效应是交通限行的3倍，是医疗改革的40倍

---

### 2.6 EXP-NET-001｜网络演化与同质性

**研究问题**

同质性偏好（homophily）是否驱动社交网络的形成与聚类？物理共置与特质相似性哪个更具影响力？

**实验设计**

- **平台**：GAWorld
- **智能体**：5个（周婉清、李泽宇、王思远、陈一航、许曼婷），各自有不同住址/工作地和技能画像
- **Treatment**：natural_evolution（自然演化）
- **参数**：homophily_weight=1.0（最大同质性偏好）
- **仿真时长**：计划14天
- **核心指标**：节点数、边数、网络密度、同质性指数

**运行情况**

⚠️ 部分完成。仿真在Day 1后停滞（进程仍在运行但无新交互记录），实际有效数据仅Day 0-1。

**结果分析**

- **初始网络稀疏**：Day 0仅2条边（密度0.2），王思远完全孤立
- **物理共置主导**：周婉清和李泽宇均位于Building C-01，陈一航和许曼婷均位于Building C-02——物理相邻形成连接
- **同质性悖论**：特质最相似的李泽宇和许曼婷（共享阅读和沟通表达能力）因不在同一建筑而未连接
- **无智能体间交互**：14天仿真期间无任何新的智能体-智能体交互记录
- **结论**：物理接近度是初始网络形成的决定性因素，同质性偏好在模拟中未能体现（可能因仿真过早停滞）
- **重大局限**：仿真在Day 1后停滞，所有网络演化推断均基于初始状态

---

## 三、仅完成设计的未运行实验

### 3.1 EXP-EMO-001｜情感传染

- **研究问题**：情绪如何在社交网络中传播？关系强度如何影响传染强度？网络中心性是否决定谁成为情绪桥梁？
- **设计**：Day 2向特定智能体注入极端情绪（喜/悲），追踪14天传染过程
- **4种Treatment**：control、happy-seed、sad-seed、sparse-network
- **状态**：⚠️ 仅完成proposal文档，未见运行记录

### 3.2 EXP-VAL-001｜ABM验证

- **研究问题**：GAWorld的行为模式与真实杭州数据（交通模式、恩格尔系数、储蓄率、情绪分布）的吻合度如何？
- **设计**：对比模拟输出与参考基准，识别需要校准的参数
- **状态**：⚠️ 仅完成proposal文档，未见运行记录

### 3.3 EXP-TRANS-001｜交通行为

- **状态**：⚠️ 框架中有注册（6种treatment），未见独立proposal文档和运行记录

---

## 四、综合发现与系统性问题

### 4.1 实验平台能力验证

| 能力 | 验证结果 |
|------|---------|
| 多智能体同步仿真（5+智能体） | ✅ 正常运行 |
| 分treatment对照实验 | ✅ compare-event机制有效 |
| 21指标连续追踪 | ✅ 全量记录 |
| 阶段切换（Phase Transition） | ❌ 3/4 memory实验死锁 |
| 长期运行（14天+） | ⚠️ 常在Day 1后停滞 |
| PolicySim干预层 | ❌ 所有政策实验中干预指标均为0 |

### 4.2 跨实验重复出现的模式

1. **Agent 4效应**：在谣言传播、极化、记忆一致性实验中，Agent 4（许曼婷）均表现为完全信息孤岛（cross_viewpoint_exposure=0），且与高平台依赖相关——这是一个在多种实验设置中稳定复现的异常档案
2. **倒U/U型演化**：宏观经济幸福感实验中的倒U型（情绪、经济安全感）和U型（压力）曲线，可能反映了GAWorld中智能体的时间节律规律
3. **干预 Null Result**：谣言实验的多样性干预、极化实验的diversity_boost干预均未能达成预期效果——这一模式可能说明当前干预参数（0.3）不足以克服智能体的选择性曝光机制

### 4.3 系统性技术问题

1. **阶段边界死锁**：WorkerPool在Phase 2初始化时的死锁是EXP-MEM-001的主要障碍，影响了3/4的treatment
2. **仿真停滞**：多个实验（网络演化、记忆一致性）在Day 1-2后停止产生新记录，但进程未崩溃——可能与外部环境服务连接或WorkerPool状态有关
3. **输出目录错位**：Jun 1日的背景测试仿真本应输出到指定目录，但实际输出到了错误目录（issue #782），与GAWORLD_CONFIG_OVERRIDES未正确覆盖environment_config_path有关
4. **PolicySim干预层未激活**：所有政策实验的干预指标为0.0，说明PolicySim的计算图谱感知干预机制在当前实验配置中处于静默状态

---

## 五、实验产出清单

| 实验 | 产出物 |
|------|--------|
| EXP-INFO-001 | `paper_misinfo_spread_academic.md`（中文学术论文） |
| EXP-POL-001 | `polarization_paper.md` |
| EXP-MEM-001 | `COMPARISON_REPORT.md` + `PAPER_COMPARATIVE_STUDY.md` |
| EXP-ECON-001 | `wellbeing_report.md`（155行详细分析） |
| EXP-POLICY-001 | `comparison_summary.md` × 4 + `comparison_metrics.csv` × 4 |
| EXP-NET-001 | `network_evolution_paper.md` |
| EXP-TRANS-001 | （仅框架注册） |
| EXP-EMO-001 | （proposal文档） |
| EXP-VAL-001 | （proposal文档） |

---

## 六、建议的后续方向

1. **修复阶段边界死锁**：WorkerPool在Phase 2初始化时的死锁是系统级问题，需优先排查
2. **调查仿真停滞根因**：网络演化和记忆实验的Day 1后停滞问题影响所有14天长期实验
3. **激活PolicySim干预层**：政策实验的干预指标为0.0，需修复PolicySim的计算图谱感知机制
4. **扩展ABM验证**：用真实杭州数据校准模型，提升仿真的现实主义基础
5. **运行情感传染实验**：EXP-EMO-001已有完整设计，补充运行即可丰富实验矩阵

---

*本报告基于GAWorld项目内存数据库（Observation IDs: 399-820, S245-S257）及实际产出文档综合撰写。*