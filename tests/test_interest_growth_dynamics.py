"""Tests for growth-system v2 dynamics: learning curve, decay, phases, evolution."""

import unittest

from gaworld.interests import (
    PHASE_EMERGING,
    PHASE_MAINTAINED,
    PHASE_TRIGGERED,
    PHASE_WELL_DEVELOPED,
    apply_daily_growth_decay,
    evolve_growth_profile,
    growth_phase,
    update_growth_from_episode,
)


def _item(**overrides):
    base = {
        "name": "阅读",
        "kind": "hobby",
        "category": "阅读",
        "motivation": "放松",
        "level": 0.2,
        "priority": 0.8,
        "weekly_target_minutes": 120,
        "preferred_time_blocks": ["evening"],
        "activity_templates": ["阅读", "看书"],
        "career_link": False,
        "sociality": 0.1,
        "last_practiced_day": 0,
        "total_minutes": 0,
        "streak_days": 0,
    }
    base.update(overrides)
    return base


def _profile(*items):
    return {"agent_id": 1, "source_hash": "abc", "items": list(items) or [_item()]}


def _reading_episode(day=1):
    return {"day": day, "final_activity": "晚上阅读", "action": "阅读并做笔记", "reflection": "有收获"}


class _FixedRng:
    def __init__(self, value):
        self.value = value

    def random(self):
        return self.value


class TestLearningCurve(unittest.TestCase):
    def _gain(self, **overrides):
        updated, progress = update_growth_from_episode(
            _profile(_item(**overrides)), _reading_episode(), step_minutes=45
        )
        change = progress["level_changes"].get("阅读")
        self.assertIsNotNone(change)
        return change["after"] - change["before"]

    def test_diminishing_returns_high_level_gains_less(self):
        self.assertGreater(self._gain(level=0.1), self._gain(level=0.8))

    def test_streak_momentum_boosts_gain(self):
        # Same level; the streaked item practiced yesterday keeps momentum.
        no_streak = self._gain(level=0.3)
        streaked = self._gain(level=0.3, streak_days=10, last_practiced_day=0)
        self.assertGreater(streaked, no_streak)

    def test_milestone_emitted_on_threshold_cross(self):
        updated, progress = update_growth_from_episode(
            _profile(_item(level=0.349, priority=1.0)), _reading_episode(), step_minutes=200
        )
        self.assertIn({"name": "阅读", "label": "入门"}, progress["milestones"])

    def test_no_milestone_without_cross(self):
        _, progress = update_growth_from_episode(
            _profile(_item(level=0.2)), _reading_episode(), step_minutes=30
        )
        self.assertEqual([], progress["milestones"])


class TestDailyDecay(unittest.TestCase):
    def test_no_decay_within_grace_period(self):
        payload, changes = apply_daily_growth_decay(
            _profile(_item(level=0.5, last_practiced_day=3)), day=5
        )
        self.assertEqual({}, changes["level_changes"])
        self.assertEqual(0.5, payload["items"][0]["level"])

    def test_decay_after_grace_period(self):
        payload, changes = apply_daily_growth_decay(
            _profile(_item(level=0.5, last_practiced_day=1)), day=10
        )
        self.assertLess(payload["items"][0]["level"], 0.5)
        self.assertIn("阅读", changes["level_changes"])

    def test_accumulated_practice_raises_retention(self):
        fresh, _ = apply_daily_growth_decay(
            _profile(_item(level=0.5, last_practiced_day=1, total_minutes=0)), day=10
        )
        seasoned, _ = apply_daily_growth_decay(
            _profile(_item(level=0.5, last_practiced_day=1, total_minutes=2400)), day=10
        )
        self.assertGreater(seasoned["items"][0]["level"], fresh["items"][0]["level"])

    def test_level_never_drops_below_floor(self):
        payload, _ = apply_daily_growth_decay(
            _profile(_item(level=0.052, last_practiced_day=1)), day=30
        )
        self.assertGreaterEqual(payload["items"][0]["level"], 0.05)

    def test_idle_gap_breaks_streak(self):
        payload, _ = apply_daily_growth_decay(
            _profile(_item(streak_days=7, last_practiced_day=3)), day=5
        )
        self.assertEqual(0, payload["items"][0]["streak_days"])

    def test_disabled_is_noop(self):
        payload, changes = apply_daily_growth_decay(
            _profile(_item(level=0.5, last_practiced_day=1)),
            day=10,
            config={"enabled": False},
        )
        self.assertEqual(0.5, payload["items"][0]["level"])
        self.assertEqual({}, changes["level_changes"])


