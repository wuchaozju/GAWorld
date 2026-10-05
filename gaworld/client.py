"""Python client for the GAWorld dashboard API (standard library only).

    from gaworld.client import GAWorldClient

    gw = GAWorldClient("http://127.0.0.1:8766")          # token: $GAWORLD_DASHBOARD_TOKEN
    gw.run_status()
    gw.intervene("set_agent_state", agent_id=3, key="stress", value=0.9)
    result = gw.run_job("/api/games/rumor/run", {"agent_ids": [1, 2, 3], "rumor_id": "water"})
    gw.call("get_city_agents", city="wuzhen", limit=20)  # any operation, by operationId
    for table, row in gw.events(["agent.step"]):
        ...

Every operation of ``GET /api/openapi.json`` can be reached with :meth:`call`;
the named methods cover the common loops (sign in, pick a world, start a run,
intervene, wait for a job, follow the record stream). Errors raise
:class:`APIError` — or the subclass for 401/403, 404, 409 and 429.
"""

from __future__ import annotations

import http.cookiejar
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator
from typing import Any

DEFAULT_URL = "http://127.0.0.1:8766"

#: Job states that mean "not finished yet"; anything else is final.
RUNNING_STATES = frozenset({"running", "queued", "pending", "starting"})
#: Final job states that mean the job did not produce its result.
FAILED_STATES = frozenset({"failed", "error", "stopped"})


class APIError(Exception):
    """A non-2xx answer: ``status``, the server's ``message`` and the decoded ``body``."""

    def __init__(self, status: int, message: str, body: Any = None, method: str = "", path: str = "") -> None:
        super().__init__(f"{method} {path} → {status}: {message}".strip())
        self.status = status
        self.message = message
        self.body = body
        self.method = method
        self.path = path


class AuthError(APIError):
    """401 (not signed in / bad token) or 403 (not allowed)."""


class NotFoundError(APIError):
    """404: unknown route, resident, job, …"""


class ConflictError(APIError):
    """409: busy, e.g. a simulation is already running or none is."""


class QuotaError(APIError):
    """429: the daily model-call quota is used up."""


class JobFailed(Exception):
    """A background job ended in ``failed`` / ``error`` / ``stopped``."""

    def __init__(self, job: dict[str, Any]) -> None:
        super().__init__(f"job {job.get('id')} {job.get('status')}: {job.get('error') or job.get('message') or ''}")
        self.job = job


_ERRORS = {401: AuthError, 403: AuthError, 404: NotFoundError, 409: ConflictError, 429: QuotaError}
_PARAM = re.compile(r"\{([^}]+)\}")


