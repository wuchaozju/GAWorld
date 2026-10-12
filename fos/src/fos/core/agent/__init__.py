"""Minimal Pipeline B Agent class.

Used by policy_cascade and simtree_runtime legacy path.
Pending Pipeline A port.
See docs/plans/policy-cascade-port-investigation.md

Contains: Agent
"""

# TODO: Port PolicyCascadeScene to Pipeline A (ExperimentScene
# subclass) and delete this file. See:
# docs/plans/policy-cascade-port-investigation.md

from __future__ import annotations

import json
import re
from typing import Any

from fos.core.agent.parsing import strip_thinking_tokens
from fos.i18n import T


class Agent:
    """Minimal legacy Agent for Pipeline B scenes."""

    class _ShortMemory:
        def __init__(self):
            self.history = []

        def get_all(self) -> list:
            return self.history

        def append(self, role, content):
            self.history.append({"role": role, "content": content})

        def clear(self):
            self.history = []

        def __len__(self) -> int:
            return len(self.history)

    def __init__(self, name: str, **kwargs):
        self.name = name
        self.properties = kwargs.get("properties", {})
        self.role_prompt = kwargs.get("role_prompt", "")
        self.user_profile = kwargs.get("user_profile", "")
        self.language = kwargs.get("language", "en")
        self.action_space = kwargs.get("action_space", [])
        self.knowledge_base = kwargs.get("knowledge_base", [])
        self.documents = kwargs.get("documents", {})
        self.score = kwargs.get("score", 0)
        self.consecutive_llm_errors = 0
        self.is_offline = False
        self.short_memory = Agent._ShortMemory()

    def serialize(self) -> dict:
        return {
            "name": self.name,
            "properties": dict(self.properties),
            "role_prompt": self.role_prompt,
            "user_profile": self.user_profile,
            "language": self.language,
            "action_space": [_serialize_action(action) for action in self.action_space],
            "knowledge_base": list(self.knowledge_base),
            "documents": dict(self.documents),
            "score": self.score,
            "short_memory": self.short_memory.get_all(),
        }

    def process(
        self,
        clients: dict[str, Any],
        initiative: bool = False,
        scene: Any | None = None,
    ) -> list[dict[str, Any]]:
        """Ask the model for one legacy action and return it as plain data."""
        client = _select_chat_client(clients, self.properties)
        prompt = self._build_prompt(scene, initiative)
        messages = [*self.short_memory.get_all(), {"role": "user", "content": prompt}]
        response = client.chat(messages, json_mode=True)
        cleaned = strip_thinking_tokens(str(response or ""))
        action = _parse_action_response(cleaned)
        self.short_memory.append("user", prompt)
        self.short_memory.append("assistant", cleaned)
        return [action] if action else []

    def _build_prompt(self, scene: Any | None, initiative: bool) -> str:
        """Build the short prompt used by the old policy cascade runner."""
        parts = [f"You are {self.name}."]
        if self.user_profile:
            parts.append(self.user_profile)
        if self.role_prompt:
            parts.append(self.role_prompt)
        if scene is not None and hasattr(scene, "get_behavior_guidelines"):
            parts.append(str(scene.get_behavior_guidelines()))
        if scene is not None and hasattr(scene, "get_agent_status_prompt"):
            parts.append(str(scene.get_agent_status_prompt(self)))
        actions = [_serialize_action(action) for action in self.action_space]
        if actions:
            parts.append("Available actions: " + ", ".join(actions))
        if initiative:
            parts.append("Take initiative if the scene calls for it.")
        parts.append('Reply as JSON, for example {"action":"yield"}.')
        return "\n\n".join(part for part in parts if part)

    def add_env_feedback(self, msg: str) -> None:
        self.short_memory.append("system", msg)

    def set_global_knowledge(self, knowledge: list) -> None:
        self.knowledge_base = knowledge

    @classmethod
    def deserialize(cls, data: dict) -> "Agent":
        props = data.get("properties", {})
        agent = cls(
            name=data["name"],
            properties=props,
            role_prompt=data.get("role_prompt") or data.get("rolePrompt", ""),
            user_profile=data.get("user_profile") or data.get("userProfile", ""),
            language=data.get("language", "en"),
            action_space=data.get("action_space") or data.get("actionSpace", []),
            knowledge_base=data.get("knowledge_base") or data.get("knowledgeBase", []),
            documents=data.get("documents", {}),
            score=data.get("score", 0),
        )
        for entry in data.get("short_memory", []):
            agent.short_memory.append(entry.get("role", ""), entry.get("content", ""))
        return agent


def _select_chat_client(clients: dict[str, Any], properties: dict) -> Any:
    """Pick the chat client the old agent should use."""
    provider_id = properties.get("provider_id")
    if provider_id is not None and provider_id in clients:
        return clients[provider_id]
    client = clients.get("chat") or clients.get("default")
    if client is None:
        raise RuntimeError(T("api.errors.legacy_chat_client_missing"))
    return client


def _serialize_action(action: Any) -> str:
    """Turn an action object or string into a saved action name."""
    if isinstance(action, str):
        return action
    name = getattr(action, "NAME", None) or getattr(action, "name", None)
    return str(name or action.__class__.__name__)


def _parse_action_response(response: str) -> dict[str, Any]:
    """Turn a model response into one action dictionary."""
    text = response.strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass
    match = re.search(r'<Action\s+name="([^"]+)"\s*(?:/|>(.*?)</Action>)', text, re.DOTALL)
    if not match:
        return {"action": "send_message", "message": text}
    action: dict[str, Any] = {"action": match.group(1)}
    for key, value in re.findall(r"<(\w+)>(.*?)</\1>", match.group(2) or "", re.DOTALL):
        action[key] = value.strip()
    return action
