"""
Integration test for PGG average contribution display feature.

Tests that when show_average_contribution=True:
1. InformationModel receives the parameter
2. Context shows average instead of individual contributions
3. Agents don't see individual neighbor names in their prompts
"""

import pytest
import asyncio
from unittest.mock import MagicMock


class TestPGGAverageContribution:
    """Integration tests for average contribution display in Public Goods Game."""

    @pytest.fixture
    def pgg_config_with_average(self):
        """Create PGG config with average contribution enabled."""
        from fos.core.experiment.config import ExperimentConfig

        return ExperimentConfig(
            scenario_id="public_goods",
            description="PGG with average contribution enabled",
            agents=[
                {"name": "Alice", "role_prompt": "You are Alice."},
                {"name": "Bob", "role_prompt": "You are Bob."},
                {"name": "Charlie", "role_prompt": "You are Charlie."},
                {"name": "Dave", "role_prompt": "You are Dave."},
            ],
            actions=[{"name": "allocate"}, {"name": "keep"}],
            parameters={
                "tokens_per_round": 20,
                "multiplier": 1.5,
                "resource_name": "tokens",
                "deduction_budget_per_phase": 0,
                "show_average_contribution": True,  # Enable average mode
            },
            state_schema={},
        )

    @pytest.fixture
    def pgg_config_without_average(self):
        """Create PGG config with average contribution disabled."""
        from fos.core.experiment.config import ExperimentConfig

        return ExperimentConfig(
            scenario_id="public_goods",
            description="PGG with individual contributions",
            agents=[
                {"name": "Alice", "role_prompt": "You are Alice."},
                {"name": "Bob", "role_prompt": "You are Bob."},
            ],
            actions=[{"name": "allocate"}, {"name": "keep"}],
            parameters={
                "tokens_per_round": 20,
                "multiplier": 1.5,
                "resource_name": "tokens",
                "deduction_budget_per_phase": 0,
                "show_average_contribution": False,  # Disable average mode
            },
            state_schema={},
        )

    def test_information_model_receives_average_param(self, pgg_config_with_average):
        """Test that InformationModel.show_average_contribution is True when enabled."""
        from fos.core.experiment.scene import ExperimentScene

        scene = ExperimentScene(pgg_config_with_average)
        mock_client = MagicMock()
        mock_client.chat = MagicMock(return_value='{"action": "allocate"}')
        scene.initialize(mock_client)

        assert scene.runner.information_model.show_average_contribution is True

    def test_information_model_defaults_to_false(self, pgg_config_without_average):
        """Test that InformationModel.show_average_contribution defaults to False."""
        from fos.core.experiment.scene import ExperimentScene

        scene = ExperimentScene(pgg_config_without_average)
        mock_client = MagicMock()
        mock_client.chat = MagicMock(return_value='{"action": "allocate"}')
        scene.initialize(mock_client)

        assert scene.runner.information_model.show_average_contribution is False

    def test_prompt_contains_average_not_individuals(self, pgg_config_with_average):
        """Test that actual LLM prompts contain average, not individual names."""
        from fos.core.experiment.scene import ExperimentScene

        scene = ExperimentScene(pgg_config_with_average)
        prompts_received = []

        def capture_chat(messages, json_mode=False):
            if messages:
                prompts_received.append(messages[0]["content"])
            if json_mode:
                return '{"action": "allocate"}'
            return '{"amount": 5}'

        mock_client = MagicMock()
        mock_client.chat = capture_chat
        scene.initialize(mock_client)

        # Run TWO rounds - average only appears in context after first round
        async def run():
            await scene.run_round(event_emitter=lambda *args, **kwargs: None)
            prompts_received.clear()  # Clear first round prompts
            await scene.run_round(event_emitter=lambda *args, **kwargs: None)
        asyncio.run(run())

        # Check that at least one prompt was captured from round 2
        assert len(prompts_received) > 0, "No prompts were captured from round 2"

        # Combine all prompts for analysis
        full_prompt = " ".join(prompts_received)

        # When average is enabled, should contain "Average" or "average" in round 2 context
        assert "Average" in full_prompt or "average" in full_prompt.lower(), \
            f"Prompt should contain 'Average' when show_average_contribution=True. Got: {full_prompt[:500]}"

        # Should NOT contain individual neighbor contribution strings like "Bob allocate"
        # (Note: "I allocate" for own action is fine)
        assert "Bob allocate" not in full_prompt, \
            "Should not show individual neighbor 'Bob allocate' in average mode"
        assert "Charlie allocate" not in full_prompt, \
            "Should not show individual neighbor 'Charlie allocate' in average mode"
        assert "Dave allocate" not in full_prompt, \
            "Should not show individual neighbor 'Dave allocate' in average mode"

    def test_prompt_shows_individuals_when_disabled(self, pgg_config_without_average):
        """Test that individual contributions are shown when average is disabled."""
        from fos.core.experiment.scene import ExperimentScene

        scene = ExperimentScene(pgg_config_without_average)
        prompts_received = []

        def capture_chat(messages, json_mode=False):
            if messages:
                prompts_received.append(messages[0]["content"])
            if json_mode:
                return '{"action": "allocate"}'
            return '{"amount": 5}'

        mock_client = MagicMock()
        mock_client.chat = capture_chat
        scene.initialize(mock_client)

        # Run TWO rounds - individual contributions appear in context after first round
        async def run():
            await scene.run_round(event_emitter=lambda *args, **kwargs: None)
            prompts_received.clear()  # Clear first round prompts
            await scene.run_round(event_emitter=lambda *args, **kwargs: None)
        asyncio.run(run())

        # Combine all prompts
        full_prompt = " ".join(prompts_received)

        # When average is disabled, should contain individual contributions
        # (The format is "Bob allocate 5" not "Bob allocated 5")
        assert "Bob allocate" in full_prompt, \
            f"Should show individual neighbor when average disabled. Got: {full_prompt[:500]}"

    def test_neighbor_count_matches_visible_count(self, pgg_config_with_average):
        """Test that neighbor count in prompt matches actual visible neighbors."""
        from fos.core.experiment.scene import ExperimentScene

        scene = ExperimentScene(pgg_config_with_average)
        prompts_received = []

        def capture_chat(messages, json_mode=False):
            if messages:
                prompts_received.append(messages[0]["content"])
            if json_mode:
                return '{"action": "allocate"}'
            return '{"amount": 5}'

        mock_client = MagicMock()
        mock_client.chat = capture_chat
        scene.initialize(mock_client)

        # Run TWO rounds - context only appears after first round
        async def run():
            await scene.run_round(event_emitter=lambda *args, **kwargs: None)
            prompts_received.clear()
            await scene.run_round(event_emitter=lambda *args, **kwargs: None)
        asyncio.run(run())

        full_prompt = " ".join(prompts_received)

        # Get the actual visible contributions for Alice
        model = scene.runner.information_model
        state = scene.state
        graph = scene.state.extensions.get("graph", {})

        if model and state:
            visible = model.get_visible_contributions("Alice", state, graph)
            if visible:
                expected_count = len(visible)
                # The prompt should say "X neighbors" where X matches visible count
                assert f"{expected_count} neighbor" in full_prompt, \
                    f"Expected '{expected_count} neighbors' in prompt. Got: {full_prompt[:500]}"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
