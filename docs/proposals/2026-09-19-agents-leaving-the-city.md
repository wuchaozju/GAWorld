# 智能体可以离开本城市 —— 出差、探亲、旅行

日期：2026-09-19
状态：已实现（本提案随代码一起落地）
范围：新增 `gaworld/world/away.py`（离城状态词汇表）+ `gaworld/travel/`（destination / trigger / itinerary / plugin）+ `tests/test_travel_away.py`；改 `gaworld/behavior/dynamic.py`（共处判定）、`gaworld/world/local_physical.py`（占用度与本地环境快照）、`gaworld/family/plugin.py`（缺席不再静默）、`gaworld/twin/stages.py`（改用共享词汇表）、`gaworld/settings/behavior.py`（新配置块）、`gaworld/settings/config_docs.py`（面板注册）、`gaworld/plugins/__init__.py`（注册插件）。
**`generative_city_sim.py` 零改动。**

---

## 一、动机：仓里已经有一整套「外地」，但没有一个人能去

### 1.1 现状核查（全仓 grep，非推测）

| 事实 | 位置 |
|---|---|
| 社交层**已经**给每个居民生成了住在外地的亲友（ghost），schema 里带 `city` 字段 | `social/network.py:359`、`_heuristic_ghosts:389` |
| ghost 的允许渠道里**写着 `"visit"`**（母/父/祖父母/挚友/朋友/导师） | `social/network.py:51-76` |
| 但 ghost「从不参与在仿真内的共处循环，只通过远程渠道互动」——`visit` 从未落成一次真实的位移 | `social/network.py:14-16` |
| 家庭层**已经**会给居民派"抽空给{父母}打个电话**或回去看看**"的日常责任 | `family/duties.py:150-153`，人物由 `assign.py:331 _attach_remote_parents` 生成 |
| 「回去看看」无法执行：没有任何机制让 agent 离开地图 | 全仓无 trip / away 状态 |
| 唯一写过「异地」的地方是数字孪生：真人 GPS 落在地图外时，把 `locations["current"]` 写成 `异地（<place>）` | `twin/stages.py:33`（`AWAY_PREFIX`）、`:84` |
| 但那只是**显示覆写**，跑在 `move` 之后（`twin_mirror`），没有任何仿真语义，也没有"怎么回来" | `twin/stages.py:10-15` |
| 离线地名表已存在：34 个省级中心点 + `haversine_km`，纯离线 | `twin/places.py:28`、`:73` |
| 地图每个节点都带真实 `lat`/`lng`（程序化地图锚在杭州 `BASE_LAT=30.2741`，真实地图用真坐标） | `city_map.py:585-586`、`:10` |

结论：**「外地」在这个仓里不是缺失的概念，而是一个只读的概念。** 居民能想起外地的母亲、能因为长期不联系而累积 obligation、能收到一条「回去看看」的责任提示——然后什么也做不了。本提案补的是这条链路上唯一缺的一环：位移本身。

### 1.2 为什么这一环值得补

- **它是唯一能证伪「关系衰减」的机制。** `social/network.py` 的 `decay_relationships` 每天扣 closeness、涨 obligation，但 obligation 现在没有出口——它只能一直涨。有了探亲，obligation 才是一个有行为后果的压力量，而不是一个单调递增的读数。
- **它给「人口不是封闭系统」一个最小实现。** 现在城市是严格封闭的：N 个人，永远 N 个人在场。出差/旅行让**在场人数**成为一个随时间波动的涌现量，而不是常数。
- **成本极低**：整条链路是规则 + 已有的 haversine + 已有的省级中心表，零新增数据文件，零新增网络依赖。

---

## 二、设计

### 2.1 状态表示：结构化 trip + 复用 `异地` 标签

两份状态，各管一件事：

```python
agent["ext"]["travel"] = {
    "status": "away",          # planned / away / returning
    "purpose": "business",     # business / family / leisure
    "place": "北京",            # REGION_CENTRES 里的名字
    "distance_km": 1120.4,
    "home_node": "Riverside Block",   # ← 回来时落回哪里（真实节点名）
    "depart_day": 12, "return_day": 15,
    "fare": 1840.0,
}
agent["locations"]["current"] = "异地（北京）"   # 复用 twin.stages.AWAY_PREFIX
```

**为什么两份都要：**

- `current` 必须**不是**节点名，否则 `update_occupancy_from_agents`（`world/local_physical.py:74`）会把一个不在场的人算进某个地点的拥挤度——凭空造出人群。
- 但 `current` **不能**是唯一的状态，否则回程会瞬移：`move_agent` 拿 `origin = locations["current"]`（`sim/_location.py:288`），`shortest_path_with_distance` 对不存在的节点返回 `[], 0.0`（`city_map.py:1085`），`distance_between` 同样返回 `0.0`（`:1063`）——**从北京回家的路程会被算成 0 公里、1 个 tick、几乎零票价。** 回程必须从结构化的 `home_node` 重建，不能从标签反推。

