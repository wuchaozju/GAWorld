"""RED tests — the persona-authoring call must go through the LLM router.

Mirror of ``tests/test_llm_routing_phase4.py`` discipline, applied to the new
``persona_generate_api`` delegate:

* the enrichment call is ``call_llm(prompt, task="persona_author",
  provider=…, agent_id=None)`` — a new task name, so config-driven task
  routing works with zero router changes;
* an explicit ``provider`` from the request body is passed through verbatim
  and beats task routing (``providers.py`` explicit-precedence);
* ``agent_id`` stays ``None``: a stray agent id would let per-agent routing
  shadow the task and answer enrichment with the wrong model.

The module does not exist yet — every test here must fail naming the missing
feature, never with a syntax error.
"""

from __future__ import annotations

import unittest
from unittest import mock

from gaworld.llm.providers import resolve_llm_target

from tests.test_persona_generate_api import BaseGenerateCase, _api


ROUTING = {
    "default": {"provider": "a", "model": "m-a"},
    "tasks": {"persona_author": {"provider": "c", "model": "m-c"}},
    "agents": {"1": {"provider": "b", "model": "m-b"}},
}


class TestRouterPrecedenceGuard(unittest.TestCase):
    """Non-RED guard: the precedence the delegate relies on already exists."""

    def test_explicit_provider_beats_task_routing(self):
        target = resolve_llm_target(ROUTING, task="persona_author", provider="z")
        self.assertEqual("z", target["provider"])
        self.assertEqual("explicit", target["source"])

    def test_task_routing_for_persona_author(self):
        target = resolve_llm_target(ROUTING, task="persona_author")
        self.assertEqual("c", target["provider"])
        self.assertEqual("task", target["source"])


class TestDelegateRouting(BaseGenerateCase):
    def test_enrichment_calls_with_persona_author_task_and_no_agent(self):
        api = _api()
        record = self.run_job({"scope": "selected", "ids": [1]})
        self.assertEqual("completed", record["status"], record.get("error"))
        self.assertEqual(1, len(self.fake_llm.calls))
        call = self.fake_llm.calls[0]
        self.assertEqual("persona_author", call["task"])
        self.assertIsNone(call["agent_id"])

    def test_explicit_provider_is_passed_through(self):
        record = self.run_job({"scope": "selected", "ids": [1], "provider": "ui-provider"})
        self.assertEqual("completed", record["status"], record.get("error"))
        call = self.fake_llm.calls[0]
        self.assertEqual("ui-provider", call["provider"])

    def test_router_resolution_prefers_explicit_over_agent_for_the_task(self):
        # Even if someone configured agent 1, an explicit provider must win —
        # the delegate passes agent_id=None so this can never silently flip.
        target = resolve_llm_target(ROUTING, task="persona_author", agent_id=1, provider="z")
        self.assertEqual("z", target["provider"])


if __name__ == "__main__":
    unittest.main()
