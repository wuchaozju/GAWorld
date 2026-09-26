"""Tests for the enhanced location system.

Covers:
- Transport cost calculation (calc_transport_cost)
- Rush hour detection (is_rush_hour)
- Weather-adjusted mode selection (choose_transport_mode)
- Spatial queries (nearby_nodes, nodes_by_category, nearest_by_category)
- Category matching (activity_to_categories, job_to_workplace_categories)
- Location resolution (resolve_best_location)
- Area price levels (area_price_level)
- Travel plan integration (travel_plan with time/weather)
"""

import os
import random
import unittest

from gaworld.world import city_map as city_map_module
from gaworld.world.city_map import (
    metro_is_usable,
    AREA_PRICE_LEVEL,
    RUSH_HOUR_PERIODS,
    TRANSPORT_FARES,
    WEATHER_MODE_ADJUSTMENTS,
    activity_to_categories,
    area_price_level,
    area_price_level_by_name,
    calc_transport_cost,
    choose_transport_mode,
    distance_between,
    is_rush_hour,
    job_to_workplace_categories,
    load_city_map,
    nearest_by_category,
    nearby_nodes,
    node_by_name,
    nodes_by_category,
    resolve_best_location,
    travel_plan,
)


def _load_map():
    return load_city_map("citymap.md")


def _agent(**overrides):
    base = {
        "id": 99,
        "job": "程序员",
        "daily_life": "写代码",
        "personality": "内向",
        "values": "技术",
        "work_style": "",
        "state": {"mobility_intent": 0.5, "stress": 0.3},
    }
    base.update(overrides)
    return base


# =========================================================================
# Transport Cost
# =========================================================================
class TestTransportCost(unittest.TestCase):

    def test_walk_is_free(self):
        self.assertEqual(calc_transport_cost("walk", 2.0), 0.0)

    def test_bus_flat_fare(self):
        cost = calc_transport_cost("bus", 10.0)
        self.assertEqual(cost, 2.0)  # flat base, no per_km

    def test_metro_distance_based(self):
        # base 2.0 + per_km 0.45 * max(0, 8.0 - 4) = 2.0 + 1.8 = 3.8
        cost = calc_transport_cost("metro", 8.0)
        self.assertAlmostEqual(cost, 3.8, places=1)

    def test_metro_within_free_km(self):
        cost = calc_transport_cost("metro", 3.0)
        self.assertEqual(cost, 2.0)  # base only, within free_km

    def test_taxi_base_plus_distance(self):
        # base 13.0 + per_km 2.5 * max(0, 5.0 - 3) = 13.0 + 5.0 = 18.0
        cost = calc_transport_cost("taxi", 5.0)
        self.assertAlmostEqual(cost, 18.0, places=1)

    def test_taxi_rush_surcharge(self):
        normal = calc_transport_cost("taxi", 5.0, rush_hour=False)
        rush = calc_transport_cost("taxi", 5.0, rush_hour=True)
        self.assertGreater(rush, normal)

    def test_car_with_parking(self):
        base = calc_transport_cost("car", 5.0, parking_hours=0.0)
        with_park = calc_transport_cost("car", 5.0, parking_hours=2.0)
        self.assertGreater(with_park, base)

    def test_unknown_mode_returns_zero(self):
        cost = calc_transport_cost("teleport", 100.0)
        self.assertEqual(cost, 0.0)


# =========================================================================
# Rush Hour
# =========================================================================
class TestRushHour(unittest.TestCase):

    def test_morning_rush(self):
        self.assertTrue(is_rush_hour("08:00"))
        self.assertTrue(is_rush_hour("07:30"))

    def test_evening_rush(self):
        self.assertTrue(is_rush_hour("17:30"))
        self.assertTrue(is_rush_hour("18:30"))

    def test_midday_not_rush(self):
        self.assertFalse(is_rush_hour("12:00"))
        self.assertFalse(is_rush_hour("14:00"))

    def test_night_not_rush(self):
        self.assertFalse(is_rush_hour("22:00"))
        self.assertFalse(is_rush_hour("03:00"))

    def test_none_input(self):
        self.assertFalse(is_rush_hour(None))

    def test_invalid_input(self):
        self.assertFalse(is_rush_hour("not_a_time"))


