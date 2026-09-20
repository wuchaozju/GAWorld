# AAAI-27 投稿说明：GAWorld-Bench

## 投稿定位

- 会议：AAAI-27 Main Technical Track
- 首选领域：Multiagent Systems
- 论文题目：*GAWorld-Bench: A Layered Validation Framework for LLM-Based Artificial Societies*
- 摘要截止：2026-07-21 23:59 UTC-12
- 全文截止：2026-07-28 23:59 UTC-12
- 补充材料与代码截止：2026-07-31 23:59 UTC-12
- 正文限制：7 页；全文最多 9 页，第 7 页之后只能是参考文献
- 当前版本：匿名审稿稿，不含作者和单位信息

官方页面：<https://aaai.org/conference/aaai/aaai-27/main-technical-track-call/>

## 一句话主张

LLM 人工社会不能凭单一逼真度分数或少量合理案例成为“科学仪器”；其宏观拟合、涌现规律、
反事实有效性、个体一致性和可复现性必须分别验证，并由不可被平均抵消的信任门槛约束。

## 三项贡献

1. 提出分层验证框架，把常被混为一谈的五类有效性命题拆开。
2. 实现 GAWorld-Bench 的 provenance、宏观与反事实检查、coverage reporting 和确定性模式子测试；
   其余轨道是协议规范，尚未全部实现。
3. 对现有 GAWorld 产物进行审计，展示时间窗口、跨运行不稳定、缺失证据和 synthetic fixture
   混入 headline scorecard 时如何导致过度解读。

## 论文明确不作出的主张

- 不声称 GAWorld 能预测真实城市或真实政策效果。
- 不声称现有单次运行具有统计显著性。
- 不把当前 `scorecard.json` 的 0.9361 或 4/4 known-sign 当作真实模型性能。
- 不把一个智能体的经济快照视为总体宏观拟合。
- 不把未完成的情绪、网络和记忆实验写成已验证结果。

## 关键审计发现

- 当前真实经济快照只有 1 个智能体：恩格尔系数 0.48、储蓄率 0.05；历史真实报告中的另一个
  单智能体快照为 0.30、0.25。
- 0.290 和 0.328 的“漂亮宏观结果”来自 synthetic fixture，不是真实仿真输出。
- 交通限行对 mobility intent 的记录值：全程均值差 +0.0068，终态差 +0.3368，量级相差约 49 倍。
- 减税对 economic security：全程均值差 -0.0086，终态差 +0.0201，窗口选择改变符号。
- 2026-06-20 的单次裁员运行给出 economic security -0.0498、stress +0.1717；2026-07-09
  的单观测批次则为 +0.0826、+0.0078，不能据此作因果推断。
- 当前 headline scorecard 的 +0.08、-0.12、+0.09、+0.06，以及完美 placebo/determinism，
  与 `make_synthetic()` 完全一致。这是强烈的 fixture-like 数字指纹，但缺少生成日志，不能单凭
  数值证明 lineage；只能作为评测代码路径检查。

## 主要投稿风险

- **实证深度不足**：没有新的多随机种子实验，主赛道审稿人可能认为框架演示不够充分。
- **创新性边界**：需要强调贡献不是复述传统 ABM validation，而是面向 LLM 人工社会的
  claim-evidence 分层、provenance separation 和 non-compensatory trust gate。
- **单案例风险**：目前只审计 GAWorld；正文已明确该限制。
- **仓库版本风险**：审计材料跨越多个日期和代码状态，因此用于揭示 provenance/measurement
  问题，不用于模型版本排名。
- **归档可比性风险**：不同日期的 code、prompt/provider、population 和 baseline lineage 未被共同
  保存，因此论文只称这些输出不可直接比较，不把差异归因为随机种子不稳定。
- **匿名性风险**：系统名、精确报告文件名和内部路径可能被公开搜索反推。提交前需要制作去除
  Git 历史、用户名、日志身份字段和公开链接的匿名 artifact package。
- **外部有效性缺失**：没有真实受影响群体参与，也没有政策现场验证。
- **引用责任**：全部参考文献已依据 DOI、出版社、OpenReview、arXiv 或官方统计页面核验，但最终
  作者仍需逐条人工确认。
- **AI 辅助写作责任**：作者必须检查所有文字、数据、引用与潜在重复，并对投稿内容承担全部责任。

## 当前文件

- `main.tex`：AAAI-27 匿名正文
- `main.pdf`：编译后的匿名正文
- `supplementary.tex`：技术补充材料
- `supplementary.pdf`：编译后的补充材料
- `references.bib`：已核验参考文献
- `figures/validation_layers.pdf`：五层验证框架图
- `figures/evidence_pipeline.pdf`：证据来源与 trust gate 流程图
- `README.md`：模板来源、哈希、证据台账和离线复核命令
- `aaai2027.sty` / `aaai2027.bst`：官方 Author Kit 原文件

## 设计验收状态

- [x] 使用 AAAI-27 官方模板
- [x] 匿名审稿格式
- [x] 未运行新的仿真或 LLM API
- [x] 真实、诊断、合成和缺失证据分离
- [x] 数值主张映射到仓库产物
- [x] 未作统计显著性或真实政策预测主张
- [x] 参考文献来自可核验的一手来源
- [x] 完成最终逐页视觉复核
- [x] 完成新读者与对抗性审稿测试，并修正 gate、coverage、状态语义和跨日期归因
- [x] 确认正文共 5 页，参考文献自第 5 页开始，未超过正文 7 页/全文 9 页限制

## 提交前必须由作者完成

- [ ] 确认最终作者名单、排序、单位和通讯作者
- [ ] 完成所有作者的 OpenReview 账户与个人资料要求
- [ ] 填写全部 conflict domains
- [ ] 确认作者评审义务与现场参会安排
- [ ] 逐句核验 AI 辅助文字并运行查重/自我重复检查
- [ ] 逐条打开参考文献并核验题目、作者、年份、页码和 DOI
- [ ] 检查匿名代码/数据链接不会泄露作者身份
- [ ] 完成 AAAI reproducibility checklist
- [ ] 在摘要、全文和补充材料截止时间前分别上传
