"""换工作 / 失业 life events actually change where the agent works.

A 失业 event that only shows up in perception text leaves the agent working
their old job, earning their old salary, and commuting to their old office —
these tests pin the economic half: `agent["job"]`, the employment flag, the
income band re-draw, and the re-hire that ends the spell.
"""

import json
import os
import tempfile
import unittest
from copy import deepcopy
from unittest import mock

from gaworld.apps import dashboard_server as ds
from gaworld.economy import finance as eco
from gaworld.events.life import list_life_event_templates, normalize_life_event
from gaworld.sim._schedule import (
    is_routine_impacting_event,
    resolve_life_event_activities,
)


def _agent(job="算法工程师", hourly=60.0, with_economy=True):
    agent = {
        "id": 1, "name": "A1", "age": 30, "job": job,
        "state": {"emotion": 0.5, "stress": 0.5, "econ_security": 0.5,
                  "risk_preference": 0.5},
    }
    if with_economy:
        agent["economy"] = {
            "base_hourly_income": hourly,
            "hourly_income": hourly,
            "gross_monthly_salary": hourly * 8 * 22,
            "income_skill": 0.6,
            "industry": eco._infer_industry(agent),
            "shock_log": [],
        }
    return agent


def _event(template_key, **over):
    payload = {"template_key": template_key, "title": template_key}
    payload.update(over)
    return normalize_life_event(payload)


class TestTemplates(unittest.TestCase):
    def test_both_templates_are_offered(self):
        keys = {t["key"] for t in list_life_event_templates()}
        self.assertIn("job_change", keys)
        self.assertIn("unemployment", keys)

    def test_new_job_survives_normalization(self):
        event = _event("job_change", new_job="社区医生")
        self.assertEqual(event["new_job"], "社区医生")

    def test_new_job_defaults_to_empty(self):
        self.assertEqual(_event("illness")["new_job"], "")

    def test_employment_events_reshape_the_day(self):
        for key in ("job_change", "unemployment"):
            template = next(t for t in list_life_event_templates() if t["key"] == key)
            self.assertTrue(is_routine_impacting_event(template), key)

    def test_job_hunt_activity_does_not_pay_wages(self):
        # "找工作" would match INCOME_KEYWORDS via the 工作 substring.
        _, follow = resolve_life_event_activities({"template_key": "unemployment"})
        self.assertFalse(eco._is_income_activity(follow, ""))


class TestIsEmploymentEvent(unittest.TestCase):
    def test_matches_template_keys(self):
        self.assertTrue(eco.is_employment_event({"template_key": "unemployment"}))
        self.assertTrue(eco.is_employment_event({"template_key": "job_change"}))

    def test_matches_employment_tag(self):
        self.assertTrue(
            eco.is_employment_event({"template_key": "custom",
                                     "impact_tags": ["employment"]}))

    def test_ignores_other_events(self):
        self.assertFalse(eco.is_employment_event({"template_key": "illness"}))
        self.assertFalse(eco.is_employment_event(None))


class TestUnemployment(unittest.TestCase):
    def test_rewrites_job_and_cuts_income(self):
        agent = _agent()
        record = eco.apply_employment_event(agent, _event("unemployment"))
        econ = agent["economy"]
        self.assertEqual(agent["job"], eco.UNEMPLOYED_JOB_TEXT)
        self.assertEqual(agent["employment"], "unemployed")
        self.assertLess(econ["base_hourly_income"], 60.0)
        self.assertEqual(econ["hourly_income"], econ["base_hourly_income"])
        self.assertEqual(record["from_job"], "算法工程师")
        self.assertEqual(record["type"], "unemployment")

    def test_starts_a_recovery_countdown_and_remembers_the_old_job(self):
        agent = _agent()
        eco.apply_employment_event(agent, _event("unemployment"))
        econ = agent["economy"]
        self.assertGreaterEqual(econ["_layoff_days_remaining"], 30)
        self.assertLessEqual(econ["_layoff_days_remaining"], 90)
        self.assertEqual(econ["previous_job"], "算法工程师")

    def test_income_never_falls_below_the_floor(self):
        agent = _agent(hourly=9.0)
        eco.apply_employment_event(agent, _event("unemployment"))
        floor = eco.DEFAULT_ECONOMY_CONFIG["min_hourly_income"]
        self.assertGreaterEqual(agent["economy"]["base_hourly_income"], floor)

    def test_logged_as_a_shock(self):
        agent = _agent()
        eco.apply_employment_event(agent, _event("unemployment"))
        self.assertEqual(agent["economy"]["shock_log"][-1]["type"], "unemployment")


class TestJobChange(unittest.TestCase):
    def test_moves_to_the_named_job(self):
        agent = _agent()
        record = eco.apply_employment_event(agent, _event("job_change", new_job="社区医生"))
        self.assertEqual(agent["job"], "社区医生")
        self.assertEqual(agent["employment"], "employed")
        self.assertEqual(agent["economy"]["industry"], "medical")
        self.assertEqual(record["to_job"], "社区医生")

    def test_unnamed_change_switches_industry(self):
        from gaworld.population.synth import JOB_TITLES

        agent = _agent()
        eco.apply_employment_event(agent, _event("job_change"))
        non_tech = {t for k, titles in JOB_TITLES.items() if k != "tech" for t in titles}
        self.assertIn(agent["job"], non_tech)

    def test_income_follows_the_new_job_band(self):
        agent = _agent(job="餐饮店员", hourly=20.0)
        eco.apply_employment_event(agent, _event("job_change", new_job="证券分析师"))
        low, _high = eco._job_income_band("证券分析师")
        self.assertGreaterEqual(agent["economy"]["base_hourly_income"], low * 0.75)

    def test_clears_a_running_unemployment_spell(self):
        agent = _agent()
        eco.apply_employment_event(agent, _event("unemployment"))
        eco.apply_employment_event(agent, _event("job_change", new_job="小学教师"))
        self.assertNotIn("_layoff_days_remaining", agent["economy"])
        self.assertNotIn("previous_job", agent["economy"])
        self.assertEqual(agent["employment"], "employed")


