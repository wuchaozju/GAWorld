"""
Tests for ContagionScene SEIR infection dynamics on a spatial grid.

Covers initialization, state transitions, spatial mechanics, round
execution, and edge cases. Uses mock LLM throughout to avoid external
API calls.

Contains tests for:
- Grid and agent initialization
- S->E->I->R state transitions
- Moore-neighborhood infection range
- run_round() lifecycle
- Edge cases (zero agents, all recovered, single agent)
"""
import asyncio

from fos.core.contagion.scene import ContagionScene
from fos.core.contagion.states import ContagionState
from fos.core.contagion.rules import StateTransition
from fos.core.experiment.controller import ActionResult
from fos.core.experiment.runner import RoundResult
from fos.core.map.grid import GameMap


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_rules(
    proximity_prob=0.3,
    action_prob=0.5,
    decay_turns=2,
):
    """Build standard SEIR transition rules for tests."""
    return [
        StateTransition(
            from_state=ContagionState.SUSCEPTIBLE,
            to_state=ContagionState.EXPOSED,
            trigger_type="proximity",
            probability=proximity_prob,
        ),
        StateTransition(
            from_state=ContagionState.SUSCEPTIBLE,
            to_state=ContagionState.EXPOSED,
            trigger_type="action",
            probability=action_prob,
        ),
        StateTransition(
            from_state=ContagionState.EXPOSED,
            to_state=ContagionState.INFECTED,
            trigger_type="decay",
            probability=1.0,
            decay_turns=1,
        ),
        StateTransition(
            from_state=ContagionState.INFECTED,
            to_state=ContagionState.RECOVERED,
            trigger_type="decay",
            probability=1.0,
            decay_turns=decay_turns,
        ),
    ]


def _make_scene(
    width=5,
    height=5,
    initial_infected=1,
    rules=None,
):
    """Create a ContagionScene with the given grid and rules."""
    return ContagionScene(
        name="test_contagion",
        initial_event="A virus spreads.",
        game_map=GameMap(width=width, height=height),
        rules=rules or _make_rules(),
        initial_infected_count=initial_infected,
    )


def _mock_llm_client():
    """Create a mock LLM client using the 'mock' dialect."""
    from fos.core.llm_config import LLMConfig
    from fos.core.llm.client import LLMClient
    return LLMClient(LLMConfig(dialect="mock", model="test"))


def _init_with_agents(
    scene,
    agent_names=("Alice", "Bob", "Carol"),
):
    """Initialize scene with named agents via mock LLM."""
    scene.config.agents = [
        {"name": name, "properties": {}, "role_prompt": f"You are {name}."}
        for name in agent_names
    ]
    scene.initialize(_mock_llm_client())
    return scene


def _run_round(scene):
    """Run a single round and return the RoundResult."""
    async def _go():
        return await scene.run_round(lambda t, d: None)
    return asyncio.run(_go())


def _place_agent(scene, name, x, y):
    """Set an agent's grid position by name."""
    for a in scene.agents:
        if a.name == name:
            a.properties["map_xy"] = [x, y]
            return
    raise ValueError(f"Agent {name} not found")


def _set_state(scene, name, state, turns=0):
    """Set an agent's contagion state and turns by name."""
    for a in scene.agents:
        if a.name == name:
            a.properties["contagion_state"] = state
            a.properties["contagion_turns"] = turns
            return
    raise ValueError(f"Agent {name} not found")


# ===================================================================
# Group 1 — Initialization
# ===================================================================


