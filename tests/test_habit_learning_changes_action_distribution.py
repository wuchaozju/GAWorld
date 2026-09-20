import unittest

from gaworld.cognition.realism import update_habits_from_episode


class TestHabitLearning(unittest.TestCase):
    def test_repeated_action_becomes_preferred(self):
        agent = {"habits": {}}
        cfg = {"behavior": {"habit_learning_rate": 0.08}}
        for _ in range(12):
            update_habits_from_episode(
                agent,
                {
                    "day": 1,
                    "time": "09:00",
                    "location": "Admin Office",
                    "final_activity": "上午工作",
                    "action": "整理任务清单",
                },
                cfg,
            )
        update_habits_from_episode(
            agent,
            {
                "day": 1,
                "time": "09:00",
                "location": "Admin Office",
                "final_activity": "上午工作",
                "action": "临时刷手机",
            },
            cfg,
        )
        item = next(iter(agent["habits"].values()))
        self.assertEqual("整理任务清单", item["preferred_action"])
        self.assertGreater(item["strength"], 0.35)


if __name__ == "__main__":
    unittest.main()
