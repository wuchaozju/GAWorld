"""
Smoke tests for sociology scenarios with real Ollama LLM.

Tests the following sociology scenarios:
- Social Norm Disruption (group, none)
- Policy Erosion (individual, none, sequential)
- Echo Chamber (neighbor, none)
- Resource Scarcity (group, none)
"""

import pytest

from fos.core.llm_config import LLMConfig
from fos.core.experiment.game_configs import GameConfig
from fos.core.experiment.runner import ExperimentRunner
from fos.core.experiment.information_model import InformationModel

from tests.smoke_tests.utils import (
    SmokeTestOutput,
    build_experiment_agent,
)


# =============================================================================
# Scenario Config Builders
# =============================================================================

def build_social_norm_config() -> GameConfig:
    """Build Social Norm Disruption game config."""
    return GameConfig(
        name="social_norm_disruption",
        description=(
            "A new rule has been announced: All participants must comply with a new mandatory requirement.\n"
            "The norm has a strength level of 0.8 (0=very weak, 1=very strong).\n\n"
            "Your task is to decide how to respond to this new rule. You can:\n"
            "- Publicly comply with the rule\n"
            "- Covertly comply while privately resisting\n"
            "- Openly refuse or challenge the rule\n"
            "- Try to persuade others to join your position"
        ),
        action_type="discrete",
        actions=["comply_publicly", "comply_covertly_resist", "resist_openly", "persuade_others"],
        action_descriptions={
            "comply_publicly": "Visibly accept and follow the norm or directive",
            "comply_covertly_resist": "Formally comply but privately circumvent or ignore",
            "resist_openly": "Openly refuse or challenge the norm or directive",
            "persuade_others": "Convince others to adopt your position or action",
        },
        payoff_summary="",
        payoff_type="none",
        grouping_mode="group",
        payoff_config={},
    )


def build_policy_erosion_config() -> GameConfig:
    """Build Policy Erosion game config."""
    return GameConfig(
        name="policy_erosion",
        description=(
            "A 3-tier hierarchy must transmit a policy from top to bottom.\n"
            "At each level, subordinates may reinterpret or resist the directive.\n\n"
            "Policy: 'All employees must complete mandatory training by Friday'\n\n"
            "Your task: Decide how to handle the policy as it reaches you."
        ),
        action_type="discrete",
        actions=["transmit_faithfully", "reinterpret_downward", "comply_directive", "resist_quietly"],
        action_descriptions={
            "transmit_faithfully": "Pass the policy on exactly as received without changes",
            "reinterpret_downward": "Adapt or modify the policy when passing it down the chain",
            "comply_directive": "Accept and implement the instruction from above",
            "resist_quietly": "Formally comply but avoid real implementation",
        },
        payoff_summary="",
        payoff_type="none",
        grouping_mode="individual",
        payoff_config={},
    )


def build_echo_chamber_config() -> GameConfig:
    """Build Echo Chamber game config."""
    return GameConfig(
        name="echo_chamber",
        description=(
            "You have an initial opinion on a topic. You interact with others who may have similar or different views.\n"
            "You prefer connections with similar views, which may lead to polarization.\n\n"
            "Your task: Express your opinion and interact with others."
        ),
        action_type="discrete",
        actions=["express_opinion", "reinforce_ingroup", "share_content", "disengage"],
        action_descriptions={
            "express_opinion": "Share your current viewpoint on the topic",
            "reinforce_ingroup": "Engage with and amplify similar viewpoints",
            "share_content": "Share information reinforcing your position",
            "disengage": "Withdraw from engagement with opposing views",
        },
        payoff_summary="",
        payoff_type="none",
        grouping_mode="neighbor",
        payoff_config={},
    )


def build_resource_scarcity_config() -> GameConfig:
    """Build Resource Scarcity game config."""
    return GameConfig(
        name="resource_scarcity",
        description=(
            "A community has limited resources (100 units total).\n"
            "Agents must decide whether to cooperate by sharing or compete by hoarding.\n"
            "This tests trust and collective action.\n\n"
            "Your task: Decide how to manage your resources."
        ),
        action_type="discrete",
        actions=["share_resources", "hoard", "propose_trade", "form_contract"],
        action_descriptions={
            "share_resources": "Give some of your resources to another agent",
            "hoard": "Keep all resources for yourself",
            "propose_trade": "Offer to exchange resources",
            "form_contract": "Propose a formal cooperative agreement",
        },
        payoff_summary="",
        payoff_type="none",
        grouping_mode="group",
        payoff_config={},
    )


