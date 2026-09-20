"""Tests for P2: anomalies as first-class signals.

Covers EnvironmentSystem anomaly flagging, reaction-side escalation
(priority boost + non-resumable at high score), and emergent local
crowd-surge detection.
"""

import os
import tempfile
import unittest

from gaworld.behavior.dynamic import (
    generate_environment_interrupts,
    generate_local_physical_interrupts,
)
from gaworld.env.system import EnvironmentSystem
from gaworld.world import city_map as cm
from gaworld.world.local_physical import local_physical_state, update_occupancy_from_agents


def _env(**anomaly_overrides):
    cfg = {"anomaly": {"enabled": True, "severity_threshold": 0.65,
                       "intraday_threshold": 0.45}}
    cfg["anomaly"].update(anomaly_overrides)
    return EnvironmentSystem(cfg)


class TestEnvAnomalyFlag(unittest.TestCase):
    def test_high_severity_is_anomaly(self):
        env = _env()
        events = [env._build_event("natural", "extreme", "雷暴大风预警", "雷暴大风预警", severity=0.72)]
        env._annotate_anomaly(events)
        self.assertTrue(events[0]["anomaly"])
        self.assertGreater(events[0]["anomaly_score"], 0.9)

    def test_routine_weather_is_not_anomaly(self):
        env = _env()
        events = [env._build_event("natural", "weather", "天气：多云", "今日多云", severity=0.2)]
        env._annotate_anomaly(events)
        self.assertFalse(events[0]["anomaly"])
        self.assertEqual(events[0]["anomaly_score"], 0.0)

    def test_intraday_shock_is_anomaly(self):
        env = _env()
        events = [env._build_event("economic", "intraday", "市场波动加剧", "市场波动加剧（14:00）", severity=0.52)]
        env._annotate_anomaly(events)
        self.assertTrue(events[0]["anomaly"])

    def test_disabled_config_marks_nothing(self):
        env = _env(enabled=False)
        events = [env._build_event("natural", "extreme", "x", "x", severity=0.9)]
        env._annotate_anomaly(events)
        self.assertFalse(events[0]["anomaly"])


class TestReactionEscalation(unittest.TestCase):
    def _agent(self):
        return {"id": 1, "name": "t", "personality": "务实", "values": "", "daily_life": "",
                "job": "", "state": {}, "locations": {"current": "X"}}

    def test_anomaly_raises_priority(self):
        agent = self._agent()
        normal = generate_environment_interrupts(
            agent, [{"type": "weather", "topic": "weather", "description": "小雨", "severity": 0.5,
                     "anomaly": False, "anomaly_score": 0.0}]
        )
        anom = generate_environment_interrupts(
            agent, [{"type": "weather", "topic": "weather", "description": "小雨", "severity": 0.5,
                     "anomaly": True, "anomaly_score": 0.6}]
        )
        self.assertGreater(anom[0].priority, normal[0].priority)
        self.assertTrue(anom[0].extra["anomaly"])

    def test_high_score_anomaly_is_non_resumable(self):
        agent = self._agent()
        cands = generate_environment_interrupts(
            agent, [{"type": "weather", "topic": "weather", "description": "短时强降雨", "severity": 0.7,
                     "anomaly": True, "anomaly_score": 0.95}]
        )
        self.assertFalse(cands[0].resumable)


class TestEmergentCrowdAnomaly(unittest.TestCase):
    def _map(self):
        content = (
            "# City Map\n"
            "@node: Hall | kind=poi | category=leisure | x=1.0 | y=1.0 | capacity=10\n"
            "@node: Annex | kind=poi | category=leisure | x=2.0 | y=1.0 | capacity=10\n"
            "@road: Hall -> Annex | type=local\n\n- City: Demo\n  - Hub: Hall\n  - Hub: Annex\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "m.md")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(content)
            return cm.load_city_map(path)

    def test_crowd_surge_flags_anomaly(self):
        city_map = self._map()
        cap = int(cm.node_by_name(city_map, "Hall")["capacity"])
        agent = {"id": 1, "locations": {"current": "Hall"}}
        # Tick 1: nearly empty.
        update_occupancy_from_agents(city_map, [agent])
        snap1 = local_physical_state(city_map, agent, time_str="12:00")
        self.assertFalse(snap1["anomaly"])
        # Tick 2: a sudden surge to capacity at Hall.
        crowd = [{"id": i, "locations": {"current": "Hall"}} for i in range(cap)]
        update_occupancy_from_agents(city_map, crowd)
        snap2 = local_physical_state(city_map, agent, time_str="12:00")
        self.assertTrue(snap2["anomaly"])
        self.assertEqual(snap2["anomaly_kind"], "crowd_surge")

    def test_anomaly_snapshot_escalates_interrupt(self):
        cands = generate_local_physical_interrupts(
            {"id": 1}, {"location": "Hall", "in_transit": False, "crowding": "非常拥挤",
                        "occupancy_ratio": 1.0, "is_open": True, "anomaly": True,
                        "anomaly_kind": "crowd_surge"}
        )
        anom = [c for c in cands if c.kind == "crowd_anomaly"]
        self.assertEqual(len(anom), 1)
        self.assertFalse(anom[0].resumable)
        self.assertGreater(anom[0].priority, 0.5)


if __name__ == "__main__":
    unittest.main()
