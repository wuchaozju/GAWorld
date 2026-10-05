# 场所容量：满了就进不去

日期：2026-10-03
状态：**已实施（2026-10-03）**——§2.2 选 B（实时计数 + 每 tick 按种子洗牌），§2.4 用默认的 commerce + leisure。
实现：`gaworld/world/venue_capacity.py`（记账与洗牌）+ `VenueCapacityPlugin`（`gaworld/world/plugin.py`）
+ 主循环一个通用的 `tick.agent_order` 过滤点；测试 `tests/test_venue_capacity.py`（含真实主循环）。
上游：路线图 P1-6；拥堵提案（`2026-09-19-endogenous-road-congestion.md`）里排出的后续之一：
「场所容量要能让动作失败（现在 100 人挤进 20 人餐馆都吃得上）」

---

## 一、现状核查（全仓 grep，非推测）

1. **容量有，但只用来写感知文本。** 每个地图节点都带 `capacity`（`world/city_map.py` 的
   `CATEGORY_LANDUSE` 类别默认值：commerce 600、leisure 700、medical 500、residential 400……，
   hub 再 ×1.5；citymap 里可逐点覆盖，但三张现有地图一处都没覆盖）。`LocalPhysicalPlugin`
   每个 tick 从居民位置算出 `node_occupancy`，只进「身边的物理环境：比较拥挤」那一行感知，
   以及 P2 的拥挤突变异常。
2. **移动已经过闸门，但闸门里没有容量。** `_stage_move` 把每次移动包成
   `ActionRequest("move")` 交给 `Controller.validate`：`location_exists` 默认开（实际几乎不触发），
   `venue_open` 默认关。被拒时居民**留在原地**、拒绝原因进下一 tick 的感知
   （`agent["_action_denials"]`），并记 `action.denied`。容量校验的落点现成，只缺校验器本身。
3. **规模上它永远不会触发。** 默认 12 人、语料 51 人、合成小镇 500 人，对 600–900 的容量，
   `agents_represent = 1` 时占用率最高也就个位数百分比。和拥堵同构：一个抽样居民代表多少真人，
   是让它生效的那个旋钮。
4. **主循环在一个 tick 内按固定顺序（`agent_ids` 顺序）逐个跑完每个居民的整条认知管线。**
   这决定了 §2.2 的难点。

## 二、设计

### 2.1 一个新的校验器 `venue_capacity`

挂在 `LocalPhysicalPlugin` 上，排在 `location_exists` 之后、与 `venue_open` 同级。
只管 `move` 请求，只管 §2.4 列出的类别。判据：

```
有效占用 = 计数 × agents_represent
有效占用 + agents_represent > capacity  → 满
```

### 2.2 计数口径（**需要拍板**）

难点：同一个 tick 里，前面的居民已经走进去了，后面的居民看到的人数要不要算上他们？

| | 怎么数 | 好处 | 代价 |
|---|---|---|---|
| **A. 滞后** | 只数 tick 开始时已经在里面的人（`node_occupancy`，已有） | 与遍历顺序无关，与拥堵层「一 tick 滞后」的不变量一致；零主循环改动 | **同一时刻扎堆到达时会冲破容量**：12:00 一百人同时去吃饭，tick 开始时里面没人，全放进去。容量只在之后的 tick 起作用（满了以后，新来的进不去，直到有人离开） |
| **B. 实时计数 + 本 tick 洗牌** | tick 开始的人数 + 本 tick 已放行的人数；开启时每个 tick 用种子把居民处理顺序洗一遍 | 扎堆到达时也卡得住；谁抢到最后一个位置是按种子的公平抽签，可复现 | 要在主循环加一个通用的顺序过滤点 `tick.agent_order`（3 行，默认原样返回，关闭时逐位不变）；开启时**其他依赖处理顺序的东西**（偶遇、同户互动的先后）也跟着随机化 |
| C. 实时计数、不洗牌 | 同 B，但顺序固定 | 最简单 | 编号靠前的居民永远先抢到位置——与 id 相关的系统性偏差（离城提案 §8.2 接受过同类偏差，但那里上限很少咬合；这里高峰时每天都咬合） |

