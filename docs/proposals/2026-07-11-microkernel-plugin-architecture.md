# GAWorld 微内核插件化架构设计（参考 Agent-Kernel）

> 状态：**已批准（2026-07-11），迁移进行中**。参考文献：Agent-Kernel 技术报告（arXiv:2512.01610，ZJU-LLMs），
> 结合 GAWorld 现状（S1/S2 迁移中途，见 `docs/REFACTOR_PLAN.md`）。
> 本方案**不另起炉灶**，是既有重构计划的架构升级版：REFACTOR_PLAN 解决"代码放哪"，
> 本方案解决"模块之间如何解耦、外部如何扩展"。

---

## 一、动机：GAWorld 当前的耦合问题

GAWorld 的领域模块（economy / behavior / interests / skills / real_work / intervention /
social / world / env …）已经物理拆分，但**逻辑上仍是硬编码流水线**：

1. **主循环内联调用一切**。`run_simulation()` 里每个子系统都以
   `if CONFIG.get("xxx", {}).get("enabled")` + 直接函数调用的方式接入
   （如 `generative_city_sim.py:3322` 的 intervention feed、`:3368` 的 dynamic_behavior、
   `:3631` 的 real_work dispatch）。新增一个子系统 = 改主循环源码。
2. **Agent 是"上帝字典"**。`agent` dict 上散落着各子系统私有键
   （`env_preferences`、`growth`、finance 字段、intervention state …），
   子系统之间通过共享可变字典隐式耦合，删掉一个子系统会留下孤儿键。
3. **HookBus 只能旁观**。现有 7 个生命周期钩子（`on_simulation_start` /
   `on_day_start` / `on_time_tick` / `on_agent_pre_step` / `on_agent_post_step` /
   `on_day_end` / `on_simulation_end`）是纯 observer——回调返回值被丢弃，
   扩展无法向感知上下文注入内容、无法否决动作、无法替换认知阶段。
4. **认知回路不可替换**。perception → planning → action → reflection 的每一步
   都是主循环里写死的函数调用，无法做"换一个 Planner 对比实验"这类研究操作。
5. **动作是自由文本**。Agent 的"动作"是 LLM 输出的字符串 + `resolve_location`
   后处理，没有统一的动作注册表，无法校验可行性（去一个不存在/已关门的地点）、
   无法做权限控制、real_work 只能靠 router 旁路拦截。

这五条正好对应 Agent-Kernel 论文指出的 agent-centric 架构通病，
其解法（society-centric 微内核）可以有选择地移植。

---

## 二、Agent-Kernel 架构精要（我们借鉴什么）

| Agent-Kernel 设计 | 一句话 | 对 GAWorld 的价值 |
|---|---|---|
| **微内核 = 稳定核 + 插件** | 核只做插件注册、校验、消息、日志；一切场景逻辑是插件 | 主循环不再认识 economy/interests/…，新增子系统零侵入 |
| **Agent / Environment / Action 三解耦** | Agent 只有认知（profile/state/perceive/plan/invoke/reflect）；环境与动作是社会级共享实体 | 加/删 agent 不需要级联更新；动作可校验、可扩展 |
| **认知回路 = 可配置的插件序列** | Perceive→Plan→Invoke→State→Reflect，顺序和实现都可换 | 认知消融实验（换 Planner、去掉 Reflect）变成改配置 |
| **Controller（Mediator，无状态）** | 所有动作请求过 Controller 校验 + 提供运行时干预 API | 拦住 LLM 幻觉动作；dashboard 干预有正式入口 |
| **System：Timer / Messager / Recorder** | 全局时钟保证确定性；异步消息防死锁；统一记录 | GAWorld 已有雏形（时间网格 / 消息 inbox / 多处 jsonl），需收敛成内核服务 |
| **Database-per-Plugin** | 插件是数据所有权单元，各选各的存储，故障隔离 | 治"上帝字典"：插件状态归插件，agent 上只留命名空间 |
| **接口标准化（ABC + execute()）** | 同类插件同签名 → 可互换、可热替换 | 让"社区贡献一个经济模块"成为可能 |

**明确不采纳的部分**（理由见第八节）：Ray/MasPod 分布式 Pod 编排、
全部 agent 间通信过 Controller、Redis/PostgreSQL 数据库适配器体系、
运行中热替换插件。

---

## 三、设计原则

