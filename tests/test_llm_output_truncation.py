"""The two ways an ``actions`` response really fails, and the repair for each.

Both were measured, not imagined: the A4 ablation arm captured 848 real
``actions`` completions, and the strict parser returned ``{}`` for 354 of them
(41.7%) -- 318 cut off by the provider's ``max_tokens``, 36 syntactically
broken by ASCII quotes inside Chinese strings. The production consequence was
not a visible error. ``_parse_action_space`` returned ``{}``, the caller
retried with *the same* activity list into the same cap, and the agent spent
the day on generic filler actions.

The fixtures below are shortened versions of real captured responses.
"""

from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from gaworld.cognition.realism import _parse_json_dict
from gaworld.llm.providers import (
    _note_truncated,
    reset_truncation_counts,
    truncation_counts,
)
from gaworld.sim import _action
from gaworld.sim._action import _parse_action_space
from gaworld.sim._schedule import loads_tolerant, repair_inner_quotes

ACTIVITIES = ["工作", "午餐", "下班后", "晚上"]

#: Cut off mid-list, exactly as the provider returns it: no closing bracket for
#: 下班后, no 晚上 at all, no closing brace.
TRUNCATED = """{
  "工作": [
    "打开内网邮件，刷新PR列表确认leader反馈",
    "接到新需求后先在Jira拆工时估算开发量"
  ],
  "午餐": [
    "独自在茶水间微波炉前加热便当"
  ],
  "下班后": [
    "回家路上顺手买第二天的早"""

#: Complete, but the model wrote quoted speech with ASCII quotes.
INNER_QUOTES = """{
  "工作": ["同事提议一起下楼吃时以"来不及"为由拒绝", "回应催稿时先说"我再看看""],
  "午餐": ["扒两口饭继续看屏幕"],
  "下班后": ["路过便利店买关东煮"],
  "晚上": ["躺床上刷招聘App"]
}"""

WELL_FORMED = json.dumps(
    {a: [f"{a}的动作{i}" for i in range(3)] for a in ACTIVITIES},
    ensure_ascii=False,
)


class TestRepairIsIdentityOnValidJson(unittest.TestCase):
    """The safety property the whole fix rests on.

    Checked against the corpus too, not just these cases: on the 494 captured
    responses that already parsed, repaired text gave a byte-identical result
    494/494. If that were not true, a repair that runs behind every parser
    would be a liability rather than a free upgrade.
    """

    def test_valid_json_is_untouched(self):
        for blob in (WELL_FORMED, '{"a": [1, 2]}', '{"a": "b: c, d"}', "[]"):
            self.assertEqual(repair_inner_quotes(blob), blob)

    def test_escaped_quotes_are_preserved_not_doubled(self):
        blob = '{"a": ["\\u5148\\u8bf4\\"\\u597d\\""]}'
        self.assertEqual(repair_inner_quotes(blob), blob)
        self.assertEqual(loads_tolerant(blob), json.loads(blob))

    def test_well_formed_response_parses_the_same_as_before(self):
        parsed = _parse_action_space(WELL_FORMED, ACTIVITIES)
        self.assertEqual(sorted(parsed), sorted(ACTIVITIES))
        self.assertEqual(parsed["工作"], ["工作的动作0", "工作的动作1", "工作的动作2"])


class TestInnerQuotes(unittest.TestCase):
    def test_strict_json_cannot_read_it(self):
        with self.assertRaises(ValueError):
            json.loads(INNER_QUOTES)

    def test_repaired_json_reads_it_and_keeps_the_quotes(self):
        parsed = _parse_action_space(INNER_QUOTES, ACTIVITIES)
        self.assertEqual(sorted(parsed), sorted(ACTIVITIES))
        self.assertIn('同事提议一起下楼吃时以"来不及"为由拒绝', parsed["工作"])

    def test_the_same_repair_reaches_the_other_parsers(self):
        # Only ever runs where json.loads already failed, which is what makes
        # it safe to put behind every parser rather than just this one.
        parsed = _parse_json_dict('{"priorities": ["回复时说"稍等"再处理"]}')
        self.assertEqual(parsed, {"priorities": ['回复时说"稍等"再处理']})


class TestTruncation(unittest.TestCase):
    def test_the_activities_that_closed_are_recovered(self):
        parsed = _parse_action_space(TRUNCATED, ACTIVITIES)
        self.assertEqual(sorted(parsed), ["午餐", "工作"])
        self.assertEqual(len(parsed["工作"]), 2)

    def test_the_half_written_list_is_dropped_not_shortened(self):
        # 下班后's bracket never closed. Handing on its one complete item would
        # look like a real action space and stop the caller's retry from asking
        # for it -- the conservative direction is to drop it.
        parsed = _parse_action_space(TRUNCATED, ACTIVITIES)
        self.assertNotIn("下班后", parsed)
        self.assertNotIn("晚上", parsed)

    def test_the_retry_is_left_a_short_job(self):
        parsed = _parse_action_space(TRUNCATED, ACTIVITIES)
        missing = [a for a in ACTIVITIES if a not in parsed]
        self.assertEqual(missing, ["下班后", "晚上"])

    def test_nothing_parseable_still_yields_nothing(self):
        self.assertEqual(_parse_action_space("对不起，我无法完成。", ACTIVITIES), {})
        self.assertEqual(_parse_action_space("", ACTIVITIES), {})


