"""Dashboard goals endpoints: payload read + validated write."""

import json
import os
import tempfile
import unittest
from unittest.mock import patch

from gaworld.apps import dashboard_server as ds


def _valid_payload():
    return {
        "life_goals": [{"id": "lg1", "title": "安家", "domain": "family",
                        "description": "", "status": "active"}],
        "long_term_goals": [{"id": "ltg1", "parent": "lg1", "title": "攒首付",
                             "horizon_days": 700, "progress": 0.1, "status": "active",
                             "created_day": 1, "updated_day": 1}],
        "short_term_goals": [{"id": "stg1", "parent": "ltg1", "title": "调仓",
                              "target_day": 14, "progress": 0.4, "status": "active",
                              "recent_note": "", "created_day": 1, "updated_day": 1}],
        "last_review_day": 0, "needs_review": False, "review_log": [],
    }


class TestGoalsPayload(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher_root = patch.object(ds, "REPO_ROOT", self.tmp.name)
        patcher_cfg = patch.object(
            ds, "_effective_config", lambda: {"memory_dir": "memory"})
        patcher_root.start()
        self.addCleanup(patcher_root.stop)
        patcher_cfg.start()
        self.addCleanup(patcher_cfg.stop)
        os.makedirs(os.path.join(self.tmp.name, "memory"), exist_ok=True)

    def test_read_missing_returns_empty(self):
        self.assertEqual(ds._agent_goals_payload(9), {})

    def test_save_then_read_roundtrip(self):
        saved = ds._save_agent_goals_payload(9, _valid_payload())
        self.assertEqual(saved["short_term_goals"][0]["title"], "调仓")
        loaded = ds._agent_goals_payload(9)
        self.assertEqual(loaded["long_term_goals"][0]["id"], "ltg1")

    def test_save_rejects_non_dict_and_empty(self):
        with self.assertRaises(ValueError):
            ds._save_agent_goals_payload(9, ["not", "a", "dict"])
        with self.assertRaises(ValueError):
            ds._save_agent_goals_payload(9, {"life_goals": [{"title": ""}]})

    def test_save_normalizes_bad_status(self):
        payload = _valid_payload()
        payload["short_term_goals"][0]["status"] = "bogus"
        saved = ds._save_agent_goals_payload(9, payload)
        self.assertEqual(saved["short_term_goals"][0]["status"], "active")


if __name__ == "__main__":
    unittest.main()
