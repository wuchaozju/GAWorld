"""These tests check the real council startup path and the discussion startup path.

This file makes sure the backend can build the right scene for each scenario.
The helper builds a fake saved simulation record.
The first test checks council chamber uses the council scene and keeps working.
The second test checks open discussion still uses the normal experiment scene.
"""

import asyncio
from types import SimpleNamespace

from fos.backend.services import simtree_runtime
from fos.core.experiment.config import ExperimentConfig
from fos.core.experiment.scene import ExperimentScene
from fos.core.experiment.scenes.council_experiment import (
    CouncilCyclePhase,
    CouncilExperimentScene,
)


def _make_sim_record(scenario_id: str) -> SimpleNamespace:
    """Build a small fake simulation record for runtime tree tests."""
    return SimpleNamespace(
        id=f"{scenario_id}-sim",
        scene_type="experiment_template",
        name=scenario_id,
        description="test simulation",
        notes="",
        latest_state=None,
        scene_config={
            "generic_config": {
                "scenario_id": scenario_id,
                "description": "Talk about a budget proposal.",
                "parameters": {
                    "proposal_text": "Build a new library.",
                    "deliberation_rounds": 2,
                    "voting_threshold": 0.5,
                    "topic": "What should the group do?",
                },
                "social_network": {"edges": []},
                "locale": "en",
            }
        },
        agent_config={
            "agents": [
                {"name": "Alice", "role_prompt": "You are Alice."},
                {"name": "Bob", "role_prompt": "You are Bob."},
                {"name": "Cara", "role_prompt": "You are Cara."},
            ]
        },
    )


def _make_council_scene() -> CouncilExperimentScene:
    """Build a small council scene directly for focused phase tests."""
    return CouncilExperimentScene(
        ExperimentConfig(
            scenario_id="council",
            agents=[
                {"name": "Alice", "role_prompt": "You are Alice."},
                {"name": "Bob", "role_prompt": "You are Bob."},
            ],
            actions=[],
            parameters={
                "proposal_text": "Build a new library.",
                "deliberation_rounds": 2,
                "voting_threshold": 0.5,
            },
            description="Council test",
            locale="en",
            social_network={"edges": [("Alice", "Bob")]},
        )
    )


def test_council_chamber_runtime_builds_the_council_scene() -> None:
    """Council chamber should build the council scene through runtime startup."""
    tree = simtree_runtime._build_tree_for_sim(_make_sim_record("council_chamber"), clients={})

    scene = tree.nodes[tree.root]["sim"].scene

    assert isinstance(scene, CouncilExperimentScene)
    assert scene.config.scenario_id == "council_chamber"
    assert scene.get_scene_actions("Alice") == ["speak", "skip"]
    assert "Current Phase" in scene.get_agent_status_prompt("Alice")


def test_council_scene_switches_actions_when_voting_starts() -> None:
    """Council scene should show vote actions during the voting phase."""
    scene = _make_council_scene()

    assert scene.get_scene_actions("Alice") == ["speak", "skip"]

    scene.cycle_phase = CouncilCyclePhase.VOTING

    assert scene.get_scene_actions("Alice") == ["vote_yes", "vote_no", "abstain"]
    assert "Current Phase: voting" in scene.get_agent_status_prompt("Alice")


def test_council_voting_prompt_hides_speak_and_skip_actions() -> None:
    """Voting prompts should show only vote actions, not deliberation actions."""
    scene = _make_council_scene()

    class CapturingLlm:
        """Small LLM stub that records the prompt and returns one vote action."""

        def __init__(self) -> None:
            self.messages: list[list[dict[str, str]]] = []

        def chat(self, messages, json_mode=False):
            _ = json_mode
            self.messages.append(messages)
            return '{"action": "vote_yes"}'

    llm = CapturingLlm()
    scene.initialize(llm)
    scene.cycle_phase = CouncilCyclePhase.VOTING
    scene.facilitator.transition_to_voting("Build a new library.")
    scene.state.extensions["voting_started"] = True

    asyncio.run(scene.runner._prompt_agent(scene.agents[0], round_num=2))
    prompt = llm.messages[0][0]["content"]

    assert 'Valid actions: "vote_yes", "vote_no", "abstain"' in prompt
    assert "- speak:" not in prompt
    assert "- skip:" not in prompt


