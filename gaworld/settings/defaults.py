"""Assembly point for all default configuration fragments."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .behavior import human_realism_settings, intervention_settings, news_settings
from .economy import economy_settings
from .environment import environment_settings
from .family import family_settings
from .integrations import integration_settings
from .llm import llm_settings
from .personality import personality_settings
from .runtime import simulation_settings


def build_default_config() -> dict[str, Any]:
    """Build a fresh default config dict from focused fragments."""
    config: dict[str, Any] = {}
    for fragment in (
        llm_settings(),
        simulation_settings(),
        environment_settings(),
        news_settings(),
        intervention_settings(),
        human_realism_settings(),
        economy_settings(),
        family_settings(),
        personality_settings(),
        integration_settings(),
    ):
        config.update(fragment)
    return deepcopy(config)
