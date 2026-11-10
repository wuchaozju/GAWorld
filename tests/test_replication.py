"""Tests for 社会调查/实验拟合度 (gaworld.research.replication + gaworld.apps.replication_api).

What we defend:

* the spec never invents a human number: unreported results stay absent,
  percentages and "62% said yes" become shares, a single choice has no mean;
* residents' answers out of range are invalid, not clamped;
* assignment is balanced (between) or complete (paired), and seeded;
* the comparison is by code: errors on the item's own range, the human value
  against the agents' 95% interval, treatment effects with a verdict, and the
  fidelity score's formula;
* the HTTP routes behind ``/api/research/replication`` extract a spec, run a
  job, store the run, export Markdown and delete it, through ``research_api``.

No LLM is reached and no city bundle is read.
"""

from __future__ import annotations

import json
import math
import re
import tempfile
import time
import unittest
from pathlib import Path
from typing import ClassVar
from unittest import mock

from gaworld.accounts import policy as access_policy
from gaworld.apps import replication_api, research_api
from gaworld.research import replication as rp
from gaworld.research import replication_interpret as ri

PEOPLE = [
    {
        "id": i,
        "name": f"居民{i}",
        "age": age,
        "gender": "女" if i % 2 else "男",
        "hukou": "本地",
        "job": "职员",
    }
    for i, age in enumerate([25, 30, 45, 50, 70, 68, 12, 38, 41, 22, 33, 59], start=1)
]

RAW_SPEC = {
    "title": "框架效应",
    "kind": "experiment",
    "population": "美国成年人",
    "conditions": [
        {"id": "C1", "label": "收益框架", "stimulus": "可以救 200 人"},
        {"id": "C2", "label": "损失框架", "stimulus": "会死 400 人"},
    ],
    "items": [
        {"id": "Q1", "text": "你支持方案 A 吗", "kind": "scale", "min": 1, "max": 7},
        {"id": "Q2", "text": "选哪个方案", "kind": "choice", "options": ["方案A", "方案B"]},
    ],
    "results": [
        {"item": "Q1", "condition": "C1", "mean": 5.0, "sd": 1.0, "n": 50, "source": "表1"},
        {"item": "Q1", "condition": "C2", "mean": 3.0, "sd": 1.0, "n": 50, "source": "表1"},
        {"item": "Q2", "condition": "C1", "distribution": {"方案A": 72}, "n": 50, "mean": 1.2},
        {"item": "Q2", "condition": "C2", "distribution": {"方案A": 22, "方案B": 78}, "n": 50},
        {"item": "Q9", "condition": "C1", "mean": 1},
    ],
}


def framed_answer(prompt: str) -> str:
    """Gain frame: support 5, pick A; loss frame: support 3, pick B — exactly the humans."""
    gain = "可以救 200 人" in prompt
    return json.dumps({"Q1": 5 if gain else 3, "Q2": 1 if gain else 2})


def extract_llm(prompt: str) -> str:
    return "好的：\n```json\n" + json.dumps(RAW_SPEC, ensure_ascii=False) + "\n```"


class SpecTest(unittest.TestCase):
    def test_results_are_normalised_never_invented(self) -> None:
        spec = rp.normalize_spec(RAW_SPEC)
        results = {(r["item"], r["condition"]): r for r in spec["results"]}
        self.assertEqual(set(results), {("Q1", "C1"), ("Q1", "C2"), ("Q2", "C1"), ("Q2", "C2")})
        self.assertEqual(results[("Q2", "C1")]["distribution"], {"方案A": 0.72, "方案B": 0.28})
        self.assertIsNone(results[("Q2", "C1")]["mean"])  # a nominal answer has no mean
        self.assertEqual(results[("Q2", "C2")]["distribution"]["方案B"], 0.78)
        self.assertEqual(spec["kind"], "experiment")

    def test_a_survey_gets_one_condition_and_a_default_scale(self) -> None:
        spec = rp.normalize_spec(
            {
                "items": [{"text": "你信任邻居吗", "kind": "likert", "min": 5, "max": 1}],
                "results": [{"item": "Q1", "condition": "whatever", "distribution": [10, 20, 30, 30, 10]}],
            }
        )
        self.assertEqual([c["id"] for c in spec["conditions"]], ["C1"])
        self.assertEqual((spec["items"][0]["min"], spec["items"][0]["max"]), (1, 5))
        self.assertEqual(spec["results"][0]["condition"], "C1")
        self.assertAlmostEqual(sum(spec["results"][0]["distribution"].values()), 1.0)
        self.assertTrue(spec["warnings"])

    def test_no_results_is_a_warning(self) -> None:
        spec = rp.normalize_spec({"items": [{"text": "x", "kind": "scale"}], "results": [{"item": "Q1"}]})
        self.assertEqual(spec["results"], [])
        self.assertIn("没有可用的真人结果", " ".join(spec["warnings"]))

    def test_answers_out_of_range_are_invalid(self) -> None:
        scale = {"id": "Q1", "kind": "scale", "min": 1, "max": 7}
        choice = {"id": "Q2", "kind": "choice", "options": ["同意", "不同意"]}
        self.assertEqual(rp.parse_answer(scale, "6.4"), 6.0)
        self.assertIsNone(rp.parse_answer(scale, 9))
        self.assertIsNone(rp.parse_answer(scale, "不知道"))
        self.assertEqual(rp.parse_answer(choice, 2), 1.0)
        self.assertEqual(rp.parse_answer(choice, "同意"), 0.0)
        self.assertIsNone(rp.parse_answer(choice, 3))
        self.assertEqual(rp.parse_answers(rp.normalize_spec(RAW_SPEC), "胡言乱语")["ok"], False)

    def test_prompt_carries_the_condition_and_every_item(self) -> None:
        spec = rp.normalize_spec(RAW_SPEC)
        prompt = rp.answer_prompt("你是居民1。", spec, spec["conditions"][1])
        self.assertIn("会死 400 人", prompt)
        self.assertNotIn("可以救 200 人", prompt)
        self.assertIn("1. 方案A", prompt)
        self.assertIn('"Q1"', prompt)


