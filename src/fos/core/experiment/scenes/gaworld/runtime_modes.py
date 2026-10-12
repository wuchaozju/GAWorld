"""This file translates beginner city-system choices into GAWorld runtime settings.

- merge_nested_overrides combines nested settings without losing earlier values.
- has_explicit_city_system_mode checks whether a saved parameter was set directly.
- build_information_overrides maps information flow choices into GAWorld flags.
- build_daily_life_overrides maps daily-life choices into GAWorld routine settings.
- build_people_overrides maps people choices into GAWorld behavior settings.
- build_memory_overrides maps memory choices into GAWorld memory settings.
"""

from __future__ import annotations

from typing import Any


def merge_nested_overrides(base: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    """Combines nested dictionaries so later settings can override starter settings."""
    merged = dict(base)
    for key, value in updates.items():
        current = merged.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            merged[key] = merge_nested_overrides(current, value)
            continue
        merged[key] = value
    return merged


def has_explicit_city_system_mode(parameters: dict[str, Any], key: str) -> bool:
    """Checks whether a city-system mode was saved directly in the scenario parameters."""
    raw_value = parameters.get(key)
    return isinstance(raw_value, str) and raw_value.strip() != ""


def build_information_overrides(mode: str) -> dict[str, Any]:
    """Turns the information control into news and outside-information settings."""
    if mode == "off":
        return {
            "external_rag": {"bootstrap": {"enabled": False}},
            "news": {"enabled": False, "info_seek": {"enabled": False}},
        }
    if mode == "active_flow":
        return {
            "external_rag": {"bootstrap": {"enabled": True}},
            "news": {"enabled": True, "info_seek": {"enabled": True}},
        }
    return {
        "external_rag": {"bootstrap": {"enabled": False}},
        "news": {"enabled": True, "info_seek": {"enabled": False}},
    }


def build_daily_life_overrides(mode: str) -> dict[str, Any]:
    """Turns the daily-life control into routine and planning settings."""
    if mode == "stable_routines":
        return {
            "routine_change": {"enabled": False},
            "spontaneity": {"enabled": False},
            "daily_planning": {
                "flexible": {
                    "enabled": True,
                    "min_items": 3,
                    "max_items": 4,
                    "max_time_shift_minutes": 60,
                    "min_gap_minutes": 60,
                    "allow_insertions": False,
                }
            },
        }
    if mode == "flexible_daily_life":
        return {
            "routine_change": {"enabled": True},
            "spontaneity": {"enabled": True},
            "daily_planning": {
                "flexible": {
                    "enabled": True,
                    "min_items": 4,
                    "max_items": 7,
                    "max_time_shift_minutes": 120,
                    "min_gap_minutes": 30,
                    "allow_insertions": True,
                }
            },
        }
    return {
        "routine_change": {"enabled": True},
        "spontaneity": {"enabled": False},
        "daily_planning": {
            "flexible": {
                "enabled": True,
                "min_items": 3,
                "max_items": 5,
                "max_time_shift_minutes": 90,
                "min_gap_minutes": 45,
                "allow_insertions": False,
            }
        },
    }


def build_people_overrides(mode: str) -> dict[str, Any]:
    """Turns the people control into behavior and realism settings."""
    if mode == "simple_behavior":
        return {
            "interests": {"enabled": False},
            "dynamic_behavior": {"enabled": False},
            "human_realism": {"enabled": False},
        }
    if mode == "rich_human_behavior":
        return {
            "interests": {"enabled": True},
            "dynamic_behavior": {"enabled": True},
            "human_realism": {"enabled": True},
        }
    return {
        "interests": {"enabled": True},
        "dynamic_behavior": {"enabled": True},
        "human_realism": {"enabled": False},
    }


def build_memory_overrides(mode: str) -> dict[str, Any]:
    """Turns the memory control into retrieval, memory, and reflection settings."""
    if mode == "in_the_moment":
        return {
            "vector_db_top_k": 1,
            "memory": {
                "consolidation": {"enabled": False},
                "decay": {"enabled": False},
                "skill_consolidation": {"enabled": False},
            },
            "fos_fast_mode": {
                "skip_daily_summary": True,
                "skip_daily_diary": True,
            },
        }
    if mode == "rich_memory":
        return {
            "vector_db_top_k": 5,
            "memory": {
                "consolidation": {"enabled": True},
                "decay": {"enabled": True},
                "skill_consolidation": {"enabled": True},
            },
            "fos_fast_mode": {
                "skip_daily_summary": False,
                "skip_daily_diary": False,
            },
        }
    return {
        "vector_db_top_k": 3,
        "memory": {
            "consolidation": {"enabled": True},
            "decay": {"enabled": False},
            "skill_consolidation": {"enabled": True},
        },
        "fos_fast_mode": {
            "skip_daily_summary": False,
            "skip_daily_diary": False,
        },
    }
