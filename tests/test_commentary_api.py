"""Tests for 新闻评论 (gaworld.apps.commentary_api).

What we defend:

* **News resolution.** Paste mode requires a body; URL mode requires a URL.
  URL mode fetches via ``fetch_news_excerpt``; a fetch failure degrades to
  ``fetch_error`` set and falls back to the caller's pasted body when one was
  also handed in.
* **Per-resident prompt + parsing.** Each resident gets one prompt with the
  persona, the news, and where it came from; one model call per resident; a
  reply that doesn't parse degrades to ``其他`` with strength 0 instead of
  polluting the histogram.
* **Stats.** Stance counts, average strength, the strongest resident, and the
  count of residents who actually spoke fall out of the reactions, not out of
  a separate judge call.
* **HTTP delegation.** The documented shapes from
  ``/api/games/commentary/{catalogue, runs, jobs/<id>}`` and the 400/404
  contract.

No LLM is reached at runtime: ``comment_fn`` / ``summary_fn`` are injected, and
the roster / profile block are mocked.
"""

from __future__ import annotations

import time
import unittest
from unittest import mock

from gaworld.apps import commentary_api, games_api


PEOPLE = [
    {
        "id": 1,
        "name": "闫然",
        "age": 41,
        "gender": "男",
        "job": "美发店员",
        "residence": "A小区",
        "state": {},
        "hukou": "本地",
    },
    {
        "id": 2,
        "name": "林佳",
        "age": 28,
        "gender": "女",
        "job": "小学老师",
        "residence": "A小区",
        "state": {},
        "hukou": "本地",
    },
    {
        "id": 3,
        "name": "蒋颂",
        "age": 67,
        "gender": "男",
        "job": "退休",
        "residence": "B小区",
        "state": {},
        "hukou": "本地",
    },
]


def _say(stance: str, strength: int, comment: str) -> str:
    """A clean, parsed reply for one resident."""
    return f'{{"stance": "{stance}", "strength": {strength}, "comment": "{comment}"}}'


def _run_with_replies(replies: list[str], **kwargs):
    """Patch roster/profile and run one commentary with a scripted LLM."""
    index = {"i": 0}

    def comment_fn(prompt: str) -> str:
        text = replies[min(index["i"], len(replies) - 1)]
        index["i"] += 1
        return text

    with (
        mock.patch("gaworld.interview.roster.load_population", return_value=PEOPLE),
        mock.patch("gaworld.interview.roster.profile_block", return_value="档案内容"),
    ):
        return commentary_api.run_commentary(
            city="wuzhen",
            agent_ids=kwargs.pop("agent_ids", [1, 2, 3]),
            news=kwargs.pop("news", commentary_api.NewsItem(title="地铁涨价", body="正文", source="paste")),
            comment_fn=comment_fn,
            summary_fn=kwargs.pop("summary_fn", lambda p: "整体偏支持。"),
            **kwargs,
        )


# ---------------------------------------------------------------------------
# News resolution
# ---------------------------------------------------------------------------


