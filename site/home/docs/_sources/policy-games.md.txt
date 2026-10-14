# 政策推演与严肃游戏

研究工作台提供两种围绕情景的研究方式：政策推演比较居民对不同政策文本的反应，严肃游戏让居民与真人按角色和回合参与共同决策。

## 功能与准备

本章用于两类操作：比较政策文本引发的居民反应，以及组织按角色、按回合进行的严肃游戏。政策推演准备城市、政策文本和抽样设置；严肃游戏准备情景、角色目标与参与方式。

## 比较政策版本

打开 **研究工作台 → 政策仿真与优化**，选择城市并输入政策文本。可以同时输入候选政策，比较两个版本。

1. 设置抽样人数、随机种子与分析模型。
2. 启动推演，让同一批居民分别评价各版本。
3. 查看支持度、生活变化、钱包影响、遵从度与居民原话。
4. 阅读修改建议与修订版政策。
5. 开启验证后，在同一批居民上继续评估修订版，比较配对结果。

抽样范围为 6–30 位、年龄至少 16 岁的居民。各版本共用同一批受访者。居民反应由模型根据档案生成，适合比较文本版本、发现可能受影响的群体与修改方向。

## 检查推荐版本

结果包括各项均值、按属性的分组比较、逐人回答与综合分。综合分由支持度、生活变化、钱包影响与遵从度按设定权重计算，推荐版本按该分数选出。

结合分组结果与原话判断推荐是否符合你的研究目标。点击下载 Markdown 保存报告，或将修订版作为下一轮输入继续比较。记录保存在 `output/research/policy/<id>.json`。

## 设计严肃游戏

打开 **研究工作台 → 严肃游戏**，描述情景中的参与者、各自目标与需要作出的决定，再设置回合数与角色数。

生成后检查背景、角色、公开目标、私密信息、回合事件与评分维度。随后为每个角色安排一位城市居民或一位真人参与者。

## 组织回合与复盘

每轮由各角色提交行动，主持流程在结算时更新公共指标与情景。真人通过自己的座位链接进入，查看公开信息与该角色的私密信息。主持界面可以检查提交状态，并结算当前回合。

最后一轮结束后，查看角色评分、学习目标评估与复盘问题，再下载 Markdown。设计保存在 `output/research/serious_games/`，对局保存在其 `sessions/` 子目录中。

严肃游戏的座位链接用于本地课堂或工作坊中的角色分配；团队账号与访问权限设置见 [团队部署与世界管理](deployment.md)。

## 与平行世界配合

政策文本推演帮助比较居民的即时反应，严肃游戏记录回合中的互动决策。需要追踪干预后的持续行动、状态变化与跨种子差异时，在 [平行世界](parallel-worlds.md) 中设置事件或配置条件，并运行完整仿真。

## 完成后检查

政策推演完成后，核对各版本使用的居民样本、各项得分和原话，再导出报告。严肃游戏每轮核对角色提交状态与公共指标，结束后检查回合记录、角色评分和复盘内容。

## 代码结构与执行流程

### 模块分工

```{container} code-map

| 源码位置 | 职责 |
| --- | --- |
| [site/dashboard/policy-sim.js](https://github.com/wuchaozju/GAWorld/blob/main/site/dashboard/policy-sim.js) | 政策输入、版本比较、结果展示和导出。 |
| [gaworld/apps/policy\_sim\_api.py](https://github.com/wuchaozju/GAWorld/blob/main/gaworld/apps/policy_sim_api.py) | 创建政策任务，读取保存结果并导出报告。 |
| [gaworld/research/policy\_sim.py](https://github.com/wuchaozju/GAWorld/blob/main/gaworld/research/policy_sim.py) | 居民抽样、版本评估、代码计分、修改建议与修订验证。 |
| [site/dashboard/serious-game.js](https://github.com/wuchaozju/GAWorld/blob/main/site/dashboard/serious-game.js) | 游戏设计、角色安排、主持与座位页面交互。 |
| [gaworld/apps/serious\_game\_api.py](https://github.com/wuchaozju/GAWorld/blob/main/gaworld/apps/serious_game_api.py) | 管理游戏与对局，接收行动并推进回合。 |
| [gaworld/research/serious\_game.py](https://github.com/wuchaozju/GAWorld/blob/main/gaworld/research/serious_game.py) | 定义游戏结构、角色视图、行动、回合结算与复盘。 |
| [gaworld/apps/game\_jobs.py](https://github.com/wuchaozju/GAWorld/blob/main/gaworld/apps/game_jobs.py) | 为耗时任务提供后台执行与进度查询。 |

```

### 执行流程

```text
政策文本 → 固定样本 → 各版本反应 → 代码汇总 → 修订 → 同样本验证
游戏描述 → 结构化设计 → 角色就座 → 每轮提交与结算 → 评分与复盘
```

两项功能都通过 `research_api.py` 分发到各自接口。政策模块对各版本使用同一批居民，聚合反应后生成修订建议。游戏模块保存角色、座位和回合状态；API 层驱动居民行动与主持结算，真人通过座位提交行动。两条流程分别保存政策记录和游戏会话。

### 从哪里修改

调整政策评分查看 `policy_sim.py` 的 `composite_score()` 与 `metrics()`；调整游戏结构、角色信息或回合规则查看 `serious_game.py`。界面和 HTTP 操作分别对应上表中的前端与 API 文件。
