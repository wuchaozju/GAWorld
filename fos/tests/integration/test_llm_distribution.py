"""
Integration test for LLM provider distribution.

Tests that provider_id is correctly converted to different LLM clients.
"""
from fos.core.experiment.scene import ExperimentScene
from fos.core.experiment.config import ExperimentConfig
from fos.core.llm.client import LLMClient
from fos.core.llm_config import LLMConfig


def test_llm_distribution():
    """Test that provider_id is correctly converted to different LLM clients."""
    # Create scene with 50/50 distribution
    scene = ExperimentScene(
        ExperimentConfig(
            scenario_id="test",
            agents=[
                {
                    "name": "Agent1",
                    "properties": {"provider_id": 1},
                    "llm_config": {"dialect": "openai", "model": "gpt-4o"},
                },
                {
                    "name": "Agent2",
                    "properties": {"provider_id": 2},
                    "llm_config": {"dialect": "ollama", "model": "llama3"},
                },
            ],
            actions=[
                {"name": "cooperate", "description": "Cooperate action"},
                {"name": "defect", "description": "Defect action"},
            ],
        )
    )
    mock_client = LLMClient(LLMConfig(dialect="mock"))
    scene.initialize(mock_client)

    # Verify that agents have different LLM configs
    assert scene.agents[0].llm_config["dialect"] == "openai"
    assert scene.agents[1].llm_config["dialect"] == "ollama"
