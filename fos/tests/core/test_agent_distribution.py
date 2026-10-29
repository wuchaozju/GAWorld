"""
Smoke tests for agent LLM distribution and role preservation.

Verifies that:
1. Agent generation produces diverse roles (no fallbacks)
2. LLM distribution assigns different models to agents via provider_clients
3. Role prompts are preserved from generation through prompt building
4. Provider distribution is even across providers
5. Fallback roles are detectable

Run with:
    pytest tests/core/test_agent_distribution.py -v
"""

from unittest.mock import MagicMock

from fos.core.llm_config import LLMConfig
from fos.core.llm.client import LLMClient
from fos.core.experiment.config import ExperimentConfig
from fos.core.experiment.scene import ExperimentScene
from fos.core.experiment.game_configs import GameConfig
from fos.core.experiment.prompt_builder import build_agent_description, build_prompt
from fos.core.llm.generation import (
    generate_archetypes_from_demographics,
    generate_agents_with_archetypes,
)


# --- Known fallback roles from locales/en.json ---
FALLBACK_ROLES = {"Citizen", "Worker", "Professional", "Student", "Other"}

# Frontend sends llm_config with unknown dialect "backend" — this triggers
# the provider_id lookup path in ExperimentScene.initialize
FRONTEND_LLM_CONFIG = {"provider": "backend"}


def _make_llm_client(model: str, dialect: str = "ollama") -> LLMClient:
    """Create a real LLMClient with the given model for testing."""
    cfg = LLMConfig(
        dialect=dialect,
        api_key="test",
        model=model,
        base_url="http://localhost:11434",
    )
    return LLMClient(cfg)


def _make_provider_clients(models: list[str]) -> dict:
    """Build a provider_clients dict mapping provider_id -> LLMClient.

    Uses provider IDs starting at 16 to match real DB-assigned IDs
    (avoids the `or` falsy-zero bug in scene.py).
    """
    clients = {}
    for i, model in enumerate(models):
        clients[16 + i] = _make_llm_client(model)
    return clients


def _make_agent_config(n_agents: int, n_providers: int) -> list[dict]:
    """Generate agent config dicts matching real frontend output.

    Frontend sends llm_config with dialect "backend" (unknown),
    which triggers the provider_id lookup path in scene.py.
    Provider IDs start at 16 to match real DB-assigned IDs.
    """
    agents = []
    for i in range(n_agents):
        provider_id = 16 + (i % n_providers)
        agents.append({
            "name": f"Agent {i + 1}",
            "properties": {
                "archetype_id": f"arch_{i % 3}",
                "archetype_label": f"Group {i % 3}",
                "Trust": 50 + i,
                "provider_id": provider_id,
            },
            "llm_config": FRONTEND_LLM_CONFIG,
            "profile": (
                f"You are a TestRole{i + 1}. A diverse agent for testing. "
                "When responding, think and react as this person would — "
                f"not as a neutral assistant.\nTrust: {50 + i} (0-100)"
            ),
            "provider_id": provider_id,
        })
    return agents


