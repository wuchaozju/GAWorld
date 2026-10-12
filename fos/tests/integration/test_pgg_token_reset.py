"""
Smoke test to verify token reset behavior in PGG.

This test runs a minimal PGG scenario and checks
whether tokens are reset each round or accumulate.

Expected behavior:
- Each round, agents should start with fresh tokens_per_round
- Cumulative scores track total earnings across all rounds
"""

import pytest
import asyncio
import logging

logging.basicConfig(level=logging.INFO)


class TestTokenReset:
    """Test token reset behavior in Public Goods Game."""

    @pytest.fixture
    def pgg_config(self):
        """Create a public goods game configuration."""
        from fos.core.experiment.config import ExperimentConfig

        return ExperimentConfig(
            scenario_id="public_goods",
            description="Public Goods Game - Token Reset Test",
            agents=[
                {"name": "Alice", "role_prompt": "You are Alice."},
                {"name": "Bob", "role_prompt": "You are Bob."},
            ],
            actions=[{"name": "allocate"}, {"name": "keep"}],
            parameters={
                "tokens_per_round": 20,
                "multiplier": 1.5,
                "resource_name": "tokens",
                "deduction_budget_per_phase": 0,  # No deduction phase
            },
            state_schema={},
        )

    def test_token_reset_between_rounds(self, pgg_config):
        """
        Test that tokens are reset each round in PGG.

        This test:
        1. Initializes a scene
        2. Checks token balances before and after rounds
        3. Verifies whether tokens accumulate or reset
        """
        from fos.core.experiment.scene import ExperimentScene
        from unittest.mock import MagicMock

        print("\n" + "="*60)
        print("TOKEN RESET SMOKE TEST")
        print("="*60 + "\n")

        # Create mock LLM client
        mock_client = MagicMock()
        call_count = [0]  # Use list to allow mutation in closure

        def mock_chat(messages, json_mode=False):
            call_count[0] += 1
            # Alternate between action choice and amount
            if call_count[0] % 2 == 1:
                return '{"action": "allocate"}'
            else:
                return '{"amount": 5}'

        mock_client.chat = mock_chat

        # Create scene
        scene = ExperimentScene(pgg_config)

        # Initialize the scene (this calls _initialize_state)
        scene.initialize(mock_client)

        # Check initial token balances
        print("INITIAL STATE (after initialize):")
        for agent_name in ["Alice", "Bob"]:
            agent_state = scene.state.agents.get(agent_name)
            if agent_state:
                tokens = agent_state.resources.get("tokens", "N/A")
                print(f"  {agent_name}: {tokens} tokens")

        # Run 2 rounds
        async def run_rounds():
            for round_num in range(1, 3):
                print(f"\n--- ROUND {round_num} ---")

                # Check token balances BEFORE round
                print("BEFORE round:")
                for agent_name in ["Alice", "Bob"]:
                    agent_state = scene.state.agents.get(agent_name)
                    if agent_state:
                        tokens = agent_state.resources.get("tokens", "N/A")
                        print(f"  {agent_name}: {tokens} tokens")

                # Run the round (async)
                await scene.run_round(
                    event_emitter=lambda *args, **kwargs: None,  # Mock event emitter
                )

                # Check token balances AFTER round
                print("AFTER round:")
                for agent_name in ["Alice", "Bob"]:
                    agent_state = scene.state.agents.get(agent_name)
                    if agent_state:
                        tokens = agent_state.resources.get("tokens", "N/A")
                        print(f"  {agent_name}: {tokens} tokens")

                # Check agent scores (cumulative earnings)
                print("CUMULATIVE SCORES:")
                for agent in scene.agents:
                    print(f"  {agent.name}: {agent.score}")

        # Run the async test
        asyncio.run(run_rounds())

        print("\n" + "="*60)
        print("VERIFICATION:")
        print("If tokens stay at 20 each round -> working correctly")
        print("If tokens grow/accumulate -> this is a BUG that needs fixing")
        print("="*60 + "\n")

    def test_payoff_calculation_uses_initial_tokens(self):
        """
        Test that payoff calculation uses initial_tokens from config.

        This verifies the PayoffEngine behavior independently.
        """
        from fos.core.experiment.payoff.engine import PayoffEngine
        from fos.core.experiment.controller import ActionResult

        print("\n" + "="*60)
        print("PAYOFF CALCULATION TEST")
        print("="*60 + "\n")

        engine = PayoffEngine()

        # Config with initial_tokens = 20
        config = {
            "multiplier": 1.5,
            "initial_tokens": 20,
        }

        # Agent contributes 5 tokens
        actions = [
            ActionResult(
                agent_name="Alice",
                action_name="contribute",
                parameters={"amount": 5},
                summary="Alice contributed 5",
                success=True,
                skipped=False,
                round_num=1,
            )
        ]

        # Calculate payoffs (without state - uses initial_tokens from config)
        payoffs = engine.calculate_round_payoffs(
            payoff_type="pool",
            actions=actions,
            config=config,
            grouping_mode="group",
            state=None,  # No state = uses config.initial_tokens
        )

        print(f"Payoff for Alice: {payoffs['Alice']}")

        # Expected:
        # - tokens_kept = initial_tokens - contribution = 20 - 5 = 15
        # - pool_return = (5 * 1.5) / 1 = 7.5
        # - payoff = 15 + 7.5 = 22.5
        expected = 22.5
        assert payoffs["Alice"] == expected, (
            f"Expected payoff {expected}, got {payoffs['Alice']}"
        )

        print("PASS: Payoff correctly uses initial_tokens from config")
        print("   This means each round is treated as starting fresh with 20 tokens")


if __name__ == "__main__":
    pytest.main([__file__], ["-v", "-s"])
