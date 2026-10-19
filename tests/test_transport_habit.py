"""Habitual transport mode: a usual way of getting around, now and then broken.

The map used throughout (``_metro_map``): West End (0,0), Midtown (3,0),
East End (6,0) and Outpost (3,9); one metro line West End > East End.
"""

from __future__ import annotations

import copy
import random
import unittest
from unittest import mock

from gaworld.world import mobility
from gaworld.world.city_map import choose_transport_mode, travel_plan
from tests.test_location_system import _metro_map


def _resident(home="Midtown", work="Outpost", **fields):
    agent = {
        "id": 1,
        "age": 35,
        "job": "工程师",
        "daily_life": "",
        "personality": "",
        "has_car": False,
        "has_two_wheeler": True,
        "locations": {"home": home, "workplace": work, "current": home},
    }
    agent.update(fields)
    return agent


class TestDefaultModeFollowsCircumstances(unittest.TestCase):
    def setUp(self):
        self.city_map = _metro_map()

    def _default(self, **kw):
        return mobility.assign_default_mode(_resident(**kw), self.city_map)

    def test_an_ordinary_resident_keeps_the_city_models_commute_mode(self):
        agent = _resident(home="West End", work="East End")
        expected = choose_transport_mode(agent, self.city_map, "West End", "East End")[0]
        self.assertEqual(mobility.assign_default_mode(agent, self.city_map), expected)
        self.assertEqual(agent["default_transport"], expected)

    def test_a_courier_rides_the_e_bike(self):
        self.assertEqual(self._default(home="West End", work="Midtown", job="外卖骑手"), "e-bike")

    def test_a_professional_driver_drives(self):
        self.assertEqual(self._default(job="网约车司机", has_car=True), "car")

    def test_a_car_owner_drives_a_long_commute(self):
        self.assertEqual(self._default(has_car=True), "car")

    def test_an_elderly_car_owner_takes_the_bus_instead(self):
        self.assertEqual(self._default(has_car=True, age=72), "bus")

    def test_someone_who_likes_walking_walks_when_it_is_walkable(self):
        self.assertEqual(self._default(home="Midtown", work="West End", daily_life="每天散步"), "walk")

    def test_a_low_carbon_car_owner_leaves_the_car(self):
        self.assertEqual(self._default(has_car=True, values="低碳环保"), "bus")

    def test_no_commute_means_a_neighbourhood_errand(self):
        self.assertEqual(self._default(work="Midtown"), "e-bike")
        self.assertEqual(self._default(work="Midtown", has_two_wheeler=False), "walk")

    def test_a_habit_is_never_something_the_resident_cannot_take(self):
        """A courier with no two-wheeler, a driver with no car: no override."""
        self.assertNotEqual(
            self._default(job="快递员", has_two_wheeler=False, home="West End", work="Midtown"), "e-bike"
        )
        self.assertNotEqual(self._default(job="出租车司机"), "car")

    def test_the_same_resident_always_gets_the_same_habit(self):
        self.assertEqual(self._default(has_car=True), self._default(has_car=True))


