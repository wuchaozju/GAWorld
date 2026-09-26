"""Tests for the P1 endogenous road congestion layer.

Two halves, matching the two files:

* ``gaworld/world/traffic.py`` — the BPR curve, how a trip's road load is
  attributed to edges, and how a tick's flows become travel-time multipliers.
* ``TrafficPlugin`` — the wiring, including the two properties the design
  leans on: results do not depend on the order agents are iterated in, and
  with the layer off nothing about a trip changes.
"""

from __future__ import annotations

import os
import tempfile
import unittest
import unittest.mock

from gaworld.kernel import build_kernel
from gaworld.world import city_map as cm
from gaworld.world import traffic as tf
from gaworld.world.plugin import TrafficPlugin


def _mini_map():
    """Three nodes in a line: A -arterial- B -local- C."""
    content = (
        "# City Map\n"
        "@node: Alpha | kind=hub | category=residential | x=0.0 | y=0.0 | capacity=100\n"
        "@node: Beta | kind=hub | category=commerce | x=3.0 | y=0.0 | capacity=100\n"
        "@node: Gamma | kind=hub | category=industry | x=6.0 | y=0.0 | capacity=100\n"
        "@road: Alpha -> Beta | type=arterial\n"
        "@road: Beta -> Gamma | type=local\n"
        "\n- City: Demo\n  - Hub: Alpha\n  - Hub: Beta\n  - Hub: Gamma\n"
    )
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "m.md")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        return cm.load_city_map(path)


def _graph_map():
    """A hand-built adjacency, because the map *generator* auto-links nearby
    nodes as arterials and its edge wins the lookup over a declared local
    street — see ``test_first_declared_class_wins`` for why that is left
    alone rather than worked around."""
    return {
        "nodes": {
            "Alpha": {"id": "Alpha", "name": "Alpha", "x": 0.0, "y": 0.0},
            "Beta": {"id": "Beta", "name": "Beta", "x": 3.0, "y": 0.0},
            "Gamma": {"id": "Gamma", "name": "Gamma", "x": 6.0, "y": 0.0},
        },
        "adjacency": {
            "Alpha": [{"node": "Beta", "distance_km": 3.0, "road_type": "arterial"}],
            "Beta": [
                {"node": "Alpha", "distance_km": 3.0, "road_type": "arterial"},
                {"node": "Gamma", "distance_km": 3.0, "road_type": "local"},
            ],
            "Gamma": [{"node": "Beta", "distance_km": 3.0, "road_type": "local"}],
        },
    }


def _trip(route, mode="car", status="arrived"):
    return {"mode": mode, "status": status, "route": list(route)}


class TestBPR(unittest.TestCase):
    def test_free_flow_is_exactly_one(self):
        self.assertEqual(tf.bpr_factor(0.0, 100.0), 1.0)

    def test_known_points(self):
        # 1 + 0.15 * (v/c)^4
        self.assertAlmostEqual(tf.bpr_factor(50.0, 100.0), 1.0 + 0.15 * 0.5 ** 4, places=9)
        self.assertAlmostEqual(tf.bpr_factor(100.0, 100.0), 1.15, places=9)

    def test_over_capacity_is_clamped(self):
        # 1 + 0.15*16 = 3.4, above the 3.0 ceiling.
        self.assertEqual(tf.bpr_factor(200.0, 100.0, max_congestion=3.0), 3.0)

    def test_degenerate_capacity_does_not_explode(self):
        self.assertLessEqual(tf.bpr_factor(10.0, 0.0), 3.0)
        self.assertGreaterEqual(tf.bpr_factor(10.0, 0.0), 1.0)


