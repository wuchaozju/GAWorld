"""The public sector: governments, their policies, and what they do to a run.

What is covered, and why each matters:

* **Policies land on the rules the economy actually runs.** A government that
  only shows up in a prompt would be a label, not a policy. The derivation is
  checked against the economy's own tax and insurance functions.
* **Transfers are booked on both sides.** Benefits paid out of thin air would
  break the money-conservation audit the currency panel reports.
* **A change of government re-derives from the base.** Deriving from the
  previous government's economy would compound: welfare → minimal → welfare
  would not land back where the first welfare term was.
* **A misnamed government stops the run.** Falling back to another government
  would quietly run a different experiment.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from copy import deepcopy

from gaworld.economy import finance
from gaworld.economy.plugin import EconomyPlugin
from gaworld.kernel import build_kernel
from gaworld.public_sector import policy
from gaworld.public_sector.plugin import PublicSectorPlugin
from gaworld.settings.public_sector import public_sector_settings


def _governments():
    return deepcopy(public_sector_settings()["public_sector"]["governments"])


def _agent(agent_id, job, age=35, employment=None):
    agent = {
        "id": agent_id,
        "name": f"A{agent_id}",
        "age": age,
        "job": job,
        "personality": "务实",
        "values": "稳定",
        "daily_life": "规律",
        "state": {"emotion": 0.5, "stress": 0.5, "econ_security": 0.5, "risk_preference": 0.5},
    }
    if employment:
        agent["employment"] = employment
    return agent


class DeriveEconomyTests(unittest.TestCase):
    def setUp(self):
        self.base = deepcopy(finance.DEFAULT_ECONOMY_CONFIG)

    def test_neutral_policies_change_nothing(self):
        derived = policy.derive_economy(self.base, _governments()["baseline"]["policies"])
        self.assertEqual(self.base, derived)

    def test_the_rate_scale_scales_the_tax_owed_exactly(self):
        derived = policy.derive_economy(self.base, {"income_tax_rate_scale": 1.3})
        for gross in (8000, 20000, 60000, 150000):
            with self.subTest(gross=gross):
                before = finance.calc_income_tax(gross, 0, self.base)
                after = finance.calc_income_tax(gross, 0, derived)
                self.assertAlmostEqual(after, before * 1.3, delta=0.02)

    def test_the_threshold_moves(self):
        derived = policy.derive_economy(self.base, {"income_tax_exemption": 9000})
        self.assertEqual(9000, derived["tax"]["monthly_exemption"])
        # 9000 gross - 1500 special deduction is under the new threshold.
        self.assertEqual(0.0, finance.calc_income_tax(10000, 0, derived))
        self.assertGreater(finance.calc_income_tax(10000, 0, self.base), 0.0)

    def test_insurance_scale_leaves_the_housing_fund_alone(self):
        derived = policy.derive_economy(self.base, {"social_insurance_rate_scale": 0.5})
        si = derived["social_insurance"]
        self.assertAlmostEqual(0.04, si["pension_rate"])
        self.assertAlmostEqual(0.01, si["medical_rate"])
        self.assertEqual(self.base["social_insurance"]["housing_fund_rate"], si["housing_fund_rate"])

    def test_reimbursement_is_clamped_and_ordered(self):
        derived = policy.derive_economy(self.base, {"medical_reimbursement": [1.4, 0.3]})
        self.assertEqual([0.3, 1.0], derived["social_insurance"]["medical_reimbursement_range"])

    def test_minimum_wage(self):
        derived = policy.derive_economy(self.base, {"min_hourly_wage": 15})
        self.assertEqual(15.0, derived["min_hourly_income"])

    def test_the_base_is_never_mutated(self):
        snapshot = deepcopy(self.base)
        policy.derive_economy(self.base, _governments()["welfare"]["policies"])
        self.assertEqual(snapshot, self.base)


class BriefTests(unittest.TestCase):
    def test_a_neutral_government_states_no_policy(self):
        text = policy.brief(_governments()["baseline"])
        self.assertIn("现行体制", text)
        self.assertNotIn("现行政策", text)

    def test_every_departure_from_neutral_is_stated(self):
        text = policy.brief(_governments()["welfare"])
        for fragment in (
            "个税起征点 6000 元/月",
            "130%",
            "医保报销 70%–95%",
            "失业救济 80 元/天",
            "养老金 120 元/天",
        ):
            self.assertIn(fragment, text)
        self.assertNotIn("。。", text)


class ValidateConfigTests(unittest.TestCase):
    def _config(self, **section):
        return {
            "public_sector": {
                "enabled": True,
                "government": "welfare",
                "governments": _governments(),
                **section,
            }
        }

    def test_off_is_never_checked(self):
        policy.validate_config({"public_sector": {"enabled": False, "government": "nope"}})

    def test_a_known_government_passes(self):
        policy.validate_config(self._config(schedule=[{"day": 3, "government": "minimal"}]))

    def test_an_unknown_government_stops_the_run(self):
        with self.assertRaisesRegex(ValueError, "nope"):
            policy.validate_config(self._config(government="nope"))
        with self.assertRaisesRegex(ValueError, "ghost"):
            policy.validate_config(self._config(schedule=[{"day": 3, "government": "ghost"}]))

    def test_the_runtime_preflight_runs_it(self):
        from gaworld.plugins import validate_runtime_config

        with self.assertRaises(ValueError):
            validate_runtime_config(self._config(government="nope"))


class PluginRunTests(unittest.TestCase):
    """The plugin against the real economy, driven through the kernel bus."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _world(self, government="welfare", schedule=None, enabled=True):
        root = self.tmp.name
        config = {
            "stateful": False,
            "random_seed": 3,
            "memory_dir": os.path.join(root, "memory"),
            "log_dir": os.path.join(root, "logs"),
            "records": {"output_dir": os.path.join(root, "records")},
            "economy": {
                "enabled": True,
                "output_dir": os.path.join(root, "economy"),
                "shocks": {"enabled": False},
            },
            "public_sector": {
                "enabled": enabled,
                "government": government,
                "announce": True,
                "schedule": schedule or [],
                "governments": _governments(),
            },
        }
        self.base_economy = deepcopy(config["economy"])
        ctx = build_kernel(config, load_entry_points=False)
        EconomyPlugin().setup(ctx)
        PublicSectorPlugin().setup(ctx)
        agents = [
            _agent(1, "软件工程师"),
            _agent(2, "待业中", employment="unemployed"),
            _agent(3, "退休教师", age=68, employment="retired"),
        ]
        ctx.set_agents(agents)
        self.ext = {}
        ctx.bus.emit("on_simulation_start", config=ctx.config, agents=agents, extension_state=self.ext)
        return ctx, agents

    def _day(self, ctx, agents, day):
        ctx.clock.day = day
        common = {
            "config": ctx.config,
            "day": day,
            "agents": agents,
            "daily_logs": {a["id"]: "" for a in agents},
            "extension_state": self.ext,
        }
        ctx.bus.emit("on_day_start", **common)
        ctx.bus.emit("on_day_end", **common)

    def _records(self, table):
        path = os.path.join(self.tmp.name, "records", f"{table}.jsonl")
        with open(path, encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]

    def test_the_government_rewrites_the_live_economy(self):
        ctx, _ = self._world("welfare")
        self.assertEqual(6000.0, ctx.config["economy"]["tax"]["monthly_exemption"])
        self.assertEqual(12.0, ctx.config["economy"]["min_hourly_income"])
        self.assertEqual(
            [0.7, 0.95], ctx.config["economy"]["social_insurance"]["medical_reimbursement_range"]
        )

    def test_transfers_reach_the_right_people_and_conserve_money(self):
        ctx, agents = self._world("welfare")
        runtime = self.ext["economy_module"]
        initial = runtime["initial_system_total"]
        before = {a["id"]: a["economy"]["lifetime_income"] for a in agents}
        self._day(ctx, agents, 1)
        gained = {a["id"]: round(a["economy"]["lifetime_income"] - before[a["id"]], 2) for a in agents}
        # Only the 待业 resident gets unemployment benefit, only the retiree a pension.
        self.assertEqual(80.0, gained[2])
        self.assertEqual(120.0, gained[3])
        self.assertEqual(0.0, gained[1])
        self.assertAlmostEqual(initial, finance._system_total(agents, runtime["sectors"]), places=2)
        row = self._records("public_sector.daily")[-1]
        self.assertEqual(200.0, row["transfers_total"])
        self.assertEqual(
            {"unemployment_benefit_daily": 1, "pension_daily": 1, "basic_income_daily": 0}, row["recipients"]
        )

    def test_basic_income_goes_to_everyone(self):
        ctx, agents = self._world("basic_income")
        self._day(ctx, agents, 1)
        self.assertEqual(150.0, self._records("public_sector.daily")[-1]["transfers_total"])

    def test_a_scheduled_change_rederives_from_the_base(self):
        ctx, agents = self._world(
            "welfare", schedule=[{"day": 2, "government": "minimal"}, {"day": 3, "government": "welfare"}]
        )
        welfare_economy = deepcopy(ctx.config["economy"])
        self._day(ctx, agents, 1)
        self._day(ctx, agents, 2)
        self.assertEqual(5.0, ctx.config["economy"]["min_hourly_income"])
        self._day(ctx, agents, 3)
        self.assertEqual(welfare_economy, ctx.config["economy"])
        sources = [row["source"] for row in self._records("public_sector.change")]
        self.assertEqual(["config", "schedule", "schedule"], sources)

    def test_the_dashboard_switch_is_a_registered_intervention(self):
        ctx, _agents = self._world("welfare")
        ctx.clock.day = 4
        result = ctx.controller.intervene(
            "public_sector.set_government", ctx, government="austerity", note="选举"
        )
        self.assertEqual("austerity", result["government"])
        self.assertEqual(4000.0, ctx.config["economy"]["tax"]["monthly_exemption"])
        with self.assertRaises(ValueError):
            ctx.controller.intervene("public_sector.set_government", ctx, government="nope")

    def test_residents_are_briefed_once_a_day_and_told_of_a_change(self):
        ctx, agents = self._world("welfare")
        self._day(ctx, agents, 1)
        retiree = agents[2]
        first = ctx.bus.collect("perception.compose", agent=retiree, day=2, time_str="08:00")
        self.assertEqual(1, len(first))
        self.assertIn("福利型政府", first[0])
        self.assertIn("养老金 120 元", first[0])  # what they were paid
        self.assertEqual([], ctx.bus.collect("perception.compose", agent=retiree, day=2, time_str="09:00"))
        ctx.controller.intervene("public_sector.set_government", ctx, government="minimal", note="")
        told = ctx.bus.collect("perception.compose", agent=retiree, day=2, time_str="10:00")
        self.assertIn("本市政府更迭：小政府上任", told[0])

    def test_the_base_economy_is_restored_at_the_end(self):
        ctx, agents = self._world("welfare")
        ctx.bus.emit("on_simulation_end", config=ctx.config, agents=agents, extension_state=self.ext)
        self.assertEqual(self.base_economy, ctx.config["economy"])

    def test_off_means_inert(self):
        ctx, agents = self._world("welfare", enabled=False)
        self.assertEqual(self.base_economy, ctx.config["economy"])
        self.assertNotIn("public_sector.set_government", ctx.controller.intervention_names())
        self.assertEqual([], ctx.bus.collect("perception.compose", agent=agents[0], day=1, time_str="08:00"))


if __name__ == "__main__":
    unittest.main()
