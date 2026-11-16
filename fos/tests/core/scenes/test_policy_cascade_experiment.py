"""
Tests for PolicyCascadeExperimentScene scaffold and ExperimentAgent feedback.

Verifies import, MRO, feedback_buffer, _agents_dict, _SimulatorAdapter,
and configure_from_config.

Contains: test fixtures and 9 test functions.
"""
from unittest.mock import MagicMock


from fos.core.experiment.agent import ExperimentAgent
from fos.core.experiment.config import ExperimentConfig
from fos.core.experiment.scene import ExperimentScene
from fos.core.llm_config import LLMConfig
from fos.core.scenes.policy_cascade_experiment import (
    PolicyCascadeExperimentScene,
    _SimulatorAdapter,
)


def _make_config(**overrides):
    defaults = {
        "agents": [
            {"name": "Alice", "properties": {"tier": "high"}, "llm_config": {"dialect": "mock"}},
            {"name": "Bob", "properties": {"tier": "low"}, "llm_config": {"dialect": "mock"}},
        ],
        "actions": [],
        "parameters": {"tier_order": ["high", "low"]},
    }
    defaults.update(overrides)
    return ExperimentConfig(**defaults)


def _mock_llm_client():
    client = MagicMock()
    client.provider = MagicMock()
    client.provider.api_key = "test"
    client.provider.base_url = "http://test"
    return client


# Test 1: is ExperimentScene subclass
def test_is_experiment_scene_subclass():
    assert issubclass(PolicyCascadeExperimentScene, ExperimentScene)


# Test 2: has correct TYPE
def test_type_attribute():
    assert PolicyCascadeExperimentScene.TYPE == "policy_cascade_experiment"


# Test 3: add_env_feedback appends
def test_add_env_feedback_appends():
    agent = ExperimentAgent(name="X", properties={}, llm_config=LLMConfig(dialect="mock"))
    agent.add_env_feedback("error 1")
    agent.add_env_feedback("error 2")
    assert agent.feedback_buffer == ["error 1", "error 2"]


# Test 4: clear_feedback_buffer empties
def test_clear_feedback_buffer():
    agent = ExperimentAgent(name="X", properties={}, llm_config=LLMConfig(dialect="mock"))
    agent.add_env_feedback("msg")
    agent.clear_feedback_buffer()
    assert agent.feedback_buffer == []


# Test 5: get_feedback_text joins
def test_get_feedback_text():
    agent = ExperimentAgent(name="X", properties={}, llm_config=LLMConfig(dialect="mock"))
    assert agent.get_feedback_text() == ""
    agent.add_env_feedback("line 1")
    agent.add_env_feedback("line 2")
    assert agent.get_feedback_text() == "line 1\nline 2"


# Test 6: initialize builds _agents_dict
def test_initialize_builds_agents_dict():
    config = _make_config()
    scene = PolicyCascadeExperimentScene(config)
    scene.initialize(_mock_llm_client())
    assert "Alice" in scene._agents_dict
    assert "Bob" in scene._agents_dict
    assert scene._agents_dict["Alice"].name == "Alice"


# Test 7: _SimulatorAdapter.agents returns _agents_dict
def test_simulator_adapter_agents():
    config = _make_config()
    scene = PolicyCascadeExperimentScene(config)
    scene.initialize(_mock_llm_client())
    adapter = _SimulatorAdapter(scene)
    assert adapter.agents is scene._agents_dict


# Test 8: _SimulatorAdapter.turns returns _current_round
def test_simulator_adapter_turns():
    config = _make_config()
    scene = PolicyCascadeExperimentScene(config)
    scene._current_round = 5
    adapter = _SimulatorAdapter(scene)
    assert adapter.turns == 5


# Test 9: configure_from_config applies tier_order
def test_configure_from_config_tier_order():
    config = _make_config(parameters={"tier_order": ["high", "mid", "low"]})
    scene = PolicyCascadeExperimentScene(config)
    assert scene.tier_order == ["high", "mid", "low"]
