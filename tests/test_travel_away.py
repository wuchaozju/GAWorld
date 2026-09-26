"""Tests for residents leaving the city.

Grouped by the properties the design leans on:

* **Absence is real.** Someone out of town holds no place in the city, meets
  nobody here, and puts nothing on the roads.
* **Coming home is a journey.** The return leg is rebuilt from the recorded
  home node, never from the away label — routing from the label silently
  yields a free, instantaneous trip, which is the trap this feature is most
  likely to fall into.
* **Departures are reproducible.** No LLM decides who leaves; the same seed
  puts the same resident on the same train on the same day.
* **Off means off.** With the block disabled the plugin registers nothing.
"""

from __future__ import annotations

import os
import tempfile
import unittest

from gaworld.behavior.dynamic import detect_co_located_agents
from gaworld.kernel import build_kernel
from gaworld.travel import destination, itinerary, trigger
from gaworld.travel.plugin import TravelPlugin
from gaworld.world import away
from gaworld.world import city_map as cm
from gaworld.world import local_physical as lp
from gaworld.world import traffic as tf


def _mini_map():
    """Three nodes in a line, near the procedural map's Hangzhou anchor."""
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


def _agent(agent_id=1, **extra):
    agent = {
        "id": agent_id,
        "name": f"居民{agent_id}",
        "job": "销售经理",
        "age": 34,
        "state": {"stress": 0.5},
        "locations": {"home": "Alpha", "workplace": "Gamma", "current": "Alpha"},
        "relationships": {},
    }
    agent.update(extra)
    return agent


def _away_agent(agent_id=1, place="北京", **trip_extra):
    agent = _agent(agent_id)
    trip = {
        "status": "away", "purpose": "family", "place": place,
        "distance_km": 1120.0, "mode": "air", "hours": 3.6, "fare": 840.0,
        "home_node": "Alpha", "depart_day": 3, "return_day": 6,
    }
    trip.update(trip_extra)
    agent["ext"] = {"travel": trip}
    agent["locations"]["current"] = away.away_label(place)
    return agent


# ---------------------------------------------------------------------------
# Absence is real
# ---------------------------------------------------------------------------

class TestAbsenceIsReal(unittest.TestCase):

    def test_away_agent_holds_no_place_in_the_city(self):
        city_map = _mini_map()
        counts = lp.update_occupancy_from_agents(city_map, [_agent(1), _away_agent(2)])
        self.assertEqual(counts, {"Alpha": 1})
        self.assertNotIn(away.away_label("北京"), counts)

    def test_two_people_away_are_not_standing_together(self):
        """The trap: the label is display text, so it collides."""
        a, b = _away_agent(1, "北京"), _away_agent(2, "北京")
        self.assertEqual(a["locations"]["current"], b["locations"]["current"])
        agents = [a, b]
        self.assertEqual(detect_co_located_agents(a, agents, {}), [])
        self.assertEqual(detect_co_located_agents(b, agents, {}), [])

    def test_unnamed_away_labels_collide_too(self):
        a, b = _away_agent(1, ""), _away_agent(2, "")
        self.assertEqual(a["locations"]["current"], away.AWAY_PREFIX)
        self.assertEqual(detect_co_located_agents(a, [a, b], {}), [])

    def test_people_in_town_still_meet(self):
        a, b = _agent(1), _agent(2)
        self.assertEqual([o["id"] for o in detect_co_located_agents(a, [a, b], {})], [2])

    def test_someone_in_town_does_not_meet_someone_away(self):
        a, b = _agent(1), _away_agent(2)
        self.assertEqual(detect_co_located_agents(a, [a, b], {}), [])

    def test_a_pinned_agent_makes_no_trip_and_no_road_load(self):
        """Blanking the destination lands `move_agent` on its no-move branch."""
        from gaworld.sim._location import move_agent

        agent = _away_agent(1)
        movement = move_agent(
            agent, desired_location="", activity="休息", time_str="09:00",
            step_minutes=30, city_map=_mini_map(),
        )
        self.assertEqual(movement["travel"]["status"], "stationary")
        self.assertNotIn(movement["travel"]["status"], tf.ON_ROAD_STATUSES)
        self.assertEqual(tf.travel_pcu(movement["travel"]), 0.0)


