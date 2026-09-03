# Social Network 扩展 — 实施设计

> 让仿真智能体的社交网络不再局限于运行时同框的其他智能体，而是有自己的家庭、伴侣、朋友、同学、工作关系等"场外熟人"，并按真人方式衰减、互动、被裁剪。

设计原则与 `AGENTS.md` 一致：最小改动、可关闭、不破坏既有 tick 行为；新代码集中在新模块 `social_network.py`，对既有 `human_realism.relationship_*` 只做向后兼容的增量。

---

## 0. 现状锚点

| 位置 | 现状 |
| --- | --- |
| `human_realism.py:516` | `relationship_update(agent, neighbor_id, signal, cfg)` 用 closeness/trust/obligation/friction 四个标量更新关系；key 是 in-sim agent id |
| `human_realism.py:548` | `relationship_weight(agent, neighbor_id)` 用扁平加权返回排序分数 |
| `generative_city_sim.py:5556-5573` | 在 `build_social_network` 之后，按 social_neighbors 默认初始化关系记录 |
| `experience_store.py:151-158` | 关系记录按 agent_id 落盘到 `output/memory/agent_<id>_relationships.json` |
| `life_events.py` | 模板化生活事件管线：`add_life_event → drain_due_life_events`，会消费 state_effects |

**问题**：关系只跟踪同框对象，没有 role/kind 区分，没有亲属粘性，没有场外互动，没有 Dunbar 上限，没有"久未联系→愧疚"的真人信号。

---

## 1. 五层扩展（核心）

```
┌──────────────────────────────────────────────────────────────┐
│ Layer 5 ─ 社交桥 / 信息不对称                                  │
│   shared_ghosts() + disclose_ghost() + known_ghosts_of()      │
├──────────────────────────────────────────────────────────────┤
│ Layer 4 ─ Dunbar 圈层 + 角色化衰减                             │
│   decay_relationships() + enforce_dunbar()                    │
├──────────────────────────────────────────────────────────────┤
│ Layer 3 ─ 场外生活事件                                         │
│   generate_ghost_event()  + 6 个事件模板 + life_events 管道    │
├──────────────────────────────────────────────────────────────┤
│ Layer 2 ─ Backstory / Ghost 名单                               │
│   bootstrap_social_roster(agent, llm)                         │
├──────────────────────────────────────────────────────────────┤
│ Layer 1 ─ Schema 扩展（kind/role/tie_origin/...）              │
│   ensure_relationship_schema() + migrate_relationships()      │
└──────────────────────────────────────────────────────────────┘
```

每一层都向后兼容：缺失字段时使用默认值，旧记录继续工作。

### 1.1 Layer 1 — Schema

每条关系记录在原有 4 标量上叠加：

```jsonc
{
  "closeness": 0.85, "trust": 0.80, "obligation": 0.80, "friction": 0.10,
  "last_interaction_day": 7,        // 既有
  // -- 新增 --
  "kind": "ghost",                  // "agent"=同框 / "ghost"=场外
  "role": "mother",                 // 见角色速查表
  "tie_origin": "hometown",         // 自由文本：college / first_job / online ...
  "profile": {                      // ghost 有，agent 通常为空
    "name": "李母", "city": "重庆", "vibe": "操心"
  },
  "channels": ["call", "visit"],    // 远程互动渠道
  "decay_rate": 0.001,              // 由 role 决定的默认值
  "obligation_base": 0.80,
  "last_contact_day": 7,            // 与 last_interaction_day 同步
  "dunbar_tier": "inner"            // enforce_dunbar 写入
}
```

迁移由 `ensure_relationship_schema(item)` 完成，无副作用、幂等、原地填充。

### 1.2 Layer 2 — Backstory（Ghost 名单）

调用 `bootstrap_social_roster(agent, llm_call)`：

- 首次启动每个智能体时执行一次（幂等：当 agent 已经有 ghost 时直接跳过，除非 `force=True`）
- LLM task 名是 `social_backstory`，prompt 要求输出 `{"ghosts": [...]}` JSON
- 解析失败时 fallback 到启发式的 8 个种子关系（母/父/兄弟/老朋友/老同学/前同事/老师/邻居）
- 每条 ghost 自动写入 role-driven 的 decay_rate / obligation_base / channels
- ID 冲突时自动加后缀（`g_mother`, `g_mother_2`）

**为什么不让用户手填**：上千个 agent 一个个填不现实；LLM 编出来的人选已经够拟真，而且后续可以由场外事件慢慢演化。