class ResolveNewsTest(unittest.TestCase):
    def test_paste_mode_requires_a_body(self) -> None:
        with self.assertRaises(ValueError):
            commentary_api.resolve_news({})
        with self.assertRaises(ValueError):
            commentary_api.resolve_news({"title": "t"})

    def test_paste_mode_keeps_the_body(self) -> None:
        main, related = commentary_api.resolve_news({"title": "涨价", "body": "一段正文"})
        self.assertEqual(main.title, "涨价")
        self.assertEqual(main.body, "一段正文")
        self.assertEqual(main.source, "paste")
        self.assertEqual(main.url, "")
        self.assertEqual(related, [])

    def test_url_mode_rejects_a_non_url(self) -> None:
        with self.assertRaises(ValueError):
            commentary_api.resolve_news({"url": "not-a-url"})

    def test_url_mode_records_a_fetch_error_when_nothing_comes_back(self) -> None:
        with mock.patch(
            "gaworld.io.web_scrape.fetch_news_excerpt", return_value=("", "")
        ) as fetch:
            main, related = commentary_api.resolve_news({"url": "https://x.test/article"})
        fetch.assert_called_once()
        self.assertEqual(main.source, "url")
        self.assertTrue(main.fetch_error)
        self.assertIn("未能获取", main.body)
        self.assertEqual(related, [])

    def test_url_mode_falls_back_to_a_pasted_body_on_fetch_failure(self) -> None:
        with mock.patch(
            "gaworld.io.web_scrape.fetch_news_excerpt", return_value=("", "")
        ):
            main, _ = commentary_api.resolve_news(
                {"url": "https://x.test/article", "body": "备用正文"}
            )
        self.assertTrue(main.fetch_error)
        self.assertEqual(main.body, "备用正文")

    def test_url_mode_uses_the_fetched_body_when_it_works(self) -> None:
        with mock.patch(
            "gaworld.io.web_scrape.fetch_news_excerpt",
            return_value=("抓到的正文很长" * 50, "网页标题"),
        ):
            main, _ = commentary_api.resolve_news({"url": "https://x.test/article"})
        self.assertEqual(main.fetch_error, "")
        self.assertEqual(main.title, "网页标题")
        self.assertTrue(main.body.startswith("抓到的正文"))

    def test_long_body_is_truncated(self) -> None:
        body = "x" * 7000
        main, _ = commentary_api.resolve_news({"body": body})
        self.assertLessEqual(len(main.body), 6000)

    def test_array_form_picks_first_as_main_and_rest_as_related(self) -> None:
        main, related = commentary_api.resolve_news(
            {"news": [
                {"body": "主", "title": "主"},
                {"body": "背 1", "title": "相关 1"},
                {"body": "背 2", "title": "相关 2"},
            ]}
        )
        self.assertEqual(main.title, "主")
        self.assertEqual([r.title for r in related], ["相关 1", "相关 2"])

    def test_related_is_capped_at_max_related(self) -> None:
        items = [{"body": f"r{i}", "title": f"R{i}"} for i in range(10)]
        main, related = commentary_api.resolve_news({"body": "m", "related": items})
        self.assertEqual(main.title, "")
        self.assertEqual(len(related), commentary_api.MAX_RELATED)

    def test_a_related_entry_with_neither_body_nor_url_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            commentary_api.resolve_news(
                {"body": "m", "related": [{"title": "no body"}]}
            )


# ---------------------------------------------------------------------------
# Comment parsing
# ---------------------------------------------------------------------------


class ParseCommentTest(unittest.TestCase):
    def test_clean_json(self) -> None:
        got = commentary_api.parse_comment(_say("支持", 75, "我看挺好的。"))
        self.assertEqual(got["stance"], "支持")
        self.assertEqual(got["strength"], 75)
        self.assertEqual(got["comment"], "我看挺好的。")

    def test_off_vocabulary_stance_falls_into_other(self) -> None:
        got = commentary_api.parse_comment(_say("超级棒", 50, "好"))
        self.assertEqual(got["stance"], commentary_api.OTHER_STANCE)

    def test_prose_with_a_substring_match_is_rescued(self) -> None:
        # Real runs sometimes answer in prose; a stance word buried in prose
        # should still be picked up before the catch-all bucket.
        got = commentary_api.parse_comment('{"stance": "保持中立", "strength": 30, "comment": "嗯"}')
        self.assertEqual(got["stance"], "中立")

    def test_strength_is_clamped(self) -> None:
        self.assertEqual(commentary_api.parse_comment(_say("支持", 900, ""))["strength"], 100)
        self.assertEqual(commentary_api.parse_comment(_say("支持", -5, ""))["strength"], 0)

    def test_broken_reply_degrades_silently(self) -> None:
        got = commentary_api.parse_comment("模型今天不想说话")
        self.assertEqual(got["stance"], commentary_api.OTHER_STANCE)
        self.assertEqual(got["strength"], 0)
        # We don't echo the raw text into the comment: that would let a model
        # "speak" by simply failing to reply, and inflate `spoke`.
        self.assertEqual(got["comment"], "")


# ---------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------