class TestFlowAttribution(unittest.TestCase):
    def test_every_edge_of_the_route_is_loaded(self):
        flows: dict[str, float] = {}
        added = tf.accumulate_travel(flows, _trip(["Alpha", "Beta", "Gamma"]))
        self.assertEqual(added, 1.0)
        self.assertEqual(len(flows), 2)
        self.assertEqual(flows[cm._edge_key("Alpha", "Beta")], 1.0)
        self.assertEqual(flows[cm._edge_key("Beta", "Gamma")], 1.0)

    def test_off_road_modes_contribute_nothing(self):
        for mode in ("walk", "metro"):
            flows: dict[str, float] = {}
            self.assertEqual(tf.accumulate_travel(flows, _trip(["Alpha", "Beta"], mode=mode)), 0.0)
            self.assertEqual(flows, {})

    def test_bus_weighs_more_than_a_car(self):
        self.assertGreater(
            tf.travel_pcu(_trip(["Alpha", "Beta"], mode="bus")),
            tf.travel_pcu(_trip(["Alpha", "Beta"], mode="car")),
        )

    def test_single_tick_trips_count(self):
        """The trap: move_agent only sets in_transit for multi-tick trips, so
        counting only those would miss nearly every vehicle."""
        for status in ("arrived", "departed", "in_transit"):
            with self.subTest(status=status):
                self.assertEqual(
                    tf.travel_pcu(_trip(["Alpha", "Beta"], status=status)), 1.0
                )

    def test_a_resident_who_did_not_travel_contributes_nothing(self):
        self.assertEqual(tf.travel_pcu(_trip(["Alpha"], status="stationary")), 0.0)
        self.assertEqual(tf.travel_pcu(None), 0.0)

    def test_agents_represent_scales_the_load(self):
        flows: dict[str, float] = {}
        tf.accumulate_travel(flows, _trip(["Alpha", "Beta"]), agents_represent=40.0)
        self.assertEqual(flows[cm._edge_key("Alpha", "Beta")], 40.0)

    def test_direction_does_not_split_an_edge(self):
        flows: dict[str, float] = {}
        tf.accumulate_travel(flows, _trip(["Alpha", "Beta"]))
        tf.accumulate_travel(flows, _trip(["Beta", "Alpha"]))
        self.assertEqual(len(flows), 1)
        self.assertEqual(flows[cm._edge_key("Alpha", "Beta")], 2.0)


class TestCapacity(unittest.TestCase):
    def test_road_class_is_read_from_the_map(self):
        city_map = _graph_map()
        self.assertEqual(tf.edge_road_type(city_map, "Alpha", "Beta"), "arterial")
        self.assertEqual(tf.edge_road_type(city_map, "Beta", "Gamma"), "local")

    def test_unknown_pair_falls_back(self):
        self.assertEqual(tf.edge_road_type(_graph_map(), "Alpha", "Nowhere"), "road")
        self.assertEqual(tf.edge_road_type(None, "Alpha", "Beta"), "road")

    def test_first_declared_class_wins(self):
        """Parallel edges between the same pair are resolved first-match, the
        same way ``_route_road_factor`` resolves them. Picking differently
        here would make the two disagree about one road."""
        city_map = _graph_map()
        city_map["adjacency"]["Beta"].append(
            {"node": "Gamma", "distance_km": 3.0, "road_type": "arterial"}
        )
        self.assertEqual(tf.edge_road_type(city_map, "Beta", "Gamma"), "local")

    def test_an_arterial_carries_more_than_a_local_street(self):
        city_map = _graph_map()
        arterial = tf.edge_capacity_pcu(city_map, "Alpha", "Beta", step_minutes=30)
        local = tf.edge_capacity_pcu(city_map, "Beta", "Gamma", step_minutes=30)
        self.assertGreater(arterial, local)

    def test_capacity_scales_with_tick_length(self):
        city_map = _graph_map()
        half = tf.edge_capacity_pcu(city_map, "Alpha", "Beta", step_minutes=30)
        full = tf.edge_capacity_pcu(city_map, "Alpha", "Beta", step_minutes=60)
        self.assertAlmostEqual(full, half * 2.0, places=6)