### 1.3 Layer 3 — 场外生活事件

`generate_ghost_event(agent, day, llm, rng)` 按权重采样一个 ghost + 一个模板，组装出一个事件 dict。

权重 = `closeness × 1.0 + obligation × 0.6 + min(0.5, gap × 0.01)`。"长期未联系"会轻微提升被选中概率（人会偶尔被远房表哥之类突然问候）。

6 个模板：

| 模板 | 触发条件 | state_effects | signal |
| --- | --- | --- | --- |
| `ghost_birthday` | closeness ≥ 0.30 | +emotion, +time_pressure | positive |
| `ghost_illness` | closeness ≥ 0.45 / kin or friend | -emotion, +stress | neutral |
| `ghost_milestone` | closeness ≥ 0.30 | +emotion | positive |
| `ghost_request` | closeness ≥ 0.40 / kin or friend | -emotion, +stress, -econ_security | neutral |
| `ghost_reconnect` | gap ≥ 30 天 / past or community | +emotion | positive |
| `ghost_conflict` | closeness ≥ 0.45 | -emotion, +stress, -self_control | negative |

生成的事件通过 `life_events.add_life_event` 推入既有的事件管线，由 `drain_due_life_events` 在指定时间消费，state_effects 走原有逻辑，无需新增中间层。

同时 `last_contact_day` 与该 ghost 的关系标量根据 signal（positive/neutral/negative）更新。

### 1.4 Layer 4 — Dunbar + 角色化衰减

**衰减**：`decay_relationships(agent, day)` 按 role 的 decay_rate 衰减 closeness（亲属 0.001/天，网友 0.020/天）；超过 7 天未联系开始累积"愧疚"obligation（封顶为 `obligation_base × 1.4`）。closeness 有 0.03 的下限以保留可召回性。

**Dunbar**：`enforce_dunbar(agent)` 默认 5/15/50/150 四级 tier。超过 150 时按 `role_aware_weight` 从弱到强裁掉弱连接；**亲属/伴侣/孩子永远受保护**，不会因为权重低被裁。survivors 被打上 `dunbar_tier` 字段，可供下游做"今天主要找谁聊"的排序。

### 1.5 Layer 5 — 社交桥 + 信息不对称

- `shared_ghosts(a, b)`：找出两个智能体之间的 ghost 桥，按 `tie_origin` / `city` / `name` 三种匹配返回桥列表。可在对话生成时注入"听说你也是 X 大的"这种 homophily 信号。
- `disclose_ghost(observer, source_id, ghost_record, ghost_key)`：把某条 ghost 的快照拷贝到 `observer["known_others"][source_id]`。在对话/反思中提到才会触发，未提到的对方永远看不到——天然实现信息不对称。
- `known_ghosts_of(observer, source_id)`：取该 observer 知道的、关于 source 的 ghost 列表。默认是空 dict。

---

## 2. 主循环挂钩点

总共三处插入，全在 `generative_city_sim.py`：

| 位置 | 调用 | 频率 |
| --- | --- | --- |
| `~5580`（in-sim relationship 默认值初始化之后） | `migrate_relationships(a)` + `bootstrap_social_roster(a, call_llm)` | 每个 agent 启动一次 |
| `~5705`（每日 `for day in range(...)` 开头） | `_maybe_inject_ghost_event(a, day, "08:30")` | 每个 agent 每日按 `GHOST_EVENT_DAILY_P=0.18` 概率 |
| `~6691`（`consolidate_day` 之后、`save_agent_relationships` 之前） | `decay_relationships(a, day)` + `enforce_dunbar(a)` | 每个 agent 每日一次 |

`relationship_update`（在每个 tick 反思后调用）也被微调：现在每次都同步 `last_contact_day = today`，让衰减子系统看到的"最近联系"始终最新。

---

## 3. 关键取舍

| 决策项 | 选择 | 理由 |
| --- | --- | --- |
| Ghost 是 dict 字段还是独立表？ | dict 字段（`kind="ghost"`） | 与现有 `agent["relationships"]` 同管线，省一套持久化 |
| LLM 失败怎么办？ | 启发式 8 个种子兜底 | 仿真不能因为外部依赖卡死 |
| 衰减是否会清零关系？ | 不，下限 0.03 | 保留"模糊记得"的可召回性 |
| 亲属是否会被 Dunbar 裁剪？ | 不 | 真人不会因为"半年没联系"就把妈剔出名单 |
| 信息不对称是否默认开启？ | 是 | `known_others` 必须显式 disclose 才能填充 |
| Ghost 互动消耗 token 吗？ | 仅在 LLM 可用时调用 `ghost_event` task；不可用走模板 | 控制成本 |

