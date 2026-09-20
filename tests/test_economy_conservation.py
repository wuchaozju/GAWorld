"""Money-conservation tests for the economy sector-pool system (P1).

Every agent money flow now has a sector counterparty (firms / government /
bank), so after initialization the total money in the system must stay
constant to within one cent, no matter how long the simulation runs.
"""

import os
import tempfile
import unittest

from gaworld.economy import finance as eco


def _build_agent(agent_id=1, job="软件工程师", age=30, risk_preference=0.6):
    return {
        "id": agent_id,
        "name": f"A{agent_id}",
        "age": age,
        "job": job,
        "personality": "上进务实",
        "values": "重视稳定和成长",
        "daily_life": "规律生活",
        "state": {
            "emotion": 0.5,
            "stress": 0.5,
            "econ_security": 0.5,
            "risk_preference": risk_preference,
        },
    }


def _build_config(tmpdir, **econ_over):
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


class TestSectorFlows(unittest.TestCase):
    """Unit-level: each flow debits/credits its counterparty by the same amount."""

    def _econ(self):
        return {
            "daily_income": 0.0, "daily_expense": 0.0,
            "lifetime_income": 0.0, "lifetime_expense": 0.0,
            "daily_expense_by_category": eco._empty_daily_categories(),
            "accounts": {"checking": 1000.0},
        }

    def test_income_paid_by_firms(self):
        econ, sectors = self._econ(), {"firms": 0.0, "government": 0.0, "bank": 0.0}
        eco._record_income(econ, 123.45, sectors)
        self.assertEqual(econ["accounts"]["checking"], 1123.45)
        self.assertEqual(sectors["firms"], -123.45)

    def test_expense_flows_to_firms(self):
        econ, sectors = self._econ(), {"firms": 0.0, "government": 0.0, "bank": 0.0}
        eco._record_expense(econ, "food", 45.678, sectors)
        # Amount is quantized to cents on both sides
        self.assertEqual(econ["accounts"]["checking"], 1000.0 - 45.68)
        self.assertEqual(sectors["firms"], 45.68)

    def test_helpers_work_without_sectors(self):
        econ = self._econ()
        eco._record_income(econ, 50.0)
        eco._record_expense(econ, "food", 20.0)
        self.assertEqual(econ["accounts"]["checking"], 1030.0)

    def test_medical_emergency_conserves(self):
        agent = _build_agent()
        cfg = eco.deepcopy(eco.DEFAULT_ECONOMY_CONFIG)
        cfg["shocks"].update({"layoff_base_prob": 0.0, "raise_base_prob": 0.0,
                              "medical_emergency_prob": 1.0})
        econ = self._econ()
        econ["base_hourly_income"] = 80
        sectors = {"firms": 0.0, "government": 0.0, "bank": 0.0}
        before = econ["accounts"]["checking"] + sum(sectors.values())
        events = eco._check_daily_shocks(agent, econ, cfg, {"enabled": False},
                                         sectors=sectors)
        self.assertTrue(any(e["type"] == "medical_emergency" for e in events))
        after = econ["accounts"]["checking"] + sum(sectors.values())
        # Patient + government together pay exactly what the hospital receives
        self.assertAlmostEqual(before, after, places=2)
        self.assertLess(sectors["government"], 0.0)   # reimbursement paid
        self.assertGreater(sectors["firms"], 0.0)     # hospital revenue


