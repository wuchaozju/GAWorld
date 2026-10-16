"""Holiday / vacation mode — drop the routine, do something new for K days.

This package is the K3-style plugin surface for the holiday feature:
``service`` is pure logic (purely testable, no LLM, no IO), ``plugin`` is
the kernel hook layer that hands the routine off to the service for the
duration of a window, and ``DEFAULT_CONFIG`` plus ``validate_config`` are
the load-time + runtime-validation surface mirrored off the existing
``gaworld.policy`` pattern.
"""

from __future__ import annotations

from typing import Any


DEFAULT_CONFIG = {
    "enabled": True,
    # Default per-day freedom bank — when the user opens K days without a
    # custom plan, the service picks one of these per time-of-day band.
    "default_days": 7,
    "max_days": 365,
    "min_days": 1,
    # Output of the holiday log lives next to the other per-plugin files
    # so the panel's "where is it written?" rule stays simple.
    "output_dir": "output/holiday",
    # Daily narrative prompt budget. The LLM sees the same persona inputs
    # it would see on a routine day; this only changes the wrapper question
    # so the "做全新的、自由的安排" promise is preserved without ballooning
    # the existing action-prompt budget.
    "plan_prompt_budget_chars": 240,
}


def _deep_merge(base, override):
    merged = dict(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def normalize_config(config=None):
    return _deep_merge(DEFAULT_CONFIG, config if isinstance(config, dict) else {})


def validate_config(config) -> None:
    """Fail fast at runtime-config validation if a holiday block is malformed.

    Mirrors the light-touch checks ``gaworld.plugins.validate_runtime_config``
    runs for every plugin: bounded numbers, positive integers, no unknown
    keys we'd silently drop.
    """
    cfg = normalize_config(config.get("holiday") if isinstance(config, dict) else None)
    for key in ("max_days", "min_days", "default_days"):
        value = cfg.get(key)
        if not isinstance(value, int) or value <= 0:
            raise ValueError(f"holiday.{key} must be a positive integer; got {value!r}")
    if cfg["min_days"] > cfg["max_days"]:
        raise ValueError(
            f"holiday.min_days ({cfg['min_days']}) cannot exceed "
            f"holiday.max_days ({cfg['max_days']})"
        )
    budget = cfg.get("plan_prompt_budget_chars")
    if not isinstance(budget, int) or not (40 <= budget <= 2000):
        raise ValueError(
            f"holiday.plan_prompt_budget_chars must be between 40 and 2000; got {budget!r}"
        )


__all__ = [
    "DEFAULT_CONFIG",
    "normalize_config",
    "validate_config",
    "service",
    "plugin",
    "Any",
]
