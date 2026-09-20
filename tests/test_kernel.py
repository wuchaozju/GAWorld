"""Unit tests for the gaworld.kernel six services (K1).

Covers the contracts plugins will rely on from K3 onward:

* EventBus — observe compatibility with HookBus, collect/filter semantics,
  priority ordering, strict mode, CONFIG["extensions"] loading.
* PluginRegistry — assembly sources, dependency ordering, trust boundary.
* Clock / Recorder / Controller / SimContext — kernel service behavior.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest

from gaworld.kernel import (
    ActionRequest,
    Clock,
    Controller,
    EventBus,
    Plugin,
    PluginRegistry,
    Recorder,
    SimContext,
    Verdict,
    build_kernel,
)


# -- helpers importable via "tests.test_kernel:<name>" -----------------------

CALLS: list = []


def sample_hook(ctx):
    CALLS.append(ctx)


class DummyPlugin(Plugin):
    id = "dummy"

    def __init__(self):
        self.setup_calls = 0
        self.teardown_calls = 0

    def setup(self, ctx):
        self.setup_calls += 1

    def teardown(self, ctx):
        self.teardown_calls += 1


class NeedsDummyPlugin(DummyPlugin):
    id = "needs_dummy"
    requires = ("dummy",)


class BrokenSetupPlugin(DummyPlugin):
    id = "broken"

    def setup(self, ctx):
        raise RuntimeError("boom")


def _ctx(**overrides) -> SimContext:
    kernel = build_kernel(overrides.pop("config", {}), load_entry_points=False)
    for key, value in overrides.items():
        setattr(kernel, key, value)
    return kernel


class TestEventBus(unittest.TestCase):
    def setUp(self):
        CALLS.clear()

    def test_emit_is_hookbus_compatible(self):
        bus = EventBus({"hooks": {"phase": ["tests.test_kernel:sample_hook"]}})
        errors = bus.emit("phase", day=3)
        self.assertEqual(errors, [])
        self.assertEqual(len(CALLS), 1)
        self.assertEqual(CALLS[0]["day"], 3)

    def test_base_context_merged_into_every_dispatch(self):
        bus = EventBus()
        bus.base_context["sim"] = "SIM"
        seen = {}
        bus.on("e", lambda ctx: seen.update(ctx))
        bus.emit("e", extra=1)
        self.assertEqual(seen["sim"], "SIM")
        self.assertEqual(seen["extra"], 1)

    def test_collect_merges_and_orders_by_priority(self):
        bus = EventBus()
        bus.on("c", lambda ctx: ["low1", "low2"])
        bus.on("c", lambda ctx: "high", priority=10)
        bus.on("c", lambda ctx: None)  # None contributes nothing
        self.assertEqual(bus.collect("c"), ["high", "low1", "low2"])

    def test_filter_chains_and_none_keeps_value(self):
        bus = EventBus()
        bus.on("f", lambda value, ctx: value + "-a")
        bus.on("f", lambda value, ctx: None)  # buggy handler: no return
        bus.on("f", lambda value, ctx: value + "-b")
        self.assertEqual(bus.filter("f", "v"), "v-a-b")

    def test_handler_error_is_contained_and_reported(self):
        bus = EventBus()
        bus.on("e", lambda ctx: 1 / 0)
        bus.on("e", lambda ctx: CALLS.append("survived"))
        errors = bus.emit("e")
        self.assertEqual(len(errors), 1)
        self.assertIn("survived", CALLS)

    def test_strict_mode_raises(self):
        bus = EventBus({"strict": True})
        bus.on("e", lambda ctx: 1 / 0)
        with self.assertRaises(RuntimeError):
            bus.emit("e")

    def test_register_alias_for_hookbus_callers(self):
        bus = EventBus()
        bus.register("e", lambda ctx: CALLS.append("via-register"))
        bus.emit("e")
        self.assertIn("via-register", CALLS)


class TestPluginRegistry(unittest.TestCase):
    def test_register_rejects_missing_and_duplicate_ids(self):
        reg = PluginRegistry()
        self.assertFalse(reg.register(Plugin()))  # no id
        self.assertTrue(reg.register(DummyPlugin()))
        self.assertFalse(reg.register(DummyPlugin()))  # duplicate

    def test_load_config_plugins_by_class_path(self):
        reg = PluginRegistry()
        reg.load_config_plugins(
            [
                {"class": "tests.test_kernel:DummyPlugin"},
                {"class": "tests.test_kernel:NeedsDummyPlugin", "enabled": False},
                {"class": "no.such.module:Nope"},  # warns, skipped
                "not-a-dict",
            ]
        )
        self.assertEqual(reg.ids(), ["dummy"])

    def test_setup_runs_in_dependency_order(self):
        reg = PluginRegistry()
        needs = NeedsDummyPlugin()
        base = DummyPlugin()
        reg.register(needs)  # registered before its dependency
        reg.register(base)
        active = reg.setup_all(_ctx())
        self.assertEqual(active, ["dummy", "needs_dummy"])
        self.assertEqual(base.setup_calls, 1)
        self.assertEqual(needs.setup_calls, 1)

    def test_missing_dependency_skips_dependent(self):
        reg = PluginRegistry()
        needs = NeedsDummyPlugin()
        reg.register(needs)
        active = reg.setup_all(_ctx())
        self.assertEqual(active, [])
        self.assertEqual(needs.setup_calls, 0)

    def test_broken_setup_deactivates_only_that_plugin(self):
        reg = PluginRegistry()
        reg.register(BrokenSetupPlugin())
        reg.register(DummyPlugin())
        active = reg.setup_all(_ctx())
        self.assertEqual(active, ["dummy"])

    def test_teardown_reverse_order(self):
        reg = PluginRegistry()
        base, needs = DummyPlugin(), NeedsDummyPlugin()
        reg.register(base)
        reg.register(needs)
        ctx = _ctx()
        reg.setup_all(ctx)
        reg.teardown_all(ctx)
        self.assertEqual(base.teardown_calls, 1)
        self.assertEqual(needs.teardown_calls, 1)
        self.assertEqual(reg.active_ids(), [])


class TestClock(unittest.TestCase):
    def test_start_day_resets_tick(self):
        clock = Clock()
        clock.start_day(2)
        clock.advance("08:30", 0)
        clock.advance("09:00", 1)
        self.assertEqual(
            clock.snapshot(), {"day": 2, "time_str": "09:00", "tick_index": 1}
        )
        clock.start_day(3)
        self.assertEqual(clock.tick_index, -1)


class TestRecorder(unittest.TestCase):
    def test_records_jsonl_with_clock_stamp(self):
        clock = Clock()
        clock.start_day(5)
        clock.advance("10:00", 3)
        with tempfile.TemporaryDirectory() as tmp:
            rec = Recorder(base_dir=tmp, clock=clock)
            rec.record("economy.ledger", {"agent_id": 1, "amount": 9.5})
            rec.record("bad/table name!", {"x": 1})  # sanitized
            rec.close()
            with open(os.path.join(tmp, "economy.ledger.jsonl"), encoding="utf-8") as fh:
                row = json.loads(fh.readline())
            self.assertEqual(row["agent_id"], 1)
            self.assertEqual(row["_day"], 5)
            self.assertEqual(row["_time"], "10:00")
            self.assertTrue(
                any(name.startswith("bad_table") for name in os.listdir(tmp))
            )


class TestController(unittest.TestCase):
    def test_default_allow_with_passthrough_request(self):
        ctrl = Controller()
        req = ActionRequest(agent_id=1, name="move", params={"to": "图书馆"})
        verdict = ctrl.validate(req, _ctx())
        self.assertTrue(verdict.allowed)
        self.assertIs(verdict.rewritten, req)

    def test_first_deny_wins_and_is_recorded(self):
        ctrl = Controller()
        ctrl.register_validator(lambda req, ctx: Verdict.deny("closed"), priority=10)
        ctrl.register_validator(lambda req, ctx: Verdict.allow())
        with tempfile.TemporaryDirectory() as tmp:
            ctx = _ctx(recorder=Recorder(base_dir=tmp))
            verdict = ctrl.validate(ActionRequest(1, "move"), ctx)
            ctx.recorder.close()
            self.assertFalse(verdict.allowed)
            self.assertEqual(verdict.reason, "closed")
            with open(os.path.join(tmp, "action.denied.jsonl"), encoding="utf-8") as fh:
                self.assertEqual(json.loads(fh.readline())["reason"], "closed")

    def test_rewrite_flows_to_next_validator(self):
        ctrl = Controller()
        rewritten = ActionRequest(1, "move", {"to": "备用地点"})
        ctrl.register_validator(lambda req, ctx: Verdict.rewrite(rewritten), priority=5)
        seen = {}
        ctrl.register_validator(lambda req, ctx: seen.update(to=req.params.get("to")) or None)
        verdict = ctrl.validate(ActionRequest(1, "move", {"to": "已关门"}), _ctx())
        self.assertTrue(verdict.allowed)
        self.assertEqual(seen["to"], "备用地点")
        self.assertIs(verdict.rewritten, rewritten)

    def test_validator_error_treated_as_no_opinion(self):
        ctrl = Controller()
        ctrl.register_validator(lambda req, ctx: 1 / 0)
        self.assertTrue(ctrl.validate(ActionRequest(1, "x"), _ctx()).allowed)

    def test_intervene_unknown_raises_and_known_is_audited(self):
        ctrl = Controller()
        with self.assertRaises(ValueError):
            ctrl.intervene("nope", _ctx())
        ctrl.register_intervention("set_flag", lambda ctx, **kw: kw["value"])
        with tempfile.TemporaryDirectory() as tmp:
            ctx = _ctx(recorder=Recorder(base_dir=tmp))
            result = ctrl.intervene("set_flag", ctx, value=42)
            ctx.recorder.close()
            self.assertEqual(result, 42)
            with open(
                os.path.join(tmp, "controller.intervention.jsonl"), encoding="utf-8"
            ) as fh:
                self.assertEqual(json.loads(fh.readline())["name"], "set_flag")


class TestSimContext(unittest.TestCase):
    def test_plugin_state_and_agent_ext_namespaces(self):
        ctx = _ctx()
        state = ctx.plugin_state("economy")
        state["pool"] = 100
        self.assertEqual(ctx.plugin_state("economy")["pool"], 100)
        agent = {"id": 1}
        ext = ctx.agent_ext(agent, "interests")
        ext["level"] = 0.4
        self.assertEqual(agent["ext"]["interests"]["level"], 0.4)

    def test_set_agents_refreshes_index(self):
        ctx = _ctx()
        ctx.set_agents([{"id": 7}, {"id": 9}])
        self.assertEqual(set(ctx.agents_by_id), {7, 9})

    def test_build_kernel_loads_extension_hooks_and_binds_sim(self):
        ctx = build_kernel(
            {"extensions": {"hooks": {"on_day_start": ["tests.test_kernel:sample_hook"]}}},
            load_entry_points=False,
        )
        self.assertIs(ctx.bus.base_context["sim"], ctx)
        CALLS.clear()
        ctx.bus.emit("on_day_start", day=1)
        self.assertEqual(len(CALLS), 1)
        self.assertIs(CALLS[0]["sim"], ctx)


if __name__ == "__main__":
    unittest.main()
