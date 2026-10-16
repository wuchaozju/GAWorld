"""Integration checks for GAWorld registry and runtime wiring.

This file checks that GAWorld is connected through exports, registries, and runtime routing.
Each test verifies one user-visible wiring expectation for the GAWorld scene.
"""

from __future__ import annotations

import pytest

from fos.backend.services import gaworld_agents as gaworld_agents_service
from fos.backend.services import simtree_runtime
from fos.core.experiment.scenes.gaworld import GAWorldScene
from fos.core.registry import get_information_model, get_scene_class
from fos.core.scenarios.registry import ALL_SCENARIOS


def test_gaworld_scene_is_importable_from_package() -> None:
    """GAWorldScene can be imported from the gaworld package export."""
    assert GAWorldScene is not None


def test_registry_returns_gaworld_scene_class() -> None:
    """Scene registry returns the GAWorldScene class for gaworld_scene."""
    assert get_scene_class("gaworld_scene") is GAWorldScene


def test_gaworld_scenario_exists_with_expected_category() -> None:
    """Scenario registry includes gaworld in generative_city category."""
    scenario = next((item for item in ALL_SCENARIOS if item.get("id") == "gaworld"), None)
    assert scenario is not None
    assert scenario["category"] == "generative_city"


def test_gaworld_scenario_does_not_include_gaworld_path_parameter() -> None:
    """GAWorld scenario parameters do not expose gaworld_path to clients."""
    scenario = next(item for item in ALL_SCENARIOS if item.get("id") == "gaworld")
    parameter_ids = {param.get("id") for param in scenario.get("parameters", [])}
    assert "gaworld_path" not in parameter_ids


def test_gaworld_adapter_logs_scene_failures_for_frontend() -> None:
    """GAWorld scene failures are emitted as node logs before the error escapes."""

    class FailingGAWorldScene:
        TYPE = "gaworld_scene"
        agents: list = []
        runner = object()

        def initialize(self, _llm_client, provider_clients=None) -> None:
            self.runner = object()

        def is_complete(self) -> bool:
            return False

        async def run_round(self, _event_emitter) -> None:
            raise RuntimeError("missing gaworld api key")

    emitted: list[tuple[str, dict]] = []
    adapter = simtree_runtime.ExperimentRunnerAdapter(FailingGAWorldScene(), clients={})
    adapter.log_event = lambda event_type, data: emitted.append((event_type, data))

    with pytest.raises(RuntimeError, match="missing gaworld api key"):
        adapter.run(max_turns=1)

    assert emitted == [
        (
            "error",
            {
                "message": "missing gaworld api key",
                "scene_type": "gaworld_scene",
            },
        )
    ]


def test_information_model_for_gaworld_scene_is_all_without_scores() -> None:
    """GAWorld info model uses global scope and hides scores."""
    model = get_information_model("gaworld_scene")
    assert model.scope_type == "all"
    assert model.include_scores is False


def test_simtree_routing_raises_when_gaworld_path_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Routing to gaworld_scene fails with i18n key when env path is missing."""
    monkeypatch.delenv("GAWORLD_PATH", raising=False)
    monkeypatch.setattr(simtree_runtime, "_GAWORLD_PATH", None)

    sim_record = type(
        "SimRecord",
        (),
        {
            "id": "SIM-GAWORLD-1",
            "scene_type": "gaworld_scene",
            "scene_config": {"parameters": {}},
            "name": "GAWorld Integration Test",
            "description": "",
            "notes": "",
            "agent_config": {"agents": []},
        },
    )()

    with pytest.raises(ValueError, match="gaworld.error.path_not_set"):
        simtree_runtime._build_tree_for_sim(sim_record, clients={})


def test_gaworld_routing_uses_startup_path_after_env_changes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Routing to gaworld_scene keeps using the path captured at startup."""
    startup_path = "C:/startup/gaworld"
    changed_path = "C:/changed/gaworld"
    monkeypatch.setattr(simtree_runtime, "_GAWORLD_PATH", startup_path)
    monkeypatch.setenv("GAWORLD_PATH", changed_path)
    # Population resolution is out of scope here — stub the live GAWorld
    # population so the tree build focuses on path capture.
    fake_page = {
        "total": 1,
        "offset": 0,
        "agents": [{"id": 1, "name": "Resident", "profile_text": ""}],
    }
    monkeypatch.setattr(
        gaworld_agents_service, "get_agents", lambda **_kwargs: dict(fake_page)
    )

    sim_record = type(
        "SimRecord",
        (),
        {
            "id": "SIM-GAWORLD-2",
            "scene_type": "gaworld_scene",
            "scene_config": {"parameters": {}},
            "name": "GAWorld Startup Path Test",
            "description": "",
            "notes": "",
            "agent_config": {"agents": []},
        },
    )()

    tree = simtree_runtime._build_tree_for_sim(sim_record, clients={})

    scene_parameters = tree.nodes[tree.root]["sim"].scene.config.parameters
    assert scene_parameters["gaworld_path"] == startup_path