class TestApplyFlows(unittest.TestCase):
    def test_heavy_flow_slows_an_edge_and_light_flow_does_not(self):
        city_map = _mini_map()
        capacity = tf.edge_capacity_pcu(city_map, "Beta", "Gamma", step_minutes=30)
        key = cm._edge_key("Beta", "Gamma")
        tf.apply_flows(city_map, {key: capacity * 2}, step_minutes=30, decay=0.0)
        self.assertGreater(cm.get_edge_congestion(city_map, "Beta", "Gamma"), 1.0)

        city_map = _mini_map()
        tf.apply_flows(city_map, {key: capacity * 0.1}, step_minutes=30, decay=0.0)
        self.assertEqual(cm.get_edge_congestion(city_map, "Beta", "Gamma"), 1.0)

    def test_a_jam_eases_off_instead_of_snapping_back(self):
        city_map = _mini_map()
        capacity = tf.edge_capacity_pcu(city_map, "Beta", "Gamma", step_minutes=30)
        key = cm._edge_key("Beta", "Gamma")
        tf.apply_flows(city_map, {key: capacity * 3}, step_minutes=30, decay=0.5)
        jammed = cm.get_edge_congestion(city_map, "Beta", "Gamma")
        self.assertGreater(jammed, 1.0)
        # Next tick nobody drives it: it relaxes, but is not instantly free.
        tf.apply_flows(city_map, {}, step_minutes=30, decay=0.5)
        eased = cm.get_edge_congestion(city_map, "Beta", "Gamma")
        self.assertLess(eased, jammed)
        self.assertGreater(eased, 1.0)

    def test_the_table_does_not_grow_without_bound(self):
        city_map = _mini_map()
        capacity = tf.edge_capacity_pcu(city_map, "Beta", "Gamma", step_minutes=30)
        key = cm._edge_key("Beta", "Gamma")
        tf.apply_flows(city_map, {key: capacity * 3}, step_minutes=30, decay=0.5)
        for _ in range(60):
            tf.apply_flows(city_map, {}, step_minutes=30, decay=0.5)
        self.assertEqual(city_map["runtime"]["edge_congestion"], {})

    def test_missing_map_is_safe(self):
        self.assertEqual(tf.apply_flows(None, {"x": 1.0}, step_minutes=30), {})


class TestRushHourOverride(unittest.TestCase):
    def test_default_is_the_static_constant(self):
        self.assertEqual(cm.rush_hour_time_mult(_mini_map()), cm.RUSH_HOUR_TIME_MULT)
        self.assertEqual(cm.rush_hour_time_mult(None), cm.RUSH_HOUR_TIME_MULT)

    def test_override_applies_and_never_speeds_travel_up(self):
        city_map = _mini_map()
        cm.set_rush_hour_time_mult(city_map, 1.0)
        self.assertEqual(cm.rush_hour_time_mult(city_map), 1.0)
        cm.set_rush_hour_time_mult(city_map, 0.2)
        self.assertEqual(cm.rush_hour_time_mult(city_map), 1.0)

    def test_a_rush_hour_trip_is_shorter_once_the_proxy_stands_down(self):
        agent = {"job": "工程师", "daily_life": "", "personality": ""}
        rush = "08:00"
        self.assertTrue(cm.is_rush_hour(rush))
        with_proxy = cm.travel_plan(agent, _mini_map(), "Alpha", "Gamma", time_str=rush)
        city_map = _mini_map()
        cm.set_rush_hour_time_mult(city_map, 1.0)
        without = cm.travel_plan(agent, city_map, "Alpha", "Gamma", time_str=rush)
        self.assertLess(without["travel_minutes"], with_proxy["travel_minutes"])
        # The taxi surcharge is a fare rule, not a congestion model: untouched.
        self.assertEqual(without["travel_cost"], with_proxy["travel_cost"])