---

## 4. 可调参数

| 常量 | 位置 | 默认 | 含义 |
| --- | --- | --- | --- |
| `GHOST_EVENT_DAILY_P` | `generative_city_sim.py` | `0.18` | 每个 agent 每天触发 ghost 事件的概率（≈一周一次） |
| `_NEGLECT_GUILT_THRESHOLD_DAYS` | `social_network.py` | `7` | 多少天未联系开始累积愧疚 |
| `_NEGLECT_GUILT_PER_DAY` | `social_network.py` | `0.005` | 每天愧疚增量 |
| `_MIN_CLOSENESS_FLOOR` | `social_network.py` | `0.03` | closeness 衰减下限 |
| `DUNBAR_TIERS` | `social_network.py` | `{inner:5, close:15, acquaintance:50, weak:150}` | 圈层上限 |
| `ROLE_CONFIG[*].decay_rate` | `social_network.py` | 见附录 A | 每个角色每日 closeness 损耗 |

---

## 5. 测试矩阵

| 测试文件 | 覆盖 |
| --- | --- |
| `tests/test_social_network_schema.py` | schema 迁移 / role-aware 权重 / 与既有 `relationship_weight` 共存 |
| `tests/test_social_backstory.py` | LLM 正常解析 / fallback / 幂等性 / role 校验 / ID 冲突 |
| `tests/test_ghost_events.py` | 采样命中 / state_effects 范围 / 长间隔触发重连 / LLM 覆盖 / signal 回写 |
| `tests/test_dunbar_decay.py` | 亲属慢衰减 / 愧疚封顶 / closeness 下限 / Dunbar 裁剪 / 亲属保护 / 分层 |
| `tests/test_social_bridge_disclosure.py` | tie_origin/city/name 桥 / 默认不可见 / disclose 后可见 / 源隔离 |
| `tests/test_simulation_social_integration.py` | bootstrap + in-sim update 共存 / 混合衰减 / life_events 管道贯通 / role-aware 优于 legacy |

共 37 个用例。原有 `tests/test_relationship_weighted_social_context.py` 仍然通过（向后兼容）。

---

## 6. 未来扩展位

- **跨智能体"得知"的自动化**：目前 `disclose_ghost` 需要显式调用，未来可在对话/反思阶段抽取 ghost 引用自动 disclose。
- **Ghost ↔ Ghost 之间的关系**：现在 ghost 是叶节点，互相不知道。如果要做"我妈和我表姐有矛盾"这种二度关系，需要扩 ghost record。
- **结构化时间事件**：生日/节日目前嵌在 closeness 阈值里，未来可加 `ghost.profile.birthday` 让事件发生在具体日期。
- ~~**岗位驱动的 coworker 生命周期**：换工作时旧 coworker 自动转为 `former_coworker`、衰减率切档；当前需要外部触发。~~
  **已实现（2026-08-29）**：`retire_work_ties()` 执行切换，由「换工作 / 失业」人生事件触发
  （`events/plugin.py:_apply_job_change`）。`coworker` / `boss` / `subordinate` 三个
  current-work 角色转为 `former_coworker`，衰减率 0.006 → 0.015、义务 0.42 → 0.20、
  渠道从 face+chat 降为 chat。`client` 不转（客户可能跟着人走）。
- **Visualization**：可以把每个 agent 的 social_roster 输出成节点图，便于人工检查。

---

## 附录 A — 角色速查表

