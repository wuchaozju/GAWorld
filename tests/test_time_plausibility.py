"""Time plausibility: activities and actions have to match the clock.

The feature has three integration points, and each of them gets its own
test here:

* the schedule repair (``build_schedule_map``) moves an item whose hour
  contradicts its activity;
* the action picker (``choose_action``) de-weights an action that makes no
  sense right now, while leaving a plausible one alone;
* the routine-change gate (``maybe_adjust_activity``) refuses a new activity
  that contradicts the hour.

The randomness is bounded, not removed: a plausible deviation (a jog at
dawn) survives, an implausible one is very unlikely rather than impossible.
"""

from __future__ import annotations

import random
import unittest
from unittest import mock

from gaworld.settings import CONFIG
from gaworld.sim import _timefit
from gaworld.sim._schedule import build_schedule_map
from gaworld.sim._utils import _time_str_to_minutes


def _minutes(hhmm: str) -> int:
    value = _time_str_to_minutes(hhmm)
    assert value is not None
    return value


class TestVerdicts(unittest.TestCase):
    def test_work_wrap_up_is_absurd_at_dawn_and_fine_at_night(self):
        # The complaint that started this: a work wrap-up in the early morning.
        action = "收尾今天的工作，整理明日计划"
        self.assertEqual(_timefit.action_time_fit(action, _minutes("06:00"))[0], _timefit.BAD)
        self.assertEqual(_timefit.action_time_fit(action, _minutes("18:30"))[0], _timefit.OK)

    def test_a_jog_at_dawn_is_allowed(self):
        action = "沿着小区跑道跑两公里"
        self.assertEqual(_timefit.action_time_fit(action, _minutes("05:40"))[0], _timefit.OK)
        self.assertEqual(_timefit.action_time_fit(action, _minutes("03:10"))[0], _timefit.BAD)

    def test_work_lunch_is_not_a_breakfast(self):
        activity = "在托管班食堂和搭班们一起吃工作餐"
        self.assertEqual(_timefit.activity_time_fit(activity, _minutes("08:32"))[0], _timefit.BAD)
        self.assertEqual(_timefit.activity_time_fit(activity, _minutes("11:40"))[0], _timefit.OK)

    def test_text_we_cannot_judge_is_left_alone(self):
        verdict, _reason = _timefit.action_time_fit("在社交平台刷到一条吐槽帖子", _minutes("23:40"))
        self.assertEqual(verdict, _timefit.UNKNOWN)

    def test_the_most_specific_keyword_wins(self):
        # "工作餐" is a lunch, not a work session.
        verdict, reason = _timefit.activity_time_fit("吃工作餐", _minutes("12:00"))
        self.assertEqual(verdict, _timefit.OK)
        self.assertIn("工作餐", reason)

    def test_work_phrases_that_merely_contain_run_are_not_runs(self):
        verdict, _reason = _timefit.action_time_fit("把今天的数据跑一遍", _minutes("09:00"))
        self.assertEqual(verdict, _timefit.UNKNOWN)

    def test_day_part_names_the_hour(self):
        self.assertEqual(_timefit.day_part(_minutes("05:30")), "清晨")
        self.assertEqual(_timefit.day_part(_minutes("13:00")), "中午")
        self.assertEqual(_timefit.day_part(None), "未知时段")


