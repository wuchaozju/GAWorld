"""
Run all smoke tests with all models.

This script provides a convenient way to run all scenario smoke tests
with one or more Ollama models. Output files are written to
test_results/scenario_smoke_tests/ for human and LLM review.

Usage:
    # Run with default model (phi4-mini:latest)
    python -m tests.smoke_tests.run_all_smoke_tests

    # Run with specific models
    python -m tests.smoke_tests.run_all_smoke_tests --models "phi4-mini:latest" "qwen3:4b-instruct-2507-q4_K_M"

    # Run specific scenarios
    python -m tests.smoke_tests.run_all_smoke_tests --scenarios prisoners_dilemma stag_hunt

    # Run with all available models
    python -m tests.smoke_tests.run_all_smoke_tests --all-models

    # Quick test (single model, single scenario)
    python -m tests.smoke_tests.run_all_smoke_tests --quick
"""

import asyncio
import argparse
import sys
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fos.core.llm_config import LLMConfig
from fos.core.llm import create_llm_client
from fos.core.experiment.agent import ExperimentAgent
from fos.core.experiment.game_configs import GameConfig
from fos.core.experiment.runner import ExperimentRunner, RoundResult
from fos.core.scenarios.registry import get_scenario


def convert_scenario_to_game_config(scenario_id: str) -> GameConfig:
    """Convert scenario registry metadata to GameConfig.

    This matches how the backend API converts scenarios for ExperimentRunner.

    Args:
        scenario_id: Scenario identifier (e.g., "prisoners_dilemma")

    Returns:
        GameConfig ready for ExperimentRunner
    """
    scenario = get_scenario(scenario_id)

    # Extract parameter defaults (including custom action names if set)
    _params = {p["id"]: p["default"] for p in scenario.get("parameters", [])}

    # Priority: 1) parameterized actions, 2) category_actions with defaults, 3) direct actions
    if _params.get("action_1") and _params.get("action_2"):
        # Game theory scenarios with customizable action names
        a1 = _params["action_1"].lower()
        a2 = _params["action_2"].lower()
        actions = [a1, a2]
        action_descriptions = {
            a1: _params.get("action_1_description", a1),
            a2: _params.get("action_2_description", a2),
        }
    elif scenario.get("category_actions") and scenario.get("default_action_ids"):
        # Sociology scenarios using category action libraries
        category_actions = scenario["category_actions"]
        default_ids = scenario["default_action_ids"]
        actions = default_ids
        action_descriptions = {
            a["id"]: a["description"]
            for a in category_actions
            if a["id"] in default_ids
        }
    else:
        # Direct actions from registry
        actions = [a["id"] for a in scenario.get("actions", [])]
        action_descriptions = {a["id"]: a["description"] for a in scenario.get("actions", [])}

    # Build payoff_config from matrix_meta if available (generic — pass all cells as-is)
    payoff_config = {}
    if "matrix_meta" in scenario:
        cells = scenario["matrix_meta"].get("cells", {})
        payoff_config = {"matrix": cells}

    # Stag Hunt uses threshold group payoff instead of a raw matrix
    if scenario.get("grouping_mode") == "group" and scenario.get("payoff_type") == "matrix":
        if "stag_reward" in _params:
            threshold_action = _params.get("action_1", "stag").lower()
            payoff_config = {
                "group_payoff_mode": "threshold",
                "threshold_action": threshold_action,
                "threshold_reward": _params["stag_reward"],
                "threshold_failure": 0,
                "safe_reward": _params["hare_reward"],
            }

    return GameConfig(
        name=scenario["id"],
        description=scenario["description"],
        action_type="discrete",
        actions=actions,
        action_descriptions=action_descriptions,
        payoff_summary=scenario.get("description", ""),
        payoff_type=scenario["payoff_type"],
        grouping_mode=scenario["grouping_mode"],
        payoff_config=payoff_config,
    )

# Available models
OLLAMA_MODELS = [
    "alibayram/hunyuan:4b",
    "qwen3:4b-instruct-2507-q4_K_M",
    "phi4-mini:latest",
    "gemma3:4b-it-qat",
]

DEFAULT_MODEL = "phi4-mini:latest"

