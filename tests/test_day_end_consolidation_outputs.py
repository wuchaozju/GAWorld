import os
import tempfile
import unittest
from unittest.mock import patch

from gaworld.cognition.realism import consolidate_day
import generative_city_sim as sim


class TestDayEndConsolidation(unittest.TestCase):
    def test_consolidation_fallback_output(self):
        agent = {"id": 5, "name": "Agent5", "state": {"stress": 0.5}}
        episodes = [
            {
                "episode_id": "e1",
                "time": "10:00",
                "final_activity": "上午工作",
                "action": "整理任务",
                "salience": 0.7,
                "reflection": "今天推进顺利",
                "tags": ["work", "success"],
            }
        ]
        result = consolidate_day(agent, 3, episodes, {}, {"remaining": 0})
        self.assertIn("memory_text", result)
        self.assertIn("intentions", result)
        self.assertTrue(result["memory_text"].startswith("[Day 3 Consolidation]"))

    def test_consolidation_uses_budget_once(self):
        agent = {"id": 5, "name": "Agent5", "state": {"stress": 0.5}}
        episodes = [
            {
                "episode_id": "e1",
                "time": "10:00",
                "final_activity": "上午工作",
                "action": "整理任务",
                "salience": 0.7,
                "reflection": "今天推进顺利",
                "tags": ["work", "success"],
            }
        ]
        budget = {"remaining": 1}
        llm_json = (
            '{"summary":"今天关键进展稳定。",'
            '"priorities":["推进重点任务"],'
            '"avoidances":["情绪化决策"],'
            '"target_social":"与同事保持协作",'
            '"target_recovery":"按时休息"}'
        )
        with patch("gaworld.cognition.realism.call_llm", return_value=llm_json):
            result = consolidate_day(agent, 3, episodes, {}, budget)
        self.assertEqual(0, budget["remaining"])
        self.assertIn("今天关键进展稳定", result["summary"])

    def test_daily_diary_fallback_contains_required_sections(self):
        agent = {
            "id": 8,
            "name": "Agent8",
            "intentions": {
                "priorities": ["推进重点任务"],
                "avoidances": ["拖延"],
                "target_social": "和同事保持沟通",
                "target_recovery": "早点休息",
            },
            "episodes": [
                {
                    "day": 2,
                    "time": "10:00",
                    "final_activity": "上午工作",
                    "action": "推进方案",
                    "reflection": "感觉进展还可以",
                    "salience": 0.8,
                }
            ],
        }
        text = sim.generate_daily_diary(
            agent,
            2,
            logs="今天推进了一些工作，也有点累。",
            day_context={"sim_date": "2026-04-05", "weekday_zh": "周日", "day_type_zh": "周末"},
            day_memory="今天最大的感受是别再拖。",
            consolidation_text="今天意识到状态不好时更要先抓重点。",
            intentions=agent["intentions"],
        )
        self.assertIn("## 今天主要发生的事情", text)
        self.assertIn("## 今天的感想", text)
        self.assertIn("## 明天的计划", text)

    def test_save_daily_diary_writes_markdown_file(self):
        agent = {"id": 9}
        diary_text = "# 日记\n\n## 今天主要发生的事情\n测试\n\n## 今天的感想\n测试\n\n## 明天的计划\n测试\n"
        with tempfile.TemporaryDirectory() as tmpdir:
            path = sim.save_daily_diary(agent, 4, diary_text, output_dir=tmpdir)
            self.assertTrue(os.path.exists(path))
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
        self.assertIn("## 明天的计划", content)
        self.assertTrue(path.endswith("day_004.md"))


if __name__ == "__main__":
    unittest.main()