def test_council_prompt_hides_explicit_social_network_section() -> None:
    """Council prompts should rely on filtered context instead of a neighbor list."""
    scene = _make_council_scene()

    class CapturingLlm:
        """Small LLM stub that records the prompt and returns one action."""

        def __init__(self) -> None:
            self.messages: list[list[dict[str, str]]] = []

        def chat(self, messages, json_mode=False):
            _ = json_mode
            self.messages.append(messages)
            return '{"action": "skip"}'

    llm = CapturingLlm()
    scene.initialize(llm)
    scene.round_context_manager.record_action_with_observers(
        agent_name="Bob",
        action_name="speak",
        parameters={"message": "Visible to Alice"},
        round_num=1,
        summary="Bob spoke: Visible to Alice",
    )

    asyncio.run(scene.runner._prompt_agent(scene.agents[0], round_num=2))
    prompt = llm.messages[0][0]["content"]

    assert "Visible to Alice" in prompt
    assert "## Your Social Network" not in prompt
    assert "Your social network neighbors:" not in prompt


def test_council_chamber_runtime_prompts_all_five_agents() -> None:
    """Council chamber should not drop the fifth agent as an odd player out."""
    record = _make_sim_record("council_chamber")
    record.agent_config["agents"] = [
        {"name": "Agent1", "role_prompt": "You are Agent1."},
        {"name": "Agent2", "role_prompt": "You are Agent2."},
        {"name": "Agent3", "role_prompt": "You are Agent3."},
        {"name": "Agent4", "role_prompt": "You are Agent4."},
        {"name": "Agent5", "role_prompt": "You are Agent5."},
    ]
    tree = simtree_runtime._build_tree_for_sim(record, clients={})
    scene = tree.nodes[tree.root]["sim"].scene

    class StubLlm:
        """Small LLM stub that always skips cleanly."""

        def chat(self, messages, json_mode=False):
            _ = messages, json_mode
            return '{"action": "skip"}'

    scene.initialize(StubLlm())
    result = asyncio.run(scene.run_round(lambda event_type, data: None))

    assert len(result.actions) == 5
    assert [action.agent_name for action in result.actions] == [
        "Agent1",
        "Agent2",
        "Agent3",
        "Agent4",
        "Agent5",
    ]


def test_open_discussion_runtime_builds_the_normal_scene() -> None:
    """Open discussion should still build the normal experiment scene."""
    tree = simtree_runtime._build_tree_for_sim(_make_sim_record("open_discussion"), clients={})

    scene = tree.nodes[tree.root]["sim"].scene

    assert isinstance(scene, ExperimentScene)
    assert not isinstance(scene, CouncilExperimentScene)


def test_council_prior_round_context_hides_non_neighbour_speech() -> None:
    """Council context should only show prior speech from visible neighbours."""
    scene = CouncilExperimentScene(
        ExperimentConfig(
            scenario_id="council",
            agents=[
                {"name": "Alice", "role_prompt": "You are Alice."},
                {"name": "Bob", "role_prompt": "You are Bob."},
                {"name": "Cara", "role_prompt": "You are Cara."},
            ],
            actions=[],
            parameters={
                "proposal_text": "Build a new library.",
                "deliberation_rounds": 2,
                "voting_threshold": 0.5,
            },
            description="Council test",
            locale="en",
            social_network={"edges": [("Alice", "Bob")]},
        )
    )

    scene.round_context_manager.record_action_with_observers(
        agent_name="Cara",
        action_name="speak",
        parameters={"message": "Keep this private."},
        round_num=1,
        summary="Cara spoke: Keep this private.",
    )

    context = scene.get_prior_round_context("Alice")

    assert "Cara spoke" not in context


def test_council_initialize_shares_one_context_manager_with_runner() -> None:
    """Council prompts and handlers should write to the same visibility log."""
    scene = _make_council_scene()

    class StubLlm:
        """Small LLM stub that always skips cleanly."""

        def chat(self, messages, json_mode=False):
            _ = messages, json_mode
            return '{"action": "skip"}'

    scene.initialize(StubLlm())

    assert scene.runner is not None
    assert scene.round_context_manager is scene.runner.context_manager