# Scenario registry
SCENARIO_BUILDERS = {
    "prisoners_dilemma": "build_pd_test",
    "pd_multiround": "build_pd_multiround_test",
    "battle_of_sexes": "build_bos_test",
    "stag_hunt": "build_stag_hunt_test",
    "public_goods": "build_public_goods_test",
    "coordination_game": "build_coordination_game_test",
    "open_discussion": "build_open_discussion_test",
    "social_norm_disruption": "build_social_norm_test",
    "policy_erosion": "build_policy_erosion_test",
    "echo_chamber": "build_echo_chamber_test",
    "resource_scarcity": "build_resource_scarcity_test",
    "grid_world": "build_grid_world_test",
    # NOTE: werewolf removed — scenario is unsupported/inactive
    # To re-enable: add "werewolf": "build_werewolf_test" back
}


class SmokeTestRunner:
    """Runner for scenario smoke tests."""

    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.results: List[Dict[str, Any]] = []

    def create_llm_client(self, model: str):
        """Create LLM client for model."""
        config = LLMConfig(
            dialect="ollama",
            model=model,
            base_url="http://localhost:11434",
            temperature=0.7,
            max_tokens=512,
        )
        return create_llm_client(config)

    def write_output(
        self,
        scenario_id: str,
        model: str,
        test_name: str,
        config: Dict[str, Any],
        round_results: List[RoundResult],
        final_scores: Dict[str, int],
        errors: List[str],
    ):
        """Write test output to file."""
        # Sanitize model name for filename
        model_safe = model.replace("/", "_").replace(":", "-")
        filename = f"{scenario_id}_{model_safe}_{test_name}.txt"
        filepath = self.output_dir / filename

        with open(filepath, 'w', encoding='utf-8') as f:
            f.write("=" * 80 + "\n")
            f.write(f"SCENARIO: {scenario_id}\n")
            f.write(f"MODEL: {model}\n")
            f.write(f"TEST: {test_name}\n")
            f.write("=" * 80 + "\n\n")

            f.write("CONFIGURATION:\n")
            for key, value in config.items():
                f.write(f"  {key}: {value}\n")
            f.write("\n")

            for round_result in round_results:
                f.write("=" * 80 + "\n")
                f.write(f"ROUND {round_result.round_num}\n")
                f.write("=" * 80 + "\n")

                for action in round_result.actions:
                    payoff = round_result.payoffs.get(action.agent_name) if round_result.payoffs else None
                    payoff_str = f" → {payoff}" if payoff is not None else ""
                    params_str = f"({action.parameters})" if action.parameters else ""
                    f.write(f"  {action.agent_name}: {action.action_name}{params_str}{payoff_str}\n")

                f.write("\n")

            f.write("=" * 80 + "\n")
            f.write("SUMMARY\n")
            f.write("=" * 80 + "\n")
            f.write(f"Final scores: {final_scores}\n")
            f.write(f"Errors: {errors if errors else 'None'}\n")
            f.write(f"Timestamp: {datetime.now().isoformat()}\n")

        print(f"  Output: {filepath}")

    async def run_test(
        self,
        scenario_id: str,
        model: str,
        test_name: str,
        game_config: GameConfig,
        agents: List[ExperimentAgent],
        max_rounds: int = 1,
        round_visibility: str = "simultaneous",
        config_extra: Dict[str, Any] = None,
    ):
        """Run a single test."""
        print(f"\nRunning: {scenario_id} / {model} / {test_name}")

        llm_client = self.create_llm_client(model)

        runner = ExperimentRunner(
            agents=agents,
            game_config=game_config,
            llm_client=llm_client,
            round_visibility=round_visibility,
        )

        try:
            round_results = await runner.run(max_rounds)

            final_scores = {agent.name: agent.score for agent in agents}
            errors = []
            warnings = []
            action_counts = {}

            for rr in round_results:
                for action in rr.actions:
                    # Track action errors
                    if action.error:
                        errors.append(f"Round {rr.round_num} - {action.agent_name}: {action.error}")

                    # Track action diversity
                    action_name = action.action_name
                    action_counts[action_name] = action_counts.get(action_name, 0) + 1

                    # Validate action is in allowed set
                    if game_config.actions and action_name not in game_config.actions:
                        errors.append(
                            f"Round {rr.round_num} - {action.agent_name}: "
                            f"Action '{action_name}' not in allowed set {game_config.actions}"
                        )

            # Validate payoffs for matrix games
            if game_config.payoff_type == "matrix":
                total_payoff = sum(final_scores.values())
                if total_payoff == 0:
                    warnings.append("Payoffs all zero - matrix calculation may not be working")

            config = {
                "model": model,
                "agents": [a.name for a in agents],
                "actions": game_config.actions,
                "payoff_type": game_config.payoff_type,
                "grouping_mode": game_config.grouping_mode,
                **(config_extra or {}),
            }

            self.write_output(scenario_id, model, test_name, config, round_results, final_scores, errors)

            success = len(errors) == 0
            self.results.append({
                "scenario": scenario_id,
                "model": model,
                "test": test_name,
                "success": success,
                "errors": errors,
                "warnings": warnings,
                "action_diversity": len(action_counts),
                "total_rounds": len(round_results),
                "final_scores": final_scores,
            })

            status = "✓ PASS" if success else "✗ FAIL"
            warning_str = f" (warnings: {len(warnings)})" if warnings else ""
            print(f"  {status}{warning_str}")

            return success

        except Exception as e:
            print(f"  ✗ ERROR: {e}")
            self.results.append({
                "scenario": scenario_id,
                "model": model,
                "test": test_name,
                "success": False,
                "errors": [str(e)],
            })
            return False

    def print_summary(self):
        """Print summary of all test results."""
        print("\n" + "=" * 80)
        print("SMOKE TEST SUMMARY")
        print("=" * 80)

        passed = sum(1 for r in self.results if r["success"])
        failed = len(self.results) - passed
        total_warnings = sum(len(r.get("warnings", [])) for r in self.results)

        print(f"Total: {len(self.results)} tests")
        print(f"Passed: {passed}")
        print(f"Failed: {failed}")
        print(f"Warnings: {total_warnings}")

        # Show action diversity stats
        diversity_stats = [r.get("action_diversity", 0) for r in self.results if r.get("success")]
        if diversity_stats:
            avg_diversity = sum(diversity_stats) / len(diversity_stats)
            print(f"Avg action diversity: {avg_diversity:.1f} unique actions per test")

        if failed > 0:
            print("\nFailed tests:")
            for r in self.results:
                if not r["success"]:
                    print(f"  - {r['scenario']}/{r['model']}/{r['test']}")
                    for err in r["errors"]:
                        print(f"      {err}")

        if total_warnings > 0:
            print("\nWarnings:")
            for r in self.results:
                if r.get("warnings"):
                    print(f"  - {r['scenario']}/{r['model']}/{r['test']}")
                    for warn in r["warnings"]:
                        print(f"      {warn}")

        return failed == 0


