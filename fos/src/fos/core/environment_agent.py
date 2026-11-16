"""
This file turns simulation behavior into grounded host suggestions.

Each class and function here does one clear job:
- `SemanticAnalyzer` keeps the optional model-powered helper behavior.
- `EnvironmentAgent.analyze_state` reads the snapshot and measures what is happening.
- `EnvironmentAgent.generate_suggestions` turns those measurements into concrete host suggestions.
- `EnvironmentAgent.apply_event` puts a typed event into a plain context dictionary.
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from fos.core.external_event import ExternalEvent, ExternalEventType, Severity

from fos.i18n import T

logger = logging.getLogger(__name__)

_INACTIVE_ACTIONS = {"yield", "skip", "wait", "pass", "observe", "monitor"}
_CONFLICT_ACTIONS = {"defect", "reduce", "punish", "attack", "block", "escalate", "reject"}


@dataclass(slots=True)
class SuggestionSignal:
    """Store one measured pattern the host may want to react to."""

    name: str
    score: float
    detail: str
    severity: str
    event_type: str


@dataclass(slots=True)
class EnvironmentAnalysisResult:
    """Store the measured state that drives suggestion generation."""

    timestamp: int
    agent_count: int
    resource_pressure: float
    social_tension: float
    dominant_action_share: float
    inactivity_ratio: float
    conflict_ratio: float
    shock_level: float
    trends: list[str] = field(default_factory=list)
    risk_factors: list[str] = field(default_factory=list)
    signals: list[SuggestionSignal] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Turn the result into the dictionary shape used by callers."""
        return {
            "timestamp": self.timestamp,
            "agent_count": self.agent_count,
            "resource_pressure": self.resource_pressure,
            "social_tension": self.social_tension,
            "dominant_action_share": self.dominant_action_share,
            "inactivity_ratio": self.inactivity_ratio,
            "conflict_ratio": self.conflict_ratio,
            "shock_level": self.shock_level,
            "trends": list(self.trends),
            "risk_factors": list(self.risk_factors),
            "signals": [
                {
                    "name": signal.name,
                    "score": signal.score,
                    "detail": signal.detail,
                    "severity": signal.severity,
                    "event_type": signal.event_type,
                }
                for signal in self.signals
            ],
        }


