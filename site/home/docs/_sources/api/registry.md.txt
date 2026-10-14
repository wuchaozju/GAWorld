# Registry 模块

插件定义、注册、依赖装配与生命周期。

接口签名与说明由当前仓库源代码生成。

## gaworld.kernel.registry

:::{py:currentmodule} gaworld.kernel.registry
:::

:::{py:class} Plugin

```{eval-rst}
Base class for GAWorld plugins.

Subclasses must set ``id`` (unique; doubles as the config, storage and
``agent_ext`` namespace) and may set ``requires`` to declare dependencies
on other plugin ids (setup runs in dependency order).
```

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/kernel/registry.py#L34`

:::

:::{py:attribute} Plugin.id
:type: str
:::

:::{py:attribute} Plugin.requires
:type: tuple[str, ...]
:::

:::{py:method} Plugin.setup(ctx: 'SimContext') -> None

```{eval-rst}
Register hooks / validators / stages / actions. Called once.
```

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/kernel/registry.py#L45`

:::

:::{py:method} Plugin.teardown(ctx: 'SimContext') -> None

```{eval-rst}
Release resources. Called once at simulation end, reverse order.
```

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/kernel/registry.py#L48`

:::

:::{py:method} Plugin.output_dir(ctx: 'SimContext') -> Path

```{eval-rst}
This plugin's owned output namespace (Database-per-Plugin).
```

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/kernel/registry.py#L51`

:::

:::{py:class} PluginRegistry()

```{eval-rst}
Collects, orders and drives plugin lifecycles.
```

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/kernel/registry.py#L57`

:::

:::{py:method} PluginRegistry.register(plugin: Plugin) -> bool

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/kernel/registry.py#L66`

:::

:::{py:method} PluginRegistry.load_config_plugins(specs) -> None

```{eval-rst}
Load ``CONFIG["plugins"]`` declarations.
```

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/kernel/registry.py#L77`

:::

:::{py:method} PluginRegistry.load_entry_points(group: str=ENTRY_POINT_GROUP) -> None

```{eval-rst}
Auto-load installed third-party plugins (no allowlist).
```

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/kernel/registry.py#L91`

:::

:::{py:method} PluginRegistry.setup_all(ctx: 'SimContext') -> list[str]

```{eval-rst}
Set up plugins in dependency order; return active plugin ids.

A plugin whose dependency is missing, or whose ``setup`` raises, is
deactivated with a warning (trust-boundary policy, same as the bus).
```

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/kernel/registry.py#L130`

:::

:::{py:method} PluginRegistry.teardown_all(ctx: 'SimContext') -> None

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/kernel/registry.py#L153`

:::

:::{py:method} PluginRegistry.get(plugin_id: str) -> Plugin | None

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/kernel/registry.py#L163`

:::

:::{py:method} PluginRegistry.ids() -> list[str]

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/kernel/registry.py#L166`

:::

:::{py:method} PluginRegistry.active_ids() -> list[str]

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/kernel/registry.py#L169`

:::
