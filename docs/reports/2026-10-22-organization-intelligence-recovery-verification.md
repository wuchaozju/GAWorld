# 组织智能限流与恢复验收

2026-10-22。针对记录 OI39f72dc5bb1a41ea92388469：第7次HTTP提交返回429/2062，前6份回答有效；不是任务得分失败。服务商的Token Plan限制不能由本地程序解除。

## 修复

- OI-1.2冻结执行政策：请求开始间隔至少10秒，同一进程同一模型只运行一项OI研究。429进入rate_limited，停止后续提交；普通429本地退避至少60秒，2062至少300秒，遵循更长的Retry-After，不自动重试。该下限不是服务商配额恢复承诺。
- 本世界同一模型的新草稿也遵守持久化退避，防止不断新建绕过等待。服务商账户可能同时受其他研究、世界或程序用量影响，因此仍可能继续429。
- 新增POST /api/research/organization-intelligence/<id>/recover：只生成关联恢复草稿，不调用模型。新版本冻结原人口/题库/顺序/评分/模型与有效回答快照；严格核对原请求和回答后重建记忆。连续恢复、重放中途停止、末尾UTF-8部分写入、Unicode分隔符都有回归覆盖。
- OI-1.2允许对完整choice/message对象进行保守的本地引号/换行转义。拒绝缺失/重复/额外字段、无效编号、歧义边界、截断内容。始终保留原文、选择与审计标记，无额外模型修复调用。旧协议仍保留其原有判定。
- 页面展示配额原因、最早重试下限、恢复入口；传输详情折叠。复用数、有效回答、本地格式恢复与HTTP统计分别显示。ETA以新调用速度及未来节流估算，复用不虚增执行速度。
- 原研究与恢复链属于同一次研究，不作为额外独立重复，不汇总其他失败记录。未完成时仍不比较条件或推断组织收益。

## 验证

- 定向：76 passed，1 skipped，805 subtests passed，17.81秒；日志 /tmp/gaworld-oi-recovery-focused.txt。跳过项是未安装可选openapi-spec-validator。
- 前端：8 passed（5项组织智能、3项研究批次）。
- 核心：490 passed，1 skipped，865 subtests passed，71.16秒；日志 /tmp/gaworld-oi-recovery-core.txt。
- Ruff新/改Python文件检查与格式检查通过，lint ratchet通过，git diff --check通过。基线与安装的Ruff版本不同，ratchet按已有规则提示全仓统计差异，改动文件未新增问题。
- 仿真HTTP：实际LLMRouter+Anthropic provider+RunLedger走通，requests.post在本地模拟前6次200、第7次429/2062；断言7次HTTP提交、1失败、0回退、6有效回答，且不继续提交。没有外网模型请求。
- 独立代码审查指出的恢复链、转义反斜杠奇偶、ETA、审计末尾解码边界均已补回归并修复。
- 真实浏览器/API/磁盘：旧失败页显示等待配额恢复；点击恢复生成新草稿；新草稿与当前模型/代码/协议/回放快照哈希一致。

## 已准备的恢复草稿

OI6969d454efb3430ca5515026，OI-1.2，MiniMax-M3，乌镇，3组。

来源OI39f72dc5bb1a41ea92388469，冻结6份有效回答，尚未启动，HTTP提交0。启动后从第7步请求，剩余321次成功步骤；失败后的手动恢复可能另产生失败HTTP尝试，所有尝试单列。原记录study.json/protocol.json/events.jsonl的SHA-256与修复前一致。

入口：http://127.0.0.1:8767/site/dashboard/research.html?tab=organization-intelligence&oi=OI6969d454efb3430ca5515026

产物：output/research/organization_intelligence/OI6969d454efb3430ca5515026/{protocol.json,study.json,replay.json,report.md,recovery-draft.png}。

本轮新增真实模型调用：0。尚未验证MiniMax套餐当前是否恢复。没有升级套餐、改为按量计费、切换模型、自动恢复或产生研究结论。服务已在8767更新，旧研究产物未改写。


## 追加：第107次代理连接断开

用户报告OIbd3d1b0e273d47d2b45f1b2e（旧OI-1.1）在第107次失败。原始错误是ProxyError / Unable to connect to proxy / RemoteDisconnected，前106份回答均有效，服务没有返回本次模型回答。一次不带密钥的HEAD探测收到HTTP404，证明探测时网络已能收到服务器响应；它不验证模型生成、账户额度或持续稳定性。

已建立恢复草稿OI28957b8be3164efab2ad09e7（OI-1.2），冻结106份逐步校验通过的原回答、原题库和原MiniMax-M3模型，启动后从第107步继续，剩余221步。源文件SHA-256不变，新模型提交0；未自动启动恢复。新草稿已通过实际API、浏览器和磁盘哈希验证。

前端对ProxyError显示「代理连接中断 · 断点已保存」，并提示检查代理服务/网络后恢复；不再用笼统的回答异常描述。新增红/绿回归，当前前端9项通过，diff检查通过。此次仅修改前端，不改变实验源码指纹；已有恢复草稿不会因此失效。

截图和诊断位于output/research/organization_intelligence/OI28957b8be3164efab2ad09e7/。
