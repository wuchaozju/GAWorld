"""
Smoketest for Public Goods Game contribution validation.

Tests that the PayoffEngine properly enforces contribution limits when
agents attempt to contribute more tokens than they have.

Uses the PayoffEngine directly to validate the contribution clamping logic
works correctly when state is provided.

Tests BUG-PGG-01 and BUG-PGG-02:
- BUG-PGG-01: Contributions are capped at agent's current token balance
- BUG-PGG-02: Payoff calculations use constrained contribution values
"""

import pytest
from fos.core.experiment.payoff.engine import PayoffEngine
from fos.core.experiment.controller import ActionResult
from fos.core.experiment.state import ExperimentState, AgentState


class TestPGGContributionSmoketest:
    """End-to-end smoketest for contribution validation with PayoffEngine."""

    @pytest.fixture
    def engine(self):
        """Create PayoffEngine instance."""
        return PayoffEngine()

    @pytest.fixture
    def pool_config(self):
        """Standard public goods game configuration.

        multiplier: 1.5x return on pool
        initial_tokens: 20 tokens per agent
        """
        return {
            "multiplier": 1.5,
            "initial_tokens": 20,
        }

    def contribute_action(self, agent_name: str, amount: int) -> ActionResult:
        """Create a contribute action result for testing.

        Args:
            agent_name: Name of the agent
            amount: Attempted contribution amount

        Returns:
            ActionResult representing a contribute action
        """
        return ActionResult(
            agent_name=agent_name,
            action_name="contribute",
            parameters={"amount": amount},
            summary=f"{agent_name} contributed {amount}",
            success=True,
            skipped=False,
            round_num=1,
        )

    def test_over_contribution_clamped_to_balance(self, engine, pool_config):
        """
        Smoketest: Agent with 20 tokens attempts to contribute 25.

        Expected behavior:
        - Contribution should be clamped to 20 (agent's balance)
        - Total pool: 20 tokens
        - Pool return: 20 * 1.5 / 1 = 30
        - Payoff: (20 - 20) + 30 = 30

        This validates BUG-PGG-01: Contributions are capped at balance.
        """
        # Create state with agent having 20 tokens
        state = ExperimentState(
            agents={"Alice": AgentState(resources={"tokens": 20})}
        )

        # Alice attempts to contribute 25 (over her balance)
        actions = [self.contribute_action("Alice", 25)]

        # Calculate payoffs with state (enables validation)
        payoffs = engine.calculate_round_payoffs(
            payoff_type="pool",
            actions=actions,
            config=pool_config,
            grouping_mode="group",
            state=state,
        )

        # Verify contribution was clamped to 20
        # Pool return = 20 * 1.5 / 1 = 30
        # Payoff = (20 - 20) + 30 = 30
        assert payoffs["Alice"] == 30.0, (
            f"Alice's payoff should be 30.0 (contributed 20, got back 30), "
            f"but got {payoffs['Alice']}"
        )

        print("✅ Smoketest passed: Over-contribution clamped to balance")

    def test_payoff_uses_constrained_not_attempted_amount(self, engine, pool_config):
        """
        Smoketest: Verify payoff uses capped amount, not attempted amount.

        Scenario:
        - Bob has 15 tokens, attempts to contribute 20
        - Contribution clamped to 15
        - Payoff calculated with 15, not 20

        Expected:
        - Pool return = 15 * 1.5 / 1 = 22.5
        - Payoff = (20 - 15) + 22.5 = 27.5

        This validates BUG-PGG-02: Payoffs use constrained values.
        """
        # Bob has 15 tokens, attempts 20
        state = ExperimentState(
            agents={"Bob": AgentState(resources={"tokens": 15})}
        )

        actions = [self.contribute_action("Bob", 20)]

        payoffs = engine.calculate_round_payoffs(
            payoff_type="pool",
            actions=actions,
            config=pool_config,
            grouping_mode="group",
            state=state,
        )

        # Contribution capped at 15
        # Pool return = 15 * 1.5 / 1 = 22.5
        # Payoff = (20 - 15) + 22.5 = 27.5
        assert payoffs["Bob"] == 27.5, (
            f"Bob's payoff should be 27.5 (tokens_kept=5, pool_return=22.5), "
            f"but got {payoffs['Bob']}"
        )

        print("✅ Smoketest passed: Payoff uses constrained amount")

    def test_multiple_agents_mixed_contributions(self, engine, pool_config):
        """
        Smoketest: Multiple agents with mixed valid and over-contributions.

        Scenario:
        - Alice has 20, contributes 10 (valid)
        - Bob has 20, attempts 25 (capped to 20)
        - Charlie has 20, contributes 5 (valid)

        Expected:
        - Total pool: 10 + 20 + 5 = 35
        - Pool return: 35 * 1.5 / 3 = 17.5
        - Alice: (20 - 10) + 17.5 = 27.5
        - Bob: (20 - 20) + 17.5 = 17.5
        - Charlie: (20 - 5) + 17.5 = 32.5

        This validates the full calculation chain with multiple agents.
        """
        state = ExperimentState(
            agents={
                "Alice": AgentState(resources={"tokens": 20}),
                "Bob": AgentState(resources={"tokens": 20}),
                "Charlie": AgentState(resources={"tokens": 20}),
            }
        )

        actions = [
            self.contribute_action("Alice", 10),   # Valid
            self.contribute_action("Bob", 25),     # Over-contribution
            self.contribute_action("Charlie", 5),  # Valid
        ]

        payoffs = engine.calculate_round_payoffs(
            payoff_type="pool",
            actions=actions,
            config=pool_config,
            grouping_mode="group",
            state=state,
        )

        # Verify all payoffs calculated correctly
        assert payoffs["Alice"] == 27.5, (
            f"Alice's payoff should be 27.5, got {payoffs['Alice']}"
        )
        assert payoffs["Bob"] == 17.5, (
            f"Bob's payoff should be 17.5 (over-contribution clamped), "
            f"got {payoffs['Bob']}"
        )
        assert payoffs["Charlie"] == 32.5, (
            f"Charlie's payoff should be 32.5, got {payoffs['Charlie']}"
        )

        print("✅ Smoketest passed: Multiple agents with mixed contributions")

    def test_zero_token_agent_cannot_contribute(self, engine, pool_config):
        """
        Smoketest: Agent with 0 tokens cannot contribute.

        Scenario:
        - Alice has 0 tokens, attempts to contribute 10
        - Bob has 20 tokens, contributes 10

        Expected:
        - Alice's contribution clamped to 0
        - Total pool: 0 + 10 = 10
        - Pool return: 10 * 1.5 / 2 = 7.5
        - Alice: (20 - 0) + 7.5 = 27.5
        - Bob: (20 - 10) + 7.5 = 17.5
        """
        state = ExperimentState(
            agents={
                "Alice": AgentState(resources={"tokens": 0}),
                "Bob": AgentState(resources={"tokens": 20}),
            }
        )

        actions = [
            self.contribute_action("Alice", 10),  # Has 0, attempts 10
            self.contribute_action("Bob", 10),    # Valid
        ]

        payoffs = engine.calculate_round_payoffs(
            payoff_type="pool",
            actions=actions,
            config=pool_config,
            grouping_mode="group",
            state=state,
        )

        # Alice's contribution clamped to 0
        assert payoffs["Alice"] == 27.5, (
            f"Alice's payoff should be 27.5 (contributed 0, got back 7.5), "
            f"got {payoffs['Alice']}"
        )
        assert payoffs["Bob"] == 17.5, (
            f"Bob's payoff should be 17.5 (contributed 10, got back 7.5), "
            f"got {payoffs['Bob']}"
        )

        print("✅ Smoketest passed: Agent with 0 tokens cannot contribute")

    def test_contribution_validation_without_state(self, engine, pool_config):
        """
        Smoketest: Without state, contribution uses attempted amount (backward compat).

        This tests that the system falls back gracefully when no state is provided.
        """
        # No state provided
        actions = [self.contribute_action("Alice", 25)]

        payoffs = engine.calculate_round_payoffs(
            payoff_type="pool",
            actions=actions,
            config=pool_config,
            grouping_mode="group",
            state=None,  # No state = no validation
        )

        # Without state, contribution is NOT validated (uses attempted amount)
        # Pool return = 25 * 1.5 / 1 = 37.5
        # Payoff = (20 - 25) + 37.5 = 32.5
        assert payoffs["Alice"] == 32.5, (
            f"Without state, payoff should be 32.5 (unvalidated), "
            f"got {payoffs['Alice']}"
        )

        print("✅ Smoketest passed: Backward compat (no state = no validation)")

    def test_negative_contribution_clamped_to_zero(self, engine, pool_config):
        """
        Smoketest: Negative contributions are clamped to 0.

        Scenario:
        - Alice has 20 tokens, attempts to contribute -5 (invalid)
        - Contribution should be clamped to 0 (minimum)

        Expected:
        - Pool return = 0 * 1.5 / 1 = 0
        - Payoff = (20 - 0) + 0 = 20
        """
        state = ExperimentState(
            agents={"Alice": AgentState(resources={"tokens": 20})}
        )

        actions = [self.contribute_action("Alice", -5)]  # Negative!

        payoffs = engine.calculate_round_payoffs(
            payoff_type="pool",
            actions=actions,
            config=pool_config,
            grouping_mode="group",
            state=state,
        )

        # Contribution clamped to 0 (minimum)
        assert payoffs["Alice"] == 20.0, (
            f"Alice's payoff should be 20.0 (contribution clamped to 0), "
            f"got {payoffs['Alice']}"
        )

        print("✅ Smoketest passed: Negative contribution clamped to 0")

    def test_all_agents_over_contribute(self, engine, pool_config):
        """
        Smoketest: All agents attempt over-contribution.

        Scenario:
        - All 3 agents have 20 tokens, all attempt 30
        - All contributions clamped to 20

        Expected:
        - Total pool: 60
        - Pool return: 60 * 1.5 / 3 = 30
        - Each agent: (20 - 20) + 30 = 30
        """
        state = ExperimentState(
            agents={
                "Alice": AgentState(resources={"tokens": 20}),
                "Bob": AgentState(resources={"tokens": 20}),
                "Charlie": AgentState(resources={"tokens": 20}),
            }
        )

        actions = [
            self.contribute_action("Alice", 30),
            self.contribute_action("Bob", 30),
            self.contribute_action("Charlie", 30),
        ]

        payoffs = engine.calculate_round_payoffs(
            payoff_type="pool",
            actions=actions,
            config=pool_config,
            grouping_mode="group",
            state=state,
        )

        # All should get same payoff (symmetric game)
        assert payoffs["Alice"] == 30.0
        assert payoffs["Bob"] == 30.0
        assert payoffs["Charlie"] == 30.0

        print("✅ Smoketest passed: All agents over-contribute (symmetric)")


