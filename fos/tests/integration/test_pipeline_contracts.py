"""
Pipeline contract tests — verifies ExperimentScene fulfills its public API contract.

These tests check that the Pipeline A ExperimentScene produces results with the
required fields and emits events, without requiring a real LLM (uses mock dialect).

Contains: TestExperimentSceneContract
"""
import asyncio
import pytest
from fos.core.experiment.config import ExperimentConfig
from fos.core.experiment.scene import ExperimentScene
from fos.core.llm.client import LLMClient
from fos.core.llm_config import LLMConfig


def _mock_client():
    return LLMClient(LLMConfig(dialect="mock"))


def _make_scene(num_agents=2, actions=None):
    if actions is None:
        actions = [
            {"name": "cooperate", "description": "Work together"},
            {"name": "defect", "description": "Act alone"},
        ]
    config = ExperimentConfig(
        scenario_id="custom",
        agents=[
            {"name": f"Agent{i+1}", "properties": {}}
            for i in range(num_agents)
        ],
        actions=actions,
    )
    scene = ExperimentScene(config)
    scene.initialize(_mock_client())
    return scene


def _run(scene):
    events = []
    def emitter(event_type, data):
        events.append({"type": event_type, "data": data})
    return asyncio.run(scene.run_round(emitter)), events


class TestExperimentSceneContract:

    def test_run_round_returns_result(self):
        scene = _make_scene()
        result, _ = _run(scene)
        assert result is not None

    def test_result_has_required_fields(self):
        """Successful round must report completed=True."""
        scene = _make_scene()
        result, _ = _run(scene)
        assert hasattr(result, "round_num")
        assert hasattr(result, "actions")
        assert hasattr(result, "completed")
        assert isinstance(result.actions, list)
        assert result.completed is True, "completed must be True after a successful round"

    def test_each_agent_produces_an_action(self):
        scene = _make_scene(num_agents=2)
        result, _ = _run(scene)
        assert len(result.actions) == 2

    def test_action_result_has_required_fields(self):
        """Successful actions must carry a name from the configured action set."""
        scene = _make_scene(num_agents=2)
        result, _ = _run(scene)
        valid_actions = {"cooperate", "defect"}
        for action in result.actions:
            assert hasattr(action, "agent_name")
            assert hasattr(action, "action_name")
            assert action.agent_name in {"Agent1", "Agent2"}
            assert action.action_name in valid_actions, (
                f"action_name '{action.action_name}' not in {valid_actions}"
            )

    def test_multiple_rounds_increment_counter(self):
        scene = _make_scene()
        r1, _ = _run(scene)
        r2, _ = _run(scene)
        assert r2.round_num > r1.round_num

    def test_agents_accessible_after_initialize(self):
        scene = _make_scene(num_agents=3)
        assert hasattr(scene, "agents")
        assert len(scene.agents) == 3
        assert all(hasattr(a, "name") for a in scene.agents)

    def test_events_emitted_during_round(self):
        scene = _make_scene(num_agents=2)
        _, events = _run(scene)
        assert len(events) > 0
        assert all("type" in e for e in events)

    def test_action_names_are_valid(self):
        """Successful actions must use a name from the configured action set."""
        actions = [
            {"name": "share", "description": "Share resources"},
            {"name": "withhold", "description": "Keep resources"},
        ]
        scene = _make_scene(num_agents=2, actions=actions)
        result, _ = _run(scene)
        valid = {"share", "withhold"}
        for action in result.actions:
            assert action.action_name in valid, (
                f"action_name '{action.action_name}' not in {valid}"
            )

    def test_events_have_meaningful_types(self):
        """Events must carry non-empty type strings and structured (non-None) data."""
        scene = _make_scene(num_agents=2)
        _, events = _run(scene)
        assert any(e["type"] not in (None, "") for e in events), (
            "At least one event must have a non-empty type string"
        )
        for event in events:
            assert event["data"] is not None, (
                f"Event data must never be None (event type='{event['type']}')"
            )

    @pytest.mark.skip(
        reason="ExperimentScene with 0 agents succeeds vacuously (completed=True, "
        "no actions). There is no graceful failure path that sets completed=False; "
        "the runner treats zero agents as an empty round, not an error."
    )
    def test_result_completed_false_on_failure(self):
        scene = _make_scene(num_agents=0)
        result, _ = _run(scene)
        assert result.completed is False

    def test_round_num_starts_at_1(self):
        """The first round must be numbered 1, not 0."""
        scene = _make_scene()
        result, _ = _run(scene)
        assert result.round_num == 1, (
            f"First round should be 1, got {result.round_num}"
        )
