"""Venue capacity: a full place turns people away (proposal 2026-10-03).

Covers the gates in the proposal §4: off means nothing changes; room admits;
full redirects to the nearest same-category venue that is open and has room,
else refuses; homes / work / hospitals are never capped; a resident already
inside or still on the road is not re-admitted; a synchronized surge is held
at capacity (the reason for counting within the tick); and the per-tick
shuffle makes who gets the last seat a seeded draw, not the lowest id.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest import mock

import pytest

from gaworld.kernel import ActionRequest, build_kernel
from gaworld.world import city_map as cm
from gaworld.world import venue_capacity as vc
from gaworld.world.plugin import VenueCapacityPlugin


def _map(shop_capacity=2):
    content = (
        "# City Map\n"
        "@node: Home | kind=hub | category=residential | x=0.0 | y=0.0 | capacity=1\n"
        f"@node: ShopA | kind=hub | category=commerce | x=1.0 | y=0.0 | capacity={shop_capacity}\n"
        f"@node: ShopB | kind=hub | category=commerce | x=2.0 | y=0.0 | capacity={shop_capacity}\n"
        "@node: Office | kind=hub | category=industry | x=3.0 | y=0.0 | capacity=1\n"
        "@node: Clinic | kind=hub | category=medical | x=4.0 | y=0.0 | capacity=1\n"
        "\n- City: Demo\n  - Hub: Home\n  - Hub: ShopA\n  - Hub: ShopB\n  - Hub: Office\n  - Hub: Clinic\n"
    )
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "m.md")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        city_map = cm.load_city_map(path)
    # Keep the shops open all day so opening hours never decide a test, and
    # pin capacities (the loader scales hubs by 1.5).
    for node in city_map["nodes"].values():
        node["open_min"], node["close_min"] = None, None
        node["capacity"] = shop_capacity if node["category"] == "commerce" else 1
    return city_map


def _agents(n, where="Home"):
    return [{"id": i, "locations": {"current": where, "home": "Home"}} for i in range(n)]


class _World:
    def __init__(self, test, *, capacity=None, traffic=None, shop_capacity=2, n=6, enabled=True):
        self.records = tempfile.mkdtemp()
        cap = {"enabled": enabled, **(capacity or {})}
        self.ctx = build_kernel(
            {"local_physical": {"capacity": cap}, "traffic": traffic or {}, "random_seed": 7,
             "records": {"output_dir": self.records}},
            load_entry_points=False,
        )
        self.ctx.extras["city_map"] = _map(shop_capacity)
        VenueCapacityPlugin().setup(self.ctx)
        self.agents = _agents(n)
        self.ctx.set_agents(self.agents)

    def tick(self, time_str="12:00", day=1):
        self.ctx.clock.advance(time_str, 0)
        self.ctx.bus.emit("on_time_tick", day=day, time_str=time_str,
                          city_map=self.ctx.extras["city_map"], agents=self.agents)

    def go(self, agent_id, to):
        return self.ctx.controller.validate(ActionRequest(agent_id, "move", {"to": to}), self.ctx)

    def rows(self, table):
        path = os.path.join(self.records, f"{table}.jsonl")
        if not os.path.exists(path):
            return []
        with open(path, encoding="utf-8") as fh:
            return [json.loads(line) for line in fh if line.strip()]


def _dest(verdict, asked):
    if not verdict.allowed:
        return None
    return verdict.rewritten.params["to"] if verdict.rewritten is not None else asked


class GateTest(unittest.TestCase):
    def test_off_by_default_changes_nothing(self):
        world = _World(self, enabled=False, shop_capacity=1)
        world.tick()
        self.assertEqual([_dest(world.go(i, "ShopA"), "ShopA") for i in range(6)], ["ShopA"] * 6)
        order = world.ctx.bus.filter("tick.agent_order", world.agents, day=1, time_str="12:00")
        self.assertIs(order, world.agents)

    def test_room_then_redirect_then_refuse(self):
        world = _World(self, shop_capacity=2)
        world.tick()
        got = [_dest(world.go(i, "ShopA"), "ShopA") for i in range(5)]
        self.assertEqual(got, ["ShopA", "ShopA", "ShopB", "ShopB", None])
        refused = world.go(5, "ShopA")
        self.assertFalse(refused.allowed)
        self.assertIn("已经满了", refused.reason)
        self.assertEqual([(r["from"], r["to"]) for r in world.rows("venue.redirect")],
                         [("ShopA", "ShopB"), ("ShopA", "ShopB")])
        self.assertEqual(len(world.rows("action.denied")), 2)

    def test_redirect_can_be_switched_off(self):
        world = _World(self, capacity={"redirect_top_k": 0}, shop_capacity=1)
        world.tick()
        self.assertEqual([_dest(world.go(i, "ShopA"), "ShopA") for i in range(2)], ["ShopA", None])

    def test_homes_work_and_hospitals_are_never_capped(self):
        world = _World(self, shop_capacity=1)
        world.tick()
        for place in ("Home", "Office", "Clinic"):
            with self.subTest(place=place):
                self.assertTrue(all(world.go(i, place).allowed for i in range(6)))

    def test_people_inside_or_on_the_way_are_not_admitted_twice(self):
        world = _World(self, shop_capacity=2)
        world.agents[0]["locations"] = {"current": "ShopA"}
        world.agents[1]["locations"] = {"current": "Home", "in_transit": True, "destination": "ShopA"}
        world.tick()
        self.assertTrue(world.go(0, "ShopA").allowed)   # already inside
        self.assertTrue(world.go(1, "ShopA").allowed)   # on the road: move_agent ignores it
        # Both still take a place: the shop is full for everyone else.
        self.assertEqual(_dest(world.go(2, "ShopA"), "ShopA"), "ShopB")

    def test_a_synchronized_surge_is_held_at_capacity(self):
        world = _World(self, capacity={"redirect_top_k": 0}, shop_capacity=20, n=30)
        world.tick()
        admitted = sum(world.go(i, "ShopA").allowed for i in range(30))
        self.assertEqual(admitted, 20)

    def test_one_resident_stands_for_many_people(self):
        # Inherits the congestion layer's knob: 10 people each, capacity 20.
        world = _World(self, traffic={"agents_represent": 10}, capacity={"redirect_top_k": 0},
                       shop_capacity=20)
        world.tick()
        self.assertEqual(sum(world.go(i, "ShopA").allowed for i in range(6)), 2)
        # An explicit value wins over the inherited one.
        world = _World(self, traffic={"agents_represent": 10},
                       capacity={"redirect_top_k": 0, "agents_represent": 1}, shop_capacity=20)
        world.tick()
        self.assertEqual(sum(world.go(i, "ShopA").allowed for i in range(6)), 6)

    def test_the_ledger_starts_fresh_every_tick(self):
        world = _World(self, capacity={"redirect_top_k": 0}, shop_capacity=1)
        world.tick("12:00")
        self.assertTrue(world.go(0, "ShopA").allowed)
        self.assertFalse(world.go(1, "ShopA").allowed)
        world.tick("12:30")  # #0 never actually moved in this test
        self.assertTrue(world.go(1, "ShopA").allowed)


class FairnessTest(unittest.TestCase):
    """Counting within a tick depends on who goes first; the seeded shuffle
    turns that into a draw instead of a privilege of the lowest ids."""

    def _admissions(self, *, shuffle):
        counts = dict.fromkeys(range(10), 0)
        world = _World(self, capacity={"redirect_top_k": 0}, shop_capacity=5, n=10)
        for tick in range(60):
            time_str = f"{8 + tick // 6:02d}:{(tick % 6) * 10:02d}"
            world.tick(time_str)
            order = world.ctx.bus.filter("tick.agent_order", world.agents, day=1, time_str=time_str)
            for agent in (order if shuffle else world.agents):
                if world.go(agent["id"], "ShopA").allowed:
                    counts[agent["id"]] += 1
        return counts

    def test_the_last_seat_is_a_draw_not_an_id_privilege(self):
        fixed = self._admissions(shuffle=False)
        self.assertEqual([fixed[i] for i in range(10)], [60] * 5 + [0] * 5)
        drawn = self._admissions(shuffle=True)
        self.assertTrue(all(10 <= drawn[i] <= 50 for i in range(10)), drawn)
        low, high = sum(drawn[i] for i in range(5)), sum(drawn[i] for i in range(5, 10))
        self.assertLess(abs(low - high), 60, drawn)

    def test_the_draw_repeats_under_the_same_seed(self):
        agents = _agents(12)
        first = [a["id"] for a in vc.shuffled(agents, 7, 1, "12:00")]
        self.assertEqual(first, [a["id"] for a in vc.shuffled(agents, 7, 1, "12:00")])
        self.assertNotEqual(first, [a["id"] for a in vc.shuffled(agents, 7, 1, "12:30")])
        self.assertNotEqual(first, [a["id"] for a in vc.shuffled(agents, 8, 1, "12:00")])


class HelperTest(unittest.TestCase):
    def test_full_is_about_the_represented_crowd(self):
        self.assertFalse(vc.is_full(1, 2, 1.0))
        self.assertTrue(vc.is_full(2, 2, 1.0))
        self.assertFalse(vc.is_full(1, 20, 10.0))     # 10 inside + 10 more = 20: fits
        self.assertTrue(vc.is_full(2, 20, 10.0))
        self.assertFalse(vc.is_full(99, 0, 1.0))      # unknown capacity: never full
        self.assertFalse(vc.is_full(99, 10, 0.0))     # nobody represented: never full

    def test_start_counts_include_trips_under_way(self):
        agents = [
            {"locations": {"current": "A"}},
            {"locations": {"current": "B", "in_transit": True, "destination": "A"}},
            {"locations": {"current": "B"}},
            {"locations": {}},
        ]
        self.assertEqual(vc.start_counts(agents, lambda loc: loc), {"A": 2, "B": 1})


@pytest.mark.slow
class MainLoopTest(unittest.TestCase):
    """The validator and the order filter inside the real tick loop.

    Every category capped and one resident standing for a million people:
    every trip to anywhere new is refused, so the residents never leave home,
    and each refusal is audited with the capacity reason.
    """

    def test_a_full_city_keeps_everyone_home(self):
        import generative_city_sim as sim
        from gaworld.settings import CONFIG
        from tests.fixtures import scratch_cwd
        from tests.fixtures.mock_llm import install

        scratch_cwd.enter(self)
        records = tempfile.mkdtemp()
        touched = ("agent_ids", "sim_days", "stateful", "simulate_realtime", "seconds_per_day",
                   "news", "intervention", "external_environment_service", "distributed",
                   "visualization", "life_events", "external_rag", "records", "local_physical")
        originals = {key: CONFIG[key] for key in touched if key in CONFIG}

        def restore():
            for key in touched:
                if key in originals:
                    CONFIG[key] = originals[key]
                else:
                    CONFIG.pop(key, None)

        self.addCleanup(restore)
        CONFIG.update(agent_ids=[4, 5], sim_days=1, stateful=False, simulate_realtime=False,
                      seconds_per_day=1)
        CONFIG["records"] = {"output_dir": records}
        CONFIG["local_physical"] = {**CONFIG.get("local_physical", {}), "capacity": {
            "enabled": True, "agents_represent": 1_000_000, "redirect_top_k": 4,
            "categories": sorted(cm.CATEGORY_LANDUSE),
        }}
        for key in ("news", "intervention", "external_environment_service", "distributed",
                    "visualization", "life_events"):
            if isinstance(CONFIG.get(key), dict):
                CONFIG[key] = {**CONFIG[key], "enabled": False}
        if isinstance(CONFIG.get("news"), dict):
            CONFIG["news"]["info_seek"] = {**CONFIG["news"].get("info_seek", {}), "enabled": False}
        if isinstance(CONFIG.get("external_rag"), dict):
            CONFIG["external_rag"] = {**CONFIG["external_rag"],
                                      "bootstrap": {**CONFIG["external_rag"].get("bootstrap", {}),
                                                    "enabled": False}}
        for name, value in (("AGENT_IDS", [4, 5]), ("SIM_DAYS", 1), ("STATEFUL", False),
                            ("SIMULATE_REALTIME", False), ("SECONDS_PER_DAY", 1),
                            ("NEWS_ENABLED", False), ("INTERVENTION_ENABLED", False),
                            ("HUMAN_REALISM_ENABLED", False), ("VISUALIZATION_ENABLED", False),
                            ("LIFE_EVENTS_ENABLED", False), ("LONG_RUN_ENABLED", False)):
            patcher = mock.patch.object(sim, name, value, create=True)
            patcher.start()
            self.addCleanup(patcher.stop)

        with install():
            sim.run_simulation()

        path = os.path.join(records, "action.denied.jsonl")
        self.assertTrue(os.path.exists(path), "no trip was refused")
        with open(path, encoding="utf-8") as fh:
            rows = [json.loads(line) for line in fh if line.strip()]
        self.assertTrue(rows and all("已经满了" in row["reason"] for row in rows))
        self.assertEqual({row["agent_id"] for row in rows}, {4, 5})


if __name__ == "__main__":
    unittest.main()
