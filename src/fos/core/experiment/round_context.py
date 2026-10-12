"""
Round Context Manager - maintains cumulative per-agent summaries.

After each round, the context manager updates each agent's summary
with the round's events, creating a running narrative of what happened.

Contains: RoundEvent dataclass, RoundContextManager class.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, TYPE_CHECKING
import asyncio
import logging

from fos.core.experiment.agent import ExperimentAgent
from fos.core.llm.client import LLMClient

if TYPE_CHECKING:
    from fos.core.experiment.information_model import InformationModel


logger = logging.getLogger(__name__)


@dataclass
class RoundEvent:
    """Single event within a round for context tracking.

    Attributes:
        agent_name: Who performed the action
        action_name: What action they took
        parameters: Action parameters
        round_num: Which round this occurred in
        summary: Human-readable summary
        observed_by: List of agents who observe this event (default: [agent_name])
        payoff: Optional payoff earned this round
        feedback: Optional coordination feedback for feedback-based games
    """
    agent_name: str
    action_name: str
    parameters: Dict[str, Any]
    round_num: int
    summary: str
    observed_by: List[str] = field(default_factory=list)
    payoff: Optional[int] = None
    feedback: Optional[str] = None  # Coordination feedback text
    # Transmit cap tracking (for speech truncation)
    transmitted_message: Optional[str] = None  # Capped version shown to neighbours
    truncated: bool = False  # Whether the speech was capped
    full_tokens: int = 0  # Token count of full speech
    transmitted_tokens: int = 0  # Token count of transmitted version

    def __post_init__(self):
        if not self.observed_by:
            self.observed_by = [self.agent_name]


class RoundContextManager:
    """Manages cumulative per-agent context summaries.

    After each round, each agent gets an updated summary that includes
    all previous actions (from their perspective or globally, depending
    on round_visibility setting).
    """

    def __init__(
        self,
        initial_contexts: Dict[str, str] | None = None,
        information_model: "InformationModel | None" = None,
        scene_state: Dict[str, Any] | None = None,
        all_agent_names: List[str] | None = None,
    ):
        """Initialize context manager.

        Args:
            initial_contexts: Optional starting contexts for each agent
            information_model: InformationModel for structured context building
            scene_state: Mutable scene state dict (shared reference with runner)
            all_agent_names: All agent names in the experiment
        """
        self._summaries: Dict[str, str] = initial_contexts or {}
        self._round_events: List[RoundEvent] = []
        self.information_model = information_model
        self.scene_state: Dict[str, Any] = scene_state if scene_state is not None else {}
        self.all_agent_names: List[str] = all_agent_names or []

    def record_action(
        self,
        agent_name: str,
        action_name: str,
        parameters: Dict[str, Any],
        round_num: int,
        summary: str,
        observed_by: List[str] | None = None,
        payoff: int | None = None,
        feedback: str | None = None,
    ) -> None:
        """Record an action for context tracking.

        Args:
            agent_name: Agent who acted
            action_name: Action they took
            parameters: Action parameters
            round_num: Current round number
            summary: Human-readable summary
            observed_by: Agents who observe this event (default: [agent_name])
            payoff: Optional payoff earned this round
            feedback: Optional coordination feedback for this round
        """
        event = RoundEvent(
            agent_name=agent_name,
            action_name=action_name,
            parameters=parameters,
            round_num=round_num,
            summary=summary,
            observed_by=observed_by or [],
            payoff=payoff,
            feedback=feedback,
        )
        self._round_events.append(event)

    def record_action_with_observers(
        self,
        agent_name: str,
        action_name: str,
        parameters: Dict[str, Any],
        round_num: int,
        summary: str,
        payoff: int | None = None,
    ) -> None:
        """Record an action, computing observed_by from the stored InformationModel.

        If no information_model is stored, only the acting agent observes themselves.
        """
        logger = logging.getLogger(__name__)
        if self.information_model and self.all_agent_names:
            logger.debug(f"[CONTEXT] Recording action for {agent_name}: scope_type={self.information_model.scope_type}, scene_state keys={list(self.scene_state.keys())}")
            observed_by = self.information_model.get_observers(
                for_agent=agent_name,
                scene_state=self.scene_state,
                all_agent_names=self.all_agent_names,
                round_num=round_num,
            )
            logger.debug(f"[CONTEXT] {agent_name}'s action observed by: {observed_by}")
        else:
            observed_by = [agent_name]
            logger.debug(f"[CONTEXT] No information_model, {agent_name} observes only self")
        self.record_action(
            agent_name=agent_name,
            action_name=action_name,
            parameters=parameters,
            round_num=round_num,
            summary=summary,
            observed_by=observed_by,
            payoff=payoff,
        )

    def get_context_for_agent(self, agent_name: str, agent_score: int | None = None) -> str:
        """Build structured context for an agent, filtered by observation scope.

        If information_model is set, uses build_structured_context() for deterministic,
        budget-bounded output. Otherwise falls back to get_context() (legacy path).

        Args:
            agent_name: Agent to build context for
            agent_score: Agent's cumulative score (shown if info_model.include_scores)
        """
        if self.information_model is None:
            return self.get_context(agent_name)

        # Deferred import avoids circular dependency
        from fos.core.context_builder import build_structured_context
        visible_events = [
            e for e in self._round_events if agent_name in e.observed_by
        ]
        return build_structured_context(
            for_agent=agent_name,
            events=visible_events,
            info_model=self.information_model,
            agent_score=agent_score if self.information_model.include_scores else None,
            state=self.scene_state.get("state") if self.scene_state else None,
            graph=self.scene_state.get("graph") or self.scene_state.get("social_network") if self.scene_state else None,
        )

    def get_round_events(self, round_num: int) -> List[RoundEvent]:
        """Get all events for a specific round.

        Args:
            round_num: Round number to query

        Returns:
            List of RoundEvent objects for the specified round
        """
        return [e for e in self._round_events if e.round_num == round_num]

    def get_context(self, agent_name: str) -> str:
        """Get the current context summary for an agent.

        Args:
            agent_name: Agent to get context for

        Returns:
            Context summary string, or empty string if none
        """
        return self._summaries.get(agent_name, "")

    def set_initial_context(self, context_summary: str) -> None:
        """Set the same initial context for all agents.

        This is called when running single rounds incrementally,
        to set the context built from previous rounds.

        Args:
            context_summary: Context summary to set for all agents
        """
        # Get all agent names that might have been registered
        # If we don't have names yet, store as default for new agents
        self._default_context = context_summary

        # Update existing summaries
        if hasattr(self, '_summaries'):
            for agent_name in list(self._summaries.keys()):
                if context_summary:
                    self._summaries[agent_name] = context_summary

    async def update_summaries(
        self,
        llm_client: LLMClient,
        agents: List[ExperimentAgent],
        round_num: int
    ) -> None:
        """Update all agent summaries after a round.

        DEPRECATED: This method is no longer called by the runner. The structured
        context builder (build_structured_context) now provides deterministic,
        budget-bounded output without LLM calls. This method is kept for backward
        compatibility but should not be used in new code.

        Each agent gets an LLM-generated summary of what happened.
        The summary is cumulative - it includes previous context plus new events.

        Args:
            llm_client: LLM client for generating summaries
            agents: List of agents in the experiment
            round_num: Current round number
        """
        # Get events for this round
        round_events = self.get_round_events(round_num)

        if not round_events:
            logger.debug(f"No events to summarize for round {round_num}")
            return

        # Build events text
        events_text = "\n".join(f"- {e.summary}" for e in round_events)

        for agent in agents:
            current_summary = self.get_context(agent.name)

            # Build summary prompt
            if current_summary:
                prompt = f"""Update this agent's running summary with new round events.

Current summary:
{current_summary}

New events from round {round_num}:
{events_text}

Return ONLY the updated summary (2-4 sentences). Keep it concise. No markdown."""
            else:
                prompt = f"""Create an initial summary for this agent after round {round_num}.

Events:
{events_text}

Return a concise summary (2-4 sentences). No markdown."""

            try:
                # No JSON mode for summaries - plain text is fine
                new_summary = await asyncio.to_thread(llm_client.chat, [{"role": "user", "content": prompt}])

                # Clean up the response
                new_summary = new_summary.strip().strip('"\'')

                self._summaries[agent.name] = new_summary
                logger.debug(f"Updated summary for {agent.name}: {new_summary[:50]}...")

            except Exception as e:
                logger.error(f"Failed to update summary for {agent.name}: {e}")
                # Keep old summary if update fails
