"""
Experiment State Management.

Provides ExperimentState and AgentState classes for tracking all
experiment data: agent properties, positions, resources, scores,
and scenario-specific extensions.

Contains: ExperimentState, AgentState
"""
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class AgentState:
    """Per-agent state tracking.

    Attributes:
        score: Cumulative score/points
        position: Grid position as (x, y) tuple, None if non-spatial
        resources: Resource amounts by type {"tokens": 10}
        properties: Scenario-specific agent data
    """
    score: int = 0
    position: Optional[tuple[int, int]] = None
    resources: dict[str, int] = field(default_factory=dict)
    properties: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        # Convert list to tuple for position
        if isinstance(self.position, list):
            self.position = tuple(self.position)

    def to_dict(self) -> dict:
        return {
            "score": self.score,
            "position": list(self.position) if self.position else None,
            "resources": self.resources,
            "properties": self.properties,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AgentState":
        return cls(
            score=data.get("score", 0),
            position=tuple(data["position"]) if data.get("position") else None,
            resources=data.get("resources", {}),
            properties=data.get("properties", {}),
        )


@dataclass
class ExperimentState:
    """Unified state for all experiment types.

    Core state (always present):
        - round: Current round number
        - agents: Per-agent state by name
        - history: Round-by-round action records

    Extensions (scenario-specific):
        - pools: Contribution pools for public goods
        - colors: Color assignments for graph coloring
        - thresholds: Success thresholds
        - etc.
    """
    round: int = 0
    agents: dict[str, AgentState] = field(default_factory=dict)
    history: list[dict[str, Any]] = field(default_factory=list)
    extensions: dict[str, Any] = field(default_factory=dict)

    def get_agent_position(self, agent_name: str) -> Optional[tuple[int, int]]:
        """Get agent's grid position, or None if not set."""
        agent = self.agents.get(agent_name)
        return agent.position if agent else None

    def update_agent_position(self, agent_name: str, position: tuple[int, int]) -> None:
        """Update agent's grid position."""
        if agent_name not in self.agents:
            self.agents[agent_name] = AgentState()
        self.agents[agent_name].position = position

    def update_agent_score(self, agent_name: str, delta: int) -> None:
        """Add delta to agent's score."""
        if agent_name not in self.agents:
            self.agents[agent_name] = AgentState()
        self.agents[agent_name].score += delta

    def update_agent_resource(self, agent_name: str, resource_type: str, amount: int) -> None:
        """Set agent's resource amount."""
        if agent_name not in self.agents:
            self.agents[agent_name] = AgentState()
        self.agents[agent_name].resources[resource_type] = amount

    def add_to_pool(self, pool_name: str, amount: int) -> None:
        """Add amount to a contribution pool."""
        if "pools" not in self.extensions:
            self.extensions["pools"] = {}
        if pool_name not in self.extensions["pools"]:
            self.extensions["pools"][pool_name] = 0
        self.extensions["pools"][pool_name] += amount

    def get_pool(self, pool_name: str) -> int:
        """Get current pool amount."""
        return self.extensions.get("pools", {}).get(pool_name, 0)

    def to_dict(self) -> dict:
        return {
            "round": self.round,
            "agents": {name: agent.to_dict() for name, agent in self.agents.items()},
            "history": self.history,
            "extensions": self.extensions,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ExperimentState":
        agents = {
            name: AgentState.from_dict(agent_data)
            for name, agent_data in data.get("agents", {}).items()
        }
        return cls(
            round=data.get("round", 0),
            agents=agents,
            history=deepcopy(data.get("history", [])),
            extensions=deepcopy(data.get("extensions", {})),
        )
