"""
Experiment module - Three-Layer Architecture for strategic experiments.

Layer 1: ExperimentAgent (lightweight agent with properties)
Layer 2: PromptBuilder (5-section structured prompts)
Layer 3: ExperimentController (action validation and execution)

Orchestrated by: ExperimentRunner
Configured by: ExperimentConfig, ExperimentScene
"""

from fos.core.experiment.agent import ExperimentAgent
from fos.core.experiment.config import ExperimentConfig
from fos.core.experiment.controller import ExperimentController
from fos.core.experiment.game_configs import GameConfig
from fos.core.experiment.kernel import ExperimentKernel
from fos.core.experiment.prompt_builder import build_prompt, build_reprompt
from fos.core.experiment.runner import ExperimentRunner, RoundResult
from fos.core.experiment.scene import ExperimentScene

__all__ = [
    "ExperimentAgent",
    "ExperimentConfig",
    "ExperimentController",
    "ExperimentKernel",
    "ExperimentRunner",
    "ExperimentScene",
    "GameConfig",
    "RoundResult",
    "build_prompt",
    "build_reprompt",
]
