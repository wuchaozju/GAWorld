# 游戏场总览（Games Overview）

> 一站式查清游戏场在玩什么、有什么、怎么互相串起来。  
> 每个游戏的"五分钟跑通 + 怎么算的 + 设计取舍 + HTTP API"都在 [`PLAYGROUND_TUTORIAL.md`](PLAYGROUND_TUTORIAL.md) 里展开。本文档只承担"目录 + 索引"的职能。

游戏场（Agent Playground）位于 dashboard 顶栏「**游戏场**」入口，背后挂着一组小游戏，所有游戏都跑在同一个城里同一个档案之上，但**不会写回城市**——一次游戏是沙盒，不是仿真。

---

## 1. 一张表：14 个游戏

| # | 游戏 | 玩法一句话 | 后端 / 命名空间 | 文档位置 |
| - | --- | --- | --- | --- |
| 1 | 斗兽场 Agent Arena | 一组居民同台答题，按正确率 + 中位耗时排座次，留 Top-K 淘汰补人 | `gaworld/apps/arena_api.py` · `/api/arena/*` | [`ARENA_TUTORIAL.md`](ARENA_TUTORIAL.md) |
| 2 | 说服游戏 Persuasion | 一对一聊天说服居民改主意，复问答案变了才算赢 | `gaworld/apps/games_api.py` · `/api/games/persuasion/*` | [`PLAYGROUND_TUTORIAL.md` §2–3](PLAYGROUND_TUTORIAL.md) |
| 3 | 灾害模式 Disaster | 一批居民同经历一场灾难，分幕推演，看行动 / 恐慌 / 互助分布 | `gaworld/apps/disaster_api.py` · `/api/games/disaster/*` | §4–5 |
| 4 | 这是我的战争 Warzone | 围困下共享仓库每天投票分配资源，看谁先让步、谁被牺牲 | `gaworld/apps/warzone_api.py` · `/api/games/warzone/*` | §12.10 |
| 5 | 谣言扩散局 Rumor Spread | 一条传闻沿熟人网络传播，画传播树、信任度、谁放大 / 谁挡；每轮是 wavefront 一波新触达的人，典型 1–2 轮就跑完；人数上限由账号当日 LLM 配额决定（`CONFIG["games"]["rumor"]["max_agents"]` 可兜底） | `gaworld/apps/rumor_api.py` · `/api/games/rumor/*` | §6–7 |
| 6 | 双队竞赛 Team Duel | 两队拿同一任务两条相反路子，蒙队名逐项打分 | `gaworld/apps/duel_api.py` · `/api/games/duel/*` | §8–9 |
| 7 | 公投局 Referendum | 同一议案先私投再公开表决，看民意的位移与改票者 | `gaworld/apps/referendum_api.py` · `/api/games/referendum/*` | §10–11 |
| 8 | 猜人局 Read the Room | 一人一道两难，凭档案猜他的选择，复问能测稳定性 | `gaworld/apps/guess_api.py` · `/api/games/guess/*` | §12 |
| 9 | 小说局 Novel Writer | 选 2–6 位居民当主角，给大纲 + 目标字数，按他们的口吻写小说 | `gaworld/apps/novel_api.py` · `/api/games/novel/*` | §12.5 |
| 10 | 陪审团 Jury Deliberation | 你写一个案件，挑 3–5 名陪审员，三轮讨论 + 匿名投票 + 量刑 | `gaworld/apps/jury_api.py` · `/api/games/jury/*` | §12.6 |
| 11 | 新闻评论 News Commentary | 给一条新闻（文字或网址），让 1–12 位居民各自评一条，看分布 | `gaworld/apps/commentary_api.py` · `/api/games/commentary/*` | §12.7 |
| 12 | 同居模式 Roommate Mode | 2–6 位居民合租一间公寓，前端按 tick 拉对话与心情仪表盘 | `gaworld/apps/roommate_api.py` · `/api/games/roommate/*` | §12.8 |
| 13 | 谁是真人 Who's Human | 居民与真人坐进同一匿名群聊，同时聊几轮后互相标真人 / 居民 | `gaworld/apps/whois_api.py` · `/api/games/whois/*` | §12.9 |
| 14 | 穿越历史 Timeslip | 把几位居民扔进一个真实朝代的关键时刻，逐幕看古人口吻 + 现代内心独白 | `gaworld/apps/timeslip_api.py` · `/api/games/timeslip/*` | §12.11 |
| 15 | 连续剧 Serial Drama | 挑主演 + 题材（内置 9 种或一句话自定），模型按他们的档案写一季连续剧——不是小说，是镜头脚本，可直接喂给可灵 / Sora / Veo / Hailuo | `gaworld/apps/serial_api.py` · `/api/games/serial/*` | §12.12 |