def _ctx(cfg, records_dir=None):
    """A kernel whose recorder writes to a throwaway directory.

    Without this the suite appends its fixtures to the repo's real
    ``output/records/traffic.tick.jsonl`` — 378 rows of ``Alpha||Beta`` at
    ``_day: 0`` were sitting in there, which is exactly the sort of thing
    someone later mistakes for a run.
    """
    ctx = build_kernel(
        {"traffic": cfg,
         "records": {"output_dir": records_dir or tempfile.mkdtemp()}},
        load_entry_points=False,
    )
    ctx.extras["city_map"] = _mini_map()
    return ctx


def _run_tick(ctx, plugin, trips, time_str):
    """One tick: commit the previous tick's flows, then collect this tick's."""
    city_map = ctx.extras["city_map"]
    ctx.bus.emit("on_time_tick", day=1, time_str=time_str, city_map=city_map, agents=[])
    for index, trip in enumerate(trips):
        ctx.bus.emit(
            "on_agent_post_step",
            day=1,
            time_str=time_str,
            agent={"id": index},
            city_map=city_map,
            step={"_travel": trip},
        )


class TestTrafficPluginWiring(unittest.TestCase):
    def test_disabled_changes_nothing(self):
        ctx = _ctx({"enabled": False})
        plugin = TrafficPlugin()
        plugin.setup(ctx)
        city_map = ctx.extras["city_map"]
        _run_tick(ctx, plugin, [_trip(["Alpha", "Beta"])] * 50, "08:00")
        ctx.bus.emit("on_time_tick", day=1, time_str="08:30", city_map=city_map, agents=[])
        self.assertEqual(city_map.get("runtime", {}).get("edge_congestion", {}), {})
        self.assertEqual(cm.rush_hour_time_mult(city_map), cm.RUSH_HOUR_TIME_MULT)

    def test_enabled_produces_congestion_on_the_next_tick_not_this_one(self):
        ctx = _ctx({"enabled": True, "agents_represent": 100.0, "decay": 0.0})
        TrafficPlugin().setup(ctx)
        city_map = ctx.extras["city_map"]
        _run_tick(ctx, None, [_trip(["Alpha", "Beta"])] * 30, "08:00")
        # Still free-flowing *during* the tick the trips were made in.
        self.assertEqual(cm.get_edge_congestion(city_map, "Alpha", "Beta"), 1.0)
        ctx.bus.emit("on_time_tick", day=1, time_str="08:30", city_map=city_map, agents=[])
        self.assertGreater(cm.get_edge_congestion(city_map, "Alpha", "Beta"), 1.0)

    def test_enabled_stands_the_static_rush_hour_proxy_down(self):
        ctx = _ctx({"enabled": True})
        TrafficPlugin().setup(ctx)
        city_map = ctx.extras["city_map"]
        ctx.bus.emit("on_time_tick", day=1, time_str="08:00", city_map=city_map, agents=[])
        self.assertEqual(cm.rush_hour_time_mult(city_map), 1.0)

    def test_the_proxy_stays_when_suppression_is_switched_off(self):
        ctx = _ctx({"enabled": True, "suppress_rush_hour_mult": False})
        TrafficPlugin().setup(ctx)
        city_map = ctx.extras["city_map"]
        ctx.bus.emit("on_time_tick", day=1, time_str="08:00", city_map=city_map, agents=[])
        self.assertEqual(cm.rush_hour_time_mult(city_map), cm.RUSH_HOUR_TIME_MULT)

    def test_result_is_independent_of_agent_iteration_order(self):
        """The reason flows are committed a tick late: otherwise whoever the
        loop reaches first decides who is stuck in traffic."""
        trips = (
            [_trip(["Alpha", "Beta"])] * 12
            + [_trip(["Beta", "Gamma"], mode="bus")] * 5
            + [_trip(["Alpha", "Beta", "Gamma"], mode="taxi")] * 7
        )
        results = []
        for ordering in (trips, list(reversed(trips))):
            ctx = _ctx({"enabled": True, "agents_represent": 50.0})
            TrafficPlugin().setup(ctx)
            city_map = ctx.extras["city_map"]
            _run_tick(ctx, None, ordering, "08:00")
            ctx.bus.emit("on_time_tick", day=1, time_str="08:30", city_map=city_map, agents=[])
            results.append(dict(city_map["runtime"]["edge_congestion"]))
        self.assertEqual(results[0], results[1])
        self.assertTrue(results[0], "the fixture should actually congest something")

    def test_each_day_starts_from_free_flow(self):
        ctx = _ctx({"enabled": True, "agents_represent": 100.0})
        TrafficPlugin().setup(ctx)
        city_map = ctx.extras["city_map"]
        _run_tick(ctx, None, [_trip(["Alpha", "Beta"])] * 30, "08:00")
        ctx.bus.emit("on_time_tick", day=1, time_str="08:30", city_map=city_map, agents=[])
        self.assertGreater(cm.get_edge_congestion(city_map, "Alpha", "Beta"), 1.0)
        ctx.bus.emit("on_day_start", day=2, city_map=city_map, agents=[])
        self.assertEqual(cm.get_edge_congestion(city_map, "Alpha", "Beta"), 1.0)

    def test_tick_length_is_measured_from_the_timeline(self):
        """Steps are not uniform, so capacity must follow the actual gap."""
        readings = []
        for gap_end in ("08:10", "09:00"):
            ctx = _ctx({"enabled": True, "agents_represent": 100.0, "decay": 0.0})
            TrafficPlugin().setup(ctx)
            city_map = ctx.extras["city_map"]
            _run_tick(ctx, None, [_trip(["Alpha", "Beta"])] * 30, "08:00")
            ctx.bus.emit("on_time_tick", day=1, time_str=gap_end, city_map=city_map, agents=[])
            readings.append(cm.get_edge_congestion(city_map, "Alpha", "Beta"))
        # Same vehicles spread over a longer tick -> lower volume/capacity.
        self.assertGreater(readings[0], readings[1])


