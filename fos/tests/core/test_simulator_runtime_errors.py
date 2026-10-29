"""This file checks that old simulator failures are visible to the tree UI.

The tests make sure an agent turn problem is written into the node event log
and remembered as a runtime error.
"""

from __future__ import annotations

from fos.core.ordering import SequentialOrdering
from fos.core.simulator import Simulator


class BrokenAgent:
    """A small agent that fails when asked to act."""

    def __init__(self) -> None:
        self.name = "Agent 1"
        self.action_space: list[str] = []
        self.properties: dict[str, str] = {}
        self.short_memory: list[dict[str, str]] = []

    def add_env_feedback(self, message: str) -> None:
        """Store scene feedback so simulator setup can finish."""
        self.short_memory.append({"role": "system", "content": message})

    def process(self, clients: dict, initiative: bool = False, scene: object | None = None) -> list[dict]:
        """Fail in the same place a broken legacy agent turn fails."""
        raise RuntimeError("agent could not act")


class OneTurnScene:
    """A small scene that lets one agent turn run."""

    def __init__(self) -> None:
        self.initial_event = "start"
        self.state = {"time": 0}
        self.complete = False

    def get_scene_actions(self, agent: BrokenAgent) -> list[str]:
        """Return no extra actions."""
        return []

    def is_complete(self) -> bool:
        """Report whether the scene has finished."""
        return self.complete

    def should_skip_turn(self, agent: BrokenAgent, simulator: Simulator) -> bool:
        """Let the agent try to act."""
        return False

    def post_turn(self, agent: BrokenAgent, simulator: Simulator) -> None:
        """Finish after the first attempted turn."""
        self.complete = True


def test_simulator_emits_error_event_when_agent_turn_fails() -> None:
    """An agent turn failure appears in the simulator event stream."""
    events: list[tuple[str, dict]] = []
    simulator = Simulator(
        agents=[BrokenAgent()],
        scene=OneTurnScene(),
        clients={},
        ordering=SequentialOrdering(),
        event_handler=lambda kind, data: events.append((kind, data)),
    )

    simulator.run(max_turns=1)

    error_events = [data for kind, data in events if kind == "error"]
    assert error_events
    assert error_events[-1]["agent"] == "Agent 1"
    assert error_events[-1]["error_type"] == "RuntimeError"
    assert "agent could not act" in error_events[-1]["message"]
    assert simulator.last_runtime_error is not None


def test_simulator_stops_after_first_agent_turn_failure() -> None:
    """One broken provider creates one visible error, not repeated copies."""
    events: list[tuple[str, dict]] = []
    simulator = Simulator(
        agents=[BrokenAgent()],
        scene=OneTurnScene(),
        clients={},
        ordering=SequentialOrdering(),
        event_handler=lambda kind, data: events.append((kind, data)),
    )
    simulator.scene.post_turn = lambda agent, sim: None

    simulator.run(max_turns=5)

    error_events = [data for kind, data in events if kind == "error"]
    assert len(error_events) == 1
    assert simulator.turns == 0
