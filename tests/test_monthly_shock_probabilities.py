"""Raise and layoff chances are monthly, drawn as a per-day hazard.

They used to be drawn as daily chances with monthly-sized numbers: an
expansion gave each resident about 12 raises a year, a trough about 10
layoffs, and after one year on the default cycle the median wage sat on the
minimum-wage floor. See docs/proposals/2026-10-03-monthly-shock-probabilities.md.
"""

import copy
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from gaworld.economy import finance as eco


def _agents(n):
    return [({"state": {"econ_security": 0.5}},
             {"base_hourly_income": 80.0, "gross_monthly_salary": 14080.0,
              "income_skill": 0.5, "daily_expense": 0,
              "daily_expense_by_category": eco._empty_daily_categories(),
              "accounts": {"checking": 1e9}})
            for _ in range(n)]


def _quiet_cfg(**shocks):
    cfg = copy.deepcopy(eco.DEFAULT_ECONOMY_CONFIG)
    cfg["shocks"].update({"medical_emergency_prob": 0.0, **shocks})
    return cfg


def _year(phase, *, n=1000, days=365, seed=3):
    """Run `days` daily draws for `n` residents; return (raises, layoffs, salary multipliers)."""
    eco._rng.seed(seed)
    cfg = _quiet_cfg()
    macro = {"enabled": True, "phase": phase or "expansion", "phase_day_counter": 0,
             "phase_duration": 10**9 if phase else 120, "inflation_rate": 0.02,
             "unemployment_rate": 0.05, "cumulative_inflation": 1.0,
             "industry_conditions": {}}
    agents = _agents(n)
    raises = layoffs = 0
    for _ in range(days):
        if phase is None:
            eco._advance_macro_cycle(macro, cfg)
        for agent, econ in agents:
            for event in eco._check_daily_shocks(agent, econ, cfg, macro):
                raises += event["type"] == "raise"
                layoffs += event["type"] == "layoff"
    mults = sorted(econ["gross_monthly_salary"] / 14080.0 for _, econ in agents)
    return raises / n, layoffs / n, mults


class MonthlyToDailyTest(unittest.TestCase):
    def test_thirty_daily_draws_compound_to_the_monthly_chance(self):
        for p in (0.001, 0.038, 0.5, 0.9):
            daily = eco._monthly_to_daily(p)
            self.assertAlmostEqual(1 - (1 - daily) ** 30, p, places=12)

    def test_edges_and_out_of_range_values(self):
        self.assertEqual(eco._monthly_to_daily(0.0), 0.0)
        self.assertEqual(eco._monthly_to_daily(1.0), 1.0)
        self.assertEqual(eco._monthly_to_daily(-0.2), 0.0)
        self.assertEqual(eco._monthly_to_daily(1.7), 1.0)


class MonthlySemanticsTest(unittest.TestCase):
    def test_a_month_of_draws_gives_the_configured_monthly_chance(self):
        # raise_base_prob 0.5 a month, skill 0.5 (multiplier 1.0), no phase effects.
        eco._rng.seed(5)
        cfg = _quiet_cfg(raise_base_prob=0.5, layoff_base_prob=0.0)
        agents = _agents(4000)
        got = 0
        for agent, econ in agents:
            events = []
            for _ in range(30):
                events += eco._check_daily_shocks(agent, econ, cfg, {"enabled": False})
            got += any(e["type"] == "raise" for e in events)
        self.assertAlmostEqual(got / len(agents), 0.5, delta=0.03)

    def test_expansion_gives_a_raise_every_couple_of_years_not_twelve_a_year(self):
        # 0.008 + 0.03 a month -> about 0.46 raises a year (was 11.8).
        raises, layoffs, _ = _year("expansion")
        self.assertGreater(raises, 0.3)
        self.assertLess(raises, 0.65)
        self.assertLess(layoffs, 0.1)

    def test_a_year_of_trough_lays_off_about_a_quarter_not_everyone_ten_times(self):
        # 0.001 + 0.025 a month -> about 0.3 layoffs a year (was 9.6).
        _, layoffs, _ = _year("trough")
        self.assertGreater(layoffs, 0.2)
        self.assertLess(layoffs, 0.45)

    def test_a_default_cycle_year_leaves_the_median_wage_where_it_was(self):
        # Was: median x0.10 (the minimum-wage floor), p10 x0.10.
        _, _, mults = _year(None)
        median = mults[len(mults) // 2]
        p90 = mults[int(0.9 * (len(mults) - 1))]
        self.assertGreater(median, 0.9)
        self.assertLess(median, 1.2)
        self.assertLess(p90, 2.0)

    def test_event_layoff_floor_stays_a_daily_chance(self):
        # A 0.6 floor on an event day means 0.6 that day, not 0.6 over a month.
        cfg = _quiet_cfg(layoff_base_prob=0.0, raise_base_prob=0.0, event_layoff_prob=0.6)
        agent, econ = _agents(1)[0]
        with patch.object(eco._rng, "random", return_value=0.59):
            events = eco._check_daily_shocks(agent, econ, cfg, {"enabled": False},
                                             event_layoff=True)
        self.assertIn("layoff", [e["type"] for e in events])


if __name__ == "__main__":
    unittest.main()
