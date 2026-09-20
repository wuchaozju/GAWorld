"""Dataclass + on-disk format for :class:`Skill`.

Disk format is a single Markdown file with a YAML frontmatter header,
e.g.::

    ---
    name: 写一段单元测试
    description: 给一段 Python 函数补 pytest 风格的边界用例
    triggers: [pytest, 单测, 边界]
    ---

    1. 先识别函数的输入域...
    2. 至少覆盖两个边界值...

A skill's identifier (``skill_id``) is the file's basename without the
``.md`` suffix; the registry guarantees uniqueness inside each source
(global or per-agent).
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

SkillSource = Literal["global", "private"]

# Strict slug regex — matches lowercase letters, digits, hyphen, underscore,
# plus CJK Unified Ideographs so Chinese-named skills survive the round-trip.
_SLUG_OK = re.compile(r"[^a-zA-Z0-9_\-一-鿿]+")

# Order frontmatter keys are written in — deterministic output makes
# round-trip tests and diffs much cleaner.
_FRONTMATTER_KEYS: tuple[str, ...] = (
    "name",
    "description",
    "triggers",
    "source",
    "owner_agent_id",
    "origin",
    "created_day",
)


@dataclass
class Skill:
    """A reusable capability an agent can hold and apply.

    Attributes
    ----------
    skill_id:
        Stable identifier; usually the filename basename.
    name:
        Short human-readable title shown in prompts.
    description:
        One-line summary used both for trigger matching and the agent's
        prompt-time skill list.
    body:
        Free-form Markdown body — the "how to use this skill" detail
        passed into work-adapter prompts.
    triggers:
        Keyword hints. The registry uses these (plus ``description``
        and ``name``) for cheap substring matching against
        action/activity text.
    source:
        ``"global"`` for hand-authored library skills,
        ``"private"`` for agent-summarised skills.
    owner_agent_id:
        The agent that owns a private skill (None for global skills).
    origin:
        Optional provenance string (e.g. ``"consolidation"``,
        ``"seed"``) — kept for debugging and analysis.
    created_day:
        Simulation day the skill was created, when known.
    """

    skill_id: str
    name: str
    description: str = ""
    body: str = ""
    triggers: list[str] = field(default_factory=list)
    source: SkillSource = "global"
    owner_agent_id: int | None = None
    origin: str = ""
    created_day: int | None = None

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> Skill:
        return cls(
            skill_id=str(payload.get("skill_id", "")),
            name=str(payload.get("name", "")),
            description=str(payload.get("description", "")),
            body=str(payload.get("body", "")),
            triggers=[str(t) for t in (payload.get("triggers") or []) if str(t).strip()],
            source=payload.get("source", "global"),
            owner_agent_id=(
                int(payload["owner_agent_id"]) if payload.get("owner_agent_id") is not None else None
            ),
            origin=str(payload.get("origin", "")),
            created_day=(int(payload["created_day"]) if payload.get("created_day") is not None else None),
        )

    def matches(self, text: str) -> bool:
        """Cheap relevance check: does ``text`` mention any trigger/name?"""

        if not text:
            return False
        haystack = text.lower()
        needles: list[str] = [self.name, *self.triggers]
        for needle in needles:
            n = (needle or "").strip().lower()
            if n and n in haystack:
                return True
        return False


# ---------------------------------------------------------------------------
# Slug + frontmatter helpers
# ---------------------------------------------------------------------------


def slugify_skill_id(name: str, fallback: str = "skill") -> str:
    """Turn a human-readable name into a filesystem-safe skill_id."""

    base = (name or "").strip()
    if not base:
        return fallback
    # collapse runs of disallowed chars to a single hyphen
    slug = _SLUG_OK.sub("-", base).strip("-_")
    return slug or fallback


def _format_yaml_scalar(value: Any) -> str:
    """Minimal YAML scalar encoder.

    We deliberately do **not** depend on PyYAML — frontmatter here is
    flat and the values we write are bounded. Anything fancier than a
    list-of-strings or string scalar lands as a JSON literal.
    """
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        items = [_format_yaml_scalar(v) for v in value]
        return "[" + ", ".join(items) + "]"
    text = str(value)
    needs_quotes = any(ch in text for ch in ":#[]{},&*!|>'\"%@`\n") or text.strip() != text
    if needs_quotes:
        escaped = text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
        return f'"{escaped}"'
    return text


def _parse_yaml_scalar(text: str) -> Any:
    """Tiny YAML scalar parser. Mirrors :func:`_format_yaml_scalar`."""

    s = text.strip()
    if not s or s.lower() == "null":
        return None
    if s.lower() == "true":
        return True
    if s.lower() == "false":
        return False
    # quoted string
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        inner = s[1:-1]
        return inner.replace("\\n", "\n").replace('\\"', '"').replace("\\\\", "\\")
    # inline list: [a, b, c] or [a, "b c"]
    if s.startswith("[") and s.endswith("]"):
        inner = s[1:-1].strip()
        if not inner:
            return []
        parts: list[str] = []
        buf: list[str] = []
        depth_quote: str | None = None
        for ch in inner:
            if depth_quote:
                buf.append(ch)
                if ch == depth_quote:
                    depth_quote = None
                continue
            if ch in ('"', "'"):
                depth_quote = ch
                buf.append(ch)
                continue
            if ch == ",":
                parts.append("".join(buf).strip())
                buf = []
                continue
            buf.append(ch)
        if buf:
            parts.append("".join(buf).strip())
        return [_parse_yaml_scalar(p) for p in parts if p]
    # try int, then float, then bare string
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        pass
    return s


_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.S)


def parse_skill_markdown(skill_id: str, text: str) -> Skill:
    """Parse a Skill markdown file (frontmatter + body)."""

    if not isinstance(text, str):
        text = ""
    match = _FRONTMATTER_RE.match(text.lstrip("﻿"))
    if not match:
        # No frontmatter — fall back to using the first line as name and
        # the rest as body. Still produces a usable Skill, which is what
        # we want for hand-curated stubs.
        first_line, _, body = text.partition("\n")
        return Skill(
            skill_id=skill_id,
            name=first_line.strip() or skill_id,
            description="",
            body=body.strip(),
            triggers=[],
            source="global",
        )

    raw_frontmatter, body = match.group(1), match.group(2)
    fields: dict[str, Any] = {}
    for line in raw_frontmatter.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        fields[key.strip()] = _parse_yaml_scalar(value)

    triggers = fields.get("triggers", [])
    if isinstance(triggers, str):
        triggers = [t.strip() for t in triggers.split(",") if t.strip()]
    if not isinstance(triggers, list):
        triggers = []

    return Skill(
        skill_id=skill_id,
        name=str(fields.get("name") or skill_id),
        description=str(fields.get("description") or ""),
        body=body.strip(),
        triggers=[str(t) for t in triggers if str(t).strip()],
        source=fields.get("source") or "global",  # type: ignore[arg-type]
        owner_agent_id=(int(fields["owner_agent_id"]) if fields.get("owner_agent_id") is not None else None),
        origin=str(fields.get("origin") or ""),
        created_day=(int(fields["created_day"]) if fields.get("created_day") is not None else None),
    )


def dump_skill_markdown(skill: Skill) -> str:
    """Serialise a :class:`Skill` to ``---``-framed markdown."""

    payload: dict[str, Any] = {
        "name": skill.name,
        "description": skill.description,
        "triggers": skill.triggers,
        "source": skill.source,
        "owner_agent_id": skill.owner_agent_id,
        "origin": skill.origin,
        "created_day": skill.created_day,
    }
    lines = ["---"]
    for key in _FRONTMATTER_KEYS:
        value = payload.get(key)
        # Drop empty optional fields so files stay terse.
        if value is None:
            continue
        if isinstance(value, str) and not value:
            continue
        if isinstance(value, list) and not value:
            continue
        lines.append(f"{key}: {_format_yaml_scalar(value)}")
    lines.append("---")
    body = (skill.body or "").rstrip()
    return "\n".join(lines) + ("\n\n" + body if body else "") + "\n"


__all__ = [
    "Skill",
    "SkillSource",
    "dump_skill_markdown",
    "parse_skill_markdown",
    "slugify_skill_id",
]