class AssignTest(unittest.TestCase):
    def test_between_is_balanced_and_seeded(self) -> None:
        conditions = [{"id": "C1"}, {"id": "C2"}, {"id": "C3"}]
        pairs = rp.assign(PEOPLE[:9], conditions, "between", 4)
        self.assertEqual(sorted(a for a, _ in pairs), list(range(1, 10)))
        self.assertEqual([sum(1 for _, c in pairs if c == cid) for cid in ("C1", "C2", "C3")], [3, 3, 3])
        self.assertEqual(pairs, rp.assign(PEOPLE[:9], conditions, "between", 4))

    def test_paired_is_everyone_times_every_condition(self) -> None:
        self.assertEqual(len(rp.assign(PEOPLE[:4], [{"id": "C1"}, {"id": "C2"}], "paired", 1)), 8)


class CompareTest(unittest.TestCase):
    def _responses(self, rows: list[tuple[int, str, int, int]]) -> list[dict]:
        return [
            {"agent_id": a, "condition": c, "ok": True, "answers": {"Q1": float(q1), "Q2": float(q2)}}
            for a, c, q1, q2 in rows
        ]

    def test_perfect_agents_replicate(self) -> None:
        spec = rp.normalize_spec(RAW_SPEC)
        rows = [(i, "C1", 4 if i % 2 else 6, 0) for i in range(1, 11)]
        rows += [(i, "C2", 3, 1) for i in range(11, 21)]
        result = rp.compare(spec, self._responses(rows), "between")
        effects = {e["item"]: e for e in result["effects"]}
        self.assertEqual(effects["Q1"]["verdict"], "replicated")
        self.assertAlmostEqual(effects["Q1"]["human_effect"], -2 / 6, places=3)
        self.assertEqual(effects["Q2"]["option"], "方案A")
        self.assertEqual(effects["Q2"]["verdict"], "replicated")
        q1c1 = next(c for c in result["cells"] if c["item"] == "Q1" and c["condition"] == "C1")
        self.assertTrue(q1c1["within_ci"])
        self.assertEqual(result["summary"]["direction_rate"], 1.0)

    def test_reversed_agents_are_caught(self) -> None:
        spec = rp.normalize_spec(RAW_SPEC)
        rows = [(i, "C1", 2 + i % 2, 1) for i in range(1, 11)] + [
            (i, "C2", 6 + i % 2, 0) for i in range(11, 21)
        ]
        result = rp.compare(spec, self._responses(rows), "between")
        self.assertEqual({e["verdict"] for e in result["effects"]}, {"reversed"})
        summary = result["summary"]
        self.assertEqual(summary["direction_rate"], 0.0)
        # score = 100 × (30% level + 30% spread + 40% direction), direction being 0 here
        self.assertAlmostEqual(
            summary["score"],
            round(
                100
                * sum(rp.SCORE_WEIGHTS[key] * value for key, value in summary["score_components"].items()),
                1,
            ),
            places=1,
        )
        self.assertEqual(summary["score_components"]["direction"], 0.0)

    def test_survey_score_is_level_accuracy(self) -> None:
        spec = rp.normalize_spec(
            {
                "items": [{"id": "Q1", "text": "x", "kind": "scale", "min": 1, "max": 5}],
                "results": [{"item": "Q1", "condition": "C1", "mean": 4.0}],
            }
        )
        responses = [{"agent_id": i, "condition": "C1", "ok": True, "answers": {"Q1": 3.0}} for i in range(5)]
        result = rp.compare(spec, responses, "between")
        cell = result["cells"][0]
        self.assertEqual((cell["diff"], cell["error"]), (-1.0, 0.25))
        # All five residents answered the same thing and it missed the humans:
        # the interval collapsed *and* did not cover the human mean, so the
        # collapse is charged to level (the paper reported no SD, so the spread
        # term could not judge it).
        self.assertTrue(cell["ci_degenerate"])
        self.assertFalse(cell["within_ci"])
        expected = round(100 * (0.75 * (1 - rp.COLLAPSE_PENALTY)), 1)
        # The published score normalises by the total weight, so compare against
        # the same arithmetic rather than a hand-rounded decimal.
        self.assertAlmostEqual(result["summary"]["score"], expected, delta=0.11)
        self.assertEqual(result["effects"], [])

    def test_verdict_table(self) -> None:
        self.assertEqual(rp.verdict(0.0, 0.3, 0.001), "no_human_effect")
        self.assertEqual(rp.verdict(0.2, 0.1, 0.5), "same_direction")
        self.assertEqual(rp.verdict(0.2, -0.1, 0.5), "not_replicated")
        self.assertEqual(rp.verdict(0.2, 0.0, None), "not_replicated")


SPREAD_SPEC = {
    "title": "灾害风险感知",
    "kind": "survey",
    "items": [{"id": "Q1", "text": "总体风险感知", "kind": "scale", "min": 0, "max": 20}],
    "results": [{"item": "Q1", "condition": "C1", "mean": 15.0, "sd": 2.83, "n": 164, "source": "表3"}],
}


