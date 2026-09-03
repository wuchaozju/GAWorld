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
        # A day is at most one burst; a month expects several, capped.
        self.assertLessEqual(ff._draw_burst_count(1, 1.0, _r.Random(1)), 1)
        self.assertEqual(ff._draw_burst_count(30, 1.0, _r.Random(1)), ff._MAX_BURSTS)

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
        from gaworld.events.life import list_life_event_templates

        catalog = ff.life_move_catalog()
        self.assertEqual(
            {item["key"] for item in catalog},
            {t["key"] for t in list_life_event_templates()},
            "the menu and the machinery that applies it must not drift apart",
        )
        self.assertIn("job_change", {item["key"] for item in catalog})

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
                    {"key": "moved_to_mars"},          # not a template → dropped
                    {"key": "job_change"},             # duplicate → dropped
                    {"key": "illness"},
                ],
            }, ensure_ascii=False),
        )
        self.assertEqual([m["key"] for m in d["life_moves"]], ["job_change", "illness"])
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
        # The routine survives only as background colour, explicitly demoted.
        self.assertIn("生活底色", prompt)
        self.assertIn("不要逐日展开", prompt)

    def test_it_sees_the_arc_so_far_not_just_last_week(self):
        prompt = self._prompt_for(self._agent())
        self.assertIn("Year 1：换了工作，搬到城东", prompt)

    def test_it_sees_where_skills_and_relationships_stand(self):
        prompt = self._prompt_for(self._agent())
        self.assertIn("水平0.30", prompt)      # development needs a baseline
        self.assertIn("亲密度0.72", prompt)    # so does a relationship trajectory
        self.assertIn("周婉清", prompt)

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

    def _agent_log(self, agent_id):
        path = os.path.join(self.tmp.name, "output", "logs", f"agent_{agent_id}.log")
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
                path = os.path.join(
                    self.tmp.name, "output", "diaries", f"agent_{aid}",
                    f"day_{end_day:03d}.md",
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