class TestGrowthPhase(unittest.TestCase):
    def test_phase_boundaries(self):
        self.assertEqual(PHASE_TRIGGERED, growth_phase(_item(level=0.1, total_minutes=0)))
        self.assertEqual(PHASE_MAINTAINED, growth_phase(_item(level=0.1, total_minutes=400)))
        self.assertEqual(PHASE_MAINTAINED, growth_phase(_item(level=0.3)))
        self.assertEqual(PHASE_EMERGING, growth_phase(_item(level=0.5)))
        self.assertEqual(PHASE_WELL_DEVELOPED, growth_phase(_item(level=0.9)))


class TestEvolution(unittest.TestCase):
    def test_stale_triggered_item_is_retired(self):
        stale = _item(name="速写", level=0.1, priority=0.4, last_practiced_day=1)
        keeper = _item(name="编程技能", kind="skill", level=0.6, last_practiced_day=19)
        payload, changes = evolve_growth_profile(_profile(stale, keeper), day=20)
        self.assertEqual(["速写"], changes["retired"])
        self.assertEqual(["编程技能"], [it["name"] for it in payload["items"]])

    def test_last_item_is_never_retired(self):
        stale = _item(name="速写", level=0.1, priority=0.4, last_practiced_day=1)
        payload, changes = evolve_growth_profile(_profile(stale), day=40)
        self.assertEqual([], changes["retired"])
        self.assertEqual(1, len(payload["items"]))

    def test_adopts_social_candidate(self):
        payload, changes = evolve_growth_profile(
            _profile(_item(last_practiced_day=4)),
            day=5,
            social_candidates=["摄影"],
            rng=_FixedRng(0.0),
        )
        self.assertEqual(["摄影"], changes["adopted"])
        adopted = [it for it in payload["items"] if it["name"] == "摄影"][0]
        self.assertEqual("hobby", adopted["kind"])
        self.assertLess(adopted["level"], 0.25)

    def test_adoption_respects_chance_roll(self):
        _, changes = evolve_growth_profile(
            _profile(_item(last_practiced_day=4)),
            day=5,
            social_candidates=["摄影"],
            rng=_FixedRng(0.99),
        )
        self.assertEqual([], changes["adopted"])

    def test_adoption_caps_and_skips_duplicates(self):
        _, changes = evolve_growth_profile(
            _profile(_item(name="阅读", last_practiced_day=4)),
            day=5,
            social_candidates=["阅读", "摄影", "烘焙"],
            rng=_FixedRng(0.0),
        )
        self.assertEqual(["摄影"], changes["adopted"])

    def test_adoption_respects_max_items(self):
        items = [_item(name=f"兴趣{i}", last_practiced_day=4) for i in range(3)]
        _, changes = evolve_growth_profile(
            _profile(*items),
            day=5,
            social_candidates=["摄影"],
            max_items=3,
            rng=_FixedRng(0.0),
        )
        self.assertEqual([], changes["adopted"])

    def test_disabled_is_noop(self):
        stale = _item(name="速写", level=0.1, priority=0.4, last_practiced_day=1)
        keeper = _item(name="编程技能", kind="skill", level=0.6, last_practiced_day=19)
        payload, changes = evolve_growth_profile(
            _profile(stale, keeper),
            day=20,
            social_candidates=["摄影"],
            config={"enabled": False},
            rng=_FixedRng(0.0),
        )
        self.assertEqual({"retired": [], "adopted": []}, changes)
        self.assertEqual(2, len(payload["items"]))


if __name__ == "__main__":
    unittest.main()