class TestInitialization:
    """Grid created with correct dimensions, agents placed, SEIR states set."""

    def test_grid_created_with_correct_dimensions(self):
        """Scene stores the GameMap with the requested width and height."""
        scene = _make_scene(width=10, height=8)
        assert scene.game_map.width == 10
        assert scene.game_map.height == 8

    def test_agents_placed_at_valid_positions(self):
        """After initialize(), every agent has map_xy within the grid."""
        scene = _init_with_agents(_make_scene(width=5, height=5))
        for agent in scene.agents:
            xy = agent.properties["map_xy"]
            assert isinstance(xy, list)
            assert 0 <= xy[0] < 5
            assert 0 <= xy[1] < 5

    def test_seir_states_initialized_correctly(self):
        """Every agent has a valid contagion_state after initialize()."""
        scene = _init_with_agents(_make_scene())
        valid = {"susceptible", "exposed", "infected", "recovered"}
        for agent in scene.agents:
            assert agent.properties["contagion_state"] in valid

    def test_all_agents_start_susceptible_except_infected(self):
        """With initial_infected=1, exactly 1 infected, rest susceptible."""
        scene = _init_with_agents(
            _make_scene(initial_infected=1),
            agent_names=("A", "B", "C", "D"),
        )
        infected = sum(
            1 for a in scene.agents
            if a.properties["contagion_state"] == "infected"
        )
        susceptible = sum(
            1 for a in scene.agents
            if a.properties["contagion_state"] == "susceptible"
        )
        assert infected == 1
        assert susceptible == 3

    def test_contagion_turns_initialized_to_zero(self):
        """All agents start with contagion_turns = 0."""
        scene = _init_with_agents(_make_scene())
        for agent in scene.agents:
            assert agent.properties["contagion_turns"] == 0


# ===================================================================
# Group 2 — State transitions
# ===================================================================


class TestStateTransitions:
    """S->E on contact, E->I after incubation, I->R after recovery."""

    def test_susceptible_becomes_exposed_on_proximity_contact(self):
        """Susceptible agent adjacent to infected becomes exposed (p=1.0)."""
        rules = [
            StateTransition(
                from_state=ContagionState.SUSCEPTIBLE,
                to_state=ContagionState.EXPOSED,
                trigger_type="proximity",
                probability=1.0,
            ),
        ]
        scene = _init_with_agents(
            _make_scene(rules=rules, initial_infected=0),
            agent_names=("Alice", "Bob"),
        )
        _set_state(scene, "Alice", "infected", turns=0)
        _place_agent(scene, "Alice", 2, 2)
        _place_agent(scene, "Bob", 2, 3)

        # Apply SEIR round with empty actions (no speak_to)
        scene._apply_seir_round([])

        assert scene.agents[1].properties["contagion_state"] == "exposed"

    def test_exposed_becomes_infected_after_incubation(self):
        """Exposed agent transitions to infected after decay_turns."""
        rules = [
            StateTransition(
                from_state=ContagionState.EXPOSED,
                to_state=ContagionState.INFECTED,
                trigger_type="decay",
                probability=1.0,
                decay_turns=1,
            ),
        ]
        scene = _init_with_agents(
            _make_scene(rules=rules, initial_infected=0),
            agent_names=("Alice",),
        )
        _set_state(scene, "Alice", "exposed", turns=0)

        scene._apply_seir_round([])

        assert scene.agents[0].properties["contagion_state"] == "infected"

    def test_infected_becomes_recovered_after_recovery_period(self):
        """Infected agent transitions to recovered after decay_turns."""
        rules = [
            StateTransition(
                from_state=ContagionState.INFECTED,
                to_state=ContagionState.RECOVERED,
                trigger_type="decay",
                probability=1.0,
                decay_turns=2,
            ),
        ]
        scene = _init_with_agents(
            _make_scene(rules=rules, initial_infected=0),
            agent_names=("Alice",),
        )
        _set_state(scene, "Alice", "infected", turns=1)

        scene._apply_seir_round([])

        assert scene.agents[0].properties["contagion_state"] == "recovered"

    def test_recovered_agents_do_not_reinfect(self):
        """Recovered agents stay recovered and don't transition again."""
        rules = [
            StateTransition(
                from_state=ContagionState.SUSCEPTIBLE,
                to_state=ContagionState.EXPOSED,
                trigger_type="proximity",
                probability=1.0,
            ),
        ]
        scene = _init_with_agents(
            _make_scene(rules=rules, initial_infected=0),
            agent_names=("Alice", "Bob"),
        )
        _set_state(scene, "Alice", "infected", turns=0)
        _set_state(scene, "Bob", "recovered", turns=0)
        _place_agent(scene, "Alice", 2, 2)
        _place_agent(scene, "Bob", 2, 3)

        scene._apply_seir_round([])

        assert scene.agents[1].properties["contagion_state"] == "recovered"


