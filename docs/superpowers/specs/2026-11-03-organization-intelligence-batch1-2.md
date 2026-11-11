# 组织智能改造：第一批（可信度）+ 第二批（可运维）+ 前端修复

日期：2026-11-03。状态：**已实施并验证**（2026-11-05）。
背景与证据见 `docs/reports/` 下的审计记录与同期的代码审计结论；本文件只写**要做什么**。

## 0. 不变量

1. 默认仿真运行的产出不变，不追加 Epoch（本次只动研究工具与可选的合作任务路径）。
2. 冻结协议仍是唯一真相来源；影响执行的改动必须让旧实验**不能续跑**（靠 `engine_version` + `runtime_fingerprint` 兑现）。
3. 隐藏数据（`reference` / `constraints` / `rubric`）永不进提示词。
4. 不完整 ≠ 差：无法测量的单元标 `unmeasured`，不进均值、不产生结论。
5. 默认仿真配置、新建城市的默认行为、既有城市状态不改变。

## 1. 组织规则进入提示词

新增 `gaworld/collaboration/organization_methods.py::instructions(method) -> list[str]`：

```
instructions = [结构说明（由 kind/rounds/review/revisions/decision 生成）]
              + [规则文本（rules[].text）]
```

- 结构说明对每一臂都生成 → 「有没有指令」不再是混淆项。
- 论文规则只属于候选组；界面与报告明说，并推荐用「自定义对照」做规则级比较。
- `organization_engine.ask()` 的 payload 增加 `instructions` 数组（与 `task` 并列，不进 `messages`、不改 `role` 字符串）；`organization_engine.VERSION` → `organization-engine-2`。
- `protocol.freeze` 把 `instructions` 记进冻结协议，可审计可导出。

## 2. 因子化对比

机制拆成 5 个因子：`roles`、`topology`、`rounds`、`review`、`decision`。
协议新增 `factors: {factor: "same"|"candidate"}`，**默认只让 `topology` 不同**。

- `roles: same` → 基线角色名与候选完全相同，消除「分析/核对/决策」vs「成员 1/2/3」的命名混淆。
- 基线生成时按 factors 逐因子覆盖。
- `scope` 改为实际不同的因子集合（如 `["topology"]`）。
- 旧的 `comparison_mode` 值映射到 factors，旧协议仍可读。

## 3. 限额与启动前预检

```
per_cell_calls = n×(1+rounds+review+revisions) + (决策可能 +1)
calls          = per_cell_calls + 4
output_chars   = per_cell_calls × 3000      # 改为每单元累计上限
prompt_chars   = 12000 + output_chars
input_chars    = per_cell_calls × prompt_chars
```

协议允许上限相应上调（calls 400 / prompt_chars 5e6 / input_chars 2e7 / output_chars 2e6）。
UI 暴露四个限额；保存时预检并返回预计单元数、预计调用数、最早完成时间、限额是否够用；不够直接拒绝保存。

## 4. 可测性口径

行级新增 `measured` 与 `invalid_reason`：

| 情况 | 处理 |
|---|---|
| 模型答了但答案错/格式不符 | 计入预先声明的失败分 0（沿用现行口径） |
| `BudgetExceeded` / 评审上限 / provider 报错 | `measured=False`，不计 0 分 |

分析侧：`complete` 要求全部单元可测；即使不完整也输出两臂描述统计（均值、完成率、调用数、耗时、逐题错误分布），只是不给判定。报告写明「N 个单元未能测量，未计入比较」。

## 5. 可运维

- **build 指纹**：不采用「导入时捕获字节」的做法——改一行注释就会让所有已保存实验失效。改为**语义指纹**：`protocol.BUILD` + `organization_engine.VERSION` + `organization_methods.VERSION` + 协议 `VERSION`，语义变了才手动改版本号；文件字节另存 `code_fingerprint`，只进审计，不挡续跑。真正的保证是逐请求的提示词指纹：提示词对不上就抛 `ProtocolDrift`，该单元记为未测量。
- **写放大**：`record.json` 只在单元完成/状态变化时写；`waiting`/`last_request_at` 移到 `live.json`；请求与响应进 append-only `events.jsonl`。
- **并发**：`execution.POLICY` 增加 `concurrency`（默认 2，可配 1＝现状）与可配 `min_interval_seconds`（默认 10）；按 arm 派生独立种子。
- **同 provider 互斥**：补上 v1 已有的两道闸（同时最多 2 项、同模型互斥）。
- **单元级容错**：provider 报错只标记该单元未测完并继续（`automatic_retries` 默认 1）；评审连续 2 次无效 → 该单元未测完，不再永久砖化整个实验。
- **恢复白名单**：从魔法哈希白名单改为「重放校验通过即允许」。