# =========================================================================
# Weather Mode Adjustment
# =========================================================================
class TestWeatherModeChoice(unittest.TestCase):

    def setUp(self):
        self.city = _load_map()
        self.agent = _agent()

    def test_rain_upgrades_ebike_to_sheltered(self):
        """In rain, an e-bike-distance trip should switch to bus/metro/taxi."""
        nodes = list(self.city["nodes"].keys())
        # Find two nodes ~2-3km apart (e-bike range)
        for i, na in enumerate(nodes):
            for nb in nodes[i + 1 : i + 10]:
                d = distance_between(self.city, na, nb)
                if 1.5 < d < 3.5:
                    mode_clear, _ = choose_transport_mode(
                        self.agent, self.city, na, nb, weather="clear"
                    )
                    mode_rain, _ = choose_transport_mode(
                        self.agent, self.city, na, nb, weather="rain"
                    )
                    if mode_clear == "e-bike":
                        self.assertIn(mode_rain, {"bus", "metro", "taxi"})
                        return
        self.skipTest("No e-bike-range pair found in city map")

    def test_clear_weather_no_change(self):
        nodes = list(self.city["nodes"].keys())
        n1, n2 = nodes[0], nodes[-1]
        mode_none, _ = choose_transport_mode(self.agent, self.city, n1, n2)
        mode_clear, _ = choose_transport_mode(
            self.agent, self.city, n1, n2, weather="clear"
        )
        self.assertEqual(mode_none, mode_clear)


# =========================================================================
# Spatial Queries
# =========================================================================
class TestSpatialQueries(unittest.TestCase):

    def setUp(self):
        self.city = _load_map()

    def test_nearby_nodes_returns_sorted(self):
        near = nearby_nodes(self.city, "Central Block", radius_km=2.0)
        self.assertGreater(len(near), 0)
        dists = [n["distance_km"] for n in near]
        self.assertEqual(dists, sorted(dists))

    def test_nearby_nodes_respects_radius(self):
        near = nearby_nodes(self.city, "Central Block", radius_km=1.0)
        for n in near:
            self.assertLessEqual(n["distance_km"], 1.0)

    def test_nodes_by_category(self):
        edu = nodes_by_category(self.city, "education")
        self.assertGreater(len(edu), 0)
        for nid in edu:
            node = self.city["nodes"][nid]
            self.assertEqual(node["category"].lower(), "education")

    def test_nearest_by_category(self):
        results = nearest_by_category(self.city, "Central Block", "medical", top_k=2)
        self.assertGreater(len(results), 0)
        self.assertLessEqual(len(results), 2)
        # Each result is (node_id, distance_km)
        for nid, d in results:
            self.assertIn(nid, self.city["nodes"])
            self.assertGreater(d, 0)

    def test_nearest_by_category_sorted(self):
        results = nearest_by_category(
            self.city, "Central Block", "education", top_k=5
        )
        dists = [d for _, d in results]
        self.assertEqual(dists, sorted(dists))


# =========================================================================
# Category Matching
# =========================================================================
class TestCategoryMatching(unittest.TestCase):

    def test_activity_to_categories_medical(self):
        cats = activity_to_categories("去医院看病")
        self.assertIn("medical", cats)

    def test_activity_to_categories_shopping(self):
        cats = activity_to_categories("去超市买菜")
        self.assertIn("commerce", cats)

    def test_activity_to_categories_exercise(self):
        cats = activity_to_categories("去公园散步")
        self.assertIn("leisure", cats)

    def test_activity_to_categories_unknown(self):
        cats = activity_to_categories("做一些神秘的事情")
        self.assertIsInstance(cats, list)

    def test_job_to_workplace_tech(self):
        cats = job_to_workplace_categories("软件工程师")
        self.assertTrue(len(cats) > 0)
        self.assertTrue(any(c in cats for c in ["industry", "commerce"]))

    def test_job_to_workplace_teacher(self):
        cats = job_to_workplace_categories("教师")
        self.assertIn("education", cats)

    def test_job_to_workplace_doctor(self):
        cats = job_to_workplace_categories("医生")
        self.assertIn("medical", cats)


# =========================================================================
# Location Resolution
# =========================================================================
class TestResolveLocation(unittest.TestCase):

    def setUp(self):
        self.city = _load_map()

    def test_resolve_returns_candidates(self):
        results = resolve_best_location(
            self.city, "Central Block", ["education"], top_k=3
        )
        self.assertGreater(len(results), 0)
        self.assertLessEqual(len(results), 3)

    def test_resolve_multiple_categories(self):
        results = resolve_best_location(
            self.city, "Central Block", ["medical", "education"], top_k=5
        )
        self.assertGreater(len(results), 0)

    def test_resolve_respects_max_radius(self):
        results = resolve_best_location(
            self.city, "Central Block", ["education"],
            top_k=20, max_radius_km=1.0
        )
        for _, d in results:
            self.assertLessEqual(d, 1.0)

    def test_resolve_empty_for_nonexistent_category(self):
        results = resolve_best_location(
            self.city, "Central Block", ["underwater_base"], top_k=5
        )
        self.assertEqual(len(results), 0)


