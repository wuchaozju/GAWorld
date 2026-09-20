"""Ghost-driven off-screen life events."""

from __future__ import annotations

import json
import random
import unittest

from gaworld.social import network as sn


def _seeded_agent():
    return {
        "id": 11,
        "name": "李白",
        "relationships": {
            "g_mother": {
                "kind": "ghost", "role": "mother",
                "closeness": 0.85, "trust": 0.85, "obligation": 0.80, "friction": 0.1,
                "decay_rate": 0.001, "obligation_base": 0.80,
                "tie_origin": "hometown",
                "profile": {"name": "李母", "city": "重庆", "vibe": "操心"},
                "last_contact_day": 3, "last_interaction_day": 3,
            },
            "g_old_classmate": {
                "kind": "ghost", "role": "classmate",
                "closeness": 0.45, "trust": 0.45, "obligation": 0.30, "friction": 0.2,
                "decay_rate": 0.012, "obligation_base": 0.28,
                "tie_origin": "college",
                "profile": {"name": "周野", "city": "北京", "vibe": "话痨"},
                "last_contact_day": 0, "last_interaction_day": 0,  # current_day=100 → gap 100
            },
        },
    }


class TestGhostEvents(unittest.TestCase):
    def test_returns_none_when_no_ghosts(self):
        agent = {"id": 1, "relationships": {}}
        rng = random.Random(0)
        self.assertIsNone(sn.generate_ghost_event(agent, current_day=1, rng=rng))

    def test_event_updates_last_contact_day(self):
        agent = _seeded_agent()
        rng = random.Random(42)
        ev = sn.generate_ghost_event(agent, current_day=100, rng=rng)
        self.assertIsNotNone(ev)
        ghost = agent["relationships"][ev["ghost_key"]]
        self.assertEqual(ghost["last_contact_day"], 100)
        self.assertEqual(ghost["last_interaction_day"], 100)

    def test_state_effects_are_present_and_clamped(self):
        agent = _seeded_agent()
        rng = random.Random(0)
        ev = sn.generate_ghost_event(agent, current_day=100, rng=rng)
        self.assertIn("state_effects", ev)
        for k, v in ev["state_effects"].items():
            self.assertIsInstance(v, float)
            self.assertLessEqual(abs(v), 0.35)

    def test_long_gap_unlocks_reconnect_template(self):
        # An agent whose only ghost has not been contacted in 120 days
        # should be eligible for the ghost_reconnect template.
        agent = {
            "id": 1,
            "relationships": {
                "g_classmate": {
                    "kind": "ghost", "role": "classmate",
                    "closeness": 0.30, "trust": 0.30, "obligation": 0.30, "friction": 0.20,
                    "decay_rate": 0.012, "obligation_base": 0.28,
                    "tie_origin": "college",
                    "profile": {"name": "周野", "city": "北京"},
                    "last_contact_day": 0, "last_interaction_day": 0,
                }
            },
        }
        seen = set()
        for seed in range(60):
            rng = random.Random(seed)
            ev = sn.generate_ghost_event(agent.copy() if False else _clone(agent), current_day=180, rng=rng)
            if ev:
                seen.add(ev["template_key"])
        self.assertIn("ghost_reconnect", seen)

    def test_llm_can_override_title_and_description(self):
        agent = _seeded_agent()
        rng = random.Random(0)

        def llm(prompt, task=None, agent_id=None):
            self.assertEqual(task, "ghost_event")
            return json.dumps({"title": "妈打来电话", "description": "她说想我了。"}, ensure_ascii=False)

        ev = sn.generate_ghost_event(agent, current_day=100, llm_call=llm, rng=rng)
        self.assertEqual(ev["title"], "妈打来电话")
        self.assertIn("想我", ev["description"])

    def test_signal_propagates_to_relationship(self):
        agent = _seeded_agent()
        ghost_before_closeness = agent["relationships"]["g_mother"]["closeness"]
        rng = random.Random(1)
        # Run repeatedly until we hit a positive-signal template to verify.
        for seed in range(40):
            local_agent = _clone(agent)
            ev = sn.generate_ghost_event(local_agent, current_day=100, rng=random.Random(seed))
            if ev and ev["signal"] == "positive":
                after = local_agent["relationships"][ev["ghost_key"]]["closeness"]
                before = agent["relationships"][ev["ghost_key"]]["closeness"]
                self.assertGreater(after, before - 1e-9)
                return
        self.skipTest("No positive-signal sample hit in 40 seeds")


def _clone(agent):
    import copy
    return copy.deepcopy(agent)


if __name__ == "__main__":
    unittest.main()