class SpreadTest(unittest.TestCase):
    """The dispersion term: residents that agree far more (or far less) than the
    people did have to cost the score — a good mean alone must not carry it."""

    def _ring(self, n: int, mean: float, sd: float) -> list[float]:
        """``n`` answers with exactly this mean and standard deviation."""
        half = sd * math.sqrt((n - 1) / n)
        return [mean + (half if i % 2 else -half) for i in range(n)]

    def _responses(self, values: list[float]) -> list[dict]:
        return [
            {"agent_id": i, "condition": "C1", "ok": True, "answers": {"Q1": float(v)}}
            for i, v in enumerate(values, start=1)
        ]

    def _compare(self, values: list[float], spec: dict | None = None) -> dict:
        return rp.compare(rp.normalize_spec(spec or SPREAD_SPEC), self._responses(values), "between")

    def test_uniform_residents_lose_the_spread_points(self) -> None:
        result = self._compare([12.51] * 164)
        cell = result["cells"][0]
        self.assertEqual(cell["spread_error"], 1.0)
        self.assertEqual(result["summary"]["spread_accuracy"], 0.0)
        # A survey without effects: level and spread split what is left of the score.
        self.assertAlmostEqual(result["summary"]["score"], 47.1, places=1)

    def test_residents_as_spread_out_as_the_people_keep_the_points(self) -> None:
        result = self._compare(self._ring(164, 12.51, 2.83))
        self.assertLess(result["cells"][0]["spread_error"], 0.001)
        self.assertAlmostEqual(result["summary"]["spread_accuracy"], 1.0, places=3)
        self.assertAlmostEqual(result["summary"]["score"], 93.3, places=1)

    def test_the_dragon_pool_case_no_longer_scores_as_if_it_matched(self) -> None:
        """164 residents at 12.51 ± 1.18 against humans at 15 ± 2.83."""
        result = self._compare(self._ring(164, 12.51, 1.18))
        summary = result["summary"]
        self.assertAlmostEqual(summary["level_accuracy"], 0.876, places=2)
        self.assertAlmostEqual(summary["spread_accuracy"], 0.417, places=2)
        # A mean-only score would have read 87.5; dispersion has to show up in the total.
        self.assertAlmostEqual(summary["score"], 66.4, places=0)
        self.assertLess(summary["score"], 100 * summary["level_accuracy"])

    def test_a_paper_without_an_sd_drops_the_spread_term(self) -> None:
        spec = {
            "title": "只有均值",
            "kind": "survey",
            "items": [{"id": "Q1", "text": "x", "kind": "scale", "min": 0, "max": 20}],
            "results": [{"item": "Q1", "condition": "C1", "mean": 15.0}],
        }
        result = self._compare([12.51] * 164, spec)
        summary = result["summary"]
        self.assertIsNone(summary["spread_accuracy"])
        self.assertIsNone(summary["score_components"].get("spread"))
        self.assertEqual(summary["score_weights"], {"level": 1.0})
        # level alone was 0.875. The residents were unanimous and missed the
        # humans, so the collapsed interval is charged to level: 0.875 × 0.75.
        self.assertAlmostEqual(summary["level_accuracy"], 0.8755 * 0.75, places=3)
        self.assertAlmostEqual(summary["score"], round(100 * 0.8755 * 0.75, 1), delta=0.11)

    def test_a_choice_question_has_no_separate_spread_term(self) -> None:
        spec = {
            "title": "单选题",
            "kind": "survey",
            "items": [{"id": "Q1", "text": "选哪个", "kind": "choice", "options": ["A", "B"]}],
            "results": [{"item": "Q1", "condition": "C1", "distribution": {"A": 50, "B": 50}}],
        }
        responses = [
            {"agent_id": i, "condition": "C1", "ok": True, "answers": {"Q1": float(i % 2)}}
            for i in range(1, 21)
        ]
        result = rp.compare(rp.normalize_spec(spec), responses, "between")
        # The choice error already is the whole distribution difference.
        self.assertIsNone(result["cells"][0].get("spread_error"))
        self.assertIsNone(result["summary"]["spread_accuracy"])

    def test_a_handful_of_residents_cannot_judge_spread(self) -> None:
        result = self._compare(self._ring(4, 12.51, 1.18))
        self.assertIsNone(result["cells"][0].get("spread_error"))
        self.assertIsNone(result["summary"]["spread_accuracy"])
        self.assertAlmostEqual(result["summary"]["score"], 87.5, places=1)

    def test_the_summary_says_which_formula_scored_the_run(self) -> None:
        summary = self._compare(self._ring(164, 12.51, 1.18))["summary"]
        self.assertEqual(summary["score_version"], rp.SCORE_VERSION)
        self.assertEqual(sorted(summary["score_components"]), ["level", "spread"])
        self.assertAlmostEqual(sum(summary["score_weights"].values()), 1.0, places=3)