## 6. 居民档案

- `population()` 追加 `big5`（若 `big5_csv_path()` 存在）与 profile 摘要（截断），进入 `member`。
- `make_caller` 接受并透传 `agent_id` 到 `LLMRouter.call`。

## 7. 前端

| 项 | 改动 |
|---|---|
| F1 | `.oc-error` 改用 house token `var(--red)`（暗色对比度 2.95 → ~6.7） |
| F4 | 拆 `invalidate()` 为 `invalidateDraft()` / `invalidateStudy()`；已保存实验被改动时明确提示 |
| F6 | 新增「复制本次设置」「删除记录」 |
| 预计 | 第 4 步显示预计单元/调用/最早完成时间/限额是否够用 |
| 因子化 | 「比较范围」换成因子复选组，默认只勾「通信结构」 |
| 不完整结果 | 第 5 步在无判定时仍显示描述统计与逐题错误表 |
| 可访问性 | 步骤面板加 `role="region"` + `aria-labelledby`；切步移焦；步骤条 `aria-live` 播报；`#ocBar` 加 `aria-label` |

## 8. 测试与文档

- 扩展 `tests/test_organization_comparison_workbench.py`。
- 新增引擎级测试：指令进提示词、两臂角色名一致、累计输出上限、限额失败不产生判定、不完整时仍有描述统计、语义指纹随版本变而不随文件变、提示词变了不评分（`ProtocolDrift`）。
- 前端 node:test（`site/dashboard/organization-comparison-core.test.js`）：因子默认与 `applyFactors`、时长显示、settings 带 factors。
- 浏览器冒烟（`tests/test_browser_smoke.py`）：因子复选组默认只勾「通信结构」，采用规则后说明文字点名允许不同的因子。
- 更新 `docs/ORGANIZATION_INTELLIGENCE_TUTORIAL.md`。

## 已确认的两处判断

1. `output_chars` 语义从「每次回答上限」改为「每单元累计上限」。
2. 默认因子 = 只让通信结构不同（默认 scope 由 whole_method 变 topology）。

## 实施结果（2026-11-05）

第 1–8 节全部落地，代码与文档已改完，验证如下：

| 项 | 落点 |
|---|---|
| 指令进提示词 | `gaworld/collaboration/organization_methods.py::instructions`、`organization_engine.VERSION = organization-engine-2`、协议冻结 `instructions` |
| 因子化 | `comparison/protocol.py::FACTORS/resolve_factors/apply_factors/differing_factors`；默认只差 `topology` |
| 限额与预检 | `organization_methods.estimate`、`comparison/protocol.py::_LIMIT_MAX`、`POST /comparisons/plan` |
| 可测性口径 | `comparison/runner.py` 行级 `measured/invalid_reason`；`comparison/analysis.py` 恒输出两臂描述统计 |
| 语义指纹 | `protocol.runtime_fingerprint()`（版本语义）+ `protocol.code_fingerprint()`（仅审计）+ 逐请求提示词指纹 → `ProtocolDrift` |
| 写放大 | `comparison/store.py` 拆 `record.json` / `live.json` / `events.jsonl` / `cells/` |
| 并发与容错 | `comparison/execution.py::POLICY`（2 路、10 s、可配）、同 provider 互斥、单元级 `automatic_retries`、评审 2 次即 `ScoringLimit` |
| 恢复 | `comparison/recovery.py` 改为「重放校验通过即允许」 |
| 居民档案 | `organization_intelligence_api.population()` 追加 `big5` 与 `profile`；`make_caller` 透传 `agent_id` |
| 前端 | F1/F4/F6 + 预计面板 + 因子复选组 + 不完整结果的描述统计 + `role="region"`/移焦/`aria-live` |

