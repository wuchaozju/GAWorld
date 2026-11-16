"""
InformationModel — declarative knowledge rules per scenario.

Each scenario declares what its agents can observe, how many rounds to show,
and how to format context. INFORMATION_MODEL_MAP in registry.py maps scene
keys to InformationModel instances.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, List, Optional
import logging
from fos.i18n import T

if TYPE_CHECKING:
    from fos.core.experiment.state import ExperimentState

logger = logging.getLogger(__name__)


@dataclass
class InformationModel:
    """Declarative specification of agent knowledge rules for a scenario.

    Attributes:
        scope_type: One of "self" | "pair" | "neighborhood" | "all" | "role_based"
        scope_fn: For "neighborhood"/"role_based": (agent, state, all_agents) -> list[str]
                  "neighborhood" without scope_fn falls back to state["social_network"].
        pairing_fn: For "pair": (agents: list[str], round_num: int) -> list[tuple[str,str]]
        recent_window: Rounds of full detail to include (default 3)
        primacy_keep: Always include round 1 even outside recent_window (default True)
        context_budget_chars: Max chars for Section 4 of prompt; 0 = no limit (default 0)
        payoff_template: Template for per-round line. Variables: {N}, {my_action},
                         {partner_action}, {payoff}. Replaces the default "Round N: ..."
                         line entirely — do NOT add a round prefix separately.
        include_scores: Show cumulative score in context (default True)
        show_average_contribution: Show average neighbor contribution instead of individuals (default False)
    """
    scope_type: str
    scope_fn: Optional[Callable] = None
    pairing_fn: Optional[Callable] = None
    recent_window: int = 3
    primacy_keep: bool = True
    context_budget_chars: int = 0
    # Transmit cap: max tokens per speech stored in context_summary (0 = no cap)
    transmit_cap_tokens: int = 500
    # Reduced cap used when re-rendering after a prompt overflow
    recap_tokens: int = 400
    payoff_template: Optional[str] = None
    include_scores: bool = True
    show_average_contribution: bool = False

    def __post_init__(self):
        valid = {"self", "pair", "neighborhood", "all", "role_based"}
        if self.scope_type not in valid:
            raise ValueError(
                T("scope_type must be one of {valid}, got {scope_type}", valid=valid, scope_type=self.scope_type)
            )

    def get_observers(
        self,
        for_agent: str,
        scene_state: dict,
        all_agent_names: List[str],
        round_num: int = 0,
    ) -> List[str]:
        """Return agents who observe for_agent's action this round.

        This list is stored as event.observed_by at write-time. Agent B
        sees an event iff B in event.observed_by at read-time.
        """
        if self.scope_type == "all":
            return list(all_agent_names)

        if self.scope_type == "self":
            return [for_agent]

        if self.scope_type == "pair":
            if self.pairing_fn and round_num and all_agent_names:
                for a, b in self.pairing_fn(all_agent_names, round_num):
                    if a == for_agent:
                        return [for_agent, b]
                    if b == for_agent:
                        return [for_agent, a]
            return [for_agent]

        if self.scope_type in ("neighborhood", "neighbor"):
            if self.scope_fn:
                neighbors = self.scope_fn(for_agent, scene_state, all_agent_names)
            else:
                # Check both "social_network" and "graph" keys for backwards compatibility
                network = scene_state.get("social_network") or scene_state.get("graph", {})
                logger.debug(f"[VISIBILITY] Agent {for_agent}: scene_state keys={list(scene_state.keys())}, network type={type(network).__name__}")
                if isinstance(network, dict):
                    # Check for edge list format: {"edges": [(a, b), ...]}
                    if "edges" in network:
                        edges = network.get("edges", [])
                        neighbors = [b for a, b in edges if a == for_agent] + [a for a, b in edges if b == for_agent]
                        logger.debug(f"[VISIBILITY] Agent {for_agent}: Found {len(edges)} edges, {len(neighbors)} neighbors")
                    else:
                        # Adjacency list format: {"Agent 1": ["Agent 2", "Agent 3"], ...}
                        neighbors = network.get(for_agent, [])
                        logger.debug(f"[VISIBILITY] Agent {for_agent}: Adjacency list format, {len(neighbors)} neighbors")
                else:
                    # Fallback: treat as empty if not a dict
                    logger.warning(f"[VISIBILITY] Agent {for_agent}: Network is not a dict, falling back to no neighbors")
                    neighbors = []
            result = list(set([for_agent] + list(neighbors)))
            logger.debug(f"[VISIBILITY] Agent {for_agent}: Final observers={result}")
            return result

        if self.scope_type == "role_based":
            if self.scope_fn:
                return self.scope_fn(for_agent, scene_state, all_agent_names)
            return [for_agent]

        return list(all_agent_names)  # safe fallback

    def get_visible_contributions(
        self,
        agent_name: str,
        state: "ExperimentState",
        graph: dict,
    ) -> dict[str, int]:
        """Get contributions visible to an agent based on network graph.

        Agents only see contributions from agents they're directly connected
        to in the network. Isolated agents see no contributions from others.

        Args:
            agent_name: Name of the viewing agent
            state: Current experiment state with agent contributions
            graph: Network graph with "edges" list

        Returns:
            Dict mapping neighbor_name -> contribution_amount for all
            agents connected to the viewing agent.

        Example:
            graph = {"edges": [("Alice", "Bob"), ("Bob", "Charlie")]}
            # Alice sees: {"Bob": contribution}
            # Bob sees: {"Alice": contribution, "Charlie": contribution}
            # Charlie sees: {"Bob": contribution}
        """
        edges = graph.get("edges", [])

        # Find neighbors (bidirectional edges)
        neighbors = (
            [b for a, b in edges if a == agent_name] +
            [a for a, b in edges if b == agent_name]
        )

        visible = {}
        for neighbor in neighbors:
            if neighbor in state.agents:
                # Get contribution from agent properties
                contribution = state.agents[neighbor].properties.get("last_contribution", 0)
                visible[neighbor] = contribution

        return visible

    def get_neighbor_average(
        self,
        agent_name: str,
        state: "ExperimentState",
        graph: dict,
    ) -> float | None:
        """Calculate average contribution from neighbors.

        Args:
            agent_name: Name of the viewing agent
            state: Current experiment state with agent contributions
            graph: Network graph with "edges" list

        Returns:
            Average contribution from neighbors, or None if no neighbors
        """
        visible = self.get_visible_contributions(agent_name, state, graph)

        if not visible:
            return None

        contributions = list(visible.values())
        if not contributions:
            return None

        return sum(contributions) / len(contributions)