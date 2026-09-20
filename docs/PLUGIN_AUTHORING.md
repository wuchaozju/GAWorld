# GAWorld 插件作者指南

> 适用于 K1/K2-lite 之后的内核（`gaworld/kernel/`）。
> 架构背景见 `docs/proposals/2026-07-11-microkernel-plugin-architecture.md`。

一个插件可以在**不改任何 GAWorld 源码**的前提下：订阅模拟生命周期、向 agent
的感知注入内容、改写被选中的动作、注册动作校验器与运行时干预、拥有自己的
per-agent 状态和输出目录。

## 最小插件

```python
# my_pkg/rumor.py
from gaworld.kernel import Plugin


class RumorPlugin(Plugin):
    id = "rumor"                 # 唯一标识 = 配置/存储/agent 状态命名空间
    requires = ()                # 依赖的其他插件 id（决定 setup 顺序）

    def setup(self, ctx):
        # ctx 是 SimContext：config / clock / agents / bus / controller /
        # recorder / registry / llm / rng
        ctx.bus.on("on_day_start", self.on_day_start)
        ctx.bus.on("perception.compose", self.inject_rumor)

    def teardown(self, ctx):
        pass

    def on_day_start(self, hook_ctx):          # observe：返回值被忽略
        pass

    def inject_rumor(self, hook_ctx):          # collect：返回 0..n 条贡献
        agent = hook_ctx["agent"]
        ctx = hook_ctx["sim"]                  # 每次分发都携带 SimContext
        state = ctx.agent_ext(agent, self.id)  # 本插件的 per-agent 命名空间
        if state.get("heard_rumor"):
            return ["有人跟你提起：城东要修新地铁线（真实性存疑）"]
        return None
```

## 装配方式（三选一，可叠加）

1. **配置声明**（无需安装包，路径可导入即可）：

   ```python
   CONFIG["plugins"] = [
       {"class": "my_pkg.rumor:RumorPlugin", "enabled": True},
   ]
   ```

2. **entry points**（`pip install` 后自动装配，无 allowlist）：

   ```toml
   # 你的包的 pyproject.toml
   [project.entry-points."gaworld.plugins"]
   rumor = "my_pkg.rumor:RumorPlugin"
   ```

3. **代码注册**（测试/脚本场景）：`ctx.registry.register(RumorPlugin())`。

装配失败（导入错误、非 Plugin 子类、`setup` 抛异常、依赖缺失）只会
`logger.warning` 并停用该插件，不会中断模拟——内核把插件当作信任边界。

## 三种钩子语义

| 语义 | 注册后签名 | 返回值 | 用途 |
|---|---|---|---|
| observe | `fn(ctx_dict)` | 忽略 | 旁观生命周期（统计、落盘、外部同步） |
| collect | `fn(ctx_dict)` | `None` / 单项 / 列表，内核合并 | 感知注入、候选征集 |
| filter | `fn(value, ctx_dict)` | 新值；`None` 表示保持原值 | 改写流经的数据 |

同一事件的处理器按 `priority` 降序执行（`ctx.bus.on(event, fn, priority=10)`），
同优先级按注册顺序。每个 `ctx_dict` 都含 `sim`（SimContext）。

## 当前可用事件

| 事件 | 语义 | 上下文关键键 |
|---|---|---|
| `agents.built` | observe | `agents` `config`（agent 构建后、初始快照前——做 per-agent 状态播种用这里） |
| `on_simulation_start` / `on_simulation_end` | observe | `config` `agents` `agents_by_id` `city_map` |
| `on_day_start` / `on_day_end` | observe | `day` + 同上 |
| `on_time_tick` | observe | `day` `time_str` |
| `on_agent_pre_step` / `on_agent_post_step` | observe | `agent` `day` `time_str` `step`（post_step 的 `step` 含 `action`/`outcome`/`reflection` 等全步数据） |
| `perception.compose` | **collect** | `agent` `day` `time_str` `scheduled_activity` `env_context` `social_context` `env_events` `policy` `policy_desc` `news`（贡献并入环境上下文，会出现在 Env 日志行） |
| `perception.sections` | **collect** | `agent` `day` `time_str` `scheduled_activity` `social_context`（贡献渲染在感知 prompt 内部的专属段落，不污染环境上下文——技能块用这里） |
| `action.selected` | **filter**（value=动作字符串） | `agent` `activity` `day` `time_str` `location` |
| `memory.consolidate` | observe | `agent` `day`（日终逐 agent 发射，插件自管节奏门控——技能蒸馏用这里） |
| `episode.compose` | observe（可改写 episode） | `agent` `episode` `step_minutes` `day` `time_str`（episode 构建后、入库前；interests 插件在此填充成长键） |
| `env.events.compose` | **collect** | `agent` `day` `time_str` `step` `daily_logs`（事件生产者在此贡献 per-agent 环境事件，与当日/当 tick 环境流合并——life_events 插件用这里） |
| `env.events.tick` | **collect** | `day` `time_str`（tick 级环境事件贡献，供可视化帧合并等 tick 级消费者） |
| `state.effects` | observe | `agent` `step` `day` `time_str`（update_state 阶段内、社会影响之前——插件在此施加自己的状态增量） |

