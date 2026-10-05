"""Tests for 小说局 (gaworld.apps.novel_api).

What we defend:

* **Word counting.** A Chinese character counts as one word; an English run
  splits on whitespace. Empty / whitespace input is zero.
* **Style resolution.** Built-in presets resolve by id; custom blocks need
  both ``text`` and ``point_of_view``; unknown ids raise ``ValueError``.
* **Cast + outline parsing.** Missing / malformed agent_ids are dropped;
  chapters without any cast characters fall back to the full picked set
  rather than ship an empty stage.
* **Outline budget allocation.** A model that returned every chapter at 1500
  words regardless of the 30 000-word target still ends up with chapters
  whose targets sum to roughly the request.
* **Run shape.** Result has title / premise / cast / chapters / outline /
  stats / target_words. Every chapter has ``chapter``, ``title``, ``text``,
  ``word_count``, ``characters``. Each picked agent_id appears in the cast.
* **Cost.** One cast + one outline + N chapter calls + one summary call.
* HTTP delegation returns the documented shapes and the 400/404 contract,
  including the ``/api/games/novel/`` branch in ``games_api``.

No LLM is reached: ``author_fn`` / ``structure_fn`` / ``summary_fn`` are
injected as plain callables, and the persona cards are handed in directly.
"""

from __future__ import annotations

import time
import unittest
from unittest import mock

from gaworld.apps import games_api, novel_api


def _person(agent_id, name, age=40, job="客服专员", residence="A小区"):
    return {
        "id": agent_id,
        "name": name,
        "age": age,
        "gender": "女",
        "job": job,
        "residence": residence,
        "hukou": "本地",
        "state": {},
    }


def _card(agent_id, name, age=40, job="客服专员", residence="A小区"):
    return {
        "agent_id": agent_id,
        "name": name,
        "age": age,
        "gender": "女",
        "job": job,
        "residence": residence,
        "profile_md": f"**身份**：{name}，{job}。",
        "persona_short": f"你是{name}，{age}岁，{job}。",
    }


def _scripted(replies: list[str]):
    """An answer_fn that returns the scripted replies in order, recording every prompt."""
    calls: list[str] = []

    def fn(prompt: str) -> str:
        calls.append(prompt)
        return replies[min(len(calls) - 1, len(replies) - 1)]

    fn.calls = calls  # type: ignore[attr-defined]
    return fn


# ---------------------------------------------------------------------------
# Word counting
# ---------------------------------------------------------------------------


class WordCountTest(unittest.TestCase):
    def test_chinese_chars_each_count_as_one(self) -> None:
        self.assertEqual(novel_api.count_words("你好"), 2)
        # Including the fullwidth comma: 你 好 ， 世 界 = 5 chars
        self.assertEqual(novel_api.count_words("你好，世界"), 5)

    def test_english_words_count_by_whitespace(self) -> None:
        self.assertEqual(novel_api.count_words("hello world"), 2)
        self.assertEqual(novel_api.count_words("hello, world!"), 2)

    def test_mixed_chinese_and_english(self) -> None:
        # 4 Chinese + 2 English words = 6
        self.assertEqual(novel_api.count_words("我叫 Alice,我住 Beijing"), 6)

    def test_empty_and_whitespace_are_zero(self) -> None:
        self.assertEqual(novel_api.count_words(""), 0)
        self.assertEqual(novel_api.count_words("   \n\t  "), 0)


# ---------------------------------------------------------------------------
# Style resolution
# ---------------------------------------------------------------------------


class StyleTest(unittest.TestCase):
    def test_builtins_resolve_by_id(self) -> None:
        for entry in novel_api.STYLE_PRESETS:
            got = novel_api.resolve_style(entry["id"])
            self.assertEqual(got["id"], entry["id"])
            self.assertTrue(got["text"])
            self.assertTrue(got["point_of_view"])

    def test_list_styles_is_a_copy(self) -> None:
        first = novel_api.list_styles()
        second = novel_api.list_styles()
        self.assertEqual(first, second)
        first.clear()
        # Mutating the returned list does not change the underlying tuple.
        self.assertEqual(len(second), len(novel_api.STYLE_PRESETS))

    def test_custom_style_needs_text(self) -> None:
        with self.assertRaises(ValueError):
            novel_api.resolve_style("", {"text": "", "point_of_view": "第三人称"})
        with self.assertRaises(ValueError):
            novel_api.resolve_style("", {"text": "  ", "point_of_view": "第三人称"})

    def test_custom_style_defaults_pov_when_missing(self) -> None:
        got = novel_api.resolve_style("", {"text": "干净的短句。"})
        self.assertEqual(got["point_of_view"], "第三人称")
        self.assertEqual(got["id"], "custom")

    def test_unknown_id_raises(self) -> None:
        with self.assertRaises(ValueError):
            novel_api.resolve_style("not-a-real-style")


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


