# 环境模块

环境状态、事件查询与远程环境访问。

接口签名与说明由当前仓库源代码生成。

## gaworld.env.system

:::{py:currentmodule} gaworld.env.system
:::

:::{py:class} EnvironmentSystem(config, llm_fn=None)

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/env/system.py#L28`

:::

:::{py:method} EnvironmentSystem.start_day(day, day_context=None, agents=None, span=None)

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/env/system.py#L602`

:::

:::{py:method} EnvironmentSystem.tick(day, time_str, agents=None)

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/env/system.py#L638`

:::

:::{py:method} EnvironmentSystem.get_events()

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/env/system.py#L651`

:::

:::{py:method} EnvironmentSystem.get_day_events()

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/env/system.py#L654`

:::

:::{py:method} EnvironmentSystem.get_day_context_text()

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/env/system.py#L657`

:::

:::{py:method} EnvironmentSystem.export_runtime_state()

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/env/system.py#L660`

:::

:::{py:method} EnvironmentSystem.import_runtime_state(state)

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/env/system.py#L667`

:::

:::{py:method} EnvironmentSystem.get_context_text()

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/env/system.py#L681`

:::

:::{py:class} RemoteEnvironmentClient(config)

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/env/system.py#L689`

:::

:::{py:method} RemoteEnvironmentClient.start_day(day, day_context=None, agents=None, span=None)

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/env/system.py#L712`

:::

:::{py:method} RemoteEnvironmentClient.tick(day, time_str, agents=None)

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/env/system.py#L734`

:::

:::{py:method} RemoteEnvironmentClient.get_events()

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/env/system.py#L750`

:::

:::{py:method} RemoteEnvironmentClient.get_day_events()

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/env/system.py#L753`

:::

:::{py:method} RemoteEnvironmentClient.get_day_context_text()

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/env/system.py#L756`

:::

:::{py:method} RemoteEnvironmentClient.get_context_text()

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/env/system.py#L759`

:::
