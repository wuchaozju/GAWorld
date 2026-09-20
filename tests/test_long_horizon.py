"""Tests for month/year-granularity long-horizon runs.

Four layers:

* **Horizon planning** — :func:`plan_horizon` / :func:`span_days` /
  :func:`plan_hook_chunks` turn a run length into steps and into the
  day-boundary hook emissions that back them.
* **Period digest** — :func:`simulate_agent_period`: the wider state-delta
  cap, milestone memories, burst scaling, and the ``day`` delegation.
* **Economy under a coarse step** — fixed costs and shock draws scale with
  ``period_days``, wage income is booked even though no tick ran, money is
  still conserved, and exactly twelve monthly settlements happen in a year.
* **E2E smoke** — 2-agent month and year runs of
  :func:`generative_city_sim.run_simulation` against the mock LLM: exactly
  one ``fast_forward_period`` call per agent per step, no tick-loop tasks,
  per-step briefs + diaries on disk, and the day hooks replayed in chunks.
"""

from __future__ import annotations

import importlib
import json
import os
import shutil
import sys
import tempfile
import unittest
from datetime import date

import gaworld.sim._fastforward as ff
from gaworld.economy import finance as eco
from tests.fixtures.mock_llm import install


# ---------------------------------------------------------------------------
# Horizon planning
# ---------------------------------------------------------------------------

class TestHorizonPlanning(unittest.TestCase):
    START = date(2026, 1, 15)

    def test_day_unit_is_one_period_per_day(self):
        periods = ff.plan_horizon(1, 3, "day", start_date=self.START)
        self.assertEqual([p.end_day for p in periods], [1, 2, 3])
        self.assertEqual([p.days for p in periods], [1, 1, 1])
        self.assertEqual(periods[2].title, "Day 3")

    def test_months_are_calendar_anchored_and_contiguous(self):
        total = ff.span_days("month", 12, start_date=self.START)
        periods = ff.plan_horizon(1, total, "month", start_date=self.START)
        self.assertEqual(len(periods), 12)
        # Contiguous, no gaps or overlaps, covering exactly the horizon.
        self.assertEqual(periods[0].start_day, 1)
        self.assertEqual(periods[-1].end_day, total)
        for prev, nxt in zip(periods, periods[1:]):
            self.assertEqual(nxt.start_day, prev.end_day + 1)
        self.assertEqual(sum(p.days for p in periods), total)
        # Real calendar lengths, not a flat 30.
        self.assertEqual(periods[0].days, 31)  # Jan 15 -> Feb 15
        self.assertEqual(periods[1].days, 28)  # Feb 15 -> Mar 15 (2026)
        self.assertIn("2026-01-15", periods[0].describe())

    def test_years_account_for_leap_days(self):
        start = date(2026, 3, 1)
        total = ff.span_days("year", 2, start_date=start)
        periods = ff.plan_horizon(1, total, "year", start_date=start)
        self.assertEqual([p.days for p in periods], [365, 366])
        self.assertEqual(periods[1].title, "Year 2")

    def test_final_period_is_clipped_to_the_horizon(self):
        periods = ff.plan_horizon(1, 40, "month", start_date=self.START)
        self.assertEqual(len(periods), 2)
        self.assertEqual(periods[1].days, 9)  # 40 - 31

    def test_span_and_plan_work_without_a_calendar(self):
        self.assertEqual(ff.span_days("month", 3, start_date=None), 90)
        self.assertEqual(ff.span_days("year", 1, start_date=None), 365)
        periods = ff.plan_horizon(1, 90, "month", start_date=None)
        self.assertEqual([p.days for p in periods], [30, 30, 30])
        self.assertIn("Day 1~30", periods[0].describe())

    def test_resume_offsets_the_calendar(self):
        periods = ff.plan_horizon(101, 60, "month", start_date=self.START)
        # Day 101 is 100 days after Jan 15 2026 -> Apr 25.
        self.assertEqual(periods[0].start_date, date(2026, 4, 25))
        self.assertEqual(periods[0].start_day, 101)

    def test_hook_chunks_tile_the_period_and_stay_month_sized(self):
        periods = ff.plan_horizon(1, 365, "year", start_date=self.START)
        chunks = ff.plan_hook_chunks(periods[0], ff.hook_chunk_days({}))
        self.assertEqual(sum(days for _, days in chunks), 365)
        self.assertTrue(all(days <= 30 for _, days in chunks))
        self.assertEqual(chunks[-1][0], periods[0].end_day)

    def test_hook_chunk_days_is_capped_at_thirty(self):
        # A chunk longer than 30 days would cross two monthly settlements.
        self.assertEqual(ff.hook_chunk_days({"long_run": {"hook_chunk_days": 90}}), 30)
        self.assertEqual(ff.hook_chunk_days({"long_run": {"hook_chunk_days": 0}}), 1)

    def test_a_coarse_unit_implies_fast_forward(self):
        """`unit=month/year` + `enabled=false` is not "run day by day".

        There is no per-month tick loop, so the only way to honour a coarse
        unit is fast-forward. Resolving the combination the other way means a
        dashboard user who picks 年 without ticking the box silently gets a
        365-tick-loop-day run — the expensive wrong answer.
        """
        self.assertTrue(ff.long_run_enabled({"long_run": {"unit": "month"}}))
        self.assertTrue(ff.long_run_enabled({"long_run": {"enabled": False, "unit": "year"}}))
        # A day unit still needs the explicit flag, and still defaults off.
        self.assertFalse(ff.long_run_enabled({"long_run": {"enabled": False, "unit": "day"}}))
        self.assertFalse(ff.long_run_enabled({"long_run": {}}))
        self.assertFalse(ff.long_run_enabled({}))
        # A typo must not turn fast-forward on behind your back.
        self.assertFalse(ff.long_run_enabled({"long_run": {"unit": "decade"}}))

    def test_unknown_unit_degrades_to_day(self):
        self.assertEqual(ff.long_run_unit({"long_run": {"unit": "decade"}}), "day")
        self.assertEqual(ff.long_run_unit({"long_run": {"unit": "MONTH"}}), "month")


# ---------------------------------------------------------------------------
# Period digest
# ---------------------------------------------------------------------------

