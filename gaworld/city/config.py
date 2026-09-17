"""Point the simulator's config at a selected city bundle.

Setting ``"city": "<slug>"`` anywhere in the config chain swaps the whole world
the simulator runs in: its map, its environment events and its background
prompt, plus the population files if the bundle has any.

Kept deliberately dependency-free (only :mod:`gaworld.city.bundle`, which is
stdlib-only) because this runs during config load, long before the heavier
simulation packages are wanted.
"""

from __future__ import annotations

import json
from typing import Any

#: Keys a bundle's ``environment.json`` may contribute to the running config.
#: Mirrors ``settings.overrides.load_environment_config`` plus ``background``,
#: which is what stops a new city's agents from believing they are in Hangzhou.
ENVIRONMENT_KEYS = (
    "environment",
    "external_environment",
    "external_environment_service",
    "environment_server",
)

#: Every runtime path the simulator writes, as ``config path -> path under the
#: city's run root``. Dotted keys address nested config sections.
#:
#: The layout inside a run root mirrors the default ``output/`` tree one-for-one.
#: That is load-bearing, not cosmetic: Analytics joins ``state/`` and ``economy/``
#: onto a run's root, and ``replay_runs`` globs ``output/*/visualization`` to
#: find traces — both keep working only because the names below do not change.
RUN_PATHS = {
    "run_output_dir": "",  # the root itself; Analytics reads this one
    "memory_dir": "memory",
    "vector_db_path": "memory/vector_db.sqlite",
    "log_dir": "logs",
    "state_output_dir": "state",
    "network_output_dir": "network",
    "environment_output_dir": "environment",
    "diary_output_dir": "diaries",
    "agent_import_output_dir": "imported_agents",
    "economy.output_dir": "economy",
    "intervention.output_dir": "intervention",
    "life_events.event_dir": "life_events",
    "visualization.output_dir": "visualization",
    "collaboration.sessions_dir": "collaboration/sessions",
    "real_work.artifacts_dir": "work",
    "twin.root": "twin",
}


def run_overrides(slug: str) -> dict[str, Any]:
    """Config patch moving every runtime path under this city's run root.

    Agent memory, logs and the vector store are keyed by agent id alone, and
    ``sim_state.json`` holds one world clock — so without this, two cities'
    ``#1`` share one set of files and one calendar, and selecting a new city
    drops its residents into the previous city's accumulated history.
    """
    from gaworld.city.bundle import RUNS_DIRNAME

    base = f"{RUNS_DIRNAME}/{slug}"
    patch: dict[str, Any] = {}
    for path, leaf in RUN_PATHS.items():
        parts = path.split(".")
        node = patch
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = f"{base}/{leaf}" if leaf else base
    return patch


def city_overrides(ref: str, root: Any = None) -> dict[str, Any]:
    """Config patch for the city *ref*, or ``{}`` when it cannot be resolved.

    Resolution failures are non-fatal: a config naming a city that has been
    deleted should fall back to the default world with a warning rather than
    make the simulator unstartable.
    """
    from gaworld.city.bundle import CityNotFoundError, resolve_city

    if not str(ref or "").strip():
        return {}
    try:
        bundle = resolve_city(str(ref).strip(), root)
    except (CityNotFoundError, OSError, json.JSONDecodeError):
        return {}

    patch: dict[str, Any] = dict(bundle.paths_for_config())
    patch["city"] = bundle.slug
    patch.update(run_overrides(bundle.slug))

    if bundle.environment_path.exists():
        try:
            payload = json.loads(bundle.environment_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {}
        if isinstance(payload, dict):
            for key in ENVIRONMENT_KEYS:
                if isinstance(payload.get(key), dict):
                    patch[key] = payload[key]
            background = str(payload.get("background") or "").strip()
            if background:
                patch["background"] = background

    # The city's industry profile biases what local work pays. This rides in as
    # a config override rather than a hook in the economy: `industry_conditions`
    # is already read from config, so a real city needs no new code path.
    if bundle.knowledge_path.exists():
        from gaworld.city.knowledge import CityProfile

        try:
            profile = CityProfile.from_dict(
                json.loads(bundle.knowledge_path.read_text(encoding="utf-8"))
            )
        except (OSError, json.JSONDecodeError, TypeError):
            profile = CityProfile()
        conditions = profile.industry_conditions()
        if conditions:
            patch.setdefault("economy", {}).setdefault("macro", {})["industry_conditions"] = {
                **conditions,
                "default": 1.0,
            }
    return patch


def apply_city(config: dict[str, Any], root: Any = None) -> dict[str, Any]:
    """Merge the selected city's overrides into *config*, in place."""
    from gaworld.settings.overrides import deep_update

    patch = city_overrides(config.get("city", ""), root)
    if patch:
        deep_update(config, patch)
    return config


__all__ = [
    "ENVIRONMENT_KEYS",
    "RUN_PATHS",
    "apply_city",
    "city_overrides",
    "run_overrides",
]