class SemanticAnalyzer:
    """Offer optional event analysis when a model client is available."""

    def __init__(self, llm_client: Any | None = None) -> None:
        """Store the optional model client."""
        self.llm_client = llm_client

    async def analyze_event_relevance(
        self,
        event: ExternalEvent,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """Estimate how relevant one external event is to the current snapshot."""
        if not self.llm_client:
            return self._rule_based_analysis(event, context)
        return await self._llm_analysis(event, context)

    async def analyze_agent_impact(
        self,
        event: ExternalEvent,
        agent_states: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Estimate which agents are most affected by one external event."""
        if not self.llm_client:
            return self._rule_based_agent_impact(event, agent_states)
        return await self._llm_agent_impact(event, agent_states)

    def _rule_based_analysis(
        self,
        event: ExternalEvent,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """Estimate event relevance with plain rules."""
        relevance_score = 0.5
        if event.event_type == ExternalEventType.MARKET and context.get("resource_pressure", 0.0) > 0.4:
            relevance_score = 0.75
        if event.event_type == ExternalEventType.POLICY and context.get("social_tension", 0.0) > 0.25:
            relevance_score = 0.8
        urgency = {
            Severity.CRITICAL: 1.2,
            Severity.HIGH: 1.0,
            Severity.MEDIUM: 0.8,
            Severity.LOW: 0.6,
        }.get(event.severity, 1.0)
        return {
            "relevance_score": min(1.0, relevance_score),
            "urgency_modifier": urgency,
            "affected_domains": self._get_affected_domains(event.event_type),
            "recommended_response": self._get_recommended_response(event),
        }

    def _rule_based_agent_impact(
        self,
        event: ExternalEvent,
        agent_states: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Estimate agent impact with plain rules."""
        impacts: list[dict[str, Any]] = []
        for agent in agent_states:
            impact_score = 0.3
            factors: list[str] = []
            agent_type = str(agent.get("type", "generic"))
            if event.event_type == ExternalEventType.MARKET and agent_type in {"trader", "merchant", "banker"}:
                impact_score = 0.8
                factors.append("Economic role likely to react to market pressure.")
            if event.event_type == ExternalEventType.POLICY and agent_type in {"governor", "official", "bureaucrat"}:
                impact_score = 0.7
                factors.append("Government role likely to react to policy changes.")
            impacts.append(
                {
                    "agent_id": agent.get("id"),
                    "agent_type": agent_type,
                    "impact_score": min(1.0, impact_score),
                    "factors": factors,
                }
            )
        return impacts

    async def _llm_analysis(
        self,
        event: ExternalEvent,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """Log the prompt and fall back to the safe rule-based path for now."""
        prompt = (
            f"Event={event.title}\nType={event.event_type.value}\nSeverity={event.severity.value}\n"
            f"Turns={context.get('current_turn', 0)}\nSignals={context.get('risk_factors', [])}"
        )
        logger.debug("LLM environment analysis prompt: %s", prompt[:200])
        return self._rule_based_analysis(event, context)

    async def _llm_agent_impact(
        self,
        event: ExternalEvent,
        agent_states: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Fall back to the safe rule-based path for now."""
        return self._rule_based_agent_impact(event, agent_states)

    def _get_affected_domains(self, event_type: ExternalEventType) -> list[str]:
        """List the broad areas one event type touches."""
        return {
            ExternalEventType.POLICY: ["governance", "regulation", "law"],
            ExternalEventType.MARKET: ["economy", "trade", "finance"],
            ExternalEventType.NEWS: ["public_opinion", "sentiment", "media"],
            ExternalEventType.CUSTOM: ["custom_domain"],
            ExternalEventType.MANUAL: ["host_intervention"],
        }.get(event_type, ["unknown"])

    def _get_recommended_response(self, event: ExternalEvent) -> str:
        """Return a short response hint based on severity."""
        if event.severity == Severity.CRITICAL:
            return "Immediate action required."
        if event.severity == Severity.HIGH:
            return "Respond within the current cycle."
        if event.severity == Severity.MEDIUM:
            return "Plan a response for the next round."
        return "Monitor and reassess."


class EnvironmentAgent:
    """Read one environment snapshot and suggest grounded host interventions."""

    def __init__(self, clients: dict[str, Any] | None = None) -> None:
        """Store optional clients and the semantic helper."""
        self.clients = clients or {}
        self.semantic_analyzer = SemanticAnalyzer(llm_client=self.clients.get("llm"))

    def analyze_state(self, context: dict[str, Any]) -> dict[str, Any]:
        """Measure the most important behavior patterns in the snapshot."""
        recent_actions = list(context.get("recent_actions", []) or [])
        action_names = [str(action.get("action_name") or "").strip().lower() for action in recent_actions]
        action_names = [name for name in action_names if name]
        action_counts = Counter(action_names)
        total_actions = sum(action_counts.values())
        dominant_action_share = (max(action_counts.values()) / total_actions) if total_actions else 0.0
        inactivity_ratio = self._ratio_for_keywords(action_counts, _INACTIVE_ACTIONS, total_actions)
        conflict_ratio = self._ratio_for_keywords(action_counts, _CONFLICT_ACTIONS, total_actions)
        shock_level = self._calculate_shock_level(context)
        resource_pressure = self._calculate_resource_pressure(context)
        social_tension = max(self._calculate_social_tension(context), conflict_ratio)

        trends: list[str] = []
        risk_factors: list[str] = []
        signals: list[SuggestionSignal] = []

        if inactivity_ratio >= 0.4:
            detail = self._build_inactivity_detail(context, inactivity_ratio)
            trends.append(detail)
            risk_factors.append("Round behavior is stalling.")
            signals.append(SuggestionSignal("stall", inactivity_ratio, detail, "moderate", "notification"))

        if conflict_ratio >= 0.25:
            detail = self._build_conflict_detail(context, conflict_ratio)
            trends.append(detail)
            risk_factors.append("Conflict-style actions are spreading.")
            signals.append(SuggestionSignal("conflict", conflict_ratio, detail, "severe" if conflict_ratio >= 0.5 else "moderate", "emergency"))

        if dominant_action_share >= 0.75 and total_actions >= max(3, context.get("agent_count", 0)):
            detail = self._build_dominance_detail(action_counts, dominant_action_share)
            trends.append(detail)
            risk_factors.append("One action is dominating the whole round.")
            signals.append(SuggestionSignal("concentration", dominant_action_share, detail, "mild", "opinion"))

        if shock_level > 0:
            detail = self._build_shock_detail(context, shock_level)
            trends.append(detail)
            risk_factors.append("Recent notices or outside events may be changing behavior.")
            signals.append(SuggestionSignal("shock", shock_level, detail, "moderate", "notification"))

        result = EnvironmentAnalysisResult(
            timestamp=int(context.get("current_turn", context.get("time", 0)) or 0),
            agent_count=int(context.get("agent_count", len(context.get("agents", []))) or 0),
            resource_pressure=resource_pressure,
            social_tension=social_tension,
            dominant_action_share=dominant_action_share,
            inactivity_ratio=inactivity_ratio,
            conflict_ratio=conflict_ratio,
            shock_level=shock_level,
            trends=trends,
            risk_factors=risk_factors,
            signals=signals,
        )
        return result.to_dict()

    def generate_suggestions(
        self,
        context: dict[str, Any],
        count: int = 3,
    ) -> list[dict[str, Any]]:
        """Turn measured behavior into grounded host suggestions."""
        analysis = self.analyze_state(context)
        suggestions: list[dict[str, Any]] = []

        for signal in sorted(analysis["signals"], key=lambda item: item["score"], reverse=True):
            suggestions.append(
                {
                    "event_type": signal["event_type"],
                    "description": self._build_suggestion_text(signal),
                    "severity": signal["severity"],
                    "grounding": signal["detail"],
                }
            )

        if analysis["resource_pressure"] > 0.8:
            suggestions.append(
                {
                    "event_type": "notification",
                    "description": T("prompts.env_agent.resource_pressure", locale="en"),
                    "severity": "moderate",
                    "grounding": f"Resource pressure is {analysis['resource_pressure']:.2f}.",
                }
            )

        if not suggestions:
            suggestions.append(
                {
                    "event_type": "notification",
                    "description": T("prompts.env_agent.stable_probing", locale="en"),
                    "severity": "mild",
                    "grounding": "No strong instability signal was found in the latest finished rounds.",
                }
            )

        return suggestions[:count]

    def apply_event(self, event: ExternalEvent, context: dict[str, Any]) -> bool:
        """Put one external event into the right plain context bucket."""
        event_type = event.event_type
        if event_type == ExternalEventType.POLICY:
            context.setdefault("policy_events", []).append(event.to_dict())
            return True
        if event_type == ExternalEventType.MARKET:
            context.setdefault("market_events", []).append(event.to_dict())
            return True
        if event_type == ExternalEventType.NEWS:
            context.setdefault("news_events", []).append(event.to_dict())
            return True
        if event_type == ExternalEventType.MANUAL:
            context.setdefault("manual_events", []).append(event.to_dict())
            return True
        return False

    def _calculate_resource_pressure(self, context: dict[str, Any]) -> float:
        """Measure how full the resource bucket looks."""
        resources = context.get("resources", {})
        if not resources:
            return 0.0
        total = sum(value for value in resources.values() if isinstance(value, (int, float)))
        capacity = context.get("resource_capacity", total * 2)
        if capacity == 0:
            return 0.0
        return min(1.0, total / capacity)

    def _calculate_social_tension(self, context: dict[str, Any]) -> float:
        """Measure direct conflict markers in agent state."""
        agents = context.get("agents", [])
        if not agents:
            return 0.0
        conflicts = sum(1 for agent in agents if agent.get("in_conflict", False))
        return min(1.0, conflicts / max(1, len(agents)))

    def _calculate_shock_level(self, context: dict[str, Any]) -> float:
        """Measure how strongly recent outside events are shaping the next round."""
        recent_events = list(context.get("recent_events", []) or [])
        scene_signals = dict(context.get("scene_signals", {}) or {})
        if not recent_events and not scene_signals.get("latest_notice") and not scene_signals.get("latest_environment_notice"):
            return 0.0
        shock_points = min(3, len(recent_events)) * 0.2
        if scene_signals.get("latest_notice"):
            shock_points += 0.25
        if scene_signals.get("pending_follow_up_count", 0):
            shock_points += 0.15
        return min(1.0, shock_points)

    def _ratio_for_keywords(self, action_counts: Counter[str], keywords: set[str], total_actions: int) -> float:
        """Measure how much of the round matches a keyword set."""
        if total_actions == 0:
            return 0.0
        matching = sum(count for action, count in action_counts.items() if action in keywords)
        return matching / total_actions

    def _build_inactivity_detail(self, context: dict[str, Any], inactivity_ratio: float) -> str:
        """Describe the stall pattern in plain language."""
        current_turn = int(context.get("current_turn", 0) or 0)
        percentage = round(inactivity_ratio * 100)
        return f"In the most recent finished rounds up to round {current_turn}, about {percentage}% of tracked actions were stall-type choices such as yield or skip."

    def _build_conflict_detail(self, context: dict[str, Any], conflict_ratio: float) -> str:
        """Describe the conflict pattern in plain language."""
        current_turn = int(context.get("current_turn", 0) or 0)
        percentage = round(conflict_ratio * 100)
        return f"By round {current_turn}, about {percentage}% of tracked actions were conflict-style choices such as defect, punish, or escalate."

    def _build_dominance_detail(self, action_counts: Counter[str], dominant_action_share: float) -> str:
        """Describe the one-sided action pattern in plain language."""
        dominant_action, dominant_count = action_counts.most_common(1)[0]
        percentage = round(dominant_action_share * 100)
        return f"The action '{dominant_action}' dominated the recent rounds with {dominant_count} uses, or about {percentage}% of all tracked actions."

    def _build_shock_detail(self, context: dict[str, Any], shock_level: float) -> str:
        """Describe the recent outside-shock pattern in plain language."""
        recent_events = list(context.get("recent_events", []) or [])
        scene_signals = dict(context.get("scene_signals", {}) or {})
        notice = scene_signals.get("latest_environment_notice") or scene_signals.get("latest_notice")
        if notice:
            return f"A recent notice is still active in scene state: '{str(notice)[:120]}'. Shock level is {shock_level:.2f}."
        if recent_events:
            latest = recent_events[-1]
            return f"The latest tracked outside event was '{latest.get('title') or latest.get('type')}'. Shock level is {shock_level:.2f}."
        return f"Recent outside inputs produce a shock level of {shock_level:.2f}."

    def _build_suggestion_text(self, signal: dict[str, Any]) -> str:
        """Turn one measured signal into a host-ready suggestion."""
        if signal["name"] == "stall":
            return f"{signal['detail']} Inject a concrete deadline, new incentive, or short-term pressure so the next round has a reason to move."
        if signal["name"] == "conflict":
            return f"{signal['detail']} Inject a stabilizing notice, mediation prompt, or costly outside consequence before the next round deepens the conflict."
        if signal["name"] == "concentration":
            return f"{signal['detail']} Inject a countervailing event so agents must react to something new instead of repeating the same dominant move."
        if signal["name"] == "shock":
            return f"{signal['detail']} Inject a clarifying follow-up notice so agents respond to the changed conditions in a more explicit way next round."
        return signal["detail"]
