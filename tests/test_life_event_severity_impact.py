"""Part A — a life event's *severity* now drives how hard it disrupts the day.

Before this change, env/life events were counted (flat +0.10 trigger, +boost
prob) regardless of severity, so a 0.86 "被人陷害" moved the schedule no more
than a trivial event. These tests pin the new severity-weighted behaviour:

1. ``_routine_change_trigger_strength`` scales with event severity;
2. a plain event (fallback severity 0.5) reproduces the old ~0.10 magnitude;
3. a severe event beats a *medium*-commitment activity's resistance (so the
   routine-change LLM is consulted) while a mild event does not;
4. state effects are amplified by severity in the LifeEventsPlugin.
"""

import unittest
from unittest.mock import patch

import generative_city_sim as sim
from gaworld.events.plugin import LifeEventsPlugin


def _calm_agent():
    # State chosen so the *internal* trigger is ~0: any routine change here
    # must come from the event, not from stress/fatigue/hunger.
    return {
        "id": 91,
        "name": "状态平稳的人",
        "job": "自由职业者",
        "personality": "",
        "daily_life": "",
        "values": "",
        "state": {
            "emotion": 0.6,
            "stress": 0.4,
            "econ_security": 0.5,
            "risk_preference": 0.5,
            "energy": 0.7,
            "hunger": 0.3,
            "fatigue_debt": 0.2,
            "self_control": 0.6,
            "time_pressure": 0.25,
        },
    }


class TestSeverityWeightedTrigger(unittest.TestCase):
    def test_trigger_scales_with_severity(self):
        agent = _calm_agent()
        mild = sim._routine_change_trigger_strength(agent, [{"severity": 0.45}], None)
        severe = sim._routine_change_trigger_strength(agent, [{"severity": 0.86}], None)
        self.assertGreater(severe, mild + 0.25)

    def test_plain_event_matches_legacy_magnitude(self):
        # A plain event with no severity falls back to 0.5 and reproduces the
        # old flat +0.10 trigger contribution (calm agent → trigger ≈ 0.10).
        agent = _calm_agent()
        trigger = sim._routine_change_trigger_strength(agent, [{"name": "普通事件"}], None)
        self.assertAlmostEqual(trigger, 0.10, places=2)

    def test_severe_event_beats_medium_commitment(self):
        # "购物" is a medium-commitment activity: a mild event leaves it intact
        # (LLM never consulted), a severe event forces the routine-change query.
        #
        # ROUTINE_CHANGE_RANDOMNESS has to be pinned for that to be what is
        # actually under test. At its shipped default (0.85) the knob scales
        # resistance down to ~0.40x and adds ~0.38 of free-floating restlessness
        # to the trigger, which carries *any* event past *any* commitment level:
        # the mild case then reaches the `random.random()` gate further down and
        # this assertion holds or fails on that draw, i.e. on whatever the global
        # RNG happens to be after every test that ran before it. Pinned to 0,
        # the mild case is stopped by `trigger <= resistance` — which is the
        # severity-versus-commitment claim this test exists to make.
        # The randomness path itself is covered by test_routine_change_randomness.
        agent = _calm_agent()
        with patch.object(sim, "ROUTINE_CHANGE_RANDOMNESS", 0.0), patch.object(
            sim, "call_llm"
        ) as mock_call:
            _, _, changed_mild = sim.maybe_adjust_activity(
                agent, "15:00", "购物", "环境平稳", "目标：随便逛逛",
                "无", [{"severity": 0.30, "name": "轻微小事"}], None,
            )
        self.assertFalse(changed_mild)
        mock_call.assert_not_called()

        response = '{"change": true, "activity": "回家处理", "reason": "家里出急事"}'
        with patch.object(sim, "ROUTINE_CHANGE_RANDOMNESS", 0.0), patch.object(
            sim.random, "random", return_value=0.0
        ), patch.object(sim, "call_llm", return_value=response) as mock_call:
            activity, _, changed_severe = sim.maybe_adjust_activity(
                agent, "15:00", "购物", "环境平稳", "目标：随便逛逛", "无",
                [{"severity": 0.86, "name": "家中急事", "description": "家人突然需要帮助"}],
                None,
            )
        self.assertTrue(changed_severe)
        self.assertEqual("回家处理", activity)
        mock_call.assert_called()


class TestSeverityScaledStateEffects(unittest.TestCase):
    def _apply(self, severity, base=0.5, delta=0.1):
        plugin = LifeEventsPlugin()
        plugin._severity_state_amplify = 0.8
        agent = {"id": 1, "state": {"stress": base}}
        event = {"state_effects": {"stress": delta}}
        if severity is not None:
            event["severity"] = severity
        plugin._apply_state_effects({"agent": agent, "step": {"life_events": [event]}})
        return agent["state"]["stress"]

    def test_high_severity_amplifies_delta(self):
        # factor = 1 + 0.8*(0.86-0.5) = 1.288 → 0.5 + 0.1*1.288 = 0.6288
        self.assertAlmostEqual(self._apply(0.86), 0.6288, places=3)

    def test_missing_severity_leaves_delta_unchanged(self):
        self.assertAlmostEqual(self._apply(None), 0.60, places=3)

    def test_low_severity_dampens_delta(self):
        # factor = 1 + 0.8*(0.3-0.5) = 0.84 → 0.5 + 0.1*0.84 = 0.584
        self.assertAlmostEqual(self._apply(0.30), 0.584, places=3)


if __name__ == "__main__":
    unittest.main()
