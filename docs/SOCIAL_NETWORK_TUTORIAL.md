# Social Network 教程

本教程面向 GAWorld 的运行者，目标是用 5 分钟搞清楚：智能体现在有了哪些场外关系、它们如何在仿真里"动起来"、怎么看、怎么调。

> 如果你想理解背后的设计动机和 API 细节，看 `SOCIAL_NETWORK_DESIGN.md`。

---

## 1. 这套机制做了什么

在没有这套扩展之前，一个智能体的社交圈只包含和它在 `social_neighbors` 里的其他智能体——它会因为"今天没见到"就完全脱离社交。

加上 Social Network 扩展之后：

- 每个智能体启动时会被自动配上一份**场外熟人名单**（ghost roster）：父母、兄弟姐妹、伴侣或前任、几位老朋友/老同学、前同事、邻居等。这些人**不在仿真里运行**，但活在该智能体的 `relationships` 里。
- 每天有一定概率（默认 ≈ 18%）会有一位场外熟人"发来消息"：可能是妈妈生病、老同学结婚、前任来借钱、远房朋友突然问候。这些事件走的是 GAWorld 既有的 `life_events` 管道，会影响 emotion/stress 等 state。
- 长期不联系的关系会**自动衰减**（亲属衰减慢、网友衰减快），同时会累积"愧疚"（obligation 上调，封顶为基线的 1.4 倍）。
- 一个智能体的关系名单不会无限膨胀——超过 150 时会按弱连接优先裁剪，**亲属永远受保护**。
- 两个智能体之间如果存在共同熟人（同乡、校友、共同朋友），可以被 `shared_ghosts()` 检测出来作为对话/相遇时的 homophily 信号。
- 一个智能体不会"凭空知道"另一个智能体的家庭——需要在对话中显式被告知（`disclose_ghost`）才会出现在 `known_others`。

> **和家庭系统的分工（2026-08 起）**：配偶、子女、前任、室友这几个角色现在由
> [家庭系统](FAMILY_DESIGN.md)统一决定——它保证 A 的配偶就是 B、两人共享住处、
> 一件家事同时落到全家人身上。本页描述的 ghost 名单仍然负责父母、兄弟姐妹、
> 老同学、前同事、邻居这些**家庭之外**的场外关系。
> 两者在 `relationships` 里共存：家庭系统在 `on_simulation_start` 写入亲属边，
> 并**剪掉** LLM 名单里与已分配家庭矛盾的配偶/子女（编出来的母亲、老同学不动）；
> 名单生成的 prompt 也会被告知该居民的家庭状况，不要另编。
> 父母的键名 `g_father` / `g_mother` 两边是同一套，说的是**同一个人**。
> `ROLE_CONFIG` 另外新增了 `roommate`（合租室友）。

---

## 2. 启用条件

- `HUMAN_REALISM_ENABLED = True`（项目默认开启）。如果你关掉了它，bootstrap/decay/dunbar/ghost-event 全都不会跑。
- LLM 可用时会用 LLM 生成更拟真的 backstory 与 ghost 事件描述；LLM 不可用时会用启发式 fallback，**仿真依然完整可跑**。

---

## 3. 一次完整流程会发生什么

```
启动一次 run
  └─ 每个 agent 初始化阶段
       ├─ migrate_relationships(a)           # 给旧记录补 schema
       └─ bootstrap_social_roster(a, llm)    # LLM/启发式生成 ghost 名单

每天循环
  ├─ 早晨：每个 agent 18% 概率触发 ghost 事件
  │    └─ 推入 life_events，到达 08:30 时被消费
  │
  ├─ 全天：tick 内 in-sim 互动照常走 relationship_update
  │
  └─ 日终（consolidate_day 之后）
       ├─ decay_relationships(a, day)        # 衰减 + 愧疚累积
       └─ enforce_dunbar(a)                  # 裁剪到 150 以内，打 tier 标签
```

---

## 4. 怎么看到这套机制在跑

### 4.1 看名单本身

`output/memory/agent_<id>_relationships.json` 每天 day-end 会被覆盖写入。这是你检查 ghost roster 是否生成的第一站。文件示例（节选）：

```jsonc
{
  "12": {
    "kind": "agent", "role": "",
    "closeness": 0.62, "trust": 0.55,
    "last_contact_day": 7
  },
  "g_mother": {
    "kind": "ghost", "role": "mother",
    "tie_origin": "hometown",
    "profile": { "name": "李母", "city": "重庆", "vibe": "操心" },
    "closeness": 0.85, "trust": 0.80, "obligation": 0.80,
    "channels": ["call", "visit"],
    "last_contact_day": 5,
    "dunbar_tier": "inner"
  }
}
```

`kind="ghost"` 的就是场外的、不在仿真里运行的熟人。`dunbar_tier` 是 Dunbar 裁剪后的圈层标签：`inner`（最近 5）/`close`（前 15）/`acquaintance`（前 50）/`weak`（剩余）。

