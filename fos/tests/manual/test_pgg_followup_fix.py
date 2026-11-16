"""
Test script to verify PGG follow-up prompt fix.

This script tests that:
1. Initial prompt shows only phase-filtered actions (allocate, keep)
2. Follow-up prompt for allocate does NOT show action list
3. Follow-up prompt only asks for the amount parameter
"""

import sys
from pathlib import Path
from unittest.mock import Mock

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root / "src"))

from fos.core.experiment.game_configs import GameConfig  # noqa: E402
from fos.core.experiment.prompt_builder import build_prompt, build_reprompt  # noqa: E402


def test_followup_prompt_without_action_list():
    """Test that follow-up prompt doesn't include full action list."""

    # Create a mock agent
    agent = Mock()
    agent.name = "TestAgent"
    agent.properties = {
        "age_group": "adult",
        "social_capital": 50
    }
    agent.role_prompt = None
    agent.get_properties_dict = lambda: agent.properties

    # Create game config with allocate action that has parameters
    game_config = GameConfig(
        name="public_goods",
        description="Public goods game",
        action_type="discrete",
        actions=["allocate", "keep"],  # Only these two for allocate phase
        action_descriptions={
            "allocate": "Allocate resources to the group account",
            "keep": "Keep all your resources this round",
        },
        output_field="action",
        action_schemas={
            "allocate": {
                "schema": {
                    "amount": {
                        "type": "integer",
                        "description": "How much to contribute (0 to your total resources)"
                    }
                },
                "mode": "json"
            }
        }
    )

    # Build initial prompt
    initial_prompt = build_prompt(
        agent=agent,
        game_config=game_config,
        context_summary="This is round 1.",
        include_section_markers=True,
        allowed_actions=["allocate", "keep"],  # Filtered for allocate phase
        information_model=None,
        kb_context="",
        neighbor_context="",
    )

    print("=" * 80)
    print("INITIAL PROMPT")
    print("=" * 80)
    print(initial_prompt)
    print()

    # Verify initial prompt has only allocate and keep
    assert "allocate" in initial_prompt.lower()
    assert "keep" in initial_prompt.lower()
    assert "skip" not in initial_prompt.lower(), "ERROR: 'skip' should NOT be in initial prompt!"
    print("[PASS] Initial prompt correctly shows only 'allocate' and 'keep'")

    # Build follow-up prompt for allocate
    followup_prompt = build_reprompt(
        agent=agent,
        game_config=game_config,
        context_summary="This is round 1.",
        chosen_action="allocate",
        parameter_schema={"amount": {"type": "integer", "description": "How much to contribute"}},
        mode="json",
        include_section_markers=True,
        allowed_actions=["allocate", "keep"],  # Should be passed through
        information_model=None,
        kb_context="",
        neighbor_context="",
    )

    print("=" * 80)
    print("FOLLOW-UP PROMPT")
    print("=" * 80)
    print(followup_prompt)
    print()

    # Check that follow-up has the instruction
    assert "You chose to allocate" in followup_prompt, "Missing follow-up instruction"
    print("[PASS] Follow-up prompt has correct instruction")

    # Check that follow-up asks for amount
    assert "amount" in followup_prompt.lower(), "Missing amount parameter request"
    print("[PASS] Follow-up prompt asks for amount parameter")

    # Check that follow-up does NOT have full action list
    # The action list section should NOT appear in follow-up
    action_list_count = followup_prompt.count("## Available Actions")
    assert action_list_count == 0, f"ERROR: Found {action_list_count} 'Available Actions' sections (should be 0)"
    print("[PASS] Follow-up prompt does NOT include action list section")

    # Check that skip is NOT mentioned
    skip_count = followup_prompt.lower().count('"skip"')
    assert skip_count == 0, f"ERROR: Found {skip_count} mentions of 'skip' in follow-up (should be 0)"
    print("[PASS] Follow-up prompt does NOT mention 'skip' action")

    print()
    print("=" * 80)
    print("ALL TESTS PASSED!")
    print("=" * 80)
    print()
    print("Summary:")
    print("  1. Initial prompt shows only phase-filtered actions [PASS]")
    print("  2. Follow-up prompt does NOT re-list actions [PASS]")
    print("  3. Follow-up prompt only asks for amount parameter [PASS]")


if __name__ == "__main__":
    test_followup_prompt_without_action_list()
