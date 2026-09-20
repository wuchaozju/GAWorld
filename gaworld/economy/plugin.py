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
