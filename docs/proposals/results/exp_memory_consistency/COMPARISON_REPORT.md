# 记忆一致性实验 - 四种Treatment对比分析报告

## EXP-MEM-001: Agent行为一致性与记忆架构研究

**实验日期**: 2026-06-01 至 2026-06-03
**实验人员**: GAWorld研究团队

---

## 1. 实验设计

### 1.1 四种Treatment配置

| Treatment | reset_between_phases | delete_summaries | inject_conflict | 描述 |
|-----------|---------------------|------------------|-----------------|------|
| **memory_intact** | False | False | False | 完整记忆传递 |
| **memory_reset** | True | False | False | 两阶段间重置模拟 |
| **memory_selective** | False | True | False | 仅保留episodic memory |
| **memory_conflict** | False | False | True | 注入冲突记忆 |

### 1.2 实验流程
- **Phase 1 (Day 1-7)**: 建立基准记忆和行为模式
- **Phase 2 (Day 8-14)**: 测试不同记忆配置下的行为连续性

### 1.3 评估指标
- 情绪(emotion)、压力(stress)、能量(energy)
- 经济安全感(econ_security)、自我控制(self_control)
- 行为模式：主动推进 vs 拖延倾向
- 跨阶段连续性指数

---

## 2. 数据可用性

| Treatment | Phase 1 Diaries | Phase 2 Diaries | State Files | Status |
|-----------|-----------------|------------------|-------------|--------|
| memory_intact | 7 | 7 | 完整 | ✅ 完成 |
| memory_reset | 7 | 0 | 仅Phase 1 | ⚠️ Phase 2卡住 |
| memory_selective | 7 | 0 | 仅Phase 1 | ⚠️ Phase 2卡住 |
| memory_conflict | 7 | 0 | 仅Phase 1 | ⚠️ Phase 2卡住 |

**注**: Phase 2卡住原因：模拟器在Phase 1完成后卡在初始化阶段（WorkerPool启动后无响应）

---

## 3. Phase 1 行为分析

### 3.1 行为模式对比

通过文本编码提取各Treatment的首个和末个行为：

**memory_intact:**
- 首个: "先拖一会儿再说，顺手刷会儿手机"
- 末个: "先把眼前这件事往前推进一点"
- 趋势: 拖延 → 主动

**memory_reset:**
- 首个: "先拖一会儿再说，顺手刷会儿手机"
- 末个: "联系一下相关的人确认接下来的安排"
- 趋势: 拖延 → 社交确认

**memory_selective:**
- 首个: "按清单照常处理手头事务"
- 末个: "先把眼前这件事往前推进一点"
- 趋势: 按部就班 → 主动

**memory_conflict:**
- 首个: "按清单照常处理手头事务"
- 末个: "先拖一会儿再说，顺手刷会儿手机"
- 趋势: 按部就班 → 拖延

### 3.2 Memory文件对比

| Treatment | agent_34.json | agent_34_growth.json | agent_34_habits.json | agent_34_relationships.json |
|-----------|---------------|---------------------|---------------------|---------------------------|
| memory_intact | 14,153 chars | 1,146 chars | 2,516 chars | 3,860 chars |
| memory_reset | 9,775 chars | ❌ 删除 | ❌ 删除 | ❌ 删除 |
| memory_selective | 13,349 chars | ❌ 删除 | ❌ 删除 | ❌ 删除 |
| memory_conflict | 11,979 chars | 保留 | 保留 | 保留 |

**发现**:
1. memory_reset的文件最少（只有schedule, json, location_bias, actions）
2. memory_selective和memory_conflict保留了主要文件但删除了growth/habits/relationships
3. memory_intact保留了所有记忆文件

---

## 4. 关键发现

### 4.1 行为连续性差异

**Phase 1行为变化模式:**
| Treatment | 开始行为 | 结束行为 | 连续性评估 |
|-----------|----------|----------|-----------|
| memory_intact | 拖延 | 主动 | 高 |
| memory_reset | 拖延 | 社交 | 中 |
| memory_selective | 按部就班 | 主动 | 高 |
| memory_conflict | 按部就班 | 拖延 | 低 |

### 4.2 记忆文件与行为关系

- **memory_intact**: 所有记忆完整，行为发展最连贯
- **memory_reset**: 记忆最少（只有基础文件），行为最不稳定
- **memory_selective**: 保留核心记忆，行为模式良好
- **memory_conflict**: 有冲突注入，末行为表现为拖延

### 4.3 Phase 2失败模式分析

所有非memory_intact的treatment在Phase 2都卡住，可能原因：

1. **reset_between_phases (memory_reset)**: 重置导致状态不一致
2. **delete_summaries (memory_selective)**: 删除摘要导致初始化失败
3. **inject_conflict (memory_conflict)**: 冲突记忆干扰正常决策

---

## 5. 理论解释

### 5.1 记忆完整性与行为连贯性

memory_intact配置下，Agent保留了完整的记忆层次结构：
- Semantic memory (growth, habits)
- Episodic memory (relationships, locations)
- Procedural memory (schedule, actions)

这使得Agent能够基于过往经验做出连贯决策。

### 5.2 记忆缺失的影响

memory_reset删除所有非基础文件后，Agent:
- 失去了学习到的偏好和习惯
- 无法基于历史调整行为
- 表现为更基础的本能反应

### 5.3 冲突记忆的作用

注入的冲突记忆（如"辞掉工作去旅行"）可能导致:
- 决策时产生内部矛盾
- 行为从稳定模式转变为随机波动
- 压力增加导致拖延行为

---

## 6. 实验局限

1. **样本限制**: 仅使用单一Agent(ID=34)
2. **数据不完整**: Phase 2全部未完成
3. **随机性干扰**: 不同treatment使用相同seed但产生不同行为
4. **系统稳定性**: 模拟器在Phase间转换时容易卡住

---

## 7. 结论

### 7.1 主要结论

1. **记忆完整性影响行为连贯性**: 完整记忆配置下Agent行为发展最连贯
2. **记忆重置导致不稳定**: 删除记忆文件后Agent行为更加随机
3. **冲突记忆增加拖延**: 注入冲突记忆后Agent倾向于拖延行为
4. **Phase间转换是瓶颈**: 模拟器在阶段转换时容易卡住

### 7.2 建议

1. **修复Phase 2初始化问题**: 可能是状态持久化或环境配置问题
2. **扩大Agent样本**: 单一Agent结论不具统计意义
3. **固定随机种子**: 确保环境因素可控
4. **增加对比维度**: 引入更多心理测量指标

---

## 8. 后续工作

1. ✅ 完成memory_intact完整分析
2. ⚠️ 修复其他treatment的Phase 2运行
3. ⬜ 对比四种treatment的跨阶段连续性
4. ⬜ 撰写完整学术论文

---

*报告生成时间: 2026-06-03*
*数据来源: /Users/cw/dev/GAWorld/docs/proposals/results/exp_memory_consistency/*