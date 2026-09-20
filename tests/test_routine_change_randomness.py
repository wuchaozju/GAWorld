"""Routine-randomness knob: higher ``routine_change.randomness`` makes agents
deviate from their scheduled routine more, while 0 preserves the tuned
resist-when-committed behavior.

The knob relaxes an activity's commitment resistance, injects free-floating
restlessness into the trigger, and lifts the deviation probability. Sleep
slots are exempt so high randomness doesn't keep agents up all night.
"""

import unittest
from unittest.mock import patch

import generative_city_sim as sim


def _committed_agent():
    """A calm agent on a high-commitment task that resists a weak trigger."""
    return {
        "id": 41,
        "name": "稳住的人",
        "job": "项目经理",
        "personality": "",
        "daily_life": "",
        "values": "",
        "state": {
            "emotion": 0.55,
            "stress": 0.52,
            "econ_security": 0.5,
            "risk_preference": 0.5,
            "energy": 0.6,
            "hunger": 0.35,
            "fatigue_debt": 0.35,
            "self_control": 0.75,
            "time_pressure": 0.3,
        },
    }


class TestRoutineChangeRandomness(unittest.TestCase):
    def test_zero_randomness_keeps_committed_agent_on_routine(self):
        with patch.object(sim, "ROUTINE_CHANGE_RANDOMNESS", 0.0), patch.object(
            sim, "call_llm"
        ) as mock_call:
            activity, reason, changed = sim.maybe_adjust_activity(
                _committed_agent(), "10:00", "上午工作", "环境平稳", "无", "无", [], None
            )
        self.assertFalse(changed)
        self.assertEqual("上午工作", activity)
        self.assertEqual("", reason)
        mock_call.assert_not_called()

    def test_high_randomness_pushes_committed_agent_off_routine(self):
        response = '{"change": true, "activity": "临时出去走走", "reason": "有点坐不住"}'
        # random()==0.0 makes the final activation roll always deviate; the LLM
        # then authors the new activity. With randomness off (previous test) the
        # same agent never reaches the LLM at all.
        with patch.object(sim, "ROUTINE_CHANGE_RANDOMNESS", 1.0), patch.object(
            sim.random, "random", return_value=0.0
        ), patch.object(sim, "call_llm", return_value=response) as mock_call:
            activity, reason, changed = sim.maybe_adjust_activity(
                _committed_agent(), "10:00", "上午工作", "环境平稳", "无", "无", [], None
            )
        self.assertTrue(changed)
        self.assertEqual("临时出去走走", activity)
        mock_call.assert_called_once()

    def test_sleep_is_exempt_from_randomness(self):
        # Even at max randomness, a sleep slot should not be dragged off-script:
        # the randomness boost is skipped, so a calm agent's weak trigger loses
        # to the sleep slot's resistance and the LLM is never consulted.
        with patch.object(sim, "ROUTINE_CHANGE_RANDOMNESS", 1.0), patch.object(
            sim.random, "random", return_value=0.0
        ), patch.object(sim, "call_llm") as mock_call:
            activity, reason, changed = sim.maybe_adjust_activity(
                _committed_agent(), "23:30", "睡前", "环境平稳", "无", "无", [], None
            )
        self.assertFalse(changed)
        self.assertEqual("睡前", activity)
        mock_call.assert_not_called()


if __name__ == "__main__":
    unittest.main()
