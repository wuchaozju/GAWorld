"""Minimal Pipeline B Scene base class.

Policy cascade uses this directly. Pending Pipeline A port.
See docs/plans/policy-cascade-port-investigation.md

Contains: Scene
"""

# TODO: Port PolicyCascadeScene to Pipeline A (ExperimentScene
# subclass) and delete this file. See:
# docs/plans/policy-cascade-port-investigation.md

from fos.core.event import MessageEvent


class Scene:
    """Minimal base class for Pipeline B scenes."""

    def __init__(self, name, initial_event):
        self.name = name
        self.initial_event = initial_event
        self.state = {}

    def set_simulator(self, simulator):
        self._simulator = simulator

    def get_scene_actions(self, agent) -> list:
        return []

    def parse_and_handle_action(self, action_data, agent, simulator) -> tuple:
        raw_action = action_data.get("action")
        if isinstance(raw_action, dict):
            action_name = raw_action.get("name") or raw_action.get("action")
            merged = {k: v for k, v in raw_action.items() if k != "name"}
            for key, value in action_data.items():
                if key != "action":
                    merged[key] = value
            merged["action"] = action_name
            action_data = merged
        else:
            action_name = raw_action

        if action_name == "send_message":
            message = str(action_data.get("message") or "").strip()
            if not message:
                error = "Missing message."
                agent.add_env_feedback(error)
                return False, {"error": error}, f"{agent.name} failed to post", {}, False
            event = MessageEvent(agent.name, message)
            self.deliver_message(event, agent, simulator)
            return True, {"message": message}, f"{agent.name}: {message}", {}, False

        if action_name == "yield":
            return True, {}, f"{agent.name} yielded the floor", {}, True

        return False, {}, None, {}, False

    def deliver_message(self, event, sender, simulator) -> None:
        pass

    def post_turn(self, agent, simulator) -> None:
        pass

    def should_skip_turn(self, agent, simulator) -> bool:
        return False

    def should_extend_run(self, turns, max_turns) -> bool:
        return False

    def is_complete(self) -> bool:
        return False

    def serialize_config(self) -> dict:
        return {}

    @classmethod
    def deserialize_config(cls, data) -> dict:
        return {}

    def serialize(self) -> dict:
        return {
            "type": getattr(self, "TYPE", ""),
            "name": self.name,
            "initial_event": self.initial_event,
            "state": dict(self.state),
        }

    @classmethod
    def deserialize(cls, data: dict) -> "Scene":
        obj = cls.__new__(cls)
        obj.name = data.get("name", "")
        obj.initial_event = data.get("initial_event", "")
        obj.state = dict(data.get("state", {}))
        return obj

    def on_event(self, sim, event_type, data) -> None:
        pass

    def on_private_event(self, sim, event_type, data, recipients) -> None:
        pass

    def get_behavior_guidelines(self) -> str:
        return ""

    def get_output_format(self) -> str:
        return ""

    def get_examples(self) -> str:
        return ""

    def log(self, msg) -> None:
        pass