# =============================================================================
# Social Norm Disruption Tests
# =============================================================================

@pytest.mark.asyncio
async def test_social_norm_disruption(default_llm_client, output_dir):
    """Test Social Norm Disruption scenario with 4 sociology actions."""
    game_config = build_social_norm_config()
    llm_config = LLMConfig(dialect="ollama", model="phi4-mini:latest", base_url="http://localhost:11434")

    agents = [
        build_experiment_agent("HighStatus1", llm_config, role_prompt="You are a high-status individual who supports the new rule."),
        build_experiment_agent("HighStatus2", llm_config, role_prompt="You are a high-status individual who is skeptical of the new rule."),
        build_experiment_agent("LowStatus1", llm_config, role_prompt="You are a low-status individual who must follow orders."),
        build_experiment_agent("LowStatus2", llm_config, role_prompt="You are a low-status individual who resents the new rule."),
    ]

    filename = "social_norm_disruption_phi4-mini_basic.txt"
    filepath = output_dir / filename

    with SmokeTestOutput(filepath, "social_norm_disruption", "phi4-mini", "basic") as out:
        out.write_config({
            "grouping_mode": "group",
            "payoff_type": "none",
            "agents": ["HighStatus1", "HighStatus2", "LowStatus1", "LowStatus2"],
            "actions": ["comply_publicly", "comply_covertly_resist", "resist_openly", "persuade_others"],
        })

        runner = ExperimentRunner(
            agents=agents,
            game_config=game_config,
            llm_client=default_llm_client,
            round_visibility="simultaneous",
        )

        round_results = await runner.run(max_rounds=1)

        out.write_round_header(1)
        for action in round_results[0].actions:
            out.write_action_summary(action.agent_name, action.action_name, action.parameters, None)

        final_scores = {agent.name: agent.score for agent in agents}
        errors = [a.error for a in round_results[0].actions if a.error]

        out.write_summary(final_scores, errors)

    assert len(round_results) == 1
    assert len(round_results[0].actions) == 4
    valid_actions = ["comply_publicly", "comply_covertly_resist", "resist_openly", "persuade_others", "skip"]
    for action in round_results[0].actions:
        assert action.action_name in valid_actions


# =============================================================================
# Policy Erosion Tests
# =============================================================================

@pytest.mark.asyncio
async def test_policy_erosion_sequential(default_llm_client, output_dir):
    """Test Policy Erosion with sequential hierarchy."""
    game_config = build_policy_erosion_config()
    llm_config = LLMConfig(dialect="ollama", model="phi4-mini:latest", base_url="http://localhost:11434")

    agents = [
        build_experiment_agent("Executive", llm_config, role_prompt="You are the top-level executive who issues the policy."),
        build_experiment_agent("Manager", llm_config, role_prompt="You are a middle manager who receives orders from above."),
        build_experiment_agent("Worker", llm_config, role_prompt="You are a frontline worker who must implement policies."),
    ]

    filename = "policy_erosion_phi4-mini_sequential.txt"
    filepath = output_dir / filename

    with SmokeTestOutput(filepath, "policy_erosion", "phi4-mini", "sequential") as out:
        out.write_config({
            "grouping_mode": "individual",
            "payoff_type": "none",
            "interaction_mode": "sequential",
            "agents": ["Executive", "Manager", "Worker"],
            "actions": ["transmit_faithfully", "reinterpret_downward", "comply_directive", "resist_quietly"],
        })

        runner = ExperimentRunner(
            agents=agents,
            game_config=game_config,
            llm_client=default_llm_client,
            round_visibility="sequential",  # Sequential for hierarchy
        )

        round_results = await runner.run(max_rounds=1)

        out.write_round_header(1)
        for action in round_results[0].actions:
            out.write_action_summary(action.agent_name, action.action_name, action.parameters, None)

        final_scores = {agent.name: agent.score for agent in agents}
        errors = [a.error for a in round_results[0].actions if a.error]

        out.write_summary(final_scores, errors)

    assert len(round_results) == 1
    assert len(round_results[0].actions) == 3


