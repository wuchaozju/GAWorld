"""Tests for P1: reactions consume structured signals.

Covers structured-first event classification (type/topic/impact_tags),
the impact-tag priority boost, local physical interrupts (crowding /
venue closed), and their pickup inside evaluate_step_dynamics.
"""

import unittest

from gaworld.behavior.dynamic import (
    _classify_event_type,
    evaluate_step_dynamics,
    generate_environment_interrupts,
    generate_local_physical_interrupts,
)


def _agent(**overrides):
    base = {
        "id": 1,
        "name": "测试员",
        "personality": "务实",
        "values": "效率",
        "daily_life": "朝九晚五",
        "job": "职员",
        "state": {"energy": 0.7, "emotion": 0.5, "stress": 0.3,
                  "self_control": 0.5, "risk_preference": 0.5, "social_need": 0.4},
        "locations": {"current": "Office"},
        "relationships": {},
        "social_neighbors": [],
    }
    base.update(overrides)
    return base


class TestStructuredClassification(unittest.TestCase):
    def test_earthquake_not_masked_by_natural_type(self):
        # Regression: a 'natural'-typed quake used to fall into the weather
        # branch first. It must now classify as an emergency.
        cat, sub = _classify_event_type(
            {"type": "natural", "description": "发生地震", "severity": 0.9}
        )
        self.assertEqual((cat, sub), ("emergency", "earthquake"))

    def test_economic_event_routes_to_news_by_severity(self):
        low = _classify_event_type({"type": "economic", "description": "主要指数小幅下跌", "severity": 0.4})
        high = _classify_event_type({"type": "economic", "description": "市场剧烈波动", "severity": 0.8})
        self.assertEqual(low, ("news", "local"))
        self.assertEqual(high, ("news", "breaking"))

    def test_traffic_via_topic_and_mobility_tag(self):
        cat, _sub = _classify_event_type({
            "type": "natural", "topic": "traffic",
            "description": "主干道通行缓慢", "impact_tags": ["mobility"],
        })
        self.assertEqual(cat, "traffic")

    def test_weather_still_classifies(self):
        self.assertEqual(_classify_event_type({"type": "weather", "description": "开始下雨"})[0], "weather")
        self.assertEqual(_classify_event_type({"type": "natural", "description": "暴雨预警"}), ("weather", "storm"))


class TestImpactTagBoost(unittest.TestCase):
    def test_mobility_tag_raises_priority(self):
        agent = _agent()
        base = generate_environment_interrupts(
            agent, [{"type": "weather", "description": "小雨", "severity": 0.5}]
        )
        boosted = generate_environment_interrupts(
            agent, [{"type": "weather", "description": "小雨", "severity": 0.5, "impact_tags": ["mobility"]}]
        )
        self.assertTrue(base and boosted)
        self.assertGreater(boosted[0].priority, base[0].priority)
        self.assertIn("mobility", boosted[0].extra["impact_tags"])


class TestLocalPhysicalInterrupts(unittest.TestCase):
    def test_packed_location_generates_candidate(self):
        cands = generate_local_physical_interrupts(
            _agent(), {"location": "Mall", "in_transit": False, "crowding": "非常拥挤",
                       "occupancy_ratio": 0.95, "is_open": True}
        )
        kinds = {c.kind for c in cands}
        self.assertIn("crowd_packed", kinds)
        self.assertTrue(all(c.resumable for c in cands if c.kind == "crowd_packed"))

    def test_closed_venue_is_non_resumable(self):
        cands = generate_local_physical_interrupts(
            _agent(), {"location": "Clinic", "in_transit": False, "crowding": "比较空旷",
                       "occupancy_ratio": 0.1, "is_open": False}
        )
        closed = [c for c in cands if c.kind == "venue_closed"]
        self.assertEqual(len(closed), 1)
        self.assertFalse(closed[0].resumable)

    def test_in_transit_and_empty_yield_nothing(self):
        self.assertEqual(generate_local_physical_interrupts(_agent(), {"in_transit": True, "location": "X"}), [])
        self.assertEqual(generate_local_physical_interrupts(_agent(), None), [])
        self.assertEqual(generate_local_physical_interrupts(_agent(), {"location": "", "crowding": "非常拥挤"}), [])

    def test_evaluate_step_dynamics_picks_up_local_physical(self):
        agent = _agent()
        agent["_local_physical"] = {"location": "Office", "in_transit": False,
                                    "crowding": "非常拥挤", "occupancy_ratio": 0.98, "is_open": True}
        result = evaluate_step_dynamics(
            agent, time_str="14:00", scheduled_activity="刷手机",  # low commitment
            env_events=[], all_agents=[agent], agents_by_id={1: agent},
            config={"dynamic_behavior": {"enabled": True}},
        )
        # The candidate must at least be considered in the pipeline.
        self.assertGreaterEqual(result["all_candidates"], 1)


if __name__ == "__main__":
    unittest.main()
