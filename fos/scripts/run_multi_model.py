"""
Run the 11-20 Money Request Game with 12 personas across 3 different models.

This script makes sure only one model is loaded in LM Studio at a time.
For each of the 3 models in MODELS it first unloads the other two models
via the LM Studio management API, then loads the target model, waits for
it to finish loading, and then runs one round of the game for each of the
first 12 personas read from final_200_personas.csv (persona texts come
from personas/{username}.txt).

Each persona's decision (which number from 11 to 20 they asked for) is
recorded. After all 3 models finish, the results are saved to
multi_model_results.json at the repo root, and a cross-model comparison
table is printed to the screen and saved to multi_model_table.txt.

Functions:
    curl_post(url, data)        — Send a JSON POST request using curl.
    lm_studio_reachable()       — Check that LM Studio answers on port 1234.
    load_twelve_usernames()     — Read the first 12 usernames from the CSV.
    load_persona_text(user)     — Read one persona file as a single string.
    build_payoff_matrix()       — Build the 10x10 payoff table for the game.
    build_game_config()         — Build the game settings for the 11-20 game.
    build_llm_config(model)     — Build LLM settings pointing at LM Studio.
    unload_model(model)         — Ask LM Studio to unload one model.
    load_model(model)           — Ask LM Studio to load one model, then wait.
    run_one_decision(...)       — Run one game round for one persona on one model.
    print_model_counts(...)     — Print how often each number was chosen.
    build_comparison_table(...) — Build the cross-model table as text.
    main()                      — Run all 36 decisions and save the results.
"""

import asyncio
import json
import subprocess
import sys
import time
from pathlib import Path

# Make the worktree's `src` importable when this script is run directly.
_SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from fos.core.experiment.agent import ExperimentAgent  # noqa: E402
from fos.core.experiment.game_configs import GameConfig  # noqa: E402
from fos.core.experiment.runner import ExperimentRunner  # noqa: E402
from fos.core.llm.client import LLMClient  # noqa: E402
from fos.core.llm_config import LLMConfig  # noqa: E402

# The 3 models to test on LM Studio, loaded one at a time.
MODELS = [
    "openai/gpt-oss-20b",
    "google/gemma-4-26b-a4b",
    "qwen/qwen3.6-35b-a3b",
]
BASE_URL = "http://localhost:1234/v1"
MANAGE_URL = "http://localhost:1234/api/v0/models"

# Repo root is the parent of the scripts/ directory.
REPO = Path(__file__).resolve().parent.parent

_PERSONA_COUNT = 12


def curl_post(url: str, data: dict) -> None:
    """Send a JSON POST request to a URL using curl.

    Raises a CalledProcessError if curl itself fails (for example when
    LM Studio is not reachable), so failures are never silent.
    """
    subprocess.run(
        ["curl", "-s", "-X", "POST", url,
         "-H", "Content-Type: application/json", "-d", json.dumps(data)],
        timeout=30,
        check=True,
    )