class LeakAndCoverageTest(unittest.TestCase):
    """Two ways a fidelity score can flatter the residents without evidence.

    A leak: the material a resident reads carries the paper's own result (the
    transcription of the question kept "均值 15"), so the resident is handed the
    answer the score then measures. Missing values: the paper reported one
    question out of two, and the score was quietly computed on what was left.
    """

    SPEC: ClassVar[dict] = {
        "title": "龙池镇灾害风险感知",
        "kind": "survey",
        "items": [
            {"id": "Q1", "text": "总体风险感知", "kind": "scale", "min": 0, "max": 20},
            {
                "id": "Q2",
                "text": "当灾害威胁到你所在位置时，你是否愿意撤离？",
                "kind": "scale",
                "min": 0,
                "max": 20,
            },
        ],
        "results": [{"item": "Q1", "condition": "C1", "mean": 15.0, "sd": 2.83, "n": 164, "source": "表3"}],
    }

    def _responses(self, n: int = 20) -> list[dict]:
        return [
            {
                "agent_id": i,
                "condition": "C1",
                "ok": True,
                "answers": {"Q1": 12.51 + (i % 5) * 0.1, "Q2": 3.82},
            }
            for i in range(1, n + 1)
        ]

    # ---- leak ----

    def test_a_question_that_carries_the_human_mean_is_a_leak(self) -> None:
        spec = rp.normalize_spec(
            {
                "title": "泄漏",
                "kind": "survey",
                "items": [
                    {
                        "id": "Q1",
                        "text": "你支持方案 A 吗（原研究均值为 15）",
                        "kind": "scale",
                        "min": 0,
                        "max": 20,
                    }
                ],
                "results": [{"item": "Q1", "condition": "C1", "mean": 15.0, "sd": 2.83, "n": 164}],
            }
        )
        findings = rp.leak_findings(spec)
        self.assertEqual(len(findings), 1)
        self.assertEqual((findings[0]["item"], findings[0]["kind"]), ("Q1", "均值"))
        self.assertEqual(findings[0]["where"], "题目")
        self.assertTrue(any("材料泄漏" in w for w in spec["warnings"]), spec["warnings"])

    def test_a_stimulus_that_quotes_the_result_is_a_leak_too(self) -> None:
        spec = rp.normalize_spec(
            {
                "title": "材料泄漏",
                "kind": "experiment",
                "conditions": [
                    {"id": "C1", "label": "对照", "stimulus": "上一组被试的平均得分是 15 分。"},
                    {"id": "C2", "label": "处理", "stimulus": "你看到一段关于撤离的宣传材料。"},
                ],
                "items": [{"id": "Q1", "text": "你的评价", "kind": "scale", "min": 0, "max": 20}],
                "results": [{"item": "Q1", "condition": "C1", "mean": 15.0, "sd": 2.83, "n": 164}],
            }
        )
        findings = rp.leak_findings(spec)
        self.assertEqual([(f["item"], f["condition"]) for f in findings], [("Q1", "C1")])
        self.assertEqual(findings[0]["where"], "材料")

    def test_a_plain_number_without_a_result_word_is_not_a_leak(self) -> None:
        spec = rp.normalize_spec(
            {
                "title": "不是泄漏",
                "kind": "survey",
                "items": [
                    {"id": "Q1", "text": "过去 15 天你关注过洪水预警吗", "kind": "scale", "min": 0, "max": 20}
                ],
                "results": [{"item": "Q1", "condition": "C1", "mean": 15.0, "sd": 2.83, "n": 164}],
            }
        )
        self.assertEqual(rp.leak_findings(spec), [])
        self.assertEqual(spec["warnings"], [])

    def test_a_leaked_cell_is_shown_but_kept_out_of_the_score(self) -> None:
        spec = rp.normalize_spec(
            {
                "title": "泄漏",
                "kind": "survey",
                "items": [
                    {
                        "id": "Q1",
                        "text": "你支持方案 A 吗（原研究均值为 15）",
                        "kind": "scale",
                        "min": 0,
                        "max": 20,
                    }
                ],
                "results": [{"item": "Q1", "condition": "C1", "mean": 15.0, "sd": 2.83, "n": 164}],
            }
        )
        result = rp.compare(spec, self._responses(), "between")
        summary = result["summary"]
        self.assertEqual(summary["leaked_cells"], 1)
        self.assertIsNotNone(result["cells"][0].get("leak"))
        # The residents were handed the answer: the cell cannot score them either way.
        self.assertEqual(summary["cells_compared"], 0)
        self.assertIsNone(summary["score"])
        self.assertTrue(summary["leak_findings"])

    def test_the_report_names_the_leak(self) -> None:
        spec = rp.normalize_spec(
            {
                "title": "泄漏",
                "kind": "survey",
                "items": [
                    {
                        "id": "Q1",
                        "text": "你支持方案 A 吗（原研究均值为 15）",
                        "kind": "scale",
                        "min": 0,
                        "max": 20,
                    }
                ],
                "results": [{"item": "Q1", "condition": "C1", "mean": 15.0, "sd": 2.83, "n": 164}],
            }
        )
        run = rp.run_replication(
            spec=spec,
            sample_size=8,
            seed=1,
            answer=lambda prompt: json.dumps({"Q1": 15, "Q2": 3}),
            population=PEOPLE,
            profile_fn=lambda city, agent_id: "",
            workers=1,
        )
        markdown = rp.export_markdown(run)
        self.assertIn("材料泄漏", markdown)
        self.assertIn("这个分数覆盖了多少", markdown)

    # ---- missing values ----

    def test_a_question_without_a_human_result_is_named(self) -> None:
        spec = rp.normalize_spec(self.SPEC)
        cover = rp.coverage(spec)
        self.assertEqual(cover["cells_possible"], 2)
        self.assertEqual(cover["cells_with_human"], 1)
        self.assertEqual(cover["missing_items"], ["Q2"])
        self.assertEqual(cover["human_coverage"], 0.5)
        self.assertTrue(any("Q2" in w for w in cover["warnings"]), cover["warnings"])
        self.assertTrue(
            any("不能代表整项研究" in w for w in spec["warnings"]),
            spec["warnings"],
        )

    def test_the_score_says_how_much_of_the_study_it_covers(self) -> None:
        spec = rp.normalize_spec(self.SPEC)
        summary = rp.compare(spec, self._responses(), "between")["summary"]
        self.assertEqual(summary["score_scope"], "1/2 个单元格")
        self.assertEqual(summary["coverage"]["cells_with_human"], 1)
        self.assertTrue(summary["coverage_warnings"])

    def test_the_reading_is_told_the_score_only_covers_what_was_reported(self) -> None:
        spec = rp.normalize_spec(self.SPEC)
        run = rp.run_replication(
            spec=spec,
            sample_size=8,
            seed=1,
            answer=lambda prompt: json.dumps({"Q1": 12.5, "Q2": 3}),
            population=PEOPLE,
            profile_fn=lambda city, agent_id: "",
            workers=1,
        )
        prompt = ri.build_prompt(run)
        self.assertIn("评分口径", prompt)
        self.assertIn("1/2", prompt)

    def test_a_complete_paper_has_no_coverage_warning(self) -> None:
        spec = rp.normalize_spec(
            {
                "title": "完整",
                "kind": "survey",
                "items": [{"id": "Q1", "text": "x", "kind": "scale", "min": 0, "max": 20}],
                "results": [{"item": "Q1", "condition": "C1", "mean": 15.0, "sd": 2.83, "n": 164}],
            }
        )
        cover = rp.coverage(spec)
        self.assertEqual(cover["human_coverage"], 1.0)
        self.assertEqual(cover["warnings"], [])


