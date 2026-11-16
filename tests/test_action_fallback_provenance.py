"""J1 — structured fallback provenance in gaworld/sim/_action.py."""

import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from gaworld.sim import _action, _fallback


class TestFallbackProvenance(unittest.TestCase):
    def test_unusable_llm_response_records_fallback(self):
        agent = {"id": 31, "name": "阿明", "age": 40, "job": "教师", "daily_life": "", "values": ""}
        with tempfile.TemporaryDirectory() as tmp:
            log_path = os.path.join(tmp, "action_space_fallbacks.jsonl")
            _fallback.reset_fallback_aggregate()
            env = {k: v for k, v in os.environ.items() if k != _fallback.FALLBACK_LOG_ENV}
            env[_fallback.FALLBACK_LOG_ENV] = log_path
            with mock.patch.dict(os.environ, env, clear=True):
                with unittest.mock.patch.object(_action, "retrieve_relevant_memories", return_value=[]):
                    with unittest.mock.patch.object(
                        _action._llm_providers, "call_llm", return_value="完全不是 JSON"
                    ):
                        result = _action._llm_generate_actions_batch(agent, ["工作"])
            self.assertIn("工作", result)
            self.assertTrue(result["工作"])  # generic fallback actions filled in

            lines = []
            with open(log_path, encoding="utf-8") as fh:
                lines = [json.loads(line) for line in fh]
            self.assertEqual(1, len(lines))
            record = lines[0]
            self.assertEqual(31, record["agent_id"])
            self.assertEqual(["工作"], record["activities"])
            self.assertEqual(2, record["attempts"])
            self.assertTrue(record["fallback"])
            self.assertIn("reason", record)

            aggregate = _fallback.fallback_aggregate()
            self.assertEqual(1, aggregate["action_space_fallback_count"])
            self.assertIn(31, aggregate["agents"])
            self.assertIn("工作", aggregate["activities"])

            with open(os.path.splitext(log_path)[0] + "_summary.json", encoding="utf-8") as fh:
                summary = json.load(fh)
            self.assertEqual(1, summary["action_space_fallback_count"])
        _fallback.reset_fallback_aggregate()

    def test_full_response_records_nothing(self):
        agent = {"id": 7, "name": "x", "age": 30, "job": "", "daily_life": "", "values": ""}
        good = json.dumps({"工作": ["写报告", "开会"]}, ensure_ascii=False)
        with tempfile.TemporaryDirectory() as tmp:
            log_path = os.path.join(tmp, "fb.jsonl")
            _fallback.reset_fallback_aggregate()
            with unittest.mock.patch.dict(os.environ, {_fallback.FALLBACK_LOG_ENV: log_path}):
                with unittest.mock.patch.object(_action, "retrieve_relevant_memories", return_value=[]):
                    with unittest.mock.patch.object(_action._llm_providers, "call_llm", return_value=good):
                        _action._llm_generate_actions_batch(agent, ["工作"])
            self.assertFalse(os.path.exists(log_path))
            self.assertEqual(0, _fallback.fallback_aggregate()["action_space_fallback_count"])
        _fallback.reset_fallback_aggregate()


if __name__ == "__main__":
    unittest.main()