class OutlineParseTest(unittest.TestCase):
    def test_clean_outline(self) -> None:
        raw = (
            '{"chapters": ['
            '{"chapter": 1, "title": "开端", "summary": "下雨了", "target_words": 1500, "characters": [1, 2]},'
            '{"chapter": 2, "title": "转折", "summary": "她出现了", "target_words": 1500, "characters": [3]}'
            "]}"
        )
        chapters = novel_api._parse_outline(raw, [1, 2, 3])
        self.assertEqual([c["chapter"] for c in chapters], [1, 2])
        self.assertEqual(chapters[0]["characters"], [1, 2])
        self.assertEqual(chapters[1]["characters"], [3])
        self.assertEqual(chapters[1]["title"], "转折")

    def test_unknown_character_ids_are_dropped(self) -> None:
        raw = '{"chapters": [{"chapter": 1, "title": "x", "target_words": 1500, "characters": [1, 99]}]}'
        chapters = novel_api._parse_outline(raw, [1, 2])
        self.assertEqual(chapters[0]["characters"], [1])

    def test_a_chapter_with_no_cast_falls_back_to_the_full_set(self) -> None:
        raw = '{"chapters": [{"chapter": 1, "title": "x", "target_words": 1500, "characters": []}]}'
        chapters = novel_api._parse_outline(raw, [1, 2])
        # Empty list -> the entire picked set, so the chapter never ships nameless.
        self.assertEqual(sorted(chapters[0]["characters"]), [1, 2])

    def test_missing_chapters_get_a_default_eight_chapter_outline(self) -> None:
        chapters = novel_api._parse_outline("", [1, 2])
        self.assertEqual(len(chapters), 8)
        for ch in chapters:
            self.assertEqual(sorted(ch["characters"]), [1, 2])

    def test_garbage_input_is_a_default_outline(self) -> None:
        chapters = novel_api._parse_outline("这根本不是 JSON", [1, 2])
        self.assertEqual(len(chapters), 8)


class CastParseTest(unittest.TestCase):
    def test_clean_cast(self) -> None:
        raw = '{"cast": [{"agent_id": 1, "role": "主角", "arc": "经历了一夜"}, {"agent_id": 2, "role": "对手", "arc": "执念"}], "premise": "一个雨夜"}'
        got = novel_api._parse_cast(raw)
        self.assertEqual([c["agent_id"] for c in got["cast"]], [1, 2])
        self.assertEqual(got["premise"], "一个雨夜")

    def test_invalid_agent_ids_are_dropped(self) -> None:
        raw = '{"cast": [{"agent_id": 1}, {"agent_id": "bad"}, {"agent_id": 2}]}'
        got = novel_api._parse_cast(raw)
        self.assertEqual([c["agent_id"] for c in got["cast"]], [1, 2])

    def test_garbage_cast_returns_empty(self) -> None:
        got = novel_api._parse_cast("definitely not json")
        self.assertEqual(got["cast"], [])
        # And it still gives back something to render.
        self.assertTrue(got["premise"])


class AllocateBudgetTest(unittest.TestCase):
    def test_chapter_targets_sum_to_target(self) -> None:
        # 6 chapters at 1500 = 9000, asked for 30000 → each scales ~3.3x
        outline = [
            {"chapter": i, "title": f"c{i}", "target_words": 1500, "characters": [1]}
            for i in range(1, 7)
        ]
        scaled = novel_api._allocate_budgets(outline, 30000)
        self.assertEqual(sum(c["target_words"] for c in scaled), 30000)
        # And each chapter is bounded.
        for ch in scaled:
            self.assertGreaterEqual(ch["target_words"], 300)

    def test_zero_planned_keeps_targets(self) -> None:
        # An empty outline stays empty (caller deals with that).
        self.assertEqual(novel_api._allocate_budgets([], 10000), [])
        # A single chapter keeps its original target when the budget matches.
        outline = [{"chapter": 1, "title": "x", "target_words": 1500, "characters": []}]
        result = novel_api._allocate_budgets(outline, 1500)
        self.assertEqual(result[0]["target_words"], 1500)


