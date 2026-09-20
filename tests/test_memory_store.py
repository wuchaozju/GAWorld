import os
import tempfile
import unittest
from unittest.mock import patch

from gaworld.memory import store as ms
from gaworld.settings import CONFIG


class TestMemoryStoreCaches(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.old_log_dir = ms.LOG_DIR
        self.old_memory_dir = ms.MEMORY_DIR
        self.old_vector_db_path = ms.VECTOR_DB_PATH
        ms.LOG_DIR = os.path.join(self.tmpdir.name, "logs")
        ms.MEMORY_DIR = os.path.join(self.tmpdir.name, "memory")
        ms.VECTOR_DB_PATH = os.path.join(ms.MEMORY_DIR, "vector.sqlite")
        ms._LOG_CACHE.clear()
        ms._close_vector_db()

    def tearDown(self):
        ms._close_vector_db()
        ms._LOG_CACHE.clear()
        ms.LOG_DIR = self.old_log_dir
        ms.MEMORY_DIR = self.old_memory_dir
        ms.VECTOR_DB_PATH = self.old_vector_db_path

    def test_recent_log_blocks_and_actions_follow_append_cache(self):
        agent = {"id": 7}
        ms.append_agent_log(agent, "[Morning]\nPlan: 出门\nAction: 吃早餐\n")
        ms.append_agent_log(agent, "[Noon]\nPlan: 工作\nAction: 写代码\n")

        blocks = ms.load_recent_log_blocks(7, max_blocks=2, max_chars=200)
        actions = ms.load_recent_actions(7, max_items=4)

        self.assertEqual(2, len(blocks))
        self.assertIn("[Morning]", blocks[0])
        self.assertIn("[Noon]", blocks[1])
        self.assertEqual(["吃早餐", "写代码"], actions)

    def test_vector_db_connection_is_reused(self):
        first = ms._vector_db_connect()
        second = ms._vector_db_connect()

        self.assertIs(first, second)

        ms.vector_db_add_entry(3, "memory", "project alpha launch", sim_day=1, sim_time="08:00")
        hits = ms.vector_db_search(3, "project alpha launch", top_k=1)

        self.assertEqual(1, len(hits))
        self.assertEqual("memory", hits[0]["type"])

    def test_twin_state_round_trip(self):
        payload = {
            "mode": "personal_twin",
            "layers": {"private": {"status": "local_only"}},
            "today_summary": "今天主要在准备面试。",
        }
        ms.save_agent_twin_state(11, payload)
        loaded = ms.load_agent_twin_state(11)

        self.assertEqual("personal_twin", loaded.get("mode"))
        self.assertEqual("local_only", loaded.get("layers", {}).get("private", {}).get("status"))
        self.assertIn("准备面试", loaded.get("today_summary", ""))


class TestSalienceWeightedRetrieval(unittest.TestCase):
    """D1b: weighted scoring + recall bookkeeping."""

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

    def test_legacy_mode_default_preserves_pure_cosine(self):
        CONFIG["memory"] = {"salience_weight": False}
        ms.vector_db_add_entry(11, "memory", "项目 alpha 上线 顺利", sim_day=1)
        hits = ms.vector_db_search(11, "项目 alpha 上线", top_k=1)
        self.assertEqual(1, len(hits))
        # In legacy mode the returned score is the raw cosine: between
        # 0 and 1, and no decay/salience math applied (so a same-day
        # memory must keep its full cosine value).
        cos_sim = hits[0]["score"]
        self.assertGreater(cos_sim, 0.5)
        self.assertLessEqual(cos_sim, 1.0 + 1e-6)

    def test_weighted_mode_boosts_high_salience(self):
        CONFIG["memory"] = {
            "salience_weight": True,
            "decay_halflife_days": 14,
        }
        # Two near-identical memories. The high-salience one should
        # outrank the low-salience one even though cos_sim is equal.
        ms.vector_db_add_entry(
            12, "memory", "杭州 房租 上涨", sim_day=1, salience=0.95
        )
        ms.vector_db_add_entry(
            12, "memory", "杭州 房租 上涨", sim_day=1, salience=0.10
        )
        hits = ms.vector_db_search(12, "杭州 房租", top_k=2)
        self.assertEqual(2, len(hits))
        # First hit's score must beat second hit's score because the
        # only differentiator is salience.
        self.assertGreater(hits[0]["score"], hits[1]["score"])

    def test_weighted_mode_increments_recall_count(self):
        CONFIG["memory"] = {"salience_weight": True}
        ms.vector_db_add_entry(13, "memory", "练习 编程 项目", sim_day=2)
        ms.vector_db_search(13, "练习 编程", top_k=1)
        ms.vector_db_search(13, "练习 编程", top_k=1)
        conn = ms._vector_db_connect()
        row = conn.execute(
            "SELECT recall_count, last_recall_at FROM memory_entries WHERE agent_id = 13"
        ).fetchone()
        self.assertEqual(2, int(row[0]))
        self.assertGreater(float(row[1]), 0.0)


class TestEmbedTextDispatch(unittest.TestCase):
    """Cover the hash↔LLM provider dispatch added by the RAG enhancement."""

    def setUp(self):
        ms._EMBED_CACHE.clear()
        self._old_mode = CONFIG.get("vector_db_embedding_provider", "hash")

    def tearDown(self):
        ms._EMBED_CACHE.clear()
        CONFIG["vector_db_embedding_provider"] = self._old_mode

    def test_hash_mode_default_preserves_legacy_dim(self):
        CONFIG["vector_db_embedding_provider"] = "hash"
        vec = ms._embed_text("浙江的就业市场", dim=256)
        self.assertEqual(256, len(vec))
        # L2-normalised: nonzero text → unit norm (within fp slack).
        norm = sum(v * v for v in vec) ** 0.5
        self.assertAlmostEqual(1.0, norm, places=3)

    def test_llm_mode_uses_provider_and_caches(self):
        CONFIG["vector_db_embedding_provider"] = "llm"
        calls = {"n": 0}

        def fake_embed_text(text, task=None):
            calls["n"] += 1
            # Non-unit length on purpose — _embed_text must normalise.
            return [3.0, 4.0, 0.0]

        with patch("gaworld.llm.providers.embed_text", side_effect=fake_embed_text):
            v1 = ms._embed_text("the same text")
            v2 = ms._embed_text("the same text")
        self.assertEqual(3, len(v1))
        # Normalised to unit length.
        self.assertAlmostEqual(1.0, sum(v * v for v in v1) ** 0.5, places=5)
        self.assertEqual(v1, v2)
        # Cache hit on the second call: provider only consulted once.
        self.assertEqual(1, calls["n"])

    def test_llm_mode_falls_back_to_hash_on_failure(self):
        CONFIG["vector_db_embedding_provider"] = "llm"

        def fake_embed_text(text, task=None):
            return None  # Simulates "not configured / endpoint down"

        with patch("gaworld.llm.providers.embed_text", side_effect=fake_embed_text):
            vec = ms._embed_text("回退到哈希词袋", dim=256)
        self.assertEqual(256, len(vec))


if __name__ == "__main__":
    unittest.main()