class TestPeriodDigest(unittest.TestCase):
    def _agent(self):
        return {
            "id": 1,
            "name": "李泽宇",
            "state": {
                "emotion": 0.58,
                "stress": 0.62,
                "econ_security": 0.5,
                "city_identity": 0.48,
            },
            "memory": ["上个月一直在赶项目"],
            "social_neighbors": [2],
            "goals": {},
        }

    def _period(self, unit="month"):
        return ff.plan_horizon(1, 31, unit, start_date=date(2026, 1, 15))[0]

    def _config(self, **over):
        block = {"enabled": True, "brief_llm": True, "max_state_delta": 0.15,
                 "randomness": 0, "unit": "month"}
        block.update(over)
        return {"long_run": block}

    def test_delta_cap_widens_with_the_unit(self):
        cfg = self._config()
        self.assertAlmostEqual(ff.max_state_delta_for("day", cfg), 0.15)
        self.assertAlmostEqual(ff.max_state_delta_for("month", cfg), 0.30)
        self.assertAlmostEqual(ff.max_state_delta_for("year", cfg), 0.45)

    def test_digest_uses_the_period_task_and_the_wider_cap(self):
        seen = {}

        def llm(prompt, task=None, agent_id=None):
            seen["task"] = task
            seen["prompt"] = prompt
            return json.dumps(
                {
                    "brief": "这个月换了岗位，节奏慢慢稳下来。",
                    "memory": "换岗后第一次准点下班。",
                    "highlights": ["内部转岗成功", "周末开始跑步", "内部转岗成功"],
                    # Over-cap → clamped to the month cap (0.30), not 0.15.
                    "state_changes": {"emotion": 0.9, "stress": -0.5, "bogus": 1.0},
                    "social": [{"neighbor": 2, "signal": "positive"}],
                },
                ensure_ascii=False,
            )

        d = ff.simulate_agent_period(
            self._agent(),
            period=self._period(),
            base_schedule=[("07:00", "起床"), ("09:00", "工作")],
            agents_by_id={2: {"name": "周婉清"}},
            config=self._config(),
            llm_fn=llm,
        )
        self.assertEqual(seen["task"], "fast_forward_period")
        self.assertIn("2026-01-15", seen["prompt"])
        self.assertEqual(d["state_changes"], {"emotion": 0.30, "stress": -0.30})
        # memory + de-duplicated highlights, capped at 3 for a month.
        self.assertEqual(d["memories"], ["换岗后第一次准点下班。", "内部转岗成功", "周末开始跑步"])
        self.assertEqual(d["burst_count"], 0)  # randomness=0

    def test_day_unit_period_delegates_to_the_day_digest(self):
        seen = []
        ff.simulate_agent_period(
            self._agent(),
            period=self._period("day"),
            base_schedule=[("07:00", "起床")],
            config=self._config(unit="day"),
            llm_fn=lambda p, task=None, agent_id=None: seen.append(task)
            or json.dumps({"brief": "平稳的一天"}, ensure_ascii=False),
        )
        self.assertEqual(seen, ["fast_forward_day"])

    def test_fallback_brief_when_llm_is_off(self):
        d = ff.simulate_agent_period(
            self._agent(),
            period=self._period(),
            base_schedule=[("07:00", "起床")],
            config=self._config(brief_llm=False),
            llm_fn=None,
        )
        self.assertTrue(d["brief"])
        self.assertEqual(d["state_changes"], {})
        self.assertEqual(len(d["memories"]), 1)

    def test_burst_count_scales_with_the_span(self):
        import random as _r

        # r=0 → never, whatever the span.
        self.assertEqual(ff._draw_burst_count(365, 0.0, _r.Random(1)), 0)
        # A day is at most one burst.
        self.assertLessEqual(ff._draw_burst_count(1, 1.0, _r.Random(1)), 1)
        # Longer steps must not be clamped to a day-sized cap: the old flat
        # `_MAX_BURSTS = 4` let a whole year hold no more than a fortnight,
        # which is what made long runs read as empty.
        month = ff._draw_burst_count(30, 1.0, _r.Random(1))
        year = ff._draw_burst_count(365, 1.0, _r.Random(1))
        self.assertGreater(year, month)
        self.assertEqual(ff.event_budget(365)["bursts"], year)
        self.assertGreater(ff.event_budget(365)["bursts"], 4)

    def test_burst_hint_reaches_the_prompt(self):
        prompts = []
        d = ff.simulate_agent_period(
            self._agent(),
            period=self._period(),
            base_schedule=[("07:00", "起床")],
            config=self._config(randomness=1.0),
            llm_fn=lambda p, **k: prompts.append(p)
            or json.dumps({"brief": "起伏的一个月"}, ensure_ascii=False),
        )
        self.assertGreater(d["burst_count"], 0)
        self.assertIn("突发", prompts[0])

    def test_jitter_amplitude_scales_with_the_unit(self):
        import random as _r

        self.assertEqual(ff.jitter_scale_for("day"), 1.0)
        agent = self._agent()
        applied = ff.apply_random_jitter(
            agent, randomness=1.0, rng=_r.Random(1), scale=ff.jitter_scale_for("year")
        )
        for step in applied.values():
            self.assertLessEqual(
                abs(step), ff._JITTER_SCALE * ff.jitter_scale_for("year") + 1e-9
            )

    def test_period_brief_block_is_labelled_by_unit(self):
        block = ff.render_period_brief_block(
            self._period(), [("李泽宇", "换了岗位")], world_line="地铁新线开通"
        )
        self.assertIn("Month 1 简报", block)
        self.assertIn("地铁新线开通", block)


class TestDashboardSpanField(unittest.TestCase):
    """The toolbar's horizon field is expressed in the step unit.

    The browser only ever sends ``{unit, count}``; the calendar math that
    turns "10 年" into 3653 sim days stays on the server, so there is one
    implementation of it rather than a JS approximation next to a Python one.
    """

    def _cfg(self, unit, sim_days, start="2026-01-15"):
        return {
            "sim_days": sim_days,
            "long_run": {"unit": unit},
            "calendar": {"start_date": start},
        }

    def test_span_round_trips_through_the_config_summary(self):
        from gaworld.apps import dashboard_server as ds

        start = date(2026, 1, 15)
        for unit, count in (("day", 30), ("month", 24), ("year", 10)):
            days = ff.span_days(unit, count, start_date=start)
            self.assertEqual(
                ds._sim_span(self._cfg(unit, days)),
                {"unit": unit, "count": count},
                f"{count} {unit}(s) -> {days} days should read back as {count}",
            )

    def test_patch_converts_the_span_to_sim_days(self):
        from unittest.mock import patch

        from gaworld.apps import dashboard_server as ds

        with patch.object(ds, "_effective_config", lambda: self._cfg("month", 30)):
            patched = ds._sanitize_config_patch(
                {"sim_span": {"unit": "month", "count": 3}}
            )
        # Jan 15 + 3 months = Apr 15 -> 31 + 28 + 31 days.
        self.assertEqual(patched["sim_days"], 90)

    def test_saving_a_coarse_unit_also_ticks_fast_forward(self):
        """The saved file must describe the run that will actually happen."""
        from gaworld.apps import dashboard_server as ds

        patched = ds._sanitize_config_patch(
            {"long_run": {"unit": "year", "enabled": False}}
        )
        self.assertEqual({"unit": "year", "enabled": True}, patched["long_run"])
        # Switching back to 天 leaves the checkbox under the user's control.
        patched = ds._sanitize_config_patch(
            {"long_run": {"unit": "day", "enabled": False}}
        )
        self.assertEqual({"unit": "day", "enabled": False}, patched["long_run"])

    def test_span_wins_over_a_stale_sim_days(self):
        from unittest.mock import patch

        from gaworld.apps import dashboard_server as ds

        with patch.object(ds, "_effective_config", lambda: self._cfg("year", 30)):
            patched = ds._sanitize_config_patch(
                {"sim_days": 2, "sim_span": {"unit": "year", "count": 1}}
            )
        self.assertEqual(patched["sim_days"], 365)


class TestCoarseProgressParsing(unittest.TestCase):
    """`parallel.runner.latest_day` reads the run banner for progress."""

    def test_coarse_banner_reports_the_step_last_sim_day(self):
        from gaworld.parallel import runner

        period = ff.plan_horizon(1, 100, "month", start_date=date(2026, 1, 15))[2]
        # Mirrors the banner generative_city_sim prints for a coarse step.
        banner = (f"================= {period.title} · Day {period.end_day} "
                  f"({period.describe()}) =================")
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "run.log")
            with open(path, "w", encoding="utf-8") as fh:
                # The goal-text decoy the anchored regex exists to reject.
                fh.write(f"- 短期[stg1]：目标 Day 999\n{banner}\n")
            self.assertEqual(runner.latest_day(path), period.end_day)


