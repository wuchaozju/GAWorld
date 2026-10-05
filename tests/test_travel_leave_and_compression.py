"""Leaving the city, second pass (docs/proposals/2026-10-03-travel-leave-and-cost.md).

* **The calendar is the run's calendar.** The travel and family plugins
  imported their day-type helper from a module that does not define it and
  so always assumed day 1 was a Monday.
* **Away is not at work.** The economy's income seek rewrote a family visit to
  "工作" on most steps (every step for a laid-off resident).
* **A missed working day on leave is paid**, up to an annual allowance.
* **A day away costs one LLM call**, not a routine plus several per step.
"""

from __future__ import annotations

import copy
import json
import os
import tempfile
import unittest
from typing import ClassVar
from unittest import mock

import pytest

from gaworld.economy import finance as eco
from gaworld.family.plugin import FamilyPlugin
from gaworld.kernel import build_kernel
from gaworld.sim._utils import _resolve_day_context, calendar_from_config
from gaworld.sim.pipeline import StagePipeline
from gaworld.travel.plugin import AWAY_SKIPPED_STAGES, TravelPlugin
from gaworld.world import away
from tests.fixtures import scratch_cwd
from tests.fixtures.mock_llm import install
from tests.test_economy_conservation import _build_agent, _build_config
from tests.test_travel_away import _away_agent, _mini_map

SATURDAY_START = {"start_date": "2026-10-03", "start_weekday": "monday",
                  "weekend_days": ["saturday", "sunday"]}


def _types(day_count, calendar):
    cal = calendar_from_config({"calendar": calendar} if calendar is not None else {})
    return [_resolve_day_context(d, **cal)["day_type"] for d in range(1, day_count + 1)]


class CalendarTest(unittest.TestCase):
    def test_a_saturday_start_makes_days_one_and_two_the_weekend(self):
        self.assertEqual(_types(8, SATURDAY_START),
                         ["weekend", "weekend"] + ["weekday"] * 5 + ["weekend"])

    def test_a_bare_config_keeps_the_monday_start(self):
        self.assertEqual(_types(7, None), ["weekday"] * 5 + ["weekend"] * 2)

    def test_both_plugins_read_the_run_calendar(self):
        config = {"travel": {"enabled": True}, "calendar": SATURDAY_START}
        ctx = build_kernel(config, load_entry_points=False)
        travel, family = TravelPlugin(), FamilyPlugin()
        travel.setup(ctx)
        family.setup(ctx)
        # The old fallback said day 1 was a Monday and day 6 a Saturday.
        self.assertTrue(travel._is_weekend(1) and family._is_weekend(1))
        self.assertFalse(travel._is_weekend(6) or family._is_weekend(6))


