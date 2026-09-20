"""GroupPlugin — kernel wiring for the cohort tier.

Per ``AGENTS.md`` a new subsystem is a ``gaworld.kernel.Plugin``, not inline
logic in ``generative_city_sim.py``. This plugin is deliberately *observational*
for now: it partitions the running population into cohorts and publishes cohort
statistics to the recorder each day, without altering any agent's behaviour.

That split is intentional. The cohort tier's own day loop lives in
``gaworld.group.driver`` and runs as a parallel driver, because group mode is a
different *mode* rather than a behaviour tweak — it replaces the tick loop
instead of hooking into it. Wiring a mode switch into ``run_simulation`` before
the cohort kernel has been validated (design doc Phase 3, the L0/L2/L4 gate)
would put an unvalidated approximation on the default path. So:

* **this plugin**, enabled in an individual run, gives you cohort telemetry —
  useful on its own for seeing how a population clusters and drifts;
* **the driver**, invoked via ``python -m gaworld.group``, runs actual group
  mode;
* the ``CONFIG["simulation_mode"]`` switch lands once Phase 3 has measured what
  the approximation costs.
"""

from __future__ import annotations

from typing import Any

from gaworld.kernel import Plugin


class GroupPlugin(Plugin):
    """Publishes cohort structure and drift for a running individual simulation."""

    id = "group"

    def setup(self, ctx: Any) -> None:
        ctx.bus.on("on_simulation_start", self._on_simulation_start)
        ctx.bus.on("on_day_end", self._on_day_end)

    # -- config -----------------------------------------------------------

    def _config(self, ctx: Any) -> dict[str, Any]:
        block = ctx.config.get(self.id, {}) if isinstance(ctx.config, dict) else {}
        return block if isinstance(block, dict) else {}

    def _enabled(self, ctx: Any) -> bool:
        return bool(self._config(ctx).get("enabled", False))

    # -- handlers ---------------------------------------------------------

    def _on_simulation_start(self, ctx: Any = None, **_kwargs: Any) -> None:
        if ctx is None or not self._enabled(ctx):
            return
        from gaworld.group.cohort import partition_cohorts

        cfg = self._config(ctx)
        agents = list(getattr(ctx, "agents", []) or [])
        if not agents:
            return
        cohorts = partition_cohorts(
            agents,
            axes=cfg.get("cohort_axes"),
            min_size=int(cfg.get("min_cohort_size", 4)),
        )
        ctx.plugin_state(self.id)["cohorts"] = cohorts
        ctx.recorder.record(
            "group.partition",
            {
                "population": len(agents),
                "cohorts": [c.to_dict() for c in cohorts],
            },
        )

    def _on_day_end(self, ctx: Any = None, **_kwargs: Any) -> None:
        if ctx is None or not self._enabled(ctx):
            return
        from gaworld.group.cohort import refresh_cohort_statistics

        cohorts = ctx.plugin_state(self.id).get("cohorts") or []
        if not cohorts:
            return
        agents_by_id = {int(a["id"]): a for a in (getattr(ctx, "agents", []) or [])}
        for cohort in cohorts:
            refresh_cohort_statistics(cohort, agents_by_id)
        ctx.recorder.record(
            "group.cohort_stats",
            {
                "cohorts": [
                    {
                        "id": c.id,
                        "size": c.size,
                        "centroid": c.centroid,
                        "dispersion": c.dispersion,
                    }
                    for c in cohorts
                ]
            },
        )


__all__ = ["GroupPlugin"]
