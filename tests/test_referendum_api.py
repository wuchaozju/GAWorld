"""Tests for 公投局 (gaworld.apps.referendum_api).

What we defend:

* every voter is asked exactly twice — private, then public — in that order;
* the public prompt carries the tally, the loudest quotes from round one,
  the voter's own private position, and the campaign line when there is one;
* the campaign line is never shown as fact, and an absent one adds nothing;
* stances are coerced onto the three-way vocabulary (赞成 / 同意 / 中立 …)
  and an unreadable ballot lands on neither side of the margin;
* the tally, the margin, the swing and the flip list match the ballots;
* a failing digest does not fail the vote;
* HTTP delegation returns the documented shapes and the 400/404 contract,
  including the ``/api/games/referendum/`` branch in ``games_api``.

No LLM is reached: ``answer_fn`` / ``summary_fn`` are injected and the roll
is handed in directly.
"""

from __future__ import annotations

import time
import unittest
from unittest import mock

from gaworld.apps import games_api, referendum_api

_SURNAMES = "甲乙丙丁戊己庚辛"


def _roll(n: int = 4) -> list[referendum_api.Voter]:
    return [
        referendum_api.Voter(
            agent_id=i,
            name=f"{_SURNAMES[i - 1]}{i}",
            age=30 + i,
            job="客服专员",
            residence="A小区",
            persona_text=f"你是{_SURNAMES[i - 1]}{i}，{30 + i}岁。",
        )
        for i in range(1, n + 1)
    ]


def _ballot(stance: str, strength: int = 60, say: str = "就这样") -> str:
    return f'{{"stance": "{stance}", "strength": {strength}, "say": "{say}"}}'


def _always(reply: str):
    calls: list[str] = []

    def fn(prompt: str) -> str:
        calls.append(prompt)
        return reply

    fn.calls = calls  # type: ignore[attr-defined]
    return fn