新增 `gaworld/world/away.py`，只有三个函数：`is_away(agent)` / `away_label(place)` / `home_node_of(agent)`。它是这套词汇表的**唯一定义点**，`twin/stages.py` 的既有 away 路径也改为调用它，避免两处各写一份「异地」的判定。

### 2.2 谁会走：三类动机，各自挂在已经存在的量上

不设一个统一的「出行概率」旋钮。三类出行的驱动力不同，混成一个数就说不清标定的是什么：

| 类型 | 触发量（全部已存在） | 在外做什么 | 收入 |
|---|---|---|---|
| **出差** | 职业（`economy` 的 job / industry）+ 工作日 | 活动仍是「工作」 | 照常（`_is_income_activity` 认活动不认地点，`finance.py:405`） |
| **探亲** | ghost 里 `role ∈ kin` 且 `city` 非本市；obligation 越高、`last_contact_day` 越久越可能 | 陪伴、家务 | 无工作收入 |
| **旅行** | 周末/假期 + 可支配现金 + 大五 openness（`personality/traits.py`）+ 累积 stress | 休闲 | 无工作收入 |

**探亲的触发量是本提案的核心论点**：它不是新编的一个概率，而是把 `decay_relationships` 已经在算的 obligation 接上一个行为出口。closeness 衰减 → obligation 上涨 → 越过阈值 → 一次探亲 → `last_contact_day` 归零、obligation 回落。这是一个闭环，而不是又一个采样。

### 2.3 目的地与距离：复用省级中心表

目的地从 `twin/places.py:REGION_CENTRES` 抽样，**探亲时优先取 ghost 的 `city` 字段**（`social/network.py:359` 已经生成了它）。距离 = `haversine_km(地图中心, 省会中心)`（`places.py:73`）。

由距离推出行方式与票价，三档，边界按国内实际出行习惯：

| 距离 | 方式 | 单程时长 | 票价量级 |
|---|---|---|---|
| < 300 km | 高铁 | ~2 h | 距离 × 0.45 元 |
| 300–1200 km | 高铁 | 距离 / 250 km/h | 距离 × 0.45 元 |
| > 1200 km | 飞机 | 距离 / 700 km/h + 2 h 地面 | 距离 × 0.75 元 |

**这些系数是 (c) 类「合理猜测」**，按 Bench 的机制来源分级必须如此标注：由它们支撑的任何结论都不得单独立论。它们只决定一次出行贵不贵、久不久，不决定任何机制的定性形状。

### 2.4 在外的一天

`on_day_start` 携带**可变的** `schedule_map`（`generative_city_sim.py:4586`），插件按 purpose 改写当天日程；`get_activity_for_time`（`:2718`）逐 tick 从 `schedule_map` 读活动，**timeline 不用动**——这是整个接入里最省事的一点。

`location.resolve` 是 filter（`:3439`）：离城时返回空，`move_agent` 拿到 `desired_location=None` → `target == origin` → 走 `status: "stationary"` 分支（`sim/_location.py:300-311`）。于是：零位移、零通勤票价、零路网流量（`TrafficPlugin` 的 `ON_ROAD_STATUSES` 不含 `stationary`）。**不需要为离城在移动/交通层加任何特判。**

开销上：**离城的一天和在城的一天花一样多的 LLM。** 人在外地也在过日子，v1 不做压缩（见 §七）。

### 2.5 必须修的三处旧代码

这三处是本提案的**真实成本**，不修就是静默错误：

1. **共处判定会把所有外地人凑成一堆。** `detect_co_located_agents`（`behavior/dynamic.py:537-546`）对 `current` 做字符串相等。两个人都在外地时标签可能都是 `异地（北京）`，甚至无地名时都是 `异地`——他们会被判为"同一地点"，进而互相触发社交打断。加一行 `is_away` 守卫排除。
2. **占用度会多出幽灵键。** `update_occupancy_from_agents` 会把 `异地（北京）` 当成一个地点计数写进 `runtime["node_occupancy"]`。这个键没有任何读者，是惰性的——但它会出现在导出的占用表里误导分析。跳过离城者。
3. **家庭责任会无声消失。** `family/plugin.py:339` 的 `at_home` 在离城时自然变成 `False`，同住家人的责任段落直接不再出现——**方向对，但静默**。至少要把"你不在家"这件事写进感知，而不是让责任凭空蒸发。（把负担转移到同住伴侣身上是下一步，见 §七。）

