"""Tests for D1c: consolidation + decay modules."""

from __future__ import annotations

import os
import tempfile
import time
import unittest

from gaworld.memory import store as ms
from gaworld.settings import CONFIG
from gaworld.memory import consolidation, decay


class _MemoryStoreTempDir:
    """Mixin: route memory_store at a fresh sqlite per test."""

    def _setup_tmp_store(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.old_memory_dir = ms.MEMORY_DIR
        self.old_vector_db_path = ms.VECTOR_DB_PATH
        ms.MEMORY_DIR = os.path.join(self.tmpdir.name, "memory")
        ms.VECTOR_DB_PATH = os.path.join(ms.MEMORY_DIR, "vector.sqlite")
        ms._close_vector_db()

    def _teardown_tmp_store(self):
        ms._close_vector_db()
        ms.MEMORY_DIR = self.old_memory_dir
        ms.VECTOR_DB_PATH = self.old_vector_db_path


class TestConsolidation(unittest.TestCase, _MemoryStoreTempDir):
    def setUp(self):
        self._setup_tmp_store()
        self._old_mem_cfg = CONFIG.get("memory", {}).copy()

    def tearDown(self):
        self._teardown_tmp_store()
        CONFIG["memory"] = self._old_mem_cfg

    def test_disabled_returns_empty(self):
        """Turning it off is a no-op even with episodes and a working LLM.

        This case used to assert that *the default* was off, and it has never
        passed: the test and ``settings/runtime.py`` were added in the same
        commit (aca2ce7) already disagreeing -- the settings file says
        ``enabled: True`` while ``consolidation.py`` falls back to ``False``
        when the key is absent. Which of the two is intended is a product
        decision and is recorded in ``test_the_current_defaults`` below rather
        than silently settled here. What this case can test without deciding
        anything is the mechanism: when it *is* off, nothing happens.
        """
        CONFIG["memory"] = {"consolidation": {"enabled": False}}
        for i in range(4):
            ms.vector_db_add_entry(7, "memory", f"E{i}: 工作 顺利", sim_day=1)
        out = consolidation.consolidate_recent(
            {"id": 7}, llm=lambda p: '["foo"]', today=2
        )
        self.assertEqual([], out)

    def test_the_current_defaults(self):
        """Pins what ships today. **Not** a statement that it is right.

        ``memory.consolidation`` and ``memory.decay`` both ship enabled, so an
        operator who never touches the config gets periodic summarisation and
        periodic **deletion** of low-salience memories older than 30 days.
        Deletion-by-default in a longitudinal simulator is the kind of thing
        that should be chosen on purpose; nobody has confirmed it was. This
        test exists so the choice is visible and so a change to it is
        deliberate -- see the open question in CHANGELOG.
        """
        defaults = CONFIG["memory"]
        self.assertTrue(defaults["consolidation"]["enabled"])
        self.assertTrue(defaults["decay"]["enabled"])
        self.assertEqual(30, defaults["decay"]["min_age_days"])
        self.assertEqual(0.20, defaults["decay"]["salience_floor"])

    def test_enabled_writes_semantic_rows_with_high_salience(self):
        CONFIG["memory"] = {
            "consolidation": {"enabled": True, "lookback_days": 7, "max_outputs": 2}
        }
        for i in range(5):
            ms.vector_db_add_entry(
                8, "memory", f"项目 alpha 推进 顺利 进度 {i}", sim_day=2
            )

        captured_prompt = {}

        def fake_llm(prompt):
            captured_prompt["p"] = prompt
            return '["稳步推进 alpha 项目，整体节奏顺利", "保持每日小目标的工作方式"]'

        out = consolidation.consolidate_recent(
            {"id": 8}, llm=fake_llm, today=2, max_outputs=2
        )
        self.assertEqual(2, len(out))
        # Each output stored as a `semantic` row with elevated salience.
        conn = ms._vector_db_connect()
        rows = conn.execute(
            "SELECT entry_type, salience FROM memory_entries "
            "WHERE agent_id = 8 AND entry_type = 'semantic'"
        ).fetchall()
        self.assertEqual(2, len(rows))
        for entry_type, salience in rows:
            self.assertEqual("semantic", entry_type)
            self.assertAlmostEqual(0.80, float(salience), places=2)
        # Prompt fed to the LLM should mention the episodes.
        self.assertIn("项目 alpha", captured_prompt["p"])

    def test_skips_when_too_few_episodes(self):
        CONFIG["memory"] = {"consolidation": {"enabled": True}}
        ms.vector_db_add_entry(9, "memory", "孤立 一条", sim_day=1)
        out = consolidation.consolidate_recent(
            {"id": 9}, llm=lambda p: '["x"]', today=1
        )
        self.assertEqual([], out)

    def test_parser_recovers_from_extra_prose(self):
        CONFIG["memory"] = {"consolidation": {"enabled": True}}
        for i in range(3):
            ms.vector_db_add_entry(10, "memory", f"日常 工作 {i}", sim_day=1)
        # LLM wraps the array in narration — common failure mode.
        wrapped = '好的，以下是总结：\n["这是一条心得", "另一条心得"]\n谢谢。'
        out = consolidation.consolidate_recent(
            {"id": 10}, llm=lambda p: wrapped, today=1
        )
        self.assertEqual(["这是一条心得", "另一条心得"], out)


class TestDecay(unittest.TestCase, _MemoryStoreTempDir):
    def setUp(self):
        self._setup_tmp_store()
        self._old_mem_cfg = CONFIG.get("memory", {}).copy()

    def tearDown(self):
        self._teardown_tmp_store()
        CONFIG["memory"] = self._old_mem_cfg

    def _insert_old_row(self, agent_id, text, salience, age_seconds, entry_type="memory"):
        # Bypass vector_db_add_entry to control created_at directly.
        ms._init_vector_db()
        conn = ms._vector_db_connect()
        import json as _json
        vec = ms._embed_text(text)
        old_created_at = time.time() - age_seconds
        with conn:
            conn.execute(
                "INSERT INTO memory_entries "
                "(agent_id, entry_type, text, sim_day, sim_time, created_at, "
                " embedding, salience, emotion, recall_count, last_recall_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    int(agent_id), entry_type, text, 0, "00:00",
                    old_created_at, _json.dumps(vec), float(salience), 0.0, 0, 0.0,
                ),
            )

    def test_disabled_is_noop(self):
        # Same story as consolidation above: this asserted the default, the
        # default has always been on, and the mechanism is what is testable
        # without deciding whether it should be.
        CONFIG["memory"] = {"decay": {"enabled": False}}
        self._insert_old_row(31, "已经很久 没用 的 旧 记忆", 0.10, age_seconds=86400 * 100)
        out = decay.decay_pass(31, today=200)
        self.assertEqual({"decayed": 0, "deleted": 0}, out)

    def test_enabled_deletes_old_below_floor_fades_others(self):
        CONFIG["memory"] = {
            "decay": {
                "enabled": True,
                "min_age_days": 30,
                "salience_floor": 0.20,
            }
        }
        # One old row well below floor → deleted.
        self._insert_old_row(32, "陈旧 琐事 一", 0.15, age_seconds=86400 * 60)
        # One old row above floor → faded by salience_step.
        self._insert_old_row(32, "陈旧 但 还算 有 印象 二", 0.50, age_seconds=86400 * 60)
        # One young row → untouched.
        self._insert_old_row(32, "最近 的 事 三", 0.50, age_seconds=86400 * 2)

        out = decay.decay_pass(32, today=100, salience_step=0.05)
        self.assertEqual({"decayed": 1, "deleted": 1}, out)
        conn = ms._vector_db_connect()
        rows = dict(
            conn.execute(
                "SELECT text, salience FROM memory_entries WHERE agent_id = 32"
            ).fetchall()
        )
        self.assertNotIn("陈旧 琐事 一", rows)
        self.assertAlmostEqual(0.45, float(rows["陈旧 但 还算 有 印象 二"]), places=3)
        self.assertAlmostEqual(0.50, float(rows["最近 的 事 三"]), places=3)

    def test_enabled_spares_semantic_and_external(self):
        CONFIG["memory"] = {
            "decay": {
                "enabled": True,
                "min_age_days": 30,
                "salience_floor": 0.50,  # would normally delete everything below
            }
        }
        # Both protected types with low salience and old timestamps.
        self._insert_old_row(
            33, "心得 不应 被 遗忘", 0.10, age_seconds=86400 * 100, entry_type="semantic"
        )
        self._insert_old_row(
            33, "外部 背景 信息", 0.10, age_seconds=86400 * 100, entry_type="external_info"
        )
        out = decay.decay_pass(33, today=200)
        self.assertEqual({"decayed": 0, "deleted": 0}, out)
        conn = ms._vector_db_connect()
        cnt = conn.execute(
            "SELECT COUNT(1) FROM memory_entries WHERE agent_id = 33"
        ).fetchone()[0]
        self.assertEqual(2, cnt)


if __name__ == "__main__":
    unittest.main()