class TestWithoutEconomyState(unittest.TestCase):
    def test_job_text_still_changes(self):
        agent = _agent(with_economy=False)
        record = eco.apply_employment_event(agent, _event("unemployment"))
        self.assertEqual(agent["job"], eco.UNEMPLOYED_JOB_TEXT)
        self.assertNotIn("to_hourly", record)

    def test_other_events_are_a_no_op(self):
        agent = _agent()
        self.assertIsNone(eco.apply_employment_event(agent, _event("illness")))
        self.assertEqual(agent["job"], "算法工程师")


class TestRehire(unittest.TestCase):
    def _quiet_cfg(self):
        cfg = deepcopy(eco.DEFAULT_ECONOMY_CONFIG)
        cfg["shocks"].update({"layoff_base_prob": 0.0, "raise_base_prob": 0.0,
                              "medical_emergency_prob": 0.0})
        return cfg

    def test_spell_ends_back_in_the_old_line_of_work(self):
        agent = _agent()
        eco.apply_employment_event(agent, _event("unemployment"))
        econ = agent["economy"]
        econ["_layoff_days_remaining"] = 1

        events = eco._check_daily_shocks(agent, econ, self._quiet_cfg(), {})

        self.assertEqual(agent["job"], "算法工程师")
        self.assertEqual(agent["employment"], "employed")
        self.assertIn("rehired", [e["type"] for e in events])
        self.assertNotIn("previous_job", econ)

    def test_random_layoff_does_not_rewrite_the_job(self):
        # The pre-existing random layoff shock cuts income only; nothing marks
        # the agent as unemployed, so recovery must leave the job text alone.
        agent = _agent()
        econ = agent["economy"]
        econ["_layoff_days_remaining"] = 1

        events = eco._check_daily_shocks(agent, econ, self._quiet_cfg(), {})

        self.assertEqual(agent["job"], "算法工程师")
        self.assertNotIn("rehired", [e["type"] for e in events])


class TestDashboardEmploymentPayload(unittest.TestCase):
    """The panel has to read the *live* job, not the Day-1 one in the profile."""

    def _payload(self, econ):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "agent_1_economy.json"), "w", encoding="utf-8") as fh:
                json.dump(econ, fh, ensure_ascii=False)
            with mock.patch.object(ds, "_memory_base_dir", return_value=tmp):
                return ds._employment_payload(1)

    def test_empty_without_economy_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(ds, "_memory_base_dir", return_value=tmp):
                self.assertEqual({}, ds._employment_payload(1))

    def test_reports_the_current_job(self):
        payload = self._payload({"job": "算法工程师", "base_hourly_income": 60.0})
        self.assertEqual(payload["job"], "算法工程师")
        self.assertEqual(payload["status"], "employed")
        self.assertEqual(payload["hourly_income"], 60.0)

    def test_reports_an_unemployment_spell(self):
        payload = self._payload({
            "job": eco.UNEMPLOYED_JOB_TEXT,
            "base_hourly_income": 12.0,
            "previous_job": "算法工程师",
            "_layoff_days_remaining": 42,
        })
        self.assertEqual(payload["status"], "unemployed")
        self.assertEqual(payload["recovery_days"], 42)
        self.assertEqual(payload["previous_job"], "算法工程师")

    def test_history_keeps_only_employment_records(self):
        payload = self._payload({"job": "小学教师", "shock_log": [
            {"type": "medical_emergency", "total_cost": 100},
            {"type": "unemployment", "from_job": "算法工程师", "to_job": "待业中", "day": 3},
            {"type": "rehired", "to_job": "算法工程师"},
        ]})
        self.assertEqual([r["type"] for r in payload["history"]],
                         ["unemployment", "rehired"])

    def test_end_to_end_from_the_event_to_the_panel(self):
        agent = _agent()
        eco.apply_employment_event(agent, _event("unemployment"), day=7)
        payload = self._payload(agent["economy"])
        self.assertEqual(payload["job"], eco.UNEMPLOYED_JOB_TEXT)
        self.assertEqual(payload["status"], "unemployed")
        self.assertEqual(payload["history"][-1]["day"], 7)
        self.assertEqual(payload["history"][-1]["from_job"], "算法工程师")


class TestDashboardEmploymentUI(unittest.TestCase):
    _ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

    def _read(self, *parts):
        with open(os.path.join(self._ROOT, "site", "dashboard", *parts), encoding="utf-8") as fh:
            return fh.read()

    def test_the_panel_renders_the_employment_block(self):
        app = self._read("app.js")
        self.assertIn("employmentHtml(payload.employment)", app)
        self.assertIn("memory.block_employment", app)

    def test_both_locales_carry_the_new_keys(self):
        keys = [
            "memory.block_employment", "memory.employment_job",
            "memory.employment_employed", "memory.employment_unemployed",
            "memory.employment_hourly", "memory.employment_recovery",
            "memory.employment_days", "memory.employment.job_change",
            "memory.employment.unemployment", "memory.employment.rehired",
            "life_event.new_job", "life_event.new_job_placeholder",
        ]
        for locale in ("zh-CN.json", "en.json"):
            table = json.loads(self._read("locales", locale))
            for key in keys:
                self.assertIn(key, table, f"{key} missing from {locale}")


if __name__ == "__main__":
    unittest.main()
