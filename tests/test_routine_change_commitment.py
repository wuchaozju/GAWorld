import unittest
from unittest.mock import patch

import generative_city_sim as sim


class TestRoutineChangeCommitment(unittest.TestCase):
    """Trigger strength versus an activity's commitment resistance.

    Every test here pins ``ROUTINE_CHANGE_RANDOMNESS`` to 0. The knob defaults
    to 0.85, and at that setting it scales resistance down to ~0.40x and adds
    ~0.38 of free-floating restlessness to the trigger — enough to carry *any*
    trigger past *any* commitment level. The "resists" case would then survive
    only on the `random.random()` draw further down, i.e. on whatever state the
    global RNG happens to be in when this file runs, which is why it flips
    depending on what ran before it. Pinned to 0, both cases are decided by
    `trigger <= resistance`, which is the thing being asserted.

    The knob's own behaviour is covered by test_routine_change_randomness.
    """

    def setUp(self):
        patcher = patch.object(sim, "ROUTINE_CHANGE_RANDOMNESS", 0.0)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_high_commitment_activity_resists_weak_trigger(self):
        agent = {
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
        with patch.object(sim, "call_llm") as mock_call:
            activity, reason, changed = sim.maybe_adjust_activity(
                agent,
                "10:00",
                "上午工作",
                "环境平稳",
                "目标：推进项目；顾虑：时间有限；冲动：想省点力；打算：先完成关键任务；预期：按时推进",
                "无",
                [],
                None,
            )
        self.assertEqual("上午工作", activity)
        self.assertFalse(changed)
        self.assertEqual("", reason)
        mock_call.assert_not_called()

    def test_low_commitment_activity_changes_when_trigger_beats_resistance(self):
        agent = {
            "id": 42,
            "name": "容易起意的人",
            "job": "自由职业者",
            "personality": "",
            "daily_life": "",
            "values": "",
            "state": {
                "emotion": 0.3,
                "stress": 0.82,
                "econ_security": 0.5,
                "risk_preference": 0.5,
                "energy": 0.25,
                "hunger": 0.85,
                "fatigue_debt": 0.8,
                "self_control": 0.2,
                "time_pressure": 0.9,
            },
        }
        response = '{"change": true, "activity": "吃点东西", "reason": "又饿又累，想先恢复一下"}'
        with patch.object(sim.random, "random", return_value=0.0), patch.object(
            sim, "call_llm", return_value=response
        ) as mock_call:
            activity, reason, changed = sim.maybe_adjust_activity(
                agent,
                "20:00",
                "个人时间",
                "人有点烦，注意力也散",
                "目标：把晚上过稳；顾虑：状态很差；冲动：想直接躺平；打算：先做最省力的安排；预期：别让状态继续下滑",
                "社区里有点嘈杂",
                [{"name": "晚高峰拥堵"}],
                None,
            )
        self.assertTrue(changed)
        self.assertEqual("吃点东西", activity)
        self.assertIn("恢复", reason)
        mock_call.assert_called_once()


if __name__ == "__main__":
    unittest.main()
