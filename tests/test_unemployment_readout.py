"""Unemployment is counted from the agents, not drifted on its own RNG.

``macro.unemployment_rate`` was seeded from config and then multiplied by
``_rng.uniform`` at every phase transition, so the model could report 5.2%
unemployment with every agent holding a job. Nothing read the figure —
``config_docs`` says so outright ("a business-cycle indicator; layoff_risk is
what actually costs jobs") — so this changes no behaviour, only whether the
number shown is true.
"""

from __future__ import annotations

import unittest

from gaworld.economy import finance


def _agent(employment=None, job="工程师"):
    agent = {"id": 1, "job": job}
    if employment is not None:
        agent["employment"] = employment
    return agent


class TestLabourForceSnapshot(unittest.TestCase):
    def test_the_ilo_denominator_excludes_people_outside_the_labour_force(self):
        """Retirees and students are not unemployed; counting them either as
        jobless or as employed both misstate the rate."""
        snap = finance.labour_force_snapshot([
            _agent("employed"), _agent("employed"), _agent("employed"),
            _agent("unemployed"),
            _agent("retired"), _agent("not_in_labor_force"), _agent("student"),
        ])
        self.assertEqual(snap["employed"], 3)
        self.assertEqual(snap["unemployed"], 1)
        self.assertEqual(snap["not_in_labor_force"], 3)
        self.assertEqual(snap["labour_force"], 4)
        self.assertEqual(snap["unemployment_rate"], 0.25)

    def test_both_vocabularies_land_outside_the_labour_force(self):
        """The economy writes "retired"; the population synthesiser writes
        "not_in_labor_force". They must not be counted differently."""
        economy = finance.labour_force_snapshot([_agent("employed"), _agent("retired")])
        synth = finance.labour_force_snapshot([_agent("employed"), _agent("not_in_labor_force")])
        self.assertEqual(economy, synth)

    def test_an_agent_with_no_field_falls_back_to_its_job_text(self):
        self.assertEqual(
            finance.labour_force_snapshot([_agent(job=finance.UNEMPLOYED_JOB_TEXT)])["unemployed"], 1)
        self.assertEqual(
            finance.labour_force_snapshot([_agent(job=finance.RETIRED_JOB_TEXT)])["not_in_labor_force"], 1)
        self.assertEqual(finance.labour_force_snapshot([_agent()])["employed"], 1)

    def test_an_empty_town_does_not_divide_by_zero(self):
        self.assertEqual(finance.labour_force_snapshot([])["unemployment_rate"], 0.0)
        self.assertEqual(finance.labour_force_snapshot(None)["unemployment_rate"], 0.0)

    def test_a_town_with_only_retirees_has_no_unemployment(self):
        snap = finance.labour_force_snapshot([_agent("retired"), _agent("retired")])
        self.assertEqual(snap["labour_force"], 0)
        self.assertEqual(snap["unemployment_rate"], 0.0)


class TestMacroReadsTheTown(unittest.TestCase):
    def _run_day(self, agents, **macro_overrides):
        cfg = dict(finance.DEFAULT_ECONOMY_CONFIG)
        cfg["macro"] = {**cfg["macro"], **macro_overrides}
        macro = finance._init_macro_state(cfg)
        macro["unemployment_rate"] = 0.052
        context = {
            "config": {"economy": cfg},
            "agents": agents,
            "day": 1,
            # The runtime lives under "economy_module", not "economy" — the
            # same flat name whose stale hook registration once silently
            # disabled the whole subsystem.
            "extension_state": {"economy_module": {"enabled": True, "macro": macro,
                                                   "sectors": {}, "sim_day_counter": 0}},
        }
        return cfg, macro, context

    def test_the_reported_rate_matches_the_town(self):
        agents = [_agent("employed")] * 9 + [_agent("unemployed")]
        cfg, macro, context = self._run_day(agents)
        finance.on_day_start(context)
        self.assertAlmostEqual(macro["unemployment_rate"], 0.1, places=4)
        self.assertEqual(macro["labour_force"]["employed"], 9)

    def test_full_employment_is_reported_as_zero_not_as_the_config_seed(self):
        """The headline symptom: 5.2% on the dashboard, nobody out of work."""
        cfg, macro, context = self._run_day([_agent("employed")] * 20)
        finance.on_day_start(context)
        self.assertEqual(macro["unemployment_rate"], 0.0)

    def test_the_switch_restores_the_drifting_figure(self):
        cfg, macro, context = self._run_day([_agent("employed")] * 20,
                                            unemployment_from_agents=False)
        finance.on_day_start(context)
        self.assertEqual(macro["unemployment_rate"], 0.052)


if __name__ == "__main__":
    unittest.main()
