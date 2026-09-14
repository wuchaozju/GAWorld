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
    return patch


def apply_city(config: dict[str, Any], root: Any = None) -> dict[str, Any]:
    """Merge the selected city's overrides into *config*, in place."""
    from gaworld.settings.overrides import deep_update

    patch = city_overrides(config.get("city", ""), root)
    if patch:
        deep_update(config, patch)
    return config


__all__ = ["ENVIRONMENT_KEYS", "apply_city", "city_overrides"]
