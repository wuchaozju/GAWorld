"""Where the dashboard reads and writes, for the request's active world.

Every path the dashboard resolves goes through here: the module constants are
the shared default world's, and each helper switches to the active world's copy
(``output/worlds/<id>/``) when a request runs inside one. The active world is
the ``gaworld.accounts.context.WORLD`` context variable, set per request by the
dashboard's guard and carried into background jobs by ``ownership.spawn``.

Split out of ``dashboard_server``. Tests redirect paths by patching this module
(``world_paths.REPO_ROOT``, ``world_paths.effective_config``); the old
``ds._effective_config`` / ``ds.REPO_ROOT`` names raise, pointing here.
"""

from __future__ import annotations

import json
import os
from typing import Any

from gaworld import worlds
from gaworld.accounts import context as request_context
from gaworld.city.config import AGENT_FILES
from gaworld.settings import CONFIG

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DASHBOARD_CONFIG_PATH = os.path.join(REPO_ROOT, "dashboard_config.json")
PROFILE_PATH = os.path.join(REPO_ROOT, CONFIG.get("md_path", "data/hangzhou_profiles_with_names.md"))
STATE_CSV_PATH = os.path.join(REPO_ROOT, CONFIG.get("csv_path", "data/hangzhou_agents_state_init.csv"))
ECONOMY_SNAPSHOT_PATH = os.path.join(REPO_ROOT, "output", "economy", "wealth_snapshot.csv")
#: Kernel Recorder output (one JSONL per table). Panels that read a plugin's
#: recorded stream resolve it from here so tests can redirect it.
RECORDS_DIR = os.path.join(REPO_ROOT, "output", "records")
RUN_LOG_PATH = os.path.join(REPO_ROOT, "output", "dashboard", "simulation_run.log")
#: Where the plugin reads the frozen z scores from. Editing here takes effect on
#: the **next** run, like every other seed the studio writes: the plugin loads
#: this file once at ``agents.built`` and the record is read-only afterwards.
BIG5_CSV_PATH = os.path.join(
    REPO_ROOT,
    (CONFIG.get("personality", {}) or {}).get("profile_path", "data/agents_big5.csv"),
)


def current_world() -> dict[str, Any] | None:
    return request_context.WORLD.get()


def world_file(*parts: str) -> str:
    """Absolute path inside the active world's directory (callers check there is one)."""
    world = current_world()
    assert world is not None, "world_file() outside a world"
    return os.path.join(REPO_ROOT, worlds.root(world["id"]), *parts)


def config_path() -> str:
    """Where `POST /api/config` writes: the world's config, else the global file."""
    world = current_world()
    return worlds.config_path(REPO_ROOT, world["id"]) if world else DASHBOARD_CONFIG_PATH


def profile_path() -> str:
    world = current_world()
    return os.path.join(REPO_ROOT, worlds.seed_paths(world["id"])[1]) if world else PROFILE_PATH


def state_csv_path() -> str:
    world = current_world()
    return os.path.join(REPO_ROOT, worlds.seed_paths(world["id"])[0]) if world else STATE_CSV_PATH


def big5_csv_path() -> str:
    """The Big Five seed table of the active world (its own copy under ``seed/``)."""
    world = current_world()
    if not world:
        return BIG5_CSV_PATH
    return os.path.join(REPO_ROOT, worlds.root(world["id"]), "seed", AGENT_FILES["personality.profile_path"])


def run_root() -> str:
    """Where the active world's runs write: the world's directory, else the
    selected city's run root (``output/cities/<slug>``), else ``output/``."""
    if current_world():
        return world_file()
    return os.path.join(REPO_ROOT, effective_config().get("run_output_dir") or "output")


def _run_path(section: str, fallback: str, *parts: str) -> str:
    """``<section>.output_dir`` of the effective config, or *fallback*.

    The fixed ``output/...`` constants are only right for the default world. A
    selected city moves every run path under ``output/cities/<slug>/`` (see
    ``gaworld.city.config.RUN_PATHS``), so reading the constant showed the
    previous world's numbers — or the test suite's — as the current run's.
    """
    configured = (effective_config().get(section) or {}).get("output_dir")
    return os.path.join(REPO_ROOT, configured, *parts) if configured else fallback


def economy_snapshot_path() -> str:
    if current_world():
        return world_file("economy", "wealth_snapshot.csv")
    return _run_path("economy", ECONOMY_SNAPSHOT_PATH, "wealth_snapshot.csv")


