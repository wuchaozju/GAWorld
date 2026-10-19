"""Find the skills a piece of work should use.

Two steps, split by cost:

* :func:`find_local_skills` — run by the router while it builds a brief,
  inside the tick. Ranks the agent's own skills *and* the whole global
  library against the task (title, brief, action, deliverable, the job's
  required skills). Disk only, deterministic.
* :func:`make_market_hook` — run by the worker on its own thread just
  before the adapter, so a slow network never holds up a tick. When the
  local search left free slots it asks the online skill market and
  appends what it finds to the brief.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Sequence
from typing import Any

from gaworld.logging_setup import get_logger
from gaworld.skills.market import SkillMarket
from gaworld.skills.prompt_helpers import relevant_skills_for_text, render_agent_skills
from gaworld.skills.registry import SkillRegistry
from gaworld.skills.schemas import Skill
from gaworld.skills.search import search_skills
from gaworld.work.schemas import WorkBrief

_LOG = get_logger("gaworld.work.skill_lookup")

#: How many skills one brief carries.
SKILLS_PER_BRIEF = 3

SKILL_BLOCK_HEADER = "【可用技能】"

# Words that describe each deliverable, matched against a skill's
# name/description/triggers.
DELIVERABLE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "html_landing": ("网页", "页面", "前端", "设计", "landing", "html"),
    "poster_svg": ("海报", "排版", "设计", "poster", "svg"),
    "py_script": ("代码", "脚本", "编程", "python"),
    "py_test": ("测试", "单测", "pytest"),
    "md_article": ("文章", "写作", "文案", "article", "writing"),
    "lesson_plan": ("教案", "备课", "教学", "lesson"),
    "research_note": ("研究", "文献", "综述", "research"),
}

# The market's search is English-semantic; a Chinese task title brings
# back noise, so the query is the deliverable in English.
DELIVERABLE_MARKET_QUERIES: dict[str, str] = {
    "html_landing": "landing page design",
    "poster_svg": "poster design",
    "py_script": "python best practices",
    "py_test": "pytest unit testing",
    "md_article": "article writing",
    "lesson_plan": "lesson plan",
    "research_note": "literature review research",
}


def find_local_skills(
    agent: dict[str, Any],
    registry: SkillRegistry | None,
    *,
    text: str,
    deliverable: str,
    extra_keywords: Sequence[str] = (),
    auto_search: bool = True,
) -> list[Skill]:
    """Best skills for a task from the agent's skills + the global library.

    With ``auto_search`` off this is the old behaviour: only the agent's
    own skills, first trigger matches against ``text``. A broken skill
    directory never blocks dispatch — it just yields no skills.
    """
    if registry is None:
        return []
    try:
        if not auto_search:
            return relevant_skills_for_text(registry.list_for_agent(agent), text, limit=SKILLS_PER_BRIEF)
        keywords = [*DELIVERABLE_KEYWORDS.get(deliverable, ()), *extra_keywords]
        return search_skills(registry.list_searchable(agent), text, keywords=keywords, limit=SKILLS_PER_BRIEF)
    except Exception:
        _LOG.warning("local skill search failed for agent %s", agent.get("id"), exc_info=True)
        return []


def append_skills(brief_text: str, skills: Sequence[Skill]) -> str:
    """``brief_text`` with ``skills`` added under the skills block."""
    text = render_agent_skills(skills, max_skills=len(skills), include_body=True)
    if not text:
        return brief_text
    if SKILL_BLOCK_HEADER not in brief_text:
        brief_text += f"\n{SKILL_BLOCK_HEADER}"
    return f"{brief_text}\n{text}"


def make_market_hook(
    market: SkillMarket,
    registry: SkillRegistry | None,
) -> Callable[[WorkBrief], WorkBrief]:
    """A worker brief hook that fills free skill slots from the market."""

    def hook(brief: WorkBrief) -> WorkBrief:
        missing = SKILLS_PER_BRIEF - len(brief.skill_ids)
        query = DELIVERABLE_MARKET_QUERIES.get(brief.deliverable)
        if missing <= 0 or not query:
            return brief
        try:
            found = market.find(query, limit=missing, exclude_ids=brief.skill_ids)
        except Exception:  # offline / market down: work on without
            _LOG.warning("skill market lookup failed for %s", brief.task_id, exc_info=True)
            return brief
        if not found:
            return brief
        if registry is not None:
            for skill in found:
                registry.register_global(skill)
        return dataclasses.replace(
            brief,
            brief_text=append_skills(brief.brief_text, found),
            skill_ids=[*brief.skill_ids, *(s.skill_id for s in found)],
        )

    return hook


__all__ = [
    "DELIVERABLE_KEYWORDS",
    "DELIVERABLE_MARKET_QUERIES",
    "SKILLS_PER_BRIEF",
    "SKILL_BLOCK_HEADER",
    "append_skills",
    "find_local_skills",
    "make_market_hook",
]
