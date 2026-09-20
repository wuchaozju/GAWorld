"""Typed wrapper over the legacy :data:`config.CONFIG` dictionary.

The legacy ``config.CONFIG`` is a nested ``dict`` that has been the
single source of simulation parameters since the project started.
This module provides:

* :class:`SimulationConfig` – a :class:`dataclass` that exposes the
  most-used fields (sim length, agent ids, paths, LLM routing) with
  validated types.
* :func:`load_simulation_config` – a factory that builds it from
  ``config.CONFIG`` (which already supports environment overrides via
  ``GAWORLD_CONFIG_OVERRIDES`` and ``dashboard_config.json``).

The legacy ``CONFIG`` dict is preserved verbatim so existing modules
keep working unchanged. New code should prefer reading from
:class:`SimulationConfig` to get type-checked values.

We deliberately avoid pydantic here so the package has no extra
runtime dependency. Switching to pydantic later only requires
replacing the field definitions; the public surface stays the same.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------

def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _safe_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(default)


def _safe_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(v) for v in value if str(v).strip()]
    return [str(value).strip()] if str(value).strip() else []


def _safe_int_list(value: Any) -> list[int]:
    out: list[int] = []
    seen: set[int] = set()
    if value is None:
        return out
    if not isinstance(value, (list, tuple, set)):
        value = [value]
    for raw in value:
        try:
            v = int(raw)
        except (TypeError, ValueError):
            continue
        if v <= 0 or v in seen:
            continue
        seen.add(v)
        out.append(v)
    return out


# ---------------------------------------------------------------------
# Sub-configs
# ---------------------------------------------------------------------

@dataclass(frozen=True)
class LLMProvider:
    name: str
    type: str
    model: str
    extras: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LLMRouting:
    default: str
    tasks: Mapping[str, str] = field(default_factory=dict)
    agents: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class LLMConfig:
    providers: Mapping[str, LLMProvider]
    routing: LLMRouting


@dataclass(frozen=True)
class PathsConfig:
    csv_path: str
    md_path: str
    map_path: str
    memory_dir: str
    log_dir: str
    diary_dir: str
    environment_dir: str
    visualization_dir: str
    vector_db_path: str


@dataclass(frozen=True)
class SimulationConfig:
    """Typed view of the simulation knobs used by the main loop."""

    agent_ids: tuple[int, ...]
    sim_days: int
    seconds_per_day: int
    simulate_realtime: bool
    time_step_minutes: int | None
    time_grid_snap: bool
    stateful: bool
    print_agent_profile: bool
    background: str
    memory_model_version: int
    require_clean_reset_on_memory_model_change: bool
    paths: PathsConfig
    llm: LLMConfig
    raw: Mapping[str, Any] = field(default_factory=dict)

    @property
    def random_seed(self) -> int | None:
        seed = self.raw.get("random_seed")
        try:
            return int(seed) if seed is not None else None
        except (TypeError, ValueError):
            return None


# ---------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------

def _build_paths(raw: Mapping[str, Any]) -> PathsConfig:
    vis = raw.get("visualization", {}) or {}
    return PathsConfig(
        csv_path=str(raw.get("csv_path", "data/hangzhou_agents_state_init.csv")),
        md_path=str(raw.get("md_path", "data/hangzhou_profiles_with_names.md")),
        map_path=str(raw.get("map_path", "data/citymap.md")),
        memory_dir=str(raw.get("memory_dir", "output/memory")),
        log_dir=str(raw.get("log_dir", "output/logs")),
        diary_dir=str(raw.get("diary_output_dir", "output/diaries")),
        environment_dir=str(raw.get("environment_output_dir", "output/environment")),
        visualization_dir=str(vis.get("output_dir", "output/visualization")),
        vector_db_path=str(raw.get("vector_db_path", "output/memory/vector_db.sqlite")),
    )


def _build_llm(raw: Mapping[str, Any]) -> LLMConfig:
    block = raw.get("llm", {}) or {}
    providers_raw = block.get("providers", {}) or {}
    providers: dict[str, LLMProvider] = {}
    for name, cfg in providers_raw.items():
        if not isinstance(cfg, dict):
            continue
        providers[name] = LLMProvider(
            name=name,
            type=str(cfg.get("type", "")),
            model=str(cfg.get("model", "")),
            extras={k: v for k, v in cfg.items() if k not in {"type", "model"}},
        )
    routing_raw = block.get("routing", {}) or {}
    routing = LLMRouting(
        default=str(routing_raw.get("default", "")),
        tasks=dict(routing_raw.get("tasks", {}) or {}),
        agents={str(k): str(v) for k, v in (routing_raw.get("agents", {}) or {}).items()},
    )
    return LLMConfig(providers=providers, routing=routing)


def _parse_step_minutes(value: Any) -> int | None:
    """Mirror ``generative_city_sim._parse_step_minutes`` without importing it."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip().lower()
    if not text:
        return None
    import re

    match = re.match(r"^(\d+)\s*(m|min|mins|minute|minutes|h|hour|hours)?$", text)
    if not match:
        return None
    amount = int(match.group(1))
    unit = match.group(2)
    if not unit or unit.startswith("m"):
        return amount
    if unit.startswith("h"):
        return amount * 60
    return amount


def from_legacy(raw: Mapping[str, Any]) -> SimulationConfig:
    """Build a :class:`SimulationConfig` from the legacy ``CONFIG`` dict."""
    return SimulationConfig(
        agent_ids=tuple(_safe_int_list(raw.get("agent_ids", []))),
        sim_days=_safe_int(raw.get("sim_days", 30), 30),
        seconds_per_day=_safe_int(raw.get("seconds_per_day", 10), 10),
        simulate_realtime=_safe_bool(raw.get("simulate_realtime", False)),
        time_step_minutes=_parse_step_minutes(raw.get("time_step_minutes")),
        time_grid_snap=_safe_bool(raw.get("time_grid_snap", False)),
        stateful=_safe_bool(raw.get("stateful", True), True),
        print_agent_profile=_safe_bool(raw.get("print_agent_profile", False)),
        background=str(raw.get("background", "")),
        memory_model_version=_safe_int(raw.get("memory_model_version", 1), 1),
        require_clean_reset_on_memory_model_change=_safe_bool(
            raw.get("require_clean_reset_on_memory_model_change", False)
        ),
        paths=_build_paths(raw),
        llm=_build_llm(raw),
        raw=dict(raw),
    )


def load_simulation_config() -> SimulationConfig:
    """Load the active :class:`SimulationConfig` from :mod:`config`.

    Lazily imports :mod:`config` so this module is import-safe in unit
    tests that stub the legacy module.
    """
    from gaworld.settings import CONFIG  # local import to avoid circular dependency

    return from_legacy(CONFIG)


__all__ = [
    "LLMConfig",
    "LLMProvider",
    "LLMRouting",
    "PathsConfig",
    "SimulationConfig",
    "from_legacy",
    "load_simulation_config",
]
