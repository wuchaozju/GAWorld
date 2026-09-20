# 研究与发现:个人发展与兴趣系统现状

## 现有架构
- `gaworld/interests.py`:GrowthProfile(每 agent,LLM 推导+规则 fallback,cache+`agent_N_growth.json` 持久化)。GrowthItem 字段:name/kind(hobby|skill)/category/motivation/level/priority/weekly_target_minutes/preferred_time_blocks/activity_templates/career_link/sociality/last_practiced_day/total_minutes/streak_days
- 接入点:
  - `sim/_action.py` ~L499-543:growth 匹配加权动作评分(growth_skill/growth_interest/growth_career 分量)
  - `cognition/realism.py`:每日意图含 growth_focus(0-2 项);format_growth_context 进 prompt
  - `sim/_curiosity.py`、`sim/_rag.py`、`memory/ingest.py`:growth_focus 喂好奇心搜索词与 RAG 查询
  - `generative_city_sim.py` ~L3828:每步 episode 后 update_growth_from_episode(关键词匹配→minutes+level 上升),STATEFUL 时落盘
  - `apps/dashboard_server.py` L406:暴露 growth profile;`work/capabilities.py` L152 用于工作能力
- 日终钩子:PHASE 3c(generative_city_sim.py ~L4048):consolidate_day、decay_relationships、enforce_dunbar、日记;之后 hook_bus.emit("on_day_end")。可在此接成长日终 tick
- 配置:`settings/behavior.py` human_realism_settings()["interests"]:enabled/max_items/daily_insert_chance/weekend_boost/progress_minutes_per_step/cache_path

## 缺陷(专家小组视角)
1. **level 只升不降**:无遗忘/技能萎缩;练习增益与当前水平无关(真实学习是幂律递减收益)
2. **兴趣集静态**:bootstrap 后 items 永不变(除非 profile 文本变);无新兴趣发现、无放弃
3. **streak_days 有记录但无任何作用**;sociality 字段无消费方
4. **无社会传染**:agent 不会从社交对象处习得兴趣(经典 ABM 机制缺失)
5. **无里程碑/自我效能反馈**:升级不产生可感知事件(日记/反思无法引用)
6. **BUG:`sim/_summary.py::_growth_diff` 读 `growth_profile.interests`/`minutes`/int level,实际 schema 是 `items`/`total_minutes`/float level → 永远空 diff,成长报告失效**(与 memory 里 ABM validation schema bug 同类)

## 测试现状
- tests/test_interest_growth_updates.py、test_interest_growth_profile.py、test_interest_daily_routine_prompt.py、test_memory_growth_boost.py
- 测试用 unittest 风格,profile 用 dict 字面量构造

## 理论依据
- Hidi & Renninger 兴趣发展四阶段:触发期→维持期→浮现期→成熟期(可由 level/total_minutes/streak 推导)
- 幂律学习曲线(收益随水平递减);间隔遗忘(不练则衰减,累计练习量提高保持率)
- 兴趣的社会传染/同质性扩散(ABM 常用机制)