# =============================================================================
# Test Builders
# =============================================================================

def build_pd_test():
    """Build Prisoner's Dilemma test using scenario registry."""
    llm_config = LLMConfig(dialect="ollama", model="", base_url="http://localhost:11434")

    config = convert_scenario_to_game_config("prisoners_dilemma")

    agents = [
        ExperimentAgent(name="Alice", properties={}, llm_config=llm_config, role_prompt="You are Alice."),
        ExperimentAgent(name="Bob", properties={}, llm_config=llm_config, role_prompt="You are Bob."),
    ]

    return config, agents, "two_agents"


def build_bos_test():
    """Build Battle of Sexes test using scenario registry."""
    llm_config = LLMConfig(dialect="ollama", model="", base_url="http://localhost:11434")

    config = convert_scenario_to_game_config("battle_of_the_sexes")

    agents = [
        ExperimentAgent(name="Partner1", properties={}, llm_config=llm_config, role_prompt="You prefer opera."),
        ExperimentAgent(name="Partner2", properties={}, llm_config=llm_config, role_prompt="You prefer football."),
    ]

    return config, agents, "coordination"


def build_stag_hunt_test():
    """Build Stag Hunt test using scenario registry."""
    llm_config = LLMConfig(dialect="ollama", model="", base_url="http://localhost:11434")

    config = convert_scenario_to_game_config("stag_hunt")

    agents = [
        ExperimentAgent(name="Hunter1", properties={}, llm_config=llm_config, role_prompt="You are Hunter1."),
        ExperimentAgent(name="Hunter2", properties={}, llm_config=llm_config, role_prompt="You are Hunter2."),
        ExperimentAgent(name="Hunter3", properties={}, llm_config=llm_config, role_prompt="You are Hunter3."),
    ]

    return config, agents, "group"


