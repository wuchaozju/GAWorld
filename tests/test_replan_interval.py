"""Tests for P3: same-day replanning of the affected interval."""

import unittest

from gaworld.sim._schedule import replan_affected_interval


def _times(schedule):
    return [t for t, _ in schedule]


class TestReplanAffectedInterval(unittest.TestCase):
    def setUp(self):
        self.schedule = [
            ("08:00", "通勤上班"),
            ("09:00", "工作"),
            ("12:00", "午饭"),
            ("13:00", "工作"),
            ("18:00", "通勤回家"),
        ]

    def test_defer_disrupted_activity_in_window(self):
        # An anomaly at 09:00 disrupts "工作" for the next 2 hours.
        new_sched, changes = replan_affected_interval(
            self.schedule, "09:00", "11:00",
            is_affected=lambda t, a: a == "工作",
            defer=True, defer_gap_minutes=30,
        )
        # The 09:00 工作 slot is removed from the window and re-placed at/after 11:00.
        self.assertNotIn(("09:00", "工作"), new_sched)
        deferred = [(t, a) for t, a in new_sched if a == "工作" and t >= "11:00"]
        self.assertTrue(deferred)
        # 13:00 工作 is outside the window -> untouched.
        self.assertIn(("13:00", "工作"), new_sched)
        # Unaffected slots are preserved.
        self.assertIn(("12:00", "午饭"), new_sched)
        self.assertIn(("18:00", "通勤回家"), new_sched)
        self.assertEqual([c["kind"] for c in changes], ["defer"])
        self.assertEqual(changes[0]["to"], deferred[0][0])

    def test_relocate_in_place(self):
        new_sched, changes = replan_affected_interval(
            self.schedule, "09:00", "11:00",
            is_affected=lambda t, a: a == "工作",
            relocate=lambda t, a: "在家办公",
        )
        self.assertIn(("09:00", "在家办公"), new_sched)
        self.assertEqual(changes[0]["kind"], "relocate")
        self.assertEqual(changes[0]["to"], "在家办公")

    def test_schedule_stays_sorted_and_unique(self):
        new_sched, _ = replan_affected_interval(
            self.schedule, "09:00", "14:00",
            is_affected=lambda t, a: a == "工作",
        )
        times = _times(new_sched)
        self.assertEqual(times, sorted(times))
        self.assertEqual(len(times), len(set(times)))

    def test_no_op_when_nothing_affected(self):
        new_sched, changes = replan_affected_interval(
            self.schedule, "09:00", "11:00",
            is_affected=lambda t, a: a == "不存在的活动",
        )
        self.assertEqual(new_sched, self.schedule)
        self.assertEqual(changes, [])

    def test_invalid_window_is_noop(self):
        new_sched, changes = replan_affected_interval(
            self.schedule, "11:00", "09:00",  # end <= start
            is_affected=lambda t, a: True,
        )
        self.assertEqual(new_sched, self.schedule)
        self.assertEqual(changes, [])

    def test_deferred_avoids_time_collision(self):
        sched = [("09:00", "工作"), ("11:00", "会议"), ("11:30", "会议2")]
        new_sched, _changes = replan_affected_interval(
            sched, "09:00", "11:00",
            is_affected=lambda t, a: a == "工作",
            defer=True, defer_gap_minutes=30,
        )
        # 11:00 is taken by 会议 -> deferred 工作 must land on a free slot.
        work_slots = [t for t, a in new_sched if a == "工作"]
        self.assertEqual(len(work_slots), 1)
        self.assertNotIn(work_slots[0], {"11:00", "11:30"})


if __name__ == "__main__":
    unittest.main()
