"""Part C — serious life events leave a decaying, cross-day aftermath.

The aftermath extends an event's influence beyond its single firing tick and
beyond the 2-day recency window of ``_recent_life_events_for_prompt``: it
decays over days, feeds the daily planner a "still affecting you" constraint,
and applies a small lingering state pressure.
"""

import unittest

from gaworld.events import life as life_impl
from gaworld.sim._prompt import _event_aftermath_for_prompt

CFG = {
    "life_events": {
        "aftermath": {
            "enabled": True,
            "min_severity": 0.55,
            "decay_per_day": 0.5,
            "min_residual": 0.15,
            "max_age_days": 6,
            "max_items": 4,
            "state_pressure_scale": 0.5,
        }
    }
}


def _event(**over):
    ev = {
        "id": "e1",
        "template_key": "illness",
        "title": "突然生病",
        "impact_tags": ["health", "routine"],
        "severity": 0.7,
        "state_effects": {"fatigue_debt": 0.12, "stress": 0.14},
    }
    ev.update(over)
    return ev


class TestPushAftermath(unittest.TestCase):
    def test_records_serious_event(self):
        agent = {"id": 1}
        life_impl.push_event_aftermath(agent, _event(), day=5, config=CFG)
        self.assertEqual(len(agent["event_aftermath"]), 1)
        entry = agent["event_aftermath"][0]
        self.assertEqual(entry["residual"], 0.7)
        self.assertEqual(entry["started_day"], 5)

    def test_skips_mild_event(self):
        agent = {"id": 1}
        life_impl.push_event_aftermath(agent, _event(severity=0.4), day=5, config=CFG)
        self.assertNotIn("event_aftermath", agent)

    def test_refire_same_id_updates_in_place(self):
        agent = {"id": 1}
        life_impl.push_event_aftermath(agent, _event(), day=5, config=CFG)
        life_impl.push_event_aftermath(agent, _event(severity=0.9), day=6, config=CFG)
        self.assertEqual(len(agent["event_aftermath"]), 1)
        self.assertEqual(agent["event_aftermath"][0]["residual"], 0.9)


class TestDecayAftermath(unittest.TestCase):
    def test_decays_and_prunes(self):
        agent = {"id": 1}
        life_impl.push_event_aftermath(agent, _event(severity=0.7), day=5, config=CFG)
        # day 6: 0.7 * 0.5 = 0.35 (survives)
        life_impl.decay_event_aftermath(agent, day=6, config=CFG)
        self.assertAlmostEqual(agent["event_aftermath"][0]["residual"], 0.35, places=3)
        # day 7: 0.35 * 0.5 = 0.175 (survives, > 0.15)
        life_impl.decay_event_aftermath(agent, day=7, config=CFG)
        self.assertAlmostEqual(agent["event_aftermath"][0]["residual"], 0.175, places=3)
        # day 8: 0.0875 < min_residual 0.15 → pruned
        life_impl.decay_event_aftermath(agent, day=8, config=CFG)
        self.assertEqual(agent["event_aftermath"], [])

    def test_decay_is_idempotent_within_a_day(self):
        agent = {"id": 1}
        life_impl.push_event_aftermath(agent, _event(severity=0.8), day=5, config=CFG)
        life_impl.decay_event_aftermath(agent, day=6, config=CFG)
        r1 = agent["event_aftermath"][0]["residual"]
        life_impl.decay_event_aftermath(agent, day=6, config=CFG)  # same day again
        r2 = agent["event_aftermath"][0]["residual"]
        self.assertEqual(r1, r2)


class TestStatePressure(unittest.TestCase):
    def test_applies_scaled_residual_pressure(self):
        agent = {"id": 1, "state": {"fatigue_debt": 0.2, "stress": 0.3}}
        life_impl.push_event_aftermath(agent, _event(severity=0.7), day=5, config=CFG)
        life_impl.apply_aftermath_state_pressure(agent, config=CFG)
        # fatigue += 0.12 * residual(0.7) * scale(0.5) = 0.042
        self.assertAlmostEqual(agent["state"]["fatigue_debt"], 0.242, places=3)
        self.assertAlmostEqual(agent["state"]["stress"], 0.349, places=3)


class TestAftermathPrompt(unittest.TestCase):
    def test_prompt_reflects_residual_strength(self):
        agent = {"id": 1}
        life_impl.push_event_aftermath(agent, _event(severity=0.7), day=5, config=CFG)
        text = _event_aftermath_for_prompt(agent, day=6)
        self.assertIn("事件余波", text)
        self.assertIn("突然生病", text)
        self.assertIn("影响仍然很强", text)

    def test_empty_when_no_aftermath(self):
        self.assertEqual(_event_aftermath_for_prompt({"id": 1}, day=6), "事件余波：无。")


if __name__ == "__main__":
    unittest.main()
