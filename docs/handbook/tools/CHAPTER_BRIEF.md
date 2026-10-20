# 章节写作共同规约（所有写作者必读）

**项目**：GAWorld —— 生成式多智能体社会仿真平台（仓库根目录 `/Users/cw/dev/GAWorld`）
**读者**：第一次上手 GAWorld 的研究者 / 教师 / 学生，��是社科的本科生。
**语言**：简体中文（专有名词如 Agent、LLM、Plugin 保留英文原词）。
**产物**：`docs/handbook/chapters/NN-slug.md`，一个文件一章。

## 一、硬性规则

1. **只写你负责的那一个文件**。不要创建、修改、删除仓库里的任何其它文件。不要跑仿真、不要改代码。
2. **只写你亲手核实过的东西**。每一个命令、参数、文件路径、API 路由、目录名，在写进正文前必须用 `read` / `grep` / `bash --help` 在仓库里核对过。宁可少写一句，也不要编造。
   - 典型核对方式：`python3 generative_city_sim.py --help`、`python3 -m gaworld.city <sub> --help`、`grep -n "..." gaworld/apps/routes.py`、读 `docs/*.md`。
3. **数字要可靠**。凡是仓库里查得到的数字（阶段数、插件数、文件数、调用量）就写实数；查不到就写「示例」并明确标注是示意值。**禁止杜撰评测分数、论文结论、基线数字。**
4. **格式**：
   - 章首：`# 第 N 章　标题`（N 用阿拉伯数字，标题后跟一个空行）
   - 正文用 `##` 作小节标题，`###` 作子小节。**不要用 `#`（除章首）和不要用 `####` 以下。**
   - 代码块标注语言：`bash` / `python` / `json` / `http` / `text`
   - 表格用 markdown 表格，列数不超过 5 列
   - 行文里**不要**用 `**加粗**` 强调整段；加粗只用于关键词、参数名、路径
5. **插图**：从给你的图片清单里挑，格式
   ```markdown
   ![一句话说明](../images/文件名.png)

   **图 N-M　图题**
   白话解释这张图在讲什么（2–4 句）。图注紧跟在图片下面。
   ```
   `N` 是本章章号，`M` 从 1 开始递增。**每章 2–5 张图**，图必须配文字解读，不能是装饰。
6. **每章结尾**必须有两个小节：
   ```markdown
   ## 本章小结

   - 3–6 条，每条一句话，是本章真正要记住的东西。

   ## 动手练习

   1. **练习名**（约 20 分钟）
      具体操作步骤。
      **验收标准**：怎么判断做成了。
   ```
   练习要真的能跑，验收标准要可观察。
7. **篇幅**：正文 4 500 – 6 500 个中文字（不含代码块、表格、图注）。宁可短而准，不要注水。
8. **语气**：像一位带学生的资深工程师在讲自己维护的系统。直接、具体、少形容词。不写「本文档由 AI 生成」，不写「本手册旨在……」这类套话。第一句就进正题。
9. **不要重复其它章的内容**。每章开头用一两句交代「这一章解决什么问题」，然后直接开讲。跨章引用写「见第 N 章」即可。

## 二、章节编号与图片编号

- 章号从第 1 章到第 20 章，**不要跳号**。
- 图注编号 `图 N-M`：N = 章号，M = 该章内序号。

## 三、常用事实（已核实，可直接引用）

