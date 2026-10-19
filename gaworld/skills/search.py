"""Rank skills against a task so work can find them on its own.

:func:`gaworld.skills.prompt_helpers.relevant_skills_for_text` takes the
first skills whose name/trigger shows up in a piece of text, out of the
handful an agent already holds. Work needs more than that: when a
resident takes on a job it should look through the whole library for the
skills that fit *this* job, best first. This module does the ranking;
it stays pure (no disk, no network) so the router can call it every tick.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from gaworld.skills.schemas import Skill


def _usable_keyword(word: str) -> bool:
    # Short ASCII words ("ui", "py") are substrings of too many unrelated
    # words; a CJK word of two characters is already specific.
    w = word.strip()
    if not w:
        return False
    return len(w) >= 3 or not w.isascii()


def score_skill(skill: Skill, text: str, keywords: Sequence[str] = ()) -> int:
    """How well ``skill`` fits a task described by ``text`` + ``keywords``.

    * name mentioned in the task: +3
    * each trigger mentioned in the task: +2
    * each task keyword found in the skill's name/description/triggers: +1
    """
    hay = (text or "").lower()
    score = 0
    name = (skill.name or "").strip().lower()
    if name and name in hay:
        score += 3
    for trigger in skill.triggers:
        t = (trigger or "").strip().lower()
        if t and t in hay:
            score += 2
    surface = " ".join([skill.name, skill.description, *skill.triggers]).lower()
    for word in keywords:
        if _usable_keyword(word) and word.strip().lower() in surface:
            score += 1
    return score


def search_skills(
    candidates: Iterable[Skill],
    text: str,
    *,
    keywords: Sequence[str] = (),
    limit: int = 3,
) -> list[Skill]:
    """Return up to ``limit`` candidates with a positive score, best first.

    Ties keep the candidates' order, so callers that list the agent's own
    skills first get those ahead of an equally good library skill.
    """
    scored = [(score_skill(s, text, keywords), i, s) for i, s in enumerate(candidates)]
    ranked = sorted((item for item in scored if item[0] > 0), key=lambda item: (-item[0], item[1]))
    return [s for _, _, s in ranked[: max(0, limit)]]


__all__ = ["score_skill", "search_skills"]