def records_dir() -> str:
    return world_file("records") if current_world() else _run_path("records", RECORDS_DIR)


def run_log_path() -> str:
    return world_file("run.log") if current_world() else RUN_LOG_PATH


def deep_update(base: Any, patch: Any) -> Any:
    if not isinstance(base, dict) or not isinstance(patch, dict):
        return base
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            deep_update(base[key], value)
        else:
            base[key] = value
    return base


def read_json_file(path: str, default: Any = None) -> Any:
    if not os.path.exists(path):
        return {} if default is None else default
    try:
        with open(path, encoding="utf-8") as f:
            payload = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {} if default is None else default
    return payload


def atomic_write_json(path: str, payload: Any) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)


def dashboard_config() -> dict[str, Any]:
    payload = read_json_file(DASHBOARD_CONFIG_PATH, {})
    return payload if isinstance(payload, dict) else {}


def effective_config() -> dict[str, Any]:
    """The configuration a fresh process would load, as of right now.

    Deliberately *not* ``deepcopy(CONFIG)``. ``CONFIG`` is assembled once at
    import and ``settings/overrides.py`` already merges the override files
    into it, so it is a snapshot that goes stale the moment the dashboard
    writes one. Reading it back told a user who had just reset a key that it
    still held its old value — the exact "the edit looks like it worked"
    failure the 配置 panel exists to prevent — because the reset emptied the
    override file while the stale copy kept the overridden value.

    So rebuild from the Python defaults and re-apply the layers in the order
    ``overrides.apply_runtime_overrides`` uses (env last, twice, so it beats
    the environment file). The dashboard layer comes from
    ``dashboard_config()`` rather than the loader's relative path, keeping
    the module path constants the single lever over where it reads.
    """
    from gaworld.city.config import apply_city
    from gaworld.settings.defaults import build_default_config
    from gaworld.settings.overrides import load_env_override, load_environment_config

    cfg = build_default_config()
    env_override = load_env_override()
    world = current_world()
    deep_update(cfg, dashboard_config())
    if world:
        deep_update(cfg, worlds.read_config(REPO_ROOT, world["id"]))
    deep_update(cfg, env_override)
    deep_update(cfg, load_environment_config(cfg.get("environment_config_path")))
    apply_city(cfg, root=REPO_ROOT)
    if world:
        # Last but the environment: a world's paths beat the city's run root.
        deep_update(cfg, worlds.overrides(world["id"]))
    deep_update(cfg, env_override)
    return cfg


def memory_base_dir() -> str:
    return os.path.join(REPO_ROOT, effective_config().get("memory_dir", "output/memory"))


def memory_file(agent_id: Any, suffix: str = "") -> str:
    return os.path.join(memory_base_dir(), f"agent_{int(agent_id)}{suffix}.json")


#: Name in ``dashboard_server`` before the split -> name here; its guard
#: (``dashboard_server._MovedNamesGuard``) points stale uses at these.
DASHBOARD_ALIASES = {
    "REPO_ROOT": "REPO_ROOT",
    "DASHBOARD_CONFIG_PATH": "DASHBOARD_CONFIG_PATH",
    "PROFILE_PATH": "PROFILE_PATH",
    "STATE_CSV_PATH": "STATE_CSV_PATH",
    "ECONOMY_SNAPSHOT_PATH": "ECONOMY_SNAPSHOT_PATH",
    "RECORDS_DIR": "RECORDS_DIR",
    "RUN_LOG_PATH": "RUN_LOG_PATH",
    "BIG5_CSV_PATH": "BIG5_CSV_PATH",
    "_current_world": "current_world",
    "_world_file": "world_file",
    "_config_path": "config_path",
    "_profile_path": "profile_path",
    "_state_csv_path": "state_csv_path",
    "_big5_csv_path": "big5_csv_path",
    "_economy_snapshot_path": "economy_snapshot_path",
    "_records_dir": "records_dir",
    "_run_log_path": "run_log_path",
    "_deep_update": "deep_update",
    "_read_json_file": "read_json_file",
    "_atomic_write_json": "atomic_write_json",
    "_dashboard_config": "dashboard_config",
    "_effective_config": "effective_config",
    "_memory_base_dir": "memory_base_dir",
    "_memory_file": "memory_file",
}
