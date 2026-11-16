"""
This file checks a small council pilot with real local Ollama models.

It proves that neighbour-only prompt visibility still holds in the council
scene, and that a short deliberation round plus a vote round can finish with
readable, parseable actions.
"""

from __future__ import annotations

import asyncio
import os
import random
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import pytest

from fos.core.experiment.config import ExperimentConfig
from fos.core.experiment.scenes.council_experiment import (
    CouncilCyclePhase,
    CouncilExperimentScene,
)
from fos.core.llm.client import LLMClient
from fos.core.llm.generation import generate_agents_with_archetypes
from fos.core.llm_config import LLMConfig


pytestmark = pytest.mark.real_llm

DEFAULT_COUNCIL_MODELS = [
    "ministral-3:3b",
    "granite4:3b",
    "phi4-mini:latest",
    "qwen3:4b-instruct-2507-q4_K_M",
]
DEFAULT_AGENT_COUNT = 3
COUNCIL_DEMOGRAPHICS = [
    {"name": "Age", "categories": ["18-29", "30-49", "50+"]},
    {"name": "Political View", "categories": ["progressive", "moderate"]},
]
COUNCIL_TRAITS = [
    {"name": "Trust", "mean": 58, "std": 14},
    {"name": "Empathy", "mean": 64, "std": 12},
    {"name": "Openness", "mean": 61, "std": 11},
]


class CapturingLLMClient:
    """Wrap one real client so tests can inspect the exact prompt text."""

    def __init__(self, delegate: LLMClient) -> None:
        self.delegate = delegate
        self.provider = delegate.provider
        self.calls: list[dict[str, object]] = []

    def chat(self, messages: list[dict[str, str]], json_mode: bool = False) -> str:
        self.calls.append({"messages": messages, "json_mode": json_mode})
        return self.delegate.chat(messages, json_mode=json_mode)


def _selected_council_models() -> list[str]:
    """Read the council pilot model list from env or use the default four."""
    raw_models = os.environ.get("FOS_TEST_COUNCIL_MODELS", "").strip()
    if not raw_models:
        return DEFAULT_COUNCIL_MODELS
    return [model.strip() for model in raw_models.split(",") if model.strip()]


def _real_llm_config_for_model(model_name: str) -> LLMConfig:
    """Build one Ollama config for the named local model."""
    if os.environ.get("FOS_TEST_REAL_LLM") != "1":
        pytest.skip("FOS_TEST_REAL_LLM is not set")

    provider = os.environ.get("FOS_TEST_LLM_PROVIDER", "ollama")
    if provider != "ollama":
        pytest.skip("Council pilot tests are Ollama-only")

    base_url = (
        os.environ.get("FOS_TEST_LLM_BASE_URL")
        or os.environ.get("OLLAMA_BASE_URL")
        or "http://localhost:11434"
    )
    return LLMConfig(
        dialect="ollama",
        model=model_name,
        base_url=base_url,
        temperature=float(os.environ.get("FOS_TEST_LLM_TEMPERATURE", "0.7")),
        max_tokens=int(os.environ.get("FOS_TEST_LLM_MAX_TOKENS", "256")),
    )


def _ollama_json_get(base_url: str, path: str) -> dict:
    """Read one JSON payload from the local Ollama API."""
    url = base_url.rstrip("/") + path
    request = Request(url, headers={"Accept": "application/json"})
    try:
        with urlopen(request, timeout=5) as response:
            return __import__("json").loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        pytest.skip(f"Ollama is not reachable at {base_url}: {exc}")


def _ollama_model_names(base_url: str) -> set[str]:
    """Return installed Ollama model names from the local server."""
    data = _ollama_json_get(base_url, "/api/tags")
    return {str(model["name"]) for model in data.get("models", [])}


def _ollama_has_model(requested_model: str, installed_models: set[str]) -> bool:
    """Check whether the requested model tag is installed locally."""
    if requested_model in installed_models:
        return True
    if ":" not in requested_model:
        return any(name.split(":", 1)[0] == requested_model for name in installed_models)
    return False


@pytest.fixture(params=_selected_council_models(), ids=lambda name: name)
def council_model_name(request: pytest.FixtureRequest) -> str:
    """Return one selected council pilot model name."""
    return str(request.param)


@pytest.fixture
def council_real_llm_client(council_model_name: str) -> CapturingLLMClient:
    """Create one capturing client for a local Ollama council pilot run."""
    config = _real_llm_config_for_model(council_model_name)
    installed_models = _ollama_model_names(config.base_url or "http://localhost:11434")
    if not _ollama_has_model(config.model, installed_models):
        pytest.skip(f"Model {config.model} is not installed locally. Run: ollama pull {config.model}")

    client = LLMClient(config)
    try:
        client.chat(
            [{"role": "user", "content": "Reply with the word ready."}],
            json_mode=False,
        )
    except Exception as exc:
        pytest.skip(f"Ollama model {config.model} failed basic response preflight: {exc}")

    return CapturingLLMClient(client)


def _generated_agent_to_scene_config(agent: dict[str, object]) -> dict[str, object]:
    """Turn one generated demographic agent into scene config data."""
    return {
        "name": str(agent["name"]),
        "role_prompt": str(agent.get("profile") or ""),
        "properties": dict(agent.get("properties") or {}),
    }


