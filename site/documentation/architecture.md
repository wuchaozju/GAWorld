# 架构与可扩展性

GAWorld 使用微内核组织时间、事件、插件、动作校验和记录。具体的社会、经济、家庭、技能和工作逻辑由相应模块实现。

## 执行模型

`generative_city_sim.py` 提供运行入口；`gaworld/sim/` 实现认知管线；`gaworld/core/` 组织居民与执行。日常行动和长时段快进按所选时间尺度推进。

```text
CLI / Dashboard / Python client
                 │
          仿真入口与运行配置
                 │
      SimContext + 认知管线
        │        │        │
     居民状态   插件系统   环境与地图
        └────────┼────────┘
             记录与输出
```

## SimContext

`SimContext` 是插件访问运行服务的入口，包括配置、时钟、居民、事件总线、控制器、记录器、注册表、模型调用与随机数生成器。插件通过它获取当前运行上下文。

## 内核服务

| 服务 | 作用 |
| --- | --- |
| `Clock` | 推进并读取仿真时间 |
| `EventBus` | 分发 observe、collect、filter 钩子 |
| `PluginRegistry` | 注册插件、解析依赖、执行生命周期 |
| `Controller` | 校验动作，分发运行时干预 |
| `Recorder` | 写入带仿真时间的结构化事件 |
| `SimContext` | 汇集运行服务和插件状态 |

## 认知管线

```text
prepare → perceive → interrupts → plan → adjust_activity → move
→ select_action → reflect → update_state → broadcast → memorize → record
```

`CONFIG["pipeline"]["agent_step"]` 声明阶段顺序。自定义阶段使用 `fn(agent, step, ctx)` 签名；`step` 在阶段之间传递本步数据。实验中可以替换或消融中间阶段，并记录相应配置。

## 模型调用

模型提供商实现在 `gaworld/llm/`，配置在 `gaworld/settings/llm.py`。控制台管理服务商后端与账号密钥，运行配置选择默认模型和日程模型。

## 状态与记录

插件通过 `ctx.agent_ext(agent, plugin_id)` 保存居民扩展状态，通过 `ctx.plugin_state(plugin_id)` 保存模拟级状态。结构化记录通过 `ctx.recorder.record()` 写入 JSONL。

## 扩展点

- 在 `gaworld/` 子包中实现新的运行逻辑。
- 通过 `Plugin` 注册生命周期处理器、感知贡献、动作过滤器和干预。
- 通过配置或 Python entry point 装配插件。
- 通过 HTTP API 和 Python 客户端连接外部程序。

完整插件示例见 [自定义模块](custom_modules.md)，类型与方法见 [API 参考](api/index.md)。