# ---------------------------------------------------------------------------
# Coarse action space (life moves) and event space (period environment)
# ---------------------------------------------------------------------------

class TestCoarseActionSpace(unittest.TestCase):
    """A month/year step's action space is life moves, not a daily routine."""

    def _period(self, unit="year"):
        return ff.plan_horizon(1, 365, unit, start_date=date(2026, 1, 1))[0]

    def _agent(self):
        return {"id": 1, "name": "A", "state": {"emotion": 0.5, "stress": 0.5},
                "memory": [], "social_neighbors": [], "goals": {}}

    def _config(self):
        return {"long_run": {"enabled": True, "brief_llm": True, "unit": "year",
                             "randomness": 0}}

    def test_catalog_comes_from_the_life_event_templates(self):
        """Every offered move must be one the simulator can actually apply."""
        from gaworld.events.life import list_life_event_templates

        known = {t["key"] for t in list_life_event_templates()}
        for unit in ("month", "year"):
            offered = {item["key"] for item in ff.life_move_catalog(unit)}
            self.assertTrue(offered)
            self.assertTrue(
                offered <= known,
                "the menu and the machinery that applies it must not drift apart",
            )

    def test_a_month_and_a_year_get_different_action_spaces(self):
        """A year is not a long month.

        Both units used to be handed the identical eight templates, so one
        bout of flu was as available to a year as to a month, while the moves
        a year is actually made of — moving house, going back to study,
        starting a business — did not exist at all.
        """
        month = {item["key"] for item in ff.life_move_catalog("month")}
        year = {item["key"] for item in ff.life_move_catalog("year")}
        self.assertNotEqual(month, year)
        # Long-range moves belong to the year, and are new.
        for key in ("job_change", "relocation", "further_study", "entrepreneurship"):
            self.assertIn(key, year, f"{key} should be available over a year")
            self.assertNotIn(key, month, f"{key} is not a month-sized move")
        # A day-scale disruption is a month's texture, not a year's headline.
        self.assertIn("illness", month)
        self.assertNotIn("illness", year)
        # Mid-range moves are shared by both.
        self.assertTrue({"promotion", "relationship_break"} <= month & year)

    def test_state_focus_and_outcomes_differ_by_scale(self):
        """A year's meaning sits in the slow variables, and must resolve."""
        self.assertIn("慢变量", ff._STATE_FOCUS["year"])
        self.assertIn("mobility_intent", ff._STATE_FOCUS["year"])
        self.assertIn("基本不会有明显变化", ff._STATE_FOCUS["month"])
        self.assertIn("必须交代结果", ff._OUTCOME_HINT["year"])

    def test_an_untagged_template_stays_available(self):
        """A user-added template must not silently vanish from the menu."""
        from unittest.mock import patch

        from gaworld.events import life

        extra = dict(life.LIFE_EVENT_TEMPLATES[0])
        extra.update({"key": "custom_thing", "title": "自定义", "description": "x"})
        extra.pop("scale", None)
        with patch.object(life, "LIFE_EVENT_TEMPLATES", [extra]):
            for unit in ("month", "year"):
                self.assertEqual(
                    ["custom_thing"], [i["key"] for i in ff.life_move_catalog(unit)]
                )

    def test_the_menu_reaches_the_period_prompt(self):
        seen = {}
        ff.simulate_agent_period(
            self._agent(), period=self._period(), base_schedule=[("07:00", "起床")],
            config=self._config(),
            llm_fn=lambda p, **k: seen.setdefault("p", p) and "" or json.dumps(
                {"brief": "平稳的一年"}, ensure_ascii=False),
        )
        self.assertIn("job_change=换工作", seen["p"])
        self.assertIn("life_moves", seen["p"])

    def test_moves_are_whitelisted_to_applicable_keys(self):
        d = ff.simulate_agent_period(
            self._agent(), period=self._period(), base_schedule=[("07:00", "起床")],
            config=self._config(),
            llm_fn=lambda p, **k: json.dumps({
                "brief": "换了工作",
                "life_moves": [
                    {"key": "job_change", "new_job": "数据分析师", "note": "想换方向"},
                    {"key": "moved_to_mars"},   # not a template → dropped
                    {"key": "job_change"},      # duplicate → dropped
                    {"key": "illness"},         # day-scale → not a year's move
                    {"key": "relocation", "note": "搬到城东"},
                ],
            }, ensure_ascii=False),
        )
        self.assertEqual(
            ["job_change", "relocation"], [m["key"] for m in d["life_moves"]],
            "unknown, duplicate and out-of-scale keys must all be dropped",
        )
        self.assertEqual(d["life_moves"][0]["new_job"], "数据分析师")

    def test_a_day_step_keeps_its_own_action_space(self):
        """Day digests are unchanged — no life-move menu, no life_moves."""
        seen = {}
        d = ff.simulate_agent_period(
            self._agent(), period=ff.plan_horizon(1, 1, "day", start_date=date(2026, 1, 1))[0],
            base_schedule=[("07:00", "起床")],
            config={"long_run": {"enabled": True, "brief_llm": True, "unit": "day",
                                 "randomness": 0}},
            llm_fn=lambda p, **k: seen.setdefault("p", p) and "" or json.dumps(
                {"brief": "平稳的一天"}, ensure_ascii=False),
        )
        self.assertNotIn("life_moves", seen["p"])
        self.assertEqual(d.get("life_moves", []), [])


class TestCoarseEventSpace(unittest.TestCase):
    """A month/year step's environment is structural, not one day's weather."""

    def _env(self, **over):
        from environment import EnvironmentSystem

        cfg = {"external_environment": {
            "enabled": True, "generator_mode": "rules",
            "natural": {"enabled": True, "daily_weather_chance": 1.0},
        }}
        cfg["external_environment"].update(over)
        return EnvironmentSystem(cfg)

    def test_a_day_step_still_draws_the_weather(self):
        env = self._env()
        events = env.start_day(1, day_context={"sim_date": "2026-01-01"})
        self.assertTrue(any(e.get("type") == "natural" for e in events),
                        f"expected a weather event in a day step: {events}")

    def test_a_coarse_step_drops_the_daily_weather_draw(self):
        env = self._env()
        events = env.start_day(
            365, day_context={"sim_date": "2026-01-01"},
            span={"days": 365, "unit": "year", "label": "第1年"},
        )
        self.assertFalse(
            any(e.get("type") == "natural" for e in events),
            "one day's weather is not a year's environment",
        )

    def test_a_coarse_step_asks_the_llm_at_the_right_scale(self):
        from environment import EnvironmentSystem

        prompts = []

        def llm(prompt, task=None, agent_id=None):
            prompts.append((task, prompt))
            return json.dumps({"day_summary": "行业收缩，房租下行",
                               "day_events": [], "intraday_rules": {"x": 1}},
                              ensure_ascii=False)

        env = EnvironmentSystem(
            {"external_environment": {"enabled": True, "generator_mode": "llm"}},
            llm_fn=llm,
        )
        env.start_day(30, day_context={"sim_date": "2026-01-01"},
                      span={"days": 30, "unit": "month", "label": "第1月"})
        task, prompt = prompts[0]
        self.assertEqual(task, "external_environment_period")
        self.assertIn("这一月", prompt)
        # The requested JSON schema has no intraday_rules field...
        self.assertNotIn('"intraday_rules"', prompt)
        # ...and any the model volunteers are discarded: without ticks there
        # is nothing to roll them against.
        self.assertEqual({}, env._intraday_rules)


