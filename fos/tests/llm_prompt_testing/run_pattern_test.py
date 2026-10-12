"""
Single pattern test runner for LLM prompt testing.

Executes comprehensive tests for a single interaction pattern across
all scenarios, models, agents, and iterations.
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .agents import AgentProfile, ALL_AGENTS, get_archetypal_agents
from .config import (
    AVAILABLE_MODELS,
    ModelConfig,
    test_config,
)
from .csv_reporter import CSVReporter, TestResult
from .cross_llm_analyzer import apply_cross_llm_status
from .evaluators import EvaluationResult, evaluate_output
from .ollama_client import ChatMessage, LLMResponse, OllamaClient
from .prompt_builder import build_prompt  # New simplified prompt builder
from .prompt_tuner import PromptTuner
from .scenarios import ScenarioConfig, get_scenarios_for_pattern

logger = logging.getLogger(__name__)


# ============================================================================
# Test Configuration
# ============================================================================

@dataclass
class PatternTestConfig:
    """Configuration for testing a single pattern."""

    pattern: str
    scenarios: List[str] = field(default_factory=list)
    models: List[ModelConfig] = field(default_factory=lambda: AVAILABLE_MODELS)
    agent_types: List[str] = field(default_factory=lambda: ["archetypal", "domain-specific"])
    max_iterations: int = 5
    runs_per_iteration: int = 3
    stop_on_perfect: bool = True


# ============================================================================
# Prompt Builder
# ============================================================================

def build_system_prompt(
    scenario: ScenarioConfig,
    agent: AgentProfile,
    use_simple: bool = True,  # Use simplified prompts by default for 3B-4B models
) -> str:
    """
    Build the system prompt for a test.

    Args:
        scenario: The scenario configuration
        agent: The agent profile

    Returns:
        Complete system prompt string
    """
    prompt = f"""You are {agent.name} - {agent.role_prompt}

Personality: {agent.personality}
Style: {agent.style}

Goals:
{chr(10).join(f"- {g}" for g in agent.goals)}

"""

    # Add scenario-specific instructions
    if scenario.system_instructions:
        prompt += scenario.system_instructions + "\n"

    # Add available actions
    if scenario.actions:
        prompt += "\n" + scenario.get_actions_prompt()
        action_names = ", ".join(f'"{a.name}"' for a in scenario.actions)
        prompt += f"""

IMPORTANT: You MUST use EXACTLY one of these action names: {action_names}
Do NOT invent your own actions. Do NOT use generic phrases like "I choose" or "I decide".
"""

    # Add output format instructions with explicit examples
    first_action = f'"{scenario.actions[0].name}"' if scenario.actions else "action_name"
    prompt += f"""
Output Format (follow exactly - NO OTHER TEXT):
--- Thoughts ---
[Brief thought]

---- Plan ---
Goals: [your goals]
Milestones: [completed ✓, pending →]

---- Action ---
<Action name="{first_action}">
  parameter="value"
</Action>

CRITICAL: Your output must end with the Action tag. Do NOT add explanations, notes, or extra text after the Action tag.
Keep thoughts and plan brief.

EXAMPLE: If choosing to cooperate, output EXACTLY:
--- Thoughts ---
I will cooperate to maximize mutual benefit.

---- Plan ---
Goals: Achieve best outcome
Milestones: → decision made

---- Action ---
<Action name="cooperate" />