def test_gaworld_routing_uses_live_population_when_no_agents_are_passed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty GAWorld agent config is filled from the LIVE GAWorld population."""
    fake_page = {
        "city": {"slug": "liuxi-cun", "name": "柳溪村", "selected": True},
        "total": 1,
        "limit": 200,
        "offset": 0,
        "agents": [
            {
                "id": 34,
                "name": "Xu Guilan",
                "profile_text": "Real GAWorld resident",
                "gender": "female",
                "age": 41,
                "residence": "柳溪村",
            }
        ],
    }
    monkeypatch.setattr(simtree_runtime, "_GAWORLD_PATH", "C:/startup/gaworld")
    monkeypatch.setattr(gaworld_agents_service, "get_agents", lambda **_kwargs: dict(fake_page))

    sim_record = type(
        "SimRecord",
        (),
        {
            "id": "SIM-GAWORLD-3",
            "scene_type": "gaworld_scene",
            "scene_config": {"parameters": {}},
            "name": "GAWorld Live Population Test",
            "description": "",
            "notes": "",
            "agent_config": {"agents": []},
        },
    )()

    tree = simtree_runtime._build_tree_for_sim(sim_record, clients={})

    scene_agents = tree.nodes[tree.root]["sim"].scene.config.agents
    assert [agent["id"] for agent in scene_agents] == [34]
    assert scene_agents[0]["name"] == "Xu Guilan"


def test_gaworld_routing_replaces_placeholder_agents(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Generic builder placeholders are replaced with live GAWorld agents."""
    fake_page = {
        "city": {"slug": "liuxi-cun", "name": "柳溪村", "selected": True},
        "total": 1,
        "limit": 200,
        "offset": 0,
        "agents": [
            {
                "id": 34,
                "name": "Xu Guilan",
                "profile_text": "Real GAWorld resident",
                "residence": "柳溪村",
            }
        ],
    }
    monkeypatch.setattr(simtree_runtime, "_GAWORLD_PATH", "C:/startup/gaworld")
    monkeypatch.setattr(gaworld_agents_service, "get_agents", lambda **_kwargs: dict(fake_page))

    sim_record = type(
        "SimRecord",
        (),
        {
            "id": "SIM-GAWORLD-4",
            "scene_type": "gaworld_scene",
            "scene_config": {"parameters": {}},
            "name": "GAWorld Placeholder Test",
            "description": "",
            "notes": "",
            "agent_config": {"agents": [{"name": "Agent 1", "properties": {}}]},
        },
    )()

    tree = simtree_runtime._build_tree_for_sim(sim_record, clients={})

    scene_agents = tree.nodes[tree.root]["sim"].scene.config.agents
    assert [agent["id"] for agent in scene_agents] == [34]
    assert scene_agents[0]["name"] == "Xu Guilan"


def test_gaworld_routing_keeps_explicit_agents_when_text_selection_is_blank(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Explicit GAWorld agents stay selected even when agent_ids text is blank."""
    monkeypatch.setattr(simtree_runtime, "_GAWORLD_PATH", "C:/startup/gaworld")

    sim_record = type(
        "SimRecord",
        (),
        {
            "id": "SIM-GAWORLD-5",
            "scene_type": "gaworld_scene",
            "scene_config": {"parameters": {"agent_ids": ""}},
            "name": "GAWorld Explicit Agent Test",
            "description": "",
            "notes": "",
            "agent_config": {
                "agents": [
                    {"id": "34", "name": "Xu Guilan", "properties": {"residence": "Hangzhou"}},
                    {"id": "35", "name": "Cai Derong", "properties": {"residence": "Hangzhou"}},
                    {"name": "Missing Id"},
                ]
            },
        },
    )()

    tree = simtree_runtime._build_tree_for_sim(sim_record, clients={})

    scene = tree.nodes[tree.root]["sim"].scene
    assert [agent["id"] for agent in scene.config.agents[:2]] == ["34", "35"]
    assert scene.config.parameters["agent_ids"] == ["34", "35"]