# ---------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------


_CAST_RAW = (
    '{"cast": [{"agent_id": 1, "role": "主角", "arc": "一夜未眠"},'
    ' {"agent_id": 2, "role": "推动情节", "arc": "替人值班"}], "premise": "雨夜的小面馆"}'
)
_OUTLINE_RAW = (
    '{"chapters": ['
    '{"chapter": 1, "title": "夜班", "summary": "她接班。", "target_words": 1500, "characters": [1, 2]},'
    '{"chapter": 2, "title": "来电", "summary": "一个陌生电话。", "target_words": 1500, "characters": [1]}'
    "]}"
)
_CHAPTER_TEMPLATE = "正文章节内容：雨夜的灯光，{name} 站在面馆里。" * 3  # ~50 Chinese chars * 3 = 150 chars


def _scripted_structure(replies: list[str]):
    """Like _scripted, but for structure_fn: same call shape."""
    return _scripted(replies)


class RunNovelTest(unittest.TestCase):
    def setUp(self) -> None:
        novel_api.reset_jobs()
        self.cards = [
            _card(1, "甲一", age=42, job="面馆老板"),
            _card(2, "乙二", age=36, job="外卖员"),
        ]

    def test_run_shape_and_required_keys(self) -> None:
        author_calls: list[str] = []
        structure_calls: list[str] = []

        def structure(prompt: str) -> str:
            structure_calls.append(prompt)
            return _CAST_RAW if len(structure_calls) == 1 else _OUTLINE_RAW

        def author(prompt: str) -> str:
            author_calls.append(prompt)
            return _CHAPTER_TEMPLATE.replace("{name}", "甲一")

        result = novel_api.run_novel(
            city="",
            agent_ids=[1, 2],
            outline="雨夜的小面馆来了一个陌生的电话",
            target_words=8000,
            cards=self.cards,
            structure_fn=structure,
            author_fn=author,
            summary_fn=lambda p: "封面简介：一位面馆老板的雨夜。",
            progress=lambda p, m: None,
        )
        # Result contract
        for key in ("run_id", "title", "premise", "cast", "chapters", "outline", "style", "target_words", "stats", "created_at"):
            self.assertIn(key, result)
        self.assertEqual(result["target_words"], 8000)
        self.assertEqual(len(result["chapters"]), 2)
        for ch in result["chapters"]:
            self.assertIn("chapter", ch)
            self.assertIn("title", ch)
            self.assertIn("text", ch)
            self.assertIn("word_count", ch)
            self.assertIn("characters", ch)
            self.assertGreater(ch["word_count"], 0)
        # Cast covers every picked agent
        cast_ids = {c["agent_id"] for c in result["cast"]}
        self.assertEqual(cast_ids, {1, 2})
        # Stats line
        stats = result["stats"]
        self.assertEqual(stats["chapters"], 2)
        self.assertEqual(stats["target_words"], 8000)
        self.assertEqual(sum(c["word_count"] for c in result["chapters"]), stats["total_words"])
        # Cost: structure (2) + author (1 per chapter) + summary (1) = 5 calls
        self.assertEqual(len(structure_calls), 2)
        self.assertEqual(len(author_calls), 2)
        # Outline budgets are normalised to roughly the target
        outline_targets = [c["target_words"] for c in result["outline"]]
        self.assertAlmostEqual(sum(outline_targets), 8000, delta=50)

    def test_chapter_prompts_carry_the_persona(self) -> None:
        prompts: list[str] = []

        def structure(prompt: str) -> str:
            return _CAST_RAW if "premise" in prompt or "主角团" in prompt else _OUTLINE_RAW

        def author(prompt: str) -> str:
            prompts.append(prompt)
            return _CHAPTER_TEMPLATE.replace("{name}", "甲一")

        novel_api.run_novel(
            city="",
            agent_ids=[1, 2],
            outline="雨夜的小面馆来了一个陌生的电话",
            target_words=4000,
            cards=self.cards,
            structure_fn=structure,
            author_fn=author,
            summary_fn=lambda p: "",
            progress=lambda p, m: None,
        )
        # Both chapter prompts should mention the cast (chapter 1 has both,
        # chapter 2 has only #1 per the test outline).
        self.assertEqual(len(prompts), 2)
        self.assertIn("甲一", prompts[0])
        self.assertIn("乙二", prompts[0])
        self.assertIn("甲一", prompts[1])
        # And each chapter's summary should be embedded.
        self.assertIn("她接班", prompts[0])
        self.assertIn("陌生电话", prompts[1])

    def test_min_and_max_agent_limits(self) -> None:
        cards = [_card(i, f"人{i}") for i in range(1, 8)]
        for too_many in ([1] * (novel_api.MAX_AGENTS + 1),):
            with self.assertRaises(ValueError):
                novel_api.run_novel(
                    city="",
                    agent_ids=too_many,
                    outline="x",
                    target_words=4000,
                    cards=cards,
                    structure_fn=lambda p: _CAST_RAW,
                    author_fn=lambda p: "x",
                    summary_fn=lambda p: "",
                    progress=lambda p, m: None,
                )
        for too_few in ([1], []):
            with self.assertRaises(ValueError):
                novel_api.run_novel(
                    city="",
                    agent_ids=too_few,
                    outline="x",
                    target_words=4000,
                    cards=[_card(1, "甲一")],
                    structure_fn=lambda p: _CAST_RAW,
                    author_fn=lambda p: "x",
                    summary_fn=lambda p: "",
                    progress=lambda p, m: None,
                )

    def test_target_words_is_clamped(self) -> None:
        # Asking for 999 999 should be capped at MAX_TARGET_WORDS, not crash.
        def author(prompt: str) -> str:
            return "短。"

        def structure(prompt: str) -> str:
            return _CAST_RAW if "premise" in prompt or "主角团" in prompt else _OUTLINE_RAW

        result = novel_api.run_novel(
            city="",
            agent_ids=[1, 2],
            outline="x",
            target_words=999_999,
            cards=self.cards,
            structure_fn=structure,
            author_fn=author,
            summary_fn=lambda p: "",
            progress=lambda p, m: None,
        )
        self.assertEqual(result["target_words"], novel_api.MAX_TARGET_WORDS)

    def test_provider_failure_does_not_kill_the_run(self) -> None:
        # A summary call blowing up must not abort the whole novel.
        def structure(prompt: str) -> str:
            return _CAST_RAW if "premise" in prompt or "主角团" in prompt else _OUTLINE_RAW

        def author(prompt: str) -> str:
            return "正文。"

        def boom(_: str) -> str:
            raise RuntimeError("provider down")

        result = novel_api.run_novel(
            city="",
            agent_ids=[1, 2],
            outline="x",
            target_words=4000,
            cards=self.cards,
            structure_fn=structure,
            author_fn=author,
            summary_fn=boom,
            progress=lambda p, m: None,
        )
        self.assertEqual(result["back_cover"], "")
        self.assertGreater(len(result["chapters"]), 0)


