"""EconomyPlugin — formalizes the economy's hook wiring (K3f).

The economy subsystem was already event-driven: since K1 its six lifecycle
handlers were declared as ``CONFIG["extensions"]["hooks"]`` entries in
``gaworld/settings/integrations.py``. This plugin replaces that config-level
declaration with first-class plugin assembly — same handlers, same events,
same self-gating (`economy.enabled` is checked inside each handler), and the
runtime still lives in ``extension_state["economy_module"]``.

Ordering parity notes: intervention's ``on_agent_post_step`` (priority 10)
and interests' ``on_day_end`` (priority 10) keep running before the
economy's priority-0 handlers, exactly as before the formalization.
"""

from __future__ import annotations

from gaworld.kernel import Plugin


class EconomyPlugin(Plugin):
    id = "economy"

    def setup(self, ctx):
        # Domain import stays out of kernel assembly; resolved once here.
        from gaworld.economy import finance

        ctx.bus.on("on_simulation_start", finance.on_simulation_start)
        ctx.bus.on("on_day_start", finance.on_day_start)
        ctx.bus.on("on_agent_pre_step", finance.on_agent_pre_step)
        ctx.bus.on("on_agent_post_step", finance.on_agent_post_step)
        ctx.bus.on("on_day_end", finance.on_day_end)
        ctx.bus.on("on_simulation_end", finance.on_simulation_end)
        # K3f+: the economy owns the money, so it is the economy that applies
        # event impacts that cost or earn money (see
        # docs/proposals/2026-11-15-event-impact-cascade.md).
        ctx.bus.on("event.impact.apply", self._apply_impact)

    def _apply_impact(self, hook_ctx):
        """Book an event impact that lands on money."""
        from gaworld.economy import finance

        impact = hook_ctx.get("impact")
        agent = hook_ctx.get("agent")
        if impact is None or not isinstance(agent, dict):
            return
        if getattr(impact, "domain", "") != "economy":
            return
        params = getattr(impact, "params", {}) or {}
        scale = float(hook_ctx.get("scale", 1.0) or 1.0)
        severity = float(hook_ctx.get("objective_severity", 1.0) or 1.0)
        kind = getattr(impact, "kind", "")
        context = {
            "config": getattr(hook_ctx.get("sim"), "config", {}),
            "day": hook_ctx.get("day"),
            "agents": [agent],
        }

        if kind == "expense":
            # Amounts are quoted at severity 1.0; a milder event costs less.
            amount = float(params.get("amount", 0.0) or 0.0) * severity * scale
            finance.charge_external_expense(
                agent, str(params.get("category", "event")), amount, context=context
            )
        elif kind == "bonus":
            amount = float(params.get("amount", 0.0) or 0.0) * severity * scale
            finance.credit_event_bonus(agent, str(params.get("category", "bonus")), amount, context=context)
        elif kind == "income_change":
            fraction = float(params.get("fraction", 0.0) or 0.0) * scale
            days = int(params.get("days", 1) or 1)
            finance.apply_event_income_change(agent, fraction, days, config=context["config"])
