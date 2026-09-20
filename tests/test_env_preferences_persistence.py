"""Tests for P4 persistence: env_preferences survive a save/load round-trip."""

import os
import tempfile
import unittest

from gaworld.memory.experience import (
    load_agent_env_preferences,
    save_agent_env_preferences,
)
from gaworld.memory.spatial_preferences import location_aversion, record_anomaly_experience


class TestEnvPreferencePersistence(unittest.TestCase):
    def test_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = {"memory_dir": tmp}
            agent = {"id": 42}
            record_anomaly_experience(agent, location="Mall", day=3, weight=1.0,
                                      reason="crowd_anomaly", time_str="12:00")
            save_agent_env_preferences(42, agent["env_preferences"], cfg=cfg)

            self.assertTrue(os.path.exists(os.path.join(tmp, "agent_42_env_preferences.json")))

            reloaded = load_agent_env_preferences(42, cfg=cfg)
            # A fresh agent rehydrated from disk keeps the learned aversion.
            agent2 = {"id": 42, "env_preferences": reloaded}
            self.assertGreaterEqual(location_aversion(agent2, "Mall"), 1.0)
            self.assertEqual(reloaded["avoid"]["Mall"]["count"], 1)

    def test_missing_file_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(load_agent_env_preferences(999, cfg={"memory_dir": tmp}), {})

    def test_save_rejects_non_dict(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = {"memory_dir": tmp}
            save_agent_env_preferences(7, None, cfg=cfg)  # type: ignore[arg-type]
            self.assertEqual(load_agent_env_preferences(7, cfg=cfg), {})


if __name__ == "__main__":
    unittest.main()