class TestAgentGeneration:
    """Tests for the agent generation pipeline."""

    def test_generate_archetypes_creates_cross_product(self):
        """Archetypes should be the cross-product of demographics."""
        demographics = [
            {"name": "Age", "categories": ["18-30", "31-50"]},
            {"name": "Income", "categories": ["High", "Low"]},
        ]
        archetypes = generate_archetypes_from_demographics(demographics)
        assert len(archetypes) == 4
        labels = {a["label"] for a in archetypes}
        assert "Age: 18-30 | Income: High" in labels
        assert "Age: 31-50 | Income: Low" in labels

    def test_generate_archetypes_equal_probability(self):
        """All archetypes should have equal probability."""
        demographics = [
            {"name": "Age", "categories": ["18-30", "31-50", "51+"]},
        ]
        archetypes = generate_archetypes_from_demographics(demographics)
        probs = {a["probability"] for a in archetypes}
        assert len(probs) == 1
        assert abs(list(probs)[0] - 1.0 / 3) < 0.01

    def test_fallback_roles_are_known(self):
        """Verify we know all fallback roles for detection."""
        assert FALLBACK_ROLES == {"Citizen", "Worker", "Professional", "Student", "Other"}

    def test_generated_agents_have_diverse_roles(self):
        """Mock LLM should produce diverse roles, not fallbacks."""
        mock_client = MagicMock()
        mock_client.chat.return_value = (
            '{"description": "A test person.", "roles": '
            '["Diplomat", "Engineer", "Artist", "Merchant", "Scholar"]}'
        )

        agents = generate_agents_with_archetypes(
            total_agents=25,
            demographics=[{"name": "Age", "categories": ["Young", "Old"]}],
            archetype_probabilities=None,
            traits=[{"name": "Trust", "mean": 50, "std": 15}],
            llm_client=mock_client,
        )

        assert len(agents) == 25
        roles = {a["role"] for a in agents}
        assert roles.issubset({"Diplomat", "Engineer", "Artist", "Merchant", "Scholar"})
        assert not roles.intersection(FALLBACK_ROLES)

    def test_generated_agents_have_profiles(self):
        """Every generated agent must have a non-empty profile."""
        mock_client = MagicMock()
        mock_client.chat.return_value = (
            '{"description": "A bold leader.", "roles": ["Leader", "Follower"]}'
        )

        agents = generate_agents_with_archetypes(
            total_agents=10,
            demographics=[{"name": "Age", "categories": ["Young"]}],
            archetype_probabilities=None,
            traits=[{"name": "Trust", "mean": 50, "std": 10}],
            llm_client=mock_client,
        )

        for agent in agents:
            assert agent["profile"], f"Agent {agent['name']} has empty profile"
            assert "You are a" in agent["profile"]
            assert agent["role"] not in FALLBACK_ROLES

    def test_fallback_detection_when_llm_fails(self):
        """When LLM returns empty, fallback roles should be detectable."""
        mock_client = MagicMock()
        mock_client.chat.return_value = ""

        agents = generate_agents_with_archetypes(
            total_agents=5,
            demographics=[{"name": "Age", "categories": ["Young"]}],
            archetype_probabilities=None,
            traits=[{"name": "Trust", "mean": 50, "std": 10}],
            llm_client=mock_client,
            timeout=1,
        )

        roles = {a["role"] for a in agents}
        assert roles.issubset(FALLBACK_ROLES), f"Expected fallback roles, got: {roles}"

    def test_demographic_generation_without_llm_uses_editable_fallback_agents(self):
        """Provider-free creation should still produce editable demographic agents."""
        agents = generate_agents_with_archetypes(
            total_agents=3,
            demographics=[{"name": "Age", "categories": ["Young"]}],
            archetype_probabilities=None,
            traits=[{"name": "Trust", "mean": 50, "std": 10}],
            llm_client=None,
        )

        assert len(agents) == 3
        for agent in agents:
            assert agent["name"]
            assert agent["role"] in FALLBACK_ROLES
            assert agent["profile"]
            assert agent["properties"]["Age"] == "Young"
            assert "Trust" in agent["properties"]


class TestLLMDistribution:
    """Tests for LLM client distribution across agents."""

    def test_provider_clients_assigned_to_agents(self):
        """Agents with provider_id should get their assigned LLM client."""
        provider_clients = _make_provider_clients(["model-a", "model-b", "model-c"])
        # Use _make_agent_config which includes llm_config (matches frontend)
        agent_config = _make_agent_config(n_agents=6, n_providers=3)

        config = ExperimentConfig(
            agents=agent_config,
            actions=[{"name": "test"}],
            scenario_id="public_goods",
        )
        scene = ExperimentScene(config)
        default_client = _make_llm_client("default-model")
        scene.initialize(default_client, provider_clients=provider_clients)

        # Verify each agent got the right client
        for agent in scene.agents:
            client = scene._agent_llm_clients[agent.name]
            pid = agent.provider_id
            assert pid is not None, f"{agent.name} has no provider_id"
            assert client is provider_clients[pid], (
                f"{agent.name} with provider_id={pid} got wrong client"
            )

    def test_no_agent_uses_default_when_providers_available(self):
        """When provider_clients exist, no agent should use the default client."""
        provider_clients = _make_provider_clients(["model-a", "model-b"])
        agent_config = _make_agent_config(n_agents=4, n_providers=2)

        config = ExperimentConfig(
            agents=agent_config,
            actions=[{"name": "test"}],
            scenario_id="public_goods",
        )
        scene = ExperimentScene(config)
        default_client = _make_llm_client("default-model")
        scene.initialize(default_client, provider_clients=provider_clients)

        for agent in scene.agents:
            client = scene._agent_llm_clients[agent.name]
            assert client is not default_client, (
                f"{agent.name} is using the default client instead of its provider client"
            )

    def test_distribution_is_even(self):
        """With round-robin provider_ids, distribution should be even."""
        n_agents = 200
        n_providers = 5
        provider_clients = _make_provider_clients([f"model-{i}" for i in range(n_providers)])
        agent_config = _make_agent_config(n_agents=n_agents, n_providers=n_providers)

        config = ExperimentConfig(
            agents=agent_config,
            actions=[{"name": "test"}],
            scenario_id="public_goods",
        )
        scene = ExperimentScene(config)
        default_client = _make_llm_client("default-model")
        scene.initialize(default_client, provider_clients=provider_clients)

        model_counts: dict[str, int] = {}
        for agent in scene.agents:
            client = scene._agent_llm_clients[agent.name]
            model = client.provider.model
            model_counts[model] = model_counts.get(model, 0) + 1

        assert len(model_counts) == n_providers, (
            f"Expected {n_providers} distinct models, got {len(model_counts)}"
        )
        expected_per_model = n_agents // n_providers
        for model, count in model_counts.items():
            assert count == expected_per_model, (
                f"Model {model}: expected {expected_per_model} agents, got {count}"
            )

    def test_actual_model_name_matches_provider(self):
        """The actual model name on the LLM client should match the provider config."""
        provider_clients = {
            16: _make_llm_client("qwen3:4b"),
            17: _make_llm_client("gemma3:4b"),
            18: _make_llm_client("ministral-3:3b"),
        }
        agent_config = [
            {"name": "A1", "properties": {"provider_id": 16}, "provider_id": 16,
             "llm_config": FRONTEND_LLM_CONFIG, "profile": "You are a Tester."},
            {"name": "A2", "properties": {"provider_id": 17}, "provider_id": 17,
             "llm_config": FRONTEND_LLM_CONFIG, "profile": "You are a Checker."},
            {"name": "A3", "properties": {"provider_id": 18}, "provider_id": 18,
             "llm_config": FRONTEND_LLM_CONFIG, "profile": "You are a Verifier."},
        ]

        config = ExperimentConfig(agents=agent_config, actions=[{"name": "test"}])
        scene = ExperimentScene(config)
        scene.initialize(_make_llm_client("default"), provider_clients=provider_clients)

        expected = {"A1": "qwen3:4b", "A2": "gemma3:4b", "A3": "ministral-3:3b"}
        for agent in scene.agents:
            client = scene._agent_llm_clients[agent.name]
            actual_model = client.provider.model
            assert actual_model == expected[agent.name], (
                f"{agent.name}: expected model '{expected[agent.name]}', got '{actual_model}'"
            )


