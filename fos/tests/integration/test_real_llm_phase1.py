import asyncio
import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import pytest

from fos.core.experiment.agent import ExperimentAgent
from fos.core.experiment.config import ExperimentConfig
from fos.core.experiment.controller import ExperimentController
from fos.core.experiment.game_configs import GameConfig, PRISONERS_DILEMMA
from fos.core.experiment.information_model import InformationModel
from fos.core.experiment.kernel import ExperimentKernel
from fos.core.experiment.round_context import RoundContextManager
from fos.core.experiment.runner import ExperimentRunner
from fos.core.experiment.scene import ExperimentScene
from fos.core.experiment.state import ExperimentState
from fos.core.llm.client import LLMClient
from fos.core.llm_config import LLMConfig


pytestmark = pytest.mark.real_llm


class CapturingLLMClient:
    def __init__(self, delegate):
        self.delegate = delegate
        self.provider = delegate.provider
        self.calls = []

    def chat(self, messages, json_mode=False):
        self.calls.append({"messages": messages, "json_mode": json_mode})
        return self.delegate.chat(messages, json_mode=json_mode)


def _real_llm_config():
    if os.environ.get("FOS_TEST_REAL_LLM") != "1":
        pytest.skip("FOS_TEST_REAL_LLM is not set")

    provider = os.environ.get("FOS_TEST_LLM_PROVIDER", "ollama")
    if provider != "ollama":
        pytest.skip(
            "Phase 1 real-LLM tests are Ollama-only. Set FOS_TEST_LLM_PROVIDER=ollama "
            "or omit it to use the Ollama default."
        )

    model = os.environ.get("FOS_TEST_LLM_MODEL", "")
    if not model:
        pytest.skip("FOS_TEST_LLM_MODEL is not set. Choose a locally installed Ollama model.")

    base_url = (
        os.environ.get("FOS_TEST_LLM_BASE_URL")
        or os.environ.get("OLLAMA_BASE_URL")
        or "http://localhost:11434"
    )

    return LLMConfig(
        dialect="ollama",
        model=model,
        base_url=base_url,
        temperature=float(os.environ.get("FOS_TEST_LLM_TEMPERATURE", "0.1")),
        max_tokens=int(os.environ.get("FOS_TEST_LLM_MAX_TOKENS", "256")),
    )


