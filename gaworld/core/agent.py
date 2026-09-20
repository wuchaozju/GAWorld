"""Typed :class:`Agent` adapter sitting on top of the legacy ``dict`` agent.

The codebase passes ``agent`` around as a plain ``dict`` with two dozen
fields. Replacing every callsite at once would require touching almost
every module. This adapter takes a different approach:

* :class:`Agent` is a :class:`dataclass` whose ``__getitem__`` /
  ``__setitem__`` delegate to a backing ``dict``. New code can use the
  dataclass directly; legacy code that does ``agent["state"]["energy"]``
  keeps working unchanged.
* :func:`view_as_agent` wraps an existing dict (cheap; no copy).
* :func:`ensure_agent_dict` returns the underlying dict, so legacy
  helpers that expect ``dict`` signatures keep working too.

This is intentionally a thin shim. As subsystems migrate, they can
move to typed access (``agent.state``) and we can tighten the field
list. For S2 the priority is to provide a single named type that
researchers can import.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterator, Mapping


@dataclass
class Agent:
    """Mutable view of an agent record.

    Attributes
    ----------
    data:
        Backing ``dict`` that owns the actual key/value store; sharing
        this dict with legacy code keeps the simulator working without
        copying state on every step.
    """

    data: dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Conventional getters
    # ------------------------------------------------------------------
    @property
    def id(self) -> int | None:
        value = self.data.get("id")
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    @property
    def name(self) -> str:
        return str(self.data.get("name", ""))

    @property
    def state(self) -> dict[str, float]:
        s = self.data.setdefault("state", {})
        return s if isinstance(s, dict) else {}

    @property
    def memory(self) -> list[dict[str, Any]]:
        m = self.data.setdefault("memory", [])
        return m if isinstance(m, list) else []

    @property
    def schedule(self) -> list[dict[str, Any]]:
        s = self.data.setdefault("schedule", [])
        return s if isinstance(s, list) else []

    @property
    def location(self) -> str | None:
        loc = self.data.get("location")
        return str(loc) if loc is not None else None

    @property
    def skill_ids(self) -> list[str]:
        """IDs of global Skills attached to this agent.

        Private (agent-summarised) skills live on disk under the
        agent's memory directory and are discovered by the
        :class:`gaworld.skills.registry.SkillRegistry`; only attached
        *global* skills need to be tracked here.
        """
        s = self.data.setdefault("skill_ids", [])
        return s if isinstance(s, list) else []

    def need(self, key: str, default: float = 0.0) -> float:
        try:
            return float(self.state.get(key, default))
        except (TypeError, ValueError):
            return float(default)

    # ------------------------------------------------------------------
    # dict-like interface (kept so legacy callsites keep working)
    # ------------------------------------------------------------------
    def __getitem__(self, key: str) -> Any:
        return self.data[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self.data[key] = value

    def __delitem__(self, key: str) -> None:
        del self.data[key]

    def __contains__(self, key: object) -> bool:
        return key in self.data

    def __iter__(self) -> Iterator[str]:
        return iter(self.data)

    def __len__(self) -> int:
        return len(self.data)

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def setdefault(self, key: str, default: Any) -> Any:
        return self.data.setdefault(key, default)

    def update(self, other: Mapping[str, Any] | None = None, **kwargs: Any) -> None:
        if other is not None:
            self.data.update(other)
        if kwargs:
            self.data.update(kwargs)

    # ------------------------------------------------------------------
    # Conversion helpers
    # ------------------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        """Return the underlying dict (no copy)."""
        return self.data

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "Agent":
        if isinstance(payload, dict):
            return cls(data=payload)
        return cls(data=dict(payload))


def view_as_agent(payload: Mapping[str, Any] | "Agent") -> Agent:
    """Return an :class:`Agent` view over ``payload`` without copying.

    Useful when consuming a legacy ``dict`` agent in a function that
    wants the typed surface.
    """
    if isinstance(payload, Agent):
        return payload
    if isinstance(payload, dict):
        return Agent(data=payload)
    return Agent.from_dict(payload)


def ensure_agent_dict(payload: Mapping[str, Any] | Agent) -> dict[str, Any]:
    """Return the backing dict for legacy ``dict``-typed callsites."""
    if isinstance(payload, Agent):
        return payload.data
    if isinstance(payload, dict):
        return payload
    return dict(payload)
