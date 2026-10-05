"""A random layoff is a spell: when it ends the wage comes back (to 85–100%).

Before this the cut (50–85%) was permanent — the 30–90 day countdown only
held raises off, and only an unemployment *life event* re-hired anyone. With
monthly shock chances about one resident in nine is laid off in a default
year, so the 10th-percentile wage sat at half the starting wage.
See docs/proposals/2026-10-03-layoff-recovery.md.
"""

import copy
import unittest
from unittest.mock import patch

from gaworld.economy import finance as eco
from tests.test_monthly_shock_probabilities import _year


def _quiet_cfg():
    cfg = copy.deepcopy(eco.DEFAULT_ECONOMY_CONFIG)
    cfg["shocks"].update({"layoff_base_prob": 0.0, "raise_base_prob": 0.0,
                          "medical_emergency_prob": 0.0})
    return cfg


def _laid_off(hourly=80.0):
    """A resident one random layoff into a spell."""
    agent = {"job": "算法工程师", "state": {"econ_security": 0.5}}
    econ = {"base_hourly_income": hourly, "gross_monthly_salary": hourly * 176,
            "income_skill": 0.5, "daily_expense": 0, "accounts": {"checking": 1e6},
            "daily_expense_by_category": eco._empty_daily_categories()}
    agent["economy"] = econ
    cfg = _quiet_cfg()
    cfg["shocks"]["layoff_base_prob"] = 1.0
    events = eco._check_daily_shocks(agent, econ, cfg, {"enabled": False})
    assert [e["type"] for e in events] == ["layoff"], events
    return agent, econ


def _run_out_the_spell(agent, econ):
    events = []
    while econ.get("_layoff_days_remaining"):
        events += eco._check_daily_shocks(agent, econ, _quiet_cfg(), {"enabled": False})
    return events


class LayoffRecoveryTest(unittest.TestCase):
    def test_the_wage_comes_back_to_85_to_100_percent_when_the_spell_ends(self):
        eco._rng.seed(1)
        agent, econ = _laid_off()
        self.assertLess(econ["base_hourly_income"], 80.0 * 0.5 + 1e-9)
        events = _run_out_the_spell(agent, econ)
        recovery = [e for e in events if e["type"] == "layoff_recovery"]
        self.assertEqual(len(recovery), 1)
        self.assertGreaterEqual(econ["base_hourly_income"], 80.0 * 0.85)
        self.assertLessEqual(econ["base_hourly_income"], 80.0)
        self.assertEqual(recovery[0]["to_hourly"], econ["base_hourly_income"])
        # Gross moves with hourly, so the monthly settlement sees the recovery.
        self.assertAlmostEqual(econ["gross_monthly_salary"] / 176,
                               econ["base_hourly_income"], places=1)
        self.assertNotIn("_pre_layoff_hourly", econ)
        self.assertEqual(agent["job"], "算法工程师")

    def test_a_second_layoff_inside_the_spell_still_returns_to_the_first_wage(self):
        eco._rng.seed(2)
        agent, econ = _laid_off()
        cfg = _quiet_cfg()
        cfg["shocks"]["layoff_base_prob"] = 1.0
        eco._check_daily_shocks(agent, econ, cfg, {"enabled": False})
        self.assertEqual(econ["_pre_layoff_hourly"], 80.0)
        _run_out_the_spell(agent, econ)
        self.assertGreaterEqual(econ["base_hourly_income"], 80.0 * 0.85)

    def test_recovery_never_lowers_the_wage(self):
        agent, econ = _laid_off()
        econ["base_hourly_income"] = 79.0  # e.g. indexation lifted it mid-spell
        econ["gross_monthly_salary"] = 79.0 * 176
        with patch.object(eco._rng, "uniform", return_value=0.85):
            _run_out_the_spell(agent, econ)
        self.assertEqual(econ["base_hourly_income"], 79.0)

    def test_a_job_change_or_retirement_inside_the_spell_forgets_the_old_wage(self):
        for key in ("job_change", "retirement"):
            agent, econ = _laid_off()
            eco.apply_employment_event(agent, {"template_key": key, "new_job": "店员"}, {})
            self.assertNotIn("_pre_layoff_hourly", econ, key)
            self.assertNotIn("_layoff_days_remaining", econ, key)

    def test_an_unemployment_event_spell_still_ends_in_a_rehire_not_a_restore(self):
        agent, econ = _laid_off()
        eco.apply_employment_event(agent, {"template_key": "unemployment"}, {})
        events = _run_out_the_spell(agent, econ)
        types = [e["type"] for e in events]
        self.assertIn("rehired", types)
        recovery = next(e for e in events if e["type"] == "layoff_recovery")
        self.assertNotIn("to_hourly", recovery)
        self.assertNotIn("_pre_layoff_hourly", econ)

    def test_a_default_year_no_longer_leaves_the_bottom_tenth_at_half_pay(self):
        # Monthly chances alone: p10 x0.51. With recovery the cut is a spell.
        _, _, mults = _year(None)
        self.assertGreater(mults[int(0.1 * (len(mults) - 1))], 0.8)


if __name__ == "__main__":
    unittest.main()
