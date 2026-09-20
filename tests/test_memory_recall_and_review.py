import random
import unittest
from unittest.mock import patch

import generative_city_sim as sim
from gaworld.llm import providers as llm_providers
from gaworld.sim import _action, _cognition, _diary, _memory_recall

# ``patch.object(sim, ...)`` only intercepts a dependency when the function
# under test also resolves that name from ``generative_city_sim``'s globals.
# The refactor moved these functions into ``gaworld.sim.*``, where they resolve
# their dependencies from *their own* module — so patching the re-export on
# ``sim`` silently intercepts nothing. That is worse than a failing test: the
# call goes to the real vector DB or the real LLM while the test reads as
# though it were stubbed. Patch where the callee looks the name up.


class TestMemoryRecallAndReview(unittest.TestCase):
    def setUp(self):
        # Reset module-level constants that e2e_smoke may have mutated.
        # Without this, tests that run after e2e_smoke in the suite see
        # STATEFUL=False / HUMAN_REALISM_ENABLED=False inherited from
        # e2e_smoke's CONFIG mutations, even after CONFIG is restored.
        sim.STATEFUL = True
        sim.HUMAN_REALISM_ENABLED = True
        sim.HUMAN_REALISM_CONFIG = sim.CONFIG.get("human_realism", {})

    def test_negative_recall_discourages_repeated_bad_action(self):
        agent = {
            "id": 21,
            "state": {
                "emotion": 0.5,
                "stress": 0.5,
                "econ_security": 0.5,
                "energy": 0.6,
                "hunger": 0.4,
                "social_need": 0.4,
                "fatigue_debt": 0.3,
                "self_control": 0.6,
                "time_pressure": 0.3,
            },
            "habits": {},
            "last_activity": "",
            "last_action": "",
        }
        action_space = {"工作": ["推进方案", "拖延刷手机"]}
        recall_context = {
            "hits": [
                {
                    "type": "episode",
                    "text": "上次拖延刷手机导致项目失败，自己很后悔也更焦虑。",
                    "score": 0.9,
                }
            ]
        }
        behavior_cfg = {
            "behavior": {
                "inertia_weight": 0.25,
                "decision_noise": 0.0,
                "avoidance_bonus_scale": 1.1,
                "need_weights": {"energy": 0.45, "hunger": 0.30, "social_need": 0.25},
                "commitment_weights": {"high": 1.2, "medium": 0.6, "low": 0.2},
            }
        }
        with patch.object(sim, "STATEFUL", False), patch.object(
            sim, "HUMAN_REALISM_CONFIG", behavior_cfg
        ):
            random.seed(11)
            productive = 0
            for _ in range(200):
                choice = sim.choose_action(
                    agent,
                    "工作",
                    action_space,
                    context="工作",
                    location_bias={},
                    location="Office",
                    time_str="10:00",
                    recall_context=recall_context,
                )
                if choice == "推进方案":
                    productive += 1
        self.assertGreater(productive, 115)

    def test_positive_recall_reinforces_repeating_good_action(self):
        agent = {
            "id": 25,
            "state": {
                "emotion": 0.55,
                "stress": 0.45,
                "econ_security": 0.5,
                "energy": 0.65,
                "hunger": 0.3,
                "social_need": 0.35,
                "fatigue_debt": 0.2,
                "self_control": 0.7,
                "time_pressure": 0.25,
            },
            "habits": {},
            "last_activity": "",
            "last_action": "",
        }
        action_space = {"上午工作": ["推进方案", "拖一会儿再开始，先刷手机分心"]}
        recall_context = {
            "hits": [
                {
                    "type": "episode",
                    "text": "上次推进方案进展很顺利，得到认可，自己也更放松。",
                    "score": 0.9,
                }
            ]
        }
        behavior_cfg = {
            "behavior": {
                "inertia_weight": 0.25,
                "decision_noise": 0.0,
                "avoidance_bonus_scale": 1.1,
                "need_weights": {"energy": 0.45, "hunger": 0.30, "social_need": 0.25},
                "commitment_weights": {"high": 1.2, "medium": 0.6, "low": 0.2},
            }
        }
        with patch.object(sim, "STATEFUL", False), patch.object(
            sim, "HUMAN_REALISM_CONFIG", behavior_cfg
        ):
            random.seed(29)
            productive = 0
            for _ in range(200):
                choice = sim.choose_action(
                    agent,
                    "上午工作",
                    action_space,
                    context="上午工作",
                    location_bias={},
                    location="Office",
                    time_str="10:00",
                    recall_context=recall_context,
                )
                if choice == "推进方案":
                    productive += 1
        self.assertGreater(productive, 140)

    def test_evoke_memory_surfaces_recollection_and_changes_state(self):
        agent = {
            "id": 22,
            "state": {
                "emotion": 0.50,
                "stress": 0.50,
            },
        }
        hits = [
            {
                "type": "memory",
                "text": "你之前顺利完成过类似任务，当时感到很满意也更放松。",
                "score": 0.6,
            }
        ]
        with patch.object(
            _memory_recall, "retrieve_relevant_memories", return_value=hits
        ) as stub:
            recall = sim.evoke_memory(agent, "planning", "类似任务")
        # Assert the stub was actually consumed. Without this the test would go
        # quiet again the next time the function moves: a patch that intercepts
        # nothing produces no error, only a different answer.
        self.assertTrue(stub.called, "the memory stub was never reached")
        self.assertIn("想起", recall["recollection"])
        self.assertGreater(agent["state"]["emotion"], 0.50)
        self.assertLess(agent["state"]["stress"], 0.50)

    def test_interview_agent_includes_recollection_in_prompt(self):
        agent = {"id": 23, "name": "测试者", "state": {"emotion": 0.5, "stress": 0.5}}
        questions = ["你为什么最近减少社交？"]
        llm_output = '[{"question":"你为什么最近减少社交？","answer":"因为前几次聚会让我有点疲惫。"}]'
        with patch.object(
            sim,
            "evoke_memory",
            return_value={
                "hint": "最近几次聚会后的疲惫感",
                "recollection": "这些问题让你回忆起一段经历：聚会后明显感到疲惫。",
                "hits": [],
            },
        ), patch.object(sim, "call_llm", return_value=llm_output) as mock_call:
            answers = sim.interview_agent(agent, questions, context="关注近期社交变化")
        prompt = mock_call.call_args.args[0]
        self.assertIn("这些问题勾起的回忆", prompt)
        self.assertIn("聚会后明显感到疲惫", prompt)
        self.assertEqual("因为前几次聚会让我有点疲惫。", answers[0]["answer"])

    def test_planning_prompt_always_includes_emotion_and_memory(self):
        agent = {
            "id": 26,
            "name": "规划者",
            "state": {"emotion": 0.33, "stress": 0.71},
            "intentions": {},
        }
        recall_context = {
            "hint": "最近几次临近中午时容易分心。",
            "recollection": "你想起一段经历：上次拖到中午后效率明显下降。",
        }
        llm_output = (
            '{"goal":"先把上午最关键的事推进一点","constraint":"状态一般而且时间不宽裕",'
            '"urge":"有点想先拖一下缓口气","plan":"先做最小推进再决定要不要休息","expected_outcome":"希望别把下午也拖乱"}'
        )
        decision_refs = {
            "emotion_text": "当前情绪：明显偏低落（emotion=0.33）；当前压力：压力偏高（stress=0.71）",
            "memory_hint": recall_context["hint"],
            "recollection": recall_context["recollection"],
            "physical_env_relevant": False,
            "social_env_relevant": False,
            "location_time_relevant": False,
            "social_network_relevant": False,
            "physical_env_text": "",
            "social_env_text": "",
            "location_time_text": "",
            "social_network_text": "",
        }
        with patch.object(sim, "call_llm", return_value=llm_output) as mock_call:
            plan = sim.planning(agent, "你感觉注意力有些散。", recall_context=recall_context, decision_refs=decision_refs)
        prompt = mock_call.call_args.args[0]
        self.assertIn("当前情绪", prompt)
        self.assertIn("你的近期经验", prompt)
        self.assertIn("你此刻被唤起的回忆", prompt)
        self.assertEqual("先把上午最关键的事推进一点", plan["goal"])

    def test_planning_prompt_only_includes_relevant_optional_references(self):
        agent = {
            "id": 27,
            "name": "选择者",
            "state": {"emotion": 0.52, "stress": 0.48},
            "intentions": {},
        }
        recall_context = {"hint": "最近的记忆", "recollection": "想到之前类似情况。"}
        llm_output = (
            '{"goal":"先把路上的变量控制住","constraint":"外面下雨而且时间卡得紧",'
            '"urge":"想直接取消外出","plan":"先看路况再决定是否绕路","expected_outcome":"希望别迟到太久"}'
        )
        decision_refs = {
            "emotion_text": "当前情绪：中性偏波动（emotion=0.52）；当前压力：压力中等（stress=0.48）",
            "memory_hint": recall_context["hint"],
            "recollection": recall_context["recollection"],
            "physical_env_relevant": True,
            "social_env_relevant": False,
            "location_time_relevant": True,
            "social_network_relevant": False,
            "physical_env_text": "下雨且路况拥堵",
            "social_env_text": "这里不应出现",
            "location_time_text": "当前地点：Central Block；当前时间：08:30",
            "social_network_text": "这里也不应出现",
        }
        with patch.object(sim, "call_llm", return_value=llm_output) as mock_call:
            sim.planning(agent, "你担心出门会被路况拖慢。", recall_context=recall_context, decision_refs=decision_refs)
        prompt = mock_call.call_args.args[0]
        self.assertIn("相关物理环境：下雨且路况拥堵", prompt)
        self.assertIn("当前地点：Central Block；当前时间：08:30", prompt)
        self.assertNotIn("这里不应出现", prompt)
        self.assertNotIn("这里也不应出现", prompt)

    def test_memory_review_generates_meta_memory(self):
        agent = {
            "id": 24,
            "name": "复盘者",
            "state": {"emotion": 0.5, "stress": 0.5, "fatigue_debt": 0.4, "self_control": 0.5},
            "memory": [],
            "episodes": [
                {
                    "episode_id": "e1",
                    "day": 2,
                    "time": "09:00",
                    "final_activity": "上午工作",
                    "action": "推进项目",
                    "reflection": "这次推进很顺利",
                    "decision_driver": "现实承诺约束",
                    "tags": ["work", "success"],
                    "salience": 0.8,
                }
            ],
        }
        budget = {"remaining": 1}
        # save_agent_memory / vector_db_add_entry are called from
        # ``_diary._append_memory_record``; call_llm goes through
        # ``_llm_providers.call_llm`` module-attribute dispatch, which is what
        # tests/fixtures/mock_llm.py reassigns too.
        with patch.object(_diary, "save_agent_memory"), patch.object(
            _diary, "vector_db_add_entry"
        ) as mock_vector, patch.object(
            llm_providers, "call_llm",
            return_value="你意识到稳定推进重点任务时，情绪和节奏都会更稳。",
        ):
            review = sim.maybe_review_memories(
                agent,
                day=2,
                time_str="12:00",
                recent_episode=agent["episodes"][0],
                llm_budget_ctx=budget,
            )
        self.assertTrue(mock_vector.called, "the memory-write stub was never reached")
        self.assertIn("MemoryReview", review)
        self.assertEqual(0, budget["remaining"])
        self.assertTrue(agent["memory"])
        self.assertIn("更稳", agent["memory"][0])
        self.assertEqual("meta_memory", mock_vector.call_args.args[1])


if __name__ == "__main__":
    unittest.main()