class TestObservability(unittest.TestCase):
    """The number has to leave the map, or tuning it is guesswork."""

    def test_a_trip_reports_the_multiplier_it_was_planned_under(self):
        from gaworld.sim._location import move_agent

        city_map = _mini_map()
        agent = {"id": 1, "job": "工程师", "locations": {"current": "Alpha", "home": "Alpha"}}
        free = move_agent(agent, "Gamma", "通勤", "08:00", 120, city_map)
        self.assertEqual(free["travel"]["congestion"], 1.0)

        jammed_map = _mini_map()
        for a, b in (("Alpha", "Beta"), ("Beta", "Gamma")):
            cm.set_edge_congestion(jammed_map, a, b, 2.0)
        agent = {"id": 1, "job": "工程师", "locations": {"current": "Alpha", "home": "Alpha"}}
        jammed = move_agent(agent, "Gamma", "通勤", "08:00", 120, jammed_map)
        self.assertGreater(jammed["travel"]["congestion"], 1.0)
        self.assertGreater(jammed["travel"]["minutes"], free["travel"]["minutes"])

    def test_staying_put_reports_free_flow(self):
        from gaworld.sim._location import move_agent

        agent = {"id": 1, "job": "工程师", "locations": {"current": "Alpha", "home": "Alpha"}}
        movement = move_agent(agent, "Alpha", "在家", "08:00", 30, _mini_map())
        self.assertEqual(movement["travel"]["congestion"], 1.0)

    def test_every_tick_is_recorded_congested_or_not(self):
        """A flat line of 1.0 is the finding that the roads never filled up."""
        ctx = _ctx({"enabled": True, "agents_represent": 100.0, "decay": 0.0})
        TrafficPlugin().setup(ctx)
        city_map = ctx.extras["city_map"]
        rows = []
        ctx.recorder.record = lambda table, data: rows.append((table, data))

        ctx.bus.emit("on_time_tick", day=1, time_str="08:00", city_map=city_map, agents=[])
        _run_tick(ctx, None, [_trip(["Alpha", "Beta"])] * 30, "08:30")
        ctx.bus.emit("on_time_tick", day=1, time_str="09:00", city_map=city_map, agents=[])

        self.assertEqual([table for table, _ in rows], ["traffic.tick"] * 3)
        quiet, _, busy = (data for _, data in rows)
        self.assertEqual(quiet["edges_loaded"], 0)
        self.assertEqual(quiet["congestion_max"], 1.0)
        self.assertEqual(busy["edges_loaded"], 1)
        self.assertGreater(busy["flow_pcu"], 0)
        self.assertGreater(busy["congestion_max"], 1.0)
        self.assertEqual(busy["busiest"][0]["edge"], cm._edge_key("Alpha", "Beta"))

    def test_nothing_is_recorded_while_the_layer_is_off(self):
        ctx = _ctx({"enabled": False})
        TrafficPlugin().setup(ctx)
        rows = []
        ctx.recorder.record = lambda table, data: rows.append(table)
        _run_tick(ctx, None, [_trip(["Alpha", "Beta"])] * 30, "08:00")
        ctx.bus.emit("on_time_tick", day=1, time_str="08:30",
                     city_map=ctx.extras["city_map"], agents=[])
        self.assertEqual(rows, [])


