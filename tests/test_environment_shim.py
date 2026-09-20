"""The root ``environment`` module is a shim, not a second implementation.

It used to be a *copy*: 705 lines duplicating the 836 in
``gaworld/env/system.py``. The two drifted in both directions — the root copy
grew a ``_safe_float`` hardening pass the package lacked, the package grew the
``_annotate_anomaly`` pass the root lacked — and because the simulator
imported the root copy, ``event["anomaly"]`` was never set and the
anomaly-aware branch in ``gaworld/behavior/dynamic.py`` was unreachable.

These tests pin the two properties that keep that from coming back: the root
module must re-export rather than redefine, and the anomaly annotation the
merge restored must actually reach events.
"""

from __future__ import annotations

import ast
import os
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHIM_PATH = os.path.join(REPO_ROOT, "environment.py")


class TestRootModuleIsAShim(unittest.TestCase):
    def test_it_re_exports_the_package_classes(self):
        import environment

        from gaworld.env import system

        self.assertIs(environment.EnvironmentSystem, system.EnvironmentSystem)
        self.assertIs(environment.RemoteEnvironmentClient, system.RemoteEnvironmentClient)

    def test_it_defines_no_implementation_of_its_own(self):
        """A redefined class here is a fork that will drift again."""
        with open(SHIM_PATH, encoding="utf-8") as handle:
            tree = ast.parse(handle.read())
        defined = [
            node.name
            for node in tree.body
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        self.assertEqual([], defined, f"{SHIM_PATH} should only re-export, but defines {defined}")


class TestMergedBehaviour(unittest.TestCase):
    """Both sides of the drift survive the merge."""

    def _env(self, **config):
        import environment

        base = {
            "external_environment": {
                "enabled": True,
                "generator_mode": "rules",
                "natural": {
                    "enabled": True,
                    "daily_weather_chance": 1.0,
                    "extreme_chance": 1.0,
                },
            },
            "anomaly": {"enabled": True, "severity_threshold": 0.65},
        }
        base.update(config)
        return environment.EnvironmentSystem(base)

    def test_events_carry_the_anomaly_annotation(self):
        """Restored from the package side; `behavior/dynamic.py` reads it."""
        events = self._env().start_day(1, day_context={"sim_date": "2026-01-01"})
        self.assertTrue(events)
        for event in events:
            self.assertIn("anomaly", event)
            self.assertIn("anomaly_score", event)
        # Ordinary weather is not an anomaly; the extreme-weather alert is.
        by_topic = {event["topic"]: event for event in events}
        if "weather" in by_topic:
            self.assertFalse(by_topic["weather"]["anomaly"])
        if "extreme" in by_topic:
            self.assertTrue(by_topic["extreme"]["anomaly"])

    def test_config_floats_survive_bad_input(self):
        """Kept from the root side: a list/None/str where a float belongs."""
        import environment

        # `float(["0.5"])` raises; `_safe_float` takes the first element.
        self.assertEqual(0.5, environment._safe_float(["0.5"]))
        self.assertEqual(0.0, environment._safe_float(None))
        self.assertEqual(1.5, environment._safe_float("1.5"))
        self.assertEqual(7.0, environment._safe_float("nope", 7.0))
        # End to end: a chance expressed as a single-element list must not
        # crash day generation.
        env = self._env(
            external_environment={
                "enabled": True,
                "generator_mode": "rules",
                "natural": {"enabled": True, "daily_weather_chance": [1.0],
                            "extreme_chance": [0.0]},
            }
        )
        events = env.start_day(1, day_context={"sim_date": "2026-01-01"})
        self.assertTrue(any(event["topic"] == "weather" for event in events))


if __name__ == "__main__":
    unittest.main()
