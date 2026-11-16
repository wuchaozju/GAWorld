"""
Simulation results formatting utilities.

Provides helper functions for formatting simulation results with custom
action and resource names based on scenario configuration.

Contains: format_round_results, format_public_goods_results
"""

from fos.core.scenarios.helpers import get_action_config, get_resource_name
from fos.i18n import T


def format_round_results(
    round_num: int, action_counts: dict, scenario_params: dict, language: str = "en"
) -> dict:
    """Format round results with custom action names.

    Args:
        round_num: Round number
        action_counts: Dict mapping actions to counts
        scenario_params: Scenario parameters for name resolution
        language: Language code for i18n

    Returns:
        Formatted results dict with custom action names
    """
    action_1 = get_action_config(scenario_params, 1)
    action_2 = get_action_config(scenario_params, 2)

    # Map original actions to custom names
    action_name_map = {
        "Opera": action_1["name"],
        "Stag": action_1["name"],
        "Football": action_2["name"],
        "Hare": action_2["name"],
    }

    formatted_counts = {}
    for action, count in action_counts.items():
        display_name = action_name_map.get(action, action)
        formatted_counts[display_name] = count

    return {
        "title": T("simulation.results.round_title", round=round_num, language=language),
        "counts": formatted_counts,
        "agents_chose_text": T(
            "simulation.results.agents_chose",
            count=sum(action_counts.values()),
            language=language,
        ),
    }


def format_public_goods_results(
    round_num: int,
    total_contributed: int,
    pool_after_multiplier: float,
    per_agent_share: float,
    scenario_params: dict,
    language: str = "en",
) -> dict:
    """Format Public Goods round results.

    Args:
        round_num: Round number
        total_contributed: Total amount contributed
        pool_after_multiplier: Pool after multiplier applied
        per_agent_share: Amount each agent receives
        scenario_params: Scenario parameters
        language: Language code for i18n

    Returns:
        Formatted results dict
    """
    resource = get_resource_name(scenario_params)
    multiplier = scenario_params.get("multiplier", 1.5)

    return {
        "title": T("simulation.results.round_title", round=round_num, language=language),
        "total_contributed": T(
            "simulation.results.total_contributed",
            language=language,
        ),
        "total_value": f"{total_contributed} {resource.lower()}",
        "pool_after_multiplier": T(
            "simulation.results.pool_after_multiplier",
            multiplier=multiplier,
            language=language,
        ),
        "pool_value": f"{pool_after_multiplier:.1f} {resource.lower()}",
        "per_agent_share": T("simulation.results.per_agent_share", language=language),
        "share_value": f"{per_agent_share:.1f} {resource.lower()}",
    }
