import tempfile
import unittest

from gaworld.memory.experience import append_agent_episode, load_agent_episodes


class TestEpisodePersistenceAcrossDays(unittest.TestCase):
    def test_episodes_append_and_reload(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = {"memory_dir": tmpdir}
            append_agent_episode(
                7,
                {
                    "episode_id": "e1",
                    "day": 1,
                    "time": "09:00",
                    "final_activity": "上午工作",
                    "action": "整理任务",
                    "salience": 0.4,
                    "created_at_day": 1,
                },
                cfg=cfg,
            )
            append_agent_episode(
                7,
                {
                    "episode_id": "e2",
                    "day": 2,
                    "time": "10:00",
                    "final_activity": "上午工作",
                    "action": "推进项目",
                    "decision_driver": "现实承诺约束",
                    "need_snapshot": {
                        "energy": 0.62,
                        "hunger": 0.31,
                        "social_need": 0.42,
                        "fatigue_debt": 0.28,
                        "self_control": 0.66,
                        "time_pressure": 0.24,
                    },
                    "change_reason": "",
                    "commitment_level": "high",
                    "expected_outcome": "希望把项目按时推进",
                    "salience": 0.6,
                    "created_at_day": 2,
                },
                cfg=cfg,
            )
            episodes = load_agent_episodes(7, cfg=cfg)
            self.assertEqual(2, len(episodes))
            self.assertEqual("e1", episodes[0]["episode_id"])
            self.assertEqual("e2", episodes[1]["episode_id"])
            self.assertEqual("现实承诺约束", episodes[1]["decision_driver"])
            self.assertEqual("high", episodes[1]["commitment_level"])
            self.assertIn("fatigue_debt", episodes[1]["need_snapshot"])
            self.assertEqual("", episodes[0].get("change_reason", ""))


if __name__ == "__main__":
    unittest.main()