class TestLongHorizonFrame(unittest.TestCase):
    """A long step simulates a life, not a timetable.

    The digest's frame has to change with the span: standing circumstances,
    the arc so far, where skills and relationships currently stand — not a
    daily routine and three memory lines from one week of a year.
    """

    def _period(self, unit="year"):
        return ff.plan_horizon(1, 365, unit, start_date=date(2026, 1, 1))[0]

    def _agent(self):
        return {
            "id": 1, "name": "李泽宇", "age": 34, "job": "软件工程师",
            "state": {"emotion": 0.5, "stress": 0.5},
            "memory": ["昨天加班"], "social_neighbors": [2],
            "relationships": {"2": {"closeness": 0.72, "trust": 0.6, "role": "同事"}},
            "growth_profile": {"items": [
                {"name": "阅读", "level": 0.30, "weekly_target_minutes": 120},
            ]},
            "_period_briefs": ["Year 1：换了工作，搬到城东"],
            "household": {"type_zh": "夫妻二人"},
        }

    def _prompt_for(self, agent):
        seen = {}

        def llm(prompt, task=None, agent_id=None):
            seen["p"] = prompt
            return json.dumps({"brief": "平稳的一年"}, ensure_ascii=False)

        ff.simulate_agent_period(
            agent, period=self._period(), base_schedule=[("07:00", "起床")],
            agents_by_id={2: {"name": "周婉清"}},
            config={"long_run": {"enabled": True, "brief_llm": True, "unit": "year",
                                 "randomness": 0}},
            llm_fn=llm,
        )
        return seen["p"]

    def test_the_frame_is_the_situation_not_the_timetable(self):
        prompt = self._prompt_for(self._agent())
        for probe in ("34岁", "软件工程师", "夫妻二人"):
            self.assertIn(probe, prompt, f"{probe} should anchor a long step")
        # The routine survives only as a prose overview, explicitly demoted,
        # and never as a clock table.
        self.assertIn("平时概况", prompt)
        self.assertIn("不要逐日展开", prompt)
        # Events first, then the general picture.
        self.assertLess(prompt.index('"highlights"'), prompt.index('"brief"'))

    def test_it_sees_the_arc_so_far_not_just_last_week(self):
        prompt = self._prompt_for(self._agent())
        self.assertIn("Year 1：换了工作，搬到城东", prompt)

    def test_it_sees_where_skills_and_relationships_stand(self):
        prompt = self._prompt_for(self._agent())
        self.assertIn("水平0.30", prompt)      # development needs a baseline
        self.assertIn("亲密度0.72", prompt)    # so does a relationship trajectory
        self.assertIn("周婉清", prompt)

    def test_the_routine_is_prose_not_a_clock_table(self):
        """"平时概况" means an overview, not a timetable.

        Rendering the schedule as ``07:00 起床；08:00 通勤；…`` invited the
        model to reason per-slot, and truncating that list made it worse: it
        stopped at lunch, so a whole year was framed as "gets up, commutes,
        works, has lunch".
        """
        agent = self._agent()
        agent["daily_life"] = "工作日朝九晚六，通勤一小时"
        overview = ff._routine_overview_text(agent, [
            ("07:00", "起床"), ("09:00", "工作"), ("18:00", "下班通勤"), ("23:00", "睡觉"),
        ])
        self.assertIn("工作日朝九晚六", overview)   # the authored overview
        self.assertIn("07:00 起", overview)          # the shape of the day
        self.assertIn("23:00 睡", overview)
        self.assertNotIn("；09:00 工作", overview)   # ...but not slot by slot

    def test_a_fragment_of_a_schedule_is_not_described_as_a_rhythm(self):
        # One entry gave "作息大致 07:00 起、07:00 睡".
        self.assertEqual("（无）", ff._routine_overview_text({}, [("07:00", "起床")]))
        self.assertEqual("（无）", ff._routine_overview_text({}, []))

    def test_every_event_budget_grows_with_the_span(self):
        """Day-sized caps are what made a simulated year feel empty.

        Each of these was a flat constant: bursts 4, highlights 4, life moves
        2 — so a year was allowed no more to happen in it than a fortnight,
        no matter what the randomness setting said (at r=0.3 a year *expects*
        ~33 unplanned events and got 4).
        """
        day, month, year = (ff.event_budget(n) for n in (1, 30, 365))
        for key in ("bursts", "highlights", "life_moves", "env_events"):
            self.assertLessEqual(day[key], month[key], key)
            self.assertLess(month[key], year[key], f"a year must hold more than a month: {key}")
        # A single day keeps its old shape exactly.
        self.assertEqual(1, day["bursts"])
        # ...and the caps stay caps: a brief is a summary, not a chronicle.
        self.assertLessEqual(year["highlights"], 10)
        self.assertLessEqual(year["life_moves"], 3)

    def test_a_coarse_fallback_brief_is_not_a_timetable(self):
        """The fallback never sees the prompt, so it needed fixing separately.

        A real year-granularity run printed
        ``原计划（06:30 起床洗漱；07:00 送儿子去幼儿园；08:00 高峰配送…）被计划外的事打断``
        as the summary of a whole year: the digest fell back, and the fallback
        rendered a truncated daily timetable regardless of span.
        """
        agent = {"id": 1, "name": "马志勇", "age": 38, "job": "外卖配送员",
                 "household": {"type_zh": "三口之家"}}
        schedule = [("06:30", "起床洗漱"), ("07:00", "送儿子去幼儿园"),
                    ("08:00", "高峰配送"), ("10:30", "路线规划练习")]
        for unit in ("month", "year"):
            digest = ff._fallback_digest(
                agent, day=365, base_schedule=schedule, brief_max_chars=480,
                burst=True, unit=unit, span_desc="第1年",
            )
            brief = digest["brief"]
            self.assertNotIn("06:30", brief, f"{unit} fallback still lists clock times")
            self.assertNotIn("原计划", brief)
            self.assertIn("外卖配送员", brief)   # described by situation instead
            self.assertTrue(digest["fallback"])
        # A single day may still be described by its plan.
        day = ff._fallback_digest(
            agent, day=1, base_schedule=schedule, brief_max_chars=240, burst=True,
        )
        self.assertIn("06:30", day["brief"])

    def test_an_unusable_response_is_reported_not_swallowed(self):
        """A provider returning junk every step must not look like quiet years."""
        period = ff.plan_horizon(1, 365, "year", start_date=date(2026, 1, 1))[0]
        with self.assertLogs("gaworld.sim.fastforward", level="WARNING") as logs:
            digest = ff.simulate_agent_period(
                {"id": 1, "name": "A", "age": 30, "state": {"emotion": 0.5},
                 "memory": [], "social_neighbors": [], "relationships": {}},
                period=period, base_schedule=[("07:00", "起床")],
                config={"long_run": {"enabled": True, "brief_llm": True,
                                     "unit": "year", "randomness": 0}},
                llm_fn=lambda p, **k: "sorry, I cannot help with that",
            )
        self.assertTrue(digest["fallback"])
        self.assertTrue(any("no usable brief" in line for line in logs.output))

    def test_development_is_clamped_to_a_plausible_week(self):
        self.assertEqual([], ff._normalize_development("not a list"))
        self.assertEqual([], ff._normalize_development([{"item": "阅读", "weekly_minutes": 0}]))
        out = ff._normalize_development([
            {"item": "阅读", "weekly_minutes": 99999},   # → capped
            {"item": "阅读", "weekly_minutes": 60},      # → duplicate dropped
            {"item": "", "weekly_minutes": 60},          # → unnamed dropped
        ])
        self.assertEqual(1, len(out))
        self.assertEqual(1200.0, out[0]["weekly_minutes"])