# ---------------------------------------------------------------------------
# HTTP delegation
# ---------------------------------------------------------------------------


class HttpTest(unittest.TestCase):
    def setUp(self) -> None:
        novel_api.reset_jobs()

    def test_catalogue_endpoint(self) -> None:
        body, status = novel_api.handle_get("/api/games/novel/catalogue")
        self.assertEqual(status, 200)
        self.assertEqual(len(body["styles"]), len(novel_api.STYLE_PRESETS))
        self.assertEqual(body["min_agents"], novel_api.MIN_AGENTS)
        self.assertEqual(body["max_agents"], novel_api.MAX_AGENTS)
        self.assertEqual(body["min_target_words"], novel_api.MIN_TARGET_WORDS)

    def test_run_needs_a_non_empty_outline(self) -> None:
        body, status = novel_api.handle_post(
            "/api/games/novel/run",
            {"city": "wuzhen", "agent_ids": [1, 2], "outline": "", "target_words": 5000},
        )
        self.assertEqual(status, 400)
        self.assertIn("error", body)

    def test_run_rejects_target_words_outside_the_range(self) -> None:
        body, status = novel_api.handle_post(
            "/api/games/novel/run",
            {"city": "wuzhen", "agent_ids": [1, 2], "outline": "x", "target_words": 10},
        )
        self.assertEqual(status, 400)
        self.assertIn("error", body)

    def test_run_rejects_unknown_style(self) -> None:
        body, status = novel_api.handle_post(
            "/api/games/novel/run",
            {
                "city": "wuzhen",
                "agent_ids": [1, 2],
                "outline": "x",
                "target_words": 5000,
                "style_id": "nope",
            },
        )
        self.assertEqual(status, 400)
        self.assertIn("error", body)

    def test_run_rejects_too_few_agents(self) -> None:
        body, status = novel_api.handle_post(
            "/api/games/novel/run",
            {"city": "wuzhen", "agent_ids": [1], "outline": "x", "target_words": 5000},
        )
        self.assertEqual(status, 400)
        self.assertIn("error", body)

    def test_run_opens_a_job_and_finishes(self) -> None:
        fake = {
            "run_id": "abc",
            "city": "wuzhen",
            "title": "未命名",
            "chapters": [],
            "cast": [],
            "target_words": 5000,
            "stats": {"total_words": 0, "target_words": 5000, "chapters": 0},
            "created_at": 1.0,
        }
        with mock.patch("gaworld.apps.novel_api.run_novel", return_value=fake):
            body, status = novel_api.handle_post(
                "/api/games/novel/run",
                {"city": "wuzhen", "agent_ids": [1, 2], "outline": "x", "target_words": 5000},
            )
            self.assertEqual(status, 202)
            job_id = body["job_id"]
            for _ in range(400):
                record = novel_api.job_status(job_id)
                if record and record["status"] != "running":
                    break
                time.sleep(0.01)
        record, status = novel_api.handle_get(f"/api/games/novel/jobs/{job_id}")
        self.assertEqual(status, 200)
        self.assertEqual(record["status"], "done")
        self.assertEqual(record["result"]["run_id"], "abc")
        listing, status = novel_api.handle_get("/api/games/novel/runs")
        self.assertEqual(listing["runs"][0]["job_id"], job_id)

    def test_unknown_job_and_endpoints_are_404(self) -> None:
        self.assertEqual(novel_api.handle_get("/api/games/novel/jobs/nope")[1], 404)
        self.assertEqual(novel_api.handle_get("/api/games/novel/nope")[1], 404)
        self.assertEqual(novel_api.handle_post("/api/games/novel/nope", {})[1], 404)

    def test_games_api_forwards_the_novel_branch(self) -> None:
        body, status = games_api.handle_get("/api/games/novel/catalogue")
        self.assertEqual(status, 200)
        self.assertIn("styles", body)
        # And a POST that fails validation should be 400, not 404.
        body, status = games_api.handle_post("/api/games/novel/run", {})
        self.assertEqual(status, 400)
        self.assertIn("error", body)


