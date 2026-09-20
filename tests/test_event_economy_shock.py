"""Regression test for the event -> economy layoff-shock bridge (B1).

Before this fix, an injected '裁员/layoff' policy event only changed agent
perception text; it never triggered the economy module's income shock, so
econ_security/stress did not respond to the intervention. These tests assert
that a layoff event today actually cuts affected agents' income.
"""

import os
import random
import tempfile
import unittest

from gaworld.economy import finance as eco


def _agent(agent_id=1):
    return {
        "id": agent_id, "name": f"A{agent_id}", "age": 30, "job": "软件工程师",
        "personality": "上进务实", "values": "稳定", "daily_life": "规律",
        "state": {"emotion": 0.5, "stress": 0.5, "econ_security": 0.5,
                  "risk_preference": 0.5},
    }


def _config(tmpdir, policy_events=None, **econ_over):
    economy = {"enabled": True, "output_dir": os.path.join(tmpdir, "economy"),
               "hours_per_step": 1.0}
    economy.update(econ_over)
    return {
        "stateful": True,
        "memory_dir": os.path.join(tmpdir, "memory"),
        "log_dir": os.path.join(tmpdir, "logs"),
        "policy_events": policy_events or [],
        "economy": economy,
    }


class TestActiveEventLayoff(unittest.TestCase):
    def test_detects_layoff_event_today(self):
        ctx = {"day": 2, "config": {"policy_events": [
            {"day": 2, "time": "09:00", "name": "大规模裁员冲击",
             "description": "部分企业裁员导致收入骤降"}]}}
        self.assertTrue(eco._active_event_layoff(ctx))

    def test_ignores_event_on_other_day(self):
        ctx = {"day": 1, "config": {"policy_events": [
            {"day": 2, "name": "大规模裁员冲击", "description": "裁员"}]}}
        self.assertFalse(eco._active_event_layoff(ctx))

    def test_ignores_non_layoff_event(self):
        ctx = {"day": 2, "config": {"policy_events": [
            {"day": 2, "name": "临时交通限行", "description": "主干道限行"}]}}
        self.assertFalse(eco._active_event_layoff(ctx))


class TestEventDrivenLayoffShock(unittest.TestCase):
    def test_event_layoff_cuts_income(self):
        cfg = eco.deepcopy(eco.DEFAULT_ECONOMY_CONFIG)
        cfg["shocks"]["event_layoff_prob"] = 1.0  # force, for a deterministic check
        econ = {"base_hourly_income": 20.0}
        random.seed(0)
        events = eco._check_daily_shocks(_agent(), econ, cfg, macro_state={},
                                         event_layoff=True)
        layoffs = [e for e in events if e["type"] == "layoff"]
        self.assertEqual(len(layoffs), 1)
        self.assertEqual(layoffs[0]["trigger"], "event")
        self.assertLess(econ["base_hourly_income"], 20.0)            # income cut
        self.assertGreater(econ.get("_layoff_days_remaining", 0), 0)

    def test_no_event_means_no_layoff(self):
        cfg = eco.deepcopy(eco.DEFAULT_ECONOMY_CONFIG)
        cfg["shocks"].update({"layoff_base_prob": 0.0, "raise_base_prob": 0.0,
                              "medical_emergency_prob": 0.0})
        econ = {"base_hourly_income": 20.0}
        random.seed(0)
        events = eco._check_daily_shocks(_agent(), econ, cfg, macro_state={},
                                         event_layoff=False)
        self.assertFalse(any(e["type"] == "layoff" for e in events))
        self.assertEqual(econ["base_hourly_income"], 20.0)          # untouched


class TestEventLayoffThroughHooks(unittest.TestCase):
    """End-to-end through on_simulation_start + on_day_start."""

    def test_layoff_event_cuts_income_via_day_start(self):
        random.seed(123)
        with tempfile.TemporaryDirectory() as tmp:
            ev = [{"day": 2, "time": "09:00", "name": "大规模裁员冲击",
                   "description": "部分企业裁员导致收入骤降"}]
            cfg = _config(
                tmp, policy_events=ev,
                macro={"enabled": False},
                shocks={"event_layoff_prob": 1.0, "layoff_base_prob": 0.0,
                        "raise_base_prob": 0.0, "medical_emergency_prob": 0.0},
            )
            ctx = {"config": cfg, "agents": [_agent(1)],
                   "extension_state": {}, "daily_logs": {}}
            eco.on_simulation_start(ctx)
            base_income = ctx["agents"][0]["economy"]["base_hourly_income"]
            for day in (1, 2, 3):
                ctx["day"] = day
                eco.on_day_start(ctx)
            econ = ctx["agents"][0]["economy"]
            self.assertLess(econ["base_hourly_income"], base_income)  # event cut income
            log = econ.get("shock_log", [])
            self.assertTrue(
                any(s["type"] == "layoff" and s.get("trigger") == "event" for s in log),
                msg=f"expected an event-driven layoff in shock_log, got {log}")


if __name__ == "__main__":
    unittest.main()