class TestSocialInfluence(unittest.TestCase):
    """Over a long step a relationship has a *trajectory*, not a ping."""

    def _agent(self):
        return {
            "id": 1, "name": "A", "age": 34, "job": "工程师",
            "state": {"emotion": 0.5}, "memory": [], "social_neighbors": [2],
            "relationships": {
                "2": {"closeness": 0.72, "trust": 0.60, "role": "coworker",
                      "decay_rate": 0.006, "last_contact_day": 10},
                "3": {"closeness": 0.50, "trust": 0.50, "role": "friend",
                      "decay_rate": 0.008, "last_contact_day": 10},
            },
        }

    def test_moves_and_new_ties_are_whitelisted(self):
        """Unconstrained, the digest invents neighbours."""
        period = ff.plan_horizon(1, 365, "year", start_date=date(2026, 1, 1))[0]
        d = ff.simulate_agent_period(
            self._agent(), period=period, base_schedule=[("07:00", "起床")],
            agents_by_id={2: {"name": "B"}, 7: {"name": "C"}},
            config={"long_run": {"enabled": True, "brief_llm": True, "unit": "year",
                                 "randomness": 0}},
            llm_fn=lambda p, **k: json.dumps({
                "brief": "x",
                "relationships": [
                    {"neighbor": "2", "closeness_delta": 0.2},
                    {"neighbor": "404", "closeness_delta": 0.2},   # unknown tie
                    {"neighbor": "3", "closeness_delta": 0},       # no-op
                ],
                "new_ties": [
                    {"neighbor": "7", "role": "coworker"},
                    {"neighbor": "2", "role": "friend"},           # already known
                    {"neighbor": "404", "role": "friend"},         # does not exist
                ],
            }, ensure_ascii=False),
        )
        self.assertEqual(["2"], [m["neighbor"] for m in d["relationships"]])
        self.assertEqual(["7"], [t["neighbor"] for t in d["new_ties"]])

    def test_drifting_apart_keeps_decaying(self):
        """A negative move must not reset the decay clock.

        Growing apart *is* the absence of contact; stamping `last_contact_day`
        on it would freeze the tie at its new value instead of letting it keep
        sliding.
        """
        from gaworld.social.network import apply_closeness_delta

        agent = self._agent()
        apply_closeness_delta(agent, "3", -0.2, current_day=200)
        self.assertEqual(10, agent["relationships"]["3"]["last_contact_day"])
        apply_closeness_delta(agent, "2", 0.2, current_day=200)
        self.assertEqual(200, agent["relationships"]["2"]["last_contact_day"])

    def test_closeness_delta_is_capped_and_trust_lags(self):
        from gaworld.social.network import apply_closeness_delta

        agent = self._agent()
        applied = apply_closeness_delta(agent, "3", 5.0, current_day=200, max_delta=0.25)
        self.assertEqual(0.25, applied["delta"])
        self.assertAlmostEqual(0.75, agent["relationships"]["3"]["closeness"])
        # Trust follows at half rate — slower to build, slower to lose.
        self.assertAlmostEqual(0.625, agent["relationships"]["3"]["trust"])

    def test_a_job_change_retires_the_colleagues_it_came_with(self):
        """SOCIAL_NETWORK_DESIGN.md §6 — the trigger that was missing."""
        from gaworld.social.network import retire_work_ties, role_config

        agent = self._agent()
        changed = retire_work_ties(agent, current_day=200)
        self.assertEqual(["2"], changed)
        tie = agent["relationships"]["2"]
        self.assertEqual("former_coworker", tie["role"])
        # The rate has to be rewritten, not just the label: the schema filler
        # uses setdefault, so a role change alone would keep 0.006 forever.
        self.assertEqual(role_config("former_coworker")["decay_rate"], tie["decay_rate"])
        self.assertGreater(tie["decay_rate"], 0.006)
        # A friend is not a colleague.
        self.assertEqual("friend", agent["relationships"]["3"]["role"])


class TestLifeStageAndHousehold(unittest.TestCase):
    """A long run has to move the person, not just the day counter."""

    def test_life_stage_follows_age(self):
        from gaworld.events.life import life_stage

        self.assertEqual("young_adult", life_stage({"age": 22})[0])
        self.assertEqual("midlife", life_stage({"age": 40})[0])
        self.assertEqual("retirement", life_stage({"age": 63})[0])
        self.assertEqual("elderly", life_stage({"age": 80})[0])
        # A missing age must not crash a prompt mid-run.
        self.assertEqual("midlife", life_stage({})[0])
        self.assertEqual("midlife", life_stage({"age": "abc"})[0])

    def test_the_stage_reaches_the_digest_frame(self):
        """Ageing with nothing consuming it is just a counter ticking."""
        young = ff._situation_text({"age": 30, "job": "工程师"})
        old = ff._situation_text({"age": 63, "job": "工程师"})
        self.assertIn("青年", young)
        self.assertIn("退休年龄", old)
        self.assertNotEqual(young, old)

    def test_household_members_age_and_children_move_out(self):
        """A five-year-old must not still be five after a decade."""
        from gaworld.family.plugin import FamilyPlugin

        plugin = FamilyPlugin()
        record = {"members": [
            {"key": "c1", "name": "小雨", "role": "child", "age": 16, "coresident": True},
            {"key": "p1", "name": "母亲", "role": "mother", "age": 68, "coresident": True},
        ]}
        agent = {"id": 1, "name": "A"}

        class _Ctx:
            config = {}

            def agent_ext(self, _agent, _plugin_id):
                return record

        plugin._record_for = lambda ctx, a: record  # noqa: ARG005
        hook_ctx = {"sim": _Ctx(), "agents": [agent], "day": 1095,
                    "period_days": 365 * 3, "daily_logs": {1: ""}}
        plugin._age_household(hook_ctx)

        self.assertEqual(19, record["members"][0]["age"], "the child did not age")
        self.assertEqual(71, record["members"][1]["age"], "the parent did not age")
        # Crossing adulthood is the one composition change ageing alone implies.
        self.assertFalse(record["members"][0]["coresident"])
        self.assertTrue(record["members"][1]["coresident"])
        self.assertIn("成年离家", hook_ctx["daily_logs"][1])

    def test_household_ageing_accumulates_across_short_steps(self):
        """Short steps must accumulate, not round to zero every time.

        Dividing the span per step would age nobody at month granularity
        (30/365 rounds to 0), so the remainder is carried between steps.
        """
        from gaworld.family.plugin import FamilyPlugin

        plugin = FamilyPlugin()
        record = {"members": [
            {"key": "c1", "name": "小雨", "role": "child", "age": 8, "coresident": True},
        ]}
        plugin._record_for = lambda ctx, a: record  # noqa: ARG005

        class _Ctx:
            config = {}

        def _step(n):
            for i in range(n):
                plugin._age_household({
                    "sim": _Ctx(), "agents": [{"id": 1, "name": "A"}],
                    "day": 30 * (i + 1), "period_days": 30, "daily_logs": {1: ""},
                })

        _step(12)  # 360 days — genuinely short of a year
        self.assertEqual(8, record["members"][0]["age"])
        _step(1)   # 390 days — the carried remainder tips it over
        self.assertEqual(9, record["members"][0]["age"])


