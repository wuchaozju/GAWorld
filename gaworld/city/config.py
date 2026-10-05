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
    "organizations.output_dir": "organizations",
    "intervention.output_dir": "intervention",
    "life_events.event_dir": "life_events",
    "visualization.output_dir": "visualization",
    "collaboration.sessions_dir": "collaboration/sessions",
    "real_work.artifacts_dir": "work",
    "real_work.queue_path": "work/queue.jsonl",
    "real_work.capabilities_cache": "work/capabilities.json",
    "real_work.market.store_path": "work/market.jsonl",
    "twin.root": "twin",
    "interests.cache_path": "memory/growth_profiles.json",
    "family.output_dir": "family",
    "personality.output_dir": "traits",
    "moltbook.log_dir": "moltbook",
    "run_manifest.output_dir": "run_manifests",
    # Defaults that live in code rather than in the config defaults: the
    # Recorder's streams, the dashboard→simulator queue, and the root every
    # plugin's own output namespace hangs off (Plugin.output_dir).
    "records.output_dir": "records",
    "kernel.interventions_path": "kernel/interventions.json",
    "output_root": "",
}

#: Inputs keyed by agent id. Agent ids restart at 1 in every city, so these
#: belong to one population: a city keeps them in its bundle directory, a world
#: next to its own copy of the residents. The default world keeps its ``data/``.
AGENT_FILES = {
    "personality.profile_path": "agents_big5.csv",
    "family.overrides_path": "family_overrides.json",
    "moltbook.accounts_path": "moltbook_accounts.json",
}


def _set_dotted(patch: dict[str, Any], path: str, value: str) -> None:
    parts = path.split(".")
    node = patch
    for part in parts[:-1]:
        node = node.setdefault(part, {})
    node[parts[-1]] = value


def agent_file_overrides(base: str) -> dict[str, Any]:
    """Config patch pointing every :data:`AGENT_FILES` input into *base*."""
    patch: dict[str, Any] = {}
    for path, leaf in AGENT_FILES.items():
        _set_dotted(patch, path, f"{base}/{leaf}")
    return patch


def run_overrides(slug: str) -> dict[str, Any]:
    """Config patch moving every runtime path under this city's run root.

    Agent memory, logs and the vector store are keyed by agent id alone, and
    ``sim_state.json`` holds one world clock — so without this, two cities'
    ``#1`` share one set of files and one calendar, and selecting a new city
    drops its residents into the previous city's accumulated history.
    """
    from gaworld.city.bundle import RUNS_DIRNAME

    return run_root_overrides(f"{RUNS_DIRNAME}/{slug}")


def run_root_overrides(base: str) -> dict[str, Any]:
    """Config patch moving every path in :data:`RUN_PATHS` under *base*."""
    patch: dict[str, Any] = {}
    for path, leaf in RUN_PATHS.items():
        _set_dotted(patch, path, f"{base}/{leaf}" if leaf else base)
    return patch


def city_overrides(ref: str, root: Any = None) -> dict[str, Any]:
    """Config patch for the city *ref*, or ``{}`` when it cannot be resolved.

    Resolution failures are non-fatal: a config naming a city that has been
    deleted should fall back to the default world with a warning rather than
    make the simulator unstartable.
    """
    from gaworld.city.bundle import PROJECT_ROOT, CityNotFoundError, resolve_city
    from gaworld.settings.overrides import deep_update

    if not str(ref or "").strip():
        return {}
    try:
        bundle = resolve_city(str(ref).strip(), root)
    except (CityNotFoundError, OSError, json.JSONDecodeError):
        return {}

    patch: dict[str, Any] = dict(bundle.paths_for_config())
    patch["city"] = bundle.slug
    deep_update(patch, run_overrides(bundle.slug))
    try:
        city_dir = bundle.directory.resolve().relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        city_dir = str(bundle.directory)
    deep_update(patch, agent_file_overrides(city_dir))

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
    "AGENT_FILES",
    "ENVIRONMENT_KEYS",
    "RUN_PATHS",
    "agent_file_overrides",
    "apply_city",
    "city_overrides",
    "run_overrides",
    "run_root_overrides",
]