def lm_studio_reachable() -> bool:
    """Check whether LM Studio answers a request on localhost:1234."""
    try:
        result = subprocess.run(
            ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", MANAGE_URL],
            timeout=10,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip() == "200"
    except subprocess.TimeoutExpired:
        return False


def load_twelve_usernames() -> list[str]:
    """Read the first 12 usernames from final_200_personas.csv."""
    csv_path = REPO / "final_200_personas.csv"
    lines = csv_path.read_text(encoding="utf-8").splitlines()
    return [line.strip() for line in lines[:_PERSONA_COUNT]]


def load_persona_text(username: str) -> str:
    """Read one persona file from the personas/ directory as a string."""
    persona_path = REPO / "personas" / f"{username}.txt"
    return persona_path.read_text(encoding="utf-8")


def build_payoff_matrix() -> dict:
    """Build the full 10x10 payoff matrix for the 11-20 game.

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


def build_llm_config(model: str) -> LLMConfig:
    """Build a fresh LLMConfig pointing at LM Studio for one model."""
    return LLMConfig(
        dialect="openai",
        base_url=BASE_URL,
        api_key="lm-studio",
        model=model,
        temperature=0.7,
    )


def unload_model(model: str) -> None:
    """Ask LM Studio to unload one model from memory."""
    print(f"Unloading {model}...")
    curl_post(f"{MANAGE_URL}/unload", {"model": model})
    time.sleep(3)


def load_model(model: str) -> None:
    """Ask LM Studio to load one model, then wait for it to finish."""
    curl_post(f"{MANAGE_URL}/load", {"model": model})
    print(f"Loading {model}...")
    time.sleep(10)


async def run_one_decision(
    username: str,
    model: str,
    llm_client: LLMClient,
) -> str:
    """Run exactly one round of the 11-20 game for one persona on one model.

    Returns the amount the persona chose (an integer from 11 to 20, for example 15).
    """
    persona_text = load_persona_text(username)
    game_config = build_game_config()
    llm_config = build_llm_config(model)

    agent = ExperimentAgent(
        name=username,
        properties={},
        llm_config=llm_config,
        role_prompt=persona_text,
    )

    runner = ExperimentRunner(
        agents=[agent],
        game_config=game_config,
        llm_client=llm_client,
        round_visibility="simultaneous",
    )
    round_results = await runner.run(max_rounds=1)
    return round_results[0].actions[0].action_name


def print_model_counts(model: str, results: list[tuple[str, str]]) -> None:
    """Print how often each number from 11 to 20 was chosen for a model."""
    print(f"\nCounts for {model}:")
    for n in range(11, 21):
        count = sum(1 for _, chosen in results if chosen == n)
        print(f"  {n}: {count}")


def build_comparison_table(
    usernames: list[str],
    all_results: dict[str, list[tuple[str, str]]],
) -> str:
    """Build the cross-model comparison table of chosen actions as text."""
    lines = []
    header = f"{'username':30s}"
    for model in MODELS:
        header += f"  {model.split('/')[-1][:15]:15s}"
    lines.append(header)
    lines.append("-" * 90)
    for i, user in enumerate(usernames):
        row = f"{user:30s}"
        for model in MODELS:
            chosen = all_results[model][i][1]
            row += f"  {chosen:15s}"
        lines.append(row)
    return "\n".join(lines)


async def main() -> None:
    """Run 36 decisions (12 personas x 3 models) and save the results.

    For each model: unload the other two, load the target, wait, then run
    all 12 personas against it. Results are saved to multi_model_results.json
    and the comparison table to multi_model_table.txt at the repo root.
    """
    if not lm_studio_reachable():
        print("LM Studio not reachable — cannot run the multi-model experiment.")
        sys.exit(1)

    usernames = load_twelve_usernames()
    print(f"Running {len(usernames)} personas across {len(MODELS)} models")

    all_results: dict[str, list[tuple[str, str]]] = {}

    for model in MODELS:
        print(f"\n{'=' * 60}")
        print(f"MODEL: {model}")
        print(f"{'=' * 60}")

        # Unload the other models, then load this one (never two at once).
        for other in MODELS:
            if other != model:
                unload_model(other)
        load_model(model)

        llm_client = LLMClient(build_llm_config(model))
        results: list[tuple[str, str]] = []
        for user in usernames:
            chosen = await run_one_decision(user, model, llm_client)
            results.append((user, chosen))
            print(f"  {user:30s} -> {chosen}")

        all_results[model] = results
        print_model_counts(model, results)

    # Save the raw results to disk.
    with open(REPO / "multi_model_results.json", "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2)
    print(f"\nSaved to {REPO / 'multi_model_results.json'}")

    # Build, print, and save the cross-model table.
    table_text = build_comparison_table(usernames, all_results)
    print("\n" + table_text)
    with open(REPO / "multi_model_table.txt", "w", encoding="utf-8") as f:
        f.write(table_text + "\n")
    print(f"\nSaved to {REPO / 'multi_model_table.txt'}")


if __name__ == "__main__":
    asyncio.run(main())