1. **绞杀者模式，不重写**。内核先包住现有代码，子系统逐个迁成插件；
   每一步测试全过、`--days 1` 输出与基线一致。
2. **内核极小**。内核只包含：Context、Clock、EventBus、Registry、Controller、
   Recorder 六件事，目标 < 800 行。领域逻辑一行都不进内核。
3. **插件对等**。GAWorld 自带的 economy/interests/… 与第三方扩展用**同一套接口**——
   自带子系统就是插件体系的第一批用户（dogfooding，保证接口够用）。
4. **配置即装配**。启用哪些插件、认知管线什么顺序，由 `CONFIG["plugins"]` /
   `CONFIG["pipeline"]` 声明，不改源码。
5. **兼容优先**。`agent` dict、现有输出文件路径、HookBus 的 7 个 phase 名全部保留；
   旧扩展点继续工作。

---

## 四、目标架构总览

```
┌─────────────────────────────────────────────────────────────┐
│                        应用层（不变）                          │
│   CLI · dashboard · Agent Studio · simviz · benchmark        │
├─────────────────────────────────────────────────────────────┤
│                     gaworld/kernel/  （新）                   │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────┐    │
│  │ SimContext│ │  Clock   │ │ EventBus │ │PluginRegistry│    │
│  └──────────┘ └──────────┘ └──────────┘ └──────────────┘    │
│  ┌──────────────────────┐ ┌───────────────────────────┐     │
│  │ Controller（动作校验＋ │ │ Recorder（统一结构化记录）  │     │
│  │  运行时干预）          │ └───────────────────────────┘     │
│  └──────────────────────┘                                   │
├──────────────┬──────────────────┬───────────────────────────┤
│  认知管线插槽  │   世界插槽        │        动作注册表           │
│ CognitionStage│ EnvironmentProvider│    ActionProvider        │
│ perceive/plan │ 地图·天气·事件·    │  move/communicate/work/   │
│ /act/reflect/ │ 社交网络·物理感知  │  consume/…（带校验器）      │
│ state/memory  │                  │                           │
├──────────────┴──────────────────┴───────────────────────────┤
│                    SystemPlugin（生命周期插件）                │
│  economy · interests · skills · real_work · intervention ·   │
│  dynamic_behavior · life_events · spatial_prefs · 第三方扩展  │
└─────────────────────────────────────────────────────────────┘
```

对应 Agent-Kernel 五模块的映射：

| Agent-Kernel | GAWorld 落点 |
|---|---|
| System（Timer/Messager/Recorder） | `kernel/clock.py` + `kernel/bus.py` + `kernel/recorder.py` |
| Controller | `kernel/controller.py` |
| Agent module（认知插件链） | `sim/pipeline.py` 的 CognitionStage 插槽 |
| Environment module | EnvironmentProvider 插槽（world/env/social 归入） |
| Action module | ActionProvider 注册表 + `@agent_callable` |

---

## 五、内核组件设计

### 5.1 SimContext —— 运行期唯一事实源

替代 37 处模块级常量（REFACTOR_PLAN 阶段 4c 的正式化）。所有插件通过它访问世界，
而不是 import 全局变量。

```python
@dataclass
class SimContext:
    config: dict                    # 合并后的最终配置（含 dashboard 覆盖）
    clock: Clock                    # 当前 day / time_str / tick
    agents: list[Agent]             # 存活 agent 列表（支持运行时增删）
    agents_by_id: dict[int, Agent]
    world: WorldFacade              # 地图/位置/天气/事件的只读查询门面
    bus: EventBus
    controller: Controller
    recorder: Recorder
    registry: PluginRegistry
    llm: LLMRouter                  # 现有 LLM_ROUTER
    rng: random.Random              # 内核级种子 RNG（插件可派生子流）

    def plugin_state(self, plugin_id: str) -> dict: ...   # 插件级共享状态
    def agent_ext(self, agent, plugin_id: str) -> dict: ...  # agent 命名空间状态
```

`agent_ext` 是治理"上帝字典"的关键：插件的 per-agent 状态一律放
`agent["ext"][plugin_id]`，现有裸键（`growth`、`env_preferences`…）在迁移期
由各插件自行做一次读旧写新的兼容。九个核心状态变量（emotion/stress/…）
是内核资产，仍留在 `agent["state"]`。

### 5.2 Clock —— 确定性时间（对应 Timer）