def build_public_goods_test():
    """Build Public Goods test using scenario registry."""
    llm_config = LLMConfig(dialect="ollama", model="", base_url="http://localhost:11434")

    config = convert_scenario_to_game_config("public_goods")

    agents = [
        ExperimentAgent(name="Player1", properties={}, llm_config=llm_config, role_prompt="You are Player1."),
        ExperimentAgent(name="Player2", properties={}, llm_config=llm_config, role_prompt="You are Player2."),
        ExperimentAgent(name="Player3", properties={}, llm_config=llm_config, role_prompt="You are Player3."),
    ]

    return config, agents, "pool"


def build_coordination_game_test():
    """Build Coordination Game test using scenario registry."""
    llm_config = LLMConfig(dialect="ollama", model="", base_url="http://localhost:11434")

    config = convert_scenario_to_game_config("coordination_game")

    agents = [
        ExperimentAgent(name="NodeA", properties={}, llm_config=llm_config, role_prompt="You are Node A."),
        ExperimentAgent(name="NodeB", properties={}, llm_config=llm_config, role_prompt="You are Node B."),
        ExperimentAgent(name="NodeC", properties={}, llm_config=llm_config, role_prompt="You are Node C."),
    ]

    return config, agents, "basic"


def build_open_discussion_test():
    """Build Open Discussion test using scenario registry."""
    llm_config = LLMConfig(dialect="ollama", model="", base_url="http://localhost:11434")

    config = convert_scenario_to_game_config("open_discussion")

    agents = [
        ExperimentAgent(name="Alice", properties={}, llm_config=llm_config, role_prompt="You are Alice."),
        ExperimentAgent(name="Bob", properties={}, llm_config=llm_config, role_prompt="You are Bob."),
        ExperimentAgent(name="Carol", properties={}, llm_config=llm_config, role_prompt="You are Carol."),
    ]

    return config, agents, "basic"


def build_social_norm_test():
    """Build Social Norm Disruption test using scenario registry."""
    llm_config = LLMConfig(dialect="ollama", model="", base_url="http://localhost:11434")

    config = convert_scenario_to_game_config("social_norm_disruption")

    agents = [
        ExperimentAgent(name="HighStatus", properties={}, llm_config=llm_config, role_prompt="You are high-status."),
        ExperimentAgent(name="LowStatus", properties={}, llm_config=llm_config, role_prompt="You are low-status."),
    ]

    return config, agents, "basic"


def build_policy_erosion_test():
    """Build Policy Erosion test using scenario registry."""
    llm_config = LLMConfig(dialect="ollama", model="", base_url="http://localhost:11434")

    config = convert_scenario_to_game_config("policy_erosion")

    agents = [
        ExperimentAgent(name="Executive", properties={}, llm_config=llm_config, role_prompt="You are the executive."),
        ExperimentAgent(name="Manager", properties={}, llm_config=llm_config, role_prompt="You are the manager."),
        ExperimentAgent(name="Worker", properties={}, llm_config=llm_config, role_prompt="You are the worker."),
    ]

    return config, agents, "sequential"


def build_echo_chamber_test():
    """Build Echo Chamber test using scenario registry."""
    llm_config = LLMConfig(dialect="ollama", model="", base_url="http://localhost:11434")

    config = convert_scenario_to_game_config("echo_chamber")

    agents = [
        ExperimentAgent(name="ProAgent", properties={}, llm_config=llm_config, role_prompt="You support the topic."),
        ExperimentAgent(name="AntiAgent", properties={}, llm_config=llm_config, role_prompt="You oppose the topic."),
    ]

    return config, agents, "neighbor"


def build_resource_scarcity_test():
    """Build Resource Scarcity test using scenario registry."""
    llm_config = LLMConfig(dialect="ollama", model="", base_url="http://localhost:11434")

    config = convert_scenario_to_game_config("resource_scarcity")

    agents = [
        ExperimentAgent(name="Community1", properties={}, llm_config=llm_config, role_prompt="You value cooperation."),
        ExperimentAgent(name="Community2", properties={}, llm_config=llm_config, role_prompt="You are practical."),
        ExperimentAgent(name="Individualist", properties={}, llm_config=llm_config, role_prompt="You prioritize yourself."),
    ]

    return config, agents, "sharing"


