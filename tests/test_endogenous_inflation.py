"""Endogenous inflation (proposal 2026-10-03-endogenous-inflation.md).

Before this change ``macro.cumulative_inflation`` accrued every day and was
never read: the price level had no effect on any ledger, although three
documents said it eroded real income. These tests pin both halves: off means
exactly the old behaviour, on means the price level reaches spending, the
demand driver moves the rate the right way, nominal spending cannot feed back
into itself, wages follow prices only partly, and money is still conserved.
"""

from __future__ import annotations

import tempfile
import unittest

from gaworld.economy import finance as eco
from tests.test_economy_conservation import _build_agent, _build_config


def _inflation(**over):
    block = {"enabled": True, "driver": "demand", "anchor": 0.025, "sensitivity": 0.5,
             "baseline_days": 30, "window_days": 30, "wage_indexation": 0.5,
             "suppress_phase_expense_mult": True}
    block.update(over)
    return {"macro": {"enabled": True, "inflation": block}}


def _run(days, *, econ_over=None, on_day=None):
    """Run the economy hooks for ``days`` days; ``on_day(day, agents)`` may
    perturb the agents before each day starts. Returns (agents, runtime, rates)."""
    with tempfile.TemporaryDirectory() as tmp:
        config = _build_config(tmp, **(econ_over or {}))
        agents = [_build_agent(i, job=j, age=a) for i, (j, a) in
                  enumerate([("医生", 45), ("程序员", 28), ("店员", 33)], start=1)]
        ext = {}
        eco.on_simulation_start({"config": config, "agents": agents, "extension_state": ext})
        runtime = ext["economy_module"]
        rates = []
        for day in range(1, days + 1):
            if on_day:
                on_day(day, agents)
            day_ctx = {"config": config, "day": day, "agents": agents,
                       "daily_logs": {a["id"]: "" for a in agents}, "extension_state": ext}
            eco.on_day_start(day_ctx)
            for agent in agents:
                for time_str, activity in (("10:00", "工作"), ("12:30", "吃午饭"), ("19:00", "逛街购物")):
                    eco.on_agent_post_step({
                        "config": config, "day": day, "time_str": time_str, "agent": agent,
                        "step": {"activity": activity, "action": activity, "location": "Office"},
                        "daily_logs": day_ctx["daily_logs"], "extension_state": ext})
            eco.on_day_end(day_ctx)
            rates.append(runtime["macro"]["inflation_rate"])
        return agents, runtime, rates


class OffTest(unittest.TestCase):
    def test_the_price_level_is_still_display_only_when_off(self):
        cfg = eco._get_cfg({"config": {}})
        macro = {"enabled": True, "phase": "peak", "cumulative_inflation": 2.0}
        self.assertEqual(eco._macro_expense_multiplier(macro, cfg), 1.06)
        _, runtime, _ = _run(40)
        self.assertNotIn("inflation_driver", runtime["macro"])


class PriceLevelTest(unittest.TestCase):
    def _cfg(self, **over):
        return eco._get_cfg({"config": {"economy": _inflation(**over)}})

    def test_the_price_level_prices_spending_and_replaces_the_phase_multiplier(self):
        macro = {"enabled": True, "phase": "peak", "cumulative_inflation": 2.0}
        self.assertEqual(eco._macro_expense_multiplier(macro, self._cfg()), 2.0)
        kept = self._cfg(suppress_phase_expense_mult=False)
        self.assertAlmostEqual(eco._macro_expense_multiplier(macro, kept), 2.12)

    def test_demand_is_measured_in_real_terms(self):
        agent = {"economy": {"daily_expense_by_category": {"food": 100.0, "housing": 900.0}}}
        infl = self._cfg()["macro"]["inflation"]
        low = {"cumulative_inflation": 1.0}
        high = {"cumulative_inflation": 2.0}
        eco._record_real_demand(low, [agent], 1, infl)
        eco._record_real_demand(high, [agent], 1, infl)
        # Housing excluded; the same nominal spend at twice the prices is half the goods.
        self.assertEqual(low["inflation_driver"]["demand_history"], [100.0])
        self.assertEqual(high["inflation_driver"]["demand_history"], [50.0])

    def test_a_medical_emergency_is_not_demand(self):
        # Routine healthcare counts; the emergency's out-of-pocket bill does not.
        cfg = eco._get_cfg({"config": {"economy": {"shocks": {
            "medical_emergency_prob": 1.0, "layoff_base_prob": 0.0, "raise_base_prob": 0.0}}}})
        econ = {"daily_expense": 0.0, "accounts": {"checking": 1e6},
                "daily_expense_by_category": {"food": 100.0, "healthcare": 30.0}}
        events = eco._check_daily_shocks({"state": {}}, econ, cfg, {"enabled": False})
        self.assertEqual([e["type"] for e in events], ["medical_emergency"])
        self.assertGreater(econ["daily_expense_by_category"]["healthcare"], 30.0)
        macro = {"cumulative_inflation": 1.0}
        eco._record_real_demand(macro, [{"economy": econ}],
                                1, self._cfg()["macro"]["inflation"])
        self.assertEqual(macro["inflation_driver"]["demand_history"], [130.0])

    def test_phillips_driver_reads_the_agents_unemployment(self):
        infl = self._cfg(driver="phillips", natural_unemployment=0.05)["macro"]["inflation"]
        self.assertLess(eco._endogenous_inflation({"unemployment_rate": 0.15}, infl), 0.025)
        self.assertGreater(eco._endogenous_inflation({"unemployment_rate": 0.0}, infl), 0.025)
        self.assertIsNone(eco._endogenous_inflation({}, {**infl, "driver": "exogenous"}))