class DegenerateIntervalTest(unittest.TestCase):
    """Residents who all answered the same thing.

    Their 95% interval collapses to a point, so the human mean can never fall
    inside it and the "human value inside the agents' 95% interval" rate reads
    0%. When the paper reported an SD the spread term already charges for the
    collapse; when it did not, the spread term drops out of the score and the
    collapse used to be invisible — the score said 87.5 while the interval
    could never be hit. These tests pin that the collapse is always priced.
    """

    SPEC_NO_SD: ClassVar[dict] = {
        "title": "只有均值",
        "kind": "survey",
        "items": [{"id": "Q1", "text": "x", "kind": "scale", "min": 0, "max": 20}],
        "results": [{"item": "Q1", "condition": "C1", "mean": 15.0}],
    }
    SPEC_WITH_SD: ClassVar[dict] = {
        "title": "灾害风险感知",
        "kind": "survey",
        "items": [{"id": "Q1", "text": "总体风险感知", "kind": "scale", "min": 0, "max": 20}],
        "results": [{"item": "Q1", "condition": "C1", "mean": 15.0, "sd": 2.83, "n": 164, "source": "表3"}],
    }

    def _responses(self, values: list[float]) -> list[dict]:
        return [
            {"agent_id": i, "condition": "C1", "ok": True, "answers": {"Q1": float(v)}}
            for i, v in enumerate(values, start=1)
        ]

    def _compare(self, values: list[float], spec: dict) -> dict:
        return rp.compare(rp.normalize_spec(spec), self._responses(values), "between")

    def test_a_collapsed_interval_is_flagged_on_the_cell(self) -> None:
        result = self._compare([12.51] * 164, self.SPEC_NO_SD)
        cell = result["cells"][0]
        self.assertTrue(cell["ci_degenerate"])
        self.assertFalse(cell["within_ci"])
        self.assertEqual(result["summary"]["within_ci_rate"], 0.0)
        self.assertEqual(result["summary"]["collapsed_ci_cells"], 1)

    def test_a_healthy_interval_is_not_flagged(self) -> None:
        values = [12.51 + (0.7 if i % 2 else -0.7) for i in range(164)]
        result = self._compare(values, self.SPEC_NO_SD)
        self.assertIs(result["cells"][0]["ci_degenerate"], False)

    def test_the_collapse_is_counted_in_the_summary(self) -> None:
        result = self._compare([12.51] * 164, self.SPEC_NO_SD)
        summary = result["summary"]
        self.assertEqual(summary["degenerate_ci_cells"], 1)
        self.assertEqual(summary["degenerate_ci_rate"], 1.0)

    def test_the_collapse_costs_points_when_the_spread_term_dropped_out(self) -> None:
        """No human SD: the spread term is gone, so the collapse has to be
        charged somewhere — level is the only component left."""
        result = self._compare([12.51] * 164, self.SPEC_NO_SD)
        summary = result["summary"]
        self.assertIsNone(summary["spread_accuracy"])
        # level alone was 0.875; the unanimous answer now costs a share of it.
        self.assertLess(summary["level_accuracy"], 0.875)
        self.assertLess(summary["score"], 87.5)

    def test_a_unanimous_crowd_that_got_it_right_is_not_charged(self) -> None:
        """The interval collapsed, but the human mean sits exactly on it: the
        group was right. The level term already says so — the collapse must not
        be charged on top of it."""
        spec = {
            "title": "只有均值",
            "kind": "survey",
            "items": [{"id": "Q1", "text": "x", "kind": "scale", "min": 0, "max": 20}],
            "results": [{"item": "Q1", "condition": "C1", "mean": 15.0}],
        }
        result = self._compare([15.0] * 164, spec)
        summary = result["summary"]
        self.assertTrue(result["cells"][0]["ci_degenerate"])
        self.assertTrue(result["cells"][0]["within_ci"])
        # The interval collapsed, but it covered the humans — nothing is charged.
        self.assertEqual(summary["collapsed_ci_cells"], 1)
        self.assertEqual(summary["degenerate_ci_cells"], 0)
        self.assertAlmostEqual(summary["level_accuracy"], 1.0, places=3)
        self.assertAlmostEqual(summary["score"], 100.0, places=1)

    def test_residents_who_spread_out_keep_their_points_without_a_paper_sd(self) -> None:
        """The same paper, but the residents are not unanimous: nothing is
        charged, because nothing collapsed."""
        values = [12.51 + (0.7 if i % 2 else -0.7) for i in range(164)]
        summary = self._compare(values, self.SPEC_NO_SD)["summary"]
        self.assertEqual(summary["degenerate_ci_cells"], 0)
        self.assertAlmostEqual(summary["level_accuracy"], 0.875, places=3)
        self.assertAlmostEqual(summary["score"], 87.5, places=1)

    def test_the_collapse_is_not_charged_twice_when_the_spread_term_priced_it(self) -> None:
        """With a human SD the spread term already charges 1.0 for the collapse;
        level must not be charged again on top of it."""
        result = self._compare([12.51] * 164, self.SPEC_WITH_SD)
        summary = result["summary"]
        self.assertEqual(summary["degenerate_ci_cells"], 1)
        self.assertEqual(summary["spread_accuracy"], 0.0)
        self.assertAlmostEqual(summary["level_accuracy"], 0.875, places=3)

    def test_a_choice_question_has_no_interval_to_collapse(self) -> None:
        spec = {
            "title": "单选题",
            "kind": "survey",
            "items": [{"id": "Q1", "text": "选哪个", "kind": "choice", "options": ["A", "B"]}],
            "results": [{"item": "Q1", "condition": "C1", "distribution": {"A": 50, "B": 50}}],
        }
        responses = [
            {"agent_id": i, "condition": "C1", "ok": True, "answers": {"Q1": float(i % 2)}}
            for i in range(1, 21)
        ]
        result = rp.compare(rp.normalize_spec(spec), responses, "between")
        self.assertIsNone(result["cells"][0].get("ci_degenerate"))
        self.assertEqual(result["summary"]["degenerate_ci_cells"], 0)

    def test_the_report_says_the_collapse_was_charged(self) -> None:
        """A score that dropped has to say why: the collapse is a deduction a
        reader cannot otherwise see."""
        summary = self._compare([12.51] * 164, self.SPEC_NO_SD)["summary"]
        text = rp._score_formula_text(summary)
        self.assertIn("退化", text)
        self.assertIn("25%", text)

    def test_the_report_does_not_mention_a_collapse_that_did_not_happen(self) -> None:
        values = [12.51 + (0.7 if i % 2 else -0.7) for i in range(164)]
        summary = self._compare(values, self.SPEC_NO_SD)["summary"]
        self.assertNotIn("退化", rp._score_formula_text(summary))

    def test_an_old_record_is_not_described_with_the_new_formula(self) -> None:
        """A record scored under v2 keeps its own formula text."""
        summary = self._compare([12.51] * 164, self.SPEC_NO_SD)["summary"]
        summary["score_version"] = 2
        summary["degenerate_ci_cells"] = 1
        self.assertNotIn("退化", rp._score_formula_text(summary))