现有时间网格逻辑收敛为内核服务：`day`、`time_str`、`tick_index`、
`minutes_per_tick` 只从 Clock 读。价值不在新功能，而在**因果一致性**——
所有插件在同一 tick 视图下工作，为将来并行化 agent step 铺路
（并行时钟由内核推进，插件无法各自偷跑）。

### 5.3 EventBus —— HookBus 的超集（关键升级）

现有 HookBus 是 fire-and-forget observer。升级为三种钩子语义，
**这是插件从"旁观者"变成"参与者"的核心**：

```python
class EventBus:
    def on(self, event: str, fn, *, priority: int = 0): ...     # 订阅

    # 1) observe：现状语义，通知型，返回值忽略（100% 兼容 HookBus）
    def emit(self, event: str, **ctx) -> list[str]: ...

    # 2) collect：征集型 —— 每个订阅者返回 0..n 条贡献，内核合并
    #    用途：感知上下文注入、interrupt 候选征集、日程建议
    def collect(self, event: str, **ctx) -> list[Any]: ...

    # 3) filter：管道型 —— value 依次流过订阅者，每个可改写
    #    用途：改写 plan prompt、调整动作权重、后处理反思文本
    def filter(self, event: str, value: T, **ctx) -> T: ...
```

- 兼容：`CONFIG["extensions"]["hooks"]` 的旧配置原样工作（observe 语义）。
- 事件名沿用现有 7 个 phase，新增细粒度事件（见 5.7 事件目录）。
- `priority` 决定 collect/filter 的执行序；同优先级按注册序。
- 错误处理沿用 HookBus 的信任边界设计：捕获、告警、`strict` 模式下抛出。

### 5.4 PluginRegistry —— 插件注册与装配

```python
class Plugin(ABC):
    id: str                       # 唯一标识，兼作配置/存储/agent_ext 命名空间
    requires: tuple[str, ...] = ()  # 依赖的其他插件（拓扑排序装配）

    def setup(self, ctx: SimContext): ...      # 注册钩子/动作/认知阶段
    def teardown(self, ctx: SimContext): ...

    # 数据所有权（Database-per-Plugin 的 GAWorld 版）
    def output_dir(self, ctx) -> Path: ...     # output/<plugin_id>/，插件自管格式
```

装配来源（按序合并）：

1. **内置插件**：`gaworld.plugins.builtin` 列表（economy、interests、…迁移后在此）。
2. **配置声明**：`CONFIG["plugins"]`，形如
   `[{"id": "my_ext", "class": "my_pkg.ext:MyPlugin", "enabled": true}, ...]`。
3. **entry points**：`pyproject.toml` 的 `[project.entry-points."gaworld.plugins"]`，
   支持 `pip install gaworld-plugin-xxx` 即插即用。

现有 `CONFIG["xxx"]["enabled"]` 开关全部保留——内置插件的 `enabled` 默认
读各自旧配置键，行为不变。

### 5.5 Controller —— 动作校验 + 运行时干预（对应 Mediator）

无状态，两个职责：

**a) 动作门（validation gate）**。Agent 的动作在执行前过一遍校验链：

```python
class Controller:
    def register_validator(self, fn: Callable[[ActionRequest, SimContext], Verdict]): ...
    def validate(self, req: ActionRequest, ctx) -> Verdict:
        # Verdict: allow / deny(reason) / rewrite(new_request)
```

首批校验器（都是现有逻辑的收编，不是新功能）：
- 位置存在且营业（`world/local_physical` 已有数据）；
- 经济可负担（economy 插件注册：现金约束逻辑已有）;
- 政策合规（policy 插件注册：如"限行日不能开车"）。

`deny` 的动作以结构化理由回注给 agent 的下一次感知
（"你想去 X 但它已关门"），这正是 Agent-Kernel 拦考试说话的机制，
也顺便修掉了 LLM 幻觉动作导致的静默不一致。

**b) 运行时干预 API**。dashboard 现有的改配置/改 profile 收编为正式接口：

```python
controller.intervene("set_agent_state", agent_id=31, key="stress", value=0.8)
controller.intervene("inject_event", event={...})
controller.intervene("update_config", path="economy.credit.apr", value=0.15)
controller.intervene("add_agent", seed={...})   # 运行时人口变化（Adaptability）
controller.intervene("remove_agent", agent_id=7)
```

