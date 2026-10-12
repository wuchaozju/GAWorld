"""This file checks that the old agent can speak and save itself safely.

The tests make sure legacy policy cascade agents can turn a model reply into
an action and can be stored as plain JSON data.
"""

from __future__ import annotations

import json

from fos.core.actions.base_actions import SendMessageAction, YieldAction
from fos.core.agent import Agent


class FakeChatClient:
    """A tiny chat client that returns one fixed model reply."""

    def __init__(self, response: str) -> None:
        self.response = response
        self.messages: list[list[dict[str, str]]] = []

    def chat(self, messages: list[dict[str, str]], json_mode: bool = False) -> str:
        """Remember the prompt and return the fixed response."""
        self.messages.append(messages)
        return self.response


class FakeScene:
    """A tiny scene that supplies prompt text for a legacy agent."""

    def get_behavior_guidelines(self) -> str:
        """Return short behavior instructions."""
        return "Share one concise policy update."

    def get_agent_status_prompt(self, agent: Agent) -> str:
        """Return the agent-specific scene status."""
        return f"{agent.name} should respond now."


def test_legacy_agent_processes_json_chat_response() -> None:
    """A legacy agent can turn a JSON model reply into an action."""
    agent = Agent(name="Agent 1", role_prompt="You are careful.", user_profile="Top tier")
    client = FakeChatClient('{"action": "send_message", "message": "Policy stays clear."}')

    actions = agent.process({"chat": client}, scene=FakeScene())

    assert actions == [{"action": "send_message", "message": "Policy stays clear."}]
    assert client.messages
    assert agent.short_memory.get_all()[-1] == {
        "role": "assistant",
        "content": '{"action": "send_message", "message": "Policy stays clear."}',
    }


def test_legacy_agent_serialize_has_no_action_objects() -> None:
    """A legacy agent with action objects saves plain action names."""
    agent = Agent(
        name="Agent 1",
        action_space=[SendMessageAction(), YieldAction(), "custom_action"],
    )

    saved = agent.serialize()

    assert saved["action_space"] == ["send_message", "yield", "custom_action"]
    json.dumps(saved)