class TestFamilyLifecycle(unittest.TestCase):
    """Marriage, childbirth and bereavement change the household, not the prose."""

    def _record(self):
        return {"marital_status": "never", "members": [
            {"key": "p1", "name": "母亲", "role": "mother", "age": 71,
             "coresident": True, "kind": "ghost"},
        ]}

    def _agent(self, age=30):
        return {"id": 1, "name": "李泽宇", "age": age, "gender": "男"}

    def test_household_type_is_derived_from_who_lives_there(self):
        from gaworld.family.lifecycle import derive_household_type

        self.assertEqual("with_parents", derive_household_type(self._record()))
        self.assertEqual("single", derive_household_type({"members": []}))

    def test_the_arc_marriage_child_bereavement(self):
        import random

        from gaworld.family import lifecycle as lc

        rng, record, agent = random.Random(7), self._record(), self._agent()
        self.assertFalse(lc.can_bear_child(agent, record), "no partner yet")

        self.assertEqual("multigen", lc.marry(record, agent, day=365, rng=rng)["household_type"])
        self.assertEqual("married", record["marital_status"])
        self.assertIsNone(lc.marry(record, agent, day=400, rng=rng), "cannot marry twice")

        born = lc.bear_child(record, agent, day=730, rng=rng)
        self.assertEqual(0, born["member"]["age"])

        lost = lc.bereave(record, agent, day=1095, rng=rng)
        self.assertEqual("母亲", lost["member"]["name"])
        # Kept on the record, not deleted: a parent who died is not a parent
        # who never existed.
        self.assertTrue(lost["member"]["deceased"])
        self.assertFalse(lost["member"]["coresident"])
        self.assertEqual("nuclear", lost["household_type"])
        self.assertIsNone(lc.bereave(record, agent, day=1200, rng=rng))

    def test_eligibility_has_exactly_one_rule_table(self):
        """Two tables for one question is how a fix lands on one path only.

        The digest's action menu and the dashboard's candidate ranking both
        ask "can this person do this?". They used to answer it from separate
        code — `life_move_eligible` reading the agent, and the candidate
        `gate` rules reading a context dict — so tightening one left the other
        wrong.
        """
        import inspect

        from gaworld.events import life

        source = inspect.getsource(life.life_move_eligible)
        self.assertIn("candidate_applies", source)
        # The adapter must not re-implement any rule of its own.
        for smell in ("age >=", "age <=", "child_count", "has_partner"):
            self.assertNotIn(smell, source, f"{smell} looks like a second rule table")

    def test_the_two_callers_agree(self):
        """Same person, same question, same answer on both paths."""
        from gaworld.events.candidates import candidate_applies, context_from_agent
        from gaworld.events.life import life_move_eligible

        people = [
            {"age": 28, "employment": "employed",
             "family_facts": {"marital_status": "married", "has_partner": True,
                              "child_count": 0, "oldest_elder_age": 70}},
            {"age": 66, "employment": "employed",
             "family_facts": {"marital_status": "married", "has_partner": True,
                              "child_count": 2, "oldest_elder_age": None}},
            {"age": 40, "employment": "retired",
             "family_facts": {"marital_status": "never", "has_partner": False,
                              "child_count": 0, "oldest_elder_age": None}},
        ]
        for agent in people:
            ctx = context_from_agent(agent)
            for key in ("marriage", "childbirth", "bereavement", "retirement", "job_change"):
                self.assertEqual(
                    candidate_applies(key, ctx), life_move_eligible(key, agent),
                    f"{key} disagrees for age {agent['age']}",
                )

    def test_eligibility_blocks_the_absurd(self):
        from gaworld.events.life import life_move_eligible

        married = {"has_partner": True, "child_count": 0,
                   "marital_status": "married", "oldest_elder_age": None}
        self.assertFalse(life_move_eligible(
            "childbirth", {"age": 70, "family_facts": married}))
        self.assertFalse(life_move_eligible(
            "marriage", {"age": 40, "family_facts": married}))
        self.assertFalse(life_move_eligible("retirement", {"age": 28}))
        self.assertTrue(life_move_eligible("retirement", {"age": 63}))
        # A retiree does not change jobs or get laid off.
        self.assertFalse(life_move_eligible(
            "job_change", {"age": 66, "employment": "retired"}))
        # Nobody to lose -> not offered.
        self.assertFalse(life_move_eligible(
            "bereavement", {"age": 40, "family_facts": {
                "oldest_elder_age": None, "has_partner": False, "child_count": 0}}))

    def test_the_menu_is_filtered_per_person(self):
        young = {"age": 28, "family_facts": {
            "has_partner": True, "child_count": 0, "marital_status": "married"}}
        old = {"age": 66, "employment": "employed", "family_facts": {
            "has_partner": True, "child_count": 2, "marital_status": "married"}}
        young_keys = {c["key"] for c in ff.life_move_catalog("year", young)}
        old_keys = {c["key"] for c in ff.life_move_catalog("year", old)}
        self.assertIn("childbirth", young_keys)
        self.assertNotIn("retirement", young_keys)
        self.assertIn("retirement", old_keys)
        self.assertNotIn("childbirth", old_keys)

    def test_retirement_is_not_unemployment(self):
        """A pension is permanent; a layoff is a spell you recover from."""
        from gaworld.economy.finance import apply_employment_event

        agent = {"id": 1, "name": "A", "age": 61, "job": "工程师", "economy": {
            "base_hourly_income": 60.0, "accounts": {"checking": 1000.0},
            "daily_income": 0.0, "lifetime_income": 0.0, "income_skill": 0.5,
            "shock_log": [],
        }}
        change = apply_employment_event(
            agent, {"template_key": "retirement", "impact_tags": ["employment"]}, {})
        self.assertEqual("retirement", change["type"])
        self.assertEqual("已退休", agent["job"])
        self.assertEqual("retired", agent["employment"])
        self.assertLess(change["to_hourly"], change["from_hourly"])
        # No recovery countdown and no remembered job, so the re-hire path
        # that brings a laid-off agent back can never fire for a retiree.
        self.assertNotIn("_layoff_days_remaining", agent["economy"])
        self.assertNotIn("previous_job", agent["economy"])

    def test_the_household_brief_reaches_the_digest_frame(self):
        """`agent["household"]` is never set; the brief lives in `family`."""
        text = ff._situation_text(
            {"age": 34, "job": "工程师", "family": "与妻子和一个上小学的女儿同住"})
        self.assertIn("与妻子", text)


# ---------------------------------------------------------------------------
# Economy under a coarse step
# ---------------------------------------------------------------------------

def _econ_agent(agent_id=1, job="软件工程师", age=30):
    return {
        "id": agent_id,
        "name": f"A{agent_id}",
        "age": age,
        "job": job,
        "personality": "上进务实",
        "values": "重视稳定和成长",
        "daily_life": "规律生活",
        "state": {"emotion": 0.5, "stress": 0.5, "econ_security": 0.5,
                  "risk_preference": 0.5},
    }


def _econ_config(tmpdir, **econ_over):
    economy = {
        "enabled": True,
        "output_dir": os.path.join(tmpdir, "economy"),
        "hours_per_step": 1.0,
    }
    economy.update(econ_over)
    return {
        "stateful": False,
        "random_seed": 7,
        "memory_dir": os.path.join(tmpdir, "memory"),
        "log_dir": os.path.join(tmpdir, "logs"),
        "economy": economy,
    }


