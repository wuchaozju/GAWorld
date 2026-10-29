"""
This file runs the council-style experiment with debate rounds and voting.

It keeps track of which stage the meeting is in, stores what each person
has seen so far, and makes sure only connected neighbours can see each
other's speeches and votes when a social network is set.
"""
import logging
from enum import Enum
from typing import Any

from fos.i18n import T
from fos.core.experiment.scene import ExperimentScene
from fos.core.experiment.config import ExperimentConfig
from fos.core.experiment.round_context import RoundContextManager
from fos.core.experiment.information_model import InformationModel
from fos.core.experiment.facilitator import CouncilPhase, SystemFacilitator
from fos.experiments.confederates import (
    ConfederateSpec,
    assert_confederate_votes,
    build_confederate_lookup,
)

logger = logging.getLogger(__name__)


class CouncilCyclePhase(Enum):
    """Phase within the deliberation-voting cycle.

    The cycle repeats: DELIBERATION → VOTING → POST_VOTE_DISCUSSION → DELIBERATION → ...

    This is separate from SystemFacilitator.CouncilPhase which handles
    the linear DISCUSSION → VOTING → CONCLUDED flow.
    """
    DELIBERATION = "deliberation"
    VOTING = "voting"
    POST_VOTE_DISCUSSION = "post_vote_discussion"


