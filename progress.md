# 进度日志

## 会话 2026-07-04:个人发展与兴趣系统增强(已完成)

### 已完成
- 调研现有系统,见 findings.md;发现并修复 _summary.py::_growth_diff schema bug
- 设计文档:docs/proposals/2026-07-04-personal-growth-v2.md(四视角专家评审)
- 实现(纯规则,零新增 LLM 调用,持久化 schema 不变):
  - interests.py:递减收益学习曲线、streak 动量、里程碑事件、growth_phase 四阶段(进 prompt 上下文)
  - interests.py:apply_daily_growth_decay(遗忘衰减,保持率随练习量、阶段感知)
  - interests.py:evolve_growth_profile(淘汰停滞触发期条目 + 社交传染习得新兴趣)
  - generative_city_sim.py PHASE 3c 日终接线(收集社交对象兴趣→衰减→演化→落盘→🌱打印)
  - settings/behavior.py:interests.decay / interests.evolution 配置块
- 测试:tests/test_interest_growth_dynamics.py 18 例全过;全量 527 过,6 失败均在干净 HEAD 复现(存量问题,与本次无关);ruff 无新增违规
- CHANGELOG.md 顶部新增 Personal Growth v2 条目(含 Docs 小节)
- 文档更新:README.md / README.zh-CN.md(特性 bullet、interests 配置说明、成长系统章节扩写,双语)、docs/TUTORIAL.v2.md §5.5 扩写+配置表行、docs/FEATURES.md 特性表行、docs/PROJECT_STRUCTURE.md interests.py 条目

### 遗留
- 用户需在宿主机删除 stale lock:`rm /Users/cw/dev/GAWorld/.git/index.lock`(沙盒 git stash 失败所致,工作区无损)

### 待办
无
