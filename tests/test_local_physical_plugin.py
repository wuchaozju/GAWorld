"""Wiring tests for the LocalPhysicalPlugin (K3g migration).

Kernel-level: the local-physical domain logic has its own suite
(test_local_physical.py); pinned here is the plugin wiring:

1. ``on_time_tick`` refreshes the map (sim time + occupancy) when enabled,
   and skips when disabled or without a map;
2. ``perception.compose`` stores the snapshot on ``agent["_local_physical"]``
   and contributes the "身边的物理环境：…" line at priority 30 (ahead of
   lower-priority contributions);
3. disabled: the agent key resets to ``{}`` and nothing is contributed;
4. ``inject_into_perception=False``: snapshot stored, no line contributed.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from gaworld.kernel import build_kernel
from gaworld.world.plugin import LocalPhysicalPlugin

SNAPSHOT = {"crowding": "busy", "is_open": True}


def _make_ctx(lp_cfg: dict):
    ctx = build_kernel({"local_physical": lp_cfg}, load_entry_points=False)
    ctx.extras["city_map"] = {"nodes": {}}  # placeholder; impl is patched
    ctx.extras["env_system"] = object()
    return ctx


class TestLocalPhysicalPlugin(unittest.TestCase):
    def _setup(self, lp_cfg: dict):
        ctx = _make_ctx(lp_cfg)
        plugin = LocalPhysicalPlugin()
        plugin.setup(ctx)
        return ctx, plugin

    def test_tick_refresh_when_enabled(self):
        ctx, _ = self._setup({"enabled": True})
        calls = []
        agents = [{"id": 1}]
        with patch(
            "gaworld.world.city_map.set_sim_time",
            lambda cm, t: calls.append(("time", t)),
        ), patch(
            "gaworld.world.local_physical.update_occupancy_from_agents",
            lambda cm, ag: calls.append(("occupancy", len(ag))),
        ):
            ctx.bus.emit(
                "on_time_tick",
                day=1,
                time_str="09:00",
                city_map=ctx.extras["city_map"],
                agents=agents,
            )
        self.assertEqual(calls, [("time", "09:00"), ("occupancy", 1)])

    def test_tick_refresh_skipped_when_disabled_or_no_map(self):
        ctx, _ = self._setup({"enabled": False})
        with patch(
            "gaworld.world.city_map.set_sim_time",
            lambda cm, t: self.fail("must not refresh when disabled"),
        ):
            ctx.bus.emit("on_time_tick", day=1, time_str="09:00",
                         city_map=ctx.extras["city_map"], agents=[])
        ctx2, _ = self._setup({"enabled": True})
        with patch(
            "gaworld.world.city_map.set_sim_time",
            lambda cm, t: self.fail("must not refresh without a map"),
        ):
            ctx2.bus.emit("on_time_tick", day=1, time_str="09:00",
                          city_map=None, agents=[])

    def test_snapshot_stored_and_line_contributed(self):
        ctx, _ = self._setup({"enabled": True, "inject_into_perception": True})
        agent = {"id": 1}
        with patch(
            "gaworld.world.local_physical.local_physical_state",
            lambda *a, **kw: dict(SNAPSHOT),
        ), patch(
            "gaworld.world.local_physical.physical_state_text",
            lambda snap: "人比较多，门开着",
        ):
            snippets = ctx.bus.collect(
                "perception.compose", agent=agent, day=1, time_str="09:00",
            )
        self.assertEqual(agent["_local_physical"], SNAPSHOT)
        self.assertEqual(snippets, ["身边的物理环境：人比较多，门开着"])

    def test_priority_ahead_of_lower_contributions(self):
        ctx, _ = self._setup({"enabled": True})
        ctx.bus.on("perception.compose", lambda hc: "干预推荐行", priority=10)
        agent = {"id": 1}
        with patch(
            "gaworld.world.local_physical.local_physical_state",
            lambda *a, **kw: dict(SNAPSHOT),
        ), patch(
            "gaworld.world.local_physical.physical_state_text",
            lambda snap: "拥挤",
        ):
            snippets = ctx.bus.collect(
                "perception.compose", agent=agent, day=1, time_str="09:00",
            )
        self.assertEqual(snippets, ["身边的物理环境：拥挤", "干预推荐行"])

    def test_disabled_resets_key_and_contributes_nothing(self):
        ctx, _ = self._setup({"enabled": False})
        agent = {"id": 1, "_local_physical": {"stale": True}}
        snippets = ctx.bus.collect(
            "perception.compose", agent=agent, day=1, time_str="09:00",
        )
        self.assertEqual(agent["_local_physical"], {})
        self.assertEqual(snippets, [])

    def test_inject_disabled_stores_snapshot_only(self):
        ctx, _ = self._setup({"enabled": True, "inject_into_perception": False})
        agent = {"id": 1}
        with patch(
            "gaworld.world.local_physical.local_physical_state",
            lambda *a, **kw: dict(SNAPSHOT),
        ):
            snippets = ctx.bus.collect(
                "perception.compose", agent=agent, day=1, time_str="09:00",
            )
        self.assertEqual(agent["_local_physical"], SNAPSHOT)
        self.assertEqual(snippets, [])


if __name__ == "__main__":
    unittest.main()
