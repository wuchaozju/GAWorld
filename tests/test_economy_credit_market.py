"""Tests for P2 economy features: cash-constrained consumption, simple credit,
common market factor, and income/expense keyword disjointness."""

import os
import tempfile
import unittest

from gaworld.economy import finance as eco


def _build_agent(agent_id=1, job="软件工程师", age=30):
    return {
        "id": agent_id, "name": f"A{agent_id}", "age": age, "job": job,
        "personality": "上进务实", "values": "稳定", "daily_life": "规律",
        "state": {"emotion": 0.5, "stress": 0.5, "econ_security": 0.5,
                  "risk_preference": 0.5},
    }


def _econ(checking=0.0, savings=0.0, net_salary=5000.0):
    return {
        "daily_income": 0.0, "daily_expense": 0.0,
        "lifetime_income": 0.0, "lifetime_expense": 0.0,
        "daily_expense_by_category": eco._empty_daily_categories(),
        "accounts": {"checking": checking, "savings": savings},
        "net_monthly_salary": net_salary,
        "monthly_expense_estimate": 4000.0,
    }


def _sectors():
    return {"firms": 0.0, "government": 0.0, "bank": 0.0}


def _total(econ, sectors):
    accounts = econ["accounts"]
    return round(sum(eco._to_float(accounts.get(k, 0), 0)
                     for k in ("checking", "savings", "investment", "housing_fund"))
                 + sum(sectors.values()), 2)


class TestCashConstraint(unittest.TestCase):
    def test_hardship_cuts_luxuries_harder_than_necessities(self):
        cfg = eco.deepcopy(eco.DEFAULT_ECONOMY_CONFIG)
        econ = _econ(checking=400.0)  # 0.1 month of liquidity -> hardship
        expense_map = {"food": 100.0, "leisure": 100.0}
        scaled = eco._apply_cash_constraint(econ, expense_map, cfg)
        self.assertLess(scaled["food"], 100.0)
        self.assertLess(scaled["leisure"], scaled["food"])  # leisure cut harder

    def test_no_cut_when_liquidity_is_healthy(self):
        cfg = eco.deepcopy(eco.DEFAULT_ECONOMY_CONFIG)
        econ = _econ(checking=20000.0)
        expense_map = {"food": 100.0, "leisure": 100.0}
        self.assertEqual(eco._apply_cash_constraint(econ, expense_map, cfg),
                         expense_map)


class TestPayExpense(unittest.TestCase):
    def test_savings_drawdown_before_credit(self):
        cfg = eco.deepcopy(eco.DEFAULT_ECONOMY_CONFIG)
        econ, sectors = _econ(checking=10.0, savings=100.0), _sectors()
        before = _total(econ, sectors)
        paid = eco._pay_expense(econ, "food", 50.0, cfg, sectors)
        self.assertEqual(paid, 50.0)
        self.assertEqual(econ["accounts"]["savings"], 60.0)
        self.assertEqual(econ["accounts"]["checking"], 0.0)
        self.assertEqual(econ.get("debt", 0), 0)          # no borrowing needed
        self.assertEqual(sectors["firms"], 50.0)
        self.assertEqual(_total(econ, sectors), before)   # conserved

    def test_credit_line_borrows_from_bank(self):
        cfg = eco.deepcopy(eco.DEFAULT_ECONOMY_CONFIG)
        econ, sectors = _econ(checking=0.0, savings=0.0, net_salary=5000.0), _sectors()
        before = _total(econ, sectors)
        paid = eco._pay_expense(econ, "food", 300.0, cfg, sectors)
        self.assertEqual(paid, 300.0)
        self.assertEqual(econ["debt"], 300.0)
        self.assertEqual(sectors["bank"], -300.0)
        self.assertEqual(sectors["firms"], 300.0)
        self.assertEqual(_total(econ, sectors), before)   # borrowed money conserved

    def test_truncates_when_credit_exhausted(self):
        cfg = eco.deepcopy(eco.DEFAULT_ECONOMY_CONFIG)
        cfg["credit"]["enabled"] = False
        econ, sectors = _econ(checking=20.0), _sectors()
        paid = eco._pay_expense(econ, "food", 50.0, cfg, sectors)
        self.assertEqual(paid, 20.0)                       # only what's affordable
        self.assertEqual(econ["accounts"]["checking"], 0.0)
        self.assertTrue(econ.get("_distress_today", False))

    def test_credit_limit_respected(self):
        cfg = eco.deepcopy(eco.DEFAULT_ECONOMY_CONFIG)
        econ, sectors = _econ(net_salary=100.0), _sectors()  # limit = 200
        paid = eco._pay_expense(econ, "food", 500.0, cfg, sectors)
        self.assertEqual(econ["debt"], 200.0)
        self.assertEqual(paid, 200.0)
        self.assertTrue(econ.get("_distress_today", False))