class TestEconomyCoarseStep(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)

    def _start(self, **econ_over):
        config = _econ_config(self.tmpdir.name, **econ_over)
        agent = _econ_agent()
        ext = {}
        eco.on_simulation_start(
            {"config": config, "agents": [agent], "extension_state": ext}
        )
        return config, agent, ext

    def _ctx(self, config, agent, ext, day, **extra):
        ctx = {"config": config, "day": day, "agents": [agent],
               "daily_logs": {agent["id"]: ""}, "extension_state": ext}
        ctx.update(extra)
        return ctx

    def test_fixed_costs_scale_with_the_span(self):
        """One 30-day emission books what 30 daily emissions book."""
        quiet = {"shocks": {"enabled": False},
                 "macro": {"enabled": False},
                 "investment": {"enabled": False, "auto_save_enabled": False}}
        config, agent, ext = self._start(**quiet)
        for day in range(1, 31):
            eco.on_day_start(self._ctx(config, agent, ext, day))
        daily_expense = agent["economy"]["lifetime_expense"]

        config2, agent2, ext2 = self._start(**quiet)
        eco.on_day_start(self._ctx(config2, agent2, ext2, 1, period_days=30))
        # Equal up to cent-rounding: 30 rounded payments vs one rounded payment.
        self.assertAlmostEqual(
            agent2["economy"]["lifetime_expense"], daily_expense, delta=0.5)
        self.assertEqual(ext2["economy_module"]["sim_day_counter"], 30)

    def test_coarse_step_books_wages_that_no_tick_credited(self):
        config, agent, ext = self._start()
        econ = agent["economy"]
        eco.on_day_start(self._ctx(config, agent, ext, 1, period_days=30, coarse=True))
        eco.on_day_end(self._ctx(config, agent, ext, 30, period_days=30, coarse=True))
        self.assertGreater(econ["daily_income"], 0.0)
        # The wage is in the monthly tax base, and money is conserved.
        self.assertAlmostEqual(
            eco._system_total([agent], ext["economy_module"]["sectors"]),
            ext["economy_module"]["initial_system_total"],
            places=2,
        )

    def test_no_proxy_wage_when_ticks_already_ran(self):
        config, agent, ext = self._start()
        eco.on_day_start(self._ctx(config, agent, ext, 1, coarse=True))
        eco.on_agent_post_step({
            "config": config, "day": 1, "time_str": "10:00", "agent": agent,
            "step": {"activity": "工作", "action": "推进任务", "location": "Office"},
            "daily_logs": {1: ""}, "extension_state": ext,
        })
        tick_income = agent["economy"]["daily_income"]
        self.assertGreater(tick_income, 0.0)
        eco.on_day_end(self._ctx(config, agent, ext, 1, coarse=True))
        self.assertAlmostEqual(agent["economy"]["daily_income"], tick_income, places=2)

    def test_a_coarse_year_settles_twelve_months_and_conserves_money(self):
        config, agent, ext = self._start()
        runtime = ext["economy_module"]
        initial_total = runtime["initial_system_total"]
        period = ff.plan_horizon(1, 365, "year", start_date=date(2026, 1, 1))[0]
        for end_day, days in ff.plan_hook_chunks(period, 30):
            common = {"period_days": days, "coarse": True}
            eco.on_day_start(self._ctx(config, agent, ext, end_day - days + 1, **common))
            eco.on_day_end(self._ctx(config, agent, ext, end_day, **common))
        self.assertEqual(runtime["sim_month_counter"], 12)
        self.assertAlmostEqual(
            eco._system_total([agent], runtime["sectors"]), initial_total, places=2)
        # A year of earning and spending, not a year of pure drain.
        self.assertGreater(agent["economy"]["lifetime_income"], 0.0)

    def test_month_settlement_fires_once_per_boundary_crossed(self):
        config, agent, ext = self._start()
        runtime = ext["economy_module"]
        # Two 20-day emissions cross the day-30 boundary exactly once.
        for end_day, days in ((20, 20), (40, 20)):
            eco.on_day_start(self._ctx(config, agent, ext, end_day - days + 1,
                                       period_days=days, coarse=True))
            eco.on_day_end(self._ctx(config, agent, ext, end_day,
                                     period_days=days, coarse=True))
        self.assertEqual(runtime["sim_month_counter"], 1)


# ---------------------------------------------------------------------------
# E2E smoke — a 3-month run
# ---------------------------------------------------------------------------

def _has_dep(name: str) -> bool:
    try:
        importlib.import_module(name)
        return True
    except ImportError:
        return False


_REQUIRED = ("networkx", "matplotlib", "matplotlib.pyplot")
_MISSING = [m for m in _REQUIRED if not _has_dep(m)]
_PY_OK = sys.version_info >= (3, 11)


