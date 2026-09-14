"""Integration glue: bootstrap → in-sim relationship_update → decay → ghost events.

This intentionally exercises the new social_network module *together
with* human_realism.relationship_update and life_events.add_life_event,
so that the surfaces the simulator now relies on stay coherent without
having to import generative_city_sim itself (which has heavy deps).
"""

from __future__ import annotations

import os
import random
import tempfile
import unittest

from gaworld.cognition import realism as human_realism
from gaworld.events import life as life_events
from gaworld.social import network as sn


class TestIntegration(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.config = {
            "life_events": {
                "event_dir": os.path.join(self.tmpdir.name, "life_events"),
                "events_file": "events.json",
            }
        }

    def _make_agent(self):
        return {
            "id": 7,
            "name": "李白",
            "job": "数据分析师",
            "living": "成都",
            "personality": "温和、谨慎",
            "current_day": 0,
            "state": {"emotion": 0.5, "stress": 0.4},
            "relationships": {
                "12": {  # an in-sim neighbour, legacy schema
                    "closeness": 0.5, "trust": 0.5,
                    "obligation": 0.5, "friction": 0.5,
                    "last_interaction_day": 0,
                },
            },
        }

    def test_bootstrap_then_in_sim_update_coexist(self):
        agent = self._make_agent()
        sn.bootstrap_social_roster(agent, None, current_day=0)  # heuristic
        # In-sim neighbour update still works on the legacy record:
        human_realism.relationship_update(agent, 12, "positive", {})
        rec = agent["relationships"]["12"]
        self.assertGreater(rec["closeness"], 0.5)
        # And the bootstrap added off-screen ghosts:
        ghosts = [v for v in agent["relationships"].values()
                  if isinstance(v, dict) and v.get("kind") == "ghost"]
        self.assertGreater(len(ghosts), 0)

    def test_relationship_phase_keeps_continuous_emotion(self):
        agent = self._make_agent()
        agent["current_day"] = 3
        agent["state"]["emotion"] = 0.52
        agent["state"]["emotion_state"] = 1
        agent["relationships"]["12"]["closeness"] = 0.72
        rec = human_realism.relationship_update(agent, 12, "negative", {})
        self.assertEqual(rec["phase"], 2)
        self.assertEqual(rec["last_interaction_day"], 3)
        self.assertEqual(rec["last_contact_day"], 3)
        self.assertEqual(agent["state"]["emotion"], 0.52)
        self.assertIn(agent["state"]["emotion_state"], {2, 3})

    def test_decay_runs_on_mixed_in_sim_and_ghost(self):
        agent = self._make_agent()
        sn.bootstrap_social_roster(agent, None, current_day=0)
        # Touch the in-sim neighbour today so it does not decay.
        agent["current_day"] = 30
        human_realism.relationship_update(agent, 12, "positive", {})
        before = {k: dict(v) for k, v in agent["relationships"].items()
                  if isinstance(v, dict)}
        sn.decay_relationships(agent, current_day=30)
        sn.enforce_dunbar(agent)
        # In-sim partner with last_contact_day=30 should not decay.
        self.assertAlmostEqual(
            agent["relationships"]["12"]["closeness"],
            before["12"]["closeness"],
            places=5,
        )
        # A neglected ghost should have a lower closeness than its
        # starting closeness.
        for key, item in before.items():
            if isinstance(item, dict) and item.get("kind") == "ghost":
                self.assertLessEqual(
                    agent["relationships"][key]["closeness"],
                    item["closeness"] + 1e-9,
                )

    def test_ghost_event_flows_through_life_events_pipeline(self):
        agent = self._make_agent()
        sn.bootstrap_social_roster(agent, None, current_day=0)
        rng = random.Random(3)
        ev = sn.generate_ghost_event(agent, current_day=5, rng=rng)
        self.assertIsNotNone(ev)
        # Translate to a life_events payload the simulator would push:
        payload = {
            "title": ev["title"],
            "description": ev["description"],
            "severity": ev.get("severity", 0.55),
            "impact_tags": ev["impact_tags"],
            "state_effects": ev["state_effects"],
            "schedule_mode": "scheduled",
            "day": 5,
            "time": "08:30",
            "agent_ids": [agent["id"]],
            "template_key": ev["template_key"],
            "created_by": "social_network",
        }
        stored = life_events.add_life_event(payload, self.config)
        self.assertEqual(stored["template_key"], ev["template_key"])
        # And it surfaces as a due event at the scheduled time.
        due = life_events.drain_due_life_events(5, "08:30", self.config)
        self.assertEqual(len(due), 1)
        self.assertEqual(due[0]["title"], ev["title"])

    def test_role_aware_weight_used_after_migration(self):
        agent = self._make_agent()
        sn.bootstrap_social_roster(agent, None, current_day=0)
        # The mother ghost should outrank the (legacy) in-sim neighbour
        # for the purposes of social-context sampling, given the same
        # base scores. Sanity-check via the public weight function.
        kin_key = next(
            k for k, v in agent["relationships"].items()
            if v.get("role") == "mother"
        )
        kin_w = human_realism.relationship_weight(agent, kin_key.lstrip("g_"))  # not numeric; will hit default
        # Use the direct key string instead (relationship_weight just does dict lookup by str).
        agent["relationships"][kin_key]["closeness"] = 0.7
        agent["relationships"][kin_key]["trust"] = 0.7
        agent["relationships"][kin_key]["obligation"] = 0.5
        agent["relationships"][kin_key]["friction"] = 0.0
        kin_w = human_realism.relationship_weight(agent, kin_key)
        agent["relationships"]["12"]["closeness"] = 0.7
        agent["relationships"]["12"]["trust"] = 0.7
        agent["relationships"]["12"]["obligation"] = 0.5
        agent["relationships"]["12"]["friction"] = 0.0
        legacy_w = human_realism.relationship_weight(agent, 12)
        self.assertGreater(kin_w, legacy_w)


if __name__ == "__main__":
    unittest.main()