class TestTruncationIsVisible(unittest.TestCase):
    """The API said the answer was cut off; the old code only looked when the
    answer was empty, so a truncated-with-text response was indistinguishable
    from a malformed one."""

    def setUp(self):
        reset_truncation_counts()

    def tearDown(self):
        reset_truncation_counts()

    def test_both_api_shapes_are_counted(self):
        _note_truncated("anthropic:m", "max_tokens", 512)   # Anthropic
        _note_truncated("openai:m", "length", 512)          # OpenAI
        self.assertEqual(truncation_counts(), {"anthropic:m": 1, "openai:m": 1})

    def test_a_normal_stop_is_not_counted(self):
        for reason in ("end_turn", "stop", None, ""):
            _note_truncated("anthropic:m", reason, 512)
        self.assertEqual(truncation_counts(), {})

    def test_counting_does_not_raise(self):
        # A truncated answer is often still usable -- the parser above salvages
        # it -- so turning a degraded result into a hard failure would be worse.
        self.assertIsNone(_note_truncated("anthropic:m", "max_tokens", 512))


class TestChunking(unittest.TestCase):
    """The un-chunked call could not have worked at production scale.

    One activity's block is 193 characters at the median (215 at p75) across
    848 real completions; the 512-token cap passes about 916. Four sit on the
    edge, six or more never fit, and a real day carries **ten** distinct
    activities. So the single call returned four at best and its retry, asked
    for the other six, hit the same wall -- what kept caches healthy was
    ``ensure_action_space_for_activity`` buying the rest back one call at a
    time afterwards.
    """

    #: A real day, from a captured run (``output/memory/agent_37_schedule``).
    TEN = ["起床", "送孩子", "配送", "休息", "午餐",
           "下午配送", "接孩子", "家庭晚餐", "有声小说", "睡觉"]

    def _run(self, activities, seeds=None):
        calls: list[list[str]] = []
        prompts: list[str] = []

        def fake(prompt, task=None, agent_id=None, provider=None):
            import re
            match = re.search(r"活动列表：(.+)", prompt)
            asked = [a.strip() for a in match.group(1).split(", ")] if match else []
            calls.append(asked)
            prompts.append(prompt)
            return json.dumps(
                {a: [f"{a}-动作{i}" for i in range(6)] for a in asked},
                ensure_ascii=False,
            )

        with patch.object(_action._llm_providers, "call_llm", fake), \
                patch.object(_action, "retrieve_relevant_memories", lambda *a, **k: []):
            result = _action._llm_generate_actions(
                {"id": 1, "name": "x"}, activities, seeds)
        return result, calls, prompts

    def test_a_real_day_is_split_into_calls_that_fit(self):
        result, calls, _ = self._run(self.TEN)
        self.assertEqual([len(c) for c in calls], [3, 3, 3, 1])
        for activity in self.TEN:
            self.assertIn(activity, result)

    def test_single_activity_path_is_unchanged(self):
        # ensure_action_space_for_activity asks for one and must stay one call.
        _, calls, _ = self._run(["工作"])
        self.assertEqual(len(calls), 1)

    def test_seeds_are_scoped_to_their_chunk(self):
        # Carrying every activity's seeds into every chunk is prompt weight
        # with nothing to contribute to the answer being asked for.
        seeds = {a: [f"{a}-种子"] for a in self.TEN}
        _, calls, prompts = self._run(self.TEN, seeds)
        self.assertEqual([p.count("-种子") for p in prompts], [3, 3, 3, 1])

    def test_chunk_size_comes_from_config(self):
        from gaworld.settings import CONFIG

        original = CONFIG["action_space"]["activities_per_call"]
        CONFIG["action_space"]["activities_per_call"] = 5
        try:
            _, calls, _ = self._run(self.TEN)
            self.assertEqual([len(c) for c in calls], [5, 5])
        finally:
            CONFIG["action_space"]["activities_per_call"] = original

    def test_a_broken_config_value_cannot_stall_the_loop(self):
        from gaworld.settings import CONFIG

        original = CONFIG["action_space"]["activities_per_call"]
        for bad in (0, -3, "x", None):
            CONFIG["action_space"]["activities_per_call"] = bad
            try:
                _, calls, _ = self._run(self.TEN)
                self.assertTrue(all(len(c) >= 1 for c in calls))
                self.assertLessEqual(len(calls), len(self.TEN))
            finally:
                CONFIG["action_space"]["activities_per_call"] = original


if __name__ == "__main__":
    unittest.main()
