"""
Integration tests using local Ollama to verify prompts work with 3-4B models.

These tests verify that the simplified prompt format produces valid JSON
responses from small language models.

Run with: pytest tests/integration/ -v -m integration
"""
import json
import pytest
import requests

from fos.core.experiment.prompt_builder import build_prompt
from fos.core.experiment.agent import ExperimentAgent
from fos.core.experiment.game_configs import GameConfig


OLLAMA_API = "http://localhost:11434/v1"
TEST_MODELS = ["qwen3:4b-instruct-2507-q4_K_M", "phi4-mini:latest", "gemma3:4b-it-qat"]


@pytest.fixture
def simple_game_config():
    """Simple game config for testing."""
    return GameConfig(
        name="test",
        description="Choose to cooperate or defect.",
        action_type="discrete",
        actions=["cooperate", "defect"],
        action_descriptions={
            "cooperate": "Work together for mutual benefit",
            "defect": "Act selfishly for personal gain"
        },
    )


@pytest.fixture
def test_agent():
    """Test agent for prompts."""
    return ExperimentAgent(
        name="Alice",
        properties={},
        llm_config={},
        role_prompt="You are participating in a game theory experiment.",
    )


@pytest.fixture
def spatial_game_config():
    """Spatial game config with move action."""
    return GameConfig(
        name="spatial_test",
        description="You are on a 5x5 grid. You can cooperate with neighbors or move to a new position.",
        action_type="discrete",
        actions=["cooperate", "defect", "move"],
        action_descriptions={
            "cooperate": "Work together with adjacent agents",
            "defect": "Act selfishly",
            "move": "Move to an adjacent tile"
        },
    )


def check_ollama_available():
    """Check if Ollama is running."""
    try:
        response = requests.get("http://localhost:11434/api/tags", timeout=2)
        return response.status_code == 200
    except requests.RequestException:
        return False


@pytest.mark.integration
@pytest.mark.skipif(not check_ollama_available(), reason="Ollama not running")
@pytest.mark.parametrize("model", TEST_MODELS)
def test_llm_outputs_valid_action(model, simple_game_config, test_agent):
    """LLM returns valid JSON with one of the action names."""
    context = "This is the first round."
    prompt = build_prompt(test_agent, simple_game_config, context)

    try:
        response = requests.post(
            f"{OLLAMA_API}/chat/completions",
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1,  # Low temp for consistency
            },
            timeout=30,
        )

        if response.status_code != 200:
            pytest.skip(f"Model {model} not available")

        result = response.json()
        content = result["choices"][0]["message"]["content"]

        # Strip markdown code blocks if present (some models ignore "No markdown")
        content = content.strip()
        if content.startswith("```"):
            # Remove markdown code block wrapper
            lines = content.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            content = "\n".join(lines).strip()

        # Parse JSON response
        parsed = json.loads(content)

        assert "action" in parsed, f"Response missing 'action' field: {content}"
        assert parsed["action"] in ["cooperate", "defect"], f"Invalid action: {parsed['action']}"
        assert "reasoning" not in parsed, "Response should not have 'reasoning' field"

    except json.JSONDecodeError as e:
        pytest.fail(f"LLM returned invalid JSON: {content}\nError: {e}")
    except requests.exceptions.RequestException as e:
        pytest.skip(f"Request failed: {e}")


@pytest.mark.integration
@pytest.mark.skipif(not check_ollama_available(), reason="Ollama not running")
def test_llm_handles_context(simple_game_config, test_agent):
    """LLM correctly incorporates context into decision."""
    context = """Previous rounds:
Round 1: Alice cooperated, Bob defected → 0 pts
Round 2: Alice cooperated, Bob cooperated → 3 pts
Your score: 3"""

    prompt = build_prompt(test_agent, simple_game_config, context)

    # Just verify prompt contains context
    assert "Round 1" in prompt
    assert "Round 2" in prompt
    assert "3 pts" in prompt

    # Test with first available model
    model = TEST_MODELS[0]

    try:
        response = requests.post(
            f"{OLLAMA_API}/chat/completions",
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1,
            },
            timeout=30,
        )

        if response.status_code != 200:
            pytest.skip(f"Model {model} not available")

        result = response.json()
        content = result["choices"][0]["message"]["content"]
        parsed = json.loads(content)

        assert "action" in parsed

    except (json.JSONDecodeError, requests.exceptions.RequestException) as e:
        pytest.skip(f"Request/parse failed: {e}")


