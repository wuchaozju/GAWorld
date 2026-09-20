"""Wiring tests for the RealWorkPlugin (K3h migration).

Kernel-level with a stub runtime (the work domain has its own suites —
test_real_work_router / test_real_work_adapters). Pinned:

1. ``on_simulation_start`` creates + starts the runtime and stores it in
   plugin state (a ``None`` runtime — feature disabled — is stored too);
2. ``on_day_start`` ticks the job market;
3. the ``action.outcome`` filter rewrites the outcome on dispatch and
   appends the 回收 suffix on absorption; disabled runs pass through;
4. ``teardown`` stops the worker pool.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from gaworld.kernel import build_kernel
from gaworld.work.plugin import RealWorkPlugin


class _StubRouter:
    def __init__(self, outcome):
        self._outcome = outcome
        self.dispatched = []

    def maybe_dispatch(self, agent, **kw):
        self.dispatched.append(kw)
        return self._outcome


class _StubRuntime:
    def __init__(self, dispatch_outcome=None, absorbed=None):
        self.router = _StubRouter(dispatch_outcome)
        self._absorbed = absorbed
        self.started = False
        self.stopped = False
        self.ticked_days = []

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def tick_day(self, day):
        self.ticked_days.append(day)

    def absorb_for(self, agent, **kw):
        return self._absorbed


def _setup(runtime):
    ctx = build_kernel({}, load_entry_points=False)
    ctx.llm = lambda prompt, **kw: ""
    plugin = RealWorkPlugin()
    plugin.setup(ctx)
    with patch(
        "gaworld.work.runtime.RealWorkRuntime.create",
        staticmethod(lambda config, agents, llm_fn=None: runtime),
    ):
        ctx.bus.emit("on_simulation_start", agents=[{"id": 1}])
    return ctx, plugin


class TestRealWorkPlugin(unittest.TestCase):
    def test_runtime_created_started_and_stored(self):
        runtime = _StubRuntime()
        ctx, _ = _setup(runtime)
        self.assertTrue(runtime.started)
        self.assertIs(ctx.plugin_state("real_work")["runtime"], runtime)

    def test_disabled_runtime_none_everything_noops(self):
        ctx, _ = _setup(None)
        ctx.bus.emit("on_day_start", day=1)
        outcome = ctx.bus.filter(
            "action.outcome", "原始结果", agent={"id": 1},
            activity="工作", action="写代码", day=1, time_str="09:00",
        )
        self.assertEqual(outcome, "原始结果")

    def test_day_tick_reaches_market(self):
        runtime = _StubRuntime()
        ctx, _ = _setup(runtime)
        ctx.bus.emit("on_day_start", day=3)
        self.assertEqual(runtime.ticked_days, [3])

    def test_outcome_rewritten_on_dispatch_and_absorb(self):
        runtime = _StubRuntime(
            dispatch_outcome="接下了【落地页设计】任务", absorbed=[{"task_id": "t1"}]
        )
        ctx, _ = _setup(runtime)
        with patch(
            "gaworld.work.ingest.summarise_for_outcome",
            lambda done: "完成落地页 1 件",
        ):
            outcome = ctx.bus.filter(
                "action.outcome", "在【工作】中执行了【写代码】",
                agent={"id": 1}, activity="工作", action="写代码",
                day=1, time_str="09:00",
            )
        self.assertEqual(outcome, "接下了【落地页设计】任务｜回收：完成落地页 1 件")
        self.assertEqual(runtime.router.dispatched[0]["chosen_action"], "写代码")

    def test_no_dispatch_keeps_base_outcome_absorb_still_appends(self):
        runtime = _StubRuntime(dispatch_outcome=None, absorbed=[{"task_id": "t1"}])
        ctx, _ = _setup(runtime)
        with patch(
            "gaworld.work.ingest.summarise_for_outcome", lambda done: "旧任务 1 件"
        ):
            outcome = ctx.bus.filter(
                "action.outcome", "在【休闲】中执行了【散步】",
                agent={"id": 1}, activity="休闲", action="散步",
                day=1, time_str="20:00",
            )
        self.assertEqual(outcome, "在【休闲】中执行了【散步】｜回收：旧任务 1 件")

    def test_teardown_stops_worker_pool(self):
        runtime = _StubRuntime()
        ctx, plugin = _setup(runtime)
        plugin.teardown(ctx)
        self.assertTrue(runtime.stopped)
        self.assertNotIn("runtime", ctx.plugin_state("real_work"))


if __name__ == "__main__":
    unittest.main()