### 2.6 回来

`return_day` 当天：从 `home_node` 重建回程（票价 + 时长按 §2.3），`current` 写回 `home_node`，`ext.travel` 清空。整趟行程写一条 episode（`memory/experience.append_agent_episode`，孪生已经在用），使它后续可被回忆——否则一次出行在记忆里不存在，等于没发生。

---

## 三、配置

`gaworld/settings/behavior.py` 新增 `travel` 块：

| 键 | 默认 | 含义 |
|---|---|---|
| `enabled` | **`False`** | 总开关。默认关——离城改变在场人数、社交共处和支出，**旧 run 不可比** |
| `seed` | `20260919` | 子系统自带种子，全局无种子时出发日仍可复现（与 family / personality 同规矩） |
| `max_away_share` | `0.15` | 同一天最多多少比例的居民在外（防止城市被掏空） |
| `fare_per_km` | `{"rail": 0.45, "air": 0.75}` | (c) 类系数，见 §2.3 |
| `daily_surcharge` | `180.0` | 在外每日住宿 + 外食，走 `charge_external_expense` 结算 |
| `business.base_daily_prob` | `0.004` | 工作日触发出差的基础概率（按职业调制） |
| `business.days` | `[2, 4]` | 出差天数区间 |
| `family.obligation_threshold` | `0.72` | 探亲的 obligation 触发线 |
| `family.daily_prob_over_threshold` | `0.18` | 越线后每日真正动身的概率（人是在一周内回去，不是内疚落地当天就走） |
| `family.days` | `[2, 5]` | |
| `leisure.base_daily_prob` | `0.02` | 周末触发旅行的基础概率（按开放性与压力调制） |
| `leisure.min_cash_months` | `1.5` | 低于这么多个月的现金储备就不旅行 |
| `leisure.days` | `[3, 7]` | |

（实现时把提案里的 `daily_spend_mult`（在外支出**倍率**）换成了 `daily_surcharge`（在外**每日固定开销**）：`expense_mult` 在 `finance.py:1962` 只由宏观周期驱动，没有 per-agent 入口，要做成倍率就得改经济步进函数本身。固定开销走现成的守恒支出通道，一行调用，且同样表达了"在外更贵"。）

按 `docs/` 同步清单的规矩，**必须同时注册进 `config_docs.py` 的 `SECTIONS` + `LABELS` + `MANUAL_HELP`**，否则整个子系统在浏览器配置面板里根本不出现（回归闸：`tests/test_dashboard_family.py:43 test_every_config_fragment_has_a_panel_section`）。settings 注释写英文，`MANUAL_HELP` 写中文。

---

## 四、验证门

`tests/test_travel_away.py`，40 条，无网络、无 LLM。

| # | 门 | 对应测试 |
|---|---|---|
| 1 | **零效应（硬门槛）**：`enabled=False` 时插件一个钩子都不注册，连跑 14 天日程、位置、`ext` 全部不变 | `test_disabled_registers_nothing` / `test_disabled_leaves_the_day_untouched` |
| 2 | **回程不瞬移**（最容易踩的坑）：先把 `city_map.py:1085` 那个 `([], 0.0)` 的静默退化**钉成断言**，再证明落地走的是行程里的 `home_node` 而不是标签 | `test_the_away_label_is_not_routable` / `test_home_node_comes_from_the_itinerary_not_the_label` / `test_landing_restores_a_real_position_and_closes_the_trip` |
| 3 | **不在场就是不在场**：不进任何地点的 `node_occupancy`；不与任何人构成共处对——**包括另一个同样在外地的人**，标签有地名和没地名两种碰撞都测 | `test_away_agent_holds_no_place_in_the_city` / `test_two_people_away_are_not_standing_together` / `test_unnamed_away_labels_collide_too` |
| 4 | **不产生路网流量**：离城者的 move 落在 `stationary` 分支，不在 `ON_ROAD_STATUSES` 里，`travel_pcu` 为 0 | `test_a_pinned_agent_makes_no_trip_and_no_road_load` |
| 5 | **obligation 闭环**（§2.2 论点的直接检验，不过则探亲动机模型不成立）：跑完整趟探亲后 obligation 下降、closeness 上升、`last_contact_day` 前移 | `test_going_spends_the_obligation_that_sent_them` |
| 6 | **确定性**：同种子两次跑逐日决策完全一致，换种子则不同 | `test_the_same_seed_puts_the_same_person_on_the_same_train` |
| 7 | **城市不会被掏空**：10 人、上限 0.2，连跑 19 天在外人数始终 ≤ 2 | `test_the_city_cannot_be_emptied` |
| 8 | **孪生的真人位置不被仿真接管**：有「异地」标记但没有行程的 agent，连跑 19 天既不被送回家也不被塞进行程 | `test_a_real_out_of_town_position_is_never_sent_home` |