# ===================================================================
# Group 3 — Spatial mechanics
# ===================================================================


class TestSpatialMechanics:
    """Agents only infect neighbors within range; outside range is safe."""

    def test_agents_within_range_can_be_infected(self):
        """Adjacent infected agent can spread to susceptible neighbor (p=1)."""
        rules = [
            StateTransition(
                from_state=ContagionState.SUSCEPTIBLE,
                to_state=ContagionState.EXPOSED,
                trigger_type="proximity",
                probability=1.0,
            ),
        ]
        scene = _init_with_agents(
            _make_scene(rules=rules, initial_infected=0),
            agent_names=("Alice", "Bob"),
        )
        _set_state(scene, "Alice", "infected", turns=0)
        _place_agent(scene, "Alice", 2, 2)
        _place_agent(scene, "Bob", 2, 3)  # adjacent

        scene._apply_seir_round([])

        assert scene.agents[1].properties["contagion_state"] == "exposed"

    def test_agents_outside_range_are_not_infected(self):
        """Agents beyond Moore neighborhood are not infected by proximity."""
        rules = [
            StateTransition(
                from_state=ContagionState.SUSCEPTIBLE,
                to_state=ContagionState.EXPOSED,
                trigger_type="proximity",
                probability=1.0,
            ),
        ]
        scene = _init_with_agents(
            _make_scene(rules=rules, initial_infected=0),
            agent_names=("Alice", "Bob"),
        )
        _set_state(scene, "Alice", "infected", turns=0)
        _place_agent(scene, "Alice", 0, 0)
        _place_agent(scene, "Bob", 4, 4)  # far away

        scene._apply_seir_round([])

        assert scene.agents[1].properties["contagion_state"] == "susceptible"

    def test_moore_neighbors_center_has_eight(self):
        """Center cell (2,2) on a 5x5 grid has exactly 8 Moore neighbors."""
        scene = _make_scene()
        neighbors = scene.get_moore_neighbors(2, 2)
        assert len(neighbors) == 8

    def test_moore_neighbors_corner_has_three(self):
        """Corner cell (0,0) has 3 Moore neighbors."""
        scene = _make_scene()
        neighbors = scene.get_moore_neighbors(0, 0)
        assert len(neighbors) == 3

    def test_get_adjacent_agents_returns_correct_neighbors(self):
        """get_adjacent_agents returns names of agents in adjacent cells."""
        scene = _init_with_agents(
            _make_scene(initial_infected=0),
            agent_names=("Alice", "Bob", "Carol"),
        )
        _place_agent(scene, "Alice", 2, 2)
        _place_agent(scene, "Bob", 2, 3)   # adjacent
        _place_agent(scene, "Carol", 4, 4)  # far

        adjacent = scene.get_adjacent_agents("Alice")
        assert "Bob" in adjacent
        assert "Carol" not in adjacent

    def test_get_adjacent_agents_returns_empty_for_unknown(self):
        """get_adjacent_agents returns [] for a nonexistent agent."""
        scene = _init_with_agents(_make_scene())
        assert scene.get_adjacent_agents("Nobody") == []


# ===================================================================
# Group 4 — Round execution
# ===================================================================


