import os
import random
import tempfile
import unittest
import csv
import json
from unittest.mock import patch

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


def _build_config(tmpdir, **overrides):
    base = {
        "stateful": True,
        "memory_dir": os.path.join(tmpdir, "memory"),
        "log_dir": os.path.join(tmpdir, "logs"),
        "economy": {
            "enabled": True,
            "output_dir": os.path.join(tmpdir, "economy"),
            "hours_per_step": 1.0,
        },
    }
    for k, v in overrides.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            base[k].update(v)
        else:
            base[k] = v
    return base


class TestTaxAndSocialInsurance(unittest.TestCase):
    """Verify Chinese tax & social insurance calculations."""

    def test_social_insurance_deduction(self):
        cfg = eco.deepcopy(eco.DEFAULT_ECONOMY_CONFIG)
        gross = 15000.0
        total, breakdown, hf = eco.calc_social_insurance(gross, cfg)
        # pension 8% + medical 2% + unemployment 0.5% + housing fund 8% = 18.5%
        expected_total = 15000 * (0.08 + 0.02 + 0.005 + 0.08)
        self.assertAlmostEqual(total, expected_total, places=1)
        self.assertIn("pension", breakdown)
        self.assertIn("housing_fund_individual", breakdown)
        # Housing fund total = individual + employer
        self.assertAlmostEqual(hf, 15000 * 0.08 * 2, places=1)

    def test_social_insurance_respects_cap(self):
        cfg = eco.deepcopy(eco.DEFAULT_ECONOMY_CONFIG)
        gross = 80000.0  # way above cap of 36000
        total, _, _ = eco.calc_social_insurance(gross, cfg)
        capped_total = 36000 * (0.08 + 0.02 + 0.005 + 0.08)
        self.assertAlmostEqual(total, capped_total, places=1)

    def test_income_tax_low_income_zero(self):
        cfg = eco.deepcopy(eco.DEFAULT_ECONOMY_CONFIG)
        # Gross 5000 -> SI ~925 -> taxable = 5000-925-5000-1500 < 0 -> tax = 0
        tax = eco.calc_income_tax(5000.0, 925.0, cfg)
        self.assertEqual(tax, 0.0)

    def test_income_tax_middle_income(self):
        cfg = eco.deepcopy(eco.DEFAULT_ECONOMY_CONFIG)
        gross = 15000.0
        si = 15000 * 0.185  # 2775
        taxable = gross - si - 5000 - 1500  # 15000 - 2775 - 5000 - 1500 = 5725
        # Falls in 3000-12000 bracket: 10% rate, 210 quick deduction
        expected = 5725 * 0.10 - 210
        tax = eco.calc_income_tax(gross, si, cfg)
        self.assertAlmostEqual(tax, expected, places=1)

    def test_net_salary_pipeline(self):
        cfg = eco.deepcopy(eco.DEFAULT_ECONOMY_CONFIG)
        gross = 20000.0
        net, tax, si_total, si_bd, hf = eco.calc_net_monthly_salary(gross, cfg)
        self.assertGreater(net, 0)
        self.assertLess(net, gross)
        self.assertEqual(round(gross - si_total - tax, 2), net)
        self.assertGreater(hf, 0)

    def test_tax_disabled(self):
        cfg = eco.deepcopy(eco.DEFAULT_ECONOMY_CONFIG)
        cfg["tax"]["enabled"] = False
        tax = eco.calc_income_tax(50000, 5000, cfg)
        self.assertEqual(tax, 0.0)

    def test_social_insurance_disabled(self):
        cfg = eco.deepcopy(eco.DEFAULT_ECONOMY_CONFIG)
        cfg["social_insurance"]["enabled"] = False
        total, bd, hf = eco.calc_social_insurance(20000, cfg)
        self.assertEqual(total, 0.0)
        self.assertEqual(hf, 0.0)


