"""Minimal legacy Simulator for Pipeline B scenes.

Orchestrates agent turns, event broadcasting, and scene lifecycle.
Minimal legacy Simulator stub.

Contains: Simulator
"""

from __future__ import annotations

import logging
from copy import deepcopy
from queue import Queue
from typing import Callable, List, Optional

from fos.core.agent import Agent
from fos.core.environment_config import EnvironmentConfig
from fos.core.ordering import SequentialOrdering
from fos.i18n import T

logger = logging.getLogger(__name__)


class Simulator:
    """Minimal legacy Simulator for Pipeline B simulation orchestration."""

    def __init__(
        self,
        agents: List[Agent],
        scene,
        clients,
        broadcast_initial=True,
        max_steps_per_turn=5,
        ordering=None,
        event_handler: Callable[[str, dict], None] = None,
        environment_config: Optional[EnvironmentConfig] = None,
    ):
        self.started = False
        self.log_event = event_handler
        for agent in agents:
            agent.log_event = self.log_event
        self.environment_config = environment_config or EnvironmentConfig()
        self._suggestions_viewed_turn = None
        self.agents = {agent.name: agent for agent in agents}
        self.clients = clients
        self.scene = scene
        if hasattr(scene, "set_simulator"):
            scene.set_simulator(self)
        self.turns = 0
        self.max_steps_per_turn = max_steps_per_turn
        self.ordering = ordering
        if self.ordering:
            self.ordering.set_simulation(self)
        self.event_queue = Queue()
        self.order_iter = self.ordering.iter() if self.ordering else iter([])
        self.last_runtime_error: RuntimeError | None = None

        if broadcast_initial:
            for agent in agents:
                if hasattr(self.scene, "initialize_agent"):
                    self.scene.initialize_agent(agent)
                scene_actions = self.scene.get_scene_actions(agent) or []
                existing = {getattr(a, "NAME", None) for a in agent.action_space}
                for act in scene_actions:
                    name = getattr(act, "NAME", None)
                    if name and name not in existing:
                        agent.action_space.append(act)
            self.broadcast(self.scene.initial_event)
            if hasattr(self.scene, "pre_run"):
                self.scene.pre_run(self)
        self.started = True

    def emit_event(self, event_type: str, data: dict):
        if self.log_event:
            self.log_event(event_type, data)

    def emit_event_later(self, event_type: str, data: dict):
        self.event_queue.put((event_type, data))

    def emit_remaining_events(self):
        while not self.event_queue.empty():
            event_type, data = self.event_queue.get_nowait()
            self.emit_event(event_type, data)

    def reset_event_queue(self):
        self.event_queue = Queue()

    def broadcast(self, event, receivers: Optional[List[str]] = None):
        sender = event.get_sender() if hasattr(event, "get_sender") else None
        time = self.scene.state.get("time") if self.scene.state else None
        formatted = event.to_string(time) if hasattr(event, "to_string") else str(event)
        allow_set = {str(r).strip() for r in receivers} if receivers else None
        recipients = []
        for agent in self.agents.values():
            if agent.name == sender:
                continue
            if allow_set is not None and agent.name not in allow_set:
                continue
            agent.add_env_feedback(formatted)
            recipients.append(agent.name)
        payload = {
            "time": time,
            "type": type(event).__name__,
            "sender": sender,
            "recipients": recipients,
            "text": event.to_string() if hasattr(event, "to_string") else str(event),
        }
        code = getattr(event, "code", None)
        if code:
            payload["code"] = code
        params = getattr(event, "params", None)
        if params is not None:
            payload["params"] = params
        self.emit_event_later("system_broadcast", payload)

    def serialize(self):
        ord_state = self.ordering.serialize() if self.ordering else None
        snap = {
            "agents": {name: agent.serialize() for name, agent in self.agents.items()},
            "scene": self.scene.serialize() if hasattr(self.scene, "serialize") else {},
            "max_steps_per_turn": int(self.max_steps_per_turn),
            "ordering": getattr(self.ordering, "NAME", "sequential") if self.ordering else "sequential",
            "ordering_state": ord_state,
            "event_queue": list(self.event_queue.queue),
            "turns": int(self.turns),
            "environment_config": self.environment_config.serialize(),
            "_suggestions_viewed_turn": self._suggestions_viewed_turn,
        }
        return deepcopy(snap)

    @classmethod
    def deserialize(cls, data, clients, log_handler=None):
        data = deepcopy(data)
        from fos.core.registry import get_scene_class
        scenario_data = data["scene"]
        scene_type = scenario_data["type"]
        scene_class = get_scene_class(scene_type)
        if not scene_class:
            raise ValueError(T("Unknown scene type: {scene_type}", scene_type=scene_type))
        scene = scene_class.deserialize(scenario_data)
        agents = [Agent.deserialize(ad) for ad in data["agents"].values()]
        env_cfg = EnvironmentConfig.deserialize(data.get("environment_config", {}))

        ordering = None
        ordering_name = data.get("ordering", "sequential")
        if ordering_name == "sequential":
            ordering = SequentialOrdering()

        sim = cls(
            agents=agents, scene=scene, clients=clients,
            broadcast_initial=False,
            max_steps_per_turn=data.get("max_steps_per_turn", 5),
            event_handler=log_handler,
            environment_config=env_cfg,
            ordering=ordering,
        )
        sim.turns = data.get("turns", 0)
        sim._suggestions_viewed_turn = data.get("_suggestions_viewed_turn")

        ordering_state = data.get("ordering_state")
        if ordering and ordering_state:
            ordering.deserialize(ordering_state)

        return sim

    def are_environment_suggestions_available(self) -> bool:
        if not self.environment_config.enabled or self.turns == 0:
            return False
        interval = self.environment_config.turn_interval
        current_interval = (self.turns // interval) * interval
        if self._suggestions_viewed_turn == current_interval:
            return False
        return self.turns >= interval

    def dismiss_environment_suggestions(self) -> None:
        interval = self.environment_config.turn_interval
        self._suggestions_viewed_turn = (self.turns // interval) * interval

    def run(self, max_turns=1000):
        turns = 0
        self.last_runtime_error = None
        if hasattr(self.scene, "reset_for_run"):
            self.scene.reset_for_run()
        while True:
            self.emit_remaining_events()
            over_limit = turns >= max_turns
            should_extend = False
            if over_limit and hasattr(self.scene, "should_extend_run"):
                should_extend = bool(self.scene.should_extend_run(turns, max_turns))
            if over_limit and not should_extend:
                break
            if self.scene.is_complete():
                break
            agent_name = next(self.order_iter)
            agent = self.agents.get(agent_name)
            if not agent:
                continue
            if self.scene.should_skip_turn(agent, self):
                self.scene.post_turn(agent, self)
                self.ordering.post_turn(agent.name)
                turns += 1
                continue
            steps = 0
            continue_turn = True
            self.emit_remaining_events()
            while continue_turn and steps < self.max_steps_per_turn:
                try:
                    action_datas = agent.process(self.clients, initiative=False, scene=self.scene)
                    if not action_datas:
                        break
                    yielded = False
                    for action_data in action_datas:
                        if not action_data:
                            continue
                        success, result, summary, meta, pass_control = (
                            self.scene.parse_and_handle_action(action_data, agent, self)
                        )
                        self.emit_remaining_events()
                        if bool(pass_control):
                            yielded = True
                            break
                except Exception as error:
                    logger.exception("Exception during agent turn", extra={"agent": agent.name})
                    self.last_runtime_error = RuntimeError(
                        f"Agent {agent.name} turn failed: {error}"
                    )
                    self.emit_event(
                        "error",
                        {
                            "agent": agent.name,
                            "error_type": type(error).__name__,
                            "message": str(error),
                        },
                    )
                    return
                steps += 1
                if yielded:
                    continue_turn = False
            self.scene.post_turn(agent, self)
            self.emit_remaining_events()
            self.ordering.post_turn(agent.name)
            turns += 1
            self.turns = turns