# =========================================================================
# Area Price Level
# =========================================================================
class TestAreaPriceLevel(unittest.TestCase):

    def setUp(self):
        self.city = _load_map()

    def test_commerce_higher_than_industry(self):
        self.assertGreater(
            AREA_PRICE_LEVEL["commerce"], AREA_PRICE_LEVEL["industry"]
        )

    def test_area_price_level_by_node(self):
        level = area_price_level(self.city, "Central Block")
        self.assertGreater(level, 0)

    def test_area_price_level_by_name_unknown(self):
        level = area_price_level_by_name(self.city, "Nonexistent Place")
        self.assertEqual(level, 1.0)  # default


# =========================================================================
# Travel Plan Integration
# =========================================================================
class TestTravelPlan(unittest.TestCase):

    def setUp(self):
        self.city = _load_map()
        self.agent = _agent()

    def test_travel_plan_includes_cost(self):
        nodes = list(self.city["nodes"].keys())
        plan = travel_plan(
            self.agent, self.city, nodes[0], nodes[-1], time_str="08:00"
        )
        self.assertIn("travel_cost", plan)
        self.assertIsInstance(plan["travel_cost"], float)
        self.assertGreaterEqual(plan["travel_cost"], 0.0)

    def test_travel_plan_rush_hour_flag(self):
        nodes = list(self.city["nodes"].keys())
        plan_rush = travel_plan(
            self.agent, self.city, nodes[0], nodes[-1], time_str="08:00"
        )
        plan_off = travel_plan(
            self.agent, self.city, nodes[0], nodes[-1], time_str="14:00"
        )
        self.assertTrue(plan_rush["rush_hour"])
        self.assertFalse(plan_off["rush_hour"])

    def test_travel_plan_rush_hour_longer(self):
        nodes = list(self.city["nodes"].keys())
        plan_rush = travel_plan(
            self.agent, self.city, nodes[0], nodes[-1], time_str="08:00"
        )
        plan_off = travel_plan(
            self.agent, self.city, nodes[0], nodes[-1], time_str="14:00"
        )
        # Rush hour travel should take equal or longer
        self.assertGreaterEqual(
            plan_rush["travel_minutes"], plan_off["travel_minutes"]
        )

    def test_travel_plan_same_origin_destination(self):
        plan = travel_plan(
            self.agent, self.city, "Central Block", "Central Block"
        )
        self.assertEqual(plan["distance_km"], 0.0)
        self.assertEqual(plan["travel_cost"], 0.0)

    def test_travel_plan_with_weather(self):
        nodes = list(self.city["nodes"].keys())
        plan = travel_plan(
            self.agent, self.city, nodes[0], nodes[-1],
            time_str="10:00", weather="rain"
        )
        self.assertIn("mode", plan)
        self.assertIn("travel_cost", plan)


if __name__ == "__main__":
    unittest.main()


def _metro_map():
    """One line with two stops 6 km apart, plus a node nowhere near it."""
    import tempfile

    content = (
        "# City Map\n"
        "@node: West End | kind=hub | category=transit | x=0.0 | y=0.0 | capacity=500\n"
        "@node: Midtown | kind=hub | category=commerce | x=3.0 | y=0.0 | capacity=500\n"
        "@node: East End | kind=hub | category=transit | x=6.0 | y=0.0 | capacity=500\n"
        "@node: Outpost | kind=hub | category=residential | x=3.0 | y=9.0 | capacity=500\n"
        "@metro: M1 | stops=West End > East End\n"
        "\n- City: Demo\n  - Hub: Midtown\n"
    )
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "m.md")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        return load_city_map(path)


