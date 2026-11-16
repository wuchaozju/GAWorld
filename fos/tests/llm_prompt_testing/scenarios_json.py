"""
Scenario configurations for LLM prompt testing - JSON action format.

Uses JSON format for actions instead of XML to work around model limitations.
"""

from dataclasses import dataclass, field
from typing import Dict


@dataclass
class Action:
    """An action that an agent can take."""

    name: str
    description: str
    parameters: Dict[str, str] = field(default_factory=dict)

    def to_xml(self) -> str:
        """Convert action to XML-like format."""
        if self.parameters:
            params = " ".join(f'{k}="{v}"' for k, v in self.parameters.items())
            return f'<{self.name}{params} />'
        return f'<{self.name} />'


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

strategic_scenarios = {
    "prisoners_dilemma": {
        "id": "prisoners_dilemma",
        "name": "Prisoner's Dilemma",
        "description": "Two suspects are arrested and held separately. Each must decide whether to betray the other or remain silent.",
        "pattern": "Strategic Decisions",
        "actions": [strategic_prisoners_dilemma, strategic_defect],
        "json_format": True,
    },
    "stag_hunt": {
        "id": "stag_hunt",
        "name": "Stag Hunt",
        "description": "Hunters must all choose stag (high reward) or hare (safe but low reward). Stag requires everyone to cooperate.",
        "pattern": "Strategic Decisions",
        "actions": [Action("stag", "Hunt stag"), Action("hare", "Hunt hare")],
        "json_format": True,
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
        "json_format": True,
    },
}


def get_strategic_scenario(scenario_id: str):
    """Get a strategic scenario configuration by ID."""
    return strategic_scenarios.get(scenario_id)


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

opinions_influence_scenarios = {
    "opinion_polarization": {
        "id": "opinion_polarization",
        "name": "Opinion Polarization",
        "description": "Agents discuss a controversial policy. Watch how opinions shift and polarize.",
        "pattern": "Opinions & Influence",
        "actions": [opinion_polarization, opinion_moderate],
        "json_format": True,
    },
    "consensus_game": {
        "id": "consensus_game",
        "name": "consensus",
        "description": "Agents discuss and update opinions toward group average.",
        "pattern": "Opinions & Influence",
        "actions": [Action("consensus", "Express opinion"), Action("listen", "Listen to others")],
        "json_format": True,
    },
}


def get_opinions_scenario(scenario_id: str):
    """Get an opinions & influence scenario configuration by ID."""
    return opinions_influence_scenarios.get(scenario_id, opinion_polarization)


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

network_scenarios = {
    "information_cascade": {
        "id": "information_cascade",
        "name": "Information Cascade",
        "description": "Participants guess the state of an urn. Previous choices are visible.",
        "pattern": "Network & Spread",
        "actions": [information_cascade, Action("observe_history", "Choose privately")],
        "json_format": True,
    },
    "opinion_spread": {
        "id": "opinion_spread",
        "name": "Opinion Spread",
        "description": "Opinions propagate through network connections.",
        "pattern": "Network & Spread",
        "actions": [opinion_spread],
        "json_format": True,
    },
}


def get_network_scenario(scenario_id: str):
    """Get a network & spread scenario configuration by ID."""
    return network_scenarios.get(scenario_id, information_cascade)


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


markets_scenarios = {
    "basic_trading": {
        "id": "basic_trading",
        "name": "Basic Trading",
        "description": "Simple resource exchange between agents.",
        "pattern": "Markets & Exchange",
        "actions": [basic_trading],
        "json_format": True,
    },
}


def get_markets_scenario(scenario_id: str):
    """Get a markets & exchange scenario configuration by ID."""
    return markets_scenarios.get(scenario_id, basic_trading)


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


spatial_scenarios = {
    "spatial_cooperation": {
        "id": "spatial_cooperation",
        "name": "Spatial Cooperation",
        "description": "Agents arranged on a grid. Cooperation can spread through neighbor imitation.",
        "pattern": "Spatial & Movement",
        "actions": [spatial_cooperation, Action("move", "Move to new location"), Action("imitate_best_neighbor", "Imitate best neighbor")],
        "json_format": True,
    },
    "segregation": {
        "id": "segregation",
        "name": "Segregation Model",
        "description": "Agents have location preferences. Move if too many neighbors are different from you.",
        "pattern": "Spatial & Movement",
        "actions": [segregation, Action("stay", "Stay in current location"), Action("check_neighbors", "Check neighbors")],
        "json_format": True,
    },
}


def get_spatial_scenario(scenario_id: str):
    """Get a spatial & movement scenario configuration by ID."""
    return spatial_scenarios.get(scenario_id, spatial_cooperation)


# ============================================================================
# Open Conversation
# ============================================================================

focus_group = Action(
    name="participate_discussion",
    description="Participate in the group discussion",
)


conversation_scenarios = {
    "focus_group": {
        "id": "focus_group",
        "name": "Focus Group",
        "description": "Structured discussion with turn-taking.",
        "pattern": "Open Conversation",
        "actions": [focus_group],
        "json_format": True,
    },
}


def get_conversation_scenario(scenario_id: str):
    """Get an open conversation scenario configuration by ID."""
    return conversation_scenarios.get(scenario_id, focus_group)


# ============================================================================
# All Scenarios
# ============================================================================

ALL_SCENARIOS = {
    "Strategic Decisions": strategic_scenarios,
    "Opinions & Influence": opinions_influence_scenarios,
    "Network & Spread": network_scenarios,
    "Markets & Exchange": markets_scenarios,
    "Spatial & Movement": spatial_scenarios,
    "Open Conversation": conversation_scenarios,
}


def get_scenario(scenario_id: str):
    """Get any scenario configuration by ID across all patterns."""
    for pattern_scenarios in ALL_SCENARIOS.values():
        if scenario_id in pattern_scenarios:
            return pattern_scenarios[scenario_id]
    return None