class RunCommentaryTest(unittest.TestCase):
    def test_every_resident_speaks_once(self) -> None:
        replies = [
            _say("支持", 80, "挺好"),
            _say("反对", 60, "不行"),
            _say("中立", 30, "观望"),
        ]
        run = _run_with_replies(replies)
        self.assertEqual(len(run["nodes"]), 3)
        self.assertEqual([n["stance"] for n in run["nodes"]], ["支持", "反对", "中立"])

    def test_stats_aggregate_stance_counts_and_strength(self) -> None:
        replies = [
            _say("支持", 90, "好"),
            _say("反对", 50, "不好"),
            _say("中立", 30, "不清楚"),
        ]
        run = _run_with_replies(replies)
        stats = run["stats"]
        self.assertEqual(stats["total"], 3)
        self.assertEqual(stats["spoke"], 3)
        self.assertEqual(
            stats["stance_counts"],
            {"支持": 1, "反对": 1, "中立": 1, "质疑": 0, "其他": 0},
        )
        self.assertAlmostEqual(stats["avg_strength"], (90 + 50 + 30) / 3, places=1)
        self.assertEqual(stats["strongest"]["agent_id"], 1)
        self.assertEqual(stats["strongest"]["stance"], "支持")

    def test_a_broken_reply_lands_in_other_and_does_not_crash_the_run(self) -> None:
        replies = ["模型今天不想说话", _say("支持", 70, "ok"), _say("反对", 60, "nope")]
        run = _run_with_replies(replies)
        nodes = {n["agent_id"]: n for n in run["nodes"]}
        self.assertEqual(nodes[1]["stance"], commentary_api.OTHER_STANCE)
        self.assertEqual(nodes[1]["strength"], 0)
        self.assertEqual(nodes[2]["stance"], "支持")
        self.assertEqual(nodes[3]["stance"], "反对")
        self.assertEqual(run["stats"]["stance_counts"]["其他"], 1)
        self.assertEqual(run["stats"]["spoke"], 2)

    def test_a_failing_summary_does_not_fail_the_run(self) -> None:
        def boom(prompt: str) -> str:
            raise RuntimeError("provider down")

        with (
            mock.patch("gaworld.interview.roster.load_population", return_value=PEOPLE),
            mock.patch("gaworld.interview.roster.profile_block", return_value="档案内容"),
        ):
            run = commentary_api.run_commentary(
                city="wuzhen",
                agent_ids=[1, 2],
                news=commentary_api.NewsItem(title="t", body="b", source="paste"),
                comment_fn=lambda p: _say("支持", 70, "ok"),
                summary_fn=boom,
            )
        self.assertEqual(run["summary"], "")
        self.assertEqual(run["stats"]["total"], 2)

    def test_prompt_carries_persona_title_body_and_source(self) -> None:
        captured: list[str] = []

        def comment_fn(prompt: str) -> str:
            captured.append(prompt)
            return _say("支持", 70, "ok")

        news = commentary_api.NewsItem(title="地铁涨价", body="正文内容", source="paste")
        with (
            mock.patch("gaworld.interview.roster.load_population", return_value=PEOPLE[:1]),
            mock.patch("gaworld.interview.roster.profile_block", return_value="**性格**：平和"),
        ):
            commentary_api.run_commentary(
                city="wuzhen", agent_ids=[1], news=news, comment_fn=comment_fn, summary_fn=lambda p: ""
            )
        self.assertEqual(len(captured), 1)
        prompt = captured[0]
        self.assertIn("闫然", prompt)
        self.assertIn("平和", prompt)
        self.assertIn("地铁涨价", prompt)
        self.assertIn("正文内容", prompt)
        self.assertIn("别人直接贴给你的", prompt)  # source line for paste mode

    def test_prompt_for_url_mode_mentions_the_url(self) -> None:
        captured: list[str] = []

        def comment_fn(prompt: str) -> str:
            captured.append(prompt)
            return _say("支持", 70, "ok")

        news = commentary_api.NewsItem(title="t", body="b", source="url", url="https://x.test/a")
        with (
            mock.patch("gaworld.interview.roster.load_population", return_value=PEOPLE[:1]),
            mock.patch("gaworld.interview.roster.profile_block", return_value="档案"),
        ):
            commentary_api.run_commentary(
                city="wuzhen", agent_ids=[1], news=news, comment_fn=comment_fn, summary_fn=lambda p: ""
            )
        self.assertIn("https://x.test/a", captured[0])
        self.assertIn("你是从文章里读到它的", captured[0])

    def test_related_news_appears_in_the_prompt_but_does_not_change_stats(self) -> None:
        captured: list[str] = []

        def comment_fn(prompt: str) -> str:
            captured.append(prompt)
            return _say("支持", 70, "只对主新闻表态")

        related = [
            commentary_api.NewsItem(title="相关 A", body="背景段 A", source="paste"),
            commentary_api.NewsItem(title="相关 B", body="背景段 B" * 200, source="paste"),
        ]
        with (
            mock.patch("gaworld.interview.roster.load_population", return_value=PEOPLE[:1]),
            mock.patch("gaworld.interview.roster.profile_block", return_value="档案"),
        ):
            run = commentary_api.run_commentary(
                city="wuzhen",
                agent_ids=[1],
                news=commentary_api.NewsItem(title="主", body="主新闻正文", source="paste"),
                related=related,
                comment_fn=comment_fn,
                summary_fn=lambda p: "",
            )
        # The prompt carries the related block AND the instruction that
        # related items are background only.
        self.assertIn("【相关阅读", captured[0])
        self.assertIn("《相关 A》", captured[0])
        self.assertIn("相关 B", captured[0])
        self.assertIn("只对上面这条主新闻表态", captured[0])
        # The very long B body should be truncated, not blow the budget.
        self.assertLess(len(captured[0]), 4000)
        # Result round-trips the related list and the stats still cover one
        # resident × the main news only.
        self.assertEqual(len(run["related"]), 2)
        self.assertEqual(run["related"][0]["title"], "相关 A")
        self.assertEqual(run["stats"]["total"], 1)
        self.assertEqual(run["stats"]["stance_counts"]["支持"], 1)

    def test_too_many_related_items_are_silently_truncated(self) -> None:
        related = [
            commentary_api.NewsItem(title=f"R{i}", body="b", source="paste")
            for i in range(20)
        ]
        with (
            mock.patch("gaworld.interview.roster.load_population", return_value=PEOPLE[:1]),
            mock.patch("gaworld.interview.roster.profile_block", return_value="档案"),
        ):
            run = commentary_api.run_commentary(
                city="wuzhen",
                agent_ids=[1],
                news=commentary_api.NewsItem(title="主", body="主", source="paste"),
                related=related,
                comment_fn=lambda p: _say("中立", 50, "ok"),
                summary_fn=lambda p: "",
            )
        self.assertEqual(len(run["related"]), commentary_api.MAX_RELATED)

    def test_an_empty_pick_is_a_value_error(self) -> None:
        with (
            mock.patch("gaworld.interview.roster.load_population", return_value=PEOPLE),
            mock.patch("gaworld.interview.roster.profile_block", return_value="x"),
        ):
            with self.assertRaises(ValueError):
                commentary_api.run_commentary(
                    city="wuzhen",
                    agent_ids=[],
                    news=commentary_api.NewsItem(title="t", body="b", source="paste"),
                )