**尚未做的一条**：跨种子的行为学判定（至少 3 个种子聚合、判据用基线相对而非绝对常数）。上面全是机制正确性，不是标定——任何关于「出行率对不对」的结论都还立不住，见 §八.5。

---

## 五、风险

- **城市被掏空**：三个触发叠加可能让同一天走掉一大半人，城市的社交密度塌掉。`max_away_share` 是硬闸，但它是个粗暴的全局裁剪——超限时按什么顺序拒绝，需要确定性规则（按 agent id 排序），否则引入顺序依赖。
- **标签碰撞**：`异地` 无地名时是所有人共用的同一个字符串。§2.5(1) 的守卫是必须的，不是可选的。
- **与孪生的交互**：真人 GPS 出城时，孪生也会写 `异地（…）`，但**没有** `ext.travel`。`is_away` 必须对两种来源都为真，而回程逻辑只对有结构化 trip 的那种生效——孪生的位置由真人决定，仿真不该把他"送回家"。这条要写测试锁住。
- **经济口径**：探亲/旅行期间没有工作活动 → 按 `_is_income_activity` 不产生小时收入。对月薪制居民这是错的（带薪年假）。**已知未修**，见 §八.1。

---

## 六、成本

零新增 LLM 调用**类型**，但离城的一天与在城的一天开销相同（§2.4）。触发与行程全是规则计算，可忽略。无新增数据文件、无网络依赖（省级中心表已在仓内，且 `twin/places.py` 明确承诺离线）。

---

## 七、不在本提案范围（刻意留出）

- **离城日压缩成一条摘要**。`sim/_fastforward.py:1199 simulate_agent_day` 正是现成的「一天一次 LLM」路径，但 `StagePipeline.run_step`（`sim/pipeline.py:114`）无条件跑完每个 stage，没有跳过语义。要接，得给 pipeline 加一个通用的 `step["_skip_stages"]`——三行，且在 `sim/pipeline.py` 而非 `generative_city_sim.py`。v1 不做：先证明离城这件事本身是对的，再省它的钱。
- **结伴出行**（一家人一起去、同事一起出差）。需要跨 agent 的行程协商，是 `collaboration` 那条线。
- **家庭负担转移**（一方出差，另一方多承担育儿）。§2.5(3) 只保证不静默，不做转移。
- **迁出/迁入**（永久离开这座城市）。那是人口学，不是出行；本提案的 trip 永远会回来。
- **在外地遇到的人**。外地没有地图、没有居民，`visit` 的对象仍然是 ghost。把外地也建成城市是 `gaworld/city/` 那条线的事。

---

## 八、落地时做的决定（原「待确认」）

1. **月薪制居民休假期间的收入 → 保持现状，并在此明说这是已知的简化。** 探亲 / 旅行期间没有工作活动，按 `_is_income_activity`（`finance.py:405`，认活动不认地点）不产生小时收入。对月薪制居民这是**错的**（带薪年假）。改对需要动薪资结算路径，范围远超本提案；等薪资口径本身重构时一起修。**在此之前，任何依赖离城期间收入的结论都不成立。**
2. **`max_away_share` 的裁剪顺序 → 按 agent 列表顺序**（稳定、可复现）。代价是系统性偏差：靠前的居民永远优先获得出行名额。上限很少真正咬合，但一旦咬合，这个偏差是真的。
3. **离城状态落进 recorder → 落了。** `travel.depart` / `travel.return` 两张表，出发与返回各记一行完整行程。它很便宜，而且是本子系统唯一的对外可观测量——不落的话「今天谁不在城里」就只能靠单测看，看不到全局形状。
4. **探亲触发 → 纯规则，不调 LLM。** obligation 越线后按日概率动身。让 LLM 判断「现在该不该回去」更像人，但会引入一个无法跨种子复现的决策点；与本仓其它触发器（人生事件、动态行为）的做法保持一致。
5. **仍然待做：标定。** §四 的 8 条门全是机制正确性——「离城的人确实不在城里」「回程确实是一段路程」。**没有一条说出行率是对的。** 出差概率、obligation 阈值、票价系数都是 (c) 类猜测，要立论必须跨种子、跨取值做方向一致性检验（判据基线相对，不用绝对常数），这一步还没做。

---

相关：`docs/proposals/2026-09-19-endogenous-road-congestion.md`（同类的"补一条已经写好读侧、缺写侧"的改造）、`gaworld/social/network.py`（ghost 与远程渠道）、`gaworld/twin/places.py`（离线地名与距离）。