def build_grid_world_test():
    """Build Grid World test using scenario registry."""
    llm_config = LLMConfig(dialect="ollama", model="", base_url="http://localhost:11434")

    config = convert_scenario_to_game_config("grid_world")

    agents = [
        ExperimentAgent(name="Explorer1", properties={}, llm_config=llm_config, role_prompt="You are an explorer."),
        ExperimentAgent(name="Explorer2", properties={}, llm_config=llm_config, role_prompt="You are a gatherer."),
    ]

    return config, agents, "movement"


def build_werewolf_test():
    """Build Werewolf test using scenario registry."""
    llm_config = LLMConfig(dialect="ollama", model="", base_url="http://localhost:11434")

    config = convert_scenario_to_game_config("werewolf")

    agents = [
        ExperimentAgent(name="Villager1", properties={}, llm_config=llm_config, role_prompt="You are a villager."),
        ExperimentAgent(name="Villager2", properties={}, llm_config=llm_config, role_prompt="You are a villager."),
        ExperimentAgent(name="Werewolf", properties={}, llm_config=llm_config, role_prompt="You are a werewolf."),
    ]

    return config, agents, "voting"


def build_pd_multiround_test():
    """Build multi-round Prisoner's Dilemma test for context verification."""
    llm_config = LLMConfig(dialect="ollama", model="", base_url="http://localhost:11434")

    config = convert_scenario_to_game_config("prisoners_dilemma")

    agents = [
        ExperimentAgent(
            name="Alice",
            properties={},
            llm_config=llm_config,
            role_prompt="You are Alice. Remember what happened in previous rounds."
        ),
        ExperimentAgent(
            name="Bob",
            properties={},
            llm_config=llm_config,
            role_prompt="You are Bob. Remember what happened in previous rounds."
        ),
    ]

    return config, agents, "two_rounds"


# =============================================================================
# Main Entry Point
# =============================================================================

async def main():
    parser = argparse.ArgumentParser(description="Run scenario smoke tests")
    parser.add_argument(
        "--models",
        nargs="+",
        default=[DEFAULT_MODEL],
        help="Models to test with",
    )
    parser.add_argument(
        "--scenarios",
        nargs="+",
        default=list(SCENARIO_BUILDERS.keys()),
        help="Scenarios to test",
    )
    parser.add_argument(
        "--all-models",
        action="store_true",
        help="Test with all available models",
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Quick test (single model, single scenario)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("test_results/scenario_smoke_tests"),
        help="Output directory for test results",
    )

    args = parser.parse_args()

    # Determine models
    if args.all_models:
        models = OLLAMA_MODELS
    elif args.quick:
        models = [DEFAULT_MODEL]
        args.scenarios = ["prisoners_dilemma"]
    else:
        models = args.models

    print("=" * 80)
    print("SCENARIO SMOKE TESTS")
    print("=" * 80)
    print(f"Models: {models}")
    print(f"Scenarios: {args.scenarios}")
    print(f"Output: {args.output_dir}")
    print("=" * 80)

    runner = SmokeTestRunner(args.output_dir)

    # Run tests
    for scenario_id in args.scenarios:
        if scenario_id not in SCENARIO_BUILDERS:
            print(f"Unknown scenario: {scenario_id}")
            continue

        builder_name = SCENARIO_BUILDERS[scenario_id]
        builder = globals().get(builder_name)

        if not builder:
            print(f"Builder not found: {builder_name}")
            continue

        # Determine max_rounds based on scenario
        max_rounds = 2 if "multiround" in scenario_id else 1

        for model in models:
            try:
                game_config, agents, test_name = builder()
                await runner.run_test(
                    scenario_id=scenario_id,
                    model=model,
                    test_name=test_name,
                    game_config=game_config,
                    agents=agents,
                    max_rounds=max_rounds,
                )
            except Exception as e:
                print(f"Error running {scenario_id} with {model}: {e}")

    # Print summary
    success = runner.print_summary()

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