# ---------------------------------------------------------------------------
# Coming home is a journey
# ---------------------------------------------------------------------------

class TestComingHome(unittest.TestCase):

    def test_the_away_label_is_not_routable(self):
        """Why `home_node` exists at all — this is the silent failure.

        Routing from the label looks like it works: it returns a valid plan
        with no error, in which the journey from Beijing is free and takes a
        single tick.
        """
        city_map = _mini_map()
        route, km = cm.shortest_path_with_distance(city_map, away.away_label("北京"), "Alpha")
        self.assertEqual((route, km), ([], 0.0))
        self.assertEqual(cm.distance_between(city_map, away.away_label("北京"), "Alpha"), 0.0)

    def test_home_node_comes_from_the_itinerary_not_the_label(self):
        agent = _away_agent(1)
        self.assertEqual(away.home_node_of(agent), "Alpha")
        self.assertIsNotNone(cm.node_by_name(_mini_map(), away.home_node_of(agent)))

    def test_landing_restores_a_real_position_and_closes_the_trip(self):
        ctx = _ctx({"enabled": True})
        plugin = _plugin(ctx)
        agent = _away_agent(1)
        plugin._land(agent, away.trip_of(agent), 7, {"sim": ctx})
        self.assertEqual(agent["locations"]["current"], "Alpha")
        self.assertFalse(away.is_away(agent))
        self.assertEqual(away.trip_of(agent), {})

    def test_journey_length_scales_with_distance(self):
        near = destination.journey(400.0)
        far = destination.journey(2500.0)
        self.assertEqual(near["mode"], "rail")
        self.assertEqual(far["mode"], "air")
        self.assertGreater(far["hours"], near["hours"])
        self.assertGreater(far["fare"], near["fare"])

    def test_even_the_shortest_trip_costs_half_a_day(self):
        self.assertGreaterEqual(destination.journey(130.0)["hours"], destination.MIN_LEG_HOURS)


# ---------------------------------------------------------------------------
# Destinations
# ---------------------------------------------------------------------------

class TestDestinations(unittest.TestCase):

    def test_catalogue_is_real_distances_and_drops_the_neighbourhood(self):
        places = destination.catalogue(_mini_map())
        self.assertTrue(places)
        self.assertTrue(all(km >= destination.MIN_TRIP_KM for _n, km in places))
        by_name = dict(places)
        # The map is anchored near Hangzhou, so Beijing is over 1000 km away
        # and Guangdong further still. Real coordinates, not a made-up scale.
        self.assertGreater(by_name["北京"], 1000.0)
        self.assertGreater(by_name["广东"], by_name["江苏"])

    def test_catalogue_order_does_not_depend_on_the_source_table(self):
        names = [n for n, _ in destination.catalogue(_mini_map())]
        self.assertEqual(names, sorted(names))

    def test_a_ghosts_city_is_matched_out_of_free_text(self):
        self.assertEqual(destination.match_place("北京市朝阳区"), "北京")
        self.assertEqual(destination.match_place("老家在四川"), "四川")
        self.assertEqual(destination.match_place("海外"), "")

    def test_a_visit_goes_where_the_relative_lives(self):
        import random

        place, km = destination.pick(
            _mini_map(), random.Random(1), prefer="北京市", max_km=5000.0
        )
        self.assertEqual(place, "北京")
        self.assertGreater(km, 1000.0)

    def test_a_short_trip_cannot_cross_the_country(self):
        import random

        for seed in range(20):
            _place, km = destination.pick(_mini_map(), random.Random(seed), max_km=800.0)
            self.assertLessEqual(km, 800.0)


# ---------------------------------------------------------------------------
# Why people go
# ---------------------------------------------------------------------------