# =============================================================================
# Echo Chamber Tests
# =============================================================================

@pytest.mark.asyncio
async def test_echo_chamber_neighbor_visibility(default_llm_client, output_dir):
    """Test Echo Chamber with neighbor-based visibility."""
    game_config = build_echo_chamber_config()
    llm_config = LLMConfig(dialect="ollama", model="phi4-mini:latest", base_url="http://localhost:11434")

    agents = [
        build_experiment_agent("ProAgent1", llm_config, role_prompt="You strongly support the topic."),
        build_experiment_agent("ProAgent2", llm_config, role_prompt="You moderately support the topic."),
        build_experiment_agent("AntiAgent1", llm_config, role_prompt="You strongly oppose the topic."),
        build_experiment_agent("AntiAgent2", llm_config, role_prompt="You moderately oppose the topic."),
    ]

    # Network: Pro agents connected, Anti agents connected, one bridge
    graph = {
        "edges": [
            ("ProAgent1", "ProAgent2"),
            ("AntiAgent1", "AntiAgent2"),
            ("ProAgent2", "AntiAgent1"),  # Bridge
        ]
    }

    information_model = InformationModel(
        scope_type="neighborhood",
        pairing_fn=None,
        context_budget_chars=0,
    )

    filename = "echo_chamber_phi4-mini_neighbor.txt"
    filepath = output_dir / filename

    with SmokeTestOutput(filepath, "echo_chamber", "phi4-mini", "neighbor") as out:
        out.write_config({
            "grouping_mode": "neighbor",
            "payoff_type": "none",
            "agents": ["ProAgent1", "ProAgent2", "AntiAgent1", "AntiAgent2"],
            "actions": ["express_opinion", "reinforce_ingroup", "share_content", "disengage"],
            "graph": "polarized with bridge",
        })

        runner = ExperimentRunner(
            agents=agents,
            game_config=game_config,
            llm_client=default_llm_client,
            round_visibility="simultaneous",
            information_model=information_model,
        )

        runner.set_scene_state({"graph": graph})
        round_results = await runner.run(max_rounds=1)

        out.write_round_header(1)
        for action in round_results[0].actions:
            out.write_action_summary(action.agent_name, action.action_name, action.parameters, None)

        final_scores = {agent.name: agent.score for agent in agents}
        errors = [a.error for a in round_results[0].actions if a.error]

        out.write_summary(final_scores, errors)

    assert len(round_results) == 1
    assert len(round_results[0].actions) == 4


# =============================================================================
# Resource Scarcity Tests
# =============================================================================

@pytest.mark.asyncio
async def test_resource_scarcity_sharing(default_llm_client, output_dir):
    """Test Resource Scarcity with sharing actions."""
    game_config = build_resource_scarcity_config()
    llm_config = LLMConfig(dialect="ollama", model="phi4-mini:latest", base_url="http://localhost:11434")

    agents = [
        build_experiment_agent("Community1", llm_config, role_prompt="You are a community-minded person who values cooperation."),
        build_experiment_agent("Community2", llm_config, role_prompt="You are practical and willing to share if others do."),
        build_experiment_agent("Individualist", llm_config, role_prompt="You prioritize your own needs over the group."),
    ]

    filename = "resource_scarcity_phi4-mini_sharing.txt"
    filepath = output_dir / filename

    with SmokeTestOutput(filepath, "resource_scarcity", "phi4-mini", "sharing") as out:
        out.write_config({
            "grouping_mode": "group",
            "payoff_type": "none",
            "agents": ["Community1", "Community2", "Individualist"],
            "actions": ["share_resources", "hoard", "propose_trade", "form_contract"],
            "total_resources": 100,
        })

        runner = ExperimentRunner(
            agents=agents,
            game_config=game_config,
            llm_client=default_llm_client,
            round_visibility="simultaneous",
        )

        round_results = await runner.run(max_rounds=1)

        out.write_round_header(1)
        for action in round_results[0].actions:
            out.write_action_summary(action.agent_name, action.action_name, action.parameters, None)

        final_scores = {agent.name: agent.score for agent in agents}
        errors = [a.error for a in round_results[0].actions if a.error]

        out.write_summary(final_scores, errors)

    assert len(round_results) == 1
    assert len(round_results[0].actions) == 3