# ---------------------------------------------------------------------------
# Story-line visualisation metrics
# ---------------------------------------------------------------------------


class CoOccurrenceTest(unittest.TestCase):
    """``co_occurrences`` drives the 同框关系 network view."""

    def test_pair_count_is_chapters_in_common(self) -> None:
        chs = [
            novel_api.Chapter(chapter=1, characters=[1, 2]),
            novel_api.Chapter(chapter=2, characters=[1, 2]),
            novel_api.Chapter(chapter=3, characters=[2, 3]),
            novel_api.Chapter(chapter=4, characters=[1, 3]),
        ]
        rows = novel_api.compute_co_occurrences(chs)
        by_pair = {(r["a"], r["b"]): r["count"] for r in rows}
        self.assertEqual(by_pair[(1, 2)], 2)
        self.assertEqual(by_pair[(1, 3)], 1)
        self.assertEqual(by_pair[(2, 3)], 1)

    def test_pairs_are_canonical_low_id_first(self) -> None:
        rows = novel_api.compute_co_occurrences([novel_api.Chapter(chapter=1, characters=[5, 2, 8])])
        # Each pair sorts with the lower id first.
        for row in rows:
            self.assertLess(row["a"], row["b"])

    def test_empty_cast_yields_no_rows(self) -> None:
        self.assertEqual(novel_api.compute_co_occurrences([]), [])


