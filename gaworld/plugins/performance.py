"""Observe simulation work through the normal kernel plugin lifecycle."""

from __future__ import annotations

from typing import Any

from gaworld.core.performance import ACTIVE_TIMINGS, TimingCollector
from gaworld.kernel import Plugin, SimContext


class PerformancePlugin(Plugin):
    id = "performance"

    def setup(self, ctx: SimContext) -> None:
        config = ctx.config.get(self.id, {}) or {}
        if not config.get("enabled", True):
            return
        ctx.bus.on("agents.built", self._activate, priority=10000)
        ctx.bus.on("on_day_end", self._day_end, priority=-10000)
        ctx.bus.on("on_simulation_end", self._simulation_end, priority=-10000)

    @staticmethod
    def _activate(hook_ctx: dict[str, Any]) -> None:
        ctx = hook_ctx["sim"]
        state = ctx.plugin_state("performance")
        if "token" not in state:
            config = ctx.config.get("performance", {}) or {}
            collector = TimingCollector(sample_limit=config.get("sample_limit", 512))
            state["collector"] = collector
            state["token"] = ACTIVE_TIMINGS.set(collector)
            ctx.extras["performance"] = collector

    @staticmethod
    def _publish(ctx: SimContext, scope: str, day: Any = None) -> None:
        collector = ctx.plugin_state("performance").get("collector")
        if collector is None:
            return
        report = collector.snapshot()
        report.update(scope=scope, day=day, coverage="agents.built_to_on_simulation_end")
        ctx.recorder.record("performance.summary", report)
        # Keep categories separate: stage totals already include nested work.
        leaders = []
        for prefix in ("stage.", "llm.", "memory."):
            rows = [(name, row) for name, row in report["operations"].items() if name.startswith(prefix)]
            if rows:
                name, row = max(rows, key=lambda item: item[1]["total_ms"])
                leaders.append(f"{name}: {row['calls']}次 / 累计{row['total_ms'] / 1000:.2f}s")
        print(f"[性能 {scope} day={day}] {'；'.join(leaders) or '尚无计时样本'}")

    def _day_end(self, hook_ctx: dict[str, Any]) -> None:
        self._publish(hook_ctx["sim"], "day_end", hook_ctx.get("day"))

    def _simulation_end(self, hook_ctx: dict[str, Any]) -> None:
        self._publish(hook_ctx["sim"], "simulation_end")

    def teardown(self, ctx: SimContext) -> None:
        token = ctx.plugin_state(self.id).pop("token", None)
        if token is not None and ACTIVE_TIMINGS.get() is ctx.plugin_state(self.id).get("collector"):
            ACTIVE_TIMINGS.reset(token)