干预动作本身也是插件可注册的（`register_intervention`），
dashboard server 只是它的一个 HTTP 前端。每次干预写入 Recorder，
保证实验可追溯。

### 5.6 Recorder —— 统一结构化记录

现状：每个子系统各写各的 csv/jsonl/json（economy 5 种、memory 6 种、…）。
不强迁——插件仍可自管文件（Database-per-Plugin 原则），但内核提供统一入口：

```python
recorder.record("economy.ledger", {...})     # 表名即命名空间
recorder.record("action.denied", {...})
```

默认落 `output/records/<table>.jsonl`。价值：跨插件时间线对齐
（benchmark 和 compare-event 目前要各自解析 5 种格式）、
干预审计、以及给未来的回放/回滚留一条统一事件流。

### 5.7 事件目录（首版）

| 事件 | 语义 | 替代的现状 |
|---|---|---|
| `simulation.start / end` | observe | 同名 hook |
| `day.start / end` | observe | 同名 hook |
| `tick` | observe | `on_time_tick` |
| `agent.step.pre / post` | observe | `on_agent_pre_step / post` |
| `perception.compose` | **collect** → 注入感知片段 | intervention feed、skills 注入、local_physical 快照注入（现全为内联调用） |
| `interrupt.candidates` | **collect** → InterruptCandidate 列表 | dynamic_behavior 的各引擎 + 物理环境候选（现为内部 if 链） |
| `plan.prompt` | **filter** | 各处 prompt 拼接 |
| `action.selected` | **filter** → Controller 校验前的最后改写 | real_work router 旁路拦截 |
| `schedule.compose` | **collect/filter** | interests 的日程替换、周末重写 |
| `state.updated` | observe | 情绪扩散、mood 统计 |
| `memory.consolidate` | observe | skills 蒸馏、记忆压缩的触发点 |

---

## 六、三类扩展插槽

### 6.1 CognitionStage —— 认知管线（对应 Agent module 插件链）

`run_simulation` 内层循环重构为阶段序列，每阶段读写共享的 `StepContext`
（对应 Agent-Kernel "component 以公共属性缓存插件数据" 的设计）：

```python
@dataclass
class StepContext:                 # 单个 agent 单个 tick 的数据总线
    agent: Agent
    scheduled_activity: str
    perception: str = ""
    recall: str = ""
    plan: str = ""
    action: ActionRequest | None = None
    outcome: str = ""
    reflection: str = ""
    extras: dict = field(default_factory=dict)   # 插件命名空间暂存

class CognitionStage(ABC):
    name: str
    def run(self, step: StepContext, ctx: SimContext) -> None: ...
```

管线由配置声明，默认与现状等价：

```python
CONFIG["pipeline"]["agent_step"] = [
    "perceive", "recall", "interrupts", "plan",
    "adjust_activity", "select_action", "execute",
    "reflect", "update_state", "record_memory",
]
```

由此获得的能力（全部是现在做不到的）：
- **替换**：`{"plan": "my_pkg:RulePlanner"}` —— 换掉 LLM Planner 做消融；
- **插入**：在 `plan` 前插一个第三方 `deliberate` 阶段（"三思型 agent"，
  论文 2.2 节的 contemplative agent 例子）；
- **删除**：去掉 `reflect` 测试反思的贡献度——GAWorld-Bench 的消融实验
  从改代码变成改配置。

### 6.2 EnvironmentProvider —— 共享世界（对应 Environment module）

world（地图/交通）、env（天气/事件）、social（关系网络）统一到只读查询 +
受控写入的门面后面。Agent 不再直接持有 `city_map` 引用，
通过 `ctx.world` 查询——这是"环境是唯一事实源"原则的落地，
也是运行时换地图/加建筑（Adaptability）的前提。

```python
class EnvironmentProvider(ABC):
    namespace: str                       # "space" / "weather" / "relations" / ...
    def query(self, method: str, **kw): ...
    def mutate(self, method: str, **kw): ...   # 只允许经 Controller 调用
```

### 6.3 ActionProvider —— 动作注册表（对应 Action module + @AgentCall）

```python
class ActionProvider(ABC):
    def actions(self) -> list[ActionSpec]: ...

@dataclass
class ActionSpec:
    name: str                  # "move" / "send_message" / "claim_job" / ...
    agent_callable: bool       # 对应 @AgentCall 权限注解
    describe: Callable         # 生成给 LLM 的动作描述（进 prompt 的动作菜单）
    execute: Callable[[ActionRequest, SimContext], ActionResult]
```

