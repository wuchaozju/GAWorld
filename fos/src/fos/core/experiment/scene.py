"""This file exposes the experiment scene and gives it its starting values."""

import logging
from typing import Any

from fos.core.experiment.config import ExperimentConfig
from fos.core.experiment.scene_configuration import SceneConfigurationMixin
from fos.core.experiment.scene_lifecycle import SceneLifecycleMixin
from fos.core.experiment.scene_prompts import ScenePromptMixin
from fos.core.experiment.scene_runtime import SceneRuntimeMixin
from fos.core.experiment.state import ExperimentState

logger = logging.getLogger(__name__)


class ExperimentScene(
    SceneLifecycleMixin,
    SceneConfigurationMixin,
    ScenePromptMixin,
    SceneRuntimeMixin,
):
    """Run a standalone experiment without the older scene bridge."""

    TYPE = "experiment_template"

    def __init__(self, config: ExperimentConfig):
        """Store the experiment settings and create empty runtime state."""
        self.config = config
        self.global_knowledge: dict[str, Any] = config.global_knowledge
        self.agents = []
        self.runner = None
        self.llm_client = None
        self.current_round = 0
        self._history: list[dict[str, Any]] = []
        self._pending_host_messages: list[str] = []
        self.state = ExperimentState()
        self._pgg_phase = "allocate"

        logger.debug(
            "ExperimentScene initialized: scenario_id='%s' (type: %s)",
            config.scenario_id,
            type(config.scenario_id).__name__,
        )
