# 居民数据

居民数据视图、属性访问与字典转换。

接口签名与说明由当前仓库源代码生成。

## gaworld.core.agent

:::{py:currentmodule} gaworld.core.agent
:::

:::{py:class} Agent

```{eval-rst}
Mutable view of an agent record.

:ivar data: Backing ``dict`` that owns the actual key/value store; sharing
            this dict with legacy code keeps the simulator working without
            copying state on every step.

```

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/core/agent.py#L28`

:::

:::{py:attribute} Agent.data
:type: dict[str, Any]
:::

:::{py:property} Agent.id
:type: int | None

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/core/agent.py#L45`

:::

:::{py:property} Agent.name
:type: str

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/core/agent.py#L53`

:::

:::{py:property} Agent.state
:type: dict[str, float]

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/core/agent.py#L57`

:::

:::{py:property} Agent.memory
:type: list[dict[str, Any]]

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/core/agent.py#L62`

:::

:::{py:property} Agent.schedule
:type: list[dict[str, Any]]

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/core/agent.py#L67`

:::

:::{py:property} Agent.location
:type: str | None

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/core/agent.py#L72`

:::

:::{py:property} Agent.skill_ids
:type: list[str]

```{eval-rst}
IDs of global Skills attached to this agent.

Private (agent-summarised) skills live on disk under the
agent's memory directory and are discovered by the
:class:`gaworld.skills.registry.SkillRegistry`; only attached
*global* skills need to be tracked here.
```

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/core/agent.py#L77`

:::

:::{py:method} Agent.need(key: str, default: float=0.0) -> float

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/core/agent.py#L88`

:::

:::{py:method} Agent.get(key: str, default: Any=None) -> Any

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/core/agent.py#L115`

:::

:::{py:method} Agent.setdefault(key: str, default: Any) -> Any

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/core/agent.py#L118`

:::

:::{py:method} Agent.update(other: Mapping[str, Any] | None=None, **kwargs: Any) -> None

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/core/agent.py#L121`

:::

:::{py:method} Agent.to_dict() -> dict[str, Any]

```{eval-rst}
Return the underlying dict (no copy).
```

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/core/agent.py#L130`

:::

:::{py:method} Agent.from_dict(payload: Mapping[str, Any]) -> 'Agent'
:classmethod:

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/core/agent.py#L135`

:::

:::{py:function} view_as_agent(payload: Mapping[str, Any] | 'Agent') -> Agent

```{eval-rst}
Return an :class:`Agent` view over ``payload`` without copying.

Useful when consuming a legacy ``dict`` agent in a function that
wants the typed surface.
```

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/core/agent.py#L141`

:::

:::{py:function} ensure_agent_dict(payload: Mapping[str, Any] | Agent) -> dict[str, Any]

```{eval-rst}
Return the backing dict for legacy ``dict``-typed callsites.
```

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/core/agent.py#L154`

:::
