"""DynamicBehaviorPlugin — the dynamic behaviour system as a plugin (K3i).

Owns the interrupt/thought *computation*: on the ``interrupts.compose``
filter it runs the dynamic engines (interrupt arbitration, spontaneity,
social chains, event cascades) and returns the transient-thought dict.

Contract notes:

- The engines always return a dict (``{}`` when nothing should change), so
  a ``None`` flowing out of the filter means *no producer ran* — the
  interrupts stage then falls back to the legacy spontaneity path, exactly
  matching the old ``dynamic_behavior.enabled`` if/else.
- The *application* of an interrupt result (activity change, mood delta,
  schedule insertion, P3 replanning) stays in the adjust_activity stage:
  the ``dynamic_result`` dict is the generic contract between any
  interrupt-producing plugin and the pipeline, not this plugin's private
  logic. After application the stage emits ``interrupt.applied`` for
  observers (e.g. spatial preferences).
"""

from __future__ import annotations

from gaworld.kernel import Plugin


class DynamicBehaviorPlugin(Plugin):
    id = "dynamic_behavior"

    def setup(self, ctx):
        # Domain import stays out of kernel assembly; resolved once here.
        from gaworld.behavior import dynamic as impl

        self._impl = impl
        if not bool((ctx.config.get("dynamic_behavior", {}) or {}).get("enabled", True)):
            return
        ctx.bus.on("interrupts.compose", self._compose)

    def _compose(self, value, hook_ctx):
        if value is not None:
            return None  # an upstream producer already made the thought
        sim = hook_ctx["sim"]
        agent = hook_ctx["agent"]
        step = hook_ctx.get("step") or {}
        return self._impl.dynamic_transient_thought(
            agent,
            hook_ctx.get("time_str"),
            step.get("scheduled_activity", ""),
            perception_text=step.get("_perception", ""),
            env_events=step.get("_env_events", []),
            policy_desc=step.get("policy_desc"),
            social_context=step.get("social_context", ""),
            inbox_messages=step.get("_inbox_messages", []),
            all_agents=sim.agents,
            agents_by_id=sim.agents_by_id,
            config=sim.config,
        )