class RoundsTest(unittest.TestCase):
    def test_everyone_votes_twice_private_then_public(self) -> None:
        answer = _always(_ballot("支持"))
        run = referendum_api.run_referendum(
            city="",
            agent_ids=[],
            motion_id="waste",
            voters=_roll(4),
            answer_fn=answer,
            summary_fn=lambda p: "简报",
        )
        calls = answer.calls  # type: ignore[attr-defined]
        self.assertEqual(len(calls), 8)
        self.assertTrue(all("现在还没人知道别人的想法" in c for c in calls[:4]))
        self.assertTrue(all("现在是正式表决" in c for c in calls[4:]))
        self.assertEqual(run["summary"], "简报")
        self.assertEqual(run["stats"]["total"], 4)

    def test_public_prompt_carries_tally_quotes_and_own_position(self) -> None:
        def answer(prompt: str) -> str:
            if "现在还没人知道" in prompt:
                return (
                    _ballot("反对", 95, "建在我家楼下凭什么")
                    if "你是甲1" in prompt
                    else _ballot("支持", 70, "省钱")
                )
            return _ballot("支持")

        run = referendum_api.run_referendum(
            city="",
            agent_ids=[],
            motion_id="waste",
            voters=_roll(3),
            answer_fn=answer,
            summary_fn=lambda p: "",
        )
        # Re-run just to capture the public prompt text.
        captured: list[str] = []

        def spy(prompt: str) -> str:
            captured.append(prompt)
            return (
                _ballot("反对", 95, "建在我家楼下凭什么") if "现在还没人知道" in prompt else _ballot("支持")
            )

        referendum_api.run_referendum(
            city="",
            agent_ids=[],
            motion_id="waste",
            voters=_roll(3),
            answer_fn=spy,
            summary_fn=lambda p: "",
        )
        public = captured[3]
        self.assertIn("支持 0 人", public)
        self.assertIn("反对 3 人", public)
        self.assertIn("建在我家楼下凭什么", public)  # a round-one quote
        self.assertIn("你刚才私下的想法是「反对」", public)
        self.assertEqual(len(run["quotes"]), 3)  # 1 against + 2 for

    def test_campaign_line_is_shown_as_a_leaflet_and_is_optional(self) -> None:
        captured: list[str] = []

        def spy(prompt: str) -> str:
            captured.append(prompt)
            return _ballot("支持")

        referendum_api.run_referendum(
            city="",
            agent_ids=[],
            motion_id="fee",
            campaign="不涨物业费，电梯停两个月",
            voters=_roll(2),
            answer_fn=spy,
            summary_fn=lambda p: "",
        )
        public = captured[2]
        self.assertIn("有人在群里和电梯口贴出了这样一句话", public)
        self.assertIn("不涨物业费，电梯停两个月", public)

        captured.clear()
        referendum_api.run_referendum(
            city="",
            agent_ids=[],
            motion_id="fee",
            voters=_roll(2),
            answer_fn=spy,
            summary_fn=lambda p: "",
        )
        self.assertNotIn("贴出了这样一句话", captured[2])

    def test_flips_are_recorded_with_the_reason(self) -> None:
        def answer(prompt: str) -> str:
            if "现在还没人知道" in prompt:
                return _ballot("反对", 40, "不太想要")
            return _ballot("支持", 55, "大家都说好，那就这样吧") if "你是甲1" in prompt else _ballot("反对")

        run = referendum_api.run_referendum(
            city="",
            agent_ids=[],
            motion_id="waste",
            voters=_roll(3),
            answer_fn=answer,
            summary_fn=lambda p: "",
        )
        self.assertEqual(len(run["flips"]), 1)
        flip = run["flips"][0]
        self.assertEqual((flip["agent_id"], flip["from"], flip["to"]), (1, "反对", "支持"))
        self.assertIn("大家都说好", flip["say"])
        self.assertEqual(run["stats"]["swing"], 1)
        self.assertEqual(run["stats"]["flips"], 1)

    def test_an_unreadable_ballot_is_asked_once_more(self) -> None:
        replies = iter(["模型今天不想说话", _ballot("反对", 70, "不行")])
        voters = _roll(1) + _roll(1)  # two voters, one prompt each round
        voters[1].agent_id, voters[1].name = 2, "乙2"
        calls: list[str] = []

        def answer(prompt: str) -> str:
            calls.append(prompt)
            if len(calls) <= 2:  # the first voter's private round: fail, then parse
                return next(replies)
            return _ballot("支持")

        run = referendum_api.run_referendum(
            city="",
            agent_ids=[],
            motion_id="waste",
            voters=voters,
            answer_fn=answer,
            summary_fn=lambda p: "",
        )
        # 2 private (one retried) + 2 public = 5 calls, and no lost ballot.
        self.assertEqual(len(calls), 5)
        self.assertEqual(run["voters"][0]["private"]["stance"], "反对")

    def test_a_retry_that_also_fails_is_not_asked_a_third_time(self) -> None:
        answer = _always("模型今天不想说话")
        run = referendum_api.run_referendum(
            city="",
            agent_ids=[],
            motion_id="waste",
            voters=_roll(2),
            answer_fn=answer,
            summary_fn=lambda p: "",
        )
        self.assertEqual(len(answer.calls), 8)  # type: ignore[attr-defined]
        self.assertEqual(run["stats"]["public"][referendum_api.OTHER_STANCE], 2)

    def test_an_undecided_voter_is_not_told_their_view_was_other(self) -> None:
        captured: list[str] = []

        def spy(prompt: str) -> str:
            captured.append(prompt)
            return "读不出来的回复"

        referendum_api.run_referendum(
            city="",
            agent_ids=[],
            motion_id="waste",
            voters=_roll(2),
            answer_fn=spy,
            summary_fn=lambda p: "",
        )
        public = captured[4]
        self.assertIn("你刚才没拿定主意", public)
        self.assertNotIn("想法是「其他」", public)

    def test_a_failing_digest_does_not_fail_the_vote(self) -> None:
        def boom(prompt: str) -> str:
            raise RuntimeError("provider down")

        run = referendum_api.run_referendum(
            city="",
            agent_ids=[],
            motion_id="market",
            voters=_roll(2),
            answer_fn=_always(_ballot("支持")),
            summary_fn=boom,
        )
        self.assertEqual(run["summary"], "")
        self.assertEqual(run["stats"]["result"], "通过")

    def test_two_voters_minimum(self) -> None:
        with self.assertRaises(ValueError):
            referendum_api.run_referendum(
                city="", agent_ids=[], motion_id="waste", voters=_roll(1), answer_fn=_always("x")
            )


class TallyTest(unittest.TestCase):
    def test_counts_margin_and_result(self) -> None:
        votes = [
            {"stance": "支持", "strength": 90, "say": ""},
            {"stance": "支持", "strength": 60, "say": ""},
            {"stance": "反对", "strength": 80, "say": ""},
            {"stance": "弃权", "strength": 10, "say": ""},
        ]
        counts = referendum_api.tally(votes)
        self.assertEqual((counts["支持"], counts["反对"], counts["弃权"]), (2, 1, 1))
        self.assertEqual(counts["avg_strength"], round((90 + 60 + 80) / 3, 1))
        self.assertEqual(counts["polarised"], 2)

    def test_an_unreadable_ballot_lands_on_neither_side(self) -> None:
        run = referendum_api.run_referendum(
            city="",
            agent_ids=[],
            motion_id="waste",
            voters=_roll(2),
            answer_fn=_always("模型今天不想说话"),
            summary_fn=lambda p: "",
        )
        public = run["stats"]["public"]
        self.assertEqual(public["支持"], 0)
        self.assertEqual(public["反对"], 0)
        self.assertEqual(public[referendum_api.OTHER_STANCE], 2)
        self.assertEqual(run["stats"]["result"], "平票")
        self.assertEqual(run["stats"]["margin"], 0)


