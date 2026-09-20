"""RealWorkRouter — decide whether to dispatch real work for a tick.

The router has two paths:
* **Path B (Market)**: with some probability, browse the JobMarket
  and possibly accept the best matching open job, converting it to a
  WorkBrief. Tried first because market jobs come with concrete
  briefs and rewards.
* **Path A (Self-driven)**: if Path B did not fire, infer a
  deliverable from ``activity + chosen_action + capabilities`` and
  submit a self-initiated WorkBrief.

The router itself does **not** call the LLM — adapters do that
inside the worker pool, asynchronously.
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Optional

from gaworld.logging_setup import get_logger
from gaworld.settings import CONFIG
from gaworld.skills.prompt_helpers import relevant_skills_for_text, render_agent_skills
from gaworld.skills.registry import SkillRegistry, get_default_registry
from gaworld.skills.schemas import Skill
from gaworld.work.market import (
    JobAlreadyTaken,
    JobMarket,
    accept_probability,
    browse_probability,
    deterministic_random,
)
from gaworld.work.queue import WorkQueue
from gaworld.work.schemas import (
    DELIVERABLES,
    AgentCapabilities,
    MarketJob,
    WorkBrief,
)

_LOG = get_logger("gaworld.work.router")


# Activity gate keywords (mirrors generative_city_sim.py:2585).
_WORK_ACTIVITY_KEYWORDS = (
    "工作", "上班", "加班", "上课", "实验", "课题", "创作", "写作", "备课", "研究",
)

# Adapter selection by deliverable.
_DELIVERABLE_TO_ADAPTER = {
    "html_landing": "web_design",
    "poster_svg": "web_design",
    "py_script": "code",
    "py_test": "code",
    "md_article": "content",
    "lesson_plan": "teaching",
    "research_note": "teaching",
}

# Estimated minutes per deliverable type (used for downstream reasoning).
_ESTIMATED_MINUTES = {
    "html_landing": 30,
    "poster_svg": 30,
    "py_script": 15,
    "py_test": 15,
    "md_article": 20,
    "lesson_plan": 25,
    "research_note": 25,
}


def _activity_is_work(activity: str) -> bool:
    if not activity:
        return False
    return any(k in activity for k in _WORK_ACTIVITY_KEYWORDS)


def _deliverable_from_action(act: str, capabilities: AgentCapabilities) -> Optional[str]:
    """Pick a deliverable from the chosen action text + capabilities."""

    a = (act or "").lower()
    candidates = list(capabilities.deliverables) or []
    if not candidates:
        return None

    rules: list[tuple[tuple[str, ...], str]] = [
        (("设计", "页面", "海报", "ui", "排版", "视觉"), "html_landing"),
        (("海报", "插画"), "poster_svg"),
        (("代码", "脚本", "调试", "算法", "编程", "实现"), "py_script"),
        (("文章", "推文", "选题", "案例", "笔记", "推送", "公众号", "内容"), "md_article"),
        (("备课", "讲义", "教案"), "lesson_plan"),
        (("综述", "文献", "研究"), "research_note"),
    ]
    for needles, deliverable in rules:
        if deliverable not in candidates:
            continue
        if any(n in a for n in needles):
            return deliverable
    # Fallback: first capability.
    return candidates[0]


def _build_brief_text(
    agent: dict[str, Any],
    capabilities: AgentCapabilities,
    *,
    title: str,
    description: str,
    chosen_action: str,
    relevant_skills: list[Skill] | None = None,
) -> str:
    """Compose a labelled brief that adapters can parse.

    The labels (【任务】 etc.) are read by the adapter helpers to fish
    out fields without a separate schema. When ``relevant_skills`` is
    non-empty, an extra 【可用技能】 block is appended; adapters that
    inline ``brief_text`` into LLM prompts will pick this up for free.
    """

    skills_kw = "、".join(capabilities.skills[:4]) or "-"
    role_label = {
        "ui_designer": "设计师",
        "algorithm_engineer": "工程师",
        "content_creator": "创作者",
        "teacher_researcher": "研究者",
    }.get(capabilities.job_label, "执行者")
    base = (
        f"【{role_label}】{agent.get('name', '')}\n"
        f"【职业】{agent.get('job', '')}\n"
        f"【风格关键词】{skills_kw}\n"
        f"【调性】{capabilities.notes[:80]}\n"
        f"【任务】{title}\n"
        f"【动作】{chosen_action}\n"
        f"【简报】{description}"
    )
    if relevant_skills:
        skill_text = render_agent_skills(relevant_skills, max_skills=3, include_body=True)
        if skill_text:
            base += f"\n【可用技能】\n{skill_text}"
    return base


def _skills_for_action(
    agent: dict[str, Any],
    *,
    registry: SkillRegistry | None,
    action_text: str,
    enabled: bool,
) -> list[Skill]:
    """Pick the top skills relevant to a chosen action.

    Wrapped in a try/except so a misconfigured skill directory never
    blocks work dispatch — the router falls back to behaving as before.
    """
    if not enabled or registry is None:
        return []
    try:
        all_skills = registry.list_for_agent(agent)
    except Exception:  # noqa: BLE001
        return []
    if not all_skills:
        return []
    return relevant_skills_for_text(all_skills, action_text, limit=3)


class RealWorkRouter:
    """Decides per-tick whether to dispatch real work."""

    def __init__(
        self,
        *,
        queue: WorkQueue,
        market: Optional[JobMarket],
        capabilities: dict[int, AgentCapabilities],
        config: dict[str, Any],
        skill_registry: Optional[SkillRegistry] = None,
    ) -> None:
        self.queue = queue
        self.market = market
        self.capabilities = capabilities
        self.config = config or {}
        self._market_cfg = self.config.get("market", {}) if isinstance(self.config, dict) else {}
        skills_cfg = CONFIG.get("skills", {}) if isinstance(CONFIG, dict) else {}
        self._skills_enabled = bool(skills_cfg.get("inject_into_work_brief", True))
        # Resolve lazily so tests that don't touch skills pay nothing.
        self._skill_registry = skill_registry
        if self._skills_enabled and self._skill_registry is None:
            try:
                self._skill_registry = get_default_registry()
            except Exception:  # noqa: BLE001
                self._skill_registry = None

    # ------------------------------------------------------------------
    def maybe_dispatch(
        self,
        agent: dict[str, Any],
        *,
        activity: str,
        chosen_action: str,
        sim_day: int,
        sim_time: str,
        tick_index: int = 0,
    ) -> Optional[str]:
        """Try Path B then Path A; return outcome text or None."""

        if not self.config.get("enabled"):
            return None
        if not _activity_is_work(activity):
            return None

        agent_id = int(agent.get("id", 0) or 0)
        if not agent_id:
            return None

        capabilities = self.capabilities.get(agent_id)
        if capabilities is None or not capabilities.deliverables:
            return None

        # Throttle: one in-flight task at a time per agent.
        if self.queue.has_unfinished_for(agent_id):
            return None

        # Path B — browse market.
        if self.market is not None and self._market_cfg.get("enabled"):
            outcome = self._maybe_market_dispatch(
                agent, capabilities,
                sim_day=sim_day, sim_time=sim_time, tick_index=tick_index,
            )
            if outcome is not None:
                return outcome

        # Path A — self-driven.
        return self._self_driven_dispatch(
            agent, capabilities,
            activity=activity, chosen_action=chosen_action,
            sim_day=sim_day, sim_time=sim_time,
        )

    # ------------------------------------------------------------------
    # Path B
    # ------------------------------------------------------------------
    def _maybe_market_dispatch(
        self,
        agent: dict[str, Any],
        capabilities: AgentCapabilities,
        *,
        sim_day: int,
        sim_time: str,
        tick_index: int,
    ) -> Optional[str]:
        if self.market is None:
            return None
        agent_id = int(agent.get("id", 0))
        max_per_day = int(self._market_cfg.get("max_taken_per_agent_per_day", 2))
        if self.market.daily_take_for(sim_day, agent_id) >= max_per_day:
            return None

        rng = deterministic_random(agent_id, sim_day, salt=f"market|{tick_index}|{sim_time}")
        base_p = float(self._market_cfg.get("browse_probability_base", 0.15))
        state = agent.get("state", {}) if isinstance(agent.get("state"), dict) else {}
        p = browse_probability(state, base=base_p)
        if rng.random() > p:
            return None

        top_k = int(self._market_cfg.get("browse_top_k", 5))
        listings = self.market.browse(capabilities, sim_day=sim_day, top_k=top_k)
        if not listings:
            return None

        top_job, top_score = listings[0]
        accept_p = accept_probability(top_score, state)
        if rng.random() > accept_p:
            _LOG.debug("agent %s browsed %d jobs but did not accept", agent_id, len(listings))
            return None

        try:
            taken = self.market.take(
                top_job.job_id, agent_id,
                sim_time=sim_time, sim_day=sim_day,
                max_taken_per_agent_per_day=max_per_day,
            )
        except JobAlreadyTaken:
            return None

        brief = self._brief_from_market_job(agent, capabilities, taken, sim_day, sim_time)
        if brief is None:
            self.market.release(top_job.job_id)
            return None
        self.queue.submit(brief)
        self.market.link_task(taken.job_id, brief.task_id)
        return f"在工作平台接单：【{taken.title}】，task={brief.task_id[:10]}"

    def _brief_from_market_job(
        self,
        agent: dict[str, Any],
        capabilities: AgentCapabilities,
        job: MarketJob,
        sim_day: int,
        sim_time: str,
    ) -> Optional[WorkBrief]:
        if job.deliverable not in DELIVERABLES:
            return None
        adapter = _DELIVERABLE_TO_ADAPTER.get(job.deliverable)
        if adapter is None:
            return None
        action_hint = f"{job.title} {job.description}"
        relevant = _skills_for_action(
            agent,
            registry=self._skill_registry,
            action_text=action_hint,
            enabled=self._skills_enabled,
        )
        brief_text = _build_brief_text(
            agent, capabilities,
            title=job.title,
            description=job.description,
            chosen_action="接受平台订单并交付",
            relevant_skills=relevant,
        )
        return WorkBrief(
            task_id=f"wt_{uuid.uuid4().hex[:10]}",
            agent_id=int(agent.get("id", 0)),
            sim_day=sim_day,
            sim_time=sim_time,
            activity="工作",
            chosen_action=f"承接订单：{job.title}",
            deliverable=job.deliverable,
            adapter=adapter,
            brief_text=brief_text,
            estimated_minutes=_ESTIMATED_MINUTES.get(job.deliverable, 25),
            submitted_at=time.time(),
            market_job_id=job.job_id,
        )

    # ------------------------------------------------------------------
    # Path A
    # ------------------------------------------------------------------
    def _self_driven_dispatch(
        self,
        agent: dict[str, Any],
        capabilities: AgentCapabilities,
        *,
        activity: str,
        chosen_action: str,
        sim_day: int,
        sim_time: str,
    ) -> Optional[str]:
        deliverable = _deliverable_from_action(chosen_action, capabilities)
        if deliverable is None:
            return None
        adapter = _DELIVERABLE_TO_ADAPTER.get(deliverable)
        if adapter is None:
            return None
        title = chosen_action[:30] or activity
        description = (
            f"基于角色背景与当前活动【{activity}】自主推进，"
            f"输出一个 {deliverable} 类型的产物。"
        )
        relevant = _skills_for_action(
            agent,
            registry=self._skill_registry,
            action_text=f"{chosen_action} {activity}",
            enabled=self._skills_enabled,
        )
        brief_text = _build_brief_text(
            agent, capabilities,
            title=title,
            description=description,
            chosen_action=chosen_action,
            relevant_skills=relevant,
        )
        brief = WorkBrief(
            task_id=f"wt_{uuid.uuid4().hex[:10]}",
            agent_id=int(agent.get("id", 0)),
            sim_day=sim_day,
            sim_time=sim_time,
            activity=activity,
            chosen_action=chosen_action,
            deliverable=deliverable,
            adapter=adapter,
            brief_text=brief_text,
            estimated_minutes=_ESTIMATED_MINUTES.get(deliverable, 25),
            submitted_at=time.time(),
            market_job_id=None,
        )
        self.queue.submit(brief)
        return f"开始着手【{title}】，已投递任务 {brief.task_id[:10]}"


__all__ = ["RealWorkRouter"]
