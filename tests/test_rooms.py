"""Rooms: the indoor spatial tree in the simulation (``local_physical.rooms``).

Covers: the backend tree is the renderer's tree (blueprints and the
activity → slot rule compared against the JS files under node); the room
choice (visitors never in staff rooms, aliases, the home plugin's room wins);
one flat per household (citymap interiors, floors added when short, stable
when a household moves in); placement on ``agent.moved`` (sticky while it
fits, objects not shared, cleared on the road); encounters need the same
room; venue capacity per room (share of the floor plan, redirect, refusal
names the room, the admitted room is where the visitor lands); the trace
carries the room; and a real main-loop run with rooms on.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from gaworld.behavior.dynamic import detect_co_located_agents
from gaworld.kernel import ActionRequest, build_kernel
from gaworld.world import city_map as cm
from gaworld.world import spatial_tree as st
from gaworld.world.plugin import RoomsPlugin, VenueCapacityPlugin

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _map(cafe_capacity=10):
    content = (
        "# City Map\n"
        "@node: Tower | kind=hub | category=residential | x=0.0 | y=0.0 | capacity=100\n"
        "@node: Cafe | kind=hub | category=leisure | x=1.0 | y=0.0 | capacity=10\n"
        "@node: CafeB | kind=hub | category=leisure | x=2.0 | y=0.0 | capacity=10\n"
        "@node: Office | kind=hub | category=industry | x=3.0 | y=0.0 | capacity=10\n"
        "\n- City: Demo\n  - Hub: Tower\n  - Hub: Cafe\n  - Hub: CafeB\n  - Hub: Office\n"
    )
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "m.md")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        city_map = cm.load_city_map(path)
    for node in city_map["nodes"].values():
        node["open_min"], node["close_min"] = None, None
        node["capacity"] = cafe_capacity if node["category"] == "leisure" else 100
    city_map["interiors"] = {
        "Tower": {
            "floors": [
                {"name": "1F", "units": ["1A", "1B"]},
                {"name": "2F", "units": ["2A", "2B"]},
            ]
        }
    }
    return city_map


def _resident(agent_id, household=None, *, at="Tower", home="Tower", work="Office"):
    agent = {"id": agent_id, "locations": {"current": at, "home": home, "workplace": work}}
    if household:
        agent["ext"] = {"family": {"household_id": household}}
    return agent


class _World:
    def __init__(self, test, agents, *, rooms=True, capacity=False, cafe_capacity=10):
        self.records = tempfile.mkdtemp()
        test.addCleanup(shutil.rmtree, self.records, True)
        self.ctx = build_kernel(
            {
                "local_physical": {
                    "rooms": {"enabled": rooms},
                    "capacity": {"enabled": capacity, "agents_represent": 1.0},
                },
                "random_seed": 7,
                "records": {"output_dir": self.records},
            },
            load_entry_points=False,
        )
        self.city_map = _map(cafe_capacity)
        self.ctx.extras["city_map"] = self.city_map
        VenueCapacityPlugin().setup(self.ctx)
        self.plugin = RoomsPlugin()
        self.plugin.setup(self.ctx)
        self.agents = agents
        self.ctx.set_agents(agents)
        self.test = test
        test.assertEqual(self.ctx.bus.emit("agents.built", agents=agents, config={}), [])

    def tick(self, time_str="12:00"):
        self.ctx.clock.advance(time_str, 0)
        self.test.assertEqual(
            self.ctx.bus.emit(
                "on_time_tick", day=1, time_str=time_str, city_map=self.city_map, agents=self.agents
            ),
            [],
        )

    def moved(self, agent, activity):
        self.test.assertEqual(
            self.ctx.bus.emit(
                "agent.moved", agent=agent, activity=activity, city_map=self.city_map, day=1, time_str="12:00"
            ),
            [],
        )
        return agent["locations"].get("room")

    def go(self, agent, to, activity):
        verdict = self.ctx.controller.validate(
            ActionRequest(agent["id"], "move", {"to": to, "activity": activity}), self.ctx
        )
        if not verdict.allowed:
            return None, verdict.reason
        return (verdict.rewritten.params["to"] if verdict.rewritten is not None else to), ""


def _node_json(script):
    result = subprocess.run(["node", "-e", script], cwd=REPO_ROOT, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise AssertionError(result.stderr)
    return json.loads(result.stdout)


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class SameTreeAsTheRendererTest(unittest.TestCase):
    def test_blueprints_match_spatial_tree_js(self):
        js = _node_json(
            'const S=require("./site/simviz/spatial-tree.js");console.log(JSON.stringify(S.BLUEPRINTS))'
        )
        for key, bp in js.items():
            py = st.BLUEPRINTS[st.BLUEPRINT_ALIASES.get(key, key)]
            self.assertEqual(py["category"], bp["category"], key)
            self.assertEqual(bool(py.get("outdoor")), bool(bp.get("outdoor")), key)
            self.assertEqual([r["name"] for r in py["rooms"]], [r["name"] for r in bp["rooms"]], key)
            for pr, jr in zip(py["rooms"], bp["rooms"], strict=True):
                self.assertEqual((pr["type"], pr["door"]), (jr["type"], jr["door"]), (key, pr["name"]))
                for f in "xywh":
                    self.assertAlmostEqual(pr[f], jr[f], places=12)
                self.assertEqual(len(pr["objects"]), len(jr["objects"]), (key, pr["name"]))
                for po, jo in zip(pr["objects"], jr["objects"], strict=True):
                    self.assertEqual(
                        (po["name"], po["kind"], po["slot"]), (jo["name"], jo["kind"], jo["slot"])
                    )
                    for f in "xywh":
                        self.assertAlmostEqual(po[f], jo[f], places=12)

    def test_layouts_are_chosen_like_the_renderer_does(self):
        samples = [
            {"label": "Riverside Park", "category": "leisure"},
            {"label": "Park Cafe", "category": "leisure"},
            {"label": "Park View Apartments", "category": "residential"},
            {"label": "中山hotel"},
            {"label": "城西诊所", "category": "medical"},
            {"label": "X", "amenity": "pharmacy"},
            {"label": "X", "tags": {"shop": "bakery"}},
            {"label": "X", "office": "yes"},
            {"label": "X", "building_type": "house"},
            {"label": "X", "interior_type": "gym", "amenity": "cafe"},
            {"label": "Lakeview Tower", "category": "residential"},
            {"label": "Unknown Spot"},
            {"label": "龙湖杭州滨江天街", "category": "commerce"},
            {"label": "南星街道", "category": "residential"},
            {"label": "Café Lumière"},
            {"label": "X", "amenity": "cafe"},
            {"id": "CafeB", "category": "leisure"},
            {"label": "浙江大学", "category": "education"},
            {"label": "Main St Station"},
            {},
        ]
        js = _node_json(
            'const S=require("./site/simviz/spatial-tree.js");'
            f"console.log(JSON.stringify({json.dumps(samples, ensure_ascii=False)}.map(n => S.layoutFor(n).type)))"
        )
        self.assertEqual([st.layout_type(n) for n in samples], js)

    def test_activity_slots_match_the_dashboard_indoor_view(self):
        samples = [
            "睡觉",
            "做饭",
            "咖啡馆避雨办公",
            "处理待办",
            "洗澡",
            "上班",
            "超市采购",
            "午休 nap",
            "去健身房锻炼",
            "和朋友吃饭",
            "看电视",
            "上课",
            "刷牙",
            "开会",
            "看病",
            "读书",
            "弹钢琴",
            "上厕所",
            "Shopping",
            "work",
            "休息一下",
            "",
        ]
        js = _node_json(
            'const I=require("./site/dashboard/indoor-view.js");'
            f"console.log(JSON.stringify({json.dumps(samples)}.map(I.activitySlot)))"
        )
        self.assertEqual([st.activity_slot(s) for s in samples], js)


class TreeTest(unittest.TestCase):
    def test_room_shares_cover_each_plan(self):
        for key, bp in st.BLUEPRINTS.items():
            total = sum(st.room_share(key, r["name"]) for r in bp["rooms"])
            self.assertAlmostEqual(total, 1.0, places=6, msg=key)

    def test_store_and_index(self):
        tree = st.build_building_tree({"label": "Maple Court", "category": "residential"})
        self.assertEqual(tree.sector, "Maple Court")
        self.assertIn("Kitchen", tree.arena_names("Maple Court"))
        stove = tree.locate("stove")
        self.assertEqual((stove["arena"], stove["slot"]), ("Kitchen", "cook"))
        self.assertEqual(tree.resolve(stove["address"]), stove)
        self.assertEqual(tree.arena_for_activity("Maple Court", "cook"), "Kitchen")
        self.assertEqual(tree.arena_for_activity("Maple Court", "nothing"), "Bedroom 1")
        # duplicate furniture gets unique addresses
        self.assertIn("chair 2", tree.object_names("Maple Court", "Kitchen"))
        rect = tree.object_building_rect(stove)
        self.assertTrue(0 <= rect["x"] <= 1 and 0 <= rect["y"] <= 1)
        self.assertTrue(st.build_building_tree({"label": "Pocket Park", "category": "leisure"}).outdoor)
        self.assertEqual(
            st.build_building_tree({"label": "Blue Bottle", "amenity": "cafe"}).layout_label, "咖啡馆"
        )

    def test_visitors_never_get_staff_rooms(self):
        self.assertEqual(st.rooms_for("leisure", "cook"), ["Seating"])
        self.assertIn("Kitchen", st.rooms_for("leisure", "cook", staff=True))
        self.assertNotIn("Storeroom", st.rooms_for("commerce", "shop"))
        self.assertIn("Storeroom", st.rooms_for("commerce", "shop", staff=True))

    def test_the_people_who_work_here_fall_back_to_the_staff_room(self):
        self.assertEqual(st.rooms_for("leisure", None, staff=True), ["Counter", "Seating"])
        self.assertEqual(st.rooms_for("leisure", None), ["Seating"])

    def test_aliases_and_the_home_plugins_room(self):
        self.assertIn("Ward A", st.rooms_for("medical", "sleep"))
        self.assertEqual(st.rooms_for("leisure", "order"), ["Counter", "Seating"])
        self.assertEqual(st.rooms_for("residential", "eat", resident=True, home_type="kitchen"), ["Kitchen"])


class FlatTest(unittest.TestCase):
    def test_flats_come_from_the_citymap_and_floors_are_added_when_short(self):
        interior = {"floors": [{"name": "1F", "units": ["1A", "1B"]}, {"name": "2F", "units": ["2A", "2B"]}]}
        self.assertEqual(st.building_units(interior, 3), ["1A", "1B", "2A", "2B"])
        self.assertEqual(st.building_units(interior, 6), ["1A", "1B", "2A", "2B", "3A", "3B"])
        # whole floors are added, four flats a floor when the citymap lists none
        self.assertEqual(st.building_units(None, 5), ["1A", "1B", "1C", "1D", "2A", "2B", "2C", "2D"])

    def test_each_household_gets_its_own_flat_and_keeps_it(self):
        first = st.assign_units(["h1", "h2", "h3"], None)
        self.assertEqual(len(set(first.values())), 3)
        self.assertEqual(first, st.assign_units(["h3", "h1", "h2"], None))
        later = st.assign_units(["h4"], None, first)
        self.assertEqual({k: later[k] for k in first}, first)
        self.assertNotIn(later["h4"], first.values())

    def test_household_members_share_a_flat_and_neighbours_do_not(self):
        agents = [_resident(1, "H1"), _resident(2, "H1"), _resident(3, "H2"), _resident(4)]
        world = _World(self, agents)
        flats = [world.moved(a, "看电视")["unit"] for a in agents]
        self.assertEqual(flats[0], flats[1])
        self.assertEqual(len({flats[0], flats[2], flats[3]}), 3)
        self.assertTrue(set(flats) <= {"1A", "1B", "2A", "2B"})

    def test_apartment_blocks_have_flats_too_and_other_homes_do_not(self):
        self.assertTrue(st.is_residential("apartment"))
        self.assertFalse(st.is_residential("mixed"))

    def test_a_household_that_moves_in_later_gets_a_flat_of_its_own(self):
        agents = [_resident(i, f"H{i}") for i in range(1, 5)]
        world = _World(self, agents)
        newcomer = _resident(9, "H9")
        flat = world.moved(newcomer, "看电视")["unit"]
        self.assertIn(flat, {"3A", "3B"})  # the building's four flats were taken: a floor is added


class PlacementTest(unittest.TestCase):
    def test_off_by_default_places_nobody(self):
        world = _World(self, [_resident(1)], rooms=False)
        self.assertIsNone(world.moved(world.agents[0], "睡觉"))
        self.assertFalse(hasattr(world.plugin, "_flats"))

    def test_the_room_follows_the_activity_and_beds_are_not_shared(self):
        a, b = _resident(1, "H1"), _resident(2, "H1")
        world = _World(self, [a, b])
        world.tick("23:00")
        ra, rb = world.moved(a, "睡觉"), world.moved(b, "睡觉")
        self.assertEqual((ra["arena"], ra["object"]), ("Bedroom 1", "bed"))
        self.assertEqual((rb["arena"], rb["object"]), ("Bedroom 2", "bed"))
        world.tick("07:00")
        self.assertEqual(world.moved(a, "做饭")["arena"], "Kitchen")

    def test_a_resident_stays_put_while_the_room_still_fits(self):
        a = _resident(1, "H1", at="Cafe")
        world = _World(self, [a])
        self.assertEqual(world.moved(a, "点一杯咖啡")["arena"], "Counter")
        world.tick("12:30")
        # the counter does not host eating: off to the seating area
        self.assertEqual(world.moved(a, "吃午饭")["arena"], "Seating")
        world.tick("12:45")
        self.assertEqual(world.moved(a, "再点一杯咖啡")["arena"], "Seating")  # order may use Seating

    def test_visitors_and_staff_at_a_cafe(self):
        guest = _resident(1, "H1", at="Cafe")
        barista = _resident(2, "H2", at="Cafe", work="Cafe")
        world = _World(self, [guest, barista])
        self.assertEqual(world.moved(guest, "想做饭")["arena"], "Seating")
        self.assertEqual(world.moved(barista, "上班")["arena"], "Counter")

    def test_the_home_plugins_room_wins_at_home(self):
        a = _resident(1, "H1")
        a["_home_observation"] = {"is_at_home": True, "current_room": {"key": "study"}}
        world = _World(self, [a])
        self.assertEqual(world.moved(a, "发呆")["arena"], "Study")

    def test_on_the_road_there_is_no_room(self):
        a = _resident(1, "H1")
        world = _World(self, [a])
        world.moved(a, "看电视")
        a["locations"]["in_transit"] = True
        self.assertIsNone(world.moved(a, "去咖啡馆"))


class EncounterTest(unittest.TestCase):
    def test_neighbours_at_home_do_not_meet_but_a_household_in_one_room_does(self):
        me, partner, neighbour = _resident(1, "H1"), _resident(2, "H1"), _resident(3, "H2")
        world = _World(self, [me, partner, neighbour])
        for agent in (me, partner, neighbour):
            world.moved(agent, "看电视")
        met = detect_co_located_agents(me, world.agents, {a["id"]: a for a in world.agents})
        self.assertEqual([a["id"] for a in met], [2])

    def test_different_rooms_of_one_place_do_not_meet(self):
        guest, barista = _resident(1, "H1", at="Cafe"), _resident(2, "H2", at="Cafe", work="Cafe")
        world = _World(self, [guest, barista])
        world.moved(guest, "吃饭")
        world.moved(barista, "上班")
        self.assertEqual(detect_co_located_agents(guest, world.agents, {}), [])

    def test_without_rooms_the_place_is_enough(self):
        me, neighbour = _resident(1, "H1"), _resident(3, "H2")
        self.assertEqual([a["id"] for a in detect_co_located_agents(me, [me, neighbour], {})], [3])
        # a room left over from somewhere else does not count
        me["locations"]["room"] = {"node": "Cafe", "unit": "", "arena": "Seating"}
        self.assertEqual([a["id"] for a in detect_co_located_agents(me, [me, neighbour], {})], [3])


class CapacityByRoomTest(unittest.TestCase):
    def _world(self, n, **kw):
        agents = [_resident(i, f"H{i}") for i in range(1, n + 1)]
        world = _World(self, agents, capacity=True, **kw)
        world.tick()
        return world

    def test_a_dining_room_fills_on_its_share_of_the_floor_plan(self):
        # Seating is 45% of a café: capacity 10 → 4.5 people, so four diners.
        world = self._world(6)
        dests = [world.go(a, "Cafe", "吃午饭")[0] for a in world.agents[:5]]
        self.assertEqual(dests, ["Cafe"] * 4 + ["CafeB"])
        self.assertEqual(world.agents[4]["locations"]["room_intent"], {"node": "CafeB", "arena": "Seating"})

    def test_another_activity_still_finds_room(self):
        world = self._world(6)
        for a in world.agents[:4]:
            world.go(a, "Cafe", "吃午饭")
        # the counter (22%) still takes coffee orders
        self.assertEqual(world.go(world.agents[4], "Cafe", "买咖啡")[0], "Cafe")
        self.assertEqual(world.agents[4]["locations"]["room_intent"]["arena"], "Counter")

    def test_refusal_names_the_full_room(self):
        world = self._world(3, cafe_capacity=2)  # Seating holds 0.9 people: nobody
        dest, reason = world.go(world.agents[0], "Cafe", "吃午饭")
        self.assertIsNone(dest)
        self.assertIn("就餐区", reason)

    def test_the_admitted_room_is_where_the_visitor_lands(self):
        world = self._world(2)
        a = world.agents[0]
        world.go(a, "Cafe", "买咖啡")
        a["locations"]["current"] = "Cafe"
        self.assertEqual(world.moved(a, "买咖啡")["arena"], "Counter")
        self.assertNotIn("room_intent", a["locations"])

    def test_people_inside_and_on_the_way_count_in_their_rooms(self):
        world = self._world(6)
        inside = world.agents[:3]
        for a in inside:
            a["locations"]["current"] = "Cafe"
            world.moved(a, "吃饭")
        on_way = world.agents[3]
        on_way["locations"].update(
            in_transit=True, destination="Cafe", room_intent={"node": "Cafe", "arena": "Seating"}
        )
        world.tick("12:15")
        # 4 already count in Seating: the next diner is sent on
        self.assertEqual(world.go(world.agents[4], "Cafe", "吃饭")[0], "CafeB")


class TraceTest(unittest.TestCase):
    def test_the_step_payload_carries_the_room_only_where_the_resident_is(self):
        from gaworld.apps.visualizer import build_agent_step_payload

        agent = _resident(1, "H1")
        args = {
            "time_str": "12:00",
            "location": "Tower",
            "resolved_location": "Tower",
            "target_location": "",
            "scheduled_activity": "",
            "activity": "",
            "action": "",
            "outcome": "",
            "perception": "",
            "plan": "",
            "reflection": "",
        }
        self.assertNotIn("room", build_agent_step_payload(agent, **args))
        agent["locations"]["room"] = {"node": "Tower", "unit": "1A", "arena": "Kitchen", "object": "stove"}
        self.assertEqual(
            build_agent_step_payload(agent, **args)["room"],
            {"node": "Tower", "unit": "1A", "arena": "Kitchen", "object": "stove"},
        )
        agent["locations"]["current"] = "Cafe"
        self.assertNotIn("room", build_agent_step_payload(agent, **args))


class MainLoopTest(unittest.TestCase):
    """Rooms on inside the real tick loop: every step places the resident."""

    def test_residents_are_placed_every_step(self):
        import generative_city_sim as sim
        from gaworld.settings import CONFIG
        from tests.fixtures import scratch_cwd
        from tests.fixtures.mock_llm import install

        scratch_cwd.enter(self)
        records = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, records, True)
        touched = (
            "agent_ids",
            "sim_days",
            "stateful",
            "simulate_realtime",
            "seconds_per_day",
            "news",
            "intervention",
            "external_environment_service",
            "distributed",
            "visualization",
            "life_events",
            "external_rag",
            "records",
            "local_physical",
        )
        originals = {key: CONFIG[key] for key in touched if key in CONFIG}

        def restore():
            for key in touched:
                if key in originals:
                    CONFIG[key] = originals[key]
                else:
                    CONFIG.pop(key, None)

        self.addCleanup(restore)
        CONFIG.update(
            agent_ids=[4, 5], sim_days=1, stateful=False, simulate_realtime=False, seconds_per_day=1
        )
        CONFIG["records"] = {"output_dir": records}
        CONFIG["local_physical"] = {**CONFIG.get("local_physical", {}), "rooms": {"enabled": True}}
        for key in (
            "news",
            "intervention",
            "external_environment_service",
            "distributed",
            "visualization",
            "life_events",
        ):
            if isinstance(CONFIG.get(key), dict):
                CONFIG[key] = {**CONFIG[key], "enabled": False}
        if isinstance(CONFIG.get("news"), dict):
            CONFIG["news"]["info_seek"] = {**CONFIG["news"].get("info_seek", {}), "enabled": False}
        if isinstance(CONFIG.get("external_rag"), dict):
            CONFIG["external_rag"] = {
                **CONFIG["external_rag"],
                "bootstrap": {**CONFIG["external_rag"].get("bootstrap", {}), "enabled": False},
            }
        for name, value in (
            ("AGENT_IDS", [4, 5]),
            ("SIM_DAYS", 1),
            ("STATEFUL", False),
            ("SIMULATE_REALTIME", False),
            ("SECONDS_PER_DAY", 1),
            ("NEWS_ENABLED", False),
            ("INTERVENTION_ENABLED", False),
            ("HUMAN_REALISM_ENABLED", False),
            ("VISUALIZATION_ENABLED", False),
            ("LIFE_EVENTS_ENABLED", False),
            ("LONG_RUN_ENABLED", False),
        ):
            patcher = mock.patch.object(sim, name, value, create=True)
            patcher.start()
            self.addCleanup(patcher.stop)

        placed = []
        original = RoomsPlugin._place

        def spy(plugin, hook_ctx):
            original(plugin, hook_ctx)
            room = (hook_ctx["agent"].get("locations") or {}).get("room")
            if room:
                placed.append((hook_ctx["agent"]["id"], dict(room)))

        with mock.patch.object(RoomsPlugin, "_place", spy), install():
            sim.run_simulation()

        self.assertTrue(placed, "nobody was placed in a room")
        self.assertEqual({agent_id for agent_id, _ in placed}, {4, 5})
        for _agent_id, room in placed:
            self.assertTrue(room["arena"])
            self.assertTrue(room["node"])


if __name__ == "__main__":
    unittest.main()