class TestDebtService(unittest.TestCase):
    def test_interest_capitalized_and_repaid_from_surplus(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = {
                "stateful": False, "random_seed": 7,
                "memory_dir": os.path.join(tmp, "memory"),
                "log_dir": os.path.join(tmp, "logs"),
                "economy": {
                    "enabled": True, "output_dir": os.path.join(tmp, "economy"),
                    "shocks": {"enabled": False},
                    "investment": {"enabled": False, "auto_save_enabled": False},
                },
            }
            agent = _build_agent()
            ext = {}
            ctx = {"config": config, "agents": [agent], "extension_state": ext}
            eco.on_simulation_start(ctx)
            runtime = ext["economy_module"]
            sectors = runtime["sectors"]
            econ = agent["economy"]

            econ["debt"] = 1000.0
            econ["accounts"]["checking"] = 50000.0  # plenty of surplus
            econ["month_gross_income"] = 0.0
            before = eco._system_total([agent], sectors)

            runtime["sim_day_counter"] = 30
            end_ctx = {"config": config, "day": 30, "agents": [agent],
                       "daily_logs": {1: ""}, "extension_state": ext}
            eco.on_day_end(end_ctx)

            with_interest = round(1000.0 * (1 + 0.18 / 12.0), 2)
            repaid = sectors["bank"]
            self.assertGreater(repaid, 0.0)
            self.assertAlmostEqual(econ["debt"], round(with_interest - repaid, 2), places=2)
            # Interest capitalization creates a claim, not money: total conserved
            self.assertAlmostEqual(eco._system_total([agent], sectors), before, places=2)


class TestMarketFactor(unittest.TestCase):
    def test_full_correlation_gives_identical_returns(self):
        cfg = eco.deepcopy(eco.DEFAULT_ECONOMY_CONFIG)
        cfg["investment"]["market_correlation"] = 1.0
        market = {"deposits": 0.002, "funds": -0.03, "stocks": -0.12}  # a crash month
        weights = {"deposits": 0.4, "funds": 0.4, "stocks": 0.2}
        ret_a, _ = eco._simulate_monthly_investment_return(100000, weights, cfg,
                                                           market_returns=market)
        ret_b, _ = eco._simulate_monthly_investment_return(100000, weights, cfg,
                                                           market_returns=market)
        self.assertEqual(ret_a, ret_b)          # no idiosyncratic noise at rho=1
        self.assertLess(ret_a, 0.0)             # the crash hits everyone

    def test_zero_correlation_market_draw_is_deterministic_mean(self):
        cfg = eco.deepcopy(eco.DEFAULT_ECONOMY_CONFIG)
        cfg["investment"]["market_correlation"] = 0.0
        market = eco._draw_monthly_market_returns(cfg)
        self.assertAlmostEqual(market["stocks"], 0.08 / 12.0, places=10)

    def test_fallback_without_market_returns(self):
        eco._rng.seed(42)
        cfg = eco.deepcopy(eco.DEFAULT_ECONOMY_CONFIG)
        ret, per_asset = eco._simulate_monthly_investment_return(
            100000, {"deposits": 0.5, "funds": 0.3, "stocks": 0.2}, cfg)
        self.assertNotEqual(ret, 0.0)
        self.assertIn("stocks", per_asset)


class TestKeywordDisjointness(unittest.TestCase):
    def test_income_keywords_disjoint_from_expense_keywords(self):
        income = set(eco.INCOME_KEYWORDS)
        for category, keywords in eco.EXPENSE_KEYWORDS.items():
            overlap = income & set(keywords)
            self.assertFalse(
                overlap,
                msg=f"INCOME_KEYWORDS overlaps EXPENSE_KEYWORDS[{category}]: {overlap}")


if __name__ == "__main__":
    unittest.main()