class DemandDriverTest(unittest.TestCase):
    def test_the_baseline_period_holds_the_anchor(self):
        _, runtime, rates = _run(29, econ_over=_inflation())
        self.assertTrue(all(abs(r - 0.025) < 1e-12 for r in rates))
        self.assertIsNone(runtime["macro"]["inflation_driver"]["baseline"])

    def test_more_income_raises_inflation_and_less_lowers_it(self):
        def pay(scale):
            def on_day(day, agents):
                if day == 45:  # before the day-60 re-plan, so the new budget lands then
                    for agent in agents:
                        econ = agent["economy"]
                        for key in ("gross_monthly_salary", "base_hourly_income"):
                            econ[key] = econ[key] * scale
            return on_day

        _, _, control = _run(100, econ_over=_inflation())
        _, _, richer = _run(100, econ_over=_inflation(), on_day=pay(1.5))
        _, _, poorer = _run(100, econ_over=_inflation(), on_day=pay(0.6))
        self.assertGreater(richer[-1], control[-1])
        self.assertLess(poorer[-1], control[-1])
        self.assertTrue(all(0.001 <= r <= 0.15 for r in richer + poorer))

    def test_money_is_still_conserved(self):
        _, runtime, _ = _run(200, econ_over=_inflation())
        self.assertLessEqual(max(abs(r["drift"]) for r in runtime["audit_rows"]), 0.01)
        self.assertGreater(runtime["macro"]["cumulative_inflation"], 1.0)


class WageIndexationTest(unittest.TestCase):
    def _month_end(self, indexation, price):
        with tempfile.TemporaryDirectory() as tmp:
            config = _build_config(tmp, **_inflation(wage_indexation=indexation))
            agents = [_build_agent(1)]
            ext = {}
            eco.on_simulation_start({"config": config, "agents": agents, "extension_state": ext})
            runtime = ext["economy_module"]
            runtime["sim_day_counter"] = 29
            ctx = {"config": config, "day": 30, "agents": agents,
                   "daily_logs": {1: ""}, "extension_state": ext}
            eco.on_day_start(ctx)
            gross = agents[0]["economy"]["gross_monthly_salary"]
            runtime["macro"]["cumulative_inflation"] = price
            eco._driver_state(runtime["macro"])["price_at_settlement"] = 1.0
            eco.on_day_end(ctx)
            return gross, agents[0]["economy"]

    def test_half_of_last_months_price_rise_reaches_wages(self):
        gross, econ = self._month_end(0.5, 1.10)
        self.assertAlmostEqual(econ["gross_monthly_salary"], round(gross * 1.05, 2), places=2)

    def test_no_indexation_keeps_the_nominal_wage(self):
        gross, econ = self._month_end(0.0, 1.10)
        self.assertEqual(econ["gross_monthly_salary"], gross)

    def test_the_plan_is_made_on_real_income(self):
        _, econ = self._month_end(0.0, 2.0)
        real = econ["net_monthly_salary"] / 2.0
        self.assertAlmostEqual(econ["monthly_expense_estimate"],
                               round(real * (1.0 - econ["savings_rate"]), 2), places=2)
        self.assertEqual(econ["engel_coefficient"],
                         round(eco._engel_params(real, eco._get_cfg({"config": {}}))[0], 4))


if __name__ == "__main__":
    unittest.main()