class TestScheduleRepair(unittest.TestCase):
    def test_an_item_is_moved_into_the_window_of_its_activity(self):
        schedule = [
            ("06:00", "起床洗漱"),
            ("08:32", "在托管班食堂和搭班们一起吃工作餐"),
            ("12:00", "午饭"),
            ("22:30", "睡前"),
        ]
        repaired, changes = _timefit.repair_schedule(schedule)
        times = dict(repaired)
        self.assertNotIn("08:32", times)
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]["from"], "08:32")
        self.assertEqual(len(repaired), len(schedule))

    def test_a_plausible_schedule_is_left_alone(self):
        schedule = [
            ("07:00", "吃早饭"),
            ("09:00", "通勤"),
            ("10:00", "上午工作"),
            ("12:00", "午饭"),
            ("18:30", "下班"),
            ("22:30", "睡前"),
        ]
        repaired, changes = _timefit.repair_schedule(schedule)
        self.assertEqual(repaired, schedule)
        self.assertEqual(changes, [])

    def test_the_move_stays_local(self):
        # 03:00 "上班" is 4.5 hours away from the window: too far to move,
        # so the item stays where it is rather than teleporting.
        schedule = [("03:00", "上班"), ("12:00", "午饭")]
        repaired, changes = _timefit.repair_schedule(schedule)
        self.assertIn(("03:00", "上班"), repaired)
        self.assertEqual(changes, [])

    def test_a_night_shift_schedule_is_not_dragged_into_the_day(self):
        schedule = [("22:00", "上班"), ("23:30", "上班"), ("03:00", "夜班")]
        repaired, _changes = _timefit.repair_schedule(schedule)
        self.assertIn(("22:00", "上班"), repaired)

    def test_an_item_with_an_unreadable_time_is_kept_as_is(self):
        schedule = [("08:00", "吃工作餐"), ("乱写的", "自由活动")]
        repaired, _changes = _timefit.repair_schedule(schedule)
        self.assertIn(("乱写的", "自由活动"), repaired)

    def test_repair_can_be_switched_off(self):
        schedule = [("03:00", "上班")]
        with mock.patch.dict(CONFIG, {"time_plausibility": {"enabled": False}}):
            repaired, changes = _timefit.repair_schedule(schedule)
        self.assertEqual(repaired, schedule)
        self.assertEqual(changes, [])

    def test_build_schedule_map_repairs_every_resident(self):
        schedules = {7: [("08:00", "吃工作餐"), ("12:00", "午饭")]}
        built = build_schedule_map(schedules)
        self.assertEqual(len(built[7]), 2)
        self.assertEqual(built[7][0][0], "10:30")


class TestActionGate(unittest.TestCase):
    """The gate lives inside ``choose_action``; test it through the picker."""

    def _agent(self) -> dict:
        return {
            "id": 1,
            "name": "测试居民",
            "state": {
                "emotion": 0.6,
                "stress": 0.3,
                "econ_security": 0.5,
                "risk_preference": 0.5,
                "fatigue_debt": 0.2,
                "self_control": 0.6,
                "time_pressure": 0.2,
                "energy": 0.8,
                "hunger": 0.2,
                "social_need": 0.4,
            },
        }

    def _pick(self, action_space, activity, time_str, trials=400):
        from gaworld.sim._action import choose_action

        agent = self._agent()
        picks = []
        for _ in range(trials):
            picks.append(choose_action(agent, activity, action_space, time_str=time_str))
        return picks

    def _weights(self, action_space, activity, time_str):
        from gaworld.sim._action import choose_action

        _choice, debug = choose_action(
            self._agent(),
            activity,
            action_space,
            time_str=time_str,
            return_debug=True,
        )
        return {act: entry["components"] for act, entry in debug["scores"].items()}

    def test_an_odd_hour_action_is_heavily_de_weighted_but_kept(self):
        space = {"上午工作": ["收尾今天的工作，整理明日计划", "继续跟进手上的项目"]}
        components = self._weights(space, "上午工作", "06:00")
        penalty = components["收尾今天的工作，整理明日计划"].get("time_fit")
        self.assertIsNotNone(penalty, components)
        self.assertLess(penalty, 0.0, components)
        self.assertNotIn("time_fit", components["继续跟进手上的项目"], components)

    def test_the_same_action_is_not_penalised_at_the_end_of_the_day(self):
        space = {"上午工作": ["收尾今天的工作，整理明日计划", "继续跟进手上的项目"]}
        components = self._weights(space, "上午工作", "18:30")
        self.assertNotIn("time_fit", components["收尾今天的工作，整理明日计划"], components)

    def test_a_plausible_action_is_untouched(self):
        space = {"晨练": ["沿着小区跑道跑两公里", "在楼下拉伸"]}
        components = self._weights(space, "晨练", "06:00")
        self.assertNotIn("time_fit", components["沿着小区跑道跑两公里"], components)

    def test_the_gate_can_be_switched_off(self):
        space = {"上午工作": ["收尾今天的工作，整理明日计划", "继续跟进手上的项目"]}
        with mock.patch.dict(CONFIG, {"time_plausibility": {"gate_actions": False}}):
            components = self._weights(space, "上午工作", "06:00")
        self.assertNotIn("time_fit", components["收尾今天的工作，整理明日计划"], components)


