"""Goals context must reach the intention/consolidation prompts."""

import json
import unittest
from unittest.mock import patch

from gaworld.cognition import realism


def _agent():
    return {
        "id": 5, "name": "测试者", "job": "教师", "personality": "耐心",
        "state": {"stress": 0.3}, "growth_profile": {}, "episodes": [],
    }


def _episode():
    return {"day": 1, "final_activity": "备课", "action": "整理教案",
            "salience": 0.7, "tags": [], "reflection": "还算顺利"}


class TestIntentionPromptInjection(unittest.TestCase):
    def test_goals_context_in_prompt(self):
        prompts = []

        def fake_llm(prompt, task=None, agent_id=None):
            prompts.append(prompt)
            return json.dumps({"priorities": ["推进课题"], "avoidances": ["拖延"],
                               "target_social": "", "target_recovery": "",
                               "growth_focus": []}, ensure_ascii=False)

        with patch.object(realism, "call_llm", fake_llm):
            realism.build_daily_intentions(
                _agent(), [_episode()], {}, {"remaining": 2},
                goals_context="- 短期[stg1]：完成课题申报（进度 20%）",
            )
        self.assertIn("当前人生与阶段目标", prompts[0])
        self.assertIn("完成课题申报", prompts[0])

    def test_default_goals_context_keeps_signature_optional(self):
        result = realism.build_daily_intentions(_agent(), [], {}, {"remaining": 0})
        self.assertIn("priorities", result)


class TestConsolidationGoalProgress(unittest.TestCase):
    def test_prompt_contains_goals_and_result_carries_goal_progress(self):
        prompts = []

        def fake_llm(prompt, task=None, agent_id=None):
            prompts.append(prompt)
            return json.dumps({
                "summary": "有推进", "priorities": ["继续"], "avoidances": [],
                "target_social": "", "target_recovery": "", "growth_focus": [],
                "goal_progress": [{"id": "stg1", "progress": 0.5, "note": "写了一半"}],
            }, ensure_ascii=False)

        with patch.object(realism, "call_llm", fake_llm):
            result = realism.consolidate_day(
                _agent(), 3, [_episode()], {}, {"remaining": 2},
                goals_context="- 短期[stg1]：完成课题申报（进度 20%）",
            )
        self.assertIn("当前人生与阶段目标", prompts[0])
        self.assertEqual(result["goal_progress"][0]["id"], "stg1")

    def test_no_llm_budget_returns_empty_goal_progress(self):
        result = realism.consolidate_day(_agent(), 3, [_episode()], {}, {"remaining": 0})
        self.assertEqual(result["goal_progress"], [])

    def test_no_episodes_returns_empty_goal_progress(self):
        result = realism.consolidate_day(_agent(), 3, [], {}, {"remaining": 2})
        self.assertEqual(result["goal_progress"], [])

    def test_malformed_goal_progress_becomes_empty_list(self):
        def fake_llm(prompt, task=None, agent_id=None):
            return json.dumps({"summary": "ok", "priorities": [], "avoidances": [],
                               "target_social": "", "target_recovery": "",
                               "growth_focus": [], "goal_progress": "不是列表"},
                              ensure_ascii=False)

        with patch.object(realism, "call_llm", fake_llm):
            result = realism.consolidate_day(
                _agent(), 3, [_episode()], {}, {"remaining": 2}, goals_context="x")
        self.assertEqual(result["goal_progress"], [])


class TestMainSimGoalsWiring(unittest.TestCase):
    def _agent(self):
        return {
            "id": 5, "name": "测试者", "age": 30, "job": "教师",
            "personality": "耐心", "daily_life": "规律", "values": "务实",
            "state": {}, "growth_profile": {}, "episodes": [], "intentions": {},
            "goals": {
                "life_goals": [{"id": "lg1", "title": "教书育人", "domain": "career",
                                "description": "", "status": "active"}],
                "long_term_goals": [],
                "short_term_goals": [{"id": "stg1", "parent": "", "title": "完成课题申报",
                                      "target_day": 14, "progress": 0.2,
                                      "status": "active", "recent_note": "",
                                      "created_day": 1, "updated_day": 1}],
                "last_review_day": 0, "needs_review": False, "review_log": [],
            },
        }

    def test_goals_hint_formats_and_respects_disabled(self):
        import generative_city_sim as sim

        agent = self._agent()
        with patch.object(sim, "GOALS_ENABLED", True):
            self.assertIn("完成课题申报", sim._goals_hint(agent))
        with patch.object(sim, "GOALS_ENABLED", False):
            self.assertEqual(sim._goals_hint(agent), "无")

    def test_daily_routine_prompt_contains_goals(self):
        import generative_city_sim as sim

        prompts = []

        def fake_llm(prompt, task=None, agent_id=None):
            prompts.append(prompt)
            return "[]"

        agent = self._agent()
        with patch.object(sim, "call_llm", fake_llm), \
             patch.object(sim, "GOALS_ENABLED", True), \
             patch.object(sim, "retrieve_relevant_memories", lambda *a, **k: []):
            sim.generate_daily_routine(agent, [("08:00", "起床")], day=2)
        self.assertTrue(prompts)
        self.assertIn("当前人生与阶段目标", prompts[0])
        self.assertIn("完成课题申报", prompts[0])

    def test_interview_prompt_contains_goals(self):
        import generative_city_sim as sim

        prompts = []

        def fake_llm(prompt, task=None, agent_id=None):
            prompts.append(prompt)
            return json.dumps([{"question": "q", "answer": "a"}], ensure_ascii=False)

        agent = self._agent()
        with patch.object(sim, "call_llm", fake_llm), \
             patch.object(sim, "GOALS_ENABLED", True), \
             patch.object(sim, "evoke_memory",
                          lambda *a, **k: {"hint": "无", "recollection": ""}):
            sim.interview_agent(agent, ["你最近在忙什么？"])
        self.assertIn("完成课题申报", prompts[0])


class TestDiaryGoalsInjection(unittest.TestCase):
    def test_diary_prompt_contains_goals(self):
        from gaworld.sim import _diary

        prompts = []

        def fake_llm(prompt, task=None, agent_id=None):
            prompts.append(prompt)
            return ("## 今天主要发生的事情\nx\n## 今天的感想\ny\n## 明天的计划\nz")

        agent = {
            "id": 5, "name": "测试者", "episodes": [], "intentions": {},
            "goals": {
                "life_goals": [], "long_term_goals": [],
                "short_term_goals": [{"id": "stg1", "parent": "", "title": "完成课题申报",
                                      "target_day": 14, "progress": 0.2,
                                      "status": "active", "recent_note": "",
                                      "created_day": 1, "updated_day": 1}],
                "last_review_day": 0, "needs_review": False, "review_log": [],
            },
        }
        with patch.object(_diary._llm_providers, "call_llm", fake_llm):
            _diary.generate_daily_diary(agent, 3, "今天的日志")
        self.assertIn("我的目标与追求", prompts[0])
        self.assertIn("完成课题申报", prompts[0])


if __name__ == "__main__":
    unittest.main()
