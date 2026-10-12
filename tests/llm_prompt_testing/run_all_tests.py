"""
Main entry point for LLM prompt testing.

Orchestrates testing across all interaction patterns, spawning
separate agents for each pattern to run in parallel.
"""

import argparse
import logging
import sys
from pathlib import Path
from typing import Dict, List, Optional

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from tests.llm_prompt_testing.config import (
    AVAILABLE_MODELS,
    INTERACTION_PATTERNS,
    test_config,
)
from tests.llm_prompt_testing.csv_reporter import CSVReporter
from tests.llm_prompt_testing.cross_llm_analyzer import (
    build_model_capability_profiles,
    generate_capability_matrix,
    generate_model_recommendations,
)
from tests.llm_prompt_testing.ollama_client import OllamaClient
from tests.llm_prompt_testing.run_pattern_test import PatternTestRunner


def setup_logging(level: str = "INFO") -> None:
    """Configure logging for the test framework."""
    log_level = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(test_config.log_file, mode="a"),
        ],
    )


def test_single_pattern(
    pattern: str,
    scenarios: Optional[List[str]] = None,
    models: Optional[List[str]] = None,
    agent_names: Optional[List[str]] = None,  # Renamed from agents
) -> bool:
    """
    Test a single interaction pattern.

    Args:
        pattern: The pattern name
        scenarios: Optional list of scenario IDs
        models: Optional list of model names
        agent_names: Optional list of agent names

    Returns:
        True if testing completed successfully
    """
    logger = logging.getLogger(f"PatternTest.{pattern}")

    if pattern not in INTERACTION_PATTERNS:
        logger.error(f"Unknown pattern: {pattern}")
        return False

    logger.info(f"Starting tests for pattern: {pattern}")

    try:
        runner = PatternTestRunner(pattern)
        results = runner.test_all(scenarios=scenarios, models=models, agent_names=agent_names)

        total_results = sum(len(r) for r in results.values())
        perfect_results = sum(
            sum(1 for r in results if r.overall_score == 4) for results in results.values()
        )

        logger.info(
            f"Pattern {pattern} complete: "
            f"{perfect_results}/{total_results} perfect results"
        )
        return True

    except Exception as e:
        logger.error(f"Error testing pattern {pattern}: {e}", exc_info=True)
        return False


def test_all_patterns(
    patterns: Optional[List[str]] = None,
    scenarios: Optional[List[str]] = None,
    models: Optional[List[str]] = None,
    agents: Optional[List[str]] = None,
) -> Dict[str, bool]:
    """
    Test all or specified interaction patterns.

    Args:
        patterns: List of pattern names (default: all)
        scenarios: Optional list of scenario IDs
        models: Optional list of model names
        agents: Optional list of agent names

    Returns:
        Dict mapping pattern name to success status
    """
    patterns_to_test = patterns or INTERACTION_PATTERNS
    results: Dict[str, bool] = {}

    for pattern in patterns_to_test:
        results[pattern] = test_single_pattern(
            pattern=pattern,
            scenarios=scenarios,
            models=models,
            agents=agents,
        )

    return results


def generate_final_report() -> None:
    """Generate the final summary report with model capability analysis."""
    logger = logging.getLogger("ReportGenerator")

    try:
        reporter = CSVReporter()

        # Collect all results
        all_results = []
        for pattern in INTERACTION_PATTERNS:
            pattern_dir = (
                reporter.results_dir
                / pattern.replace(" & ", "_").replace(" ", "_").lower()
            )
            if pattern_dir.exists():
                for scenario_file in pattern_dir.glob("*.csv"):
                    scenario_results = reporter.read_scenario_results(
                        pattern, scenario_file.stem
                    )
                    all_results.extend(scenario_results)

        if not all_results:
            logger.warning("No results found to generate report")
            return

        # Build model capability profiles
        profiles = build_model_capability_profiles(all_results)

        # Generate report
        report_lines = [
            "# LLM Prompt Testing - Final Report",
            f"\nGenerated at: {reporter.results_dir}\n",
            "## Test Summary\n",
            f"- **Total Test Runs**: {len(all_results)}",
            f"- **Patterns Tested**: {len(INTERACTION_PATTERNS)}",
            f"- **Models Tested**: {len(AVAILABLE_MODELS)}",
            "\n---\n",
        ]

        # Add capability matrix
        report_lines.append(generate_capability_matrix(profiles, INTERACTION_PATTERNS))

        # Add model recommendations
        report_lines.append(generate_model_recommendations(profiles))

        # Write report
        report_path = reporter.results_dir / "final_report.md"
        with open(report_path, "w", encoding="utf-8") as f:
            f.write("\n".join(report_lines))

        logger.info(f"Final report written to {report_path}")

    except Exception as e:
        logger.error(f"Error generating final report: {e}", exc_info=True)


def main():
    """Main entry point for the test framework."""
    parser = argparse.ArgumentParser(
        description="LLM Prompt Testing Framework for FOS"
    )

    parser.add_argument(
        "--pattern",
        type=str,
        help="Specific interaction pattern to test (default: all)",
        choices=INTERACTION_PATTERNS,
    )
    parser.add_argument(
        "--scenario",
        type=str,
        action="append",
        help="Specific scenario ID(s) to test (can be specified multiple times)",
    )
    parser.add_argument(
        "--model",
        type=str,
        action="append",
        help="Specific model(s) to test (can be specified multiple times)",
        choices=[m.api_name for m in AVAILABLE_MODELS],
    )
    parser.add_argument(
        "--agent",
        type=str,
        action="append",
        help="Specific agent(s) to test (can be specified multiple times)",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level (default: INFO)",
    )
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="Only generate the final report from existing results",
    )
    parser.add_argument(
        "--test-connection",
        action="store_true",
        help="Test Ollama connection and exit",
    )

    args = parser.parse_args()

    # Setup logging
    setup_logging(args.log_level)
    logger = logging.getLogger("main")

    # Test connection if requested
    if args.test_connection:
        client = OllamaClient()
        if client.test_connection():
            logger.info("Ollama connection successful")
            return 0
        else:
            logger.error("Ollama connection failed")
            return 1

    # Generate report only if requested
    if args.report_only:
        generate_final_report()
        return 0

    # Verify Ollama connection before starting
    logger.info("Testing Ollama connection...")
    client = OllamaClient()
    if not client.test_connection():
        logger.error("Cannot connect to Ollama. Exiting.")
        return 1

    # Run tests
    start_msg = "Starting LLM Prompt Testing"
    if args.pattern:
        start_msg += f" for pattern: {args.pattern}"
    else:
        start_msg += f" for all {len(INTERACTION_PATTERNS)} patterns"
    logger.info(start_msg)

    if args.pattern:
        success = test_single_pattern(
            pattern=args.pattern,
            scenarios=args.scenario,
            models=args.model,
            agents=args.agent,
        )
        result = 0 if success else 1
    else:
        results = test_all_patterns(
            scenarios=args.scenario,
            models=args.model,
            agents=args.agent,
        )
        result = 0 if all(results.values()) else 1

    # Generate final report
    logger.info("Generating final report...")
    generate_final_report()

    logger.info("Testing complete!")
    return result


if __name__ == "__main__":
    sys.exit(main())