class RunTest(unittest.TestCase):
    def _run(self, **overrides: object) -> dict:
        kwargs: dict = {
            "spec": RAW_SPEC,
            "sample_size": 8,
            "seed": 3,
            "answer": framed_answer,
            "population": PEOPLE,
            "profile_fn": lambda city, agent_id: "",
            "workers": 2,
        }
        kwargs.update(overrides)
        return rp.run_replication(**kwargs)

    def test_between_run_matches_humans(self) -> None:
        run = self._run()
        self.assertEqual(len(run["residents"]), 8)
        self.assertEqual(len(run["responses"]), 8)
        self.assertNotIn(7, [r["agent_id"] for r in run["residents"]])  # the 12-year-old
        # Q1 is exact; Q2 is unanimous where the humans split 72/28 and 22/78 (TVD .28 and .22).
        self.assertEqual(run["comparison"]["summary"]["level_accuracy"], 0.875)
        # Four residents per condition: too few to judge dispersion, so the score keeps
        # the old formula (level + direction) and the dispersion term stays empty.
        self.assertIsNone(run["comparison"]["summary"]["spread_accuracy"])
        self.assertEqual(run["comparison"]["summary"]["score"], 93.8)
        self.assertEqual(run, {**run, "seed": 3})

    def test_a_run_records_the_epoch_it_was_scored_under(self) -> None:
        """The score formula changed, so runs from before and after must not be
        pooled as if they said the same thing."""
        from gaworld.core.comparability import CURRENT_EPOCH

        self.assertEqual(self._run()["comparability_epoch"], CURRENT_EPOCH)

    def test_paired_run_and_age_range(self) -> None:
        run = self._run(design="paired", spec={**RAW_SPEC, "age_min": 40, "age_max": 60}, sample_size=50)
        self.assertEqual(sorted(r["agent_id"] for r in run["residents"]), [3, 4, 9, 12])
        self.assertEqual((run["eligible"], len(run["responses"])), (4, 8))
        self.assertEqual({e["verdict"] for e in run["comparison"]["effects"]}, {"replicated"})

    def test_invalid_answers_say_why_and_all_invalid_is_retained(self) -> None:
        replies = iter(["随便聊聊"] + [framed_answer("可以救 200 人")] * 7)
        run = self._run(answer=lambda prompt: next(replies), workers=1)
        bad = [r for r in run["responses"] if not r["ok"]]
        self.assertEqual((run["failed"], bad[0]["error"]), (1, "读不出回答：随便聊聊"))

        def broken(prompt: str) -> str:
            raise TimeoutError("provider down")

        failed = self._run(answer=broken)
        self.assertEqual(failed["failed"], len(failed["responses"]))
        self.assertIsNone(failed["comparison"]["summary"]["score"])
        self.assertIn("TimeoutError: provider down", failed["responses"][0]["error"])

    def test_unusable_spec_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            self._run(spec={**RAW_SPEC, "results": []})
        with self.assertRaises(ValueError):
            self._run(spec={**RAW_SPEC, "age_min": 90})

    def test_extraction(self) -> None:
        spec = rp.extract_spec("方法与结果。" * 60, title="T", llm=extract_llm)
        self.assertEqual(len(spec["results"]), 4)
        with self.assertRaises(ValueError):
            rp.extract_spec("太短", llm=extract_llm)

    def test_export(self) -> None:
        markdown = rp.export_markdown({**self._run(), "id": "rep-x"})
        self.assertTrue(markdown.startswith("# 社会调查/实验拟合度"))
        self.assertIn("方向一致且显著（不代表效应等价）", markdown)
        self.assertRegex(markdown, re.compile(r"拟合度分：93\.8"))
        self.assertIn("离散度准确度", markdown)
        self.assertIn("离散度误差", markdown)


