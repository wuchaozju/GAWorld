"""
Unit tests for ContagionScene as ExperimentScene subclass (Pipeline A).

Verifies initialization, agent placement, SEIR state assignment, run_round
execution, inheritance, serialization, and Moore neighborhood geometry.
Uses mock LLM dialect to avoid external API calls.

Contains: test_instantiation, test_initialize_assigns_map_xy,
          test_initialize_marks_infected, test_run_round_completes,
          test_seir_states_change, test_is_experiment_scene_subclass,
          test_does_not_inherit_pipeline_b, test_type_attribute,
          test_serialize_includes_game_map,
          test_get_moore_neighbors_center, test_get_moore_neighbors_corner,
          test_get_moore_neighbors_edge, test_get_moore_neighbors_excludes_self
"""
import asyncio

from fos.core.contagion.scene import ContagionScene
from fos.core.contagion.states import ContagionState
from fos.core.contagion.rules import StateTransition
from fos.core.experiment.scene import ExperimentScene
from fos.core.map.grid import GameMap


def _make_rules():
    """Build standard SEIR transition rules for tests."""
    return [
        StateTransition(
            from_state=ContagionState.SUSCEPTIBLE,
            to_state=ContagionState.INFECTED,
            trigger_type="proximity",
            probability=0.3,
        ),
        StateTransition(
            from_state=ContagionState.SUSCEPTIBLE,
            to_state=ContagionState.INFECTED,
            trigger_type="action",
            probability=0.5,
        ),
        StateTransition(
            from_state=ContagionState.INFECTED,
            to_state=ContagionState.RECOVERED,
            trigger_type="decay",
            probability=1.0,
            decay_turns=2,
        ),
    ]


def _make_scene(initial_infected=1):
    """Create a ContagionScene with a 5x5 grid and standard rules."""
    return ContagionScene(
        name="test_contagion",
        initial_event="A virus spreads.",
        game_map=GameMap(width=5, height=5),
        rules=_make_rules(),
        initial_infected_count=initial_infected,
    )


def _mock_llm_client():
    """Create a mock LLM client using the 'mock' dialect."""
    from fos.core.llm_config import LLMConfig
    from fos.core.llm.client import LLMClient
    config = LLMConfig(dialect="mock", model="test")
    return LLMClient(config)


def _init_with_agents(scene, agent_names=("Alice", "Bob", "Carol")):
    """Initialize scene with agents via mock LLM."""
    scene.config.agents = [
        {"name": name, "properties": {}, "role_prompt": f"You are {name}."}
        for name in agent_names
    ]
    scene.initialize(_mock_llm_client())
    return scene


# --- Tests ---


def test_instantiation():
    """ContagionScene can be instantiated with a GameMap and rules."""
    scene = _make_scene()
    assert scene.game_map.width == 5
    assert scene.game_map.height == 5
    assert len(scene.rules) == 3
    assert scene.initial_infected_count == 1


def test_initialize_assigns_map_xy():
    """initialize() assigns map_xy to all agents."""
    scene = _init_with_agents(_make_scene())
    for agent in scene.agents:
        xy = agent.properties["map_xy"]
        assert isinstance(xy, list)
        assert 0 <= xy[0] < 5
        assert 0 <= xy[1] < 5


def test_initialize_marks_infected():
    """initialize() marks initial_infected_count agents as infected."""
    scene = _init_with_agents(_make_scene(initial_infected=2))
    infected_count = sum(
        1 for a in scene.agents
        if a.properties.get("contagion_state") == "infected"
    )
    assert infected_count == 2
    for a in scene.agents:
        assert "contagion_turns" in a.properties
        assert "contagion_state" in a.properties


def test_run_round_completes():
    """run_round() completes and returns a RoundResult."""
    scene = _init_with_agents(_make_scene())
    events = []

    async def _run():
        return await scene.run_round(lambda t, d: events.append((t, d)))

    result = asyncio.run(_run())
    assert result is not None
    assert len(result.actions) == 3  # One per agent
    assert any(e[0] == "contagion_stats" for e in events)


def test_seir_states_change():
    """SEIR states change after rounds with infected agents present.

    With 3 agents in a 5x5 grid and 1 infected, decay_turns=2,
    after 2 rounds the infected agent should recover.
    """
    scene = _init_with_agents(_make_scene(initial_infected=1))
    # Find the infected agent and place all agents adjacent for proximity check
    infected = next(
        a for a in scene.agents
        if a.properties["contagion_state"] == "infected"
    )
    infected.properties["map_xy"] = [2, 2]
    for i, agent in enumerate(scene.agents):
        if agent is not infected:
            agent.properties["map_xy"] = [2 + (i % 2), 3]

    async def _run():
        return await scene.run_round(lambda t, d: None)

    # Run 2 rounds to trigger decay recovery (decay_turns=2)
    asyncio.run(_run())
    asyncio.run(_run())

    stats = scene.get_statistics()["counts"]
    # After 2 rounds, the infected agent should have recovered
    assert stats.get("recovered", 0) >= 1


def test_is_experiment_scene_subclass():
    """ContagionScene is a subclass of ExperimentScene."""
    assert issubclass(ContagionScene, ExperimentScene)
    scene = _make_scene()
    assert isinstance(scene, ExperimentScene)


def test_does_not_inherit_pipeline_b():
    """ContagionScene does not inherit from Pipeline B base classes."""
    scene = _make_scene()
    mro_names = [c.__name__ for c in type(scene).__mro__]
    assert "VillageScene" not in mro_names
    assert "Scene" not in mro_names


def test_type_attribute():
    """ContagionScene has the correct TYPE class attribute."""
    assert ContagionScene.TYPE == "contagion_scene"


def test_serialize_includes_game_map():
    """serialize_config() includes the game_map with correct dimensions."""
    scene = ContagionScene(
        name="test_contagion",
        initial_event="A virus spreads.",
        game_map=GameMap(width=10, height=8),
        rules=_make_rules(),
        initial_infected_count=1,
    )
    config = scene.serialize_config()
    assert "game_map" in config
    assert config["game_map"]["width"] == 10
    assert config["game_map"]["height"] == 8


# --- Moore neighborhood geometry ---


def test_get_moore_neighbors_center():
    """Center cell (2,2) on a 5x5 grid has 8 Moore neighbors."""
    scene = _make_scene()
    neighbors = scene.get_moore_neighbors(2, 2)
    assert len(neighbors) == 8


def test_get_moore_neighbors_corner():
    """Corner cell (0,0) on a 5x5 grid has 3 Moore neighbors."""
    scene = _make_scene()
    neighbors = scene.get_moore_neighbors(0, 0)
    assert len(neighbors) == 3


def test_get_moore_neighbors_edge():
    """Edge cell (0,2) on a 5x5 grid has 5 Moore neighbors."""
    scene = _make_scene()
    neighbors = scene.get_moore_neighbors(0, 2)
    assert len(neighbors) == 5


def test_get_moore_neighbors_excludes_self():
    """The cell itself is not included in its Moore neighbors."""
    scene = _make_scene()
    neighbors = scene.get_moore_neighbors(2, 2)
    assert (2, 2) not in neighbors
