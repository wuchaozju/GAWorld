"""Wiring tests for DynamicBehaviorPlugin + SpatialPreferencesPlugin (K3i).

Kernel-level; domain suites (test_dynamic_behavior / test_spatial_preferences)
cover the engines. Pinned here:

1. ``interrupts.compose``: the plugin produces the transient thought when
   enabled; a disabled plugin leaves ``None`` flowing (legacy fallback);
   an upstream producer's value passes through untouched.
2. ``location.resolve``: aversion-aware redirection rewrites the location;
   empty locations pass through.
3. ``interrupt.applied``: a persistent local-physical interrupt records an
   anomaly experience (with the replan-gate parity); resumable or
   city-wide anomalies do not.
4. ``agents.built`` / ``on_day_start``: stateful load and recency decay.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from gaworld.behavior.plugin import DynamicBehaviorPlugin
from gaworld.kernel import build_kernel
from gaworld.world.plugin import SpatialPreferencesPlugin


def _ctx(config):
    ctx = build_kernel(config, load_entry_points=False)
    ctx.extras["city_map"] = {"nodes": {}}
    return ctx


class TestDynamicBehaviorPlugin(unittest.TestCase):
    def test_enabled_produces_thought(self):
        ctx = _ctx({"dynamic_behavior": {"enabled": True}})
        ctx.set_agents([{"id": 1}])
        DynamicBehaviorPlugin().setup(ctx)
        thought = {"kind": "urge", "intensity": 0.4}
        with patch(
            "gaworld.behavior.dynamic.dynamic_transient_thought",
            lambda *a, **kw: dict(thought),
        ):
            out = ctx.bus.filter(
                "interrupts.compose", None,
                agent={"id": 1}, step={"scheduled_activity": "工作"},
                day=1, time_str="09:00",
            )
        self.assertEqual(out, thought)

    def test_disabled_leaves_none_for_legacy_fallback(self):
        ctx = _ctx({"dynamic_behavior": {"enabled": False}})
        DynamicBehaviorPlugin().setup(ctx)
        out = ctx.bus.filter(
            "interrupts.compose", None,
            agent={"id": 1}, step={}, day=1, time_str="09:00",
        )
        self.assertIsNone(out)

    def test_upstream_producer_wins(self):
        ctx = _ctx({"dynamic_behavior": {"enabled": True}})
        ctx.bus.on(
            "interrupts.compose",
            lambda value, hc: {"kind": "custom"} if value is None else None,
            priority=10,
        )
        DynamicBehaviorPlugin().setup(ctx)
        with patch(
            "gaworld.behavior.dynamic.dynamic_transient_thought",
            lambda *a, **kw: self.fail("must not run when upstream produced"),
        ):
            out = ctx.bus.filter(
                "interrupts.compose", None,
                agent={"id": 1}, step={}, day=1, time_str="09:00",
            )
        self.assertEqual(out, {"kind": "custom"})


class TestSpatialPreferencesPlugin(unittest.TestCase):
    def _setup(self, *, stateful=False, replan_enabled=True):
        ctx = _ctx(
            {
                "spatial_preferences": {"enabled": True, "avoid_threshold": 1.5},
                "replan": {"enabled": replan_enabled},
                "stateful": stateful,
            }
        )
        plugin = SpatialPreferencesPlugin()
        plugin.setup(ctx)
        return ctx, plugin

    def test_redirect_rewrites_location(self):
        ctx, _ = self._setup()
        with patch(
            "gaworld.memory.spatial_preferences.redirect_for_aversion",
            lambda agent, cm, loc, t, threshold: ("备用书店", True),
        ):
            out = ctx.bus.filter(
                "location.resolve", "拥挤书店",
                agent={"id": 1}, activity="阅读", day=1, time_str="10:00",
            )
        self.assertEqual(out, "备用书店")
        self.assertIsNone(
            ctx.bus.filter(
                "location.resolve", "",
                agent={"id": 1}, activity="阅读", day=1, time_str="10:00",
            ) or None
        )

    def _emit_applied(self, ctx, *, resumable, event_type, changed=True):
        recorded = []
        with patch(
            "gaworld.memory.spatial_preferences.record_anomaly_experience",
            lambda agent, **kw: recorded.append(kw),
        ):
            ctx.bus.emit(
                "interrupt.applied",
                agent={"id": 1},
                step={},
                dyn_result={
                    "interrupt": {
                        "kind": "crowd_anomaly",
                        "resumable": resumable,
                        "extra": {
                            "anomaly": True,
                            "event_type": event_type,
                            "location": "菜市场",
                        },
                    }
                },
                changed=changed,
                scheduled_activity="买菜",
                day=2,
                time_str="17:00",
            )
        return recorded

    def test_persistent_local_anomaly_recorded(self):
        ctx, _ = self._setup()
        recorded = self._emit_applied(ctx, resumable=False, event_type="local_physical")
        self.assertEqual(len(recorded), 1)
        self.assertEqual(recorded[0]["location"], "菜市场")

    def test_resumable_or_macro_anomaly_not_recorded(self):
        ctx, _ = self._setup()
        self.assertEqual(
            self._emit_applied(ctx, resumable=True, event_type="local_physical"), []
        )
        self.assertEqual(
            self._emit_applied(ctx, resumable=False, event_type="weather"), []
        )

    def test_replan_gate_parity(self):
        ctx, _ = self._setup(replan_enabled=False)
        self.assertEqual(
            self._emit_applied(ctx, resumable=False, event_type="local_physical"), []
        )

    def test_stateful_load_and_day_decay(self):
        ctx, _ = self._setup(stateful=True)
        agents = [{"id": 7}]
        with patch(
            "gaworld.memory.experience.load_agent_env_preferences",
            lambda aid: {"avoid": {"菜市场": 2.0}},
        ):
            ctx.bus.emit("agents.built", agents=agents)
        self.assertEqual(agents[0]["env_preferences"], {"avoid": {"菜市场": 2.0}})
        decayed, saved = [], []
        with patch(
            "gaworld.memory.spatial_preferences.decay_preferences",
            lambda agent, day, half_life_days: decayed.append((agent["id"], day)),
        ), patch(
            "gaworld.memory.experience.save_agent_env_preferences",
            lambda aid, prefs: saved.append(aid),
        ):
            ctx.bus.emit("on_day_start", day=3, agents=agents)
        self.assertEqual(decayed, [(7, 3)])
        self.assertEqual(saved, [7])


if __name__ == "__main__":
    unittest.main()
