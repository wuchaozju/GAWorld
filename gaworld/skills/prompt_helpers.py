"""Render Skills into prompt-friendly text fragments.

Kept separate from :mod:`gaworld.skills.registry` so cognition / work
modules can import just the formatter without pulling in the disk
scanner. The renderer is intentionally compact — long bodies blow up
prompts cheaply, so callers get short summaries by default and only
the full body when asked.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from gaworld.skills.schemas import Skill

_MAX_BODY_CHARS = 400


def render_agent_skills(
    skills: Sequence[Skill],
    *,
    max_skills: int = 6,
    include_body: bool = False,
) -> str:
    """Format a list of Skills for inclusion in an LLM prompt.

    Returns an empty string when no skills are available — callers
    should branch on the string rather than always concatenating it,
    so prompts stay clean when an agent has no skills.
    """
    items = list(skills)[:max_skills]
    if not items:
        return ""
    lines: list[str] = []
    for skill in items:
        head = f"- {skill.name}"
        if skill.description:
            head += f"：{skill.description}"
        lines.append(head)
        if include_body and skill.body:
            body = skill.body.strip().replace("\n", " ")
            if len(body) > _MAX_BODY_CHARS:
                body = body[: _MAX_BODY_CHARS - 1] + "…"
            lines.append(f"  · {body}")
    return "\n".join(lines)


def relevant_skills_for_text(
    skills: Iterable[Skill],
    text: str,
    *,
    limit: int = 3,
) -> list[Skill]:
    """Pick at most ``limit`` skills whose triggers/name match ``text``.

    Used by the work router and adapter helpers to focus the brief on
    the handful of skills that actually apply to the current action.
    """
    if not text:
        return []
    matches: list[Skill] = []
    for skill in skills:
        if skill.matches(text):
            matches.append(skill)
            if len(matches) >= limit:
                break
    return matches


__all__ = ["relevant_skills_for_text", "render_agent_skills"]
