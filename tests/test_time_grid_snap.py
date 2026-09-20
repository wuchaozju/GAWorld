"""Phase 0: schedule/grid alignment keeps the master timeline O(1) in agents.

The simulator's master timeline is the *union* of a fixed time grid and every
agent's LLM-authored schedule times. Because the LLM emits arbitrary ``HH:MM``
values, that union grows with the population, so total LLM cost grows
super-linearly in the agent count even when ``time_step_minutes`` is set.

``snap_schedule_to_grid`` pins each schedule onto the grid so the union
collapses back to the grid itself. These tests lock in both the helper's
semantics and the invariance property that motivates it.
"""

from __future__ import annotations

import os
import random
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from gaworld.sim._utils import (
    _build_time_grid,
    _minutes_to_time_str,
    _snap_time_to_grid,
    _time_str_to_minutes,
    snap_schedule_to_grid,
)


def _build_master_timeline(schedules, step_minutes=None):
    """Mirror of ``generative_city_sim.build_master_timeline``.

    Duplicated here so the test does not have to import the 235k-line
    simulator module (which runs config/LLM setup at import time).
    ``test_build_master_timeline_mirror_matches_simulator`` guards the copy
    against drift.
    """
    if step_minutes:
        times = set(_build_time_grid(step_minutes))
        for sch in schedules.values():
            times.update(t for t, _ in sch)
        return sorted(times)
    times = set()
    for sch in schedules.values():
        times.update(t for t, _ in sch)
    return sorted(times)


def _random_schedule(rng: random.Random, slots: int = 12) -> list[tuple[str, str]]:
    """A plausible LLM-authored schedule: arbitrary minute-resolution times."""
    minutes = sorted(rng.sample(range(24 * 60), slots))
    return [(_minutes_to_time_str(m), f"activity_{i}") for i, m in enumerate(minutes)]


class SnapTimeToGridTests(unittest.TestCase):
    def test_rounds_to_nearest_grid_point(self):
        self.assertEqual("08:00", _snap_time_to_grid("08:05", 30))
        self.assertEqual("08:30", _snap_time_to_grid("08:20", 30))
        self.assertEqual("08:30", _snap_time_to_grid("08:15", 30))  # .5 rounds up
        self.assertEqual("09:00", _snap_time_to_grid("08:55", 30))

    def test_already_on_grid_is_unchanged(self):
        for time_str in _build_time_grid(30):
            self.assertEqual(time_str, _snap_time_to_grid(time_str, 30))

    def test_late_times_clamp_instead_of_wrapping_past_midnight(self):
        # 23:50 rounds to 24:00, which would wrap to 00:00 and silently move a
        # late-night activity to the very start of the day.
        self.assertEqual("23:30", _snap_time_to_grid("23:50", 30))
        self.assertEqual("23:00", _snap_time_to_grid("23:59", 60))

    def test_unparseable_time_returns_none(self):
        self.assertIsNone(_snap_time_to_grid("not a time", 30))
        self.assertIsNone(_snap_time_to_grid("8:5", 30))

    def test_result_is_always_on_the_grid(self):
        rng = random.Random(7)
        for step in (15, 30, 60, 120):
            grid = set(_build_time_grid(step))
            for _ in range(500):
                time_str = _minutes_to_time_str(rng.randrange(0, 24 * 60))
                self.assertIn(_snap_time_to_grid(time_str, step), grid)