class CouncilExperimentScene(ExperimentScene):
    """Council experiment scene with phase-based deliberation and voting.

    Integrates with experiment runner for automatic round tracking and
    provides multi-round deliberation context to agents.

    Attributes:
        TYPE: Scene type identifier ("council")
        facilitator: SystemFacilitator for phase management (discussion/voting)
        round_context_manager: RoundContextManager for multi-round context
        round_num: Current round number (1-indexed)
    """
    TYPE = "council"

    def __init__(self, config: ExperimentConfig):
        """Initialize council experiment scene.

        Sets up phase controller for discussion/voting transitions and
        round context manager for multi-round deliberation tracking.

        Args:
            config: Experiment configuration with council parameters
        """
        super().__init__(config)

        # Phase controller for discussion/voting transitions (REFACTOR-COUNCIL-05)
        self.facilitator = SystemFacilitator(self)

        # Configure deliberation rounds from config parameters (FEAT-COUNCIL-03)
        # Parameters dict contains council-specific config like deliberation_rounds
        deliberation_rounds = config.parameters.get("deliberation_rounds")
        logger.info(f"[INIT] config.parameters = {config.parameters}")
        logger.info(f"[INIT] deliberation_rounds from config = {deliberation_rounds}")
        if deliberation_rounds is not None:
            self.facilitator.set_deliberation_rounds(deliberation_rounds)
            logger.info(f"Configured {deliberation_rounds} deliberation rounds before voting")

        # Initialize facilitator round tracking (FEAT-COUNCIL-03)
        # Note: self.round_num is set to 1 at end of __init__, facilitator defaults to 1
        self.facilitator.current_round_num = 1

        # Council experiments use neighbour visibility so the network changes
        # what each person can read from prior rounds.
        info_model = InformationModel(
            scope_type="neighborhood",
            recent_window=3,
            primacy_keep=True,
            include_scores=False,
        )
        self._round_context_scene_state = {
            "state": self.state,
            "graph": self.config.social_network,
            "social_network": self.config.social_network,
        }
        self.round_context_manager = RoundContextManager(
            information_model=info_model,
            scene_state=self._round_context_scene_state,
            all_agent_names=[a.get("name") for a in config.agents],
        )

        # Round tracking (experiment runner increments this)
        self.round_num = 1

        # Cycle phase state for structured deliberation/voting flow
        # NOTE: Votes are stored in self.state.extensions["votes"] (populated by handlers)
        # to integrate with existing vote action handlers in handlers.py
        self.cycle_phase: CouncilCyclePhase = CouncilCyclePhase.DELIBERATION
        self.rounds_in_cycle_phase: int = 0

        # Confederate agent support
        self._conf_lookup: dict[str, ConfederateSpec] = {}
        self._conf_specs: list[ConfederateSpec] = []
        _conf_param = (self.config.parameters or {}).get("confederates") or []
        if _conf_param:
            _specs = [
                ConfederateSpec(
                    agent_id=c["agent_id"],
                    stance=c["stance"],
                    speech_mode=c.get("speech_mode", "llm"),
                )
                for c in _conf_param
            ]
            self._conf_specs = _specs
            self._conf_lookup = build_confederate_lookup(_specs)

        logger.info(f"CouncilExperimentScene initialized with {len(self.agents)} agents")

    def initialize(self, llm_client: Any, provider_clients: dict | None = None) -> None:
        """Build the shared runner, then force council visibility to neighbours."""
        super().initialize(llm_client, provider_clients)
        if self.runner is None:
            raise RuntimeError(T("api.errors.council_runner_not_initialized"))

        info_model = InformationModel(
            scope_type="neighborhood",
            recent_window=3,
            primacy_keep=True,
            include_scores=False,
        )
        self.runner.information_model = info_model
        self.runner.context_manager = RoundContextManager(
            information_model=info_model,
            scene_state=self.runner.scene_state,
            all_agent_names=[a.name for a in self.agents],
        )
        self.runner.controller.context_manager = self.runner.context_manager
        self.round_context_manager = self.runner.context_manager

    def get_visible_observers(self, agent_name: str) -> list[str]:
        """Return the agent plus any directly connected neighbours."""
        return self.round_context_manager.information_model.get_observers(
            for_agent=agent_name,
            scene_state=self._round_context_scene_state,
            all_agent_names=[a.name for a in self.agents],
            round_num=self.round_num,
        )

    def include_social_network_section(self) -> bool:
        """Council prompts use filtered context, so no separate neighbor list is needed."""
        return False

    def get_prior_round_context(self, agent_name: str) -> str:
        """Get multi-round deliberation context for an agent.

        Returns prior round summaries showing what other agents said and did.
        This enables agents to reference previous discussion points, fixing
        BUG-CTX-01 where agents had no prior-round context.

        Args:
            agent_name: Name of agent requesting context

        Returns:
            Context string with prior round history, or "This is the first round - no prior context."
            if no prior actions recorded.
        """
        context = self.round_context_manager.get_context_for_agent(agent_name)

        if not context or context.strip() == "":
            return T("prompts.council_experiment.first_round", locale=self.config.locale)

        return context

    def get_agent_status_prompt(self, agent_name: str) -> str:
        """Get status prompt for agent including prior round context.

        Combines facilitator status (current phase: discussion/voting) with
        multi-round deliberation history to provide full context for agent
        decision-making.

        Args:
            agent_name: Name of agent

        Returns:
            Status prompt with phase info and prior round context, formatted as:
            "Current Phase: discussion/voting
             ---
             Prior Round Deliberation Context:
             [previous speeches and actions]"
        """
        # Get current phase status (discussion/voting/concluded)
        phase_status = self.facilitator.get_status_prompt()

        # Get multi-round deliberation context
        prior_context = self.get_prior_round_context(agent_name)

        # Combine for full context
        return f"{phase_status}\n\n--- Prior Round Deliberation Context ---\n{prior_context}"

    def is_complete(self) -> bool:
        """Check if council experiment is complete.

        Returns:
            True if meeting has been concluded via conclude action, False otherwise
        """
        return self.state.extensions.get("concluded", False)

    def _record_action_to_context(
        self,
        agent_name: str,
        action_name: str,
        parameters: dict[str, Any],
        summary: str
    ) -> None:
        """Record an action to the multi-round context manager.

        Called by action handlers (speak, vote) to make actions visible
        to the acting agent and their neighbours in subsequent rounds.

        Args:
            agent_name: Agent who performed the action
            action_name: Name of the action (speak, vote, etc.)
            parameters: Action parameters (message, choice, etc.)
            summary: Human-readable summary of the action
        """
        self.round_context_manager.record_action(
            agent_name=agent_name,
            action_name=action_name,
            parameters=parameters,
            round_num=self.round_num,
            summary=summary,
            observed_by=self.get_visible_observers(agent_name),
        )

    def get_scene_actions(self, agent_name: str) -> list[str]:
        """Get available actions for agent based on current cycle phase.

        Filters actions to ensure agents only see actions appropriate
        for the current phase:
        - DELIBERATION/POST_VOTE_DISCUSSION: speak, skip
        - VOTING: vote_yes, vote_no, abstain

        Checks BOTH the new cycle_phase AND the legacy facilitator.phase
        for backwards compatibility during migration.

        Args:
            agent_name: Name of agent requesting actions (unused, all agents see same actions)

        Returns:
            List of action names allowed in current phase
        """
        _ = agent_name  # All agents see same actions based on phase

        # Check NEW cycle_phase system
        if self.cycle_phase == CouncilCyclePhase.VOTING:
            return ["vote_yes", "vote_no", "abstain"]

        # Fall back to LEGACY facilitator system for backwards compatibility
        if self.facilitator.phase == CouncilPhase.VOTING:
            return ["vote_yes", "vote_no", "abstain"]

        # Default to deliberation actions
        return ["speak", "skip"]

    def record_vote(self, agent_name: str, vote: str) -> None:
        """Record an agent's vote (only first vote counts).

        Writes to state.extensions["votes"] to integrate with existing handlers.

        Args:
            agent_name: Name of the agent voting
            vote: Vote value - "yes", "no", or "abstain"
        """
        votes = self.state.extensions.get("votes", {})
        if agent_name not in votes:
            votes[agent_name] = vote
            self.state.extensions["votes"] = votes

    def check_voting_threshold(self) -> bool:
        """Check if yes votes meet the threshold percentage.

        Reads from state.extensions["votes"] (populated by handlers and record_vote).

        Returns:
            True if (yes_votes / total_votes) >= threshold
        """
        votes = self.state.extensions.get("votes", {})
        if not votes:
            return False

        total_votes = len(votes)
        yes_votes = sum(1 for v in votes.values() if v == "yes")
        threshold = self.config.parameters.get("voting_threshold", 0.5)

        return (yes_votes / total_votes) >= threshold

    def all_agents_voted(self) -> bool:
        """Check if all agents have cast their votes.

        Reads from state.extensions["votes"] (populated by handlers and record_vote).

        Returns:
            True if every agent has a vote recorded
        """
        votes = self.state.extensions.get("votes", {})
        agent_names = {a.get("name") for a in self.config.agents}
        return agent_names.issubset(votes.keys())


    def set_confederates(self, specs: list[ConfederateSpec]) -> None:
        """Register confederate agents with the scene.

        Called by the runner setup before any rounds are run.

        Args:
            specs: Confederate specifications
        """
        self._conf_specs = list(specs)
        self._conf_lookup = build_confederate_lookup(specs)
        logger.info(
            f"Registered {len(specs)} confederates: "
            f"{[(s.agent_id, s.stance) for s in specs]}"
        )

    def check_cycle_phase_transition(self) -> None:
        """Check and execute cycle phase transition after round completes.

        Transition rules:
        - DELIBERATION → VOTING: After deliberation_rounds complete
        - VOTING → POST_VOTE_DISCUSSION: All agents voted AND threshold met
        - VOTING → DELIBERATION: All agents voted AND threshold NOT met
        - POST_VOTE_DISCUSSION → DELIBERATION: After deliberation_rounds complete
        """
        # NO DEFAULT - fail fast if parameter is missing
        if "deliberation_rounds" not in self.config.parameters:
            raise ValueError(T("deliberation_rounds parameter is required. Got parameters: {parameters}", parameters=self.config.parameters))

        deliberation_rounds = self.config.parameters["deliberation_rounds"]
        logger.info(f"[TRANSITION CHECK] self.config.parameters = {self.config.parameters}")
        logger.info(f"[TRANSITION CHECK] deliberation_rounds = {deliberation_rounds}, rounds_in_cycle_phase = {self.rounds_in_cycle_phase}")

        if self.cycle_phase == CouncilCyclePhase.DELIBERATION:
            if self.rounds_in_cycle_phase >= deliberation_rounds:
                self.cycle_phase = CouncilCyclePhase.VOTING
                self.rounds_in_cycle_phase = 0
                # Clear votes for new voting round
                self.state.extensions["votes"] = {}
                logger.info(f"Transitioning to VOTING phase after {deliberation_rounds} deliberation rounds")

        elif self.cycle_phase == CouncilCyclePhase.VOTING:
            if self.all_agents_voted():
                # Hard assertion: confederate votes must match assigned stances
                if self._conf_specs:
                    assert_confederate_votes(self._conf_specs, self.state.extensions)
                if self.check_voting_threshold():
                    self.cycle_phase = CouncilCyclePhase.POST_VOTE_DISCUSSION
                    logger.info("Threshold met, transitioning to POST_VOTE_DISCUSSION")
                else:
                    self.cycle_phase = CouncilCyclePhase.DELIBERATION
                    logger.info("Threshold not met, transitioning back to DELIBERATION")
                self.rounds_in_cycle_phase = 0
                # Clear votes for next cycle
                self.state.extensions["votes"] = {}

        elif self.cycle_phase == CouncilCyclePhase.POST_VOTE_DISCUSSION:
            if self.rounds_in_cycle_phase >= deliberation_rounds:
                self.cycle_phase = CouncilCyclePhase.DELIBERATION
                self.rounds_in_cycle_phase = 0
                logger.info(f"Transitioning back to DELIBERATION after {deliberation_rounds} post-vote rounds")

    def get_speak_instruction(self) -> str | None:
        """Get brevity instruction for speak action during deliberation phases.

        Returns:
            Brevity instruction string if in DELIBERATION or POST_VOTE_DISCUSSION,
            None otherwise.
        """
        if self.cycle_phase in (CouncilCyclePhase.DELIBERATION, CouncilCyclePhase.POST_VOTE_DISCUSSION):
            return T("experiment.write_one_sentence", locale=self.language) if hasattr(self, "language") else T("experiment.write_one_sentence")
        return None

    def _advance_round(self) -> None:
        """Advance to next round after all agents have acted.

        Increments round counter, phase counter, and checks for phase transitions.
        Called by experiment runner after each round completes.
        """
        old_round = self.round_num
        old_phase_rounds = self.rounds_in_cycle_phase
        old_phase = self.cycle_phase

        self.round_num += 1
        self.rounds_in_cycle_phase += 1

        logger.info(f"[PHASE DEBUG] _advance_round: {old_round} → {self.round_num}, "
                   f"phase_rounds: {old_phase_rounds} → {self.rounds_in_cycle_phase}, "
                   f"phase: {old_phase.value}")

        # Sync round number with facilitator for deliberation enforcement (FEAT-COUNCIL-02)
        self.facilitator.current_round_num = self.round_num

        # Check for cycle phase transition
        self.check_cycle_phase_transition()

    def serialize_config(self) -> dict:
        """Serialize scene state including cycle phase.

        Extends parent serialize_config to include cycle phase state.

        Returns:
            Dict with serialized scene state including cycle phase
        """
        base_config = super().serialize_config()

        # Add cycle phase state to extensions
        if "extensions" not in base_config:
            base_config["extensions"] = {}

        base_config["extensions"]["cycle_phase"] = {
            "phase": self.cycle_phase.value,
            "rounds_in_phase": self.rounds_in_cycle_phase,
            "round_num": self.round_num,  # FIX: Serialize round_num
        }

        logger.info(f"[SERIALIZE] Saving cycle_phase={self.cycle_phase.value}, "
                   f"rounds_in_cycle_phase={self.rounds_in_cycle_phase}, round_num={self.round_num}")
        logger.info(f"[SERIALIZE] config.parameters being saved: {base_config.get('config', {}).get('parameters', {})}")

        return base_config

    @classmethod
    def deserialize_config(cls, data: dict) -> "CouncilExperimentScene":
        """Deserialize scene state including cycle phase.

        Extends parent deserialize_config to restore cycle phase state.

        Args:
            data: Serialized scene state

        Returns:
            New CouncilExperimentScene instance with restored state
        """
        # Log incoming data
        logger.info(f"[DESERIALIZE] Incoming config.parameters: {data.get('config', {}).get('parameters', {})}")

        # Call parent to get base scene (properly initialized)
        scene = super().deserialize_config(data)

        # Log what the scene has after parent deserialization
        logger.info(f"[DESERIALIZE] After parent deserialize, scene.config.parameters: {scene.config.parameters}")

        # Restore cycle phase state from extensions
        cycle_data = data.get("extensions", {}).get("cycle_phase", {})
        if cycle_data:
            scene.cycle_phase = CouncilCyclePhase(cycle_data.get("phase", "deliberation"))
            scene.rounds_in_cycle_phase = cycle_data.get("rounds_in_phase", 0)
            # FIX: Restore round_num
            scene.round_num = cycle_data.get("round_num", 1)
            logger.info(f"[DESERIALIZE] Loaded cycle_phase={scene.cycle_phase.value}, "
                       f"rounds_in_cycle_phase={scene.rounds_in_cycle_phase}, round_num={scene.round_num}")
        else:
            logger.warning("[DESERIALIZE] No cycle_phase data found in extensions, using defaults")

        return scene
