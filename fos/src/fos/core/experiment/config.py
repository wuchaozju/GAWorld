"""
Experiment configuration dataclass.

Defines the structure for experiment scenarios including agents,
actions with descriptions, scenario parameters, locale, and
shared global knowledge for RAG retrieval.

Contains: ExperimentConfig
"""

from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass
class ExperimentConfig:
    """Configuration for an experiment scenario.

    Attributes:
        agents: List of agent definitions with name, properties, role_prompt, llm_config
        actions: List of action definitions with name and description
        parameters: Scenario parameters (payoff values, etc.)
        description: Human-readable scenario description
        scenario_id: Identifier for the scenario type
        round_visibility: How agents see each other's choices
        locale: Language code for prompt translation (en/zh)
    """

    agents: list[dict[str, Any]]
    actions: list[dict[str, Any]]
    parameters: dict[str, Any] = field(default_factory=dict)
    state_schema: dict[str, Any] = field(default_factory=dict)
    description: str = ""
    scenario_id: str = "custom"
    round_visibility: str = "simultaneous"  # simultaneous | sequential | paired
    social_network: dict = field(default_factory=dict)  # Graph topology: {"edges": [["Alice","Bob"], ...]}
    locale: str = "en"  # Language for prompts and generated text
    global_knowledge: Dict[str, Any] = field(default_factory=dict)
