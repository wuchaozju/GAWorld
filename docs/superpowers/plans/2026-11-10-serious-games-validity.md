# Serious Games Validity Implementation Plan

> 执行方式：本会话按任务内联实施；用户已确认完整设计，不另行请求执行选择。采用测试先行，完成后依 requesting-code-review 技能做独立审阅。不自动提交混有并行修改的工作区。

**Goal:** 完整实现已确认的六项反馈，兼容已有游戏与对局。
**Architecture:** 保留应用入口，将角色匹配、协商状态与指标规则拆到 gaworld/research 的独立模块；前端通过已有严肃游戏面板编辑、预览、行动和干预。v1 会话保持原语义，新机制版本化。
**Tech Stack:** Python 3.11+，pytest，原生 JS，node:test；沿用现有 HTTP/ownership/OpenAPI。

## Task 1: schema 与角色匹配
- [x] 创建 tests/test_serious_game_validity.py：未知资格拒绝、固定种子、全局一对一、手动重复拒绝、版本兼容。
- [x] 运行 python -m pytest tests/test_serious_game_validity.py -q，确认新测试失败。
- [x] 新建 gaworld/research/game_casting.py，提供 validate_conditions / match_roles；在 serious_game.py normalize_spec/new_session 中接入，新设计版本为2，旧设计无版本为1。
- [x] 提供 serious_game_api.py 匹配预览；校验开局匹配，不依赖前端声明。

## Task 2: 协商、利益、指标规则
- [x] 新测试覆盖同版本签署、改版失效、预算耗尽、延期、搁置、退出、部分协议、公共/私有权限、资源转移、规则上下界和定义可比。
- [x] 新建 gaworld/research/game_negotiation.py 与 game_rules.py。结构化意图、提案、接受记录；按冻结规则判定 outcome，主持文本不能签协议。
- [x] 接入 record_action/parse_agent_action/agent_prompt/apply_resolution/debrief/public_view/export；模型叙述与确定性计算分开。
- [x] 新 schema 接收预注册指标定义、私人值与收益规则；无规则的变化标记为模型估计，私密结果不进入参与者公共视图。

## Task 3: 回合边界干预
- [x] 测试 pause/continue/intervene/new role 的权限、幂等、结算排队、已提交行动与重启；先看失败再实现。
- [x] serious_game_api.py 增加预览、边界暂停、继续、终止、干预；持久化队列和应用记录。保持 ownership.spawn。
- [x] gaworld/apps/openapi.py 记录所有路由及结构化行动字段。

## Task 4: 前端工作流
- [x] 新建 site/dashboard/serious-game.test.js，以实际渲染输出测试时间顺序、隐私、匹配、提案及回合边界控件。
- [x] serious-game.js 增加可编辑设计、匹配预览、模式选择、真人结构化行动、干预与结局；保持草稿、焦点与滚动。
- [x] research.css 添加复用页面令牌的样式；locale 文件只按本任务新增键。
- [x] node --test site/dashboard/serious-game.test.js 验证后，用本地假后端浏览器验收中文/英文、深浅色和390px。

## Task 5: 同居剩余调度
- [x] 先运行新近已有 tests/test_roommate_continuity.py 并检查实际变更。
- [x] 在新 tests/test_roommate_engagement.py 覆盖清醒长时间独处的共同事务、忙碌/睡眠不强迫、模型超时不产生假对话、冷却与状态。
- [x] 增加独立 gaworld/apps/roommate_engagement.py 并最小接线，保留已有连续性实现。

## Task 6: 验收与交付
- [x] python -m pytest tests/test_serious_game.py tests/test_serious_game_validity.py tests/test_roommate_api.py tests/test_roommate_continuity.py tests/test_roommate_engagement.py tests/test_openapi.py -q
- [x] python -m pytest --suite core -q；node 前端相关套件；python scripts/lint_ratchet.py。
- [x] 独立代码审阅并修复影响行为、权限、恢复的缺陷。
- [x] 更新 docs/RESEARCH_WORKBENCH_TUTORIAL.md；写 docs/reports/2026-11-10-serious-games-validity.md，准确区分规则验证与未进行的真实模型评估。