迁移策略务实处理 GAWorld 的现实——动作目前是自由文本：
1. **第一步不改变自由文本行为**。默认注册一个 `freeform` 动作兜底，
   LLM 输出照旧走 `resolve_location` 等后处理；
2. **结构化动作逐个上岸**：move（位置系统已结构化）、real_work 的
   claim/submit（已结构化）、消费（economy 已结构化）先注册为正式动作，
   享受 Controller 校验；
3. 长期让 LLM 从动作菜单选择 + 参数化（动作描述由 `describe` 生成注入 prompt），
   freeform 退化为 fallback。

---

## 七、现有子系统 → 插件映射

| 子系统 | 插件化后使用的扩展点 | 迁移难度 |
|---|---|---|
| `policy/intervention`（推荐/曝光干预） | SystemPlugin + `perception.compose`(collect) + Recorder | 低——本来就是"造 feed → 注入感知 → 记指标"三段 |
| `behavior/dynamic`（中断/自发性） | SystemPlugin + `interrupt.candidates`(collect)，仲裁器留内核侧 | 中——引擎已模块化，需把 if 链改成征集 |
| `world/local_physical` + `spatial_preferences` | EnvironmentProvider + `perception.compose` + `interrupt.candidates` | 低 |
| `economy/finance` | SystemPlugin（day.start/end 结算）+ Controller 校验器（现金约束）+ ActionProvider（消费/借贷） | 中——逻辑自洽，接口面广 |
| `interests`（兴趣成长） | SystemPlugin + `schedule.compose` + `memory.consolidate` | 低 |
| `skills`（技能库） | SystemPlugin + `perception.compose` + `memory.consolidate`（蒸馏） | 低 |
| `work/`（real work） | SystemPlugin + ActionProvider（claim/submit）+ `action.selected` | 低——RealWorkRuntime 已是准插件形态 |
| `events/life`（人生事件） | SystemPlugin + `perception.compose` | 低 |
| `social/network` | EnvironmentProvider("relations") | 中 |
| `policy_events` | SystemPlugin + Controller.intervene("inject_event") | 低 |
| 情绪扩散 / anomaly / curiosity | 各归上述插槽 | 低 |

判据：**迁完之后，`sim/pipeline.py` 里不允许出现任何领域模块的 import**。
主循环只认识 kernel 六件套和三类插槽。

---

## 八、明确不采纳的 Agent-Kernel 设计（及理由）

按"简单优先"原则，以下设计**不做**，避免为 50~200 agent 规模引入
10,000 agent 规模的复杂度：

1. **Ray + MasPod/PodManager 分布式编排**。GAWorld 已有 relay 分布式模式且
   当前规模用不到 Ray。但插槽接口设计成无共享全局变量（一切经 SimContext），
   保证将来若要上 Ray，切面在内核而非插件。
2. **所有 agent 间消息路由过 Controller**。GAWorld 的 agent 通信量小
   （inbox 机制），全量路由只增加延迟。仅动作请求过 Controller。
3. **数据库适配器体系（Redis/PostgreSQL adapter）**。当前 sqlite + jsonl
   完全够用。采纳的是**数据所有权归插件**的原则，不是存储技术选型。
4. **Pydantic 全面建模**。StepContext/ActionSpec 用 dataclass；
   仅插件配置声明处做 schema 校验（错误信息友好即可）。
5. **运行中热替换插件**。研究场景下"重启 + 配置变更"足够；
   热替换引入的状态一致性问题不值得。运行时干预由 Controller 承担。
6. **模拟回滚（rollback to tick）**。诱人但成本极高（所有插件状态都要
   可快照）。Recorder 的统一事件流为将来实现留了路，本期不做。

---

## 九、迁移路线（与 REFACTOR_PLAN 融合）

REFACTOR_PLAN 的阶段 0~2（基线、拆巨石、迁 legacy）**照旧执行**，
本方案从其阶段 1h（pipeline 化）起接管并扩展：