class TestRolePromptPreservation:
    """Tests that role_prompt survives from generation to prompt building."""

    def test_role_prompt_used_in_prompt(self):
        """build_agent_description should use role_prompt when provided."""
        role_prompt = "You are a Diplomatic Envoy. Skilled in negotiation."
        result = build_agent_description(
            agent_properties={"Trust": 70},
            role_prompt=role_prompt,
            agent_name="Agent 1",
        )
        assert result == role_prompt

    def test_fallback_to_properties_without_role_prompt(self):
        """Without role_prompt, build from properties."""
        result = build_agent_description(
            agent_properties={"Trust": 70},
            role_prompt=None,
            agent_name="Agent 1",
        )
        assert "Trust" in result
        assert "70" in result

    def test_scene_preserves_role_prompt(self):
        """ExperimentScene should pass profile through as role_prompt."""
        profile_text = "You are a Quantum Researcher. Pushing boundaries of physics."
        agent_config = [{
            "name": "TestAgent",
            "properties": {"Trust": 50},
            "profile": profile_text,
        }]

        config = ExperimentConfig(agents=agent_config, actions=[{"name": "test"}])
        scene = ExperimentScene(config)
        scene.initialize(_make_llm_client("test-model"), provider_clients={})

        agent = scene.agents[0]
        assert agent.role_prompt == profile_text, (
            f"role_prompt mismatch: expected '{profile_text}', got '{agent.role_prompt}'"
        )

    def test_role_prompt_in_final_prompt(self):
        """The final prompt should contain the role prompt text."""
        profile_text = "You are a Maverick Trader. High risk, high reward."
        agent_config = [{
            "name": "TestAgent",
            "properties": {"Trust": 50},
            "profile": profile_text,
        }]

        config = ExperimentConfig(
            agents=agent_config,
            actions=[{"name": "test"}],
            description="Test scenario.",
        )
        scene = ExperimentScene(config)
        scene.initialize(_make_llm_client("test-model"), provider_clients={})

        game_config = GameConfig(
            name="test",
            description="Test game.",
            actions=["test"],
            action_type="discrete",
        )

        prompt = build_prompt(
            agent=scene.agents[0],
            game_config=game_config,
            context_summary="Round 1.",
            include_section_markers=True,
        )

        assert "Maverick Trader" in prompt, (
            f"Role text missing from final prompt. Prompt starts with:\n{prompt[:300]}"
        )

    def test_fallback_role_detection(self):
        """Detect if fallback roles leaked into prompts."""
        fallback_prompt = "You are a Citizen. Individual with background: Age: 18-30"
        result = build_agent_description(
            agent_properties={},
            role_prompt=fallback_prompt,
            agent_name="Agent 1",
        )
        has_fallback = any(f"You are a {fb}." in result for fb in FALLBACK_ROLES)
        has_fallback_desc = "Individual with background:" in result
        assert has_fallback or has_fallback_desc, "Fallback detection should identify generic prompts"