class TestTriggers(unittest.TestCase):

    CFG = {
        "business": {"base_daily_prob": 0.004, "days": [2, 4]},
        "family": {"obligation_threshold": 0.72, "daily_prob_over_threshold": 0.18,
                   "days": [2, 5]},
        "leisure": {"base_daily_prob": 0.02, "min_cash_months": 1.5, "days": [3, 7]},
    }

    def _with_neglected_parent(self, obligation=0.9, last_contact=0):
        return _agent(1, relationships={
            "g_mother": {
                "kind": "ghost", "role": "mother", "obligation": obligation,
                "closeness": 0.6, "last_contact_day": last_contact,
                "profile": {"name": "妈妈", "city": "北京"},
            },
        })

    def test_only_off_screen_ties_are_worth_travelling_for(self):
        agent = self._with_neglected_parent()
        agent["relationships"]["7"] = {
            "kind": "agent", "role": "mother", "obligation": 0.99,
            "last_contact_day": 0,
        }
        keys = [k for k, _r, _p in trigger.visitable_ties(agent, 30)]
        self.assertEqual(keys, ["g_mother"])

    def test_silence_adds_to_the_pull(self):
        fresh = trigger.visitable_ties(self._with_neglected_parent(0.7, 30), 30)[0][2]
        stale = trigger.visitable_ties(self._with_neglected_parent(0.7, 0), 30)[0][2]
        self.assertGreater(stale, fresh)

    def test_a_contented_tie_never_triggers_a_visit(self):
        agent = self._with_neglected_parent(obligation=0.1, last_contact=30)
        for day in range(1, 60):
            intent = trigger.decide(
                agent, day, is_weekend=False, cfg=self.CFG, seed=7)
            self.assertNotEqual((intent or {}).get("purpose"), "family")

    def test_a_neglected_parent_eventually_pulls_someone_home(self):
        agent = self._with_neglected_parent()
        purposes = {
            (trigger.decide(agent, d, is_weekend=False, cfg=self.CFG, seed=7) or {}).get("purpose")
            for d in range(1, 60)
        }
        self.assertIn("family", purposes)

    def test_the_visit_carries_the_relatives_city(self):
        agent = self._with_neglected_parent()
        for day in range(1, 60):
            intent = trigger.decide(agent, day, is_weekend=False, cfg=self.CFG, seed=7)
            if intent and intent["purpose"] == "family":
                self.assertEqual(intent["tie_city"], "北京")
                self.assertEqual(intent["tie_key"], "g_mother")
                return
        self.fail("no family visit was ever triggered")

    def test_travel_heavy_jobs_travel_more(self):
        self.assertGreater(
            trigger.business_weight(_agent(1, job="外贸销售")),
            trigger.business_weight(_agent(1, job="图书管理员")),
        )
        self.assertEqual(trigger.business_weight(_agent(1, job="图书管理员")), 1.0)

    def test_nobody_goes_on_a_business_trip_at_the_weekend(self):
        agent = _agent(1, job="外贸销售")
        purposes = {
            (trigger.decide(agent, d, is_weekend=True, cfg=self.CFG, seed=3) or {}).get("purpose")
            for d in range(1, 200)
        }
        self.assertNotIn("business", purposes)

    def test_a_holiday_needs_money(self):
        broke = _agent(1, economy={
            "accounts": {"checking": 200.0, "savings": 0.0},
            "monthly_expense_estimate": 6000.0,
        })
        purposes = {
            (trigger.decide(broke, d, is_weekend=True, cfg=self.CFG, seed=5) or {}).get("purpose")
            for d in range(1, 200)
        }
        self.assertNotIn("leisure", purposes)

    def test_the_same_seed_puts_the_same_person_on_the_same_train(self):
        def run(seed):
            agent = self._with_neglected_parent()
            return [
                trigger.decide(agent, d, is_weekend=d % 7 in (6, 0), cfg=self.CFG, seed=seed)
                for d in range(1, 40)
            ]

        self.assertEqual(run(11), run(11))
        self.assertNotEqual(run(11), run(12))


# ---------------------------------------------------------------------------
# The plugin
# ---------------------------------------------------------------------------

def _ctx(travel_cfg, agents=None):
    ctx = build_kernel({"travel": travel_cfg}, load_entry_points=False)
    ctx.extras["city_map"] = _mini_map()
    if agents is not None:
        ctx.set_agents(agents)
    return ctx


def _plugin(ctx):
    plugin = TravelPlugin()
    plugin.setup(ctx)
    return plugin


def _day_start(ctx, day, agents, schedule_map):
    ctx.bus.emit(
        "on_day_start",
        day=day,
        agents=agents,
        schedule_map=schedule_map,
        city_map=ctx.extras["city_map"],
        daily_logs={a["id"]: "" for a in agents},
        extension_state={},
    )