内置参考实现：`gaworld/policy/plugin.py`（InterventionPlugin，K3a 迁移的
第一个内置子系统——感知注入 + post_step 指标落盘 + agents.built 播种，
三种钩子用法齐全）。

## 认知管线（K2）：替换 / 插入 / 消融阶段

agent 每步认知是 12 个命名阶段的序列（`gaworld/sim/pipeline.py`）：

```
prepare → perceive → interrupts → plan → adjust_activity → move →
select_action → reflect → update_state → broadcast → memorize → record
```

顺序由配置声明，缺省即以上全序：

```python
CONFIG["pipeline"]["agent_step"] = [
    "prepare", "perceive",
    "my_pkg.stages:deliberate",          # 插入自定义阶段（三思型 agent）
    "interrupts", "plan", "adjust_activity", "move",
    "select_action",                      # "reflect" 被省略 = 消融反思
    "update_state", "broadcast", "memorize", "record",
]
```

自定义阶段签名 `fn(agent, step, ctx)`：`step` 是本步数据总线（dict——
hook 可见键沿用旧名，阶段间工作键以下划线开头，如 `_perception` /
`_plan_text` / `_act`），`ctx` 是 SimContext。阶段错误**会传播**
（阶段是控制流本体，不同于 observer 的信任边界）。

注意：`prepare`（pre-step 钩子在此发射）与 `record`（日志/最终
step 键在此写入）是结构性阶段，消融目标应是中间的认知阶段。
消融后下游阶段以默认值容错（如去掉 `reflect` 后 `reflection` 为空串）。
参考测试：`tests/test_pipeline_ablation.py`。

后续 K 阶段将新增 `interrupt.candidates`、`schedule.compose`、`plan.prompt`
等事件（见设计文档第 5.7 节事件目录）。

## 状态与数据所有权

- **per-agent 状态**：`ctx.agent_ext(agent, self.id)` → `agent["ext"]["<id>"]`
  下的 dict，随 agent 生命周期存在。不要往 agent dict 顶层塞裸键。
- **模拟级共享状态**：`ctx.plugin_state(self.id)`。其他插件可用同一调用只读
  访问，但禁止 import 你的内部模块（用 `requires` 声明依赖）。
- **输出文件**：`self.output_dir(ctx)` → `output/<id>/`，格式自定
  （Database-per-Plugin）。
- **统一事件流**：`ctx.recorder.record("<id>.<table>", {...})` →
  `output/records/<id>.<table>.jsonl`，自动附带 `_day`/`_time`，用于跨插件
  时间线对齐与审计。

## 动作校验与运行时干预（Controller）

```python
from gaworld.kernel import Verdict

def setup(self, ctx):
    ctx.controller.register_validator(self.check_curfew, priority=5)
    ctx.controller.register_intervention("rumor.plant", self.plant)

def check_curfew(self, request, ctx):
    # request: ActionRequest(agent_id, name, params, raw_text)
    if request.name == "move" and ctx.clock.time_str >= "23:00":
        return Verdict.deny("宵禁时段不能外出")
    return None            # None = 无意见，交给下一个校验器

def plant(self, ctx, agent_id=None, text=""):
    ctx.agent_ext(ctx.agents_by_id[agent_id], self.id)["heard_rumor"] = text
```

`deny` 会写入 `output/records/action.denied.jsonl`，且理由会在该 agent
**下一 tick 的感知**中以"刚才的行动受阻：…"出现（K4 起 move 动作已过
校验链；内置校验器：`location_exists` 默认开、`venue_open` 默认关，
经 `CONFIG["controller"]["validators"]` 调整）。每次 `intervene` 调用
都自动审计到 `controller.intervention` 表。

**开箱即用的标准干预**（K5，`gaworld/kernel/interventions.py`）：

| 名称 | 参数 | 语义 |
|---|---|---|
| `set_agent_state` | `agent_id` `key` `value` | 立即写入 agent 状态变量 |
| `update_config` | `path`（点号路径）`value` | 立即写入运行中 CONFIG |
| `remove_agent` | `agent_id` | 排队，下个日边界生效（含社交邻居清洗） |
| `inject_life_event` | `event` dict 或散参 | 入队人生事件（LifeEventsPlugin 注册） |

`add_agent`（运行时造人）尚未实现——需要种子摄取路径设计，见提案跟进项。

## 可运行的参考实现

`tests/test_kernel_plugin_e2e.py::ProbePlugin` 是一个被 CI 持续验证的完整
示例：经 `CONFIG["plugins"]` 装配、感知注入到达 LLM prompt、动作过滤器
观察每个被选动作。写新插件时从它抄起最快。
