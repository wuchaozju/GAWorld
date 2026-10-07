# glf 分支审查与合并结论

核验时间：2026-10-07。已执行 `git fetch origin --prune`。

**结论：当前远端 glf 不需要再整分支合入 main 或 Dev，也没有发现需要单独摘取的新功能。**
这不是因为分支比较旧就放弃合并，而是检查了历史、合并提交的冲突处理和实际试合并结果。
本次只推送审查和测试文档，不合并 glf，不修改 main、Dev，不发布运行时代码。

## 当前版本

| 引用 | 提交 | 说明 |
| --- | --- | --- |
| origin/main | `581b12acd5b48bbab6707467e27092cc6f03fe9a` | 已发布的整合主线 |
| origin/Dev | `581b12acd5b48bbab6707467e27092cc6f03fe9a` | 与 main 完全一致 |
| origin/glf | `cec3342b527e71824cfa3b1a24b03a0d00a5e78a` | 2026-09-20，merge latest Dev into glf |

`main...glf` 的左右独有提交数是 **34 / 1**。glf 唯一独有提交是合并提交 `cec3342`，没有独有的非合并提交。
该提交的两个父提交分别为旧 main `ebdad18` 和旧 Dev `8f45771`，两者均已是当前 main 的祖先。

不能仅凭这些计数判断无需合并：合并提交也可能包含新的人工修复。因此继续检查了
`git show --remerge-diff cec3342`，并使用 Git 的真实合并算法进行不修改工作区的试合并。

## 试合并及功能冲突

`git merge-tree --write-tree --name-only origin/main origin/glf` 返回 1，产生以下 9 个冲突文件。
返回 1 在此表示存在冲突，不是服务或测试崩溃；没有执行实际 `git merge`。

| 冲突文件 | 实际差异及风险 | 建议 |
| --- | --- | --- |
| `README.md` | glf 一侧缺少主线新增的群体采访介绍 | 保留 main，不删除新版说明 |
| `README.zh-CN.md` | 同上 | 保留 main |
| `dashboard_config.json` | 冲突局部是文件结尾及换行差异，无新增配置项 | 不作为功能变更引入 |
| `data/hangzhou_profiles_with_names.v1.md` | 冲突局部是文件末尾空行，无新档案 | 不改现有人物映射 |
| `data/news_cache.json` | glf 是较旧缓存，包含带换行的异常 URL 和网页不可用提示 | 不用旧生成缓存覆盖当前缓存 |
| `generative_city_sim.py` | glf 一侧缺少 `start_manifest` 导入；主线后续代码仍调用它 | 必须保留 main，否则存在运行时缺少符号风险 |
| `site/dashboard/app.js` | glf 一侧缺少 `runningCity`、`browsing`、`browsedCity`、`browsedAgents` 状态定义 | 保留主线跨城市浏览状态，避免回退现有前端契约 |
| `site/dashboard/index.html` | glf 使用不带版本参数的样式链接，main 带缓存版本参数 | 保留 main，不恢复过期引用形式 |
| `tests/test_distributed_comm.py` | glf 一侧缺少主线新增的社交快照及隐私相关用例 | 保留 main 的回归保护 |

试合并树与 main 的差异**仅在上述 9 个冲突文件**，不存在额外的无冲突文件变更。
逐项检查后，在独立临时 Git index 中做了一个假设比较：9 个冲突文件均保留 main 的完整内容，
生成的树哈希为 `593ba7ee9d1caaf35b1a275f90e719697de83f46`，与当前 main 的树哈希完全相同。

这个比较仅用于证明“本次试合并没有其他被遗漏的净变化”。未修改真实 index 或任何工作区文件，
未生成合并提交，也不是倡导以后所有冲突都选 main。
机器可读结果见 [审计证据](GLF_BRANCH_AUDIT_2026-10-07.json)。

## 为什么直接看文件差异会误判

两条分支有两个最佳共同祖先：`8f45771` 和 `ebdad18`。
`git diff main...glf` 因此会提示 multiple merge bases，并选择其中一个；不能把它列出的全部文件都理解为 glf 的新工作。
而 `git diff main glf` 比较的是两个最终快照，既包含旧功能残留，也包含 glf 尚未同步的主线功能。
直接用 glf 文件覆盖 main 会造成回退，不等于完成正常合并。

glf 保留的旧 LifeHistory、Personal What-if、规划 AB 引擎及报告来自先前旧 main，
不是 9 月 20 日之后新增的未审查功能。此前已按确认的实验模型决策归档到
`archive/main-before-dev-2026-10-06`，新版采用 Dev 的连续情绪、社交模型和研究工作台。
独立可复用的 Relay 功能已经迁入新主线。具体取舍见
[主线整合说明](DEV_MAIN_MERGE_REVIEW_2026-10-07.md)。

## 协作建议

1. 保留 glf 原分支和旧模型归档，不删除、不强推、不伪造一个无内容的合并来消除提交计数。
2. 没有未提交工作的同学从最新 main 拉新功能分支，再通过 PR 进入 Dev。
3. 若郭同学还有本机未 push 的工作，当前审查无法看到；请先提交到独立功能分支，再按实际差异 Review。
4. 新增功能经 Dev 测试后再进入 main。先前真实 LLM 测试发现的地图和行为问题仍未修复，本报告不是发布验收通过声明。

```bash
git fetch origin
git switch -c feature/glf-next origin/main
```

如果有未提交内容或本机独有提交，先保留工作，不能用 `reset --hard` 强行同步。

## 核验命令

```bash
git rev-list --left-right --count origin/main...origin/glf
git log --oneline origin/main..origin/glf
git log --no-merges --oneline origin/main..origin/glf
git merge-base --all origin/main origin/glf
git show --remerge-diff --stat origin/glf
git merge-tree --write-tree --name-only origin/main origin/glf
```

本次审查没有运行 glf 的真实模型实验，也没有把 glf 的旧实验结果与新版模型混合比较。
只推送文档及脱敏审计元数据，不上传 API Key、账号数据库、原始提示词、实验记忆或本地未跟踪文件。

## 提交前验证

在以 main 为基线的独立审查工作区重新运行核心回归：**473 项通过，674 个子测试通过，3211 项未选入 core，0 失败**，耗时 69.33 秒。
48 条警告是绘图字体缺少中文字形；这不等于图表排版已通过验收。
测试使用 mock 模型，并设置无效外网代理、放行 loopback，避免等待外部新闻服务；不是实际付费模型测试或操作系统级断网隔离。

```bash
GAWORLD_IGNORE_LOCAL_CONFIG=1 \
HTTP_PROXY=http://127.0.0.1:9 HTTPS_PROXY=http://127.0.0.1:9 \
ALL_PROXY=http://127.0.0.1:9 NO_PROXY=127.0.0.1,localhost,::1 \
python -m pytest --suite core -q
```

另外完成暂存范围检查、`git diff --cached --check` 和常见凭据格式扫描。
本次变更只有本审查文档、配套审计 JSON 及真实 LLM 验收记录，核心回归通过不代表后者列出的实际运行问题已修复。
