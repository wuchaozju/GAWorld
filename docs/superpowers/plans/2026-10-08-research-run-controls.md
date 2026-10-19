# 研究运行控制与进度实施计划

**目标：** 按用户指定的功能，在研究卡片持续显示暂停／继续、停止、进度和大致剩余时间。

**架构：** 复用研究任务、暂停和停止事件及 ExperimentRunner，不新增路由或仿真子系统。新增独立计时器，通过任务与研究详情返回进度快照；前端轮询同时刷新运行状态。仿真进程即时挂起，问卷、评分和解读在当前调用结束后检查控制事件；停止保留现有产物并禁止后续报告生成。

**技术：** Python threading、monotonic 时间、原生 JavaScript、pytest、浏览器检查。

- [x] 在 tests/test_research_study.py 新增计时、停止解读、暂停末尾阶段和任务详情测试，先确认失败。
- [x] 在 gaworld/research/progress.py 实现独立计时和 ETA；暂停时冻结活动时间，完成和停止不返回 ETA，进度为零／样本不足时返回 null。
- [x] 在 gaworld/apps/research_api.py 接入计时，添加末尾阶段检查点，停止返回停止状态而非完成及 100%；研究详情附任务快照。保留现有权限、路由和磁盘格式。
- [x] 在 gaworld/research/backends.py 为问卷世界之间增加暂停和停止检查，补全新种子准备期间的停止检查。
- [x] 修改 site/dashboard/research.js/css 与中英文 locale：固定进度卡片，控件覆盖全部 live 阶段，每轮刷新状态，避免旧请求影响另一个研究。
- [x] 执行研究相关、OpenAPI 和 core 测试；用模拟任务验证真实页面的暂停、继续、停止、刷新及窄屏布局，不运行付费研究。
- [x] 更新 docs/RESEARCH_WORKBENCH_TUTORIAL.md，说明时间估计和控制生效边界。

不修改用户既有未提交改动，不启动真实研究或提交 Git。
