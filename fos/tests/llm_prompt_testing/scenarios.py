"""
Scenario configurations for LLM prompt testing.

Supports both XML and JSON formats based on model capabilities.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any

# Use JSON for action output (default can be overridden with --use-json flag)
USE_JSON_FOR_ACTIONS = True


@dataclass
class Action:
    """An action that an agent can take."""

    name: str
    description: str
    parameters: Dict[str, str] = field(default_factory=dict)

    def to_xml(self) -> str:
        """Convert action to XML-like format (for compatibility)."""
        if self.parameters:
            params = " ".join(f'{k}="{v}"' for k, v in self.parameters.items())
            return f'<{self.name}{params} />'
        return f'<{self.name} />'

    def to_json(self) -> str:
        """Convert action to JSON format (for new models)."""
        return f'{{"action": "{self.name}", "parameters": {self.parameters}}}'


# ============================================================================
# Scenario Configurations
# ============================================================================

@dataclass
class ScenarioConfig:
    """Configuration for a single test scenario."""

    id: str
    name: str
    description: str
    pattern: str
    actions: List[Action] = field(default_factory=list)
    config: Dict[str, Any] = field(default_factory=dict)
    system_instructions: str = ""
    json_format: bool = False  # Use JSON for actions
    agent_role: str = "Agent"  # Default agent role
    personality: str = ""  # Optional personality trait
    goals: List[str] = field(default_factory=list)  # Optional goals

    def to_prompt(self) -> str:
        """Generate system prompt for this scenario."""
        parts = [f"You are {self.agent_role} - {self.name}"]

        if self.personality:
            parts.append(f"Personality: {self.personality}")

        if self.goals:
            parts.append("Goals:")
            for goal in self.goals:
                parts.append(f"- {goal}")

        if self.config:
            parts.append("Configuration:")
            for key, value in self.config.items():
                parts.append(f"  - {key}: {value}")

        if self.system_instructions:
            parts.append(f"\n{self.system_instructions}")

        # Action format instruction
        if self.json_format:
            parts.append("""
Output Format:
Respond ONLY with valid JSON like: {"action": "action_name", "parameters": {...}}

You MUST output ONLY the JSON object. No other text.
""")
        else:
            # XML format instruction
            parts.append("""
Output Format (follow exactly):
--- Thoughts ---
[brief thought]

---- Plan ---
Goals: [your goals]
Milestones: [completed ✓, pending →]

---- Action ---
<Action name="action_name">
  parameter="value"