class TestPlugin(unittest.TestCase):

    ON = {
        "enabled": True, "seed": 20260919, "max_away_share": 1.0,
        "daily_surcharge": 180.0,
        "business": {"base_daily_prob": 0.004, "days": [2, 4]},
        "family": {"obligation_threshold": 0.72, "daily_prob_over_threshold": 1.0,
                   "days": [2, 3]},
        "leisure": {"base_daily_prob": 0.0, "min_cash_months": 99.0, "days": [3, 7]},
    }

    def _puller(self, agent_id=1):
        return _agent(agent_id, relationships={
            "g_mother": {
                "kind": "ghost", "role": "mother", "obligation": 0.95,
                "closeness": 0.6, "last_contact_day": 0,
                "profile": {"name": "妈妈", "city": "北京"},
            },
        })

    def test_disabled_registers_nothing(self):
        ctx = _ctx({"enabled": False})
        before = {e: len(h) for e, h in ctx.bus._handlers.items()}
        _plugin(ctx)
        after = {e: len(h) for e, h in ctx.bus._handlers.items()}
        self.assertEqual(before, after)

    def test_disabled_leaves_the_day_untouched(self):
        ctx = _ctx({"enabled": False})
        _plugin(ctx)
        agent = self._puller()
        schedule_map = {1: [("09:00", "工作")]}
        for day in range(1, 15):
            _day_start(ctx, day, [agent], schedule_map)
        self.assertEqual(schedule_map, {1: [("09:00", "工作")]})
        self.assertEqual(agent["locations"]["current"], "Alpha")
        self.assertEqual(agent.get("ext", {}), {})

    def _run_until_departure(self, ctx, agent, max_days=60):
        schedule_map = {agent["id"]: [("09:00", "工作")]}
        for day in range(1, max_days):
            _day_start(ctx, day, [agent], schedule_map)
            if away.trip_of(agent):
                return day, schedule_map
        self.fail("nobody ever left")

    def test_a_departure_writes_a_whole_trip(self):
        ctx = _ctx(self.ON)
        _plugin(ctx)
        agent = self._puller()
        day, schedule_map = self._run_until_departure(ctx, agent)
        trip = away.trip_of(agent)
        self.assertEqual(trip["purpose"], "family")
        self.assertEqual(trip["place"], "北京")
        self.assertEqual(trip["home_node"], "Alpha")
        self.assertEqual(trip["depart_day"], day)
        self.assertGreaterEqual(trip["return_day"], day)
        self.assertTrue(away.is_away(agent))
        # The day was replaced, not decorated.
        self.assertNotEqual(schedule_map[1], [("09:00", "工作")])
        self.assertTrue(any("北京" in a for _t, a in schedule_map[1]))

    def test_the_whole_trip_is_scheduled_then_the_agent_comes_home(self):
        ctx = _ctx(self.ON)
        _plugin(ctx)
        agent = self._puller()
        depart, schedule_map = self._run_until_departure(ctx, agent)
        last = int(away.trip_of(agent)["return_day"])
        for day in range(depart + 1, last + 1):
            _day_start(ctx, day, [agent], schedule_map)
            self.assertTrue(away.is_away(agent), f"day {day}")
        _day_start(ctx, last + 1, [agent], schedule_map)
        self.assertFalse(away.is_away(agent))
        self.assertEqual(agent["locations"]["current"], "Alpha")

    def test_going_spends_the_obligation_that_sent_them(self):
        """The point of the family trigger: a loop that was open now closes."""
        ctx = _ctx(self.ON)
        _plugin(ctx)
        agent = self._puller()
        depart, schedule_map = self._run_until_departure(ctx, agent)
        before = dict(agent["relationships"]["g_mother"])
        last = int(away.trip_of(agent)["return_day"])
        for day in range(depart + 1, last + 2):
            _day_start(ctx, day, [agent], schedule_map)
        after = agent["relationships"]["g_mother"]
        self.assertLess(after["obligation"], before["obligation"])
        self.assertGreater(after["closeness"], before["closeness"])
        self.assertGreater(after["last_contact_day"], before["last_contact_day"])

    def test_the_city_cannot_be_emptied(self):
        cfg = dict(self.ON, max_away_share=0.2)
        ctx = _ctx(cfg)
        _plugin(ctx)
        agents = [self._puller(i) for i in range(1, 11)]
        schedule_map = {a["id"]: [("09:00", "工作")] for a in agents}
        for day in range(1, 20):
            _day_start(ctx, day, agents, schedule_map)
            self.assertLessEqual(sum(1 for a in agents if away.is_away(a)), 2)

    def test_a_real_out_of_town_position_is_never_sent_home(self):
        """A twin fix is the user's fact, not ours to overwrite."""
        ctx = _ctx(self.ON)
        _plugin(ctx)
        twinned = _agent(1)
        twinned["locations"]["current"] = away.away_label("上海")  # no itinerary
        schedule_map = {1: [("09:00", "工作")]}
        for day in range(1, 20):
            _day_start(ctx, day, [twinned], schedule_map)
        self.assertEqual(twinned["locations"]["current"], away.away_label("上海"))
        self.assertEqual(away.trip_of(twinned), {})

    def test_the_agent_is_told_it_is_not_in_town(self):
        ctx = _ctx(self.ON)
        _plugin(ctx)
        agent = _away_agent(1, "北京")
        lines = ctx.bus.collect("perception.compose", agent=agent, day=4, sim=ctx)
        self.assertTrue(any("北京" in str(line) for line in lines))

    def test_someone_in_town_is_told_nothing(self):
        ctx = _ctx(self.ON)
        _plugin(ctx)
        lines = ctx.bus.collect("perception.compose", agent=_agent(1), day=4, sim=ctx)
        self.assertEqual(lines, [])

    def test_the_move_stage_is_blanked_only_for_the_absent(self):
        ctx = _ctx(self.ON)
        _plugin(ctx)
        self.assertEqual(
            ctx.bus.filter("location.resolve", "Gamma", agent=_away_agent(1), sim=ctx), "")
        self.assertEqual(
            ctx.bus.filter("location.resolve", "Gamma", agent=_agent(1), sim=ctx), "Gamma")