class TestEngelCoefficient(unittest.TestCase):
    """Test Engel-coefficient-based spending allocation."""

    def test_low_income_high_engel(self):
        cfg = eco.deepcopy(eco.DEFAULT_ECONOMY_CONFIG)
        engel, save = eco._engel_params(3000, cfg)
        self.assertGreaterEqual(engel, 0.40)
        self.assertLess(save, 0.10)

    def test_high_income_low_engel(self):
        cfg = eco.deepcopy(eco.DEFAULT_ECONOMY_CONFIG)
        engel, save = eco._engel_params(25000, cfg)
        self.assertLessEqual(engel, 0.20)
        self.assertGreater(save, 0.30)

    def test_monthly_budget_food_dominates_low_income(self):
        cfg = eco.deepcopy(eco.DEFAULT_ECONOMY_CONFIG)
        budget = eco._build_monthly_budget(3500, 0.48, 0.05, cfg)
        total_consumption = 3500 * 0.95
        food_ratio = budget["food"] / total_consumption
        self.assertGreater(food_ratio, 0.35)

    def test_monthly_budget_leisure_grows_with_income(self):
        cfg = eco.deepcopy(eco.DEFAULT_ECONOMY_CONFIG)
        budget_low = eco._build_monthly_budget(4000, 0.45, 0.05, cfg)
        budget_high = eco._build_monthly_budget(25000, 0.15, 0.40, cfg)
        # Leisure absolute spend should be much higher for high income
        self.assertGreater(budget_high.get("leisure", 0), budget_low.get("leisure", 0))


class TestInvestment(unittest.TestCase):
    """Test investment portfolio and return simulation."""

    def test_portfolio_type_mapping(self):
        conservative = _build_agent(risk_preference=0.2)
        self.assertEqual(eco._infer_portfolio_type(conservative), "conservative")
        aggressive = _build_agent(risk_preference=0.8)
        self.assertEqual(eco._infer_portfolio_type(aggressive), "aggressive")

    def test_investment_return_simulation(self):
        eco._rng.seed(42)
        cfg = eco.deepcopy(eco.DEFAULT_ECONOMY_CONFIG)
        weights = {"deposits": 0.5, "funds": 0.3, "stocks": 0.2}
        ret, per_asset = eco._simulate_monthly_investment_return(100000, weights, cfg)
        # Returns should be non-zero with 100k invested
        self.assertNotEqual(ret, 0.0)
        self.assertIn("deposits", per_asset)

    def test_investment_return_zero_balance(self):
        cfg = eco.deepcopy(eco.DEFAULT_ECONOMY_CONFIG)
        ret, per_asset = eco._simulate_monthly_investment_return(0, {"deposits": 1.0}, cfg)
        self.assertEqual(ret, 0.0)

    def test_monthly_savings_transfer(self):
        econ = {
            "accounts": {"checking": 50000, "savings": 10000, "investment": 5000},
            "monthly_expense_estimate": 8000,
            "risk_tolerance": 0.5,
        }
        cfg = eco.deepcopy(eco.DEFAULT_ECONOMY_CONFIG)
        to_sav, to_inv = eco._monthly_savings_transfer(econ, cfg)
        # Should transfer from checking (50k) minus buffer (8k*2=16k) = 34k
        self.assertGreater(to_sav + to_inv, 0)
        self.assertLess(econ["accounts"]["checking"], 50000)


class TestMacroCycle(unittest.TestCase):
    """Test macro-economic cycle mechanics."""

    def test_init_macro_state(self):
        cfg = eco.deepcopy(eco.DEFAULT_ECONOMY_CONFIG)
        macro = eco._init_macro_state(cfg)
        self.assertTrue(macro["enabled"])
        self.assertEqual(macro["phase"], "expansion")
        self.assertGreater(macro["inflation_rate"], 0)

    def test_advance_macro_cycle_phase_transition(self):
        cfg = eco.deepcopy(eco.DEFAULT_ECONOMY_CONFIG)
        macro = eco._init_macro_state(cfg)
        macro["phase_day_counter"] = macro["phase_duration"] - 1
        eco._advance_macro_cycle(macro, cfg)
        # Should have transitioned to next phase
        self.assertEqual(macro["phase"], "peak")

    def test_macro_income_multiplier(self):
        cfg = eco.deepcopy(eco.DEFAULT_ECONOMY_CONFIG)
        macro = {"enabled": True, "phase": "contraction",
                 "industry_conditions": {"tech": 0.8}}
        mult = eco._macro_income_multiplier(macro, "tech", cfg)
        # contraction income_mult=0.95 * industry 0.8 = 0.76
        self.assertLess(mult, 1.0)