def _ollama_json_get(base_url: str, path: str) -> dict:
    url = base_url.rstrip("/") + path
    request = Request(url, headers={"Accept": "application/json"})
    try:
        with urlopen(request, timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        pytest.skip(f"Ollama is not reachable at {base_url}: {exc}")


def _ollama_model_names(base_url: str) -> set[str]:
    data = _ollama_json_get(base_url, "/api/tags")
    return {str(model["name"]) for model in data.get("models", [])}


def _ollama_has_model(requested_model: str, installed_models: set[str]) -> bool:
    if requested_model in installed_models:
        return True
    if ":" not in requested_model:
        return any(name.split(":", 1)[0] == requested_model for name in installed_models)
    return False


@pytest.fixture(scope="session")
def real_llm_delegate():
    config = _real_llm_config()
    installed_models = _ollama_model_names(config.base_url)
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

    try:
        structured_response = client.chat(
            [{"role": "user", "content": 'Return exactly one JSON object: {"action":"skip","message":null}'}],
            json_mode=True,
        )
        controller = ExperimentController(ExperimentKernel(), RoundContextManager())
        agent = ExperimentAgent(name="Preflight", properties={}, llm_config=LLMConfig(dialect="ollama"))
        custom_config = GameConfig(
            name="custom",
            description="Preflight custom JSON action schema.",
            action_type="discrete",
            actions=["speak", "skip"],
            payoff_type="none",
            grouping_mode="individual",
        )
        result = asyncio.run(
            controller.process_response(structured_response, agent, custom_config, client, round_num=0)
        )
        if not result.success:
            pytest.skip(
                f"Ollama model {config.model} failed structured JSON preflight: {result.error}. "
                f"Raw response: {structured_response}"
            )
    except Exception as exc:
        pytest.skip(f"Ollama model {config.model} failed structured JSON preflight: {exc}")

    return client


@pytest.fixture
def real_llm_client(real_llm_delegate):
    return CapturingLLMClient(real_llm_delegate)


def _custom_agents():
    return [
        {
            "name": "Alice",
            "properties": {"role": "neighborhood organizer"},
            "role_prompt": "You are Alice, a concise neighborhood organizer.",
            "llm_config": {},
        },
        {
            "name": "Bob",
            "properties": {"role": "shop owner"},
            "role_prompt": "You are Bob, a concise shop owner.",
            "llm_config": {},
        },
    ]


def test_real_llm_custom_scenario_v1_one_round(real_llm_client):
    asyncio.run(_run_real_llm_custom_scenario_v1_one_round(real_llm_client))


async def _run_real_llm_custom_scenario_v1_one_round(real_llm_client):
    events = []
    prompt = "Discuss whether the block should create a shared weekend cleanup plan. Keep any message under 20 words."
    scene = ExperimentScene(
        ExperimentConfig(
            agents=_custom_agents(),
            actions=[],
            parameters={"custom_prompt": prompt, "turn_ordering": "simultaneous"},
            description=prompt,
            scenario_id="custom",
            round_visibility="simultaneous",
            social_network={"edges": [["Alice", "Bob"]]},
            locale="en",
        )
    )
    scene.initialize(real_llm_client)
    result = await scene.run_round(lambda event_type, data: events.append((event_type, data)))

    assert len(real_llm_client.calls) == 2
    assert all(call["json_mode"] is True for call in real_llm_client.calls)
    assert len(result.actions) == 2
    assert scene.current_round == 1
    assert scene.state.round == 1
    assert len(scene.state.history) == 1
    assert len(events) == 2

    for action in result.actions:
        assert action.success is True
        assert action.action_name in {"speak", "skip"}
        if action.action_name == "speak":
            assert action.parameters["message"]
        if action.action_name == "skip":
            assert action.skipped is True

    first_prompt = real_llm_client.calls[0]["messages"][0]["content"]
    assert prompt in first_prompt
    assert "- speak:" in first_prompt
    assert "- skip:" in first_prompt
    assert '{"action": "speak", "message": "..."}' in first_prompt
    assert "cooperate" not in first_prompt
    assert "defect" not in first_prompt


def test_real_llm_prompt_uses_neighbor_visible_history_only(real_llm_client):
    asyncio.run(_run_real_llm_prompt_uses_neighbor_visible_history_only(real_llm_client))


async def _run_real_llm_prompt_uses_neighbor_visible_history_only(real_llm_client):
    agents = [
        ExperimentAgent(name="Alice", properties={}, llm_config={}),
        ExperimentAgent(name="Bob", properties={}, llm_config={}),
        ExperimentAgent(name="Charlie", properties={}, llm_config={}),
    ]
    game_config = GameConfig(
        name="custom",
        description="Custom prompt: discuss only information visible through your network.",
        action_type="discrete",
        actions=["speak", "skip"],
        action_descriptions={"speak": "Say one short message", "skip": "Pass"},
        payoff_type="none",
        grouping_mode="individual",
    )
    runner = ExperimentRunner(
        agents=agents,
        game_config=game_config,
        llm_client=real_llm_client,
        round_visibility="simultaneous",
        information_model=InformationModel(scope_type="neighborhood", include_scores=False, recent_window=3),
    )
    runner.set_scene_state({"graph": {"edges": [["Alice", "Bob"], ["Bob", "Charlie"]]}, "state": ExperimentState()})
    runner.context_manager.record_action_with_observers(
        agent_name="Bob",
        action_name="speak",
        parameters={"message": "VISIBLE_BRIDGE_MESSAGE"},
        round_num=1,
        summary="Bob spoke: VISIBLE_BRIDGE_MESSAGE",
    )
    runner.context_manager.record_action_with_observers(
        agent_name="Charlie",
        action_name="speak",
        parameters={"message": "HIDDEN_CHAIN_TAIL_MESSAGE"},
        round_num=1,
        summary="Charlie spoke: HIDDEN_CHAIN_TAIL_MESSAGE",
    )

    result = await runner._prompt_agent(agents[0], round_num=2)

    assert real_llm_client.calls
    sent_prompt = real_llm_client.calls[-1]["messages"][0]["content"]
    assert result.action_name in {"speak", "skip"}
    assert "VISIBLE_BRIDGE_MESSAGE" in sent_prompt
    assert "HIDDEN_CHAIN_TAIL_MESSAGE" not in sent_prompt
    assert "Your social network neighbors: Bob." in sent_prompt


@pytest.mark.parametrize(
    "game_config",
    [
        PRISONERS_DILEMMA,
        GameConfig(
            name="custom",
            description="Say a short view about whether to hold a community meeting.",
            action_type="discrete",
            actions=["speak", "skip"],
            action_descriptions={"speak": "Say one short message", "skip": "Pass"},
            payoff_type="none",
            grouping_mode="individual",
        ),
        GameConfig(
            name="coordination_probe",
            description="Choose one color for a simple coordination probe.",
            action_type="discrete",
            actions=["red", "blue"],
            action_descriptions={"red": "Choose red", "blue": "Choose blue"},
            payoff_type="feedback",
            grouping_mode="neighbor",
        ),
    ],
)
def test_real_llm_selects_only_allowed_actions(real_llm_client, game_config):
    asyncio.run(_run_real_llm_selects_only_allowed_actions(real_llm_client, game_config))


async def _run_real_llm_selects_only_allowed_actions(real_llm_client, game_config):
    agent = ExperimentAgent(name="Alice", properties={"role": "participant"}, llm_config={})
    runner = ExperimentRunner(
        agents=[agent],
        game_config=game_config,
        llm_client=real_llm_client,
        round_visibility="simultaneous",
        information_model=InformationModel(scope_type="self", include_scores=False),
    )

    result = await runner._prompt_agent(agent, round_num=1)

    assert result.success is True
    assert result.action_name in set(game_config.actions)
    if game_config.name == "custom" and result.action_name == "speak":
        assert result.parameters["message"]
