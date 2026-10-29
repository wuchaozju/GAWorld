"""
Simulation log formatting with i18n support.

Formats log messages for simulation events, using custom action names
and resource names from scenario parameters. Supports English and
Chinese translations.

Contains: format_action_log, format_public_goods_log
"""

from fos.core.scenarios.helpers import get_action_config, get_resource_name
from fos.i18n import T


def format_action_log(agent_name: str, action: str, scenario_params: dict, language: str = "en") -> str:
    """Format an action log message with custom names.

    Args:
        agent_name: Name of the agent
        action: The action taken
        scenario_params: Scenario parameters for name resolution
        language: Language code for i18n

    Returns:
        Formatted log message
    """
    # For matrix games, resolve the action name
    if action in ["Opera", "Football", "Stag", "Hare"]:
        # Determine which action index based on original name
        action_1 = get_action_config(scenario_params, 1)
        action_2 = get_action_config(scenario_params, 2)

        # Map original to custom
        action_name_map = {
            "Opera": action_1["name"],
            "Stag": action_1["name"],
            "Football": action_2["name"],
            "Hare": action_2["name"],
        }
        display_action = action_name_map.get(action, action)
    else:
        display_action = action

    return T("simulation.log.action_chosen", agent=agent_name, action=display_action, language=language)


def format_public_goods_log(
    agent_name: str, amount: int, scenario_params: dict, language: str = "en"
) -> str:
    """Format a Public Goods contribution log message.

    Args:
        agent_name: Name of the agent
        amount: Amount contributed
        scenario_params: Scenario parameters
        language: Language code for i18n

    Returns:
        Formatted log message
    """
    resource = get_resource_name(scenario_params)
    action = scenario_params.get("action_name", "Contribute")

    return T(
        "simulation.log.public_goods_contribution",
        agent=agent_name,
        action=action.lower(),
        amount=amount,
        resource=resource.lower(),
        language=language,
    )