斗兽场是历史最久的入口，仍走自己的 `/api/arena/*`，游戏场只是把它收进同一个大厅；其余 13 个游戏统一挂在 `/api/games/<game>/` 下，由 [`gaworld/apps/games_api.py`](../gaworld/apps/games_api.py) 转发到各自的后端模块。

---

## 2. 游戏的四个家族

把 14 个游戏按"问题形态"分组，更容易看出哪些可以互相替代、哪些互补。

### 2.1 一对一：说服 / 猜人 / 陪审（一次只对一个居民）

- **说服游戏**测的是「能不能让他改主意」——一个居民 + 一个问题 + 一段对话 + 一次复问，裁判对比首尾两个答案。
- **猜人局**测的是「能不能猜到他选哪边」——一个居民 + 一个两难，没有对话，玩家直接猜；可以复采样同一个居民 + 同一个两难，看猜得多准。
- **陪审团**测的是「一群人在一段审议后怎么判」——3–5 个居民就一个案件讨论三轮，再匿名投票有罪 / 无罪 + 量刑。

> 当研究问题是「人格可塑性 vs 一致性」时，这三个游戏侧重点不同。说服看"用户能不能改"，猜人看"别人能不能猜"，陪审看"群体审议有没有收敛到一个答案"。

### 2.2 一群人同时面对一件事：灾害 / 这是我的战争 / 谣言 / 公投 / 新闻评论

- **灾害模式**给一个外部冲击（地震 / 疫情 / 战争 / 洪水 / 大停电），看群体在 N 幕里的行为分布。
- **这是我的战争（Warzone）**给一个持续资源约束——每天怎么分，谁先让步，谁被牺牲。
- **谣言扩散局**给一个信息源 + 一个传播网络——看谁放大、谁挡。
- **公投局**给一个议案 + 一段宣传语——看私下表态和公开表决之间怎么漂移。
- **新闻评论**给一条新闻——看每个居民一句评论 + 立场 + 强度，不涉及彼此博弈。

> 这一族最容易出"曲线型"研究问题：地震几幕之后互助率怎么走、围城第几天基尼系数抬到 0.6、谣言传几跳。

### 2.3 任务协作 / 创意：双队 / 小说（多居民，共做一件事）

- **双队竞赛**——两组人同一任务两条相反路线，盲审按维度打分。
- **小说局**——几个人一起当主角，给定大纲和字数，写一篇小说。

> 双队是"协作型 vs 对抗型"路线对比的范式；小说是"模拟人格 + 长文一致性"的范式（论文里常用语料来自这里）。

### 2.4 长期同居 / 多人：同居模式 / 谁是真人（长会话 + 真人参与）

- **同居模式**——2–6 位居民在公寓里，每天活动 + 碰面 + 对话，前端按 tick 反复拉，仪表盘跑关系值和心情。
- **谁是真人**——居民和真人同坐一个匿名群聊；每条发言只显示编号；几轮后互相标"真人 / 居民"，揭晓看谁骗过了谁。**唯一一个真人入场的游戏。**

> 它们的成本模型都不一样：同居是状态机增量；whois 是真人群聊加一个真人回合。

---

## 3. 共同约定

游戏场所有游戏都遵守以下约定，保持它们彼此可读、行为可测。

1. **不写回城市。** 一次游戏是沙盒：`output/worlds/<id>/` 里的居民档案、状态 CSV、记忆，谁也不能动。重启 dashboard，房间消失——居民不记得发生过这事（这是设计，不是 bug）。
2. **LLM 调用全部可注入。** 每个游戏的实现都把模型调用包成 `*_fn` 参数（命名因游戏而异：`proposal_fn` / `vote_fn`、`stage_fn` / `essay_fn`、`answer_fn` 等）。测试把这些塞成纯函数，**整套跑不需要任何 API key**。
3. **居民档案走 `gaworld.interview.roster`。** `load_population(city)` 给身份行，`profile_block(city, agent_id)` 给 profile.md 里的档案正文。`""` = 默认世界。所有游戏复用同一份 persona，避免"同一居民在不同游戏里性格不一样"的脱节。
4. **结构化回复走 `first_json_object()`。** 模型在 JSON 后面接着说话、多打一个 `}`，都能被它扫括号深度救回来。失败了**降级一条，不毁整场**。
5. **后台任务走 `JobStore`。** 体量较大的（灾害 / 谣言 / 双队 / 公投 / 战争 / 穿越 / 政策仿真 / 严肃游戏）通过 [`gaworld/apps/game_jobs.py`](../gaworld/apps/game_jobs.py) 起后台作业，给前端 `job_id` 查进度，结果归档在 `output/games/<game>/<job_id>.json`。陪审 / 评论也走同一套。
6. **解析失败 = 单条降级。** 模型吐了乱码 → 这一行 / 这一幕 / 这一票降级成中性默认值，整体仍出。后端允许跑完，但结果里要明示"哪些字段是降级出来的"。
7. **温度按"角色"分**。居民说话 0.7（要像人），总结 / 评论员 0.3–0.4（要稳），裁判 / 判定 0.0（要确定性）。所有游戏都按这套分；同一个 prompt 不会让模型兼任两种温度。

