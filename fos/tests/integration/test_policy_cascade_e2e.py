"""
End-to-end smoke test for PolicyCascadeExperimentScene wiring.

Verifies scene creation, initialization with mock LLM,
run_round execution, and registry presence.

Contains: test_scene_creation, test_initialize, test_run_round, test_registry
"""
import asyncio
from fos.core.experiment.config import ExperimentConfig
from fos.core.scenes.policy_cascade_experiment import PolicyCascadeExperimentScene
from fos.core.llm.client import LLMClient, LLMConfig


def _make_config():
    return ExperimentConfig(
        scenario_id="policy_cascade",
        agents=[
            {"name": "Director", "properties": {"tier": "high"}},
            {"name": "Manager", "properties": {"tier": "mid"}},
        ],
        actions=[
            {"name": "send_message", "description": "Send a message"},
            {"name": "yield", "description": "End your turn"},
        ],
        parameters={
            "tier_order": ["high", "mid"],
            "cascade_mode": "standard",
        },
    )


def test_scene_creation():
    config = _make_config()
    scene = PolicyCascadeExperimentScene(config)
    assert scene.TYPE == "policy_cascade_experiment"


def test_initialize():
    config = _make_config()
    scene = PolicyCascadeExperimentScene(config)
    scene.initialize(LLMClient(LLMConfig(dialect="mock")))
    assert "Director" in scene._agents_dict
    assert "Manager" in scene._agents_dict


def test_run_round():
    config = _make_config()
    scene = PolicyCascadeExperimentScene(config)
    scene.initialize(LLMClient(LLMConfig(dialect="mock")))
    events = []
    result = asyncio.run(scene.run_round(lambda t, d: events.append((t, d))))
    assert result is not None
    assert hasattr(result, "round_num")


def test_registry():
    from fos.core.registry import SCENE_MAP
    assert "policy_cascade_experiment" in SCENE_MAP