GROUP_SPEC = {
    **RAW_SPEC,
    "groups": [
        {"id": "G1", "label": "女性", "gender": "female"},
        {"id": "G2", "label": "男性", "gender": "男性"},
        {"id": "G3", "label": "本科以上", "education": "本科"},
        {"id": "G4", "label": "外地青年", "hukou": "外来人口", "age_min": 35, "age_max": 18},
    ],
    "results": RAW_SPEC["results"]
    + [
        {"item": "Q1", "condition": "C1", "group": "G1", "mean": 5.5, "sd": 1.0, "n": 25},
        {"item": "Q1", "condition": "C1", "group": "G2", "mean": 4.5, "sd": 1.0, "n": 25},
        {"item": "Q1", "condition": "C1", "group": "G3", "mean": 9},
    ],
}

READING = {
    "summary": "居民整体重现了框架效应，但女性和男性的差距被放大。",
    "findings": [
        {"ref": "q1 / c2-c1", "pattern": "missing_effect", "claim": "效应消失了", "evidence": "…"},
        {
            "ref": "Q1/C1/G2-G1",
            "pattern": "exaggerated",
            "claim": "性别差距被放大",
            "evidence": "-0.333 vs -0.167",
        },
        {"ref": "Q9/C1", "pattern": "homogeneity", "claim": "编的一行"},
    ],
    "population_gap": "文献是美国大学生，居民是中国城镇居民。",
    "suggestions": [{"title": "加大样本", "rationale": "分组单元格太小", "how": "规模选 100"}],
}


def gendered_answer(prompt: str) -> str:
    """Gain frame: women 6, men 4 (humans: 5.5 vs 4.5); loss frame: everyone 3; pick by frame."""
    gain = "可以救 200 人" in prompt
    woman = re.search(r"岁，女。", prompt) is not None
    return json.dumps({"Q1": (6 if woman else 4) if gain else 3, "Q2": 1 if gain else 2})


class GroupTest(unittest.TestCase):
    def test_groups_map_onto_resident_attributes_only(self) -> None:
        spec = rp.normalize_spec(GROUP_SPEC)
        groups = {g["id"]: g for g in spec["groups"]}
        self.assertEqual(sorted(groups), ["G1", "G2", "G3", "G4"])
        self.assertEqual((groups["G1"]["gender"], groups["G2"]["gender"]), ("女", "男"))
        self.assertEqual(
            (groups["G4"]["hukou"], groups["G4"]["age_min"], groups["G4"]["age_max"]), ("外地", 18, 35)
        )
        self.assertEqual(groups["G3"]["education"], "本科")
        self.assertIn("G3", {r["group"] for r in spec["results"]})
        self.assertFalse(rp.in_group({"age": 24}, groups["G3"]))
        self.assertEqual(rp.group_dimension(groups["G4"]), "age+hukou")
        self.assertEqual(rp.group_text(groups["G4"]), "18–35 岁 · 外地户籍")
        self.assertTrue(rp.in_group({"age": 20, "hukou": "外省"}, groups["G4"]))
        self.assertFalse(rp.in_group({"age": 20, "hukou": "本地"}, groups["G4"]))
        self.assertFalse(rp.in_group({"age": 20, "hukou": "未知"}, groups["G4"]))

    def test_group_cells_and_gaps_are_compared_on_the_right_residents(self) -> None:
        run = RunTest()._run(spec=GROUP_SPEC, answer=gendered_answer, sample_size=11, design="paired")
        comparison = run["comparison"]
        cells = {c["ref"]: c for c in comparison["group_cells"]}
        self.assertEqual(set(cells), {"Q1/C1/G1", "Q1/C1/G2", "Q1/C1/G3"})
        self.assertEqual(cells["Q1/C1/G3"]["agent"]["n"], 0)
        self.assertEqual((cells["Q1/C1/G1"]["agent"]["mean"], cells["Q1/C1/G2"]["agent"]["mean"]), (6.0, 4.0))
        women = sum(1 for r in run["residents"] if r["gender"] == "女")
        self.assertEqual(cells["Q1/C1/G1"]["agent"]["n"], women)
        self.assertEqual(cells["Q1/C1/G1"]["thin"], women < rp.MIN_GROUP_N)
        (gap,) = comparison["group_gaps"]
        self.assertEqual((gap["ref"], gap["verdict"]), ("Q1/C1/G2-G1", "replicated"))
        self.assertAlmostEqual(gap["human_effect"], -1 / 6, places=3)
        self.assertAlmostEqual(gap["agent_effect"], -2 / 6, places=3)
        summary = comparison["summary"]
        self.assertEqual((summary["group_cells_compared"], summary["group_direction_rate"]), (2, 1.0))
        # Groups are reported next to the score, not folded into it.
        plain = RunTest()._run(spec=RAW_SPEC, answer=gendered_answer, sample_size=11, design="paired")
        self.assertEqual(summary["score"], plain["comparison"]["summary"]["score"])
        self.assertIn("## 分组对照", rp.export_markdown(run))

    def test_sd_ratio_flags_uniform_agents(self) -> None:
        spec = rp.normalize_spec(RAW_SPEC)
        responses = [
            {"agent_id": i, "condition": "C1", "ok": True, "answers": {"Q1": 5.0 + i % 2}} for i in range(6)
        ]
        cell = rp.compare(spec, responses, "between")["cells"][0]
        self.assertLess(cell["sd_ratio"], 1)


