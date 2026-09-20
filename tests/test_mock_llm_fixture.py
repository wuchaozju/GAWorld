"""Tests for the MockLLM test fixture itself."""

from __future__ import annotations

import unittest

from tests.fixtures.mock_llm import DEFAULT_RESPONSES, MockLLM, install


class TestMockLLMBasics(unittest.TestCase):
    def test_returns_default_for_known_task(self):
        mock = MockLLM()
        out = mock("anything", task="schedule")
        self.assertIn("起床", out)

    def test_records_calls(self):
        mock = MockLLM()
        mock("p1", task="schedule", agent_id=1)
        mock("p2", task="reflection", agent_id=1)
        self.assertEqual(2, mock.call_count())
        self.assertEqual(1, mock.call_count("schedule"))
        self.assertEqual(["reflection", "schedule"], mock.tasks_seen())

    def test_set_response_overrides(self):
        mock = MockLLM()
        mock.set_response("schedule", "OVERRIDE")
        self.assertEqual("OVERRIDE", mock("any", task="schedule"))

    def test_set_handler_uses_callable(self):
        mock = MockLLM()
        mock.set_handler("planning", lambda prompt, aid: f"plan-for-{aid}")
        self.assertEqual("plan-for-7", mock("p", task="planning", agent_id=7))

    def test_unknown_task_returns_generic(self):
        mock = MockLLM()
        self.assertEqual("ok", mock("p", task="completely-new"))


class TestDefaultsCoverFrequentTasks(unittest.TestCase):
    """The simulator dispatches ~20 distinct task names; make sure we
    have a default for the most common ones so smoke tests don't fall
    through to the generic ``"ok"`` (which would break parsers)."""

    REQUIRED = (
        "schedule",
        "daily_routine",
        "actions",
        "perception",
        "planning",
        "reflection",
        "daily_diary",
        "summary",
        "memory_consolidation",
        "daily_intentions",
        "growth_profile",
        "routine_change",
        "external_environment",
    )

    def test_required_tasks_present(self):
        missing = [t for t in self.REQUIRED if t not in DEFAULT_RESPONSES]
        self.assertEqual([], missing, f"missing default responses for: {missing}")


class TestInstallPatch(unittest.TestCase):
    def test_install_swaps_llm_providers_call_llm(self):
        from gaworld.llm import providers as llm_providers

        original = llm_providers.call_llm
        with install() as mock:
            self.assertIsNot(llm_providers.call_llm, original)
            self.assertIs(llm_providers.call_llm, mock)
        self.assertIs(llm_providers.call_llm, original)


if __name__ == "__main__":
    unittest.main()
