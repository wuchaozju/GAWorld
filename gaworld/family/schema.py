"""Family data model and config resolution.

Two dataclasses carry everything downstream needs:

* :class:`Member` — one person in an agent's household or close kin. It is
  either another in-sim agent (``kind="agent"``) or an off-screen person
  (``kind="ghost"``). The ``key`` is exactly the key used in the agent's
  ``relationships`` dict, so ties, narrative and contagion all address the
  same record.
* :class:`Household` — a co-residence unit. Agents in ``agent_ids`` share a
  ``home`` location; ``ghost_members`` are the off-screen people who live
  there too (spouse, children, an elderly parent).

Everything is plain data (``to_dict`` round-trips) so households can be
recorded to JSONL and reloaded without importing this module.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: Marital statuses. ``never`` covers both "never married" and, for
#: cohabiting agents, "not married but living with a partner" — the
#: distinction is carried by the household type, not by this field.
MARITAL_STATUSES = ("never", "married", "divorced", "widowed")

#: Household types, in the order the assigner tries to build them.
HOUSEHOLD_TYPES = (
    "single",         # 独居
    "shared",         # 合租
    "with_parents",   # 与父母同住
    "cohabit",        # 未婚同居
    "couple",         # 夫妻二人（无子女或子女已独立）
    "nuclear",        # 核心家庭（夫妻 + 未成年/在读子女）
    "single_parent",  # 单亲家庭
    "multigen",       # 三代同堂
)

HOUSEHOLD_TYPE_ZH = {
    "single": "独居",
    "shared": "合租",
    "with_parents": "与父母同住",
    "cohabit": "未婚同居",
    "couple": "夫妻二人",
    "nuclear": "核心家庭",
    "single_parent": "单亲家庭",
    "multigen": "三代同堂",
}

MARITAL_STATUS_ZH = {
    "never": "未婚",
    "married": "已婚",
    "divorced": "离异",
    "widowed": "丧偶",
}

ROLE_ZH = {
    "spouse": "配偶",
    "partner": "伴侣",
    "child": "子女",
    "parent": "父母",
    "mother": "母亲",
    "father": "父亲",
    "sibling": "兄弟姐妹",
    "grandparent": "祖辈",
    "ex": "前任",
    "roommate": "室友",
}


@dataclass
class Member:
    """One person related to an agent by family (or co-residence)."""

    key: str
    name: str
    role: str
    kind: str = "ghost"          # "agent" | "ghost"
    age: int = 0
    gender: str = ""
    coresident: bool = True
    agent_id: int | None = None
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "name": self.name,
            "role": self.role,
            "kind": self.kind,
            "age": int(self.age),
            "gender": self.gender,
            "coresident": bool(self.coresident),
            "agent_id": self.agent_id,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Member:
        return cls(
            key=str(data.get("key", "")),
            name=str(data.get("name", "")),
            role=str(data.get("role", "")),
            kind=str(data.get("kind", "ghost")),
            age=int(data.get("age", 0) or 0),
            gender=str(data.get("gender", "")),
            coresident=bool(data.get("coresident", True)),
            agent_id=data.get("agent_id"),
            note=str(data.get("note", "")),
        )


@dataclass
class Household:
    """A co-residence unit shared by 0..n in-sim agents and 0..n ghosts."""

    id: str
    type: str
    agent_ids: list[int] = field(default_factory=list)
    ghost_members: list[Member] = field(default_factory=list)
    district: str = ""
    home: str = ""

    def size(self) -> int:
        return len(self.agent_ids) + sum(1 for m in self.ghost_members if m.coresident)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "type_zh": HOUSEHOLD_TYPE_ZH.get(self.type, self.type),
            "agent_ids": list(self.agent_ids),
            "ghost_members": [m.to_dict() for m in self.ghost_members],
            "district": self.district,
            "home": self.home,
            "size": self.size(),
        }


# ---------------------------------------------------------------------------
# Config resolution
# ---------------------------------------------------------------------------


def family_config(config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return ``CONFIG["family"]`` merged over the packaged defaults.

    Missing sub-dicts fall back to the defaults key-by-key, so a caller can
    override a single knob (``{"family": {"finance": {"pooling_rate": 0.3}}}``)
    without restating the whole block.
    """
    from gaworld.settings.family import family_settings

    defaults = family_settings()["family"]
    user = {}
    if isinstance(config, dict):
        candidate = config.get("family")
        if isinstance(candidate, dict):
            user = candidate
    merged = dict(defaults)
    for key, value in user.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            sub = dict(merged[key])
            sub.update(value)
            merged[key] = sub
        else:
            merged[key] = value
    return merged


def band_lookup(bands: list[dict[str, Any]], age: int, default: Any = None) -> Any:
    """Find the first band whose ``age`` range contains ``age``.

    Bands are ``{"age": [lo, hi], ...}``; the whole dict is returned so
    callers can pull whichever payload key they need.
    """
    for band in bands or []:
        rng = band.get("age") or []
        if len(rng) != 2:
            continue
        try:
            lo, hi = int(rng[0]), int(rng[1])
        except (TypeError, ValueError):
            continue
        if lo <= int(age) <= hi:
            return band
    return default