class TestRoundExecution:
    """run_round returns RoundResult, positions update, infection changes."""

    def test_run_round_returns_valid_round_result(self):
        """run_round() returns a RoundResult with actions for each agent."""
        scene = _init_with_agents(_make_scene())
        result = _run_round(scene)
        assert isinstance(result, RoundResult)
        assert len(result.actions) == 3

    def test_run_round_emits_contagion_stats_event(self):
        """run_round() emits a contagion_stats event with state counts."""
        scene = _init_with_agents(_make_scene())
        events = []

        async def _go():
            return await scene.run_round(lambda t, d: events.append((t, d)))
        asyncio.run(_go())

        stats_events = [e for e in events if e[0] == "contagion_stats"]
        assert len(stats_events) >= 1
        counts = stats_events[0][1]["counts"]
        assert isinstance(counts, dict)
        assert "susceptible" in counts or "infected" in counts

    def test_infection_count_changes_across_rounds(self):
        """Infection count can change after rounds (forced proximity p=1)."""
        rules = [
            StateTransition(
                from_state=ContagionState.SUSCEPTIBLE,
                to_state=ContagionState.INFECTED,
                trigger_type="proximity",
                probability=1.0,
            ),
        ]
        scene = _init_with_agents(
            _make_scene(rules=rules, initial_infected=0),
            agent_names=("Alice", "Bob"),
        )
        _set_state(scene, "Alice", "infected", turns=0)
        _place_agent(scene, "Alice", 2, 2)
        _place_agent(scene, "Bob", 2, 3)

        _run_round(scene)

        bob_state = scene.agents[1].properties["contagion_state"]
        assert bob_state == "infected"

    def test_agent_positions_stored_as_map_xy(self):
        """Agent positions are stored in properties['map_xy'] after init."""
        scene = _init_with_agents(_make_scene())
        for agent in scene.agents:
            assert "map_xy" in agent.properties
            xy = agent.properties["map_xy"]
            assert len(xy) == 2


# ===================================================================
# Group 5 — Edge cases
# ===================================================================


class TestEdgeCases:
    """Zero agents, all recovered, single agent."""

    def test_zero_agents_does_not_crash(self):
        """Scene with zero agents initializes and runs without error."""
        scene = _init_with_agents(_make_scene(), agent_names=[])
        result = _run_round(scene)
        assert isinstance(result, RoundResult)
        assert len(result.actions) == 0

    def test_all_agents_already_recovered(self):
        """No transitions occur when all agents are already recovered."""
        rules = [
            StateTransition(
                from_state=ContagionState.SUSCEPTIBLE,
                to_state=ContagionState.EXPOSED,
                trigger_type="proximity",
                probability=1.0,
            ),
        ]
        scene = _init_with_agents(
            _make_scene(rules=rules, initial_infected=0),
            agent_names=("Alice", "Bob"),
        )
        for a in scene.agents:
            a.properties["contagion_state"] = "recovered"
            a.properties["contagion_turns"] = 0

        scene._apply_seir_round([])

        for a in scene.agents:
            assert a.properties["contagion_state"] == "recovered"

    def test_single_agent_does_not_crash(self):
        """Scene with a single agent initializes and runs without error."""
        scene = _init_with_agents(
            _make_scene(initial_infected=1),
            agent_names=("Solo",),
        )
        result = _run_round(scene)
        assert isinstance(result, RoundResult)
        assert len(result.actions) == 1

    def test_double_transition_prevented_in_same_round(self):
        """An agent that transitions via action is not also hit by proximity."""
        rules = [
            StateTransition(
                from_state=ContagionState.SUSCEPTIBLE,
                to_state=ContagionState.EXPOSED,
                trigger_type="action",
                probability=1.0,
            ),
            StateTransition(
                from_state=ContagionState.SUSCEPTIBLE,
                to_state=ContagionState.EXPOSED,
                trigger_type="proximity",
                probability=1.0,
            ),
        ]
        scene = _init_with_agents(
            _make_scene(rules=rules, initial_infected=0),
            agent_names=("Infected", "Target"),
        )
        _set_state(scene, "Infected", "infected", turns=0)
        _set_state(scene, "Target", "susceptible", turns=0)
        _place_agent(scene, "Infected", 2, 2)
        _place_agent(scene, "Target", 2, 3)

        # Simulate a speak_to action from Infected to Target
        actions = [ActionResult(
            success=True,
            action_name="speak_to",
            parameters={"target": "Target"},
            summary="spoke",
            agent_name="Infected",
            round_num=1,
            skipped=False,
            error=None,
            debug_log=[],
        )]
        scene._apply_seir_round(actions)

        # Target should be exposed exactly once
        assert scene.agents[1].properties["contagion_state"] == "exposed"
        # Only one transition event recorded for Target
        target_events = [
            e for e in scene._statistics.events
            if e.agent_id == "Target"
        ]
        assert len(target_events) == 1