@unittest.skipIf(_MISSING, f"missing runtime deps: {_MISSING}")
@unittest.skipUnless(_PY_OK, "requires Python 3.11+ (datetime.UTC)")
class TestLongHorizonE2E(unittest.TestCase):
    """2-agent runs at ``long_run.unit`` = ``month`` (3 steps) and ``year``."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        data_src = os.path.join(repo_root, "data")
        data_dst = os.path.join(self.tmp.name, "data")
        if os.path.isdir(data_src):
            shutil.copytree(data_src, data_dst)
        original_cwd = os.getcwd()
        os.chdir(self.tmp.name)
        self.addCleanup(os.chdir, original_cwd)

    def _patch_config(self, sim_days: int, unit: str = "month") -> None:
        from gaworld.settings import CONFIG

        originals: dict[str, object] = {}
        for key in (
            "agent_ids", "sim_days", "stateful", "simulate_realtime",
            "seconds_per_day", "news", "human_realism", "intervention",
            "external_environment_service", "distributed", "visualization",
            "life_events", "external_rag", "long_run", "calendar",
        ):
            if key in CONFIG:
                originals[key] = CONFIG[key]
        self.addCleanup(lambda: CONFIG.update(originals))

        CONFIG["agent_ids"] = [4, 5]
        CONFIG["sim_days"] = sim_days
        CONFIG["stateful"] = False
        CONFIG["simulate_realtime"] = False
        CONFIG["seconds_per_day"] = 1
        CONFIG["long_run"] = {
            "enabled": True, "brief_llm": True, "unit": unit,
            "max_state_delta": 0.15, "hook_chunk_days": 30,
        }
        for key, sub in (("news", "enabled"), ("intervention", "enabled"),
                         ("external_environment_service", "enabled"),
                         ("distributed", "enabled"), ("visualization", "enabled"),
                         ("life_events", "enabled")):
            if isinstance(CONFIG.get(key), dict):
                CONFIG[key] = dict(CONFIG[key])
                CONFIG[key][sub] = False
        if isinstance(CONFIG.get("news"), dict):
            CONFIG["news"]["info_seek"] = dict(CONFIG["news"].get("info_seek", {}))
            CONFIG["news"]["info_seek"]["enabled"] = False
        if isinstance(CONFIG.get("external_rag"), dict):
            CONFIG["external_rag"] = dict(CONFIG["external_rag"])
            CONFIG["external_rag"]["bootstrap"] = dict(
                CONFIG["external_rag"].get("bootstrap", {}))
            CONFIG["external_rag"]["bootstrap"]["enabled"] = False

    def _run(self, unit: str, count: int, mock=None) -> tuple[object, int]:
        import generative_city_sim as sim

        sim_days = ff.span_days(unit, count, start_date=sim.SIM_START_DATE)
        self._patch_config(sim_days, unit=unit)
        _globals = (
            "AGENT_IDS", "SIM_DAYS", "STATEFUL", "SIMULATE_REALTIME",
            "SECONDS_PER_DAY", "NEWS_ENABLED", "INTERVENTION_ENABLED",
            "HUMAN_REALISM_ENABLED", "VISUALIZATION_ENABLED",
            "LIFE_EVENTS_ENABLED", "LONG_RUN_ENABLED", "LONG_RUN_UNIT",
        )
        _saved = {name: getattr(sim, name) for name in _globals if hasattr(sim, name)}
        self.addCleanup(lambda: [setattr(sim, k, v) for k, v in _saved.items()])

        sim.AGENT_IDS = [4, 5]
        sim.SIM_DAYS = sim_days
        sim.STATEFUL = False
        sim.SIMULATE_REALTIME = False
        sim.SECONDS_PER_DAY = 1
        sim.NEWS_ENABLED = False
        sim.INTERVENTION_ENABLED = False
        sim.HUMAN_REALISM_ENABLED = False
        sim.VISUALIZATION_ENABLED = False
        sim.LIFE_EVENTS_ENABLED = False
        sim.LONG_RUN_ENABLED = True
        sim.LONG_RUN_UNIT = unit

        with install(mock) as active:
            sim.run_simulation()
        return active, sim_days

    def _assert_no_tick_loop(self, mock, expected_calls):
        seen = set(mock.tasks_seen())
        self.assertEqual(mock.call_count("fast_forward_period"), expected_calls)
        self.assertNotIn("fast_forward_day", seen)
        self.assertFalse(
            seen & {"planning", "reflection", "perception"},
            f"tick-loop tasks should be absent in fast-forward mode: {seen}",
        )

    def _run_path(self, key, default, *parts):
        """A run artifact path, read off the config rather than assumed.

        A selected city moves the whole run tree under ``output/cities/<slug>/``,
        so hardcoding ``output/logs`` here would make these tests depend on
        whichever city the developer's dashboard_config.json happens to name.
        """
        from gaworld.settings import CONFIG

        return os.path.join(self.tmp.name, CONFIG.get(key, default), *parts)

    def _agent_log(self, agent_id):
        path = self._run_path("log_dir", "output/logs", f"agent_{agent_id}.log")
        with open(path, encoding="utf-8") as fh:
            return fh.read()

    def test_monthly_run(self) -> None:
        import generative_city_sim as sim

        mock, sim_days = self._run("month", 3)
        # One period digest per agent per month — ~90 days for 6 calls, not 180.
        self._assert_no_tick_loop(mock, 2 * 3)

        for aid in (4, 5):
            text = self._agent_log(aid)
            for month in (1, 2, 3):
                self.assertIn(f"[FastForward Month {month}]", text)

        # One diary per agent per month, written on the period's last day.
        end_days = [p.end_day for p in
                    ff.plan_horizon(1, sim_days, "month", start_date=sim.SIM_START_DATE)]
        self.assertEqual(len(end_days), 3)
        for aid in (4, 5):
            for end_day in end_days:
                path = self._run_path(
                    "diary_output_dir", "output/diaries",
                    f"agent_{aid}", f"day_{end_day:03d}.md",
                )
                self.assertTrue(os.path.exists(path), f"missing diary {path}")

    def test_a_digest_life_move_actually_changes_the_world(self) -> None:
        """The coarse action space has to *do* something, not just narrate.

        The tick-scoped life-event path never fires in fast-forward, so
        without the step-scoped handler a digest saying "he changed jobs"
        leaves ``agent["job"]`` untouched — prose the model never acts on.
        The ``[JobChange ...]`` log line is written only after
        ``apply_employment_event`` reports a real rewrite, so its presence is
        evidence the move landed on the agent rather than in the brief.
        """
        from tests.fixtures.mock_llm import MockLLM

        mock = MockLLM({"fast_forward_period": json.dumps({
            "brief": "这一年换了工作，收入结构也跟着变了。",
            "memory": "递交辞呈那天松了口气。",
            "highlights": ["换到新岗位"],
            "life_moves": [{"key": "job_change", "new_job": "数据分析师",
                            "note": "想换个方向"}],
        }, ensure_ascii=False)})
        self._run("year", 1, mock=mock)

        for aid in (4, 5):
            text = self._agent_log(aid)
            self.assertIn("[JobChange", text, f"agent {aid} never changed jobs")
            self.assertIn("数据分析师", text)
            # The event also reached the narrative/record path.
            self.assertIn("换工作", text)

    def test_a_year_grows_skills_and_ages_people(self) -> None:
        """Individual development, the thing a long horizon is *for*.

        Practice accrues on `episode.compose`, which fast-forward never
        emits, so before the step-scoped growth pass a simulated year could
        only run the day-end decay: 阅读 went 0.30 → 0.10 no matter how the
        resident spent the year. And nothing ever wrote `age`, so a decade
        left everyone the age the seed CSV gave them.
        """
        from tests.fixtures.mock_llm import MockLLM

        mock = MockLLM({"fast_forward_period": json.dumps({
            "brief": "这一年一直在读书，坚持下来了。",
            "memory": "读完了第一摞书。",
            "development": [{"item": "阅读", "weekly_minutes": 240, "note": "每周都读"}],
        }, ensure_ascii=False)})
        self._run("year", 1, mock=mock)

        for aid in (4, 5):
            text = self._agent_log(aid)
            self.assertIn("[GrowthStep", text, f"agent {aid} never practised anything")
            self.assertIn("[Birthday", text, f"agent {aid} did not age over a year")
            # Growth must beat the year's decay, not merely be recorded.
            line = [ln for ln in text.splitlines() if "[GrowthStep" in ln][-1]
            before, after = line.rsplit(" ", 1)[-1].split("→")
            self.assertGreater(float(after), float(before),
                               f"a year of weekly practice should raise the level: {line}")

    def test_a_year_reorganises_the_social_circle(self) -> None:
        """Ties move, and the circle can grow — not only shrink.

        Decay plus Dunbar pruning can only ever remove ties, so before tie
        formation a decade-long run ended with everyone lonelier than they
        started — an artefact of the model, not a finding.
        """
        from tests.fixtures.mock_llm import MockLLM

        mock = MockLLM({"fast_forward_period": json.dumps({
            "brief": "这一年跟老同事走得近了，也认识了新的人。",
            "memory": "年底那顿饭吃得很尽兴。",
            "relationships": [{"neighbor": "5", "closeness_delta": 0.18,
                               "note": "常一起吃饭"}],
            "new_ties": [{"neighbor": "4", "role": "friend", "note": "同一个球队"}],
        }, ensure_ascii=False)})
        self._run("year", 1, mock=mock)

        # Agents 4 and 5 are the run's roster, so each is the other's
        # candidate: whichever direction lands, the log records the change.
        found = [self._agent_log(aid) for aid in (4, 5)]
        self.assertTrue(
            any("[Social Year 1]" in text for text in found),
            "no relationship trajectory was applied over a simulated year",
        )

    def test_yearly_run_replays_the_day_hooks_in_chunks(self) -> None:
        """A single year step: 1 digest per agent, but 13 hook emissions."""
        mock, sim_days = self._run("year", 1)
        self._assert_no_tick_loop(mock, 2 * 1)
        text = self._agent_log(4)
        self.assertIn("[FastForward Year 1]", text)
        # The economy ran once per hook chunk, not once for the whole year:
        # ceil(365 / 30) = 13 day-start emissions, each carrying 30-ish days.
        self.assertEqual(text.count("[EconomyDayStart"), 13)
        self.assertIn("x30d", text)


if __name__ == "__main__":
    unittest.main()
