"""
Strategic Decisions pattern test runner.

Runs comprehensive tests for Strategic Decisions pattern across:
- Scenarios: prisoners_dilemma, stag_hunt, minimum_effort
- Models: gemma3:4b-it-qat, ministral-3:3b
- Iterations: Up to 5 (3 runs each)
- Stops early if perfect scores achieved
"""

import logging
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from tests.llm_prompt_testing.run_pattern_test import (  # noqa: E402
    PatternTestRunner,
)
from tests.llm_prompt_testing.agents import get_archetypal_agents  # noqa: E402
from tests.llm_prompt_testing.config import AVAILABLE_MODELS, test_config  # noqa: E402
from tests.llm_prompt_testing.cross_llm_analyzer import apply_cross_llm_status  # noqa: E402
from tests.llm_prompt_testing.scenarios import (  # noqa: E402
    get_scenarios_for_pattern,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('test_results/strategic_decisions_test.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


def run_strategic_decisions_tests():
    """
    Run Strategic Decisions pattern tests with specified parameters.

    Test configuration:
    - Pattern: Strategic Decisions
    - Scenarios: prisoners_dilemma, stag_hunt, minimum_effort
    - Models: gemma3:4b-it-qat, ministral-3:3b
    - Iterations: Up to 5 (3 runs each)
    - Stop early: Yes (if all perfect)
    """
    pattern = "Strategic Decisions"
    scenarios_to_test = ["prisoners_dilemma", "stag_hunt", "minimum_effort"]
    models_to_test = [
        m for m in AVAILABLE_MODELS
        if m.api_name in ["gemma3:4b-it-qat", "ministral-3:3b"]
    ]

    # Get recommended agents for Strategic Decisions pattern
    agents_to_test = get_archetypal_agents().values()

    logger.info("="*60)
    logger.info("STRATEGIC DECISIONS PATTERN TEST")
    logger.info("="*60)
    logger.info(f"Pattern: {pattern}")
    logger.info(f"Scenarios: {scenarios_to_test}")
    logger.info(f"Models: {[m.api_name for m in models_to_test]}")
    logger.info(f"Agents: {[a.name for a in agents_to_test]}")
    logger.info(f"Iterations: Up to {test_config.max_iterations}")
    logger.info(f"Runs per iteration: {test_config.runs_per_iteration}")
    logger.info(f"Stop on perfect: {test_config.stop_on_perfect}")
    logger.info("="*60)

    # Initialize runner
    runner = PatternTestRunner(pattern=pattern)

    # Get scenarios for this pattern
    all_scenarios = get_scenarios_for_pattern(pattern)
    scenarios_to_run = [s for s in all_scenarios if s.id in scenarios_to_test]

    total_combinations = len(scenarios_to_run) * len(models_to_test) * len(agents_to_test)
    completed = 0
    all_results_by_scenario = {}

    for scenario in scenarios_to_run:
        logger.info(f"\n{'='*60}")
        logger.info(f"SCENARIO: {scenario.id} - {scenario.name}")
        logger.info(f"{'='*60}")

        scenario_results = []

        for model in models_to_test:
            for agent in agents_to_test:
                logger.info(f"\nTesting: {scenario.id} / {model.display_name} / {agent.name}")

                # Run test with iterations
                results = runner.test_scenario(
                    scenario=scenario,
                    agent=agent,
                    model=model,
                )
                scenario_results.extend(results)
                completed += 1

                # Calculate statistics for this combination
                perfect_count = sum(1 for r in results if r.overall_score == 4)
                avg_score = sum(r.overall_score for r in results) / len(results)
                iterations_run = max(r.iteration for r in results)

                logger.info(
                    f"Results: {perfect_count}/{len(results)} perfect, "
                    f"avg score {avg_score:.1f}/4, "
                    f"iterations: {iterations_run}"
                )

                logger.info(f"Progress: {completed}/{total_combinations} combinations complete")

        # Apply cross-LLM analysis to this scenario's results
        if scenario_results:
            apply_cross_llm_status(scenario_results, min_pass_count=2)
            runner.csv_reporter.write_scenario_results(
                scenario_results, pattern, scenario.id, mode="w"
            )
            all_results_by_scenario[scenario.id] = scenario_results

            # Log cross-LLM summary
            logger.info(f"\nCross-LLM Analysis for {scenario.id}:")
            for model in models_to_test:
                model_results = [r for r in scenario_results if r.model == model.api_name]
                if model_results:
                    pass_count = sum(1 for r in model_results if r.cross_llm_status == "PASS")
                    logger.info(
                        f"  {model.display_name}: {pass_count}/{len(model_results)} PASS"
                    )

    # Generate final summary
    logger.info(f"\n{'='*60}")
    logger.info("FINAL SUMMARY")
    logger.info(f"{'='*60}")

    for scenario_id, results in all_results_by_scenario.items():
        total = len(results)
        perfect = sum(1 for r in results if r.overall_score == 4)
        cross_llm_pass = sum(1 for r in results if r.cross_llm_status == "PASS")

        logger.info(
            f"{scenario_id}: {perfect}/{total} perfect, "
            f"{cross_llm_pass}/{total} cross-LLM PASS"
        )

    logger.info("\nResults saved to: test_results/strategic_decisions/")
    return all_results_by_scenario


if __name__ == "__main__":
    run_strategic_decisions_tests()