class TestShockEvents(unittest.TestCase):
    """Test economic shock events."""

    def test_layoff_shock(self):
        eco._rng.seed(7)
        agent = _build_agent()
        cfg = eco.deepcopy(eco.DEFAULT_ECONOMY_CONFIG)
        econ = {"base_hourly_income": 80, "gross_monthly_salary": 14080,
                "income_skill": 0.6,
                "daily_expense": 0, "daily_expense_by_category": eco._empty_daily_categories(),
                "accounts": {"checking": 50000}}
        macro = {"enabled": True, "phase": "trough"}
        # Force layoff
        with patch.object(eco._rng, "random", return_value=0.0):
            events = eco._check_daily_shocks(agent, econ, cfg, macro)
        layoffs = [e for e in events if e["type"] == "layoff"]
        self.assertTrue(len(layoffs) > 0)
        self.assertLess(econ["base_hourly_income"], 80)
        # Gross salary must drop proportionally so the monthly settlement
        # (tax / SI / budget) uses the post-layoff tax base.
        self.assertLess(econ["gross_monthly_salary"], 14080)
        self.assertAlmostEqual(
            econ["gross_monthly_salary"] / 14080,
            econ["base_hourly_income"] / 80, places=4)

    def test_medical_emergency(self):
        eco._rng.seed(11)
        agent = _build_agent()
        cfg = eco.deepcopy(eco.DEFAULT_ECONOMY_CONFIG)
        econ = {"base_hourly_income": 80, "income_skill": 0.6,
                "daily_expense": 0, "daily_expense_by_category": eco._empty_daily_categories(),
                "accounts": {"checking": 50000}}
        macro = {"enabled": False}
        # Force medical emergency
        with patch.object(eco._rng, "random", return_value=0.0):
            events = eco._check_daily_shocks(agent, econ, cfg, macro)
        medical = [e for e in events if e["type"] == "medical_emergency"]
        self.assertTrue(len(medical) > 0)
        self.assertLess(econ["accounts"]["checking"], 50000)


