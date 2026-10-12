"""
Standalone smoke test for the 11-20 Money Request Game.

Runs one round of the game with two mock agents (no real LLM needed),
then prints what each agent chose, the computed payoffs, and a few known
payoff table entries as a sanity check.

Run it directly with:
    python tests/smoke_tests/test_game_11_20.py
"""

import asyncio

from fos.core.experiment.agent import ExperimentAgent
from fos.core.experiment.game_configs import GameConfig
from fos.core.experiment.runner import ExperimentRunner
from fos.core.llm.client import LLMClient
from fos.core.llm_config import LLMConfig


def build_payoff_matrix() -> dict:
    """Build the full 10x10 payoff matrix for the game.

    Payoff for the row player = their number, plus 20 if the row number
    is exactly one less than the column number. Payoff for the column
    player = their number, plus 20 if the column number is exactly one
    less than the row number.
    """
    matrix = {}
    for row_num in range(11, 21):
        for col_num in range(11, 21):
            row_payoff = row_num + (20 if row_num == col_num - 1 else 0)
            col_payoff = col_num + (20 if col_num == row_num - 1 else 0)
            matrix[f"{row_num}_{col_num}"] = {
                "row": row_payoff,
                "col": col_payoff,
            }
    return matrix


def build_game_config() -> GameConfig:
    """Build the game configuration for the 11-20 Money Request Game."""
    return GameConfig(
        name="game_11_20",
        description=(
            "You and another player are playing a game in which each player "
            "requests an amount of money. The amount must be (an integer) "
            "between 11 and 20 shekels. Each player will receive the amount "
            "he requests. A player will receive an additional amount of 20 "
            "shekels if he asks for exactly one shekel less than the other "
            "player.\n\n"
            "What amount of money would you request?"
        ),
        action_type="integer",
        actions=[],
        output_field="amount",
        min=11,
        max=20,
        payoff_type="matrix",
        grouping_mode="pairwise",
        payoff_config={"matrix": build_payoff_matrix()},
    )


async def main() -> None:
    """Run one round of the game with mock agents and print the results."""
    game_config = build_game_config()
    llm_config = LLMConfig(dialect="mock")
    llm_client = LLMClient(llm_config)

    agents = [
        ExperimentAgent(
            name="Alice",
            properties={},
            llm_config=llm_config,
            role_prompt="You are Alice, an ambitious agent who wants to maximize your payoff.",
        ),
        ExperimentAgent(
            name="Bob",
            properties={},
            llm_config=llm_config,
            role_prompt="You are Bob, a cautious agent who wants a fair outcome.",
        ),
    ]

    runner = ExperimentRunner(
        agents=agents,
        game_config=game_config,
        llm_client=llm_client,
        round_visibility="simultaneous",
    )
    round_results = await runner.run(max_rounds=1)

    round_result = round_results[0]
    print("=== Round 1 results ===")
    for action in round_result.actions:
        print(f"  {action.agent_name} chose: {action.action_name}")

    print("\nComputed payoffs (round_results[0].payoffs):")
    for agent_name, payoff in (round_result.payoffs or {}).items():
        print(f"  {agent_name}: {payoff}")

    print("\nFinal scores:")
    for agent in agents:
        print(f"  {agent.name}: {agent.score}")

    print("\n=== Sanity checks (known payoff table entries) ===")
    matrix = build_payoff_matrix()
    known_entries = [
        ("11_11", {"row": 11, "col": 11}),
        ("19_20", {"row": 39, "col": 20}),
        ("20_19", {"row": 20, "col": 39}),
        ("15_15", {"row": 15, "col": 15}),
    ]
    for key, expected in known_entries:
        actual = matrix[key]
        if actual != expected:
            raise AssertionError(
                f"Payoff mismatch for {key}: got {actual}, expected {expected}"
            )
        print(f"  {key}: {actual} (expected {expected}) OK")

    print("\nAll sanity checks passed.")


if __name__ == "__main__":
    asyncio.run(main())
