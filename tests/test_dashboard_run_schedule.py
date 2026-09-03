"""定时运行: arm a timer that starts the simulation at a chosen wall clock.

The scheduling lives on the server rather than in the page, so the run still
happens after the browser tab is closed. What that buys has to be pinned down:

* the requested time is a local wall clock and must lie in the future,
* the config captured at scheduling time is what the run actually starts with,
* re-scheduling replaces the pending timer instead of stacking a second one, and
* a timer that fires but cannot start the run parks its error where
  ``/api/run/status`` shows it, since nobody is waiting on that call.
"""

from __future__ import annotations

import datetime
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from gaworld.apps import dashboard_server as ds


def _in(seconds):
    # isoformat, not strftime: the sub-second offsets the firing tests use would
    # be truncated away into the past.
    return (datetime.datetime.now() + datetime.timedelta(seconds=seconds)).isoformat()


class ScheduleSimulationTest(unittest.TestCase):
    def setUp(self):
        self.started = []
        original_start = ds._start_simulation
        ds._start_simulation = lambda payload: self.started.append(payload)
        self.addCleanup(lambda: setattr(ds, "_start_simulation", original_start))
        self.addCleanup(ds._cancel_scheduled_simulation)

    def test_status_reports_a_pending_schedule(self):
        status = ds._schedule_simulation({"at": _in(3600)})
        self.assertTrue(status["scheduled_at"], "the armed time comes back in status")
        self.assertIsNone(status["schedule_error"])
        self.assertEqual(status["scheduled_at"], ds._run_status()["scheduled_at"])

    def test_a_past_time_is_rejected(self):
        with self.assertRaises(ValueError):
            ds._schedule_simulation({"at": _in(-60)})
        self.assertIsNone(ds._run_status()["scheduled_at"])

    def test_an_unparseable_time_is_rejected(self):
        for value in ("", "tomorrow", "2026-13-40T99:99"):
            with self.assertRaises(ValueError):
                ds._schedule_simulation({"at": value})

    def test_cancelling_clears_the_schedule(self):
        ds._schedule_simulation({"at": _in(3600)})
        status = ds._cancel_scheduled_simulation()
        self.assertIsNone(status["scheduled_at"])

    def test_rescheduling_replaces_the_pending_timer(self):
        ds._schedule_simulation({"at": _in(3600)})
        first = ds.RUN_STATE["schedule"]["timer"]
        second_at = ds._schedule_simulation({"at": _in(7200)})["scheduled_at"]
        self.assertTrue(first.finished.is_set(),
                        "the replaced timer must be cancelled, not left armed")
        self.assertEqual(second_at, ds._run_status()["scheduled_at"])

    def test_firing_starts_the_run_with_the_captured_config(self):
        config = {"agent_ids": "1,2", "seconds_per_day": 5}
        ds._schedule_simulation({"at": _in(0.2), "reset": True, "config": config})
        deadline = time.time() + 5
        while not self.started and time.time() < deadline:
            time.sleep(0.02)
        self.assertEqual([{"reset": True, "config": config}], self.started)
        status = ds._run_status()
        self.assertIsNone(status["scheduled_at"], "a spent schedule stops being pending")
        self.assertIsNone(status["schedule_error"])

    def test_a_failed_start_surfaces_in_status(self):
        def boom(payload):
            raise RuntimeError("Simulation is already running")

        ds._start_simulation = boom
        ds._schedule_simulation({"at": _in(0.2)})
        deadline = time.time() + 5
        while ds._run_status()["schedule_error"] is None and time.time() < deadline:
            time.sleep(0.02)
        status = ds._run_status()
        self.assertEqual("Simulation is already running", status["schedule_error"])
        self.assertIsNone(status["scheduled_at"])


if __name__ == "__main__":
    unittest.main()
