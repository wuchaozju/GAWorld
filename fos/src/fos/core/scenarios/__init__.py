"""
Scenarios module for FOS (Future of Society).

Provides scenario definitions, action libraries, and utilities for
managing experiment scenarios.

Contains: get_all_scenarios, get_scenario, get_scenario_actions, CATEGORY_ACTION_LIBRARIES
"""

from .actions import CATEGORY_ACTION_LIBRARIES
from .registry import get_all_scenarios, get_scenario, get_scenario_actions

__all__ = [
    'get_all_scenarios',
    'get_scenario',
    'get_scenario_actions',
    'CATEGORY_ACTION_LIBRARIES',
]
