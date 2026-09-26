# 斗兽场（Agent Arena）教程

> 在 Web 端给一组居民跑 benchmark，按正确率 + 速度排座次，按 Top-K 留存 / 淘汰，再补充新选手。
>
> 面板：`http://localhost:<port>/site/dashboard/arena.html`（入口在[游戏场](PLAYGROUND_TUTORIAL.md)大厅）
> 引擎：`gaworld/apps/arena_api.py`｜前端：`site/dashboard/arena.{html,js,css}`｜测试：`tests/test_arena_api.py`

---

## 目录

- [0. 这是什么，什么时候该用](#0-这是什么什么时候该用)
- [1. 五分钟跑通](#1-五分钟跑通)
- [2. 任务来源：内置题库 + LLM 自动出题](#2-任务来源内置题库--llm-自动出题)
- [3. 评分：双重规则 + judge LLM](#3-评分双重规则--judge-llm)
- [4. 留存与淘汰](#4-留存与淘汰)
- [5. 补充新选手](#5-补充新选手)
- [6. 程序化调用：HTTP API](#6-程序化调用http-api)
- [7. 与其它管线的关系](#7-与其它管线的关系)
- [8. 排查清单](#8-排查清单)

---

## 0. 这是什么，什么时候该用

「斗兽场」是一个**只跑在内存里的 LLM 评测沙箱**。它对一组居民问一组题目，按正确率 + 中位耗时排名，按 Top-K 留存，其余进入淘汰名单，再由用户从其他城市或「批量导入」补充新选手。

**适用**：

* 你想知道「这些居民里谁答题最稳 / 最快」；
* 你想用一组标准化题目（数学 / QA / 逻辑 / 阅读 / 翻译）比较一组智能体；
* 你想把一批选手中表现差的换掉，从其他城市或新文件里补。

**不适用**：

* 想跑完整日常仿真 → `python generative_city_sim.py run`；
* 想做批量人口结构合成 → 批量导入或「人口与群体」向导；
* 想对单个智能体做长访谈 → Agent Studio 第 5 步「采访」。

---

## 1. 五分钟跑通

1. 打开 `http://localhost:<port>/site/dashboard/arena.html`。
2. 左上「目标城市」选择要比赛的城。
3. 左侧「选手」勾一组居民（最多 12 人；被淘汰的灰显，不能再选）。
4. 「任务」勾几道内置题目（10 道题已足够覆盖数学 / QA / 逻辑 / 阅读 / 翻译）。
5. 点「开始斗兽」。右侧实时战况区显示进度条 + 当前问到谁。
6. 完成后看排行榜；填「保留 Top-K = 3」→「应用留存」→ 剩下的人进入淘汰名单（左侧灰显）。
7. 想补充：在右下「补充新选手」里填来源城市 + 数量 → 点「从该城市拉 N 人」；或者点旁边的「打开批量导入补一批」。

---

## 2. 任务来源：内置题库 + LLM 自动出题

### 2.1 内置题库（10 道）

`gaworld/apps/arena_api.py::TASK_BANK` 提供 10 道手工出题：

| 类别 | 题目 |
| --- | --- |
| math | 加法、乘法、GSM8K 风格（购票找零）、长方形周长 |
| qa | 法国首都、水的化学分子式 |
| logic | 等比数列下一项、条件推理 |
| reading | 浙江省小微企业税收减免摘要 |
| translate | "The early bird..." 英 → 中 |

`GET /api/arena/tasks` 返回完整列表；`task_by_id()` 按 id 取单题。

### 2.2 LLM 自动出题

点面板「🎲 随机出题」会 POST `/api/arena/generate`：

```json
{ "n": 5, "categories": ["math", "qa", "logic"], "difficulty": "medium" }
```

后端按 prompt 让 LLM 返回一组 JSON；解析时兼容：

* 严格 JSON 数组（`[{...}, ...]`）；
* JSON 数组被前后散文包裹时，按正则提取 `{...}` 块；
* 缺字段的对象会被丢弃；
* 全空响应抛 `ValueError`。

出题结果存在前端 `state.customTasks`，勾选框可立即纳入下一轮比赛。

---

## 3. 评分：双重规则 + judge LLM

每个 (选手, 任务) 单元独立打分：

1. **快路径**：若任务的 `expected` 是字符串且选手回答的「小写 + 去标点」与 `expected` 一致 → score = 1。
   例子：`expected="Paris"` 与回答 `"paris!"` 都判 1。
2. **慢路径**：调 judge LLM。Prompt 强制模型返回 `{"score": 0|1}` 的 JSON；解析时容忍散落的 prose（如 `"...score: 1..."`）。
3. 任何 LLM 调用异常都降级为 score = 0，并在日志里 `WARNING`。

排行榜排序键：`-accuracy, median_latency`。同分时谁快谁靠前。

> **为什么不让 judge 全部慢路径？** 因为内置题库里数学 / 事实题可以严格匹配；阅读理解才走 judge。两条路径叠加给结果「又快又稳」。

---

## 4. 留存与淘汰

点「应用留存」会 POST `/api/arena/retain`：

```json
{ "city": "wuzhen", "leaderboard": [...], "k": 3 }
```

后端：

1. 取排行榜前 K 名 → 标记为 `survivors`；
2. 其余 → `mark_eliminated(city_slug, agent_ids)`，写入**内存字典** `_ELIMINATED`；
3. 返回 `{survivors, eliminated, all_eliminated}`。

**关键事实**：淘汰标记只活在内存里（重启 dashboard 进程就清空）。它**不会**删 `data/cities/<slug>/agents.csv`、`profiles.md`，更**不会**联动 `memory / big_five / social / finance` 这些按 id 命名的子状态。这是「沙箱」定位：你可以放心试错；要真删 agent 用 `gaworld/city/agents.py` 里的工具函数。

### 单独淘汰

排行榜每行有「淘汰」按钮，单人即时标记并重新渲染左列与右上角。

---

## 5. 补充新选手

补充走两条路：

### 5.1 从其他城市 pull

右下角：

```
source city slug:  香港
n:                 3
→ POST /api/arena/refill {city, from_city, n}
```

后端 `refill_from_city` 用 `gaworld/city/agents.add_agent` 把来源城市的 N 个 agent append 到目标城市（profile 名字加 `（来自 <来源>）` 后缀）。已淘汰的不进入候选池；如果来源城市全部淘汰，抛 `ValueError`。

### 5.2 通过批量导入

点「↗ 打开批量导入补一批」会跳到 Agent Studio 的批量导入 Modal。导入完成的居民会立刻出现在斗兽场的左列。

> 后端 `refill_via_import` 是程序化入口：把 `import_api.execute_import` 的入参（city, format, headers, rows, mapping, anonymise, expand_to, salt, seed）直接喂进去。dashboard 用不到，但脚本可以 chain 起来。

---

## 6. 程序化调用：HTTP API

### 6.1 `GET /api/arena/tasks`

```bash
curl -s http://localhost:<port>/api/arena/tasks | jq '.tasks | length'
# => 10
```

### 6.2 `GET /api/arena/agents?city=<slug>`

返回当前城市的所有居民 `{id, name, gender, age, industry}`。被淘汰的仍在列表里，由前端决定是否灰显。

### 6.3 `POST /api/arena/generate`

请求体 `{n, categories, difficulty}`，响应 `{tasks: [...]}`，每题带 `id, category, title, prompt, expected`。

### 6.4 `POST /api/arena/run`

```bash
curl -s -X POST http://localhost:<port>/api/arena/run \
  -H "Content-Type: application/json" \
  -d '{
    "city": "wuzhen",
    "agent_ids": [3, 5, 7],
    "task_ids": ["arith-add", "qa-capital"],
    "custom_tasks": []
  }' | jq
# => {"job_id": "arena-3a8e7c2d"}
```

后端：

* 新建 job → 后台线程同步调用 `run_round`；
* 选手回答走 `call_llm(task="arena.answer", temperature=0.2)`；
* judge 走 judge prompt；
* 完成后 result 包含 `{round_id, city, task_ids, leaderboard: [{agent_id, name, correct, attempted, accuracy, median_latency_s}, ...]}`。

### 6.5 `GET /api/arena/jobs/<id>`

轮询 job 状态。响应同 `population_api` / `import_api` 的 job 形状：`status ∈ {running, done, failed}`、`progress ∈ [0, 1]`、`message` 是当前问到谁的描述。

### 6.6 `POST /api/arena/retain`

```bash
curl -s -X POST http://localhost:<port>/api/arena/retain \
  -H "Content-Type: application/json" \
  -d '{"city": "wuzhen", "leaderboard": [...], "k": 3}'
```

响应 `{city, k, survivors, eliminated, all_eliminated}`。

### 6.7 `POST /api/arena/refill`

两种 mode：

```json
{ "city": "wuzhen", "from_city": "香港", "n": 3 }
{ "city": "wuzhen", "import_payload": { ... 与 /api/import/run 同 ... } }
```

### 6.8 `POST /api/arena/state`

返回某城市当前的 `eliminated` 列表（内存中的淘汰标记）。重启 dashboard 后为空。

---

## 7. 与其它管线的关系

* **`persona_api`**：两者都面对单个 agent；persona 是「按身份蒸馏」，arena 是「按答案打分」。
* **`interview`**：interview 是开放式问答，由人参与选问题；arena 是题目固定、自动打分、可批量横向对比。
* **`population_api` / `import_api`**：arena 的 refill 复用 `add_agent` 和 `import_api.execute_import`；同一份状态写入路径，不会冲突。
* **`dashboard_server`**：路由层只是 5 行委派，复用与 `population_api` / `import_api` 相同的 job 注册表（≤ 20 条历史 job）。

---

## 8. 排查清单

| 现象 | 原因 | 修法 |
| --- | --- | --- |
| 「城市暂无居民」 | 该城市 `agents.csv` 为空或没有该目录 | 用 `python -m gaworld.city add-agents <city> --size 100` 先造一批；或换城市 |
| 「启动中…」卡住不前进 | LLM 调用全失败（DNS / key / provider 没配） | 检查 `dashboard_config.json::llm.providers`；看 `output/logs/` |
| judge 全部 0 分 | judge prompt 被 provider 拒（敏感词 / 长度） | 改内置题或降低 `custom_tasks` 数量 |
| 「应用留存」后选手没灰 | 城市切换过，淘汰标记按 city_slug 隔离 | 刷新整个面板即可（重新拉一次） |
| 「从该城市拉 N 人」失败 | 来源城市 slug 拼错 / 全部淘汰 / 不存在 | 用 `python -m gaworld.city list` 查正确 slug |
| 「随机出题」失败 | LLM 出题响应是非空但非 JSON | 减少 `n`、明确 categories；后端会重试 |