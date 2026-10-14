# 配置模块

运行配置构建、覆盖合并、模型路由与提供商。

接口签名与说明由当前仓库源代码生成。

## gaworld.settings

:::{py:currentmodule} gaworld.settings
:::

:::{py:function} build_config() -> dict[str, Any]

```{eval-rst}
Build the active legacy CONFIG dict with runtime overrides applied.
```

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/settings/__init__.py#L11`

:::

## gaworld.settings.defaults

:::{py:currentmodule} gaworld.settings.defaults
:::

:::{py:function} build_default_config() -> dict[str, Any]

```{eval-rst}
Build a fresh default config dict from focused fragments.
```

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/settings/defaults.py#L19`

:::

## gaworld.settings.overrides

:::{py:currentmodule} gaworld.settings.overrides
:::

:::{py:function} deep_update(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/settings/overrides.py#L14`

:::

:::{py:function} load_env_override() -> dict[str, Any]

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/settings/overrides.py#L25`

:::

:::{py:function} apply_runtime_overrides(config: dict[str, Any]) -> dict[str, Any]

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/settings/overrides.py#L84`

:::

## gaworld.llm.providers

:::{py:currentmodule} gaworld.llm.providers
:::

:::{py:function} build_provider(cfg: dict[str, Any], *, attempts: int=3)

```{eval-rst}
Instantiate one backend from its ``llm.providers`` block, or ``None``.

Factored out of :meth:`LLMRouter._init_providers` so the 配置 panel's
connectivity check builds the *same* object the simulator will use. A probe
that talked to the endpoint through its own hand-rolled request would go on
passing after the router's construction drifted — which is precisely the
failure a "测试连通性" button is supposed to catch.

``attempts`` is threaded through so the probe can ask for a single shot:
the router's three-with-backoff turns an unreachable endpoint into a
minute of silence in a UI that promised an answer.
```

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/llm/providers.py#L683`

:::

:::{py:function} probe_provider(cfg: dict[str, Any], *, timeout: int=30) -> dict[str, Any]

```{eval-rst}
One real generation against ``cfg``. Never raises — the verdict is data.

Deliberately a *real* call rather than a socket/HTTP-200 check: the ways an
LLM backend is "reachable but useless" (model name not pulled, key rejected,
reasoning budget consumed before any text) all return a healthy connection
and would pass any cheaper test.

``timeout`` caps the configured one rather than replacing it, so a provider
deliberately set to 10s is not probed for 30.
```

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/llm/providers.py#L751`

:::

:::{py:class} LLMRouter(config)

```{eval-rst}
Lightweight router for selecting providers by task or agent.
```

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/llm/providers.py#L818`

:::

:::{py:method} LLMRouter.call(prompt, task=None, agent_id=None, provider=None, system=None, temperature=None, allow_fallback=True, images=None, max_tokens=None)

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/llm/providers.py#L880`

:::

:::{py:function} available_providers()

```{eval-rst}
Configured provider names with their type and model, for UI pickers.
```

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/llm/providers.py#L997`

:::

:::{py:function} resolve_provider(task=None, agent_id=None, provider=None) -> str

```{eval-rst}
Name of the provider a call with these arguments would hit first.

Lets a caller record *which model actually answered* alongside the
answer, so model provenance survives into the artifact.
```

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/llm/providers.py#L1016`

:::

:::{py:function} call_llm(prompt, task=None, agent_id=None, provider=None, system=None, temperature=None, allow_fallback=True, images=None, max_tokens=None)

```{eval-rst}
Public helper for model calls used across the simulator.

Each invocation:

* runs through retry / backoff for transient errors,
* is logged with provider, task, agent, prompt size, and latency,
* raises the original :class:`requests` exception on hard failure.

``system`` and ``temperature`` are per-call overrides. Both default to
``None`` = "use the provider's configured behaviour", so existing
callsites are unaffected. They exist for prompt-design experiments,
where the system message *is* the treatment and the sampling
temperature is part of the protocol rather than a deployment setting.

``allow_fallback=False`` pins the call to a single model: an
experiment would rather lose a cell than have it answered by a
different model than its neighbours.

``images`` is a list of ``{"media_type": ..., "data": "<base64>"}``
entries, forwarded only when non-empty so provider-shaped test doubles
whose ``call`` takes the prompt alone keep working. Check
:func:`provider_supports_images` first — this function does not.

``max_tokens`` raises (or lowers) the output cap for one call. The
configured default suits this simulator's usual turn — one event, one
decision, a short profile — so a caller that needs a whole structured
document has to say so, or the provider truncates it mid-JSON and every
parser downstream sees malformed input rather than a budget problem.
```

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/llm/providers.py#L1038`

:::