class TestTripMode(unittest.TestCase):
    def _agent(self, habit="bus", **fields):
        return {"default_transport": habit, "has_car": False, "has_two_wheeler": False, **fields}

    def test_the_habit_is_used_when_it_fits(self):
        self.assertEqual(mobility.trip_mode(self._agent(), "walk", 2.0, False), ("bus", "habit"))

    def test_a_very_short_trip_follows_the_model(self):
        self.assertEqual(mobility.trip_mode(self._agent(), "walk", 0.3, False), ("walk", "model"))

    def test_a_habit_out_of_reach_follows_the_model(self):
        self.assertEqual(mobility.trip_mode(self._agent("metro"), "bus", 5.0, False), ("bus", "model"))
        self.assertEqual(mobility.trip_mode(self._agent("walk"), "bus", 6.0, False), ("bus", "model"))

    def test_bad_weather_overrides_an_open_air_habit(self):
        rider = self._agent("e-bike", has_two_wheeler=True)
        self.assertEqual(mobility.trip_mode(rider, "bus", 3.0, False, weather="rain"), ("bus", "model"))
        self.assertEqual(mobility.trip_mode(rider, "bus", 3.0, False, weather="clear"), ("e-bike", "habit"))

    def test_breaking_the_habit_picks_another_mode_the_resident_can_take(self):
        for seed in range(50):
            mode, reason = mobility.trip_mode(
                self._agent(), "bus", 5.0, False, deviation=1.0, rng=random.Random(seed)
            )
            self.assertEqual(reason, "alternative")
            self.assertNotEqual(mode, "bus")
            self.assertNotIn(mode, ("car", "bike", "e-bike", "metro"))

    def test_no_random_source_means_no_deviation(self):
        self.assertEqual(
            mobility.trip_mode(self._agent(), "walk", 2.0, False, deviation=1.0), ("bus", "habit")
        )

    def test_the_deviation_rate_is_the_configured_one(self):
        rng = random.Random("rate")
        broken = sum(
            mobility.trip_mode(self._agent(), "bus", 2.0, False, deviation=0.12, rng=rng)[1] == "alternative"
            for _ in range(4000)
        )
        self.assertAlmostEqual(broken / 4000, 0.12, delta=0.02)


class TestTravelPlan(unittest.TestCase):
    def setUp(self):
        self.city_map = _metro_map()

    def test_a_resident_without_a_habit_is_unchanged(self):
        agent = _resident(home="West End", work="East End")
        plan = travel_plan(agent, self.city_map, "West End", "East End")
        self.assertEqual(plan["mode"], choose_transport_mode(agent, self.city_map, "West End", "East End")[0])
        self.assertEqual(plan["mode_reason"], "model")

    def test_a_habit_sets_the_mode(self):
        agent = _resident(default_transport="bus")
        plan = travel_plan(agent, self.city_map, "Midtown", "Outpost")
        self.assertEqual((plan["mode"], plan["mode_reason"]), ("bus", "habit"))


class TestMoveAgent(unittest.TestCase):
    def test_trips_are_counted_and_reproducible(self):
        from gaworld.settings import CONFIG
        from gaworld.sim._location import move_agent

        city_map = _metro_map()

        def commute(agent):
            modes = []
            for _ in range(30):
                for target in ("Outpost", "Midtown"):
                    out = move_agent(agent, target, "出行", "10:00", 600, city_map)
                    modes.append(out["travel"]["mode"])
            return modes

        first = _resident(default_transport="bus")
        second = copy.deepcopy(first)
        with mock.patch.dict(CONFIG, {"transport_habit": {"deviation_probability": 0.3}}):
            a, b = commute(first), commute(second)
        self.assertEqual(a, b)
        self.assertEqual(first["locations"]["trips_taken"], 60)
        self.assertIn("bus", a)
        self.assertTrue(set(a) - {"bus"}, "a 30% deviation over 60 trips never broke the habit")


class TestPlugin(unittest.TestCase):
    def _run(self, cfg):
        from gaworld.kernel import build_kernel
        from gaworld.world.plugin import TransportHabitPlugin

        ctx = build_kernel({"transport_habit": cfg}, load_entry_points=False)
        ctx.extras["city_map"] = _metro_map()
        TransportHabitPlugin().setup(ctx)
        agents = [_resident(has_car=True), _resident(job="外卖骑手", home="West End", work="Midtown")]
        ctx.bus.emit("agents.built", agents=agents)
        return ctx, agents

    def test_assigns_every_resident_a_habit(self):
        ctx, agents = self._run({"enabled": True})
        self.assertEqual([a["default_transport"] for a in agents], ["car", "e-bike"])
        self.assertEqual(ctx.plugin_state("transport_habit")["default_mode_counts"], {"car": 1, "e-bike": 1})

    def test_disabled_leaves_residents_alone(self):
        _ctx, agents = self._run({"enabled": False})
        self.assertTrue(all("default_transport" not in a for a in agents))


if __name__ == "__main__":
    unittest.main()
