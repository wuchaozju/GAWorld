import unittest
from unittest.mock import patch

from gaworld.cognition.realism import build_daily_intentions


class TestIntentionBudgetCap(unittest.TestCase):
    def test_budget_zero_skips_llm(self):
        agent = {
            "id": 1,
            "name": "A",
            "state": {"stress": 0.3},
            "growth_profile": {
                "items": [
                    {"name": "阅读", "kind": "hobby", "priority": 0.8},
                    {"name": "沟通表达", "kind": "skill", "priority": 0.7},
                ]
            },
        }
        budget = {"remaining": 0}
        with patch("gaworld.cognition.realism.call_llm") as mocked:
            result = build_daily_intentions(agent, [], {}, budget)
        mocked.assert_not_called()
        self.assertIn("priorities", result)
        self.assertEqual(["阅读", "沟通表达"], result["growth_focus"])
        self.assertEqual(0, budget["remaining"])

    def test_budget_consumed_once(self):
        agent = {"id": 1, "name": "A", "state": {"stress": 0.3}}
        budget = {"remaining": 1}
        payload = (
            '{"priorities":["保持节奏","推进任务"],'
            '"avoidances":["冲动决策"],'
            '"target_social":"保持适度社交",'
            '"target_recovery":"保证休息"}'
        )
        with patch("gaworld.cognition.realism.call_llm", return_value=payload) as mocked:
            result = build_daily_intentions(agent, [], {}, budget)
        mocked.assert_called_once()
        self.assertEqual(0, budget["remaining"])
        self.assertIn("保持节奏", result["priorities"])


if __name__ == "__main__":
    unittest.main()
