import unittest
from unittest.mock import patch

import generative_city_sim as sim


class TestInterestDailyRoutinePrompt(unittest.TestCase):
    def test_daily_routine_prompt_includes_growth_context_and_falls_back(self):
        agent = {
            "id": 9,
            "name": "测试者",
            "age": 29,
            "job": "运营专员",
            "personality": "稳定",
            "daily_life": "晚上常看书",
            "values": "希望持续成长",
            "growth_profile": {
                "items": [
                    {
                        "name": "阅读",
                        "kind": "hobby",
                        "category": "阅读",
                        "priority": 0.8,
                        "level": 0.3,
                        "weekly_target_minutes": 120,
                        "preferred_time_blocks": ["evening"],
                        "activity_templates": ["阅读"],
                    }
                ]
            },
        }
        base = [("08:00", "吃早饭"), ("09:00", "工作"), ("21:00", "个人时间"), ("23:00", "睡前")]
        prompts = []

        def fake_llm(prompt, task=None, agent_id=None):
            prompts.append(prompt)
            return "not json"

        with patch.object(sim, "call_llm", side_effect=fake_llm), patch.object(
            sim, "retrieve_relevant_memories", return_value=[]
        ), patch.object(sim, "_external_rag_hint", return_value="无"):
            result = sim.generate_daily_routine(
                agent,
                base,
                day=1,
                day_context={"day_type": "weekday", "weekday_zh": "周一", "day_type_zh": "工作日"},
            )

        self.assertTrue(prompts)
        self.assertIn("兴趣与技能成长画像", prompts[0])
        self.assertIn("阅读", prompts[0])
        self.assertTrue(result)
        self.assertTrue(any("睡" in activity for _, activity in result))


if __name__ == "__main__":
    unittest.main()
