# 研究工作台可靠性改造验证

日期：2026-11-10。用户已确认设计，当前 checkout 增量实施；大量并行的游戏、人口教育、调查等改动保持原样，未提交。

## 实现

- 可解释方法量表、逐设计保留/替代映射、可编辑原论文设计及来源核对；完整文本与模型前缀分开保存，超限明确标记。历史评分保留旧版标识。
- 统一编译/编辑/批准/启动/批次的预算策略；明确规划额度与实际 HTTP 尝试硬预算。管理员可显式申请部署范围内的更高额度，成员继续受账号数据库限额约束。实际人口 CSV 用于估算，避免「全部居民」被默认按五人计数。
- 批准绑定实际输入、模型与备用模型配置、运行参数及有效策略；旧批准或变化后的输入要求重新审阅。按天简报不伪造 social_need，规模修订保留条件、指标和观察天数。
- 共享 SQLite 账本在发送前原子预留请求；覆盖重试、备用路由、授权方案重试和多进程争用。预算化请求不自动跟随重定向，以免产生未经预留的额外提交。预留后进程退出可能保守消耗额度，不能因此超发。
- 人口任务持久化元数据与独立结果，按用户/世界隔离，提交幂等及有限重连；研究失败记录采用脱敏分类及可执行下一步。基础人口合成不依赖模型。

## 验证与证据

- 核心套件：`python -m pytest --suite core -q --disable-warnings --tb=short`，515 passed、1 skipped、980 subtests。跳过项为可选 openapi-spec-validator 未安装。
- 新增故障、预算、评分与来源回归先观察到预期失败，再实现；包括真实进程共享 HTTP 预留、不可绕过的备用路由预算、来源与模型变化后重新批准。
- 前端：`node --test site/dashboard/research*.test.js site/dashboard/population*.test.js`，37 tests passed；人口 UI 脚本另含 39 项断言。覆盖 POST 回包丢失、无 localStorage、有限重连、手动重连、刷新、旧响应隔离及安全转义。
- 受控浏览器：`python tests/browser/research_flow_acceptance.py`。评分表、social_need 不兼容提示和 HTTP 预算可见；生成/编译/解读刷新恢复，4 次刷新不重复提交，3 个原 POST；1440px 浅色、390px 浅色/深色无横向溢出，无页面错误。产物在 `output/research-flow-verification/`，不纳入提交。
- `git diff --check` 通过。完整 lint ratchet 的本轮相关文件增量通过；仓库整体仍会随其他并行改动显示未格式化或 lint 项，未改动它们，也未更新 baseline。providers.py 原有两条 Ruff 提示保留。

## 审查与边界

独立审查发现并补强：备用模型与人格/家庭文件必须绑定批准；人口后续任务需要固定所选快照，避免多页并发切换输入。后续聚焦回归的最终结果记录在本报告的补充验证段。

本轮没有运行真实模型实验或新的付费研究，没有修改原实验结果，没有重启当前 Dashboard 服务。后端 Python 修改须由新服务进程加载。代码与受控验收不证明服务商当前配额、连接或真实研究结果有效，也不能凭信号终止直接断言内存不足。截图特定二十分钟停止的个案仍缺少对应原日志，未声称已还原原因。

## 补充验证

最终研究/LLM、凭据、HTTP、人口任务与 OpenAPI 集中回归：`python -m pytest tests/test_research*.py tests/test_llm*.py tests/test_gaworld_llm_fallback.py tests/test_dashboard_population.py tests/test_population_job_recovery.py tests/test_openapi.py -q --disable-warnings --tb=short`，511 passed、1 skipped、919 subtests；跳过项同上。独立审查后人口测试76 passed，无剩余阻断发现。

最终 lint ratchet 仍由并行改动中的 `gaworld/research/model_provenance.py`、`gaworld/research/replication_export.py` 与 `tests/test_serious_game_validity.py` 阻止全仓通过。本轮专属模块 Ruff 检查及 diff-check 通过；未替其他任务清理或更新基线。
