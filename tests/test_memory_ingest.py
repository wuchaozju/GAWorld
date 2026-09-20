"""Tests for D3: runtime external info absorption."""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

from gaworld.memory import store as ms
from gaworld.settings import CONFIG
from gaworld.interests import KIND_HOBBY, KIND_SKILL, GrowthItem, GrowthProfile
from gaworld.memory import ingest


class TestDeriveAbsorbQueries(unittest.TestCase):
    def test_growth_focus_takes_priority(self):
        profile = GrowthProfile(
            agent_id=1,
            items=[
                GrowthItem(name="跑步", kind=KIND_HOBBY, priority=0.9),
                GrowthItem(name="编程技能", kind=KIND_SKILL, priority=0.6),
            ],
        )
        agent = {
            "id": 1,
            "job": "工程师",
            "values": "稳健 长期",
            "growth_profile": profile.to_dict(),
            "state": {"stress": 0.4, "econ_security": 0.7},
        }
        queries = ingest.derive_absorb_queries(agent, max_queries=2)
        self.assertEqual(2, len(queries))
        # Highest priority growth item should be the first query.
        self.assertEqual("跑步", queries[0])
        self.assertEqual("编程技能", queries[1])

    def test_falls_back_to_job_when_no_growth(self):
        agent = {
            "id": 2,
            "job": "教师",
            "state": {"stress": 0.7, "econ_security": 0.4},
        }
        queries = ingest.derive_absorb_queries(agent, max_queries=1)
        self.assertEqual(1, len(queries))
        self.assertIn("教师", queries[0])
        # Stress high → query should reflect pressure framing.
        self.assertIn("压力", queries[0])


class TestAbsorbExternalForAgent(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.old_memory_dir = ms.MEMORY_DIR
        self.old_vector_db_path = ms.VECTOR_DB_PATH
        ms.MEMORY_DIR = os.path.join(self.tmpdir.name, "memory")
        ms.VECTOR_DB_PATH = os.path.join(ms.MEMORY_DIR, "vector.sqlite")
        ms._close_vector_db()
        self._old_ext_cfg = CONFIG.get("external_rag", {}).copy()

    def tearDown(self):
        ms._close_vector_db()
        ms.MEMORY_DIR = self.old_memory_dir
        ms.VECTOR_DB_PATH = self.old_vector_db_path
        CONFIG["external_rag"] = self._old_ext_cfg

    def _enable_ingest(self, quota=2):
        CONFIG["external_rag"] = {
            **(CONFIG.get("external_rag", {}) or {}),
            "runtime_absorb": True,
            "daily_quota_per_agent": quota,
        }

    def test_disabled_returns_empty(self):
        # Default config has runtime_absorb=False.
        out = ingest.absorb_external_for_agent(
            {"id": 7, "job": "x"},
            day=1, time_str="07:00",
            llm=lambda p: "summary",
            web_fetch_fn=lambda q: [{"title": "T", "content": "C", "url": "U"}],
        )
        self.assertEqual([], out)

    def test_enabled_writes_external_info_rows(self):
        self._enable_ingest(quota=2)
        # Two query sources: growth focus + job. derive_absorb_queries
        # uses growth first, then job, so we expect two queries → two
        # web fetches → two stored snippets.
        profile = GrowthProfile(
            agent_id=8,
            items=[GrowthItem(name="跑步", kind=KIND_HOBBY, priority=0.9)],
        )
        agent = {
            "id": 8, "job": "工程师",
            "state": {"stress": 0.7, "econ_security": 0.4},
            "growth_profile": profile.to_dict(),
        }

        def fake_fetch(query):
            return [{
                "title": f"标题 {query}",
                "content": f"正文 {query}",
                "url": "https://example.com",
            }]

        # _summarize_bootstrap_web_item internally calls call_llm via
        # the providers module; intercept that.
        with patch("gaworld.sim._rag._llm_providers.call_llm", return_value="简短摘要"):
            out = ingest.absorb_external_for_agent(
                agent,
                day=3, time_str="07:30",
                llm=lambda p: "unused",
                web_fetch_fn=fake_fetch,
                max_queries=2,
            )
        self.assertEqual(2, len(out))
        # Every payload should be tagged with the external-info prefix
        # so _external_rag_hint can pick it up.
        for line in out:
            self.assertTrue(line.startswith("[额外信息"), line)

        conn = ms._vector_db_connect()
        rows = conn.execute(
            "SELECT entry_type, salience FROM memory_entries WHERE agent_id = 8"
        ).fetchall()
        self.assertEqual(2, len(rows))
        for entry_type, salience in rows:
            self.assertEqual("external_info", entry_type)
            self.assertAlmostEqual(0.65, float(salience), places=2)

    def test_quota_caps_writes(self):
        self._enable_ingest(quota=1)
        agent = {"id": 9, "job": "教师", "state": {"stress": 0.7}}

        def fake_fetch(query):
            return [
                {"title": "a", "content": "a", "url": "u1"},
                {"title": "b", "content": "b", "url": "u2"},
            ]

        with patch("gaworld.sim._rag._llm_providers.call_llm", return_value="x"):
            out = ingest.absorb_external_for_agent(
                agent,
                day=1, time_str="07:00",
                llm=lambda p: "x",
                web_fetch_fn=fake_fetch,
                max_queries=3,
                max_items_per_query=3,
            )
        # Quota=1 must cap total writes regardless of how many items
        # each query produced.
        self.assertEqual(1, len(out))

    def test_fetch_exception_does_not_crash(self):
        self._enable_ingest(quota=2)
        agent = {"id": 10, "job": "教师"}

        def broken_fetch(query):
            raise RuntimeError("network down")

        out = ingest.absorb_external_for_agent(
            agent,
            day=1, time_str="07:00",
            llm=lambda p: "x",
            web_fetch_fn=broken_fetch,
        )
        self.assertEqual([], out)


if __name__ == "__main__":
    unittest.main()
