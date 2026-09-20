"""Part B — a serious, routine-impacting life event reshapes the rest of the day.

The pure helper is tested in isolation (no simulator loop): the current slot
becomes the event's immediate response, upcoming high/medium-commitment slots
inside the window are swapped for the follow-on activity, and meals/sleep are
left in place.
"""

import unittest

from gaworld.sim._schedule import (
    is_routine_impacting_event,
    reshape_day_for_life_event,
    resolve_life_event_activities,
)


class TestResolveActivities(unittest.TestCase):
    def test_template_key_wins(self):
        self.assertEqual(
            resolve_life_event_activities({"template_key": "illness"}),
            ("就医处理", "在家休养"),
        )

    def test_falls_back_to_impact_tag(self):
        self.assertEqual(
            resolve_life_event_activities(
                {"template_key": "custom", "impact_tags": ["family"]}
            ),
            ("处理家中急事", "陪伴家人"),
        )

    def test_default_when_unmapped(self):
        self.assertEqual(
            resolve_life_event_activities({"template_key": "custom", "impact_tags": ["misc"]}),
            ("临时处理要务", "跟进后续"),
        )


class TestRoutineImpacting(unittest.TestCase):
    def test_health_event_impacts_routine(self):
        self.assertTrue(is_routine_impacting_event({"impact_tags": ["health", "stress"]}))

    def test_lottery_does_not_impact_routine(self):
        # money/emotion/risk — colours mood, but doesn't pull you out of work
        self.assertFalse(is_routine_impacting_event({"impact_tags": ["money", "emotion", "risk"]}))


class TestReshapeDay(unittest.TestCase):
    def _day(self):
        return [
            ("08:00", "吃早饭"),
            ("10:00", "上午工作"),
            ("12:00", "午饭"),
            ("14:00", "下午工作"),
            ("18:30", "下班"),
            ("23:30", "睡前"),
        ]

    def test_illness_at_10_reshapes_workday(self):
        event = {"template_key": "illness", "impact_tags": ["health"], "severity": 0.7}
        new_sched, changes = reshape_day_for_life_event(
            self._day(), "10:00", event, window_minutes=240
        )
        as_map = dict(new_sched)
        # current slot overridden to the immediate response
        self.assertEqual(as_map["10:00"], "就医处理")
        # a high-commitment slot inside the window (12:00 lunch is low-commit,
        # 14:00 work at +240min boundary) — 14:00 is exactly cur+240 = end, so
        # it's NOT inside the half-open window; assert the lunch stayed put.
        self.assertEqual(as_map["12:00"], "午饭")
        # meals and sleep untouched
        self.assertEqual(as_map["08:00"], "吃早饭")
        self.assertEqual(as_map["23:30"], "睡前")
        self.assertTrue(any(c["kind"] == "override" for c in changes))

    def test_relocates_high_commitment_inside_window(self):
        event = {"template_key": "family_emergency", "impact_tags": ["family"], "severity": 0.8}
        # window 300 min from 10:00 covers 12:00 and 14:00
        new_sched, changes = reshape_day_for_life_event(
            self._day(), "10:00", event, window_minutes=300
        )
        as_map = dict(new_sched)
        self.assertEqual(as_map["10:00"], "处理家中急事")
        self.assertEqual(as_map["14:00"], "陪伴家人")  # high-commitment work swapped
        self.assertEqual(as_map["12:00"], "午饭")       # low-commitment meal kept
        self.assertTrue(any(c["kind"] == "relocate" for c in changes))

    def test_inserts_block_when_no_slot_at_time(self):
        event = {"template_key": "illness", "impact_tags": ["health"], "severity": 0.75}
        new_sched, changes = reshape_day_for_life_event(
            self._day(), "10:45", event, window_minutes=120
        )
        as_map = dict(new_sched)
        self.assertEqual(as_map["10:45"], "就医处理")
        self.assertTrue(any(c["kind"] == "insert" for c in changes))
        # times stay sorted and unique
        times = [t for t, _ in new_sched]
        self.assertEqual(times, sorted(times))
        self.assertEqual(len(times), len(set(times)))


if __name__ == "__main__":
    unittest.main()
