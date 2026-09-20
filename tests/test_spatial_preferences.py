"""Tests for P4: structured spatial learning from anomalies."""

import os
import tempfile
import unittest

from gaworld.memory.spatial_preferences import (
    decay_preferences,
    location_aversion,
    record_anomaly_experience,
    redirect_for_aversion,
    time_bucket,
)
from gaworld.world import city_map as cm


class TestRecordAndQuery(unittest.TestCase):
    def test_record_accumulates_score(self):
        agent = {"id": 1}
        record_anomaly_experience(agent, location="Mall", day=1, weight=1.0, reason="crowd_anomaly", time_str="12:30")
        record_anomaly_experience(agent, location="Mall", day=1, weight=1.0, reason="crowd_anomaly", time_str="12:45")
        self.assertEqual(agent["env_preferences"]["avoid"]["Mall"]["count"], 2)
        self.assertGreaterEqual(location_aversion(agent, "Mall"), 2.0)

    def test_time_bucket_weighting(self):
        agent = {"id": 1}
        record_anomaly_experience(agent, location="Mall", day=1, weight=2.0, time_str="12:00")  # noon
        noon = location_aversion(agent, "Mall", "12:30")
        night = location_aversion(agent, "Mall", "23:30")
        self.assertGreater(noon, night)

    def test_unknown_location_zero(self):
        self.assertEqual(location_aversion({"id": 1}, "Nowhere"), 0.0)

    def test_time_bucket_labels(self):
        self.assertEqual(time_bucket("08:00"), "morning")
        self.assertEqual(time_bucket("12:30"), "noon")
        self.assertEqual(time_bucket("23:30"), "night")
        self.assertEqual(time_bucket("bad"), "")


class TestDecay(unittest.TestCase):
    def test_decay_reduces_and_prunes(self):
        agent = {"id": 1}
        record_anomaly_experience(agent, location="Mall", day=1, weight=1.0)
        # One half-life later -> score halves.
        decay_preferences(agent, current_day=8, half_life_days=7.0)
        self.assertAlmostEqual(location_aversion(agent, "Mall"), 0.5, places=2)
        # Far in the future -> pruned away entirely.
        decay_preferences(agent, current_day=200, half_life_days=7.0)
        self.assertEqual(location_aversion(agent, "Mall"), 0.0)


class TestRedirect(unittest.TestCase):
    def _map(self):
        content = (
            "# City Map\n"
            "@node: Cafe A | kind=poi | category=commerce | x=1.0 | y=1.0\n"
            "@node: Cafe B | kind=poi | category=commerce | x=1.4 | y=1.0\n"
            "@node: Home | kind=poi | category=residential | x=5.0 | y=5.0\n"
            "@road: Cafe A -> Cafe B | type=local\n"
            "@road: Cafe B -> Home | type=local\n"
            "\n- City: Demo\n  - Hub: Cafe A\n  - Hub: Cafe B\n  - Hub: Home\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "m.md")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(content)
            return cm.load_city_map(path)

    def test_no_redirect_below_threshold(self):
        city_map = self._map()
        agent = {"id": 1}
        loc, redirected = redirect_for_aversion(agent, city_map, "Cafe A", "10:00", threshold=1.5)
        self.assertEqual(loc, "Cafe A")
        self.assertFalse(redirected)

    def test_redirect_to_less_aversive_same_category(self):
        city_map = self._map()
        agent = {"id": 1}
        # Build strong aversion to Cafe A only.
        for _ in range(3):
            record_anomaly_experience(agent, location="Cafe A", day=1, weight=1.0)
        loc, redirected = redirect_for_aversion(agent, city_map, "Cafe A", "10:00", threshold=1.5)
        self.assertTrue(redirected)
        self.assertEqual(loc, "Cafe B")  # same category, no aversion

    def test_safe_when_map_missing(self):
        loc, redirected = redirect_for_aversion({"id": 1}, None, "Cafe A", "10:00")
        self.assertEqual(loc, "Cafe A")
        self.assertFalse(redirected)


if __name__ == "__main__":
    unittest.main()