| role | category | decay_rate | obligation_base | protected | channels |
| --- | --- | ---: | ---: | :-: | --- |
| `mother` | kin | 0.001 | 0.80 | ✓ | call, visit |
| `father` | kin | 0.001 | 0.80 | ✓ | call, visit |
| `parent` | kin | 0.001 | 0.78 | ✓ | call, visit |
| `sibling` | kin | 0.002 | 0.62 | ✓ | call, chat |
| `grandparent` | kin | 0.001 | 0.70 | ✓ | call, visit |
| `relative` | kin | 0.004 | 0.40 | ✓ | chat |
| `spouse` | kin | 0.000 | 0.85 | ✓ | face, call |
| `partner` | kin | 0.000 | 0.82 | ✓ | face, call |
| `child` | kin | 0.000 | 0.90 | ✓ | face, call |
| `best_friend` | friend | 0.004 | 0.55 | – | call, chat, visit |
| `close_friend` | friend | 0.005 | 0.50 | – | call, chat, visit |
| `friend` | friend | 0.008 | 0.40 | – | chat, visit |
| `classmate` | past | 0.012 | 0.28 | – | chat |
| `ex` | past | 0.010 | 0.20 | – | chat |
| `former_coworker` | past | 0.015 | 0.20 | – | chat |
| `old_friend` | past | 0.006 | 0.35 | – | chat, call |
| `coworker` | work | 0.006 | 0.42 | – | face, chat |
| `boss` | work | 0.005 | 0.55 | – | face, chat |
| `subordinate` | work | 0.006 | 0.40 | – | face, chat |
| `mentor` | work | 0.005 | 0.45 | – | chat, visit |
| `client` | work | 0.009 | 0.40 | – | face, chat |
| `neighbor` | community | 0.010 | 0.28 | – | face |
| `online_friend` | community | 0.020 | 0.15 | – | chat |
| `acquaintance` | community | 0.018 | 0.18 | – | chat, face |
| _未知 / 缺省_ | other | 0.008 | 0.40 | – | face |

**category 权重偏置**（用于 `role_aware_weight` 时的乘子）：kin × 1.30, friend × 1.10, work × 1.00, past × 0.85, community × 0.90, other × 1.00。

---

## 附录 B — API 速查

所有公开符号都在 `social_network.py` 的 `__all__` 列出。

### Schema

```python
ensure_relationship_schema(item, *, role="", kind="agent",
                           tie_origin="", profile=None,
                           current_day=0) -> dict
```
原地为单条关系记录补全新字段；幂等。返回同一 dict。

```python
migrate_relationships(agent, current_day=0) -> None
```
对整个 `agent["relationships"]` 调用 `ensure_relationship_schema`。

```python
role_config(role: str | None) -> dict
```
查角色配置；未知 role 返回带 `role_unknown` 标记的默认配置。

```python
role_aware_weight(item: dict | None) -> float
```
基于 closeness/trust/obligation/friction × category 权重，返回 ≥ 0.01。

### Backstory

```python
bootstrap_social_roster(agent, llm_call=None, *, current_day=0,
                        rng=None, force=False) -> list[dict]
```
- 默认幂等：agent 中已有任意 ghost 时直接返回 `[]`
- `force=True` 强制重新生成
- 返回新加入的 ghost 记录列表

LLM 接口签名：`llm_call(prompt, task=None, agent_id=None) -> str`，task 固定为 `"social_backstory"`。

### 衰减 / Dunbar

```python
decay_relationships(agent, current_day, cfg=None) -> {"touched": int, "current_day": int}
```
按 role 衰减 closeness/trust，长期忽视的关系累积 obligation 愧疚。

```python
enforce_dunbar(agent, limits=None) -> {"kept": int, "pruned": int, "tiers": dict}
```
裁掉最弱的非保护连接到 150 以内，并为所有生存记录写入 `dunbar_tier`。

### Ghost 事件

```python
generate_ghost_event(agent, current_day, llm_call=None, rng=None, cfg=None) -> dict | None
```
返回的 dict 形如：
```python
{
  "template_key": "ghost_birthday",
  "title": "李母的生日",
  "description": "...",
  "severity": 0.55,
  "impact_tags": ["relationship", "off_screen", "mother"],
  "state_effects": {"emotion": 0.04, ...},
  "channel": "chat",
  "ghost_key": "g_mother",
  "ghost_name": "李母",
  "ghost_role": "mother",
  "signal": "positive",
}
```
可直接 mapping 到 `life_events.add_life_event` 的 payload。

LLM task 名 `"ghost_event"`，期望返回 `{"title": "...", "description": "..."}`。

### 社交桥 / 信息不对称

```python
shared_ghosts(agent_a, agent_b) -> list[dict]
```
返回每个桥的 `{via, agent_a_ghost, agent_b_ghost, a_name, b_name}`。

```python
disclose_ghost(observer, source_id, ghost_record, ghost_key, current_day=0) -> dict
```
把 ghost 快照写入 `observer["known_others"][source_id][ghost_key]`。

```python
known_ghosts_of(observer, source_id) -> dict[str, dict]
```
读取 observer 知道的关于 source 的 ghost；默认空 dict（信息不对称）。