**倾向 B。** A 解决不了提出这件事的那个场景（扎堆到达），C 的偏差在高峰时是系统性的。
B 的顺序过滤点是通用的内核扩展点，不只为这一个功能。

### 2.3 满了怎么办

1. **先改址**：`nearest_by_category` 找同类最近的 `redirect_top_k`（默认 4）个场所，
   取第一个有空位、且此刻营业的，用 `Verdict.rewrite` 改写目的地；记 `venue.redirect`。
2. **都满就拒绝**：沿用现有拒绝语义——留在原地，下一 tick 感知里出现
   「你想前往【X】，但没能成行：【X】已经满了」，记 `action.denied`。

活动本身不变（"吃午饭"仍是吃午饭，只是换个地方或在原地），经济按活动关键词记账，不受影响。

### 2.4 适用类别（**需要确认**）

默认只管 **commerce、leisure**——人们自主选择去不去、去哪家的地方。

| 类别 | 管不管 | 理由 |
|---|---|---|
| commerce / leisure | 管 | 满了换一家是日常经验 |
| residential | 不管 | 回自己家不该被拒 |
| industry / education / government | 不管 | 上班上学是承诺型活动，容量是按编制定的，被拒没有意义 |
| medical | 不管 | 拒绝看病是很强的主张；医院拥挤应表现为等待，不是进不去（不在本提案范围） |
| transit | 不管 | 站点拥挤是拥堵层与运力的事 |
| mixed | 不管 | 类别不明，容量默认值最没依据 |

### 2.5 放大系数

默认沿用 `traffic.agents_represent`（同一个抽样人口，一个居民代表的真人数不该有两个答案），
可用 `local_physical.capacity.agents_represent` 单独覆盖。

## 三、配置

```python
"local_physical": {
    ...,
    "capacity": {
        "enabled": False,             # 默认关：开启改变谁在哪，开启前后的 run 不可比
        "categories": ["commerce", "leisure"],
        "agents_represent": None,     # None = 沿用 traffic.agents_represent
        "redirect_top_k": 4,          # 改址时看几个同类场所；0 = 不改址，满了直接拒绝
    },
},
```

默认关、选择开启，所以不新增可比性版本（`gaworld/core/comparability.py` 的规则：
默认关的开关由运行清单里的配置快照区分）。

## 四、验证门（机制正确性；**都不说明容量参数是对的**）

1. 关闭时与现状逐位一致（同种子轨迹相同）。
2. 容量充足时不改址、不拒绝。
3. 满员：同类有空位 → 改址到最近的有空位且营业的那家；全满 → 拒绝、留在原地、感知里有原因。
4. 类别外的地点（住宅、单位、医院）永不因容量被拒。
5. （B）同种子两次运行结果相同；换种子后「谁被拒」变化，且被拒概率与 id 无关
   （对 id 做秩相关检验，不显著）。
   （A）打乱遍历顺序结果不变。
6. 扎堆场景：容量 20、30 人同一 tick 到达——B 下放进去恰好 20 人；A 下 30 人（写成已知局限的测试）。

## 五、机制来源

准入控制本身是平凡的；**参数全是 (c) 类**：类别默认容量是猜的、`agents_represent` 是建模旋钮。
写进 `benchmark/MECHANISM_PROVENANCE.md`。依赖它的结论只能用「跨 `agents_represent`
取值的方向一致性」立论，不能报一个绝对的拒绝率。

## 六、不在本提案范围

- 排队与等待时间（医院、热门餐厅门口等位）。
- 预约 / 提前订位。
- 按房间计的容量（前端的室内空间树还没下沉到 `gaworld/world`）。
- 价格对拥挤的响应。
- 为场所单独标定容量（需要数据）。