# ---------------------------------------------------------------------------
# HTTP delegation
# ---------------------------------------------------------------------------


class HttpTest(unittest.TestCase):
    def setUp(self) -> None:
        commentary_api.reset_jobs()

    def test_catalogue_lists_stances_and_max_agents(self) -> None:
        body, status = commentary_api.handle_get("/api/games/commentary/catalogue")
        self.assertEqual(status, 200)
        self.assertIn("支持", body["stances"])
        self.assertIn("反对", body["stances"])
        self.assertEqual(body["max_agents"], commentary_api.MAX_AGENTS)

    def test_run_needs_at_least_one_resident(self) -> None:
        body, status = commentary_api.handle_post(
            "/api/games/commentary/run", {"city": "wuzhen", "agent_ids": [], "body": "x"}
        )
        self.assertEqual(status, 400)
        self.assertIn("error", body)

    def test_run_needs_some_news(self) -> None:
        body, status = commentary_api.handle_post(
            "/api/games/commentary/run", {"city": "wuzhen", "agent_ids": [1]}
        )
        self.assertEqual(status, 400)
        self.assertIn("error", body)

    def test_run_opens_a_job_and_finishes(self) -> None:
        fake = {
            "run_id": "abc",
            "city": "wuzhen",
            "news": {"title": "t", "body": "b", "source": "paste", "url": "", "fetch_error": ""},
            "nodes": [],
            "stats": {"total": 0, "spoke": 0, "stance_counts": {}, "avg_strength": 0.0, "strongest": None},
            "summary": "",
            "created_at": 1.0,
        }
        with mock.patch("gaworld.apps.commentary_api.run_commentary", return_value=fake):
            body, status = commentary_api.handle_post(
                "/api/games/commentary/run",
                {"city": "wuzhen", "agent_ids": [1, 2], "body": "正文"},
            )
            self.assertEqual(status, 202)
            job_id = body["job_id"]
            for _ in range(200):
                record = commentary_api.job_status(job_id)
                if record and record["status"] != "running":
                    break
                time.sleep(0.01)
        record, status = commentary_api.handle_get(f"/api/games/commentary/jobs/{job_id}")
        self.assertEqual(status, 200)
        self.assertEqual(record["status"], "done")
        self.assertEqual(record["result"]["run_id"], "abc")
        listing, status = commentary_api.handle_get("/api/games/commentary/runs")
        self.assertEqual(status, 200)
        self.assertEqual(listing["runs"][0]["job_id"], job_id)

    def test_unknown_job_and_endpoints_are_404(self) -> None:
        self.assertEqual(commentary_api.handle_get("/api/games/commentary/jobs/nope")[1], 404)
        self.assertEqual(commentary_api.handle_get("/api/games/commentary/nope")[1], 404)
        self.assertEqual(commentary_api.handle_post("/api/games/commentary/nope", {})[1], 404)

    def test_routing_through_games_api(self) -> None:
        # The /api/games/commentary/ branch lives in games_api; verify it
        # actually delegates rather than returning a 404 from the host.
        body, status = games_api.handle_get("/api/games/commentary/catalogue")
        self.assertEqual(status, 200)
        self.assertIn("stances", body)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
