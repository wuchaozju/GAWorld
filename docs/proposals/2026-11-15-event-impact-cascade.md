# 事件影响级联与事件评估（2026-11-15）

状态：已实现。
代码：`gaworld/events/impact.py`（影响单与影响池）、
`gaworld/events/impact_env.py`（环境事件规则表）、
`gaworld/events/appraisal.py`（规则层评估）、
`gaworld/events/appraisal_llm.py`（模型层评估）、
`gaworld/events/cascade.py`（影响筛选、影响账本与日程落地）、
`gaworld/events/impact_plugin.py`（编排插件）、
`gaworld/sim/_stages.py`（`appraise` 阶段）。
配置：`CONFIG["event_impact"]`（`gaworld/settings/runtime.py`，默认开启）。
测试：`tests/test_event_impact.py`。
可比性版本：Epoch 14。

---

## 1. 为什么

事件落地时只有三样东西：一组心理状态增量（`state_effects`）、一行「人生事件：……」
的提示词、以及——只有当模板带 `employment` 标签时——工作与收入的改写。

也就是说：**事件的绝大部分后果并不发生**。

* 「突然生病」不会让日程空出一上午，不会产生医疗支出，不会让同住的人多一份照料负担；
* 「失业」只改收入，不改「接下来几个月每天要找工作」这件事在日程里的形状；
* 「亲人离世」除了让情绪掉一点，不改变家里的分工、支出和安排；
* 环境事件（暴雨、拥堵、涨价、场所停业）几乎是纯描述的——它们出现在提示词里，
  但从不真正改写任何状态。

还有第二个问题：**所有居民对同一件事的反应是一样的**。
`state_effects` 是模板里的常量，`severity` 是事件的全局属性。一个有房贷有孩子的人
和一个单身自由职业者遇到同一次失业，得到的 delta 完全相同。这与现实相反，
也使「人格影响行为」这条线在事件路径上断掉了——人格已经在动作选择、情绪基线、
信息食谱里起作用，唯独在最重要的事情上不起作用。

## 2. 做了什么

### 2.1 三层分离

| 层 | 是什么 | 谁算 |
|---|---|---|
| **客观影响池** | 这件事在物理上会造成什么 | 事件模板 / 环境规则表，声明式 |
| **主体预估** | 这个居民**怎么看**这件事 | OCEAN + 当前状态 + 情境暴露度，规则层，零 token |
| **实际落地** | 真正改变了什么 | 客观池 × 主体预估，再叠加模型给的行动计划 |

核心不变量：**实际影响 = 客观影响 × 主体预估**。严重度不再是事件的全局数字，
而是每个居民各有一份。

### 2.2 影响单

```python
Impact(domain, kind, params, scale, duration_days, note)
```

第一版的四个领域与影响类型：

| domain | kind | params | 落地到哪 |
|---|---|---|---|
| `economy` | `expense` | `category`, `amount` | `charge_external_expense`（守恒闭环不变） |
| `economy` | `bonus` | `category`, `amount` | 一次性进账；钱从政府池出（福利彩票是国有机构），守恒不变 |
| `economy` | `income_change` | `fraction`, `days` | 临时的日薪变化（求学、误工）；到期自动恢复 |
| `family` | `care_load` | `delta`, `duty` | 家庭记录的照料负担叠加 + 额外家务 |
| `family` | `member_state` | `role`, `state` | 户内成员状态（生病 / 需照料） |
| `schedule` | `activity_replace` | `targets`, `replacement`, `window_minutes` | 当天日程改写 |
| `schedule` | `activity_add` | `time`, `activity`, `minutes` | 插入一项新安排 |
| `environment` | `condition` | `key`, `label`, `scope` | 城市/个人环境状态，进入感知 |

`params["amount"]` 是**严重度 1.0 时**的标准量；实际扣账时再乘事件的客观严重度与
主体预估系数，因此一场 0.5 严重度的小雨只扣半份车费。

人生事件的客观影响池写在模板的 `impacts` 段里；环境事件的客观影响池由
`gaworld/events/impact_env.py` 的规则表按关键词与 `impact_tags` 匹配得到
（暴雨、交通、涨价、停业、高温、空气质量）。

### 2.3 规则层评估

`gaworld/events/appraisal.py::rule_appraisal` 永远运行、零 token，输出：

* `perceived_severity` — 客观严重度 × 敏感度。
  敏感度由三处叠加：**人格**（N 高放大、C 高对不可控的钱与时间更焦虑、
  E 高放大社交与家庭事件、O 高放大陌生情境、A 高放大冲突与恢复类事件）、
  **状态脆弱性**（stress 高、经济安全感低、时间压力高）、
  **情境匹配**（失业 × 有孩 / 负债更重；疾病 × 同住老人小孩更重）。
* `concerns` — 各领域的关注权重（人格兴趣 × 情境暴露度），决定哪些领域真的落地。
* `coping_style` — 应对方式：行动解决 / 求助他人 / 内敛消化 / 外化情绪 / 探索重构。
* `resilience` — 韧性系数，缩放总影响。

### 2.4 模型层评估：思考-反应-行动

`gaworld/events/appraisal_llm.py`。**默认开启，但只在 `severity ≥ 0.55` 时调用**
（`event_impact.appraisal.llm_min_severity`），每个事件每个居民一次。

一次调用产出结构化结果：

```json
{
  "thought": "……",
  "appraisal": {"perceived_severity": 0.72, "primary_concern": "economy",
                "concerns": ["economy", "schedule"], "duration_days": 14,
                "expected_consequences": ["本月收入中断", "需要重新找工作"]},
  "emotion": {"delta_emotion": -0.15, "delta_stress": 0.18, "tone": "焦虑但克制"},
  "plan": {"actions": [{"kind": "activity_replace", "target": "上午的班",
                        "replacement": "去医院"}],
           "seek_help_from": ["伴侣"], "info_needed": ["医保报销范围"]}
}
```