class ParseTest(unittest.TestCase):
    def test_clean_ballot(self) -> None:
        got = referendum_api.parse_vote(_ballot("反对", 88, "离我家太近"))
        self.assertEqual(got, {"stance": "反对", "strength": 88, "say": "离我家太近"})

    def test_synonyms_are_coerced(self) -> None:
        self.assertEqual(referendum_api.parse_vote('{"stance": "赞成"}')["stance"], "支持")
        self.assertEqual(referendum_api.parse_vote('{"stance": "同意"}')["stance"], "支持")
        self.assertEqual(referendum_api.parse_vote('{"stance": "保持中立"}')["stance"], "弃权")

    def test_a_negated_stance_is_not_read_as_its_opposite(self) -> None:
        # "不支持" contains "支持": a substring pass would record a yes vote.
        self.assertEqual(referendum_api.parse_vote('{"stance": "不支持"}')["stance"], "反对")
        self.assertEqual(referendum_api.parse_vote('{"stance": "不同意"}')["stance"], "反对")
        self.assertEqual(referendum_api.parse_vote('{"stance": "不赞成这个方案"}')["stance"], "反对")

    def test_strength_is_clamped_and_garbage_is_othered(self) -> None:
        self.assertEqual(referendum_api.parse_vote('{"stance": "支持", "strength": 900}')["strength"], 100)
        self.assertEqual(referendum_api.parse_vote('{"stance": "支持", "strength": "强"}')["strength"], 50)
        self.assertEqual(referendum_api.parse_vote("随便说点什么")["stance"], referendum_api.OTHER_STANCE)

    def test_a_stray_closing_brace_still_parses(self) -> None:
        got = referendum_api.parse_vote('{"stance": "弃权", "strength": 20}} 就这样')
        self.assertEqual(got["stance"], "弃权")


class MotionTest(unittest.TestCase):
    def test_bank_entries_are_playable(self) -> None:
        for item in referendum_api.list_motions():
            self.assertTrue(item["title"])
            self.assertTrue(item["text"])

    def test_custom_and_unknown(self) -> None:
        got = referendum_api.resolve_motion("", {"title": "封路", "text": "要不要封这条路"})
        self.assertEqual(got["title"], "封路")
        with self.assertRaises(ValueError):
            referendum_api.resolve_motion("", {"title": "x", "text": "  "})
        with self.assertRaises(ValueError):
            referendum_api.resolve_motion("nope")


class HttpTest(unittest.TestCase):
    def setUp(self) -> None:
        referendum_api.reset_jobs()

    def test_catalogue_endpoint(self) -> None:
        body, status = referendum_api.handle_get("/api/games/referendum/catalogue")
        self.assertEqual(status, 200)
        self.assertEqual(len(body["motions"]), len(referendum_api.MOTION_BANK))
        self.assertEqual(body["stances"], list(referendum_api.STANCES))

    def test_run_needs_two_voters_and_a_known_motion(self) -> None:
        body, status = referendum_api.handle_post(
            "/api/games/referendum/run", {"agent_ids": [1], "motion_id": "waste"}
        )
        self.assertEqual(status, 400)
        self.assertIn("error", body)
        _, status = referendum_api.handle_post(
            "/api/games/referendum/run", {"agent_ids": [1, 2], "motion_id": "nope"}
        )
        self.assertEqual(status, 400)

    def test_run_opens_a_job_and_finishes(self) -> None:
        fake = {"run_id": "abc", "created_at": 1.0, "voters": [], "flips": [], "stats": {"result": "通过"}}
        with mock.patch("gaworld.apps.referendum_api.run_referendum", return_value=fake):
            body, status = referendum_api.handle_post(
                "/api/games/referendum/run",
                {"city": "wuzhen", "agent_ids": [1, 2], "motion_id": "waste"},
            )
            self.assertEqual(status, 200)
            job_id = body["job_id"]
            for _ in range(200):
                record = referendum_api.job_status(job_id)
                if record and record["status"] != "running":
                    break
                time.sleep(0.01)
        record, status = referendum_api.handle_get(f"/api/games/referendum/jobs/{job_id}")
        self.assertEqual(status, 200)
        self.assertEqual(record["result"]["run_id"], "abc")
        listing, _ = referendum_api.handle_get("/api/games/referendum/runs")
        self.assertEqual(listing["runs"][0]["result"], "通过")

    def test_unknown_job_and_endpoints_are_404(self) -> None:
        self.assertEqual(referendum_api.handle_get("/api/games/referendum/jobs/nope")[1], 404)
        self.assertEqual(referendum_api.handle_get("/api/games/referendum/nope")[1], 404)
        self.assertEqual(referendum_api.handle_post("/api/games/referendum/nope", {})[1], 404)

    def test_games_api_forwards_the_branch(self) -> None:
        body, status = games_api.handle_get("/api/games/referendum/catalogue")
        self.assertEqual(status, 200)
        self.assertIn("motions", body)
        _, status = games_api.handle_post("/api/games/referendum/run", {})
        self.assertEqual(status, 400)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