> **进度（2026-07-11）**：
> ✅ K1 完成（commit `d8826a9`）——kernel 六件套 + run_simulation 接线，
> 23 个单测，全量 551 过 / 6 个既有失败与基线一致。
> ✅ K2-lite 完成（commit `da259d6`）——`perception.compose` 与
> `action.selected` 分发点 + 零侵入插件端到端测试
> （`tests/test_kernel_plugin_e2e.py`）。`plan.prompt` 需 `planning()`
> 阶段化后接入，归入完整 K2。
> ✅ K3a intervention 上岸——`gaworld/policy/plugin.py` +
> `gaworld/plugins/`（内置聚合点）+ 新增 `agents.built` 事件
> （agent 构建后、初始快照前）。env_context 覆盖 life_event_context
> 的既有行为按 bug 修正处理（改为追加语义），CHANGELOG 有记录。
> ✅ K2 完整认知管线（commit `5014d2f`）——step 体拆为 12 个命名阶段
> （StagePipeline，`gaworld/sim/pipeline.py`），顺序/替换/插入/删除
> 全部配置化；验收测试：reflect 消融零反思调用、路径插入自定义阶段。
> 与设计的偏差：StepContext 以 dict 实现（保持既有 hook 消费者兼容，
> typed wrapper 留待 hook 全量迁移后）；阶段暂为 run_simulation 内闭包
> （变量晚绑定，后续可机械地逐个毕业为模块函数）。
> ✅ 顺带修复重大潜在 bug（commit `352b2f1`）：3f7edba 起
> `step_ctx["activity"]` 种子值无条件覆盖 LLM/动态活动调整，
> RoutineChange 在主线路径失效约 5 个月；修复后 hook 覆盖仅在
> 实际改写种子值时生效。**该修复改变模拟动力学，进行中的实验需重新基线。**
> ✅ K3c skills 上岸——`gaworld/skills/plugin.py`；新增
> `perception.sections`（感知 prompt 内部段落征集，与污染环境上下文的
> `perception.compose` 区分）与 `memory.consolidate`（日终逐 agent）
> 两个事件；`_cognition.py` 不再 import skills 域。
> ✅ K3d interests 上岸——`gaworld/interests_plugin.py`；新增
> `episode.compose` 事件（episode 构建后、入库前）。成长画像生命周期
> （bootstrap/逐步进度/日终衰减演化）归插件；两处读端消费者
> （日程 prompt 上下文、位置/动作匹配）暂留内联，`growth_profile`
> 键位随之保留在 agent 顶层，待读端迁移后一并入 ext 命名空间。
> ✅ K3e life_events 上岸——`gaworld/events/plugin.py`，首个事件
> *生产者*插件；新增 `env.events.compose`（per-agent 环境事件贡献）、
> `env.events.tick`（tick 级贡献）、`state.effects`（状态增量施加）
> 三个事件。
> ✅ K3f economy 正式化——`gaworld/economy/plugin.py`；
> `integrations.py` 的 hooks 声明清空（回归纯用户扩展入口），
> 内置装配统一收敛到 `gaworld.plugins.builtin_plugins()`（现 6 个）。
> ✅ K3g local_physical 上岸——`gaworld/world/plugin.py`（tick 级地图
> 刷新 + 感知快照，priority 30 保持注入文本顺序不变）；
> spatial_preferences（P4）与 dynamic_behavior 中断结果深耦合，
> 留待与其一并迁移。
> ✅ K3h real_work 上岸——`gaworld/work/plugin.py`；新增
> `action.outcome` 过滤事件；teardown 顺手修复 worker 池泄漏。
> ✅ K3i dynamic_behavior + spatial_preferences 上岸——**K3 全部完成**。
> 新增 `interrupts.compose`（filter，思绪计算）、`location.resolve`
> （filter，位置重定向）、`interrupt.applied`（observe）三个事件；
> dyn_result 应用逻辑留 adjust 阶段作为中断生产者与管线间的通用契约。
> 9 个内置插件全部上岸，主循环只剩管线骨架、legacy 自发性回退和
> 通用契约应用。
> ✅ K4 校验门上岸——move 阶段接入 `Controller.validate`，deny 审计
> 落盘并在下一 tick 感知回注；`location_exists`（默认开，常态零触发）
> 与 `venue_open`（默认关，opt-in——硬拦会改动力学）两个校验器由
> LocalPhysicalPlugin 注册；经济可负担校验器待具体规则定义后再做。
> ActionProvider 动作菜单（LLM 从注册动作中选择）留作后续方向。
> ✅ K5 干预 API 落地——**K1–K5 迁移全部完成（2026-07-12）**。
> 标准干预（set_agent_state / update_config / remove_agent）随内核
> 装配，inject_life_event 由 LifeEventsPlugin 注册；运行时移除 agent
> 在日边界生效（Adaptability 达成）。
> 跟进项（不阻塞架构目标）：① `add_agent` 运行时造人（需种子摄取
> 路径设计）；② dashboard 进程的 HTTP 桥接到干预 API；③ 经济可负担
> 校验器（待具体移动前成本规则）；④ `agent["growth_profile"]` 等
> 读端迁移后收入 ext 命名空间；⑤ ActionProvider 动作菜单
> （LLM 从注册动作选择，freeform 退化为 fallback）。

