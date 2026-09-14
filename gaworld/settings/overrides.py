"""Runtime override loading for the legacy CONFIG dict."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def deep_update(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(base, dict) or not isinstance(patch, dict):
        return base
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            deep_update(base[key], value)
        else:
            base[key] = value
    return base


def load_env_override() -> dict[str, Any]:
    raw = os.environ.get("GAWORLD_CONFIG_OVERRIDES", "").strip()
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def load_json_override(path: str) -> dict[str, Any]:
    if not path:
        return {}
    target = str(path).strip()
    if not target:
        return {}
    if not os.path.isabs(target):
        target = str(PROJECT_ROOT / target)
    if not os.path.exists(target):
        return {}
    try:
        with open(target, encoding="utf-8") as f:
            payload = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def load_environment_config(path: str | None) -> dict[str, Any]:
    if not path:
        return {}
    target = str(path).strip()
    if not target:
        return {}
    if not os.path.isabs(target):
        target = str(PROJECT_ROOT / target)
    if not os.path.exists(target):
        return {}
    try:
        with open(target, encoding="utf-8") as f:
            payload = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}

    allowed: dict[str, Any] = {}
    if isinstance(payload.get("environment"), dict):
        allowed["environment"] = payload["environment"]
    if isinstance(payload.get("external_environment"), dict):
        allowed["external_environment"] = payload["external_environment"]
    if isinstance(payload.get("external_environment_service"), dict):
        allowed["external_environment_service"] = payload["external_environment_service"]
    if isinstance(payload.get("environment_server"), dict):
        allowed["environment_server"] = payload["environment_server"]
    return allowed


def apply_runtime_overrides(config: dict[str, Any]) -> dict[str, Any]:
    overrides = load_env_override()
    deep_update(config, load_json_override("dashboard_config.json"))
    deep_update(config, overrides)
    deep_update(config, load_environment_config(config.get("environment_config_path")))
    # A selected city bundle (config["city"]) supplies its own map, environment
    # and background. It is applied *after* the global environment-config file,
    # which is a default rather than a per-city intent — otherwise a city in a
    # continental climate would inherit the global file's subtropical events.
    # GAWORLD_CONFIG_OVERRIDES still runs last and has the final word.
    from gaworld.city.config import apply_city

    apply_city(config)
    deep_update(config, overrides)
    return config