class SnapScheduleToGridTests(unittest.TestCase):
    def test_all_slots_land_on_the_grid(self):
        grid = set(_build_time_grid(30))
        schedule = [("07:12", "起床"), ("08:47", "通勤"), ("12:05", "午饭"), ("22:41", "休息")]
        for time_str, _ in snap_schedule_to_grid(schedule, 30):
            self.assertIn(time_str, grid)

    def test_output_is_sorted_by_time(self):
        schedule = [("22:41", "休息"), ("07:12", "起床"), ("12:05", "午饭")]
        snapped = snap_schedule_to_grid(schedule, 30)
        minutes = [_time_str_to_minutes(t) for t, _ in snapped]
        self.assertEqual(sorted(minutes), minutes)

    def test_colliding_slots_keep_the_later_activity(self):
        # Both snap to 08:00; last write wins, matching apply_schedule_override.
        snapped = snap_schedule_to_grid([("07:50", "早餐"), ("08:10", "通勤")], 60)
        self.assertEqual([("08:00", "通勤")], snapped)

    def test_unparseable_slots_are_dropped(self):
        snapped = snap_schedule_to_grid([("07:12", "起床"), ("later", "通勤")], 30)
        self.assertEqual([("07:00", "起床")], snapped)

    def test_no_step_returns_schedule_unchanged(self):
        schedule = [("07:12", "起床"), ("08:47", "通勤")]
        self.assertEqual(schedule, snap_schedule_to_grid(schedule, 0))
        self.assertEqual([], snap_schedule_to_grid([], 30))

    def test_is_idempotent(self):
        schedule = [("07:12", "起床"), ("08:47", "通勤"), ("22:41", "休息")]
        once = snap_schedule_to_grid(schedule, 30)
        self.assertEqual(once, snap_schedule_to_grid(once, 30))


class MasterTimelineInvarianceTests(unittest.TestCase):
    """The acceptance criterion for Phase 0."""

    STEP = 30

    def _timeline_for(self, n_agents: int, *, snap: bool) -> list[str]:
        rng = random.Random(1234 + n_agents)
        schedules = {}
        for agent_id in range(n_agents):
            sch = _random_schedule(rng)
            schedules[agent_id] = snap_schedule_to_grid(sch, self.STEP) if snap else sch
        return _build_master_timeline(schedules, self.STEP)

    def test_snapped_tick_count_is_constant_across_population_sizes(self):
        expected = 24 * 60 // self.STEP
        for n_agents in (5, 20, 50, 100):
            timeline = self._timeline_for(n_agents, snap=True)
            self.assertEqual(
                expected,
                len(timeline),
                f"N={n_agents} produced {len(timeline)} ticks, expected {expected}",
            )
            self.assertEqual(_build_time_grid(self.STEP), timeline)

    def test_unsnapped_tick_count_grows_with_population(self):
        # Documents the bug this phase fixes: merely setting time_step_minutes
        # is NOT enough, because the grid is unioned with schedule times.
        small = len(self._timeline_for(5, snap=False))
        large = len(self._timeline_for(100, snap=False))
        self.assertGreater(small, 24 * 60 // self.STEP)
        self.assertGreater(large, small * 2)

    def test_build_master_timeline_mirror_matches_simulator(self):
        """Guard the local mirror against drift in the simulator source."""
        import re

        root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        with open(os.path.join(root, "generative_city_sim.py"), encoding="utf-8") as fh:
            source = fh.read()
        match = re.search(
            r"\ndef build_master_timeline\(schedules, step_minutes=None\):\n(.*?)\n\ndef ",
            source,
            re.DOTALL,
        )
        self.assertIsNotNone(match, "build_master_timeline not found in simulator")
        body = match.group(1)
        # The mirror must implement the same grid-union semantics.
        self.assertIn("_build_time_grid(step_minutes)", body)
        self.assertIn("times.update(t for t, _ in sch)", body)


class ConfigWiringTests(unittest.TestCase):
    def test_time_grid_snap_defaults_to_off(self):
        from gaworld import config as gconfig
        from gaworld.settings.runtime import simulation_settings

        raw = simulation_settings()
        self.assertIn("time_grid_snap", raw)
        self.assertFalse(raw["time_grid_snap"])
        self.assertFalse(gconfig.from_legacy(raw).time_grid_snap)

    def test_time_grid_snap_parses_from_config(self):
        from gaworld import config as gconfig
        from gaworld.settings.runtime import simulation_settings

        raw = simulation_settings()
        raw["time_grid_snap"] = True
        raw["time_step_minutes"] = "30 minutes"
        cfg = gconfig.from_legacy(raw)
        self.assertTrue(cfg.time_grid_snap)
        self.assertEqual(30, cfg.time_step_minutes)


if __name__ == "__main__":
    unittest.main()