class AwayIsNotAtWorkTest(unittest.TestCase):
    def _rewritten(self, agent, config, ext):
        hits = 0
        for _ in range(200):
            step = {"activity": "陪妈妈吃早饭、说话"}
            eco.on_agent_pre_step({"config": config, "agent": agent, "step": step,
                                   "extension_state": ext, "actions": {}})
            hits += step["activity"] != "陪妈妈吃早饭、说话"
        return hits

    def test_the_income_seek_leaves_an_away_resident_alone(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = _build_config(tmp)
            agent = _build_agent(1, job="程序员")
            ext = {}
            eco.on_simulation_start({"config": config, "agents": [agent], "extension_state": ext})
            agent["economy"]["_layoff_days_remaining"] = 20  # always seeks when home
            agent["locations"] = {"current": "Alpha"}
            self.assertEqual(self._rewritten(agent, config, ext), 200)
            agent["locations"]["current"] = away.away_label("成都")
            self.assertEqual(self._rewritten(agent, config, ext), 0)


def _economy_agent(tmp, job="程序员"):
    config = _build_config(tmp)
    agent = _build_agent(1, job=job)
    ext = {}
    eco.on_simulation_start({"config": config, "agents": [agent], "extension_state": ext})
    return agent, config, ext


class PaidLeaveTest(unittest.TestCase):
    def test_a_leave_day_pays_a_day_of_salary_out_of_the_firms_pool(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent, config, ext = _economy_agent(tmp)
            econ = agent["economy"]
            ctx = {"config": config, "extension_state": ext}
            firms_before = ext["economy_module"]["sectors"]["firms"]
            cash_before = econ["accounts"]["checking"]
            record = eco.credit_paid_leave(agent, ctx, day=3)
            self.assertEqual(record["type"], "paid_leave")
            self.assertAlmostEqual(record["pay"], econ["gross_monthly_salary"] / 22, places=1)
            self.assertAlmostEqual(econ["accounts"]["checking"] - cash_before, record["pay"], places=2)
            self.assertAlmostEqual(firms_before - ext["economy_module"]["sectors"]["firms"],
                                   record["pay"], places=2)
            self.assertAlmostEqual(econ["month_gross_income"], record["pay"], places=2)

    def test_the_allowance_runs_out_and_renews_each_year(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent, config, ext = _economy_agent(tmp)
            ctx = {"config": config, "extension_state": ext}
            kinds = [eco.credit_paid_leave(agent, ctx, day=d, days_per_year=5)["type"]
                     for d in range(10, 17)]
            self.assertEqual(kinds, ["paid_leave"] * 5 + ["unpaid_leave"] * 2)
            self.assertEqual(eco.credit_paid_leave(agent, ctx, day=400)["type"], "paid_leave")

    def test_only_the_employed_have_leave(self):
        with tempfile.TemporaryDirectory() as tmp:
            for job in ("待业中", "大学生", "已退休"):
                agent, config, ext = _economy_agent(tmp, job=job)
                self.assertIsNone(
                    eco.credit_paid_leave(agent, {"config": config, "extension_state": ext}, day=3), job)


def _plugin(config):
    ctx = build_kernel(config, load_entry_points=False)
    ctx.extras["city_map"] = _mini_map()
    plugin = TravelPlugin()
    plugin.setup(ctx)
    return ctx, plugin


def _emit_day_start(ctx, day, agents, schedule_map, config, ext):
    ctx.bus.emit("on_day_start", day=day, agents=agents, schedule_map=schedule_map,
                 city_map=ctx.extras["city_map"], daily_logs={a["id"]: "" for a in agents},
                 extension_state=ext, config=config)


class TravelLeaveTest(unittest.TestCase):
    def _trip_days(self, purpose):
        with tempfile.TemporaryDirectory() as tmp:
            agent, config, ext = _economy_agent(tmp)
            trip = _away_agent(1, purpose=purpose, depart_day=1, return_day=9)
            agent["ext"], agent["locations"] = trip["ext"], trip["locations"]
            config = {**config, "calendar": SATURDAY_START,
                      "travel": {"enabled": True, "max_away_share": 0.0}}
            ctx, _ = _plugin(config)
            for day in range(1, 10):  # Sat 3 Oct .. Sun 11 Oct
                _emit_day_start(ctx, day, [agent], {1: [("09:00", "工作")]}, config, ext)
            return [r for r in agent["economy"].get("shock_log", [])
                    if r.get("type") in ("paid_leave", "unpaid_leave")]

    def test_a_family_visit_takes_the_working_days_as_leave(self):
        records = self._trip_days("family")
        # Days 3-7 are Monday-Friday; the weekends are not leave.
        self.assertEqual([r["day"] for r in records], [3, 4, 5, 6, 7])
        self.assertEqual([r["type"] for r in records], ["paid_leave"] * 5)

    def test_a_business_trip_is_work_not_leave(self):
        self.assertEqual(self._trip_days("business"), [])


class EventsReachTest(unittest.TestCase):
    EVENTS: ClassVar[list] = [
        {"type": t, "name": t} for t in ("natural", "social", "economic", "political", "technology")
    ]

    def test_the_city_weather_and_street_events_stop_at_the_city_limits(self):
        ctx, _ = _plugin({"travel": {"enabled": True}})
        traveller = _away_agent(1)
        home = {"id": 2, "locations": {"current": "Alpha"}}
        twin = {"id": 3, "locations": {"current": away.away_label("上海")}}

        def reach(agent):
            out = ctx.bus.filter("env.events.reach", list(self.EVENTS), agent=agent, day=4,
                                 time_str="09:00")
            return [ev["type"] for ev in out]

        self.assertEqual(reach(traveller), ["economic", "political", "technology"])
        self.assertEqual(reach(home), [e["type"] for e in self.EVENTS])
        self.assertEqual(reach(twin), [e["type"] for e in self.EVENTS])  # a real person's call


class SkipStagesTest(unittest.TestCase):
    def test_a_stage_named_in_skip_stages_does_not_run_for_that_step(self):
        ran = []

        def stage(name, sets=None):
            def fn(agent, step, ctx):
                ran.append(name)
                if sets:
                    step["_skip_stages"] = sets
            return name, fn

        pipe = StagePipeline([stage("prepare", ("plan", "reflect")), stage("plan"),
                              stage("move"), stage("reflect"), stage("record")])
        pipe.run_step({}, {}, None)
        self.assertEqual(ran, ["prepare", "move", "record"])
        ran.clear()
        pipe2 = StagePipeline([stage("prepare"), stage("plan"), stage("reflect")])
        pipe2.run_step({}, {}, None)
        self.assertEqual(ran, ["prepare", "plan", "reflect"])


class CompressionTest(unittest.TestCase):
    CFG: ClassVar[dict] = {"travel": {"enabled": True, "compress_away_days": True, "max_away_share": 0.0}}

    def test_off_in_a_bare_config_registers_no_compression_hooks(self):
        ctx, _ = _plugin({"travel": {"enabled": True}})
        self.assertFalse(ctx.bus._handlers.get("day.routine.skip"))
        self.assertFalse(ctx.bus._handlers.get("on_agent_pre_step"))

    def test_routine_and_cognition_are_skipped_only_while_away(self):
        ctx, _ = _plugin(self.CFG)
        traveller = _away_agent(1, depart_day=3, return_day=6)
        home = {"id": 2, "locations": {"current": "Alpha"}}
        twin = {"id": 3, "locations": {"current": away.away_label("上海")}}  # real GPS, no trip
        skip = lambda agent, day: ctx.bus.filter("day.routine.skip", False, agent=agent, day=day)  # noqa: E731
        self.assertTrue(skip(traveller, 5))
        self.assertTrue(skip(traveller, 6))
        self.assertFalse(skip(traveller, 7))  # lands that morning: needs a routine
        self.assertFalse(skip(home, 5))
        self.assertFalse(skip(twin, 5))
        for agent, expect in ((traveller, True), (home, False), (twin, False)):
            step = {"activity": "陪妈妈吃早饭、说话"}
            ctx.bus.emit("on_agent_pre_step", agent=agent, step=step, day=5, time_str="08:30")
            self.assertEqual("_skip_stages" in step, expect, agent["id"])
        self.assertEqual(set(AWAY_SKIPPED_STAGES) & {"move", "update_state", "memorize", "record"},
                         set())

    def test_a_day_away_is_one_digest_call_that_leaves_a_memory(self):
        scratch_cwd.enter(self)
        ctx, _ = _plugin(self.CFG)
        agent = _away_agent(1, depart_day=3, return_day=6)
        agent["state"] = {"emotion": 0.5, "stress": 0.5}
        agent["memory"] = []
        reply = json.dumps({"brief": "陪妈妈逛了菜市场，聊了很多小时候的事。",
                            "memory": "妈妈的腿脚比去年慢了。",
                            "state_changes": {"stress": -0.9, "emotion": 0.05}},
                           ensure_ascii=False)
        with install() as llm:
            llm.set_response("fast_forward_day", reply)
            _emit_day_start(ctx, 4, [agent], {1: []}, {}, {})
        self.assertEqual([c["task"] for c in llm.calls], ["fast_forward_day"])
        self.assertIn("妈妈的腿脚比去年慢了。", agent["memory"])
        # The drift is capped like any fast-forward day, not taken at face value.
        self.assertGreater(agent["state"]["stress"], 0.5 - 0.9)
        self.assertLess(agent["state"]["stress"], 0.5)


@pytest.mark.slow
class MainLoopTest(unittest.TestCase):
    """A real two-day run: one resident leaves on day 1, the other stays."""

    def test_the_traveller_costs_a_fraction_of_the_stay_at_home(self):
        import generative_city_sim as sim
        from gaworld.settings import CONFIG

        scratch_cwd.enter(self)
        records = tempfile.mkdtemp()
        touched = ("agent_ids", "sim_days", "stateful", "simulate_realtime", "seconds_per_day",
                   "news", "intervention", "external_environment_service", "distributed",
                   "visualization", "life_events", "external_rag", "records", "travel", "calendar")
        originals = {key: copy.deepcopy(CONFIG[key]) for key in touched if key in CONFIG}

        def restore():
            for key in touched:
                if key in originals:
                    CONFIG[key] = originals[key]
                else:
                    CONFIG.pop(key, None)

        self.addCleanup(restore)
        CONFIG.update(agent_ids=[4, 5], sim_days=2, stateful=False, simulate_realtime=False,
                      seconds_per_day=1)
        CONFIG["records"] = {"output_dir": records}
        CONFIG["calendar"] = {**CONFIG.get("calendar", {}), "start_date": "2026-10-05"}  # Monday
        CONFIG["travel"] = {**CONFIG.get("travel", {}), "enabled": True, "max_away_share": 0.5,
                            "compress_away_days": True,
                            "business": {"base_daily_prob": 1000.0, "days": [3, 3]},
                            "family": {"obligation_threshold": 9.9},
                            "leisure": {"base_daily_prob": 0.0}}
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
        for name, value in (("AGENT_IDS", [4, 5]), ("SIM_DAYS", 2), ("STATEFUL", False),
                            ("SIMULATE_REALTIME", False), ("SECONDS_PER_DAY", 1),
                            ("NEWS_ENABLED", False), ("INTERVENTION_ENABLED", False),
                            ("HUMAN_REALISM_ENABLED", False), ("VISUALIZATION_ENABLED", False),
                            ("LIFE_EVENTS_ENABLED", False), ("LONG_RUN_ENABLED", False)):
            patcher = mock.patch.object(sim, name, value, create=True)
            patcher.start()
            self.addCleanup(patcher.stop)

        with install() as llm:
            sim.run_simulation()

        with open(os.path.join(records, "travel.depart.jsonl"), encoding="utf-8") as fh:
            departed = {json.loads(line)["agent_id"] for line in fh if line.strip()}
        self.assertEqual(len(departed), 1, departed)
        (gone,) = departed
        (stayed,) = {4, 5} - departed

        def calls(agent_id, task=None):
            return [c for c in llm.calls
                    if c["agent_id"] == agent_id and (task is None or c["task"] == task)]

        # Day 1's routine was made before anyone decided to leave; day 2's was not.
        self.assertEqual(len(calls(gone, "daily_routine")), 1)
        self.assertEqual(len(calls(stayed, "daily_routine")), 2)
        self.assertEqual(len(calls(gone, "fast_forward_day")), 2)
        per_step = ("perception", "planning", "reflection", "location_actions", "routine_change")
        self.assertEqual([c for t in per_step for c in calls(gone, t)], [])
        # The city's weather never reached the traveller.
        weather = [c for c in calls(gone, "event_effect") if "天气" in c["prompt"]]
        self.assertEqual(weather, [])
        self.assertTrue([c for c in calls(stayed, "event_effect") if "天气" in c["prompt"]])
        # What is left is what every resident pays per day (summary, diary)
        # and per economic / political / technology event (`event_effect`).
        # Without the latter, the traveller costs well under half.
        def cost(agent_id):
            return sum(1 for c in calls(agent_id) if c["task"] != "event_effect")
        self.assertLess(cost(gone), 0.4 * cost(stayed), (cost(gone), cost(stayed)))


if __name__ == "__main__":
    unittest.main()