That is ALL. No other text after the Action tag.
"""

    return prompt


def build_user_message(
    scenario: ScenarioConfig,
    turn_context: str = "",
) -> str:
    """Build the user message for a test."""
    if turn_context:
        return f"{scenario.description}\n\nCurrent situation: {turn_context}"
    return scenario.description


# ============================================================================
# Single Test Execution
# ============================================================================

@dataclass
class TestExecution:
    """Result of executing a single test."""

    result: TestResult
    response: LLMResponse
    evaluation: EvaluationResult


def execute_single_test(
    scenario: ScenarioConfig,
    agent: AgentProfile,
    model: ModelConfig,
    prompt: str,
    iteration: int,
    run_number: int,
    ollama_client: OllamaClient,
) -> TestExecution:
    """
    Execute a single test run.

    Args:
        scenario: The scenario being tested
        agent: The agent profile
        model: The model configuration
        prompt: The system prompt to use
        iteration: Current iteration number
        run_number: Run number within iteration
        ollama_client: Ollama API client

    Returns:
        TestExecution with result, response, and evaluation
    """
    messages = [
        ChatMessage(role="system", content=prompt),
        ChatMessage(
            role="user",
            content=build_user_message(scenario),
        ),
    ]

    # Call LLM
    start_time = time.time()
    try:
        response = ollama_client.chat_completion(
            messages=messages,
            model=model.api_name,
            temperature=0.7,
            max_tokens=model.max_tokens,
        )
    except Exception as e:
        logger.error(f"LLM call failed: {e}")
        # Create a failed response
        response = LLMResponse(
            content="",
            model=model.api_name,
            time_ms=int((time.time() - start_time) * 1000),
        )

    # Evaluate output
    evaluation = evaluate_output(response.content, scenario, agent)

    # Create test result
    result = TestResult.from_evaluation(
        pattern=scenario.pattern,
        scenario=scenario.id,
        model=model.api_name,
        iteration=iteration,
        run_number=run_number,
        agent_type="archetypal" if agent.name in get_archetypal_agents() else "domain-specific",
        agent_role=agent.name,
        input_prompt=prompt,
        evaluation=evaluation,
        token_count=response.total_tokens,
        time_ms=response.time_ms,
    )

    return TestExecution(result=result, response=response, evaluation=evaluation)


# ============================================================================
# Iteration Test Execution
# ============================================================================

def execute_iteration(
    scenario: ScenarioConfig,
    agent: AgentProfile,
    model: ModelConfig,
    prompt: str,
    iteration: int,
    ollama_client: OllamaClient,
) -> List[TestExecution]:
    """
    Execute a single iteration (3 runs) for a scenario/model/agent combination.

    Args:
        scenario: The scenario being tested
        agent: The agent profile
        model: The model configuration
        prompt: The current prompt
        iteration: Iteration number
        ollama_client: Ollama API client

    Returns:
        List of 3 TestExecution results
    """
    results = []

    for run_number in range(1, 4):  # 3 runs per iteration
        execution = execute_single_test(
            scenario=scenario,
            agent=agent,
            model=model,
            prompt=prompt,
            iteration=iteration,
            run_number=run_number,
            ollama_client=ollama_client,
        )
        results.append(execution)
        logger.info(
            f"Run {run_number}/3: Score={execution.evaluation.overall_score}/4 "
            f"({execution.evaluation.overall_score==4 and 'PASS' or 'FAIL'})"
        )

    return results


# ============================================================================
# Main Pattern Test Runner
# ============================================================================

class PatternTestRunner:
    """
    Runs comprehensive tests for a single interaction pattern.

    Tests all scenarios, models, and agent combinations with iterative
    prompt improvement and cross-LLM analysis.
    """

    def __init__(
        self,
        pattern: str,
        ollama_client: Optional[OllamaClient] = None,
        csv_reporter: Optional[CSVReporter] = None,
        prompt_tuner: Optional[PromptTuner] = None,
    ):
        """
        Initialize the pattern test runner.

        Args:
            pattern: The interaction pattern to test
            ollama_client: Ollama API client (creates default if None)
            csv_reporter: CSV reporter (creates default if None)
            prompt_tuner: Prompt tuner (creates default if None)
        """
        self.pattern = pattern
        self.ollama_client = ollama_client if ollama_client is not None else OllamaClient()
        self.csv_reporter = csv_reporter or CSVReporter()
        self.prompt_tuner = prompt_tuner or PromptTuner()

        # Get scenarios for this pattern
        self.scenarios = get_scenarios_for_pattern(pattern)
        logger.info(f"Testing pattern: {pattern} with {len(self.scenarios)} scenarios")

    def test_scenario(
        self,
        scenario: ScenarioConfig,
        agent: AgentProfile,
        model: ModelConfig,
    ) -> List[TestResult]:
        """
        Test a single scenario/agent/model combination with iterations.

        Args:
            scenario: The scenario to test
            agent: The agent profile to use
            model: The model to use

        Returns:
            List of all test results across iterations
        """
        all_results: List[TestResult] = []
        current_prompt = build_system_prompt(scenario, agent)

        for iteration in range(1, test_config.max_iterations + 1):
            logger.info(
                f"Iteration {iteration}/{test_config.max_iterations}: "
                f"{scenario.id} / {agent.name} / {model.display_name}"
            )

            # Execute the 3 runs for this iteration
            executions = execute_iteration(
                scenario=scenario,
                agent=agent,
                model=model,
                prompt=current_prompt,
                iteration=iteration,
                ollama_client=self.ollama_client,
            )

            # Collect results
            iteration_results = [e.result for e in executions]
            all_results.extend(iteration_results)

            # Write results to CSV
            self.csv_reporter.write_scenario_results(
                iteration_results,
                self.pattern,
                scenario.id,
                mode="a",
            )

            # Evaluate iteration results
            perfect_count = sum(1 for e in executions if e.evaluation.is_perfect)
            avg_score = sum(e.evaluation.overall_score for e in executions) / len(executions)

            logger.info(f"Iteration {iteration} complete: {perfect_count}/3 perfect, avg score {avg_score:.1f}/4")

            # Check if we should stop (all perfect)
            if test_config.stop_on_perfect and perfect_count == len(executions):
                logger.info(f"All runs perfect! Stopping after iteration {iteration}")
                break

            # Otherwise, tune the prompt for next iteration
            if iteration < test_config.max_iterations:
                evaluations = [e.evaluation for e in executions]
                improvement = self.prompt_tuner.tune_prompt(
                    current_prompt=current_prompt,
                    results=evaluations,
                    scenario=scenario,
                    agent=agent,
                    model=model.api_name,
                )
                current_prompt = improvement.new_prompt
                logger.info(f"Prompt improved: {improvement.changes_made}")

        return all_results

    def test_all(
        self,
        scenarios: Optional[List[str]] = None,
        models: Optional[List[str]] = None,
        agent_names: Optional[List[str]] = None,  # Renamed to avoid shadowing
    ) -> Dict[str, List[TestResult]]:
        """
        Test all combinations for this pattern.

        Args:
            scenarios: List of scenario IDs to test (default: all)
            models: List of model names to test (default: all)
            agent_names: List of agent names to test (default: recommended agents)

        Returns:
            Dict mapping scenario ID to list of test results
        """
        results_by_scenario: Dict[str, List[TestResult]] = {}

        # Filter scenarios
        scenarios_to_test = scenarios or [s.id for s in self.scenarios]

        # Filter models
        models_to_test = [m for m in AVAILABLE_MODELS if not models or m.api_name in models]

        # Get recommended agents for this pattern
        agents_to_test: List[AgentProfile] = []
        if agent_names:
            # agent_names is a list of agent names (strings) - look them up in ALL_AGENTS
            agents_to_test = [ALL_AGENTS.get(name) for name in agent_names if name in ALL_AGENTS]
        else:
            # Use a mix of archetypal and domain-specific agents
            from .agents import create_agent_for_pattern
            agents_to_test = create_agent_for_pattern(self.pattern, agent_type="all")[:3]  # Top 3

        total_combinations = (
            len(scenarios_to_test) * len(models_to_test) * len(agents_to_test)
        )
        completed = 0

        logger.info(
            f"Starting full test for {self.pattern}: "
            f"{total_combinations} combinations "
            f"({len(scenarios_to_test)} scenarios × {len(models_to_test)} models × {len(agents_to_test)} agents)"
        )

        for scenario in self.scenarios:
            if scenario.id not in scenarios_to_test:
                continue

            scenario_results: List[TestResult] = []

            for model in models_to_test:
                for agent in agents_to_test:
                    logger.info(f"\n{'='*60}")
                    logger.info(
                        f"Testing: {scenario.id} / {model.display_name} / {agent.name}"
                    )
                    logger.info(f"{'='*60}")

                    results = self.test_scenario(scenario, agent, model)
                    scenario_results.extend(results)
                    completed += 1

                    logger.info(
                        f"Progress: {completed}/{total_combinations} combinations complete"
                    )

            # Apply cross-LLM analysis to this scenario's results
            if scenario_results:
                apply_cross_llm_status(scenario_results, min_pass_count=2)
                self.csv_reporter.write_scenario_results(
                    scenario_results, self.pattern, scenario.id, mode="w"
                )

            results_by_scenario[scenario.id] = scenario_results

        logger.info(f"\nPattern {self.pattern} testing complete!")
        return results_by_scenario


# ============================================================================
# Standalone Test Function
# ============================================================================

def test_pattern(
    pattern: str,
    scenarios: Optional[List[str]] = None,
    models: Optional[List[str]] = None,
    agents: Optional[List[str]] = None,
) -> Dict[str, List[TestResult]]:
    """
    Standalone function to test a pattern.

    Args:
        pattern: The interaction pattern name
        scenarios: Optional list of scenario IDs to test
        models: Optional list of model names to test
        agents: Optional list of agent names to test

    Returns:
        Dict mapping scenario ID to test results
    """
    runner = PatternTestRunner(pattern)
    return runner.test_all(scenarios=scenarios, models=models, agents=agents)



# ============================================================================
# Simplified Prompt Wrapper (overrides original build_system_prompt)
# ============================================================================

def build_system_prompt_override(
    scenario: ScenarioConfig,
    agent: AgentProfile,
    use_simple: bool = True,
) -> str:
    """
    Wrapper that uses the new simplified prompt builder.

    This function shadows the original build_system_prompt to use
    the simplified prompt builder for small 3B-4B models.
    """
    return build_prompt(scenario, agent, use_simple=use_simple)


# Monkey-patch the original function
build_system_prompt = build_system_prompt_override  # noqa: F811
