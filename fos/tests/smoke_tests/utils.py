"""
Utilities for formatting smoke test output.

Provides the SmokeTestOutput class for writing formatted test results
to files for human and LLM review.
"""

from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from fos.core.experiment.agent import ExperimentAgent
    from fos.core.experiment.game_configs import GameConfig
    from fos.core.llm_config import LLMConfig


class SmokeTestOutput:
    """Writes formatted smoke test output to file.

    Each output file follows a structured format with:
    - Header with scenario, model, and test name
    - Configuration section
    - Per-round agent prompts and responses
    - Summary with final scores and errors

    Example:
        with SmokeTestOutput(output_dir / "test.txt", "pd", "llama", "coop") as out:
            out.write_config({"param": "value"})
            out.write_round_header(1)
            out.write_agent_prompt("Alice", "You are Alice...")
            out.write_llm_response('{"action": "cooperate"}')
            out.write_processed_result("cooperate", {}, 3)
            out.write_summary({"Alice": 3}, [])
    """

    def __init__(self, filepath: Path, scenario_id: str, model: str, test_name: str):
        """Initialize output writer.

        Args:
            filepath: Path to output file
            scenario_id: Scenario identifier (e.g., "prisoners_dilemma")
            model: Model name (e.g., "phi4-mini:latest")
            test_name: Test case name (e.g., "both_cooperate")
        """
        self.filepath = filepath
        self.scenario_id = scenario_id
        self.model = model
        self.test_name = test_name
        self.file = None

    def __enter__(self):
        """Open file and write header."""
        self.file = open(self.filepath, 'w', encoding='utf-8')
        self._write_header()
        return self

    def __exit__(self, *args):
        """Close file."""
        if self.file:
            self.file.close()

    def _write(self, text: str):
        """Write text to file with newline."""
        self.file.write(text + "\n")

    def _write_separator(self, char: str = "="):
        """Write a separator line."""
        self._write(char * 80)

    def _write_header(self):
        """Write test header."""
        self._write_separator()
        self._write(f"SCENARIO: {self.scenario_id}")
        self._write(f"MODEL: {self.model}")
        self._write(f"TEST: {self.test_name}")
        self._write_separator()
        self._write("")

    def write_config(self, config: Dict[str, Any]):
        """Write configuration section.

        Args:
            config: Dictionary of configuration parameters
        """
        self._write("CONFIGURATION:")
        for key, value in config.items():
            self._write(f"  {key}: {value}")
        self._write("")

    def write_round_header(self, round_num: int):
        """Write round header.

        Args:
            round_num: Round number (1-indexed)
        """
        self._write_separator()
        self._write(f"ROUND {round_num}")
        self._write_separator()

    def write_agent_prompt(self, agent_name: str, prompt: str):
        """Write agent prompt section.

        Args:
            agent_name: Name of the agent
            prompt: Full prompt sent to LLM
        """
        self._write(f"--- AGENT: {agent_name} ---")
        self._write("PROMPT:")
        self._write(prompt)
        self._write("")

    def write_llm_response(self, response: str):
        """Write LLM response section.

        Args:
            response: Raw response from LLM
        """
        self._write("LLM RESPONSE:")
        self._write(response)
        self._write("")

    def write_processed_result(
        self,
        action: str,
        parameters: Dict[str, Any],
        payoff: Optional[float | int]
    ):
        """Write processed action result.

        Args:
            action: Action name
            parameters: Action parameters
            payoff: Payoff value (None if not applicable)
        """
        self._write("PROCESSED:")
        self._write(f"  action: {action}")
        self._write(f"  parameters: {parameters}")
        payoff_str = str(payoff) if payoff is not None else "N/A"
        self._write(f"  payoff: {payoff_str}")
        self._write("")

    def write_action_summary(
        self,
        agent_name: str,
        action: str,
        parameters: Dict[str, Any],
        payoff: Optional[float | int]
    ):
        """Write a brief action summary for round context.

        Args:
            agent_name: Name of the agent
            action: Action name
            parameters: Action parameters
            payoff: Payoff value
        """
        params_str = f"({parameters})" if parameters else ""
        payoff_str = f" → {payoff}" if payoff is not None else ""
        self._write(f"  {agent_name}: {action}{params_str}{payoff_str}")

    def write_summary(self, scores: Dict[str, float | int], errors: List[str]):
        """Write test summary.

        Args:
            scores: Final scores per agent
            errors: List of errors encountered
        """
        self._write_separator()
        self._write("SUMMARY")
        self._write_separator()
        self._write(f"Final scores: {scores}")
        self._write(f"Errors: {errors if errors else 'None'}")
        self._write(f"Timestamp: {datetime.now().isoformat()}")


def build_game_config(
    scenario_id: str,
    actions: List[str],
    action_descriptions: Dict[str, str] = None,
    description: str = "",
    payoff_summary: str = "",
    payoff_type: str = "matrix",
    grouping_mode: str = "pairwise",
    payoff_config: Dict[str, Any] = None,
) -> "GameConfig":
    """Build a GameConfig for testing.

    Args:
        scenario_id: Scenario identifier
        actions: List of valid action names
        action_descriptions: Optional action descriptions
        description: Scenario description
        payoff_summary: Payoff explanation
        payoff_type: Type of payoff calculation
        grouping_mode: How agents are grouped
        payoff_config: Payoff configuration

    Returns:
        GameConfig instance
    """
    from fos.core.experiment.game_configs import GameConfig

    return GameConfig(
        name=scenario_id,
        description=description,
        action_type="discrete",
        actions=actions,
        action_descriptions=action_descriptions or {},
        payoff_summary=payoff_summary,
        payoff_type=payoff_type,
        grouping_mode=grouping_mode,
        payoff_config=payoff_config or {},
    )


def build_experiment_agent(
    name: str,
    llm_config: "LLMConfig",
    role_prompt: str = None,
    properties: Dict[str, Any] = None,
) -> "ExperimentAgent":
    """Build an ExperimentAgent for testing.

    Args:
        name: Agent name
        llm_config: LLM configuration
        role_prompt: Optional role prompt
        properties: Optional agent properties

    Returns:
        ExperimentAgent instance
    """
    from fos.core.experiment.agent import ExperimentAgent

    return ExperimentAgent(
        name=name,
        properties=properties or {},
        llm_config=llm_config,
        role_prompt=role_prompt,
    )
