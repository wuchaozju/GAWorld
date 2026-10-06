"""The dashboard API modules that answer a whole path prefix on their own.

Each listed module has ``handle_get(path, query)`` and/or
``handle_post(path, payload)`` returning ``(body, status)``; the dashboard turns
that into the JSON response. Order matters as it did in the old ``if`` chain:
the first matching route wins. Routes that need the request's user, the account
store or a cookie (auth, worlds, cluster, play, city writes) stay in
``dashboard_server``'s handler, ahead of or after this table where they were.

A new subsystem adds one line here instead of another branch to the handler.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Route:
    module: str
    prefix: str
    #: Also answer the prefix without its trailing slash (``/api/interventions``).
    bare: bool = False

    def matches(self, path: str) -> bool:
        return path.startswith(self.prefix) or (self.bare and path == self.prefix.rstrip("/"))


GET_ROUTES = (
    Route("health_api", "/api/health"),
    # Kernel surface: generic interventions (the SSE record stream and the
    # OpenAPI spec are answered by the handler, ahead of this table).
    Route("kernel_api", "/api/interventions/", bare=True),
    Route("organizations_api", "/api/organizations/", bare=True),
    Route("infosources_api", "/api/infosources/"),
    Route("bench_api", "/api/bench/"),
    Route("economy_api", "/api/economy/"),
    # Population Studio / group mode.
    Route("population_api", "/api/population"),
    Route("import_api", "/api/import"),
    # 游戏场 (playground). The arena keeps its own older namespace; every other
    # game hangs off /api/games/<game>/.
    Route("arena_api", "/api/arena"),
    Route("games_api", "/api/games/"),
    Route("family_api", "/api/family"),
    # Trailing slash on purpose: the single-agent `POST /api/interview` is a
    # different, older endpoint and must not be shadowed.
    Route("interview_api", "/api/interview/"),
    Route("research_api", "/api/research/"),
    Route("persona_api", "/api/persona/"),
    Route("external_systems_api", "/api/external-systems"),
    Route("parallel_worlds_api", "/api/parallel-worlds"),
    Route("settings_api", "/api/settings"),
    Route("city_api", "/api/city"),
    Route("moltbook_api", "/api/moltbook"),
    Route("home_api", "/api/home"),
)

POST_ROUTES = (
    Route("kernel_api", "/api/interventions/"),
    Route("organizations_api", "/api/organizations/", bare=True),
    Route("bench_api", "/api/bench/"),
    Route("population_api", "/api/population"),
    Route("import_api", "/api/import"),
    Route("arena_api", "/api/arena"),
    Route("games_api", "/api/games/"),
    Route("family_api", "/api/family"),
    Route("interview_api", "/api/interview/"),
    Route("research_api", "/api/research/"),
    Route("persona_api", "/api/persona/"),
    Route("external_systems_api", "/api/external-systems"),
    Route("parallel_worlds_api", "/api/parallel-worlds"),
    Route("settings_api", "/api/settings"),
    Route("moltbook_api", "/api/moltbook"),
)


def find(routes: tuple[Route, ...], path: str) -> Route | None:
    return next((route for route in routes if route.matches(path)), None)


def dispatch_get(path: str, query: dict) -> tuple[Any, int] | None:
    """``(body, status)`` from the module owning *path*, or None if none does."""
    route = find(GET_ROUTES, path)
    if route is None:
        return None
    return importlib.import_module(f"gaworld.apps.{route.module}").handle_get(path, query)


def dispatch_post(path: str, payload: dict) -> tuple[Any, int] | None:
    route = find(POST_ROUTES, path)
    if route is None:
        return None
    return importlib.import_module(f"gaworld.apps.{route.module}").handle_post(path, payload)