class TestMonthlySettlement(unittest.TestCase):
    """Month-end withholding routes tax/SI to government and books housing fund."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.config = _build_config(
            self.tmpdir.name,
            # Isolate the withholding flow from stochastic month-end noise
            shocks={"enabled": False},
            investment={"enabled": False, "auto_save_enabled": False},
        )

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_withholding_flows(self):
        agent = _build_agent()
        ext = {}
        ctx = {"config": self.config, "agents": [agent], "extension_state": ext}
        eco.on_simulation_start(ctx)
        runtime = ext["economy_module"]
        sectors = runtime["sectors"]
        econ = agent["economy"]

        realized_gross = 20000.0
        econ["month_gross_income"] = realized_gross
        checking_before = econ["accounts"]["checking"]
        hf_before = econ["accounts"]["housing_fund"]
        initial_total = runtime["initial_system_total"]

        runtime["sim_day_counter"] = 30  # force month end
        end_ctx = {"config": self.config, "day": 30,
                   "agents": [agent], "daily_logs": {1: ""},
                   "extension_state": ext}
        eco.on_day_end(end_ctx)

        cfg = eco._get_cfg({"config": self.config})
        _, tax, si_total, si_bd, hf_total = eco.calc_net_monthly_salary(realized_gross, cfg)
        hf_indiv = si_bd["housing_fund_individual"]

        # Checking pays tax + SI (incl. individual housing fund part)
        self.assertAlmostEqual(
            econ["accounts"]["checking"], checking_before - (tax + si_total), places=2)
        # Government receives tax + SI minus the individual HF part
        self.assertAlmostEqual(sectors["government"], tax + si_total - hf_indiv, places=2)
        # Housing fund receives individual part + employer match
        self.assertAlmostEqual(
            econ["accounts"]["housing_fund"], hf_before + hf_total, places=2)
        # Employer match came out of the firms pool
        self.assertAlmostEqual(sectors["firms"], -(hf_total - hf_indiv), places=2)
        # Accumulator reset & system total conserved
        self.assertEqual(econ["month_gross_income"], 0.0)
        self.assertAlmostEqual(
            eco._system_total([agent], sectors), initial_total, places=2)


class TestLongRunConservation(unittest.TestCase):
    """End-to-end: a year of simulated days must conserve money to the cent."""

    def test_year_long_conservation(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = _build_config(tmp)
            agents = [_build_agent(i, job=j, age=a) for i, (j, a) in
                      enumerate([("医生", 45), ("程序员", 28), ("店员", 33)], start=1)]
            # Exercise P3 paths under conservation: the 店员 is a merchant at
            # the spend location, and a full social network enables friend loans.
            agents[2]["locations"] = {"workplace": "Office", "home": "Home"}
            for a in agents:
                others = [x["id"] for x in agents if x is not a]
                a["social_neighbors"] = others
                a["relationships"] = {
                    str(i): {"closeness": 0.8, "trust": 0.8} for i in others}
            ext = {}
            ctx = {"config": config, "agents": agents, "extension_state": ext}
            eco.on_simulation_start(ctx)
            runtime = ext["economy_module"]
            initial_total = runtime["initial_system_total"]

            for day in range(1, 371):
                day_ctx = {"config": config, "day": day, "agents": agents,
                           "daily_logs": {a["id"]: "" for a in agents},
                           "extension_state": ext}
                eco.on_day_start(day_ctx)
                for agent in agents:
                    post_ctx = {"config": config, "day": day, "time_str": "10:00",
                                "agent": agent,
                                "step": {"activity": "工作", "action": "推进任务",
                                         "location": "Office"},
                                "daily_logs": day_ctx["daily_logs"],
                                "extension_state": ext}
                    eco.on_agent_post_step(post_ctx)
                eco.on_day_end(day_ctx)

            final_total = eco._system_total(agents, runtime["sectors"])
            self.assertLessEqual(abs(final_total - initial_total), 0.01)

            # Audit rows recorded daily with ~zero drift throughout
            audit = runtime["audit_rows"]
            self.assertEqual(len(audit), 370)
            self.assertLessEqual(max(abs(r["drift"]) for r in audit), 0.01)

            # A year of wages/taxes actually moved money through the pools.
            # (Government sign is indeterminate: a single large medical
            # reimbursement can exceed a small population's annual taxes.)
            sectors = runtime["sectors"]
            self.assertLess(sectors["firms"], 0.0)          # net wage payer
            self.assertNotEqual(sectors["government"], 0.0)  # taxes/reimbursements flowed

            # Exports include the audit trail
            end_ctx = {"config": config, "agents": agents, "extension_state": ext}
            eco.on_simulation_end(end_ctx)
            out = config["economy"]["output_dir"]
            self.assertTrue(os.path.exists(os.path.join(out, "conservation_audit.csv")))
            self.assertTrue(os.path.exists(os.path.join(out, "sectors.json")))


if __name__ == "__main__":
    unittest.main()
