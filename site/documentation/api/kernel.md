# 仿真内核

运行上下文、仿真时钟、事件总线与动作控制器。

接口签名与说明由当前仓库源代码生成。

## gaworld.kernel.context

:::{py:currentmodule} gaworld.kernel.context
:::

:::{py:class} SimContext

```{eval-rst}
Everything a plugin may legitimately touch at runtime.
```

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/kernel/context.py#L23`

:::

:::{py:attribute} SimContext.config
:type: dict
:::

:::{py:attribute} SimContext.clock
:type: Clock
:::

:::{py:attribute} SimContext.bus
:type: EventBus
:::

:::{py:attribute} SimContext.registry
:type: PluginRegistry
:::

:::{py:attribute} SimContext.controller
:type: Controller
:::

:::{py:attribute} SimContext.recorder
:type: Recorder
:::

:::{py:attribute} SimContext.agents
:type: list
:::

:::{py:attribute} SimContext.agents_by_id
:type: dict
:::

:::{py:attribute} SimContext.llm
:type: Callable | None
:::

:::{py:attribute} SimContext.rng
:type: random.Random
:::

:::{py:attribute} SimContext.extras
:type: dict
:::

:::{py:method} SimContext.plugin_state(plugin_id: str) -> dict

```{eval-rst}
Shared (simulation-level) mutable state owned by one plugin.

Other plugins may read it via the same call, but must not import the
owning plugin's internals.
```

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/kernel/context.py#L40`

:::

:::{py:method} SimContext.agent_ext(agent, plugin_id: str) -> dict

```{eval-rst}
Per-agent state namespace owned by one plugin.

Replaces sprinkling bare keys on the agent dict: all plugin state
lives under ``agent["ext"][plugin_id]``.
```

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/kernel/context.py#L48`

:::

:::{py:method} SimContext.set_agents(agents: list) -> None

```{eval-rst}
Refresh the live agent list (supports runtime add/remove).
```

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/kernel/context.py#L56`

:::

:::{py:function} build_kernel(config: dict, *, llm: Callable | None=None, load_entry_points: bool=True) -> SimContext

```{eval-rst}
Assemble the six kernel services from CONFIG.

Behavior-compatible with the legacy bootstrap: the EventBus loads the
same ``CONFIG["extensions"]`` hook declarations HookBus did, and plugin
sources (``CONFIG["plugins"]`` + entry points) default to empty/no-op
until plugins land in K3.
```

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/kernel/context.py#L62`

:::

## gaworld.kernel.clock

:::{py:currentmodule} gaworld.kernel.clock
:::

:::{py:class} Clock

```{eval-rst}
Current simulation time. Advanced exclusively by the main loop.
```

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/kernel/clock.py#L14`

:::

:::{py:attribute} Clock.day
:type: int
:::

:::{py:attribute} Clock.time_str
:type: str
:::

:::{py:attribute} Clock.tick_index
:type: int
:::

:::{py:attribute} Clock.minutes_per_tick
:type: int | None
:::

:::{py:method} Clock.start_day(day: int) -> None

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/kernel/clock.py#L22`

:::

:::{py:method} Clock.advance(time_str: str, tick_index: int) -> None

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/kernel/clock.py#L27`

:::

:::{py:method} Clock.snapshot() -> dict

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/kernel/clock.py#L31`

:::

## gaworld.kernel.bus

:::{py:currentmodule} gaworld.kernel.bus
:::

:::{py:class} EventBus(config: dict | None=None)

```{eval-rst}
Priority-ordered hook dispatcher with observe/collect/filter semantics.
```

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/kernel/bus.py#L30`

:::

:::{py:method} EventBus.on(event: str, fn: Callable, *, priority: int=0, critical: bool=False) -> None

```{eval-rst}
Register an observer, or a critical state-changing participant.

Critical handlers propagate their original errors immediately. This
is for participants whose failure makes continued execution invalid;
ordinary third-party observers retain the warning-only boundary.
```

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/kernel/bus.py#L55`

:::

:::{py:method} EventBus.emit(event: str, **context) -> list[str]

```{eval-rst}
Observe semantics: notify handlers, ignore return values.
```

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/kernel/bus.py#L90`

:::

:::{py:method} EventBus.collect(event: str, **context) -> list[Any]

```{eval-rst}
Contribute semantics: merge every handler's contribution(s).
```

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/kernel/bus.py#L104`

:::

:::{py:method} EventBus.filter(event: str, value: Any, **context) -> Any

```{eval-rst}
Pipeline semantics: value flows through handlers, each may rewrite.

Handlers have signature ``fn(value, context_dict)``. Returning ``None``
keeps the previous value.
```

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/kernel/bus.py#L126`

:::

## gaworld.kernel.controller

:::{py:currentmodule} gaworld.kernel.controller
:::

:::{py:class} ActionRequest

```{eval-rst}
A structured action an agent wants to execute.
```

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/kernel/controller.py#L31`

:::

:::{py:attribute} ActionRequest.agent_id
:type: Any
:::

:::{py:attribute} ActionRequest.name
:type: str
:::

:::{py:attribute} ActionRequest.params
:type: dict
:::

:::{py:attribute} ActionRequest.raw_text
:type: str
:::

:::{py:class} Verdict

```{eval-rst}
Outcome of validation: allow, deny(reason), or rewrite(request).
```

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/kernel/controller.py#L41`

:::

:::{py:attribute} Verdict.allowed
:type: bool
:::

:::{py:attribute} Verdict.reason
:type: str
:::

:::{py:attribute} Verdict.rewritten
:type: ActionRequest | None
:::

:::{py:method} Verdict.allow() -> 'Verdict'

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/kernel/controller.py#L49`

:::

:::{py:method} Verdict.deny(reason: str) -> 'Verdict'

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/kernel/controller.py#L53`

:::

:::{py:method} Verdict.rewrite(request: ActionRequest) -> 'Verdict'

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/kernel/controller.py#L57`

:::

:::{py:class} Controller()

```{eval-rst}
Stateless validation + intervention hub.
```

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/kernel/controller.py#L61`

:::

:::{py:method} Controller.register_validator(fn: Callable, *, priority: int=0) -> None

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/kernel/controller.py#L72`

:::

:::{py:method} Controller.validate(request: ActionRequest, ctx: 'SimContext') -> Verdict

```{eval-rst}
Run the validator chain; first deny wins, rewrites flow through.
```

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/kernel/controller.py#L78`

:::

:::{py:method} Controller.register_intervention(name: str, fn: Callable) -> None

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/kernel/controller.py#L110`

:::

:::{py:method} Controller.intervention_names() -> list[str]

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/kernel/controller.py#L114`

:::

:::{py:method} Controller.intervene(name: str, ctx: 'SimContext', **kwargs) -> Any

```{eval-rst}
Execute a named intervention; every call is recorded for audit.
```

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/kernel/controller.py#L117`

:::