# ---------------------------------------------------------------------------
# The shape of a day away
# ---------------------------------------------------------------------------

class TestItinerary(unittest.TestCase):

    TRIP = {
        "purpose": "family", "place": "北京", "mode": "air", "hours": 3.6,
        "tie_name": "妈妈", "depart_day": 3, "return_day": 5,
    }

    def test_each_leg_gets_its_own_day(self):
        self.assertIn("前往北京", " ".join(a for _t, a in itinerary.schedule_for(self.TRIP, 3)))
        self.assertIn("妈妈", " ".join(a for _t, a in itinerary.schedule_for(self.TRIP, 4)))
        self.assertIn("返回", " ".join(a for _t, a in itinerary.schedule_for(self.TRIP, 5)))

    def test_schedules_are_ordered_time_activity_pairs(self):
        for day in (3, 4, 5):
            schedule = itinerary.schedule_for(self.TRIP, day)
            times = [t for t, _a in schedule]
            self.assertEqual(times, sorted(times))
            for entry in schedule:
                self.assertIsInstance(entry, tuple)
                self.assertEqual(len(entry), 2)

    def test_purpose_shapes_the_day(self):
        business = " ".join(a for _t, a in itinerary.away_day(dict(self.TRIP, purpose="business")))
        leisure = " ".join(a for _t, a in itinerary.away_day(dict(self.TRIP, purpose="leisure")))
        self.assertIn("客户", business)
        self.assertNotIn("客户", leisure)

    def test_arrival_never_spills_past_midnight(self):
        schedule = itinerary.depart_day(dict(self.TRIP, hours=20.0))
        self.assertTrue(all(t <= "23:30" for t, _a in schedule))

    def test_the_perception_line_counts_down(self):
        self.assertIn("第 1 天", itinerary.perception_line(self.TRIP, 3))
        self.assertIn("第 2 天", itinerary.perception_line(self.TRIP, 4))
        self.assertIn("回本市", itinerary.perception_line(self.TRIP, 5))


if __name__ == "__main__":
    unittest.main()