class PresenceTest(unittest.TestCase):
    """``presence`` drives the 角色弧线 chart."""

    def _ch(self, text: str, characters: list[int], word_count: int | None = None) -> novel_api.Chapter:
        return novel_api.Chapter(
            chapter=1,
            characters=characters,
            text=text,
            word_count=word_count if word_count is not None else novel_api.count_words(text),
        )

    def test_a_chapter_centered_on_one_character_scores_high(self) -> None:
        # Most paragraphs mention 闫然; she should dominate.
        text = (
            "闫然在厨房里切菜。\n\n"
            "门外有人敲门，闫然擦了擦手。\n\n"
            "是她的老邻居，闫然把门打开。"
        )
        ch = self._ch(text, characters=[1, 2])
        presence = novel_api.compute_presence(ch, {1: "闫然", 2: "李姐"})
        # Every paragraph mentions 闫然 → score saturates at 100.
        self.assertGreaterEqual(presence["1"], 90)
        # 李姐 is mentioned nowhere in the text.
        self.assertEqual(presence["2"], 0)

    def test_a_chapter_with_a_few_named_paragraphs_scores_low(self) -> None:
        # 1 paragraph mentions 闫然, 5 don't — score should be modest but > 0.
        text = (
            "甲店的灯还亮着。\n\n"
            "街上有风。\n\n"
            "闫然在门口站着。\n\n"
            "路人三三两两地走过。\n\n"
            "对面那家关着门。\n\n"
            "她拢了拢大衣。"
        )
        ch = self._ch(text, characters=[1])
        presence = novel_api.compute_presence(ch, {1: "闫然"})
        # 1 of 6 paragraphs names her — score is well below the saturation cap.
        self.assertGreater(presence["1"], 0)
        self.assertLessEqual(presence["1"], 100)

    def test_missing_name_yields_zero(self) -> None:
        ch = self._ch("闫然在厨房。", characters=[1])
        # Card 1 has no name in the lookup → presence falls back to 0.
        presence = novel_api.compute_presence(ch, {})
        self.assertEqual(presence["1"], 0)

    def test_empty_text_is_all_zero(self) -> None:
        ch = self._ch("", characters=[1, 2])
        presence = novel_api.compute_presence(ch, {1: "闫然", 2: "李姐"})
        self.assertEqual(presence["1"], 0)
        self.assertEqual(presence["2"], 0)

    def test_score_is_capped_at_100(self) -> None:
        # Every paragraph names the character — saturation.
        text = "闫然吃饭。" * 50
        ch = self._ch(text, characters=[1])
        presence = novel_api.compute_presence(ch, {1: "闫然"})
        self.assertLessEqual(presence["1"], 100)


class ResultShapeTest(unittest.TestCase):
    """The finished novel must carry presence + co_occurrences for the viz."""

    def test_run_includes_presence_per_chapter_and_co_occurrences(self) -> None:
        cards = [_card(1, "甲一"), _card(2, "乙二")]

        def structure(prompt: str) -> str:
            return _CAST_RAW if "premise" in prompt or "主角团" in prompt else _OUTLINE_RAW

        def author(prompt: str) -> str:
            return "甲一在厨房。\n\n乙二在客厅。"

        result = novel_api.run_novel(
            city="",
            agent_ids=[1, 2],
            outline="雨夜",
            target_words=4000,
            cards=cards,
            structure_fn=structure,
            author_fn=author,
            summary_fn=lambda p: "",
            progress=lambda p, m: None,
        )
        # Each chapter carries a presence dict keyed by stringified agent_id.
        for ch in result["chapters"]:
            self.assertIn("presence", ch)
            self.assertIsInstance(ch["presence"], dict)
            for cid in ch["characters"]:
                self.assertIn(str(cid), ch["presence"])
        # co_occurrences lists every pair that ever shared a chapter.
        co = result["co_occurrences"]
        self.assertEqual(len(co), 1)
        self.assertEqual(co[0], {"a": 1, "b": 2, "count": 1})


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