def test_generated_agent_to_scene_config_keeps_demographics_and_profile() -> None:
    """Generated agent data should carry into the council scene unchanged."""
    generated = {
        "name": "Agent 1",
        "profile": "I am a cautious renter who weighs community costs carefully.",
        "properties": {"Age": "30-49", "Trust": 62},
    }

    config_agent = _generated_agent_to_scene_config(generated)

    assert config_agent["name"] == "Agent 1"
    assert config_agent["role_prompt"] == generated["profile"]
    assert config_agent["properties"] == generated["properties"]


def _build_generated_council_agents(llm_client: LLMClient) -> list[dict[str, object]]:
    """Generate a small demographic agent set for the council pilot."""
    seed = int(os.environ.get("FOS_TEST_COUNCIL_AGENT_SEED", "7"))
    timeout = int(os.environ.get("FOS_TEST_COUNCIL_GENERATION_TIMEOUT", "120"))
    state = random.getstate()
    random.seed(seed)
    try:
        generated_agents = generate_agents_with_archetypes(
            total_agents=DEFAULT_AGENT_COUNT,
            demographics=COUNCIL_DEMOGRAPHICS,
            archetype_probabilities={},
            traits=COUNCIL_TRAITS,
            llm_client=llm_client,
            language="en",
            timeout=timeout,
        )
    finally:
        random.setstate(state)
    return [_generated_agent_to_scene_config(agent) for agent in generated_agents]


def _build_council_scene(config_agents: list[dict[str, object]]) -> CouncilExperimentScene:
    """Build a small fixed council scene with one hidden non-neighbour path."""
    agent_names = [str(agent["name"]) for agent in config_agents]
    return CouncilExperimentScene(
        ExperimentConfig(
            scenario_id="council_chamber",
            agents=config_agents,
            actions=[],
            parameters={
                "proposal_text": "Should the town fund a shared tool library?",
                "deliberation_rounds": 2,
                "voting_threshold": 0.5,
            },
            description="Council pilot test",
            social_network={"edges": [[agent_names[0], agent_names[1]], [agent_names[1], agent_names[2]]]},
            locale="en",
        )
    )


@pytest.mark.parametrize("visible_message,hidden_message", [("VISIBLE_BRIDGE_MESSAGE", "HIDDEN_CHAIN_TAIL_MESSAGE")])
def test_real_llm_council_prompt_uses_neighbour_visible_history_only(
    council_real_llm_client: CapturingLLMClient,
    visible_message: str,
    hidden_message: str,
) -> None:
    asyncio.run(
        _run_real_llm_council_prompt_uses_neighbour_visible_history_only(
            council_real_llm_client,
            visible_message,
            hidden_message,
        )
    )


async def _run_real_llm_council_prompt_uses_neighbour_visible_history_only(
    council_real_llm_client: CapturingLLMClient,
    visible_message: str,
    hidden_message: str,
) -> None:
    config_agents = _build_generated_council_agents(council_real_llm_client.delegate)
    scene = _build_council_scene(config_agents)
    scene.initialize(council_real_llm_client)
    assert scene.runner is not None
    assert scene.round_context_manager is scene.runner.context_manager
    council_real_llm_client.calls.clear()

    agent_names = [agent.name for agent in scene.agents]

    scene.round_context_manager.record_action_with_observers(
        agent_name=agent_names[1],
        action_name="speak",
        parameters={"message": visible_message},
        round_num=1,
        summary=f"{agent_names[1]} spoke: {visible_message}",
    )
    scene.round_context_manager.record_action_with_observers(
        agent_name=agent_names[2],
        action_name="speak",
        parameters={"message": hidden_message},
        round_num=1,
        summary=f"{agent_names[2]} spoke: {hidden_message}",
    )

    result = await scene.runner._prompt_agent(scene.agents[0], round_num=2)

    sent_prompts = [
        str(call["messages"][0]["content"])
        for call in council_real_llm_client.calls
    ]
    assert result.action_name in {"speak", "skip"}
    assert any(visible_message in prompt for prompt in sent_prompts)
    assert all(hidden_message not in prompt for prompt in sent_prompts)


def test_real_llm_council_deliberation_and_vote_rounds_are_parseable(
    council_real_llm_client: CapturingLLMClient,
) -> None:
    asyncio.run(_run_real_llm_council_deliberation_and_vote_rounds_are_parseable(council_real_llm_client))


async def _run_real_llm_council_deliberation_and_vote_rounds_are_parseable(
    council_real_llm_client: CapturingLLMClient,
) -> None:
    config_agents = _build_generated_council_agents(council_real_llm_client.delegate)
    scene = _build_council_scene(config_agents)
    emitted_events: list[tuple[str, dict]] = []
    scene.initialize(council_real_llm_client)

    deliberation_result = await scene.run_round(
        lambda event_type, data: emitted_events.append((event_type, data))
    )

    assert len(deliberation_result.actions) == 3
    assert all(action.success for action in deliberation_result.actions)
    assert all(action.action_name in {"speak", "skip"} for action in deliberation_result.actions)

    scene.cycle_phase = CouncilCyclePhase.VOTING
    scene.facilitator.transition_to_voting("Should the town fund a shared tool library?")
    scene.state.extensions["voting_started"] = True

    vote_result = await scene.run_round(
        lambda event_type, data: emitted_events.append((event_type, data))
    )

    assert len(vote_result.actions) == 3
    assert all(action.success for action in vote_result.actions)
    assert all(action.action_name in {"vote_yes", "vote_no", "abstain"} for action in vote_result.actions)
    assert any(event_type == "experiment_action" for event_type, _ in emitted_events)