class TestEconomyModule(unittest.TestCase):
    """Integration tests for full economy lifecycle."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.config = _build_config(self.tmpdir.name)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_init_sets_finance_profile(self):
        eco._rng.seed(7)
        agent = _build_agent()
        ctx = {"config": self.config, "agents": [agent], "extension_state": {}}
        eco.on_simulation_start(ctx)
        self.assertIn("economy", agent)
        econ = agent["economy"]
        self.assertGreater(econ["balance"], 0.0)
        self.assertIn("wealth_drive", econ)
        self.assertIn("initial_assets", econ)
        self.assertIn("inheritance", econ["initial_assets"])
        # New fields
        self.assertIn("accounts", econ)
        self.assertIn("checking", econ["accounts"])
        self.assertIn("gross_monthly_salary", econ)
        self.assertIn("net_monthly_salary", econ)
        self.assertIn("monthly_tax", econ)
        self.assertIn("engel_coefficient", econ)
        self.assertIn("portfolio_type", econ)
        self.assertLess(econ["net_monthly_salary"], econ["gross_monthly_salary"])
        self.assertTrue(os.path.exists(os.path.join(
            self.config["log_dir"], "agent_1.log")))

    def test_init_multi_account_sums_to_balance(self):
        eco._rng.seed(13)
        agent = _build_agent()
        ctx = {"config": self.config, "agents": [agent], "extension_state": {}}
        eco.on_simulation_start(ctx)
        econ = agent["economy"]
        accounts = econ["accounts"]
        liquid = accounts["checking"] + accounts["savings"] + accounts["investment"]
        self.assertAlmostEqual(econ["balance"], liquid, places=1)

    def test_init_can_include_inheritance_assets(self):
        eco._rng.seed(9)
        agent = _build_agent()
        cfg = dict(self.config)
        cfg["economy"] = dict(self.config["economy"])
        cfg["economy"]["inheritance_enabled"] = True
        cfg["economy"]["inheritance_base_probability"] = 1.0
        start_ctx = {"config": cfg, "agents": [agent], "extension_state": {}}
        eco.on_simulation_start(start_ctx)
        init_assets = agent["economy"]["initial_assets"]
        self.assertGreater(init_assets["inheritance"], 0.0)
        self.assertAlmostEqual(
            init_assets["total"],
            init_assets["labor_savings"] + init_assets["inheritance"],
            places=2)

    def test_high_wealth_drive_can_seek_income_activity(self):
        eco._rng.seed(11)
        agent = _build_agent()
        ctx = {"config": self.config, "agents": [agent], "extension_state": {}}
        eco.on_simulation_start(ctx)
        agent["economy"]["wealth_drive"] = 0.95
        agent["economy"]["accounts"]["checking"] = 0.0
        agent["economy"]["accounts"]["savings"] = 0.0
        agent["economy"]["accounts"]["investment"] = 0.0
        agent["economy"]["balance"] = 0.0
        agent["economy"]["daily_income"] = 0.0
        agent["economy"]["income_target_daily"] = 500.0

        step = {"scheduled_activity": "散步", "activity": "散步"}
        pre_ctx = {
            "config": self.config,
            "agent": agent,
            "step": step,
            "actions": {1: {"工作": ["处理任务"]}},
            "extension_state": ctx["extension_state"],
        }
        with patch.object(eco._rng, "random", return_value=0.0):
            eco.on_agent_pre_step(pre_ctx)
        self.assertEqual("工作", step["activity"])
        self.assertTrue(step.get("economy_forced_income", False))

    def test_post_step_records_income_and_expense(self):
        eco._rng.seed(19)
        agent = _build_agent()
        ext = {}
        start_ctx = {"config": self.config, "agents": [agent], "extension_state": ext}
        eco.on_simulation_start(start_ctx)
        day_ctx = {
            "config": self.config, "day": 1,
            "agents": [agent], "daily_logs": {1: ""},
            "extension_state": ext,
        }
        eco.on_day_start(day_ctx)
        before_balance = agent["economy"]["balance"]
        post_ctx = {
            "config": self.config, "day": 1, "time_str": "10:00",
            "agent": agent,
            "step": {"activity": "工作", "action": "推进研发任务", "location": "Office"},
            "daily_logs": day_ctx["daily_logs"],
            "extension_state": ext,
        }
        eco.on_agent_post_step(post_ctx)
        econ = agent["economy"]
        self.assertGreater(econ["daily_income"], 0.0)
        self.assertGreater(econ["daily_expense"], 0.0)
        self.assertNotEqual(before_balance, econ["balance"])

    def test_day_end_does_not_raise_income_on_deficit(self):
        """Running a deficit must NOT magically raise wages (removed perpetual-motion rule)."""
        eco._rng.seed(23)
        agent = _build_agent()
        ext = {}
        start_ctx = {"config": self.config, "agents": [agent], "extension_state": ext}
        eco.on_simulation_start(start_ctx)
        econ = agent["economy"]
        base_before = econ["base_hourly_income"]
        skill_before = econ["income_skill"]
        econ["wealth_drive"] = 0.9
        econ["daily_income"] = 20.0
        econ["daily_expense"] = 180.0
        econ["income_target_daily"] = 120.0
        end_ctx = {
            "config": self.config, "day": 1,
            "agents": [agent], "daily_logs": {1: ""},
            "extension_state": ext,
        }
        eco.on_day_end(end_ctx)
        self.assertEqual(base_before, agent["economy"]["base_hourly_income"])
        self.assertEqual(skill_before, agent["economy"]["income_skill"])
        self.assertEqual(1, len(ext["economy_module"]["day_rows"]))

    def test_day_rows_include_new_fields(self):
        eco._rng.seed(31)
        agent = _build_agent()
        ext = {}
        ctx = {"config": self.config, "agents": [agent], "extension_state": ext}
        eco.on_simulation_start(ctx)
        agent["economy"]["daily_income"] = 100
        agent["economy"]["daily_expense"] = 50
        end_ctx = {
            "config": self.config, "day": 1,
            "agents": [agent], "daily_logs": {1: ""},
            "extension_state": ext,
        }
        eco.on_day_end(end_ctx)
        row = ext["economy_module"]["day_rows"][0]
        self.assertIn("checking", row)
        self.assertIn("savings", row)
        self.assertIn("investment", row)
        self.assertIn("housing_fund", row)
        self.assertIn("engel_coefficient", row)
        self.assertIn("macro_phase", row)

    def test_simulation_end_exports_per_agent_files(self):
        eco._rng.seed(31)
        agent1 = _build_agent(1)
        agent2 = _build_agent(2)
        ext = {}
        start_ctx = {"config": self.config, "agents": [agent1, agent2], "extension_state": ext}
        eco.on_simulation_start(start_ctx)
        for agent in (agent1, agent2):
            agent["economy"]["daily_income"] = 100.0 + agent["id"]
            agent["economy"]["daily_expense"] = 40.0 + agent["id"]
        day_ctx = {
            "config": self.config, "day": 1,
            "agents": [agent1, agent2], "daily_logs": {1: "", 2: ""},
            "extension_state": ext,
        }
        eco.on_day_end(day_ctx)
        end_ctx = {"config": self.config, "agents": [agent1, agent2], "extension_state": ext}
        eco.on_simulation_end(end_ctx)

        output_dir = self.config["economy"]["output_dir"]
        self.assertTrue(os.path.exists(os.path.join(output_dir, "daily_ledger.csv")))
        self.assertTrue(os.path.exists(os.path.join(output_dir, "wealth_snapshot.csv")))
        self.assertTrue(os.path.exists(os.path.join(output_dir, "agents", "agent_1_ledger.csv")))
        self.assertTrue(os.path.exists(os.path.join(output_dir, "agents", "agent_2_ledger.csv")))
        self.assertTrue(os.path.exists(os.path.join(output_dir, "agents", "agent_1_snapshot.json")))
        self.assertTrue(os.path.exists(os.path.join(output_dir, "macro_state.json")))

        with open(os.path.join(output_dir, "wealth_snapshot.csv"), "r", encoding="utf-8") as f:
            snap_rows = list(csv.DictReader(f))
        self.assertIn("initial_inheritance", snap_rows[0])
        self.assertIn("gross_monthly_salary", snap_rows[0])
        self.assertIn("monthly_tax", snap_rows[0])
        self.assertIn("engel_coefficient", snap_rows[0])
        self.assertIn("portfolio_type", snap_rows[0])

    def test_different_jobs_produce_different_profiles(self):
        """Doctors should earn more than students; spending patterns differ."""
        eco._rng.seed(42)
        doctor = _build_agent(1, job="医生", age=40)
        student = _build_agent(2, job="大学生", age=21)
        ext = {}
        ctx = {"config": self.config, "agents": [doctor, student], "extension_state": ext}
        eco.on_simulation_start(ctx)
        doc_econ = doctor["economy"]
        stu_econ = student["economy"]
        self.assertGreater(doc_econ["gross_monthly_salary"], stu_econ["gross_monthly_salary"])
        self.assertGreater(doc_econ["engel_coefficient"], 0)
        # Doctor should have lower Engel coefficient (richer)
        if doc_econ["net_monthly_salary"] > stu_econ["net_monthly_salary"]:
            self.assertLessEqual(doc_econ["engel_coefficient"], stu_econ["engel_coefficient"])

    def test_rng_isolated_from_global_random(self):
        """Same random_seed → identical economy, even if the global RNG is perturbed."""
        def run_once():
            agent = _build_agent()
            cfg = _build_config(self.tmpdir.name)
            cfg["stateful"] = False  # no state reload between runs
            cfg["random_seed"] = 42
            ctx = {"config": cfg, "agents": [agent], "extension_state": {}}
            eco.on_simulation_start(ctx)
            return agent["economy"]

        econ_a = run_once()
        random.random()  # perturb the global stream between runs
        econ_b = run_once()
        self.assertEqual(econ_a["gross_monthly_salary"], econ_b["gross_monthly_salary"])
        self.assertEqual(econ_a["accounts"], econ_b["accounts"])
        self.assertEqual(econ_a["initial_assets"], econ_b["initial_assets"])

    def test_industry_mapping(self):
        agent_tech = _build_agent(job="程序员")
        agent_fin = _build_agent(job="证券分析师")
        agent_other = _build_agent(job="自由职业")
        self.assertEqual(eco._infer_industry(agent_tech), "tech")
        self.assertEqual(eco._infer_industry(agent_fin), "finance")
        self.assertEqual(eco._infer_industry(agent_other), "default")


if __name__ == "__main__":
    unittest.main()
