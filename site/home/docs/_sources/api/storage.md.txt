# 存储模块

结构化事件记录、记忆与运行状态访问。

接口签名与说明由当前仓库源代码生成。

## gaworld.kernel.recorder

:::{py:currentmodule} gaworld.kernel.recorder
:::

:::{py:class} Recorder(base_dir: str='output/records', clock: 'Clock | None'=None)

```{eval-rst}
Append-only JSONL recorder with automatic clock stamping.
```

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/kernel/recorder.py#L26`

:::

:::{py:method} Recorder.record(table: str, data: dict) -> None

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/kernel/recorder.py#L34`

:::

:::{py:method} Recorder.close() -> None

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/kernel/recorder.py#L55`

:::

## gaworld.memory.store

:::{py:currentmodule} gaworld.memory.store
:::

:::{py:function} load_agent_memory(agent_id)

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/memory/store.py#L142`

:::

:::{py:function} known_agent_ids()

```{eval-rst}
Agent ids that have memory persisted in ``MEMORY_DIR`` — i.e. have run.
```

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/memory/store.py#L154`

:::

:::{py:function} save_agent_memory(agent)

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/memory/store.py#L168`

:::

:::{py:function} load_agent_schedule(agent_id)

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/memory/store.py#L174`

:::

:::{py:function} save_agent_schedule(agent_id, schedule)

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/memory/store.py#L200`

:::

:::{py:function} load_agent_actions(agent_id)

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/memory/store.py#L209`

:::

:::{py:function} save_agent_actions(agent_id, action_space)

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/memory/store.py#L227`

:::

:::{py:function} load_sim_state()

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/memory/store.py#L285`

:::

:::{py:function} save_sim_state(state)

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/memory/store.py#L297`

:::