验证：61 个 Python 用例、15 个 node 用例、浏览器冒烟 1 条全部通过；`scripts/lint_ratchet.py` 无新增问题；
真实模型（本地 ollama `gemma4:e4b`）跑通三条路径——完整运行（4/4 单元、0 未测量）、暂停/继续（复用已保存回答）、
崩溃后恢复（重放校验 12 条回答、复用的 4 个单元不重跑）。演练产生的实验记录已删除。

## 9. 收尾批次（2026-11-05）

### 9.1 收敛三套并存实现

组织智能一度有三套实现同时存在，用户不知道该用哪一套。收尾后的结构是「一条主路 + 两个非跑手表面」：

| 表面 | 收尾后 | 理由 |
|---|---|---|
| 对照实验 `comparison/` | **唯一能发起模型实验的入口** | 因子化、配对、限额、可测性口径都在这里 |
| 旧实验 `organization_intelligence/`（v1） | **只读历史 + 可续跑**：去掉「新建实验」，保留列表/详情/导出/日志，以及把当年存下但没跑完的实验接着跑完 | 新实验一律从对照实验发起；旧记录仍在盘上，可读、可导出、可续跑，不丢能力 |
| 团队交接模拟 `v2/` | 保留，按功能改名 `handover/`，路由改为 `/api/research/team-handover/` | 它不是模型实验（零模型调用），是另一种研究，不该叫「v2」 |

同时把三处共用的原语（居民名册 `population()`、模型信息 `model_info()`、调用器 `make_caller()`）从旧的 API 模块搬进
`gaworld/research/organization_intelligence/common.py`：主路不再 import 一个叫 `legacy` 的模块。

旧实验的数据原地不动：仍在 `output/research/organization_intelligence/OI*`，编号与内容都不变。团队交接的文件夹随代码一起改名（`.../v2/` → `.../handover/`），里面的三份既有研究一起搬过去，编号 `OI2*` 保持原样。

### 9.2 多候选并列比较（n 臂）

两臂能回答「这种组织方式比基线好吗」，回答不了「A、B、C 三种组织方式谁更好」。协议因此从「候选 + 基线」改为**臂的列表**。

- 协议新增 `arms`（有序列表）。每项：`id`、`label`、`method`（最终方法）、`factors`（相对基线）、`seed_offset`。
  - 旧协议没有 `arms` 时按两臂回退（`candidate` 偏移 0、`baseline` 偏移 1），保证旧单元的种子不变。
  - `instructions` 由 `{candidate, baseline}` 改为按臂 id 存。
- `protocol.VERSION` → `organization-comparison-2`：臂集合进了协议，语义变了，旧实验只能走「重新运行（保留进度）」。
- 每个候选带**自己那套因子**：`apply_factors` 按候选分别与基线对齐，`scope_factors` 变成按臂记录。
- 单元数 = 题数 × 重复 × 臂数；每一臂各自一次评审；限额取各臂的最大值。
- 统计：每臂的描述统计照旧；每个候选与基线各有一条配对差、bootstrap 置信区间与判定
  （判定门槛不变：少于 30 道独立题只作探索）。
- 前端第 1 步可增删候选：主候选是当前编辑的那份，附加候选从合作任务保存过的组织方式里选（最多 3 个，合计 4 臂）。
- 单元 id 从 `题:重复:candidate|baseline` 放宽到 `题:重复:candidate(-N)?|baseline`，旧单元 id 不变。
- 结论：第一个候选的判定是主结论；其余候选在结果页各自列出判定、差异与区间。

### 9.3 跨实验汇总与代价面板

组织智能页下方新增「所有实验的汇总与代价」：把这个世界里做过的对照实验放在一张表里——日期、状态、结论、参与的
组织、实际调用次数、输入输出字符、调用耗时，并给出全部实验的合计与平均。

金额不估算：配置里没有单价，字符不是 token，模型没有返回可靠计量时标为未知。接口是
`GET /api/research/organization-intelligence/comparisons/summary`。
