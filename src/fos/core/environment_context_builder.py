"""
This file pulls real simulation behavior into one simple environment snapshot.

Each function here does one small job:
- `build_environment_context` reads a simulator and returns a grounded snapshot.
- `_build_experiment_context` reads finished experiment rounds.
- `_build_legacy_context` reads older simulator state.
- `_collect_recent_runtime_events` keeps the newest emitted events.
- `_is_environment_runtime_event` keeps only runtime events that are truly environment-facing.
- `_collect_policy_signals` pulls notice and follow-up state from policy scenes.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class ActionEvidence:
    """Store one finished agent action in a plain, easy-to-read shape."""

    round_num: int
    agent_name: str
    action_name: str
    summary: str
    parameters: dict[str, Any] = field(default_factory=dict)
    feedback: str | None = None


@dataclass(slots=True)
class EnvironmentContextSnapshot:
    """Store the behavior snapshot used by the environment agent."""

    current_turn: int
    agent_count: int
    recent_actions: list[ActionEvidence] = field(default_factory=list)
    recent_rounds: list[dict[str, Any]] = field(default_factory=list)
    action_totals: dict[str, int] = field(default_factory=dict)
    recent_events: list[dict[str, Any]] = field(default_factory=list)
    scene_signals: dict[str, Any] = field(default_factory=dict)
    resources: dict[str, float] = field(default_factory=dict)
    agents: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Turn the snapshot into a plain dictionary for callers."""
        return asdict(self)


def build_environment_context(
    simulator: Any,
    *,
    recent_external_events: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Read one simulator and return a grounded environment snapshot."""
    current_turn = _read_current_turn(simulator)
    scene = getattr(simulator, "scene", None)
    if hasattr(scene, "_history"):
        snapshot = _build_experiment_context(simulator, current_turn)
    else:
        snapshot = _build_legacy_context(simulator, current_turn)

    runtime_events = _collect_recent_runtime_events(simulator)
    snapshot.recent_events.extend(runtime_events)
    if recent_external_events:
        snapshot.recent_events.extend(recent_external_events)
    snapshot.scene_signals.update(_collect_policy_signals(scene))
    return snapshot.to_dict()


def _build_experiment_context(simulator: Any, current_turn: int) -> EnvironmentContextSnapshot:
    """Read finished experiment rounds from a Pipeline A scene."""
    scene = simulator.scene
    history = list(getattr(scene, "_history", []) or [])
    agents = list(getattr(scene, "agents", []) or [])
    action_totals: dict[str, int] = {}
    recent_actions: list[ActionEvidence] = []

    for round_entry in history[-3:]:
        round_num = int(round_entry.get("round", 0) or 0)
        for action in round_entry.get("actions", []) or []:
            action_name = str(action.get("action") or "").strip()
            if not action_name:
                continue
            action_totals[action_name] = action_totals.get(action_name, 0) + 1
            recent_actions.append(
                ActionEvidence(
                    round_num=round_num,
                    agent_name=str(action.get("agent") or "").strip(),
                    action_name=action_name,
                    summary=str(action.get("summary") or "").strip(),
                    parameters=dict(action.get("parameters") or {}),
                    feedback=str(action.get("feedback") or "").strip() or None,
                )
            )

    snapshot = EnvironmentContextSnapshot(
        current_turn=current_turn,
        agent_count=len(agents),
        recent_actions=recent_actions,
        recent_rounds=history[-3:],
        action_totals=action_totals,
        agents=[
            {
                "name": getattr(agent, "name", ""),
                "score": getattr(agent, "score", 0),
                "recent_action_count": len(getattr(agent, "action_history", []) or []),
                "feedback_buffer_size": len(getattr(agent, "feedback_buffer", []) or []),
            }
            for agent in agents
        ],
    )
    return snapshot


def _build_legacy_context(simulator: Any, current_turn: int) -> EnvironmentContextSnapshot:
    """Read a smaller snapshot from an older simulator scene."""
    agents_map = getattr(simulator, "agents", {}) or {}
    scene = getattr(simulator, "scene", None)
    scene_state = getattr(scene, "state", {}) or {}
    resources = scene_state.get("resources") or {}
    normalized_resources = {
        str(key): float(value)
        for key, value in resources.items()
        if isinstance(value, (int, float))
    }
    return EnvironmentContextSnapshot(
        current_turn=current_turn,
        agent_count=len(agents_map),
        resources=normalized_resources,
        agents=[
            {
                "name": getattr(agent, "name", name),
                "in_conflict": bool(getattr(agent, "properties", {}).get("in_conflict", False)),
                "feedback_buffer_size": len(getattr(agent, "feedback_buffer", []) or []),
            }
            for name, agent in agents_map.items()
        ],
        scene_signals={"scene_state_keys": sorted(str(key) for key in scene_state.keys())[:12]},
    )


def _collect_recent_runtime_events(simulator: Any) -> list[dict[str, Any]]:
    """Keep only the newest runtime events that represent outside conditions."""
    events = list(getattr(simulator, "events", []) or [])
    recent: list[dict[str, Any]] = []
    for item in events[-8:]:
        if not isinstance(item, dict):
            continue
        event_type = str(item.get("type") or "").strip()
        event_data = dict(item.get("data") or {})
        if not _is_environment_runtime_event(event_type, event_data):
            continue
        recent.append(
            {
                "type": event_type,
                "title": _pick_runtime_event_title(event_type, event_data),
                "data": event_data,
            }
        )
    return recent


def _is_environment_runtime_event(event_type: str, event_data: dict[str, Any]) -> bool:
    """Keep only runtime events that reflect outside notices or broadcasts."""
    allowed_types = {
        "public_event",
        "system_broadcast",
        "environment_notice_received",
        "environment_private_notice_received",
        "public_broadcast",
    }
    if event_type in allowed_types:
        return True
    return bool(event_data.get("notice_only")) and event_type == "environment"


def _pick_runtime_event_title(event_type: str, event_data: dict[str, Any]) -> str:
    """Build a short event title from runtime event data."""
    for key in ("title", "content", "message", "text"):
        value = str(event_data.get(key) or "").strip()
        if value:
            return value
    return event_type


def _collect_policy_signals(scene: Any) -> dict[str, Any]:
    """Pull notice and follow-up state from policy scenes when present."""
    state = getattr(scene, "state", None)
    if not isinstance(state, dict):
        return {}
    private_events = state.get("private_events") or {}
    follow_up_conditions = state.get("pending_follow_up_conditions") or {}
    active_targets = state.get("active_tier_targets") or {}
    return {
        "task_mode": str(state.get("task_mode") or ""),
        "notice_kind": str(state.get("notice_kind") or ""),
        "latest_notice": str(state.get("latest_notice") or ""),
        "latest_environment_notice": str(state.get("latest_environment_notice") or ""),
        "policy_version": int(state.get("policy_version", 0) or 0),
        "private_event_count": len(private_events),
        "pending_follow_up_count": len(follow_up_conditions),
        "active_target_count": len(active_targets),
    }


def _read_current_turn(simulator: Any) -> int:
    """Read the current turn number from either simulator style."""
    turns = getattr(simulator, "turns", None)
    if turns is not None:
        return int(turns)
    scene = getattr(simulator, "scene", None)
    return int(getattr(scene, "current_round", 0) or 0)
