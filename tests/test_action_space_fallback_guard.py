import unittest
from unittest.mock import patch

from gaworld.cognition.realism import update_habits_from_episode
from gaworld.sim import _action
from gaworld.sim._memory_recall import (
    _behavioral_action_fallbacks,
    is_fallback_only_action_list,
)


class TestFallbackOnlyDetection(unittest.TestCase):
    def test_generic_filler_is_detected(self):
        # What an LLM failure leaves behind for an interrupt activity.
        self.assertTrue(is_fallback_only_action_list("找地方避雨", [
            "先把眼前这件事往前推进一点",
            "按原节奏继续当前安排",
            "先拖一会儿再说，顺手刷会儿手机",
            "联系一下相关的人确认接下来的安排",
        ]))

    def test_real_actions_are_not_detected(self):
        self.assertFalse(is_fallback_only_action_list("找地方避雨", [
            "钻进街角那家常去的便利店等雨停",
            "先把眼前这件事往前推进一点",
        ]))

    def test_empty_counts_as_fallback_only(self):
        self.assertTrue(is_fallback_only_action_list("通勤", []))


class TestFallbackWording(unittest.TestCase):
    def test_weather_activity_gets_weather_specific_fallbacks(self):
        fallbacks = _behavioral_action_fallbacks("找地方避雨")
        self.assertNotIn("先把眼前这件事往前推进一点", fallbacks.values())
        self.assertIn("雨", "".join(fallbacks.values()))

    def test_unknown_activity_still_gets_generic_fallbacks(self):
        fallbacks = _behavioral_action_fallbacks("参加社区抽奖")
        self.assertEqual("先把眼前这件事往前推进一点", fallbacks["progress"])


class TestFallbackOnlyIsNotCached(unittest.TestCase):
    def test_save_action_space_drops_fallback_only_entries(self):
        action_space = {
            "找地方避雨": list(_behavioral_action_fallbacks("找地方避雨").values()),
            "上午工作": ["整理今天的需求清单", "和同事对一遍排期"],
        }
        with patch.object(_action, "save_agent_actions") as saved:
            _action.save_action_space(7, action_space)
        saved.assert_called_once()
        persisted = saved.call_args[0][1]
        self.assertEqual(["上午工作"], list(persisted.keys()))


class TestHabitMinOccurrences(unittest.TestCase):
    def _episode(self, action):
        return {
            "day": 1,
            "time": "09:00",
            "location": "街边",
            "final_activity": "找地方避雨",
            "action": action,
        }

    def test_one_off_context_does_not_become_a_habit(self):
        agent = {"habits": {}}
        cfg = {"behavior": {"habit_learning_rate": 0.08, "habit_min_occurrences": 3}}
        update_habits_from_episode(agent, self._episode("钻进便利店等雨停"), cfg)
        item = next(iter(agent["habits"].values()))
        self.assertEqual(0.0, item["strength"])

    def test_repeated_context_still_builds_strength(self):
        agent = {"habits": {}}
        cfg = {"behavior": {"habit_learning_rate": 0.08, "habit_min_occurrences": 3}}
        for _ in range(6):
            update_habits_from_episode(agent, self._episode("钻进便利店等雨停"), cfg)
        item = next(iter(agent["habits"].values()))
        self.assertGreater(item["strength"], 0.0)
        self.assertEqual("钻进便利店等雨停", item["preferred_action"])


if __name__ == "__main__":
    unittest.main()
