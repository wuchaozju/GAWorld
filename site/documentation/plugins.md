# 编写插件

GAWorld 通过插件接入新的仿真机制。插件可以订阅生命周期、添加感知信息、过滤动作、处理干预，并保存自己的状态与记录。

## 目录结构

为扩展建立可导入的 Python 包，例如：

```text
my_pkg/
├── __init__.py
└── observation.py
```

## 创建插件

```python
from gaworld.kernel import Plugin


class ObservationPlugin(Plugin):
    id = "observation"
    requires = ()

    def setup(self, ctx):
        ctx.bus.on("on_day_start", self.on_day_start)

    def on_day_start(self, hook_ctx):
        ctx = hook_ctx["sim"]
        ctx.recorder.record("observation.day", {"day": hook_ctx["day"]})
```

`id` 标识插件，也用于状态和存储命名空间。`requires` 声明依赖的插件 ID。

## 注册插件

在运行配置中声明可导入的类：

```python
from gaworld.settings import CONFIG

CONFIG["plugins"] = [
    {"class": "my_pkg.observation:ObservationPlugin", "enabled": True},
]
```

发布独立扩展包时，可以通过 entry point 注册：

```toml
[project.entry-points."gaworld.plugins"]
observation = "my_pkg.observation:ObservationPlugin"
```

## 钩子类型

| 类型 | 处理器 | 返回值 |
| --- | --- | --- |
| observe | `fn(ctx_dict)` | 用于观察生命周期，返回值忽略 |
| collect | `fn(ctx_dict)` | 返回一项或多项贡献，由内核合并 |
| filter | `fn(value, ctx_dict)` | 返回修改后的值；`None` 保持原值 |

处理器按优先级降序执行，同优先级按注册顺序执行。上下文中通过 `sim` 访问 `SimContext`。

## 添加感知内容

```python
def setup(self, ctx):
    ctx.bus.on("perception.compose", self.context_message)


def context_message(self, hook_ctx):
    return ["社区服务中心今天开放意见征集。"]
```

将这些方法放入插件类中。返回内容会参与当前居民的环境感知。

## 管理状态与输出

- `ctx.agent_ext(agent, self.id)`：居民在本插件中的扩展状态。
- `ctx.plugin_state(self.id)`：模拟级共享状态。
- `self.output_dir(ctx)`：插件输出目录。
- `ctx.recorder.record("observation.event", payload)`：带仿真时间的结构化事件。

## 扩展认知管线

自定义阶段使用 `fn(agent, step, ctx)`，并在 `CONFIG["pipeline"]["agent_step"]` 中声明导入路径。阶段之间通过 `step` 传递数据。调整顺序或消融阶段时，检查下游使用的数据并添加相关测试。

## 测试

可参考仓库中的 `tests/test_kernel_plugin_e2e.py`，验证装配、事件分发与实际运行中的行为。新机制先在固定种子的短运行中检查，再扩大居民数量和时间范围。

## 参考

[插件注册](api/registry.md) · [仿真内核](api/kernel.md)
