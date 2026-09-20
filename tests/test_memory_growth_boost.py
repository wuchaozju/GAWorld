"""Tests for D4: interest/skill growth ↔ RAG integration."""

from __future__ import annotations

import os
import tempfile
import unittest

from gaworld.memory import store as ms
from gaworld.settings import CONFIG
from gaworld.interests import KIND_HOBBY, KIND_SKILL, GrowthItem, GrowthProfile


class TestGrowthBoostInRetrieval(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.old_memory_dir = ms.MEMORY_DIR
        self.old_vector_db_path = ms.VECTOR_DB_PATH
        ms.MEMORY_DIR = os.path.join(self.tmpdir.name, "memory")
        ms.VECTOR_DB_PATH = os.path.join(ms.MEMORY_DIR, "vector.sqlite")
        ms._close_vector_db()
        self._old_mem_cfg = CONFIG.get("memory", {}).copy()

    def tearDown(self):
        ms._close_vector_db()
        ms.MEMORY_DIR = self.old_memory_dir
        ms.VECTOR_DB_PATH = self.old_vector_db_path
        CONFIG["memory"] = self._old_mem_cfg

    def _agent_with_running_growth(self, agent_id: int):
        profile = GrowthProfile(
            agent_id=agent_id,
            items=[
                GrowthItem(
                    name="跑步",
                    kind=KIND_HOBBY,
                    category="健康",
                    priority=0.90,
                    activity_templates=["跑步训练", "晨跑"],
                ),
                GrowthItem(
                    name="编程技能",
                    kind=KIND_SKILL,
                    category="技术",
                    priority=0.50,
                    activity_templates=["练习编程", "做项目"],
                ),
            ],
        )
        return {"id": agent_id, "growth_profile": profile.to_dict()}

    def test_growth_match_outranks_unrelated_hit_when_enabled(self):
        # Two equally-similar memories: one matches the agent's high-
        # priority growth item, one does not. With growth_boost ON the
        # growth-matched memory must rank first.
        CONFIG["memory"] = {"growth_boost": True, "growth_boost_strength": 0.30}
        ms.vector_db_add_entry(50, "memory", "今天 完成 跑步训练 状态好")
        ms.vector_db_add_entry(50, "memory", "今天 完成 简单 杂务")
        agent = self._agent_with_running_growth(50)
        hits = ms.retrieve_relevant_memories(agent, "今天 完成 训练", max_items=2)
        self.assertEqual(2, len(hits))
        self.assertIn("跑步训练", hits[0]["text"])
        # The boosted hit should carry the growth_match annotation.
        self.assertIn("growth_match", hits[0])
        self.assertIn("跑步", hits[0]["growth_match"])

    def test_growth_boost_off_keeps_legacy_ordering(self):
        CONFIG["memory"] = {"growth_boost": False}
        ms.vector_db_add_entry(51, "memory", "今天 完成 跑步训练 状态好")
        ms.vector_db_add_entry(51, "memory", "今天 完成 训练 任务")
        agent = self._agent_with_running_growth(51)
        hits = ms.retrieve_relevant_memories(agent, "今天 完成 训练", max_items=2)
        self.assertEqual(2, len(hits))
        # No annotation when boost is off.
        for h in hits:
            self.assertNotIn("growth_match", h)

    def test_no_profile_means_no_boost(self):
        CONFIG["memory"] = {"growth_boost": True, "growth_boost_strength": 0.30}
        ms.vector_db_add_entry(52, "memory", "今天 完成 跑步训练")
        agent = {"id": 52}  # No growth_profile key.
        hits = ms.retrieve_relevant_memories(agent, "今天 完成 训练", max_items=1)
        self.assertEqual(1, len(hits))
        self.assertNotIn("growth_match", hits[0])


if __name__ == "__main__":
    unittest.main()
