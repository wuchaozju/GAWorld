"""Tests for P3 economy features: payment routing to merchant/landlord agents,
friend loans over the social network, and bench distribution metrics."""

import csv
import importlib.util
import os
import tempfile
import unittest
from pathlib import Path

from gaworld.economy import finance as eco

_ROOT = Path(__file__).resolve().parent.parent


def _load_bench():
    spec = importlib.util.spec_from_file_location(
        "gaworld_bench", _ROOT / "benchmark" / "gaworld_bench.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _build_agent(agent_id, job, age=30, workplace=None):
    agent = {
        "id": agent_id, "name": f"A{agent_id}", "age": age, "job": job,
        "personality": "务实", "values": "稳定", "daily_life": "规律",
        "state": {"emotion": 0.5, "stress": 0.5, "econ_security": 0.5,
                  "risk_preference": 0.5},
    }
    if workplace:
        agent["locations"] = {"workplace": workplace, "home": "Home"}
    return agent


def _config(tmpdir, **econ_over):
    economy = {
        "enabled": True,
        "output_dir": os.path.join(tmpdir, "economy"),
        "hours_per_step": 1.0,
        "shocks": {"enabled": False},
        "investment": {"enabled": False, "auto_save_enabled": False},
    }
    economy.update(econ_over)
    return {
        "stateful": False, "random_seed": 7,
        "memory_dir": os.path.join(tmpdir, "memory"),
        "log_dir": os.path.join(tmpdir, "logs"),
        "economy": economy,
    }


class TestMerchantRouting(unittest.TestCase):
    def test_local_spend_routes_to_merchant(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = _config(tmp)
            consumer = _build_agent(1, "程序员")
            merchant = _build_agent(2, "店员", workplace="美食街")
            agents = [consumer, merchant]
            ext = {}
            ctx = {"config": config, "agents": agents, "extension_state": ext}
            eco.on_simulation_start(ctx)
            runtime = ext["economy_module"]
            self.assertEqual(runtime["merchants"], {"美食街": [2]})
            initial = runtime["initial_system_total"]

            day_ctx = {"config": config, "day": 1, "agents": agents,
                       "daily_logs": {1: "", 2: ""}, "extension_state": ext}
            eco.on_day_start(day_ctx)
            post_ctx = {"config": config, "day": 1, "time_str": "12:00",
                        "agent": consumer,
                        "step": {"activity": "吃饭逛街", "action": "外卖聚餐",
                                 "location": "美食街"},
                        "daily_logs": day_ctx["daily_logs"],
                        "extension_state": ext}
            eco.on_agent_post_step(post_ctx)
            self.assertGreater(runtime["location_spend"].get("美食街", 0), 0)

            merchant_income_before = merchant["economy"]["daily_income"]
            eco.on_day_end(day_ctx)
            # Merchant received a labor share of the local spend
            self.assertGreater(merchant["economy"]["daily_income"],
                               merchant_income_before)
            # Routed income enters the merchant's tax base
            self.assertGreater(merchant["economy"]["month_gross_income"], 0)
            # Spend accumulator reset & money conserved
            self.assertEqual(runtime["location_spend"], {})
            self.assertLessEqual(
                abs(eco._system_total(agents, runtime["sectors"]) - initial), 0.01)

    def test_no_merchant_means_money_stays_with_firms(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = _config(tmp)
            consumer = _build_agent(1, "程序员")
            agents = [consumer]
            ext = {}
            ctx = {"config": config, "agents": agents, "extension_state": ext}
            eco.on_simulation_start(ctx)
            runtime = ext["economy_module"]
            initial = runtime["initial_system_total"]
            day_ctx = {"config": config, "day": 1, "agents": agents,
                       "daily_logs": {1: ""}, "extension_state": ext}
            eco.on_day_start(day_ctx)
            eco.on_day_end(day_ctx)
            self.assertLessEqual(
                abs(eco._system_total(agents, runtime["sectors"]) - initial), 0.01)


class TestLandlordRouting(unittest.TestCase):
    def test_rent_routes_to_landlord(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = _config(tmp)
            tenant = _build_agent(1, "程序员")
            landlord = _build_agent(2, "房东")
            agents = [tenant, landlord]
            ext = {}
            ctx = {"config": config, "agents": agents, "extension_state": ext}
            eco.on_simulation_start(ctx)
            runtime = ext["economy_module"]
            self.assertEqual(runtime["landlords"], [2])
            initial = runtime["initial_system_total"]

            day_ctx = {"config": config, "day": 1, "agents": agents,
                       "daily_logs": {1: "", 2: ""}, "extension_state": ext}
            eco.on_day_start(day_ctx)  # charges daily rent to both agents
            self.assertGreater(runtime["rent_paid_today"], 0)
            eco.on_day_end(day_ctx)
            self.assertGreater(landlord["economy"]["daily_income"], 0)
            self.assertEqual(runtime["rent_paid_today"], 0.0)
            self.assertLessEqual(
                abs(eco._system_total(agents, runtime["sectors"]) - initial), 0.01)


class TestFriendLoans(unittest.TestCase):
    def _setup(self, tmp):
        config = _config(tmp)
        borrower = _build_agent(1, "店员")
        lender = _build_agent(2, "医生", age=45)
        borrower["social_neighbors"] = [2]
        borrower["relationships"] = {"2": {"closeness": 0.9, "trust": 0.9}}
        agents = [borrower, lender]
        ext = {}
        ctx = {"config": config, "agents": agents, "extension_state": ext}
        eco.on_simulation_start(ctx)
        return config, borrower, lender, agents, ext

    def test_distressed_agent_borrows_from_friend(self):
        with tempfile.TemporaryDirectory() as tmp:
            config, borrower, lender, agents, ext = self._setup(tmp)
            runtime = ext["economy_module"]
            b_econ, l_econ = borrower["economy"], lender["economy"]
            b_econ["accounts"].update({"checking": 0.0, "savings": 0.0,
                                       "investment": 0.0})
            b_econ["_distress_today"] = True
            l_econ["accounts"]["checking"] = 200000.0
            total_before = eco._system_total(agents, runtime["sectors"])
            lender_before = l_econ["accounts"]["checking"]

            day_ctx = {"config": config, "day": 1, "agents": agents,
                       "daily_logs": {1: "", 2: ""}, "extension_state": ext}
            eco.on_day_end(day_ctx)

            loan = b_econ.get("friend_debts", {}).get("2", 0)
            self.assertGreater(loan, 0)
            self.assertGreater(b_econ["accounts"]["checking"], 0)
            self.assertLess(l_econ["accounts"]["checking"], lender_before)
            self.assertEqual(l_econ["friend_credits"].get("1"), loan)
            self.assertLessEqual(
                abs(eco._system_total(agents, runtime["sectors"]) - total_before), 0.01)

    def test_friend_loan_repaid_at_month_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            config, borrower, lender, agents, ext = self._setup(tmp)
            runtime = ext["economy_module"]
            b_econ, l_econ = borrower["economy"], lender["economy"]
            b_econ["friend_debts"] = {"2": 1000.0}
            l_econ["friend_credits"] = {"1": 1000.0}
            b_econ["accounts"]["checking"] = 50000.0  # plenty of surplus
            b_econ["month_gross_income"] = 0.0
            lender_before = l_econ["accounts"]["checking"]

            runtime["sim_day_counter"] = 30  # force month end
            day_ctx = {"config": config, "day": 30, "agents": agents,
                       "daily_logs": {1: "", 2: ""}, "extension_state": ext}
            eco.on_day_end(day_ctx)

            self.assertEqual(b_econ.get("friend_debts", {}), {})
            self.assertEqual(l_econ.get("friend_credits", {}), {})
            self.assertAlmostEqual(
                l_econ["accounts"]["checking"], lender_before + 1000.0, places=2)


class TestBenchDistributionMetrics(unittest.TestCase):
    def test_gini(self):
        bench = _load_bench()
        self.assertAlmostEqual(bench.gini([1, 1, 1, 1]), 0.0, places=9)
        self.assertAlmostEqual(bench.gini([0, 0, 0, 10]), 0.75, places=9)
        self.assertIsNone(bench.gini([]))
        self.assertIsNone(bench.gini([0.0, 0.0]))

    def test_track_a_scores_gini_and_conservation(self):
        bench = _load_bench()
        with tempfile.TemporaryDirectory() as tmp:
            econ_dir = Path(tmp) / "economy"
            econ_dir.mkdir(parents=True)
            with open(econ_dir / "wealth_snapshot.csv", "w", newline="",
                      encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=[
                    "agent_id", "balance", "housing_fund", "debt",
                    "engel_coefficient", "savings_rate"])
                w.writeheader()
                for i, bal in enumerate([1000, 5000, 20000, 200000], start=1):
                    w.writerow({"agent_id": i, "balance": bal,
                                "housing_fund": 0, "debt": 0,
                                "engel_coefficient": 0.30, "savings_rate": 0.33})
            with open(econ_dir / "conservation_audit.csv", "w", newline="",
                      encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=["day", "drift"])
                w.writeheader()
                w.writerow({"day": 1, "drift": 0.0})
                w.writerow({"day": 2, "drift": 0.0})
            result = bench.track_a_macro_fit(Path(tmp))
            self.assertIn("wealth_gini", result["metrics"])
            self.assertTrue(result["conservation"]["pass"])

    def test_track_a_conservation_gate_fails_on_drift(self):
        bench = _load_bench()
        with tempfile.TemporaryDirectory() as tmp:
            econ_dir = Path(tmp) / "economy"
            econ_dir.mkdir(parents=True)
            with open(econ_dir / "wealth_snapshot.csv", "w", newline="",
                      encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=[
                    "agent_id", "balance", "engel_coefficient", "savings_rate"])
                w.writeheader()
                w.writerow({"agent_id": 1, "balance": 10000,
                            "engel_coefficient": 0.288, "savings_rate": 0.35})
            with open(econ_dir / "conservation_audit.csv", "w", newline="",
                      encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=["day", "drift"])
                w.writeheader()
                w.writerow({"day": 1, "drift": 123.45})
            result = bench.track_a_macro_fit(Path(tmp))
            self.assertFalse(result["conservation"]["pass"])
            self.assertFalse(result["pass"])


if __name__ == "__main__":
    unittest.main()
