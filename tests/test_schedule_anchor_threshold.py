"""Part D — a looser anchor-match threshold makes the day less template-locked.

``normalize_flexible_schedule`` rejects a re-planned day back to its base when
the candidate doesn't stay near enough of the base's anchors. The required
fraction was hard-coded at 0.45; it is now the configurable
``daily_planning.flexible.min_anchor_match`` (default 0.30), so agents can
deviate further from yesterday's frame without being snapped back.
"""

import unittest
from unittest.mock import patch

from gaworld.sim import _schedule as sched


class TestAnchorThreshold(unittest.TestCase):
    def _base(self):
        return [
            ("07:00", "a"), ("08:00", "b"), ("09:00", "c"), ("10:00", "d"),
            ("11:00", "e"), ("12:00", "f"), ("13:00", "g"), ("14:00", "h"),
        ]

    def _candidate_matching_three(self):
        # keeps 07/08/09 near the base, diverges the rest far beyond max_shift
        return [
            ("07:00", "x"), ("08:00", "y"), ("09:00", "z"),
            ("20:10", "p"), ("21:20", "q"),
        ]

    def test_threshold_flips_acceptance(self):
        base = self._base()
        cand = self._candidate_matching_three()
        # 3 of 8 anchors matched: fails at 0.45 (needs 4), passes at 0.30 (needs 2)
        self.assertFalse(
            sched._has_enough_schedule_anchors(base, cand, max_shift_minutes=30, min_ratio=0.45)
        )
        self.assertTrue(
            sched._has_enough_schedule_anchors(base, cand, max_shift_minutes=30, min_ratio=0.30)
        )

    def test_default_ratio_preserves_legacy(self):
        # default arg stays at the historical 0.45
        base = self._base()
        cand = self._candidate_matching_three()
        self.assertFalse(
            sched._has_enough_schedule_anchors(base, cand, max_shift_minutes=30)
        )


class TestNormalizeHonorsConfig(unittest.TestCase):
    def _flex_config(self, min_anchor_match):
        return {
            "daily_planning": {
                "flexible": {
                    "enabled": True,
                    "min_items": 5,
                    "max_items": 12,
                    "max_time_shift_minutes": 30,
                    "min_gap_minutes": 15,
                    "allow_insertions": True,
                    "min_anchor_match": min_anchor_match,
                }
            }
        }

    def _base(self):
        return [
            ("07:00", "a"), ("08:00", "b"), ("09:00", "c"), ("10:00", "d"),
            ("11:00", "e"), ("12:00", "f"), ("13:00", "g"), ("14:00", "h"),
            ("23:00", "睡觉"),
        ]

    def _candidate(self):
        return [
            ("07:00", "x"), ("08:00", "y"), ("09:00", "z"),
            ("20:10", "p"), ("21:20", "q"),
        ]

    def test_low_threshold_accepts_divergent_day(self):
        with patch.dict(sched.CONFIG, self._flex_config(0.30), clear=False):
            result = sched.normalize_flexible_schedule(self._base(), self._candidate())
        self.assertIsNotNone(result)

    def test_high_threshold_rejects_divergent_day(self):
        with patch.dict(sched.CONFIG, self._flex_config(0.45), clear=False):
            result = sched.normalize_flexible_schedule(self._base(), self._candidate())
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
