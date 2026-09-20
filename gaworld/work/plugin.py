"""RealWorkPlugin — the real-work task system as a kernel plugin (K3h).

``RealWorkRuntime`` was already a self-contained runtime; this plugin owns
its lifecycle and its one cognition touchpoint:

- ``on_simulation_start`` (observe): create + start the runtime (returns
  ``None`` when ``real_work.enabled`` is off — every later hook no-ops).
- ``on_day_start`` (observe): job-market day tick (expiry / replenish).
- ``action.outcome`` (new filter): dispatch "work"-class actions to the
  worker pool and absorb finished artifacts, rewriting the step outcome —
  the logic previously inlined in the select_action stage.
- ``teardown``: stop the worker pool. (The inline code never stopped it;
  this is a deliberate small improvement, noted in the CHANGELOG.)
"""

from __future__ import annotations

from gaworld.kernel import Plugin
from gaworld.logging_setup import get_logger

_LOG = get_logger("gaworld.work.plugin")


class RealWorkPlugin(Plugin):
    id = "real_work"

    def setup(self, ctx):
        # Module refs (not bound functions) so tests can patch attributes.
        from gaworld.work import ingest as ingest_impl
        from gaworld.work import runtime as runtime_impl

        self._runtime_impl = runtime_impl
        self._ingest_impl = ingest_impl
        ctx.bus.on("on_simulation_start", self._start_runtime)
        ctx.bus.on("on_day_start", self._tick_day)
        ctx.bus.on("action.outcome", self._rewrite_outcome)

    def teardown(self, ctx):
        runtime = ctx.plugin_state(self.id).pop("runtime", None)
        if runtime is not None:
            try:
                runtime.stop()
            except Exception as exc:  # noqa: BLE001 — never block shutdown
                _LOG.warning("real-work runtime stop failed: %s", exc)

    # -- hooks ---------------------------------------------------------------

    def _runtime(self, sim):
        return sim.plugin_state(self.id).get("runtime")

    def _start_runtime(self, hook_ctx):
        sim = hook_ctx["sim"]
        runtime = self._runtime_impl.RealWorkRuntime.create(
            sim.config, hook_ctx.get("agents", []), llm_fn=sim.llm
        )
        if runtime is not None:
            runtime.start()
        sim.plugin_state(self.id)["runtime"] = runtime

    def _tick_day(self, hook_ctx):
        runtime = self._runtime(hook_ctx["sim"])
        if runtime is not None:
            runtime.tick_day(hook_ctx.get("day"))

    def _rewrite_outcome(self, outcome, hook_ctx):
        runtime = self._runtime(hook_ctx["sim"])
        if runtime is None:
            return None  # keep the incoming outcome
        agent = hook_ctx["agent"]
        rw_outcome = runtime.router.maybe_dispatch(
            agent,
            activity=hook_ctx.get("activity"),
            chosen_action=hook_ctx.get("action"),
            sim_day=hook_ctx.get("day"),
            sim_time=hook_ctx.get("time_str"),
        )
        if rw_outcome:
            outcome = rw_outcome
        rw_done = runtime.absorb_for(
            agent, sim_day=hook_ctx.get("day"), sim_time=hook_ctx.get("time_str")
        )
        if rw_done:
            outcome = f"{outcome}｜回收：{self._ingest_impl.summarise_for_outcome(rw_done)}"
        return outcome
