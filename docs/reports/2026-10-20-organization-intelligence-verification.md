# 组织智能实验模板实施与实跑验收

2026-10-20，GAWorld 本地工作区。功能已实现，首项真实研究已启动但因格式失败终止，科学比较未完成。

## 实现范围

研究工作台新增「组织智能」及《人换了，组织还会吗？》模板。独立研究包、用户/世界隔离的API、不可变协议与模型/代码指纹、固定模型执行、逐请求审计、请求边界停止、代码评分、不完整结果门控、Markdown/协议/审计导出。前端显示实际HTTP、活动/日历/暂停时间、粗略ETA；列表随轮询同步。默认仿真行为及现有城市状态未改变。

## 工程检查

- 核心套件：489 passed，1 skipped，789 subtests passed；69.74秒。日志 `/tmp/gaworld-oi-core.txt`。跳过项为未安装可选 openapi-spec-validator。
- OI-1.1 定向后端/API/OpenAPI/成员权限：51 passed，1 skipped，729 subtests passed；16.73秒。
- 前端：7 passed（4项组织智能、3项研究批次）；包含冻结与启动分离、未完成结果门控、转义、轮询列表同步。
- 新Python文件 Ruff check 与 format check通过；git diff --check通过。
- 全仓库 lint ratchet 未通过，来源为其他工作中的 docs/handbook 脚本：capture_console、capture_shots、diagram_specs、make_diagrams、make_reference_docx。未改动这些不相关文件。Ruff版本也与旧基线不同。
- 浏览器：真实创建冻结协议、显式启动、观察非零响应、失败状态与导出按钮；窄屏页签可换行。固定MiniMax-M3，即使当前全局默认模型已经改为M3.1-Flash。
- 冻结验收：协议SHA-256、四个实验源码指纹与磁盘一致；新旧协议除版本外完全一致，人口/任务/评分真值/调用预算/模型均保持。

## 真实运行

1. `OI483361061c3f4348b4f228c7`，OI-1，12请求后人工停止。原始任务接口有数组与方案序号歧义，单列诊断，不进入研究比较。
2. `OIa6c87ad6c429489f832ce013`，OI-1.1，计划327请求，实际11请求，活动/日历40.7秒、暂停0秒。10份回答解析成功，第11份因字符串内未转义引号解析失败并按协议终止。HTTP失败0，回退0，额外重试0。全部原始证据与失败报告已保存。

累计23次真实请求，不能报告组织收益或显著性。当前没有继续消耗模型请求的运行任务。本轮没有自动放宽协议或启动第三次研究。

入口：http://127.0.0.1:8767/site/dashboard/research.html?tab=organization-intelligence&oi=OIa6c87ad6c429489f832ce013

产物：`output/research/organization_intelligence/<id>/` 下 protocol.json、study.json、events.jsonl、providers.sqlite、report.md、diagnostic.md。服务独立后台运行，PID记录于同目录上层dashboard.pid。运行产物保持本地，不提交；保留其他未提交工作。
