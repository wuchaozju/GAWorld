# HTTP 客户端

HTTP 客户端、操作调用、后台任务与错误类型。

接口签名与说明由当前仓库源代码生成。

## gaworld.client

:::{py:currentmodule} gaworld.client
:::

:::{py:class} APIError(status: int, message: str, body: Any=None, method: str='', path: str='')

```{eval-rst}
A non-2xx answer: ``status``, the server's ``message`` and the decoded ``body``.
```

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/client.py#L40`

:::

:::{py:class} AuthError

```{eval-rst}
401 (not signed in / bad token) or 403 (not allowed).
```

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/client.py#L52`

:::

:::{py:class} NotFoundError

```{eval-rst}
404: unknown route, resident, job, …
```

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/client.py#L56`

:::

:::{py:class} ConflictError

```{eval-rst}
409: busy, e.g. a simulation is already running or none is.
```

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/client.py#L60`

:::

:::{py:class} QuotaError

```{eval-rst}
429: the daily model-call quota is used up.
```

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/client.py#L64`

:::

:::{py:class} JobFailed(job: dict[str, Any])

```{eval-rst}
A background job ended in ``failed`` / ``error`` / ``stopped``.
```

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/client.py#L68`

:::

:::{py:class} GAWorldClient(base_url: str=DEFAULT_URL, token: str | None=None, timeout: float=60.0)

```{eval-rst}
One connection's worth of state: base URL, operator token, cookies (session and world).
```

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/client.py#L80`

:::

:::{py:method} GAWorldClient.request(method: str, path: str, body: Any=None, params: dict[str, Any] | None=None) -> Any

```{eval-rst}
Send one request; JSON answers come back decoded, anything else as ``bytes``.
```

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/client.py#L117`

:::

:::{py:method} GAWorldClient.get(path: str, **params: Any) -> Any

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/client.py#L125`

:::

:::{py:method} GAWorldClient.post(path: str, body: dict[str, Any] | None=None) -> Any

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/client.py#L128`

:::

:::{py:method} GAWorldClient.operations() -> dict[str, tuple[str, str]]

```{eval-rst}
``operationId → (METHOD, path template)``, read once from the server's document.
```

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/client.py#L133`

:::

:::{py:method} GAWorldClient.call(operation_id: str, body: dict[str, Any] | None=None, **params: Any) -> Any

```{eval-rst}
Call an operation of ``/api/openapi.json``.

Path parameters are taken from ``params`` by name; the rest go into the
query string. ``body`` is the JSON body of a POST.
```

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/client.py#L144`

:::

:::{py:method} GAWorldClient.me() -> dict[str, Any]

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/client.py#L166`

:::

:::{py:method} GAWorldClient.login(nickname: str, password: str) -> dict[str, Any]

```{eval-rst}
Sign in (accounts mode); the session cookie is kept for later requests.
```

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/client.py#L169`

:::

:::{py:method} GAWorldClient.logout() -> None

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/client.py#L173`

:::

:::{py:method} GAWorldClient.worlds() -> dict[str, Any]

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/client.py#L176`

:::

:::{py:method} GAWorldClient.use_world(world_id: str) -> None

```{eval-rst}
Make *world_id* the active world of later requests (``""``: the shared default).
```

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/client.py#L179`

:::

:::{py:method} GAWorldClient.agents() -> list[dict[str, Any]]

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/client.py#L185`

:::

:::{py:method} GAWorldClient.agent(agent_id: int) -> dict[str, Any]

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/client.py#L188`

:::

:::{py:method} GAWorldClient.run_status() -> dict[str, Any]

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/client.py#L191`

:::

:::{py:method} GAWorldClient.start_run(config: dict[str, Any] | None=None, reset: bool=False) -> dict[str, Any]

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/client.py#L194`

:::

:::{py:method} GAWorldClient.stop_run() -> dict[str, Any]

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/client.py#L200`

:::

:::{py:method} GAWorldClient.interventions() -> dict[str, Any]

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/client.py#L203`

:::

:::{py:method} GAWorldClient.intervene(name: str, **kwargs: Any) -> dict[str, Any]

```{eval-rst}
Queue an intervention for the running simulation; returns the request (``status: pending``).
```

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/client.py#L206`

:::

:::{py:method} GAWorldClient.wait_intervention(request_id: str, *, interval: float=1.0, timeout: float | None=300) -> dict

```{eval-rst}
Poll until the simulation applied (or failed) the request; raises TimeoutError.
```

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/client.py#L210`

:::

:::{py:method} GAWorldClient.wait_job(poll_path: str, *, interval: float=1.0, timeout: float | None=None) -> dict[str, Any]

```{eval-rst}
Poll a ``…/jobs/{id}`` route until the job is final; raises :class:`JobFailed` if it failed.
```

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/client.py#L217`

:::

:::{py:method} GAWorldClient.run_job(path: str, body: dict[str, Any] | None=None, *, poll: str | None=None, interval: float=1.0, timeout: float | None=None) -> Any

```{eval-rst}
Start a job, wait for it, return its ``result``.

The job is polled at ``<parent of path>/jobs/<id>`` — the dashboard's
layout for every job-starting route (``/api/games/rumor/run`` →
``/api/games/rumor/jobs/<id>``); pass ``poll`` for one that differs, with
``{job_id}`` where the id goes.
```

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/client.py#L225`

:::

:::{py:method} GAWorldClient.events(tables: list[str] | tuple[str, ...] | None=None, timeout: float | None=None) -> Iterator[tuple[str, dict[str, Any]]]

```{eval-rst}
Follow ``/api/events/stream``: yields ``(table, row)`` for every new Recorder row.

Blocks between rows (the server sends a keep-alive every 15 s); stop by
breaking out of the loop. ``timeout`` bounds the wait for one line.
```

{gaworld-source}`https://github.com/wuchaozju/GAWorld/blob/main/gaworld/client.py#L253`

:::

## HTTP 接口描述

运行 Dashboard 后，可读取完整 OpenAPI 文档：

```bash
curl http://127.0.0.1:8766/api/openapi.json
```

文档包含操作名、路径、参数、请求体、响应与访问要求。客户端的 `operations()` 列出操作，`call()` 通过 `operationId` 调用。

独立的 Twin、Agent Relay 和 External Environment 服务接口见仓库的 [完整 API 参考](https://github.com/wuchaozju/GAWorld/blob/main/docs/API_REFERENCE.md)。