class TestMetroUsability(unittest.TestCase):
    """Whether the metro can carry a trip — not whether the road passes a stop.

    The original test scanned the driving route for any metro stop. On the
    default map that matched 95.5% of commutes against ten stations, so every
    trip over 3 km came out as metro and bus, car and taxi never got a single
    one. A share that is always 100% cannot be compared against an anchor.
    """

    def setUp(self):
        self.city_map = _metro_map()

    def test_both_ends_on_one_line(self):
        self.assertTrue(metro_is_usable(self.city_map, "West End", "East End"))

    def test_one_end_off_the_network(self):
        self.assertFalse(metro_is_usable(self.city_map, "West End", "Outpost"))

    def test_the_same_stop_at_both_ends_is_not_a_ride(self):
        self.assertFalse(metro_is_usable(self.city_map, "West End", "West End"))

    def test_driving_past_a_station_is_not_access(self):
        """Midtown sits on the road between the two stops but is 3 km from
        either — the old route scan counted exactly this case as metro."""
        self.assertFalse(metro_is_usable(self.city_map, "Midtown", "Outpost"))

    def test_walking_radius_widens_access(self):
        self.assertFalse(metro_is_usable(self.city_map, "Midtown", "East End"))
        self.assertTrue(metro_is_usable(self.city_map, "Midtown", "East End", access_km=4.0))

    def test_a_map_with_no_metro_is_never_usable(self):
        self.assertFalse(metro_is_usable({"nodes": {}, "metro_lines": []}, "A", "B"))


class TestModeChoiceWithoutMetroAccess(unittest.TestCase):
    def test_a_long_trip_with_no_metro_is_a_car_trip(self):
        """Previously this returned metro regardless, which is what left the
        car share at exactly zero. The car now also requires owning one —
        a resident without a car takes a taxi (see test_car_ownership)."""
        city_map = _metro_map()
        agent = {"job": "工程师", "daily_life": "", "personality": "", "has_car": True}
        mode, _ = choose_transport_mode(agent, city_map, "Midtown", "Outpost")
        self.assertEqual(mode, "car")


class TestScoredModeChoice(unittest.TestCase):
    """Generalised-cost mode choice — off by default, and why.

    The distance ladder gave the car branch only to the 6-10 km band, so a car
    owner making a 3 km trip could not drive. Scoring modes against one another
    fixes that by construction. It is not switched on because it cannot be
    calibrated against what is published: seven comfort parameters against
    three shares.
    """

    def setUp(self):
        self.city_map = _metro_map()

    def _agent(self, **extra):
        agent = {"job": "工程师", "daily_life": "", "personality": ""}
        agent.update(extra)
        return agent

    def test_the_ladder_is_still_the_default(self):
        self.assertFalse(city_map_module.mode_choice_is_scored(self.city_map))
        self.assertFalse(city_map_module.mode_choice_is_scored(None))

    def test_the_switch_takes_effect(self):
        city_map_module.set_mode_choice(self.city_map, True)
        self.assertTrue(city_map_module.mode_choice_is_scored(self.city_map))

    def test_a_car_owner_can_drive_a_short_trip(self):
        """The whole point: under the ladder this was unreachable."""
        city_map_module.set_mode_choice(self.city_map, True)
        scored = city_map_module._score_modes(
            self._agent(has_car=True, monthly_income=60000.0),
            self.city_map, "West End", "Midtown", 3.0, False)
        self.assertIn("car", scored)

    def test_someone_without_a_car_is_never_offered_one(self):
        scored = city_map_module._score_modes(
            self._agent(has_car=False), self.city_map, "West End", "Midtown", 8.0, False)
        self.assertNotIn("car", scored)

    def test_nobody_is_offered_a_metro_that_cannot_carry_them(self):
        scored = city_map_module._score_modes(
            self._agent(), self.city_map, "Midtown", "Outpost", 9.0, False)
        self.assertNotIn("metro", scored)

    def test_a_high_earner_values_time_more(self):
        """Income is what makes the taxi worth it to one person and not another."""
        rich = city_map_module._value_of_time(self._agent(monthly_income=80000.0))
        poor = city_map_module._value_of_time(self._agent(monthly_income=3000.0))
        self.assertGreater(rich, poor)
        self.assertGreater(city_map_module._value_of_time(self._agent()), 0.0)

    def test_nobody_is_offered_a_walk_across_the_city(self):
        scored = city_map_module._score_modes(
            self._agent(), self.city_map, "West End", "Outpost", 30.0, False)
        self.assertNotIn("walk", scored)
        self.assertTrue(scored, "some mode must always remain feasible")

    def test_the_choice_is_deterministic(self):
        city_map_module.set_mode_choice(self.city_map, True)
        agent = self._agent(has_car=True, monthly_income=9000.0)
        picks = {city_map_module.choose_transport_mode(
            agent, self.city_map, "West End", "East End")[0] for _ in range(20)}
        self.assertEqual(len(picks), 1)