class TestRoutineChangeGate(unittest.TestCase):
    def _agent(self) -> dict:
        return {
            "id": 1,
            "name": "测试居民",
            "job": "小学教师",
            "state": {"self_control": 0.6, "stress": 0.3},
        }

    def _adjust(self, time_str, response):
        from gaworld.sim import _step

        # Force the change branch: the trigger has to beat the commitment
        # resistance of the scheduled activity, which is what makes a
        # routine change rare in the first place.
        with (
            mock.patch.object(_step, "_routine_change_trigger_strength", return_value=1.0),
            mock.patch.object(_step, "_routine_change_resistance", return_value=("medium", 0.0)),
            mock.patch.object(_step.random, "random", return_value=0.0),
            mock.patch.object(_step._llm_providers, "call_llm", return_value=response),
        ):
            return _step.maybe_adjust_activity(
                self._agent(),
                time_str,
                "上午工作",
                "感知",
                "计划",
                "",
                [],
                "",
            )

    def test_a_change_that_contradicts_the_clock_is_refused(self):
        with mock.patch.dict(CONFIG, {"time_plausibility": {"deviation_chance": 0.0}}):
            activity, reason, changed = self._adjust(
                "06:00", '{"change": true, "activity": "收尾今天的工作", "reason": "想早点把事做完"}'
            )
        self.assertFalse(changed)
        self.assertEqual(activity, "上午工作")
        self.assertIn("时段不合适", reason)

    def test_a_change_that_fits_the_clock_is_taken(self):
        activity, _reason, changed = self._adjust(
            "06:00", '{"change": true, "activity": "晨跑", "reason": "睡够了"}'
        )
        self.assertTrue(changed)
        self.assertEqual(activity, "晨跑")

    def test_the_refusal_is_not_absolute(self):
        # Bounded randomness: with the dice rolled high, the odd hour stands.
        with mock.patch.dict(CONFIG, {"time_plausibility": {"deviation_chance": 1.0}}):
            activity, _reason, changed = self._adjust(
                "06:00", '{"change": true, "activity": "收尾今天的工作", "reason": "想早点把事做完"}'
            )
        self.assertTrue(changed)
        self.assertEqual(activity, "收尾今天的工作")

    def test_the_gate_can_be_switched_off(self):
        with mock.patch.dict(CONFIG, {"time_plausibility": {"gate_activity_changes": False}}):
            _activity, _reason, changed = self._adjust(
                "06:00", '{"change": true, "activity": "收尾今天的工作", "reason": "想早点把事做完"}'
            )
        self.assertTrue(changed)


class TestDeviationDice(unittest.TestCase):
    def test_soft_and_unknown_verdicts_always_survive(self):
        self.assertTrue(_timefit.should_keep_deviation(_timefit.SOFT))
        self.assertTrue(_timefit.should_keep_deviation(_timefit.UNKNOWN))
        self.assertTrue(_timefit.should_keep_deviation(_timefit.OK))

    def test_a_bad_verdict_survives_only_rarely(self):
        with mock.patch.dict(CONFIG, {"time_plausibility": {"deviation_chance": 0.04}}):
            rolls = [_timefit.should_keep_deviation(_timefit.BAD) for _ in range(2000)]
        share = sum(1 for value in rolls if value) / len(rolls)
        self.assertLess(share, 0.12, share)

    def test_the_dice_is_not_biased_by_the_caller(self):
        random.seed(7)
        first = [_timefit.should_keep_deviation(_timefit.BAD) for _ in range(50)]
        random.seed(7)
        second = [_timefit.should_keep_deviation(_timefit.BAD) for _ in range(50)]
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
