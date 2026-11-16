"""
Scenario helper functions for parameter extraction.

Provides utilities for extracting action configurations and resource names
from scenario parameters, handling custom naming and descriptions.

Contains: get_action_config, get_resource_name
"""

import unicodedata
from typing import Dict, Any


def _clean_label(value: str) -> str:
    """Remove invisible format characters and surrounding whitespace."""
    return "".join(
        character
        for character in value
        if unicodedata.category(character) != "Cf"
    ).strip()


def get_action_config(scenario_params: Dict[str, Any], action_number: int) -> Dict[str, str]:
    """Extract action name and description from scenario params.

    Args:
        scenario_params: Parameters dict with action_1_name, action_1_description, etc.
        action_number: 1 or 2 for the action index

    Returns:
        dict with 'name' and 'description' keys
    """
    name = scenario_params.get(f"action_{action_number}_name") or f"Action {action_number}"
    description = scenario_params.get(f"action_{action_number}_description") or ""
    return {"name": name, "description": description}


def get_resource_name(scenario_params: Dict[str, Any]) -> str:
    """Extract resource name, handling 'Custom' -> resource_name_custom mapping.

    Args:
        scenario_params: Parameters dict with resource_name, resource_name_custom

    Returns:
        Resource name string (e.g., "Tokens", "Money", "Carbon Credits")
    """
    resource_name = scenario_params.get("resource_name", "Tokens")
    if isinstance(resource_name, str):
        resource_name = _clean_label(resource_name)
    if not resource_name:
        return "Tokens"
    if resource_name == "Custom":
        custom_name = scenario_params.get("resource_name_custom", "Tokens")
        if isinstance(custom_name, str):
            custom_name = _clean_label(custom_name)
        return custom_name or "Tokens"
    return resource_name