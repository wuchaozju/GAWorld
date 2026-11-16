"""
Tests for ExperimentAgent class.
"""


from fos.core.experiment.agent import ExperimentAgent
from fos.core.llm_config import LLMConfig


def test_experiment_agent_creation():
    """Create an experiment agent with demographics."""
    llm_config = LLMConfig(dialect="openai", model="gpt-4o", api_key="test")
    agent = ExperimentAgent(
        name="Alice",
        properties={
            "age_group": "young adult",
            "profession": "doctor",
            "social_capital": 82,
        },
        llm_config=llm_config,
    )

    assert agent.name == "Alice"
    assert agent.get_property("age_group") == "young adult"
    assert agent.get_property("social_capital") == 82


def test_experiment_agent_get_properties_dict():
    """Get all properties as dict."""
    agent = ExperimentAgent(
        name="Bob",
        properties={"trait1": 50, "trait2": "high"},
        llm_config=LLMConfig(dialect="mock"),
    )

    props = agent.get_properties_dict()
    assert props == {"trait1": 50, "trait2": "high"}


def test_experiment_agent_has_property():
    """Check if agent has specific property."""
    agent = ExperimentAgent(
        name="Charlie",
        properties={"age": 35, "location": "urban"},
        llm_config=LLMConfig(dialect="mock"),
    )

    assert agent.has_property("age") is True
    assert agent.has_property("income") is False