* **模型给的 `perceived_severity` 不直接覆盖规则层**，而是被夹在
  `[规则值 × 0.5, 规则值 × 1.8]` 之间——模型看得更细，但不能让一个人的一次判断
  把客观事实推翻。夹逼用的是**未截断**的规则值：客观严重度高时，截断过的规则值
  会让所有人都顶到 1.0，个体差异随之消失。
* `emotion` 增量按预估严重度缩放后叠加进状态。
* `plan.actions` 变成真的日程改写：`activity_replace` / `activity_add` 翻译成同一种
  影响单，与模板的影响走同一条路；`contact`（找谁说说）与 `seek_info`（先弄清楚
  什么）翻译成两项新增安排。

### 2.5 落地：各域自己接

编排者（`EventImpactPlugin`）不 import 领域逻辑，只发 `event.impact.apply`：

* **经济** → `gaworld/economy/plugin.py` 订阅，扣账走 `charge_external_expense`，
  钱从支票账户流向 firms 池，货币守恒闭环不变。
* **家庭** → `gaworld/family/plugin.py` 订阅，写家庭记录的照料负担叠加与额外家务，
  并更新户内成员状态。
* **环境** → 编排插件自己维护城市/个人环境状态，通过 `perception.compose`
  让居民真的感知到。
* **日程** → 日程住在 `scope.schedule_map` 里，由 `appraise` 阶段就地改写。
  改写结果一律写回 `(时间, 活动)` 的**元组**形式——这是 `schedule_map` 的规范形式，
  也是 `get_activity_for_time` / `apply_schedule_override` /
  `reshape_day_for_life_event` 唯一认的形式（仿真器里有两处写成字典，而
  `get_activity_for_time` 读字典时会逐条跳过，居民会变成「个人时间」）。
  `appraise` 阶段读回活动时两种形状都认。

### 2.6 管线位置

```
prepare → appraise → perceive → interrupts → plan → adjust_activity → move
 → select_action → reflect → update_state → broadcast → memorize → record
```

`appraise` 是新增阶段（可配置、可 ablate）。它的产物：

* 进入 `perceive` 的环境上下文（「我对这件事的判断：……」）；
* 进入 `plan` 的决策参考；
* 被 `adjust_activity` 用来决定要不要改日程；
* 情绪增量在 `update_state` 前叠进 `agent["state"]`；
* 一条结构化的「事件应对」记忆。

### 2.7 防止影响被重复施加

事件有两个生命周期：人生事件每天一次（有稳定 id），环境事件每个 tick 都会重新生成
（id 里带日期和时间）。若不加约束，一场暴雨会在一天里被扣十几次车费。

因此每个居民维护一份**影响账本**（`agent["_impact_ledger"]`）：

* **每个事件只评估一次**——一条事件的后果不能取决于 tick 循环看了它几遍。
  人生事件按事件 id 记；环境事件每个 tick 重新生成，按 `(日, type, topic)` 记。
* 每条影响按 `(领域, 类型, 签名)` 去重：人生事件一辈子只施加一次；
  环境事件一天内同类影响只施加一次。签名区分「同领域同类型但内容不同」的两条
  影响（模板说「上午去医院」与居民自己计划说「上午去诊所」是两次改变，不是同一次
  施加两遍）。

### 2.8 长周期（fast-forward）路径

`--fast-forward` 与 `--sim-years` 路径不跑 tick，管线阶段一次都不执行——那里正是
生活事件构成整个事件空间的地方。所以 life-events 插件在 `life.step` 上把这一轮
消费掉的事件（含摘要粗动作空间里的「人生大事」衍生事件）**发布**出来，级联插件
以更低的优先级接手评估与落地。

该路径没有逐 tick 的日程表，因此日程类影响不落地，其余三类照常。

### 2.9 可观测

`output/event_impact/` 下两份产物（插件自己的目录，`event_impact.output_dir`
可改）：

* `event_responses.jsonl` — 每个事件 × 每个居民的完整记录：思考、预估、情绪、
  计划、实际落地了什么；
* `event_responses.csv` — 一行一条（事件、居民、预估严重度、主关注域、落地条数），
  供归因分析。

## 3. 边界与代价

* **模型调用**：每次事件每人一次，只在严重度 ≥ 0.55 时发生。事件本身稀疏
  （每人大约每天 0–1 次），代价可控，但要注意 `severity` 被人为调低时这条路径会静默关闭。
* **规则层的粗糙**：敏感度是线性加权，不是模型。它能做的是把「人格有影响」这件事
  变成可测量的差异，不能代替判断。
* **模型与规则的夹逼**：模型预估值被限制在规则值的 0.5–1.8 倍之间。
  一个把小事想得比天大的居民不会让世界跟着他走。
* **环境域目前只到「感知 + 状态」**：环境条件进入了居民的环境上下文与记录，
  也会改日程（通勤改道、避开户外），但没有去改道路网络与场所的物理营业状态。
* **政策事件未纳入**：这一轮只接人生事件与环境事件。

## 4. 配置

```python
"event_impact": {
    "enabled": True,
    "appraisal": {
        "enabled": True,
        "llm_enabled": True,
        "llm_min_severity": 0.55,
        "max_events_per_step": 2,
    },
    "cascade": {
        "enabled": True,
        "max_impacts_per_event": 4,
    },
    "output_dir": "",   # 留空 = 插件自己的目录（output/event_impact/）
}
```

## 5. 可比性

默认开启且改变了默认配置下运行产出的东西——事件的日程、经济、家庭、环境后果
都不同了。追加 **Epoch 14**。