### 4.2 看 ghost 事件

`output/life_events/events.json` 里 `template_key` 以 `ghost_` 开头的就是场外熟人事件：

```jsonc
{
  "id": "...", "status": "consumed",
  "template_key": "ghost_illness",
  "title": "李母生病了",
  "description": "...",
  "impact_tags": ["relationship", "off_screen", "mother"],
  "state_effects": { "emotion": -0.06, "stress": 0.10, "time_pressure": 0.06 },
  "agent_ids": [31],
  "triggered_day": 12, "triggered_time": "08:30"
}
```

事件被消费后，对应 ghost 的 `last_contact_day` 会刷新到今天，state_effects 直接进入 agent 的状态轨迹。

### 4.3 看反应

`output/state/agent_state_history.csv` 里会出现对应天的情绪/压力扰动；`output/logs/agent_<id>.log` 里事件被记录的时间点也会有日志。

---

## 5. 常见调节

| 想要的效果 | 调哪 |
| --- | --- |
| 场外事件太多 / 太少 | `generative_city_sim.py` 顶部的 `GHOST_EVENT_DAILY_P`（默认 0.18，意味着每周大约一次） |
| 亲属衰减不该 = 0，应该轻微衰减 | 改 `social_network.ROLE_CONFIG["spouse"]["decay_rate"]` 等 |
| 不想让网友这么快流失 | `ROLE_CONFIG["online_friend"]["decay_rate"]` 从 0.020 调小 |
| 圈层上限要更紧（比如 80） | `enforce_dunbar(a, limits={"weak": 80})` 或改 `DUNBAR_TIERS["weak"]` |
| 愧疚来得太慢 | `_NEGLECT_GUILT_THRESHOLD_DAYS` 调小（默认 7） |
| 完全关掉场外事件 | 把 `GHOST_EVENT_DAILY_P = 0.0`；bootstrap 与衰减仍然会跑 |
| 完全关掉这套机制 | 把 `HUMAN_REALISM_ENABLED = False`；既有 baseline 行为 |

---

## 6. 重新生成 backstory

bootstrap 是幂等的：一旦 agent 已有任意 ghost 就不会再跑。如果你换了 LLM、或想给某个 agent 重新摇一份名单：

```python
from social_network import bootstrap_social_roster
from llm_providers import call_llm

bootstrap_social_roster(agent, call_llm, current_day=day, force=True)
```

`force=True` 会在保留旧记录的前提下追加新生成的 ghost——如果想完全替换，先手动清空 `agent["relationships"]` 中 `kind == "ghost"` 的条目。

---

## 7. 把它接进对话（高级）

`shared_ghosts(a, b)` 与 `disclose_ghost(observer, source_id, ghost_record, ghost_key)` 是为对话 / 反思阶段准备的钩子，目前**没有自动调用**——这是有意的，避免在你不需要时偷偷消耗 token。

典型接入位置：在两个 agent 真的产生对话时（比如 `generative_city_sim` 的 social_context 构造阶段）调用 `shared_ghosts(a, b)`，把命中的桥放进 prompt：

```python
from social_network import shared_ghosts

bridges = shared_ghosts(agent_a, agent_b)
if bridges:
    extra_context = "你和对方有共同熟人：\n" + "\n".join(
        f"- {b['a_name']} ↔ {b['b_name']}（via {b['via']}）" for b in bridges
    )
```

对话后，如果对方提到了自己的某个 ghost，可以 disclose：

```python
from social_network import disclose_ghost

disclose_ghost(
    observer=agent_b, source_id=agent_a["id"],
    ghost_record=agent_a["relationships"]["g_mother"],
    ghost_key="g_mother",
    current_day=day,
)
```

之后 `known_ghosts_of(agent_b, agent_a["id"])` 就能在 b 的视角下看到这条信息。

---

## 8. 测试 / 验证

新功能的 6 个测试文件：

```bash
python -m unittest \
  tests.test_social_network_schema \
  tests.test_social_backstory \
  tests.test_ghost_events \
  tests.test_dunbar_decay \
  tests.test_social_bridge_disclosure \
  tests.test_simulation_social_integration
```

共 37 个用例，覆盖 schema 迁移、LLM happy path、fallback、采样、衰减、Dunbar 裁剪、桥/disclose 和与既有管线的粘合。

---

## 9. 已知限制 / 不在本期范围

- Ghost ↔ Ghost 之间的关系暂未建模（妈妈和阿姨之间是否处得来）。
- 配偶 / 子女 / 前任 / 室友已不由本机制决定（见第 1 节末尾的分工说明）。
- 生日 / 节日还没有真实日期，只是按 closeness 阈值随机触发。
- 离职等"岗位级"事件不会自动把现 coworker 转成 former_coworker，需要外部触发或额外脚本。
- `shared_ghosts` / `disclose_ghost` 还没有在 GAWorld 默认对话流里自动调用——按你的偏好接入。

如果上面任何一点是你最想要的，给我提一下，下一轮再上。