class TestPanelReader(unittest.TestCase):
    def test_absent_file_reads_as_off_not_as_clear_roads(self):
        from gaworld.apps import external_systems_api as api

        with unittest.mock.patch.object(api, "_ds") as ds:
            ds.return_value.RECORDS_DIR = tempfile.mkdtemp()
            self.assertEqual(api.traffic_runtime()["available"], False)

    def test_a_quiet_run_is_reported_as_never_congested(self):
        from gaworld.apps import external_systems_api as api

        tmp = tempfile.mkdtemp()
        with open(os.path.join(tmp, "traffic.tick.jsonl"), "w", encoding="utf-8") as fh:
            fh.write('{"_day": 1, "_time": "08:00", "edges_congested": 0, '
                     '"edges_loaded": 2, "flow_pcu": 3.0, "congestion_max": 1.0}\n')
            fh.write('{"_day": 1, "_time": "08:30", "edges_congested": 0, '
                     '"edges_loaded": 1, "flow_pcu": 1.0, "congestion_max": 1.0}\n')
        with unittest.mock.patch.object(api, "_ds") as ds:
            ds.return_value.RECORDS_DIR = tmp
            ds.return_value.REPO_ROOT = tmp
            report = api.traffic_runtime()
        self.assertTrue(report["available"])
        self.assertFalse(report["ever_congested"])
        self.assertEqual(report["tick_count"], 2)
        self.assertEqual(report["peak_congestion"], 1.0)


if __name__ == "__main__":
    unittest.main()


class TestTheSuiteLeavesNoTraceInOutput(unittest.TestCase):
    """Fixtures must not land in the repo's real run artifacts.

    ``Recorder`` defaults to ``output/records``, so a test that emits
    ``on_time_tick`` through a real kernel appends to the same file a real run
    writes. The traffic table had 378 fixture rows in it before this was
    caught — enough to look like data.
    """

    def test_the_recorder_writes_where_it_is_told(self):
        sandbox = tempfile.mkdtemp()
        ctx = _ctx({"enabled": True, "agents_represent": 100.0}, records_dir=sandbox)
        TrafficPlugin().setup(ctx)
        city_map = ctx.extras["city_map"]
        _run_tick(ctx, None, [_trip(["Alpha", "Beta"])] * 30, "08:00")
        ctx.bus.emit("on_time_tick", day=1, time_str="08:30", city_map=city_map, agents=[])
        ctx.recorder.close()

        written = os.path.join(sandbox, "traffic.tick.jsonl")
        self.assertTrue(os.path.exists(written), "the tick table should be here")
        repo_table = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "output", "records", "traffic.tick.jsonl")
        self.assertNotEqual(os.path.abspath(written), os.path.abspath(repo_table))
