"""SkillsPlugin — the reusable Skill library as a kernel plugin (K3c).

Replaces two inline integrations:

- ``perception.sections`` (collect): render the agent's attached/private
  skills as the "你已经掌握的小技能" block. The section lands at the same
  position inside the perception prompt the old ``_agent_skill_block``
  suffix did (the perceive stage passes collected sections into
  ``perception(extra_sections=...)``), so prompt structure is unchanged.
  ``CONFIG["skills"]["inject_into_cognition"]`` is honored per call, as
  before.
- ``memory.consolidate`` (observe): distil a private Skill from recent
  episodes on the ``CONFIG["memory"]["skill_consolidation"]`` cadence —
  the branch previously hard-wired inside
  :func:`gaworld.memory.lifecycle.run_daily_memory_lifecycle`.
"""

from __future__ import annotations

from gaworld.kernel import Plugin
from gaworld.logging_setup import get_logger

_LOG = get_logger("gaworld.skills.plugin")


def _due(day, every_days) -> bool:
    """Same cadence semantics as memory.lifecycle._div_due."""
    if not isinstance(day, int):
        try:
            day = int(day)
        except (TypeError, ValueError):
            return False
    step = max(1, int(every_days or 1))
    return day > 0 and day % step == 0


class SkillsPlugin(Plugin):
    id = "skills"

    def setup(self, ctx):
        # Domain imports stay out of kernel assembly; resolved once here.
        from gaworld.skills.consolidation import run_skill_consolidation
        from gaworld.skills.prompt_helpers import render_agent_skills
        from gaworld.skills.registry import get_default_registry

        self._run_consolidation = run_skill_consolidation
        self._render = render_agent_skills
        self._get_registry = get_default_registry
        # Config flags are re-checked per call (matching the old inline
        # behavior), so both hooks register unconditionally.
        ctx.bus.on("perception.sections", self._skill_section)
        ctx.bus.on("memory.consolidate", self._consolidate)

    # -- hooks ---------------------------------------------------------------

    def _skill_section(self, hook_ctx):
        sim = hook_ctx["sim"]
        cfg = sim.config.get("skills", {}) or {}
        if not cfg.get("inject_into_cognition", True):
            return None
        agent = hook_ctx["agent"]
        try:
            skills = self._get_registry().list_for_agent(agent)
        except Exception:  # noqa: BLE001 — never let skill rendering break perception
            return None
        if not skills:
            return None
        rendered = self._render(skills, max_skills=int(cfg.get("max_per_prompt", 4)))
        if not rendered:
            return None
        return f"你已经掌握的小技能：\n{rendered}"

    def _consolidate(self, hook_ctx):
        sim = hook_ctx["sim"]
        skill_cfg = (sim.config.get("memory", {}) or {}).get("skill_consolidation", {}) or {}
        if not skill_cfg.get("enabled", False):
            return
        day = hook_ctx.get("day")
        if not _due(day, skill_cfg.get("every_days", 5)):
            return
        agent = hook_ctx["agent"]
        try:
            self._run_consolidation(agent, llm=sim.llm, today=day)
        except Exception as exc:  # noqa: BLE001 — parity with the old lifecycle guard
            _LOG.warning(
                "skill consolidation failed for agent %s: %s", agent.get("id"), exc
            )