### 阶段 K1：内核骨架（不改行为）
- 新建 `gaworld/kernel/`：SimContext、Clock、EventBus（含 HookBus 兼容层）、
  PluginRegistry、Recorder；Controller 先只有 observe 型骨架。
- `run_simulation` 改为构造 SimContext 并把现有 hook_bus 换成 EventBus。
- **验收**：全量测试过；`--days 1` 输出与基线一致；旧 `extensions.hooks`
  配置的扩展仍工作（现有 `test_extension_hooks_resolve` 通过）。

### 阶段 K2：认知管线插槽
- `run_simulation` 内层循环拆为 CognitionStage 序列 + StepContext
  （即 REFACTOR_PLAN 1h，但按本方案接口做）。
- 默认管线行为与现状 byte-equal。
- **验收**：配置里把 `reflect` 阶段去掉能跑通且只影响反思相关输出；
  注册一个 no-op 自定义阶段的集成测试。

### 阶段 K3：首批插件上岸（每个一次 commit）
按第七节难度从低到高：intervention → skills → interests → life_events →
local_physical → real_work → dynamic_behavior → economy。
- 每个插件迁移 = 实现 Plugin 类 + 把内联调用改为事件订阅 +
  per-agent 状态挪进 `agent["ext"][id]`（带旧键兼容读取）。
- **验收**：该插件 `enabled=False` 时主循环无任何该模块 import 被触发；
  开关前后对比测试。

### 阶段 K4：动作注册表 + Controller 校验
- ActionProvider + `freeform` 兜底；move / real_work / 消费三个结构化动作上岸；
  位置存在性、营业时间、现金约束三个校验器。
- **验收**：注入一个"去不存在地点"的动作，得到 deny + 感知回注的端到端测试。

### 阶段 K5：干预 API + 文档
- Controller.intervene 收编 dashboard 写路径；运行时 add/remove agent。
- 撰写 `docs/PLUGIN_AUTHORING.md`（插件作者指南）+ 一个最小示例插件
  （建议：`examples/plugins/rumor_mill/`，用 collect 钩子做谣言注入——
  正好服务 EXP-INFO-001 实验）。
- **验收**：示例插件不改 gaworld 源码、仅靠 pip 安装 + 配置声明即可运行。

每阶段独立可交付、可回滚；K3 各插件之间也互相独立，可按需调序。

---

## 十、风险与开放问题

| 风险 | 缓解 |
|---|---|
| EventBus collect/filter 让执行序影响结果，破坏可复现性 | priority 显式化 + 同优先级按注册序 + Recorder 记录钩子执行序 |
| 插件间隐式依赖（如 interests 读 economy 状态） | `requires` 声明 + 只允许经 `ctx.plugin_state(other_id)` 只读访问，禁止直接 import 对方内部 |
| `agent["ext"]` 迁移期新旧双键漂移 | 每插件迁移时一次性写迁移函数，旧键只读不写，一个版本后删 |
| 性能：事件分发比直接调用慢 | 钩子按事件预索引（现 HookBus 已如此）；热路径（perception.compose）实测退化 >3% 再优化 |
| 与 REFACTOR_PLAN 并行推进的冲突 | 明确顺序：先完成其阶段 1a–1g / 2，K1 再动 `run_simulation` |

开放问题（已于 2026-07-11 由项目 owner 裁定）：
1. 内核目录：**采用 `gaworld/kernel/`**，不并入 `gaworld/core/`。
2. 插件开关消融：**不纳入** GAWorld-Bench 正式 track。
3. 第三方插件：entry_points 自动加载，**不需要 allowlist**
   （加载失败仅告警不中断，与 HookBus 的信任边界策略一致）。