class GAWorldClient:
    """One connection's worth of state: base URL, operator token, cookies (session and world)."""

    def __init__(self, base_url: str = DEFAULT_URL, token: str | None = None, timeout: float = 60.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token if token is not None else os.environ.get("GAWORLD_DASHBOARD_TOKEN", "").strip() or None
        self.timeout = timeout
        self.cookies = http.cookiejar.CookieJar()
        self._opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cookies))
        self._operations: dict[str, tuple[str, str]] | None = None

    # -- transport --------------------------------------------------------------

    def _open(self, method: str, path: str, body: Any = None, params: dict[str, Any] | None = None,
              timeout: float | None = None) -> Any:
        url = self.base_url + path
        query = {k: _query_value(v) for k, v in (params or {}).items() if v is not None}
        if query:
            url += "?" + urllib.parse.urlencode(query)
        data = json.dumps(body if body is not None else {}).encode("utf-8") if method == "POST" else None
        request = urllib.request.Request(url, data=data, method=method)
        request.add_header("Accept", "application/json")
        if data is not None:
            request.add_header("Content-Type", "application/json")
        if self.token:
            request.add_header("Authorization", f"Bearer {self.token}")
        try:
            return self._opener.open(request, timeout=timeout if timeout is not None else self.timeout)
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            try:
                decoded: Any = json.loads(raw) if raw else None
            except ValueError:
                decoded = raw.decode("utf-8", "replace")
            message = decoded.get("error", "") if isinstance(decoded, dict) else str(decoded or exc.reason)
            raise _ERRORS.get(exc.code, APIError)(exc.code, message, decoded, method, path) from None

    def request(self, method: str, path: str, body: Any = None, params: dict[str, Any] | None = None) -> Any:
        """Send one request; JSON answers come back decoded, anything else as ``bytes``."""
        with self._open(method.upper(), path, body, params) as response:
            raw = response.read()
            if "json" in response.headers.get("Content-Type", ""):
                return json.loads(raw) if raw else None
            return raw

    def get(self, path: str, **params: Any) -> Any:
        return self.request("GET", path, params=params)

    def post(self, path: str, body: dict[str, Any] | None = None) -> Any:
        return self.request("POST", path, body)

    # -- any operation, by operationId -------------------------------------------

    def operations(self) -> dict[str, tuple[str, str]]:
        """``operationId → (METHOD, path template)``, read once from the server's document."""
        if self._operations is None:
            spec = self.get("/api/openapi.json")
            self._operations = {
                op["operationId"]: (method.upper(), template)
                for template, item in spec["paths"].items()
                for method, op in item.items()
            }
        return self._operations

    def call(self, operation_id: str, body: dict[str, Any] | None = None, **params: Any) -> Any:
        """Call an operation of ``/api/openapi.json``.

        Path parameters are taken from ``params`` by name; the rest go into the
        query string. ``body`` is the JSON body of a POST.
        """
        try:
            method, template = self.operations()[operation_id]
        except KeyError:
            raise ValueError(f"unknown operation {operation_id!r}") from None

        def fill(match: re.Match[str]) -> str:
            name = match.group(1)
            if name not in params:
                raise ValueError(f"{operation_id} needs the path parameter {name!r}")
            return urllib.parse.quote(str(params.pop(name)), safe="")

        path = _PARAM.sub(fill, template)
        return self.request(method, path, body if method == "POST" else None, params)

    # -- accounts and worlds -------------------------------------------------------

    def me(self) -> dict[str, Any]:
        return self.get("/api/auth/me")

    def login(self, nickname: str, password: str) -> dict[str, Any]:
        """Sign in (accounts mode); the session cookie is kept for later requests."""
        return self.post("/api/auth/login", {"nickname": nickname, "password": password})["user"]

    def logout(self) -> None:
        self.post("/api/auth/logout")

    def worlds(self) -> dict[str, Any]:
        return self.get("/api/worlds")

    def use_world(self, world_id: str) -> None:
        """Make *world_id* the active world of later requests (``""``: the shared default)."""
        self.post("/api/worlds/select", {"id": world_id})

    # -- the simulation -------------------------------------------------------------

    def agents(self) -> list[dict[str, Any]]:
        return self.get("/api/agents")["agents"]

    def agent(self, agent_id: int) -> dict[str, Any]:
        return self.get(f"/api/agents/{int(agent_id)}/detail")

    def run_status(self) -> dict[str, Any]:
        return self.get("/api/run/status")

    def start_run(self, config: dict[str, Any] | None = None, reset: bool = False) -> dict[str, Any]:
        body: dict[str, Any] = {"reset": reset}
        if config:
            body["config"] = config
        return self.post("/api/run/start", body)

    def stop_run(self) -> dict[str, Any]:
        return self.post("/api/run/stop")

    def interventions(self) -> dict[str, Any]:
        return self.get("/api/interventions")

    def intervene(self, name: str, **kwargs: Any) -> dict[str, Any]:
        """Queue an intervention for the running simulation; returns the request (``status: pending``)."""
        return self.post(f"/api/interventions/{urllib.parse.quote(name, safe='')}", kwargs)

    def wait_intervention(self, request_id: str, *, interval: float = 1.0, timeout: float | None = 300) -> dict:
        """Poll until the simulation applied (or failed) the request; raises TimeoutError."""
        return self._poll(f"/api/interventions/{request_id}", lambda item: item.get("status") != "pending",
                          interval, timeout)

    # -- background jobs ------------------------------------------------------------

    def wait_job(self, poll_path: str, *, interval: float = 1.0, timeout: float | None = None) -> dict[str, Any]:
        """Poll a ``…/jobs/{id}`` route until the job is final; raises :class:`JobFailed` if it failed."""
        job = self._poll(poll_path, lambda record: str(record.get("status")) not in RUNNING_STATES,
                         interval, timeout)
        if str(job.get("status")) in FAILED_STATES:
            raise JobFailed(job)
        return job

    def run_job(self, path: str, body: dict[str, Any] | None = None, *, poll: str | None = None,
                interval: float = 1.0, timeout: float | None = None) -> Any:
        """Start a job, wait for it, return its ``result``.

        The job is polled at ``<parent of path>/jobs/<id>`` — the dashboard's
        layout for every job-starting route (``/api/games/rumor/run`` →
        ``/api/games/rumor/jobs/<id>``); pass ``poll`` for one that differs, with
        ``{job_id}`` where the id goes.
        """
        started = self.post(path, body)
        job_id = started.get("job_id") or started.get("id")
        if not job_id:
            raise APIError(0, f"{path} did not start a job", started, "POST", path)
        poll_path = (poll or path.rsplit("/", 1)[0] + "/jobs/{job_id}").format(job_id=job_id)
        return self.wait_job(poll_path, interval=interval, timeout=timeout).get("result")

    def _poll(self, path: str, done: Any, interval: float, timeout: float | None) -> dict[str, Any]:
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            record = self.get(path)
            if done(record):
                return record
            if deadline is not None and time.monotonic() >= deadline:
                raise TimeoutError(f"{path} still not finished after {timeout} s")
            time.sleep(interval)

    # -- the record stream ------------------------------------------------------------

    def events(self, tables: list[str] | tuple[str, ...] | None = None,
               timeout: float | None = None) -> Iterator[tuple[str, dict[str, Any]]]:
        """Follow ``/api/events/stream``: yields ``(table, row)`` for every new Recorder row.

        Blocks between rows (the server sends a keep-alive every 15 s); stop by
        breaking out of the loop. ``timeout`` bounds the wait for one line.
        """
        params = {"tables": ",".join(tables)} if tables else None
        with self._open("GET", "/api/events/stream", params=params, timeout=timeout) as response:
            event = "message"
            data: list[str] = []
            for raw in response:
                line = raw.decode("utf-8").rstrip("\r\n")
                if not line:
                    if data:
                        yield event, json.loads("\n".join(data))
                    event, data = "message", []
                elif line.startswith(":"):
                    continue
                elif line.startswith("event:"):
                    event = line[6:].strip()
                elif line.startswith("data:"):
                    data.append(line[5:].lstrip())


def _query_value(value: Any) -> Any:
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (list, tuple)):
        return ",".join(str(item) for item in value)
    return value


__all__ = [
    "APIError",
    "AuthError",
    "ConflictError",
    "GAWorldClient",
    "JobFailed",
    "NotFoundError",
    "QuotaError",
]