class InterpretTest(unittest.TestCase):
    def setUp(self) -> None:
        self.run = RunTest()._run(spec=GROUP_SPEC, answer=gendered_answer, sample_size=11, design="paired")

    def test_prompt_carries_the_tables_and_refs(self) -> None:
        prompt = ri.build_prompt(self.run)
        for ref in ("Q1/C1", "Q1/C2-C1", "Q1/C1/G1", "Q1/C1/G2-G1"):
            self.assertIn(f"| {ref} |", prompt)
        self.assertIn("美国成年人", prompt)
        self.assertIn("性别：男", prompt)

    def test_findings_are_tied_to_rows_and_checked(self) -> None:
        reading = ri.interpret(self.run, llm_fn=lambda prompt: json.dumps(READING, ensure_ascii=False))
        first, second, third = reading["findings"]
        self.assertEqual((first["ref"], first["grounded"], first["check"]), ("Q1/C2-C1", True, "conflict"))
        self.assertEqual(first["verdict"], "replicated")
        self.assertEqual((second["kind"], second["check"]), ("group_gap", "ok"))
        self.assertEqual((third["grounded"], third["check"]), (False, "unchecked"))
        markdown = "\n".join(ri.interpretation_markdown(reading))
        self.assertIn("与数字不符", markdown)
        self.assertIn("不作数", markdown)

    def test_unusable_reading_is_an_error(self) -> None:
        with self.assertRaisesRegex(ValueError, "JSON"):
            ri.interpret(self.run, llm_fn=lambda prompt: "我觉得挺好")
        with self.assertRaisesRegex(ValueError, "模型调用失败"):
            ri.interpret(self.run, llm_fn=lambda prompt: (_ for _ in ()).throw(TimeoutError("down")))

    def test_pattern_checks(self) -> None:
        item = {"id": "Q1", "kind": "scale", "min": 1, "max": 7}
        cell = {"human_mean": 6.0, "agent": {"mean": 4.5}, "error": 0.25}
        self.assertEqual(ri._pattern_check("central", "cell", cell, item), "ok")
        self.assertEqual(ri._pattern_check("extreme", "cell", cell, item), "conflict")
        self.assertEqual(ri._pattern_check("reversed", "cell", cell, item), "conflict")
        effect = {"human_effect": 0.3, "agent_effect": -0.1, "verdict": "not_replicated"}
        self.assertEqual(ri._pattern_check("reversed", "effect", effect, item), "ok")
        self.assertEqual(ri._pattern_check("missing_effect", "effect", effect, item), "ok")

    def test_interpret_is_quota_gated(self) -> None:
        self.assertTrue(access_policy.quota_gated("/api/research/replication/rep-1/interpret"))
        self.assertFalse(access_policy.quota_gated("/api/research/replication/rep-1/export"))


class HttpTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        replication_api.reset()

        def llm(prompt: str, task: str, provider: str) -> str:
            if task == "interpret":
                return json.dumps(READING, ensure_ascii=False)
            return extract_llm(prompt) if task == "extract" else framed_answer(prompt)

        for target in (
            mock.patch.object(rp, "replication_root", return_value=Path(self.tmp.name)),
            mock.patch.object(replication_api, "_LLM_OVERRIDE", llm),
            mock.patch("gaworld.interview.roster.load_population", return_value=PEOPLE),
            mock.patch("gaworld.interview.roster.profile_block", return_value=""),
        ):
            target.start()
            self.addCleanup(target.stop)

    def _wait(self, job_id: str) -> dict:
        for _ in range(200):
            record, status = research_api.handle_get(f"/api/research/replication/jobs/{job_id}")
            self.assertEqual(status, 200)
            if record["status"] != "running":
                self.assertEqual(record["status"], "done", record.get("error"))
                return record["result"]
            time.sleep(0.02)
        self.fail("job did not finish")

    def test_extract_run_view_export_delete(self) -> None:
        self.assertEqual(research_api.handle_post("/api/research/replication/extract", {"text": ""})[1], 400)
        body, status = research_api.handle_post(
            "/api/research/replication/extract", {"text": "论文正文。" * 80}
        )
        self.assertEqual(status, 202)
        spec = self._wait(body["job_id"])["spec"]

        checked, status = research_api.handle_post("/api/research/replication/check", {"spec": spec})
        self.assertEqual((status, len(checked["spec"]["items"])), (200, 2))
        refused = research_api.handle_post("/api/research/replication/run", {"spec": {**spec, "results": []}})
        self.assertEqual(refused[1], 400)

        body, status = research_api.handle_post(
            "/api/research/replication/run",
            {"spec": spec, "sample_size": 6, "seed": 2, "city_name": "测试城", "design": "paired"},
        )
        self.assertEqual(status, 202)
        run_id = self._wait(body["job_id"])["run_id"]

        listing, _ = research_api.handle_get("/api/research/replication")
        self.assertEqual((listing["runs"][0]["id"], listing["runs"][0]["score"]), (run_id, 65.6))
        run, status = research_api.handle_get(f"/api/research/replication/{run_id}")
        self.assertEqual((status, run["city_name"], len(run["responses"])), (200, "测试城", 12))
        export, _ = research_api.handle_get(f"/api/research/replication/{run_id}/export")
        self.assertTrue(export["markdown"].startswith("# 社会调查/实验拟合度"))

        self.assertEqual(
            run["interpretation"]["findings"][0]["check"], "conflict"
        )  # the effect did replicate
        run["interpretation"] = {}
        rp.save_run(run)
        body, status = research_api.handle_post(f"/api/research/replication/{run_id}/interpret", {})
        self.assertEqual(status, 202)
        self.assertIsNone(self._wait(body["job_id"])["error"])
        reread, _ = research_api.handle_get(f"/api/research/replication/{run_id}")
        self.assertEqual(reread["interpretation"]["summary"], READING["summary"])
        self.assertIn(
            "偏差解读", research_api.handle_get(f"/api/research/replication/{run_id}/export")[0]["markdown"]
        )
        self.assertEqual(research_api.handle_post("/api/research/replication/nope/interpret", {})[1], 404)

        deleted, _ = research_api.handle_post(f"/api/research/replication/{run_id}/delete", {})
        self.assertTrue(deleted["deleted"])
        self.assertEqual(research_api.handle_get(f"/api/research/replication/{run_id}")[1], 404)
        self.assertEqual(research_api.handle_get("/api/research/replication/../etc")[1], 404)


if __name__ == "__main__":
    unittest.main()
