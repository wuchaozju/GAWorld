"""
Statistics tracking for contagion state counts and transition events.

This module provides classes for tracking agent contagion state distributions
and logging state transition events. Statistics are emitted to the frontend
via WebSocket for real-time visualization.

Contains: ContagionStatistics, TransitionEvent
"""
from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass
class TransitionEvent:
    """
    Record of a contagion state transition for an agent.

    Captures the complete context of when and how an agent changed
    contagion states, enabling replay and analysis of spread dynamics.

    Attributes:
        turn: Simulation turn when the transition occurred
        agent_id: Name/ID of the agent whose state changed
        from_state: Previous contagion state (e.g., "susceptible")
        to_state: New contagion state (e.g., "infected")
        trigger_type: What caused the transition ("proximity", "action", "decay")
        source_agent_id: Optional ID of agent that caused transmission (for proximity/action)
    """

    turn: int
    agent_id: str
    from_state: str
    to_state: str
    trigger_type: str
    source_agent_id: Optional[str] = None

    def to_dict(self) -> dict:
        """
        Convert the transition event to a serializable dictionary.

        Returns:
            Dict with all event fields for JSON serialization.
            source_agent_id is only included when not None.
        """
        result = {
            "turn": self.turn,
            "agent_id": self.agent_id,
            "from_state": self.from_state,
            "to_state": self.to_state,
            "trigger_type": self.trigger_type,
        }
        if self.source_agent_id is not None:
            result["source_agent_id"] = self.source_agent_id
        return result


class ContagionStatistics:
    """
    Tracker for contagion state distribution and transition events.

    Maintains counts of agents in each state and a log of all transitions
    that occurred during simulation. Designed to be queried by the scene
    and emitted to the frontend via WebSocket events.

    Attributes:
        counts: Dict mapping state value -> agent count
        events: List of all transition events recorded
    """

    def __init__(self):
        """Initialize empty statistics tracking."""
        self.counts: Dict[str, int] = {}
        self.events: List[TransitionEvent] = []

    def update(self, agents: dict) -> None:
        """
        Recount agents per contagion state.

        Args:
            agents: Dict of agent_name -> Agent objects to count
        """
        self.counts = {}
        for agent in agents.values():
            state = agent.properties.get("contagion_state", "unknown")
            self.counts[state] = self.counts.get(state, 0) + 1

    def record_transition(self, event: TransitionEvent) -> None:
        """
        Record a state transition event.

        Args:
            event: TransitionEvent to append to the events log
        """
        self.events.append(event)

    def to_dict(self) -> dict:
        """
        Convert statistics to a serializable dictionary.

        Returns:
            Dict with counts and serialized events for JSON transmission.
        """
        return {
            "counts": self.counts,
            "events": [e.to_dict() for e in self.events],
        }

    def get_agent_states(self, agents: dict) -> Dict[str, str]:
        """
        Get a mapping of agent names to their current states.

        Useful for frontend display of which agent has which state.

        Args:
            agents: Dict of agent_name -> Agent objects

        Returns:
            Dict mapping agent_name -> state string
        """
        result = {}
        for agent in agents.values():
            state = agent.properties.get("contagion_state", "unknown")
            result[agent.name] = state
        return result