- Python ≥ 3.11；安装 `pip install -e ".[dev]"`；依赖清单 `requirements.txt`。
- CLI 入口 `generative_city_sim.py`，子命令：`run` / `reset` / `interview` / `create-agent-from-social` / `rag-add` / `rag-import` / `compare-event` / `parallel-worlds` / `serve-viz` / `dashboard` / `serve-distributed`。
- 城市 CLI：`python -m gaworld.city`，子命令 `create` / `list` / `show` / `add-agents` / `add-agent` / `migrate` / `knowledge` / `locale` / `news` / `use` / `delete`。
- 人口 CLI：`python -m gaworld.population`；群体模拟 CLI：`python -m gaworld.group`；采访 CLI：`python -m gaworld.interview --spec … --out …`；账号 CLI：`python -m gaworld.accounts init|invite|users|reset|city-permission`。
- pip 安装后的工作区入口：`gaworld init [dir]`、`gaworld dashboard`（默认 http://127.0.0.1:8766/dashboard）。
- 微内核：`gaworld/kernel/`（Clock / EventBus / PluginRegistry / Controller / Recorder / SimContext）；认知管线 `gaworld/sim/pipeline.py` 共 12 阶段：`prepare → perceive → interrupts → plan → adjust_activity → move → select_action → reflect → update_state → broadcast → memorize → record`。
- 内置插件：**不要在正文里写插件总数**。`builtin_plugins()` 当前实际注册 28 个（仓库文档里「9 个」已过时）。按子系统名字列举即可：干预(policy) / 技能(skills) / 兴趣成长(interests) / 目标(goals) / 人生事件(events) / 经济(economy) / 公共部门(public_sector) / 家庭(family) / 出行(travel) / 物理感知(world) / 真实工作(work) / 动态行为(behavior) / 空间偏好(spatial_preferences) / 居家环境(home) / 协作(collaboration) / 多人共玩(multiplayer) / 集群同步(cluster) / Moltbook / 群体模式(group) / 节假日(holiday) / 组织(organizations) / 人格(personality) / 信息源(infosources)。
- 大五人格三条通道：`rules`（确定性、零 token）/ `prompt`（注入日程与目标提示词）/ `voice`（只进日记提示词）。
- 运行产物统一在 `output/` 下：`memory/`（记忆与成长）、`state/`（状态历史长表）、`logs/`（运行日志）、`records/`（Recorder 事件流）、`environment/`（环境事件与 `timeline.jsonl`）、`parallel_worlds/`、`research/`、`interviews/`。
- 城市包在 `data/cities/<slug>/`；当前城市写在 `dashboard_config.json` 的 `{"city": slug}`。
- 产物路径有两条，**不要混**：
  - **城市层**运行根目录是 `output/cities/<slug>/`（`gaworld/city/bundle.py` 的 `RUNS_DIRNAME = "output/cities"`）——跑某座城市时，日志、记忆、状态都落在这里。
  - **账号层**的世界目录是 `output/worlds/<id>/`（`gaworld/worlds/__init__.py` 的 `WORLDS_DIR`）——多用户部署时每个用户的那一棵。
  - 两者内部用的是同一套 `RUN_PATHS` 布局。
- 插件开发：`docs/PLUGIN_AUTHORING.md`；钩子三种语义：observe / collect / filter。
- 标准运行时干预 4 个：`set_agent_state` / `update_config` / `remove_agent` / `inject_life_event`，每次调用自动审计。
- 游戏场：**不要依赖「14 个」这个总数**（仓库文档写 14，但未计入连续剧）。实际后端有 15 个：`arena`（斗兽场）、`persuasion`（说服）、`guess`（读空气）、`jury`（陪审团）、`disaster`（灾害）、`warzone`（围城）、`rumor`（谣言）、`referendum`（公投）、`commentary`（新闻评论）、`duel`（双队）、`novel`（小说）、`roommate`（同居）、`whois`（谁是真人）、`timeslip`（穿越历史）、`serial`（连续剧）。按名字列举，分四族（详见第 10 章）。
- 测试：`pytest --suite core`（约 30 秒冒烟）与 `pytest --suite full`；`tests/suites/core.txt` 里多一条陈旧项就会失败。
- 变更默认配置导致结果不可比时，在 `gaworld/core/comparability.py` 追加 `Epoch`（只增不重编号）。
- 延伸阅读：仓库 `textbook/`（22 章 + 4 附录的《多智能体社会仿真：原理、技术与案例》，另有 md/pdf/epub）、`docs/PROJECT_GUIDE.zh-CN.md`（中文完整指南）、`docs/FEATURES.md`（能力目录）、`https://s2014628.github.io/gaworld-bench/`（GAWorld Bench 效度评测）。
