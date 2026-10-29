"""
This file checks that the environment agent uses finished round behavior.

Each test here does one small job:
- `test_environment_agent_grounds_suggestions_in_round_actions` checks that conflict-heavy rounds change the suggestion text.
- `test_environment_context_filters_internal_runtime_events` checks that internal action events do not become outside shocks.
"""

from fos.core.environment_context_builder import build_environment_context
from fos.core.environment_agent import EnvironmentAgent


def test_environment_agent_grounds_suggestions_in_round_actions() -> None:
    """Conflict-heavy finished rounds should produce a grounded conflict suggestion."""
    agent = EnvironmentAgent()

    suggestions = agent.generate_suggestions(
        {
            "current_turn": 4,
            "agent_count": 4,
            "recent_actions": [
                {"round_num": 3, "agent_name": "Alice", "action_name": "defect", "summary": "Defected"},
                {"round_num": 3, "agent_name": "Bob", "action_name": "punish", "summary": "Punished"},
                {"round_num": 4, "agent_name": "Carol", "action_name": "escalate", "summary": "Escalated"},
                {"round_num": 4, "agent_name": "Dan", "action_name": "reduce", "summary": "Reduced"},
            ],
            "recent_rounds": [],
            "action_totals": {"defect": 1, "punish": 1, "escalate": 1, "reduce": 1},
            "recent_events": [],
            "scene_signals": {},
            "agents": [],
        }
    )

    assert suggestions
    assert suggestions[0]["event_type"] == "emergency"
    assert "defect" in suggestions[0]["description"] or "punish" in suggestions[0]["description"]


def test_environment_context_filters_internal_runtime_events() -> None:
    """Internal action events should not be treated as outside environment events."""

    class _FakeSimulator:
        """Hold the tiny fields the context builder reads."""

        def __init__(self) -> None:
            self.turns = 2
            self.scene = object()
            self.events = [
                {"type": "experiment_action", "data": {"action": "defect"}},
                {"type": "public_event", "data": {"message": "Storm warning"}},
            ]

    context = build_environment_context(_FakeSimulator())

    assert len(context["recent_events"]) == 1
    assert context["recent_events"][0]["type"] == "public_event"
    assert "Storm warning" in context["recent_events"][0]["title"]