---

## 4. 怎么挑一个游戏来做研究

按"问题形状"反查游戏:

| 你想研究的问题 | 推荐游戏 |
| --- | --- |
| 一个居民在压力下会不会改主意 | 说服游戏（双向）/ 猜人（看猜测稳定性） |
| 群体在外部冲击下怎么变 | 灾害模式 / 这是我的战争 |
| 信息在熟人网络怎么传、谁挡得住 | 谣言扩散局 |
| 公开表态 vs 私下的位移 | 公投局 |
| 同一个任务两条相反路线哪个赢 | 双队竞赛 |
| 一个居民按档案演戏，演得稳不稳 | 小说局 / 穿越历史 |
| 一群人对一个案件审议后是否收敛 | 陪审团 |
| 一群人看到同一条新闻的分歧度 | 新闻评论 |
| 同一屋檐下的关系动力学 | 同居模式 |
| 居民能不能骗过真人 | 谁是真人 |
| 居民在异时代场景下能不能转换语境 | 穿越历史 |
| 一群居民能否撑起一整季镜头脚本(画面提示可喂视频模型) | 连续剧 |

每个游戏在 [`PLAYGROUND_TUTORIAL.md`](PLAYGROUND_TUTORIAL.md) 都有"五分钟跑通 + 它是怎么算的 + 设计取舍 + 接口"四段展开，本文不复述。

---

## 5. 加一个新游戏

新游戏的入场费很低，一份后端 + 一份前端 + 注册表里加两条。

1. **后端**——新建 `gaworld/apps/<game>_api.py`，导出 `handle_get` / `handle_post`，返回 `(dict, status)` 元组。
2. **注册**——在 [`gaworld/apps/games_api.py`](../gaworld/apps/games_api.py) 的 `handle_get` / `handle_post` 里把 `path.startswith("/api/games/<game>/")` 的一支指过去：
   ```python
   if path.startswith("/api/games/<game>/"):
       from gaworld.apps import <game>_api
       return <game>_api.handle_get(path, query)
   ```
3. **前端**——在 `site/dashboard/` 里加 `<game>.html` + `<game>.js`。
4. **大厅入口**——`site/dashboard/games.html` 在卡片网格里加一项。
5. **OpenAPI**——[`gaworld/apps/openapi.py`](../gaworld/apps/openapi.py) 里登一遍；`tests/test_openapi.py` 跑过才不会被 CI 卡。
6. **教程**——在本表加一行，在 `PLAYGROUND_TUTORIAL.md` 加对应章节。

详细规范见 [`PLAYGROUND_TUTORIAL.md` §14](PLAYGROUND_TUTORIAL.md)。

---

## 6. 排查

| 现象 | 可能 | 处理 |
| --- | --- | --- |
| 提交按钮转圈然后 `/api/games/<game>/run` 回 400 | 自定义剧本缺字段 / 人数越界 / `*_id` 不在库里 | 错误消息会指名，先按报错改 |
| 后台作业一直 `pending` | 默认 LLM provider 没配 | `gaworld/apps/games_api.py:117` 起的 `_call_llm` 走 `gaworld.llm.providers.call_llm`；检查 `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` |
| 跑完了但居民档案像是"一个模子" | 城市里居民太少，或者重名 | 换城市；用 `add-agents` 给城市补 50+ 人 |
| 游戏结果在重启 dashboard 后消失 | 这是设计 | 复用要看归档 `output/games/<game>/<job_id>.json`；要从里面出图表直接读归档 |
| 居民说了一句和其档案八竿子打不着的话 | 模型写得飘 | 改 prompt 没用，加约束也飘；跑同居民复用原 prompt 三次，选最不像"全员同质"的那条 |