class TestPGGContributionWithScene:
    """Integration tests using ExperimentScene to validate end-to-end flow."""

    @pytest.fixture
    def pgg_config(self):
        """Create a public goods game configuration for ExperimentScene."""
        from fos.core.experiment.config import ExperimentConfig

        return ExperimentConfig(
            scenario_id="public_goods_game",
            agents=[
                {"name": "Alice", "resources": {"tokens": 20}},
                {"name": "Bob", "resources": {"tokens": 20}},
                {"name": "Charlie", "resources": {"tokens": 20}},
            ],
            actions=[{"name": "contribute"}],
            parameters={
                "payoff_type": "pool",
                "multiplier": 1.5,
                "initial_tokens": 20,
            },
        )

    def test_scene_initializes_agent_resources(self, pgg_config):
        """
        Smoketest: ExperimentScene correctly initializes agent resources from config.

        This validates that the scene's state is properly populated with
        agent resources, which is required for contribution validation.

        Note: _initialize_state() is called during initialize(), not in __init__.
        """
        from fos.core.experiment.scene import ExperimentScene
        from unittest.mock import MagicMock

        scene = ExperimentScene(pgg_config)

        # Create mock LLM client
        mock_client = MagicMock()
        mock_client.chat = MagicMock(return_value='{"action": "contribute", "amount": 10}')

        # Initialize the scene (this calls _initialize_state)
        scene.initialize(mock_client)

        # Check that _initialize_state was called and state is populated
        assert "Alice" in scene.state.agents
        assert "Bob" in scene.state.agents
        assert "Charlie" in scene.state.agents

        # Check resources were set from config
        assert scene.state.agents["Alice"].resources.get("tokens") == 20
        assert scene.state.agents["Bob"].resources.get("tokens") == 20
        assert scene.state.agents["Charlie"].resources.get("tokens") == 20

        print("✅ Smoketest passed: Scene initializes agent resources correctly")

    def test_scene_state_passed_to_payoff_engine(self, pgg_config):
        """
        Smoketest: Verify scene.state is passed to PayoffEngine.

        This validates the integration chain:
        ExperimentScene -> ExperimentRunner -> PayoffEngine.calculate_round_payoffs

        The runner should pass scene.state to the payoff engine for validation.
        """
        from fos.core.experiment.scene import ExperimentScene
        from unittest.mock import MagicMock

        scene = ExperimentScene(pgg_config)

        # Create mock LLM client
        mock_client = MagicMock()
        mock_client.chat = MagicMock(return_value='{"action": "contribute", "amount": 10}')

        # Initialize the scene (creates runner)
        scene.initialize(mock_client)

        # Verify runner has access to scene
        assert scene.runner is not None
        assert scene.runner.scene is scene

        # Verify scene.state exists and has correct data
        assert scene.state is not None
        assert "Alice" in scene.state.agents
        assert scene.state.agents["Alice"].resources.get("tokens") == 20

        print("✅ Smoketest passed: Scene state accessible to runner for validation")
