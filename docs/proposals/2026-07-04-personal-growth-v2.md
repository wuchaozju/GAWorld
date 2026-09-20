# 个人发展与兴趣系统 v2(科学家团队评审)

日期:2026-07-04
状态:已实现
范围:`gaworld/interests.py`、`generative_city_sim.py`(日终 tick 接线)、`gaworld/sim/_summary.py`(bug 修复)、`gaworld/settings/behavior.py`(配置)

## 一、专家小组评审结论

对现有系统(v1:LLM 推导静态兴趣集 + 关键词匹配单调升级)的四视角评审:

**发展心理学家**:v1 的 level 只升不降、增益与当前水平无关,违背两条最稳健的学习规律——幂律学习曲线(收益随水平递减)与间隔遗忘(不练则衰减,累计练习量提高保持率)。兴趣缺少发展阶段:Hidi & Renninger 四阶段模型(触发→维持→浮现→成熟)指出早期兴趣脆弱易弃、成熟兴趣自我维持,v1 无法表达这种差异。

**行为科学家**:streak_days 被记录但对任何行为无影响,习惯形成的动量效应缺失;升级不产生可感知事件,agent 的日记/反思无法引用"我最近入门了摄影"这类自我效能素材。

**复杂系统科学家**:兴趣集在 bootstrap 后完全静态,系统无涌现空间。缺少兴趣的社会传染(agent 从高频社交对象处习得兴趣)——这是 ABM 中产生文化聚类/同质性的经典机制;也缺少放弃机制,兴趣集无法周转。

**ML/仿真工程师**:`_summary.py::_growth_diff` 读取的 schema(`interests`/`minutes`/int level)与实际(`items`/`total_minutes`/float level)不符,成长 diff 报告一直是空的;新机制必须保持 LLM 零依赖(纯规则)以免增加预算压力,持久化格式需向后兼容存量 `agent_N_growth.json`。

## 二、设计

全部为纯函数规则机制,不新增 LLM 调用;GrowthItem 不增删字段(阶段为派生属性),存量数据直接兼容。

### P0 学习动力学(改 `update_growth_from_episode`)
- 递减收益:增益乘以 `1 - 0.6 * level`(水平越高越难涨)
- 连击动量:增益乘以 `1 + min(0.30, 0.03 * streak_days)`(习惯形成)
- 里程碑:level 上穿 0.35/0.60/0.85 时在 progress 里输出 `milestones: [{name, label}]`(入门/熟练/精通),episode 已存 growth_progress,日记/反思可引用

### P0 遗忘衰减(新 `apply_daily_growth_decay`,日终调用)
- 超过 `grace_days`(默认 2 天)未练:level 按日衰减 `daily_rate`,下限 `floor`(0.05)
- 保持率随累计练习量提高:有效衰减 `daily_rate * (1 - retention)`,`retention = min(0.8, total_minutes / 3000)`——成熟技能几乎不掉
- 断练同时将 streak_days 归零

### P1 兴趣发展阶段(新 `growth_phase`,派生属性)
- 触发期(level<0.25 且 total_minutes<300)→ 维持期(level<0.45)→ 浮现期(level<0.7)→ 成熟期
- `format_growth_context` 输出阶段标签,让 prompt 里的自我认知随发展变化
- 衰减阶段感知:触发期衰减 ×1.5(脆弱),成熟期 ×0.5(自我维持)

### P2 兴趣集演化(新 `evolve_growth_profile`,日终调用)
- 放弃:触发期条目超过 `retire_after_days`(14 天)未练且 priority<0.75 → 移除,记入 changes
- 社会传染:调用方从当日 episodes 的社交对象收集其 growth_focus 作为候选;候选未在自身条目中、有空位、且过 `adopt_chance`(0.35)骰 → 以触发期新条目加入(低 level/中 priority/高 sociality),每日最多 `max_new_per_day`(1)个
- 确定性:接受注入 rng,便于测试

### 接线(`generative_city_sim.py` PHASE 3c)
日终每 agent:收集当日社交对象兴趣候选 → `apply_daily_growth_decay` → `evolve_growth_profile` → 有变化则打印一行并落盘(STATEFUL)。受 `interests.enabled` + 新子开关门控。

### 配置(`settings/behavior.py` interests 下新增)
```python
"decay": {"enabled": True, "grace_days": 2, "daily_rate": 0.012, "floor": 0.05},
"evolution": {"enabled": True, "retire_after_days": 14, "adopt_chance": 0.35, "max_new_per_day": 1},
```

### Bug 修复
`_summary.py::_growth_diff` 改读 `items`/`total_minutes`/float level,并输出阶段变化。

## 三、不做什么
- 不动 `_action.py` 评分(已有 priority/level 项,阶段暂不进评分,避免行为大幅漂移)
- 不加 LLM 发现新兴趣(预算敏感;社会传染已提供动态性,后续可选)
- 不改 GrowthItem 持久化 schema

## 四、验证
- 单测:递减收益单调性、streak 动量、里程碑触发、衰减(grace/保持率/下限/streak 归零)、阶段边界、演化(放弃/传染/上限/确定性 rng)
- 回归:pytest 全量,重点 test_interest_*、test_curiosity_*、test_daily_routine_context