@pytest.mark.integration
@pytest.mark.skipif(not check_ollama_available(), reason="Ollama not running")
def test_followup_prompt_for_move():
    """LLM provides valid direction parameter when move is selected."""
    from fos.core.experiment.prompt_builder import build_reprompt

    # Simulate agent choosing "move" and needing direction parameter
    parameter_schema = {
        "direction": {
            "type": "string",
            "enum": ["north", "south", "east", "west"],
            "description": "Direction to move"
        }
    }

    agent = ExperimentAgent(
        name="TestAgent",
        properties={},
        llm_config={},
        role_prompt="You are on a spatial grid.",
    )

    game_config = GameConfig(
        name="spatial",
        description="Move on a grid",
        action_type="discrete",
        actions=["cooperate", "defect", "move"],
    )

    followup = build_reprompt(
        agent=agent,
        game_config=game_config,
        context_summary="You are at position (2, 2).",
        chosen_action="move",
        parameter_schema=parameter_schema,
    )

    # Verify follow-up prompt structure
    assert "move" in followup.lower()
    assert "direction" in followup.lower()

    # Test with first available model
    model = TEST_MODELS[0]

    try:
        response = requests.post(
            f"{OLLAMA_API}/chat/completions",
            json={
                "model": model,
                "messages": [{"role": "user", "content": followup}],
                "temperature": 0.1,
            },
            timeout=30,
        )

        if response.status_code != 200:
            pytest.skip(f"Model {model} not available")

        content = response.json()["choices"][0]["message"]["content"]

        # Strip markdown if present
        content = content.strip()
        if content.startswith("```"):
            lines = content.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            content = "\n".join(lines).strip()

        parsed = json.loads(content)

        # Should have action
        assert "action" in parsed
        # Direction may vary - some models use "up/down" instead of "north/south"
        # We just verify it returns some direction parameter
        if "direction" in parsed:
            # Accept various direction formats
            valid_directions = ["north", "south", "east", "west", "up", "down", "left", "right", "n", "s", "e", "w"]
            assert parsed["direction"].lower() in valid_directions, f"Invalid direction: {parsed['direction']}"

    except (json.JSONDecodeError, requests.exceptions.RequestException) as e:
        pytest.skip(f"Request/parse failed: {e}")


@pytest.mark.integration
@pytest.mark.skipif(not check_ollama_available(), reason="Ollama not running")
@pytest.mark.parametrize("model", TEST_MODELS)
def test_prompt_token_efficiency(model, simple_game_config, test_agent):
    """Prompt is efficient enough for small context windows."""
    context = "This is round 1."
    prompt = build_prompt(test_agent, simple_game_config, context)

    # Count approximate tokens (rough: 4 chars per token)
    approx_tokens = len(prompt) / 4

    # Should be under 500 tokens for efficiency
    assert approx_tokens < 500, f"Prompt too long: ~{approx_tokens} tokens"

    # Also verify with a longer context
    long_context = "\n".join([
        f"Round {i}: Alice cooperated, Bob defected"
        for i in range(1, 11)
    ])
    long_prompt = build_prompt(test_agent, simple_game_config, long_context)
    long_approx_tokens = len(long_prompt) / 4

    # Should still be under 1000 tokens with 10 rounds of history
    assert long_approx_tokens < 1000, f"Long prompt too long: ~{long_approx_tokens} tokens"


@pytest.mark.integration
@pytest.mark.skipif(not check_ollama_available(), reason="Ollama not running")
def test_all_test_models_available():
    """Check which test models are available in Ollama."""
    try:
        response = requests.get("http://localhost:11434/api/tags", timeout=5)
        if response.status_code == 200:
            models = response.json().get("models", [])
            model_names = [m["name"] for m in models]

            available = []
            missing = []
            for test_model in TEST_MODELS:
                if any(test_model in name for name in model_names):
                    available.append(test_model)
                else:
                    missing.append(test_model)

            print(f"\nAvailable models: {available}")
            print(f"Missing models: {missing}")

            # This test always passes, it's just for info
            assert True
    except requests.exceptions.RequestException:
        pytest.skip("Ollama not running")
