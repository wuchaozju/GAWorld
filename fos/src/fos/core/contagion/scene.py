"""
ContagionScene - Pipeline A scene for SEIR contagion dynamics.

Subclasses ExperimentScene to reuse the LLM prompting and action dispatch
loop while replacing payoff scoring with SEIR state transitions. Agents
spread infection through proximity and social interactions on a grid map,
with configurable transmission rates and recovery via decay rules.

Contains: ContagionScene
"""
import logging
import random
from typing import Dict, List, Tuple

from fos.i18n import T
from fos.core.contagion.states import ContagionState
from fos.core.contagion.rules import StateTransition, check_probability
from fos.core.contagion.statistics import ContagionStatistics, TransitionEvent
from fos.core.experiment.scene import ExperimentScene
from fos.core.experiment.config import ExperimentConfig
from fos.core.experiment.runner import RoundResult
from fos.core.experiment.controller import ActionResult
from fos.core.experiment.game_configs import GameConfig
from fos.core.map.grid import GameMap

logger = logging.getLogger(__name__)


class ContagionScene(ExperimentScene):
    """Pipeline A scene with SEIR contagion state tracking.

    Inherits the ExperimentScene turn loop for LLM prompting and action
    dispatch. Overrides run_round() to apply SEIR transitions after each
    round. Disables the payoff engine via payoff_type="none".

    Attributes:
        game_map: Grid for agent positioning
        rules: List of StateTransition rules defining allowed transitions
        initial_infected_count: Number of agents to start as infected
        _statistics: Internal tracker for state counts and events
    """

    TYPE = "contagion_scene"

    def __init__(
        self,
        name: str,
        initial_event: str,
        game_map: GameMap,
        rules: List[StateTransition],
        initial_infected_count: int = 1,
    ):
        self.game_map = game_map
        self.rules = rules
        self.initial_infected_count = initial_infected_count
        self._statistics = ContagionStatistics()

        # Build transmission parameters from rules for the config
        transmission_params = {
            "initial_infected_count": initial_infected_count,
        }
        for rule in rules:
            if rule.trigger_type == "proximity":
                transmission_params["proximity_probability"] = rule.probability
            elif rule.trigger_type == "action":
                transmission_params["action_probability"] = rule.probability
            elif rule.trigger_type == "decay" and rule.decay_turns is not None:
                transmission_params["recovery_turns"] = rule.decay_turns

        config = ExperimentConfig(
            scenario_id="contagion",
            agents=[],
            actions=[
                {"name": "move", "description": T("Move to an adjacent location on the map.")},
                {"name": "speak_to", "description": T("Speak to a nearby agent, share information or interact.")},
            ],
            parameters=transmission_params,
            description=initial_event,
        )
        super().__init__(config)

        # Override name after super().__init__ sets it from config
        self.name = name
        self.initial_event = initial_event

    def initialize(self, llm_client, provider_clients=None) -> None:
        """Initialize scene: call super, then place agents and mark infected.

        After ExperimentScene.initialize() creates agents from config, this
        randomly assigns grid positions and marks initial infected agents.

        Args:
            llm_client: LLM client for prompting agents
            provider_clients: Optional mapping of provider_id -> LLMClient
        """
        super().initialize(llm_client, provider_clients)

        # Assign random grid positions to agents that lack map_xy
        for agent in self.agents:
            if "map_xy" not in agent.properties:
                agent.properties["map_xy"] = [
                    random.randint(0, self.game_map.width - 1),
                    random.randint(0, self.game_map.height - 1),
                ]

        # Randomly mark initial infected agents
        infected = random.sample(
            self.agents,
            min(self.initial_infected_count, len(self.agents)),
        )
        for agent in infected:
            agent.properties["contagion_state"] = "infected"
            agent.properties["contagion_turns"] = 0
        for agent in self.agents:
            if "contagion_state" not in agent.properties:
                agent.properties["contagion_state"] = "susceptible"
                agent.properties["contagion_turns"] = 0

        # Initial statistics snapshot
        self._update_statistics()

    def _create_game_config(self) -> GameConfig:
        """Return a GameConfig with payoff_type='none' to disable scoring.

        The contagion scene does not use point-based payoffs. SEIR state
        transitions replace scoring as the primary mechanic.
        """
        return GameConfig(
            name="contagion",
            description=self.initial_event,
            action_type="discrete",
            actions=["move", "speak_to"],
            action_descriptions={
                "move": "Move to an adjacent location on the map.",
                "speak_to": "Speak to a nearby agent, share information or interact.",
            },
            output_field="action",
            payoff_type="none",
            grouping_mode="individual",
        )

    def _build_payoff_summary(self) -> str:
        """Return SEIR rules description instead of a payoff table.

        Builds a human-readable description from self.rules so agents
        understand the contagion mechanics.
        """
        parts = [
            "Contagion rules: agents with 'infected' state can spread to "
            "susceptible agents nearby.",
            "Use 'move' to change position, 'speak_to' to interact with "
            "nearby agents.",
        ]
        for rule in self.rules:
            if rule.trigger_type == "decay" and rule.decay_turns is not None:
                parts.append(f"Recovery happens after {rule.decay_turns} turns.")
            elif rule.trigger_type == "proximity":
                parts.append(
                    f"Proximity transmission chance: {rule.probability:.0%}."
                )
            elif rule.trigger_type == "action":
                parts.append(
                    f"Action transmission chance: {rule.probability:.0%}."
                )
        return " ".join(parts)

    async def run_round(self, event_emitter) -> RoundResult:
        """Run one round: normal Pipeline A loop, then apply SEIR transitions.

        Args:
            event_emitter: Callback to emit events (type, data)

        Returns:
            RoundResult with all agent actions
        """
        # 1. Run the normal Pipeline A turn loop
        result = await super().run_round(event_emitter)

        # 2. Apply SEIR transitions based on this round's actions
        self._apply_seir_round(result.actions)

        # 3. Update statistics and emit contagion_stats event
        self._update_statistics()
        event_emitter("contagion_stats", {
            "counts": self._statistics.counts,
            "agent_states": {
                a.name: a.properties.get("contagion_state", "unknown")
                for a in self.agents
            },
        })

        return result

    def _apply_seir_round(self, actions: List[ActionResult]) -> None:
        """Apply SEIR transitions after a round's actions complete.

        Processes action-based transmission (speak_to), proximity-based
        transmission (adjacent agents), and decay (recovery after N turns).

        Args:
            actions: List of ActionResult from the completed round
        """
        round_num = self.current_round

        # Build position lookup
        position_to_agents: Dict[Tuple[int, int], list] = {}
        for agent in self.agents:
            xy = agent.properties.get("map_xy")
            if xy:
                key = (xy[0], xy[1])
                position_to_agents.setdefault(key, []).append(agent)

        # Track agents that transitioned this round to prevent double transitions
        transitioned: set = set()

        # --- Action-based transmission (speak_to) ---
        agent_map = {a.name: a for a in self.agents}
        for action in actions:
            if not action.success or action.skipped:
                continue
            if action.action_name != "speak_to":
                continue

            target_name = action.parameters.get("target")
            if not target_name or target_name not in agent_map:
                continue

            sender = agent_map[action.agent_name]
            target = agent_map[target_name]
            sender_state = sender.properties.get("contagion_state", "")
            target_state = target.properties.get("contagion_state", "")

            # Infected sender → susceptible target
            if (
                sender_state == "infected"
                and target_state == "susceptible"
                and target.name not in transitioned
            ):
                for rule in self.rules:
                    if (
                        rule.trigger_type == "action"
                        and rule.from_state.value == "susceptible"
                        and check_probability(rule.probability)
                    ):
                        target.properties["contagion_state"] = rule.to_state.value
                        target.properties["contagion_turns"] = 0
                        transitioned.add(target.name)
                        self._statistics.record_transition(TransitionEvent(
                            turn=round_num,
                            agent_id=target.name,
                            from_state="susceptible",
                            to_state=rule.to_state.value,
                            trigger_type="action",
                            source_agent_id=sender.name,
                        ))
                        break

            # Susceptible sender → infected target (bidirectional check)
            if (
                sender_state == "susceptible"
                and target_state == "infected"
                and sender.name not in transitioned
            ):
                for rule in self.rules:
                    if (
                        rule.trigger_type == "action"
                        and rule.from_state.value == "susceptible"
                        and check_probability(rule.probability)
                    ):
                        sender.properties["contagion_state"] = rule.to_state.value
                        sender.properties["contagion_turns"] = 0
                        transitioned.add(sender.name)
                        self._statistics.record_transition(TransitionEvent(
                            turn=round_num,
                            agent_id=sender.name,
                            from_state="susceptible",
                            to_state=rule.to_state.value,
                            trigger_type="action",
                            source_agent_id=target.name,
                        ))
                        break

        # --- Proximity-based transmission ---
        for agent in self.agents:
            if agent.name in transitioned:
                continue
            xy = agent.properties.get("map_xy")
            if not xy:
                continue

            agent_state = agent.properties.get("contagion_state", "")

            # Check if this agent is infected — can spread to neighbors
            if agent_state == "infected":
                for neighbor_xy in self.get_moore_neighbors(xy[0], xy[1]):
                    for neighbor in position_to_agents.get(neighbor_xy, []):
                        if (
                            neighbor.name == agent.name
                            or neighbor.name in transitioned
                        ):
                            continue
                        neighbor_state = neighbor.properties.get(
                            "contagion_state", ""
                        )
                        if neighbor_state == "susceptible":
                            for rule in self.rules:
                                if (
                                    rule.trigger_type == "proximity"
                                    and rule.from_state.value == "susceptible"
                                    and check_probability(rule.probability)
                                ):
                                    neighbor.properties["contagion_state"] = (
                                        rule.to_state.value
                                    )
                                    neighbor.properties["contagion_turns"] = 0
                                    transitioned.add(neighbor.name)
                                    self._statistics.record_transition(
                                        TransitionEvent(
                                            turn=round_num,
                                            agent_id=neighbor.name,
                                            from_state="susceptible",
                                            to_state=rule.to_state.value,
                                            trigger_type="proximity",
                                            source_agent_id=agent.name,
                                        )
                                    )
                                    break

        # --- Decay: increment turns and check recovery ---
        for agent in self.agents:
            state = agent.properties.get("contagion_state", "")
            for rule in self.rules:
                if (
                    rule.trigger_type == "decay"
                    and rule.from_state.value == state
                ):
                    agent.properties["contagion_turns"] = (
                        agent.properties.get("contagion_turns", 0) + 1
                    )
                    if agent.properties["contagion_turns"] >= rule.decay_turns:
                        agent.properties["contagion_state"] = rule.to_state.value
                        agent.properties["contagion_turns"] = 0
                        self._statistics.record_transition(TransitionEvent(
                            turn=round_num,
                            agent_id=agent.name,
                            from_state=state,
                            to_state=rule.to_state.value,
                            trigger_type="decay",
                        ))
                    break

    def get_moore_neighbors(self, x: int, y: int) -> List[Tuple[int, int]]:
        """Return all valid 8-directional (Moore) neighbor coordinates.

        Args:
            x: X coordinate on the grid
            y: Y coordinate on the grid

        Returns:
            List of (x, y) tuples for valid neighboring cells
        """
        neighbors = []
        for dx in [-1, 0, 1]:
            for dy in [-1, 0, 1]:
                if dx == 0 and dy == 0:
                    continue
                nx, ny = x + dx, y + dy
                if self.game_map.in_bounds(nx, ny):
                    neighbors.append((nx, ny))
        return neighbors

    def get_adjacent_agents(self, agent_name: str) -> List[str]:
        """Return names of agents in Moore-adjacent cells to the named agent.

        Args:
            agent_name: Name of the agent to find neighbors for

        Returns:
            List of agent names in adjacent grid cells
        """
        agent = None
        for a in self.agents:
            if a.name == agent_name:
                agent = a
                break
        if not agent:
            return []

        xy = agent.properties.get("map_xy")
        if not xy:
            return []

        neighbor_coords = set(self.get_moore_neighbors(xy[0], xy[1]))
        return [
            other.name
            for other in self.agents
            if other.name != agent_name
            and other.properties.get("map_xy")
            and (
                other.properties["map_xy"][0],
                other.properties["map_xy"][1],
            ) in neighbor_coords
        ]

    def _update_statistics(self) -> None:
        """Recount SEIR states across all agents."""
        self._statistics.counts = {}
        for agent in self.agents:
            state = agent.properties.get("contagion_state", "unknown")
            self._statistics.counts[state] = (
                self._statistics.counts.get(state, 0) + 1
            )

    def get_statistics(self) -> dict:
        """Return current SEIR counts and transition events.

        Returns:
            Dict with 'counts' (state -> count) and 'events' list
        """
        return self._statistics.to_dict()

    def serialize_config(self) -> dict:
        """Serialize scene configuration for persistence.

        Extends ExperimentScene serialization with contagion-specific
        fields: game_map, rules, and initial_infected_count.
        """
        base = super().serialize_config()
        base["game_map"] = self.game_map.serialize()
        base["rules"] = [
            {
                "from_state": rule.from_state.value,
                "to_state": rule.to_state.value,
                "trigger_type": rule.trigger_type,
                "probability": rule.probability,
                "decay_turns": rule.decay_turns,
            }
            for rule in self.rules
        ]
        base["initial_infected_count"] = self.initial_infected_count
        return base

    @classmethod
    def deserialize_config(cls, data: dict) -> "ContagionScene":
        """Restore from serialized state.

        Args:
            data: Serialized config dict from serialize_config()

        Returns:
            Restored ContagionScene instance
        """
        game_map = GameMap.deserialize(data.get("game_map") or {})

        rules = []
        for rule_data in data.get("rules", []):
            rules.append(StateTransition(
                from_state=ContagionState(rule_data["from_state"]),
                to_state=ContagionState(rule_data["to_state"]),
                trigger_type=rule_data["trigger_type"],
                probability=rule_data["probability"],
                decay_turns=rule_data.get("decay_turns"),
            ))

        scene = cls(
            name=data.get("name", ""),
            initial_event=data.get("initial_event", ""),
            game_map=game_map,
            rules=rules,
            initial_infected_count=data.get("initial_infected_count", 1),
        )
        # Restore ExperimentScene state from config dict
        if "config" in data:
            config = ExperimentConfig(**data["config"])
            scene.config = config
        scene.current_round = data.get("current_round", 0)
        if data.get("state") is not None:
            from fos.core.experiment.state import ExperimentState
            scene.state = ExperimentState.from_dict(data["state"])
        if data.get("history"):
            from copy import deepcopy
            scene._history = deepcopy(data["history"])
        return scene