</Action>""")

        return "\n".join(parts)


# ============================================================================
# Strategic Decisions
# ============================================================================

strategic_prisoners_dilemma = Action(
    name="cooperate",
    description="Remain silent - cooperate with your partner",
)

strategic_defect = Action(
    name="defect",
    description="Betray your partner - testify against them",
)

strategic_scenarios_dict: Dict[str, Dict[str, Action]] = {
    "prisoners_dilemma": {
        "id": "prisoners_dilemma",
        "name": "Prisoner's Dilemma",
        "description": "Two suspects are arrested and held separately. Each must decide whether to betray the other or remain silent.",
        "pattern": "Strategic Decisions",
        "actions": [strategic_prisoners_dilemma, strategic_defect],
        "config": {"payoff_mode": "pairwise"},
        "system_instructions": "Choose your action carefully based on what you think your partner will do.",
        "json_format": False,  # Use XML for action output
    },
    "stag_hunt": {
        "id": "stag_hunt",
        "name": "Stag Hunt",
        "description": "Hunters must all choose stag (high reward) or hare (safe but low reward). Stag requires everyone to cooperate.",
        "pattern": "Strategic Decisions",
        "actions": [Action("stag", "Hunt stag"), Action("hare", "Hunt hare")],
        "config": {"payoff_mode": "threshold", "threshold": 10},
        "system_instructions": "You are in a stag hunt. Everyone choosing stag creates the best outcome for the group.",
        "json_format": False,
    },
    "minimum_effort": {
        "id": "minimum_effort",
        "name": "Minimum Effort Game",
        "description": "Team members choose effort levels. Payoff depends on the minimum effort chosen by anyone in the group.",
        "pattern": "Strategic Decisions",
        "actions": [
            Action("effort_1", "Choose effort level 1 (minimum)"),
            Action("effort_2", "Choose effort level 2"),
            Action("effort_3", "Choose effort level 3"),
            Action("effort_4", "Choose effort level 4"),
            Action("effort_5", "Choose effort level 5"),
            Action("effort_6", "Choose effort level 6"),
            Action("effort_7", "Choose effort level 7 (maximum)"),
        ],
        "config": {"payoff_mode": "minimum"},
        "system_instructions": "Choose your effort level carefully. Higher effort = higher potential reward, but requires everyone to coordinate.",
        "json_format": False,  # Use XML for action output
    },
}


def get_strategic_scenario(scenario_id: str) -> "strategic_scenarios_dict":
    """Get a strategic decisions scenario configuration."""
    return strategic_scenarios_dict.get(scenario_id)


# ============================================================================
# Opinions & Influence
# ============================================================================

opinion_polarization = Action(
    name="polarize_opinion",
    description="Move your opinion toward extreme",
)

opinion_moderate = Action(
    name="moderate_opinion",
    description="Move your opinion toward center",
)

opinions_scenarios_dict: Dict[str, Dict[str, Action]] = {
    "opinion_polarization": {
        "id": "opinion_polarization",
        "name": "Opinion Polarization",
        "description": "Agents discuss a controversial policy. Watch how opinions shift and polarize.",
        "pattern": "Opinions & Influence",
        "actions": [opinion_polarization, opinion_moderate],
        "config": {"confidence_threshold": 30},
        "system_instructions": "You have an opinion. If someone's opinion differs from yours by more than {threshold}, consider it carefully. Otherwise, move toward it slightly.",
        "json_format": False,  # Use XML for action output
    },
    "consensus_game": {
        "id": "consensus_game",
        "name": "Consensus Game",
        "description": "Agents discuss and update opinions toward group average.",
        "pattern": "Opinions & Influence",
        "actions": [Action("consensus", "Express opinion"), Action("listen", "Listen to others")],
        "config": {"mixing_rate": 0.5},
        "system_instructions": "Share your opinion openly. Listen to others and update toward the average opinion of the group.",
        "json_format": False,  # Use XML for action output
    },
}


def get_opinions_scenario(scenario_id: str) -> "opinions_scenarios_dict":
    """Get an opinions & influence scenario configuration."""
    return opinions_scenarios_dict.get(scenario_id)


# ============================================================================
# Network & Spread
# ============================================================================

information_cascade = Action(
    name="participate",
    description="Participate after seeing previous choices",
)

opinion_spread = Action(
    name="spread_opinion",
    description="Share your opinion with your network",
)

network_scenarios_dict: Dict[str, Dict[str, Action]] = {
    "information_cascade": {
        "id": "information_cascade",
        "name": "Information Cascade",
        "description": "Participants guess the state of an urn. Previous choices are visible.",
        "pattern": "Network & Spread",
        "actions": [information_cascade, Action("observe_history", "Observe previous choices"), Action("choose_privately", "Choose privately")],
        "config": {"turn_order": "sequential"},
        "system_instructions": "You will observe all previous participants' choices before you. Then guess the hidden state. Your goal is to be correct more often than wrong.",
        "json_format": True,
    },
}


def get_network_scenario(scenario_id: str) -> "network_scenarios_dict":
    """Get a network & spread scenario configuration."""
    return network_scenarios_dict.get(scenario_id, information_cascade)


# ============================================================================
# Markets & Exchange
# ============================================================================

basic_trading = Action(
    name="trade",
    description="Exchange one resource for another",
)

double_auction = Action(
    name="bid",
    description="Place a bid to buy or ask to buy",
)

markets_scenarios_dict: Dict[str, Dict[str, Action]] = {
    "basic_trading": {
        "id": "basic_trading",
        "name": "Basic Trading",
        "description": "Simple resource exchange between agents.",
        "pattern": "Markets & Exchange",
        "actions": [basic_trading],
        "config": {},
        "system_instructions": "Trade with others to improve your resource position.",
        "json_format": True,
    },
}


def get_markets_scenario(scenario_id: str) -> "markets_scenarios_dict":
    """Get a markets & exchange scenario configuration."""
    return markets_scenarios_dict.get(scenario_id, basic_trading)


# ============================================================================
# Spatial & Movement
# ============================================================================

spatial_cooperation = Action(
    name="cooperate_spatial",
    description="Cooperate with your neighbors in the spatial environment",
)

segregation = Action(
    name="move",
    description="Move to a location with more similar neighbors",
)

spatial_scenarios_dict: Dict[str, Dict[str, Action]] = {
    "spatial_cooperation": {
        "id": "spatial_cooperation",
        "name": "Spatial Cooperation",
        "description": "Agents arranged on a grid. Cooperation can spread through neighbor imitation.",
        "pattern": "Spatial & Movement",
        "actions": [spatial_cooperation, Action("move", "Move to new location"), Action("imitate_best_neighbor", "Imitate best neighbor")],
        "config": {},
        "system_instructions": "Choose your action considering your neighbors' strategies.",
        "json_format": True,
    },
    "segregation": {
        "id": "segregation",
        "name": "Segregation Model",
        "description": "Agents have location preferences. Move if too many neighbors are different from you.",
        "pattern": "Spatial & Movement",
        "actions": [segregation, Action("stay", "Stay in current location"), Action("check_neighbors", "Check neighbors")],
        "config": {},
        "system_instructions": "Check how many neighbors around you are like you. If too many are different, you may want to move.",
        "json_format": True,
    },
}


def get_spatial_scenario(scenario_id: str) -> "spatial_scenarios_dict":
    """Get a spatial & movement scenario configuration."""
    return spatial_scenarios_dict.get(scenario_id, spatial_cooperation)


# ============================================================================
# Open Conversation
# ============================================================================

focus_group = Action(
    name="participate_discussion",
    description="Participate in the group discussion",
)

conversation_scenarios_dict: Dict[str, Dict[str, Action]] = {
    "focus_group": {
        "id": "focus_group",
        "name": "Focus Group",
        "description": "Structured discussion with turn-taking.",
        "pattern": "Open Conversation",
        "actions": [focus_group],
        "config": {},
        "system_instructions": "You are in a focus group. Follow the discussion order and participate when it's your turn.",
        "json_format": True,
    },
}


def get_conversation_scenario(scenario_id: str) -> "conversation_scenarios_dict":
    """Get an open conversation scenario configuration."""
    return conversation_scenarios_dict.get(scenario_id, focus_group)


# ============================================================================
# All Scenarios
# ============================================================================

ALL_SCENARIOS: Dict[str, Dict[str, Action]] = {
    "Strategic Decisions": strategic_scenarios_dict,
    "Opinions & Influence": opinions_scenarios_dict,
    "Network & Spread": network_scenarios_dict,
    "Markets & Exchange": markets_scenarios_dict,
    "Spatial & Movement": spatial_scenarios_dict,
    "Open Conversation": conversation_scenarios_dict,
}


def get_scenario(scenario_id: str):
    """Get any scenario configuration by ID across all patterns."""
    for pattern_scenarios in ALL_SCENARIOS.values():
        if scenario_id in pattern_scenarios:
            return pattern_scenarios[scenario_id]
    return None


def get_scenarios_for_pattern(pattern: str) -> List["ScenarioConfig"]:
    """
    Get all scenario configurations for a given pattern.

    Args:
        pattern: The interaction pattern name

    Returns:
        List of ScenarioConfig objects for the pattern
    """
    scenarios = []

    # Find the scenario dict for this pattern
    pattern_dict = ALL_SCENARIOS.get(pattern, {})

    if pattern_dict:
        for scenario_id, scenario_data in pattern_dict.items():
            if isinstance(scenario_data, dict):
                # Convert dict to ScenarioConfig
                scenarios.append(ScenarioConfig(
                    id=scenario_data.get("id", scenario_id),
                    name=scenario_data.get("name", scenario_id),
                    description=scenario_data.get("description", ""),
                    pattern=scenario_data.get("pattern", pattern),
                    actions=scenario_data.get("actions", []),
                    config=scenario_data.get("config", {}),
                    system_instructions=scenario_data.get("system_instructions", ""),
                    json_format=scenario_data.get("json_format", False),
                ))

    return scenarios
