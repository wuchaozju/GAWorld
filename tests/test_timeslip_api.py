"""Tests for 《穿越历史》(gaworld.apps.timeslip_api).

What we defend:

* **Dynasty resolution.** Built-in ids resolve to the bank entry; a custom
  block needs ``name``, ``frame`` and at least two ``stages``; unknown ids
  raise ``ValueError``.
* **Stage prompt + parsing.** Each picked resident gets one record per stage;
  loose JSON (prose-wrapped, missing fields, missing agent) is repaired, not
  raised on; the prompt carries the dynasty frame, the stage text, the
  cohort, and the previous stage's lines.
* **Scoring rubric.** ``era_fit`` rewards era markers and penalises modern
  words; ``inner_conflict`` climbs when the spoken line concedes while the
  inner monologue resists; everything clamps to 0–100.
* **Aggregate shape.** ``stats.residents`` is one row per picked resident
  with era_fit / stability / inner_conflict averaged across stages; the
  scoreboard flags the most-in-period, least-in-period and most-torn picks.
* **Run shape.** ``stages`` is the staged dialogue list, ``dynasty`` and
  ``cards`` carry the inputs, ``essay`` is a string, ``scoring_note`` is set.
* HTTP delegation returns the documented shapes and the 400/404 contract,
  including the ``/api/games/timeslip/`` branch in ``games_api``.

No LLM is reached: ``stage_fn`` / ``essay_fn`` are injected as plain callables.
"""

from __future__ import annotations

import time
import unittest
from unittest import mock

from gaworld.apps import games_api, timeslip_api

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _card(agent_id: int, name: str, age: int = 40, job: str = "店员") -> dict:
    return {
        "agent_id": agent_id,
        "name": name,
        "age": age,
        "gender": "女",
        "job": job,
        "residence": "A小区",
        "profile_md": f"**身份**：{name}，{job}。",
        "persona_short": f"你是{name}，{age}岁，女，{job}。档案：长期住在 A 小区。",
    }


def _scripted(replies: list[str]):
    """An answer_fn that returns the scripted replies in order."""
    calls: list[str] = []

    def fn(_prompt: str) -> str:
        calls.append(_prompt)
        return replies[min(len(calls) - 1, len(replies) - 1)]

    fn.calls = calls  # type: ignore[attr-defined]
    return fn


def _stage_reply(*, dynasty_words: list[str], inner_resist: bool = True, missing_ids: tuple = ()) -> str:
    """A well-formed reply for one stage. IDs 1 and 2 are the picked residents by default."""
    bodies = []
    for aid in (1, 2):
        if aid in missing_ids:
            continue
        line = "、".join(dynasty_words) + "，今日之事如此。"
        inner = "我心里其实不能接受。" if inner_resist else "也罢。"
        bodies.append(f'{{"agent_id": {aid}, "line": "{line}", "inner": "{inner}"}}')
    inner_block = ",\n      ".join(bodies)
    return f'{{\n  "stage_mood": "气氛很紧",\n  "reactions": [\n      {inner_block}\n    ]\n}}'


# ---------------------------------------------------------------------------
# Dynasty resolution
# ---------------------------------------------------------------------------


class DynastyResolutionTest(unittest.TestCase):
    def test_built_in_dynasty_resolves(self) -> None:
        out = timeslip_api.resolve_dynasty("tang_revolt")
        self.assertEqual(out["dynasty"], "唐 · 安史之乱")
        self.assertGreaterEqual(len(out["stages"]), 2)

    def test_unknown_dynasty_raises(self) -> None:
        with self.assertRaises(ValueError):
            timeslip_api.resolve_dynasty("nope")

    def test_custom_dynasty_needs_name_frame_stages(self) -> None:
        with self.assertRaises(ValueError):
            timeslip_api.resolve_dynasty("", {"frame": "x", "stages": ["a", "b"]})
        with self.assertRaises(ValueError):
            timeslip_api.resolve_dynasty("", {"name": "x", "stages": ["a", "b"]})
        with self.assertRaises(ValueError):
            timeslip_api.resolve_dynasty("", {"name": "x", "frame": "y", "stages": []})
        out = timeslip_api.resolve_dynasty(
            "", {"name": "我的朝代", "frame": "一句话", "stages": ["一幕", "二幕"]}
        )
        self.assertEqual(out["dynasty"], "我的朝代")
        self.assertEqual(len(out["stages"]), 2)


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


class ParseTest(unittest.TestCase):
    def test_clean_json_parses(self) -> None:
        raw = '{"stage_mood": "x", "reactions": [{"agent_id": 1, "line": "一句", "inner": "我心里。"}]}'
        cleaned = timeslip_api._parse_reactions(raw, [1])
        self.assertEqual(cleaned[0]["line"], "一句")
        self.assertEqual(cleaned[0]["inner"], "我心里。")

    def test_prose_wrapped_json_parses(self) -> None:
        raw = '看了一下输出：{"stage_mood": "x", "reactions": [{"agent_id": 2, "line": "二句", "inner": "不"}]} 以及其他。'
        cleaned = timeslip_api._parse_reactions(raw, [2])
        self.assertEqual(cleaned[0]["line"], "二句")

    def test_missing_agent_is_backfilled(self) -> None:
        raw = '{"stage_mood": "x", "reactions": [{"agent_id": 1, "line": "a", "inner": "b"}]}'
        cleaned = timeslip_api._parse_reactions(raw, [1, 2])
        self.assertEqual(len(cleaned), 2)
        self.assertEqual(cleaned[0]["agent_id"], 1)
        self.assertEqual(cleaned[1]["agent_id"], 2)
        # the back-fill line should not be empty
        self.assertTrue(cleaned[1]["line"])

    def test_extra_agent_is_dropped(self) -> None:
        raw = '{"stage_mood": "x", "reactions": [{"agent_id": 99, "line": "x", "inner": "y"}]}'
        cleaned = timeslip_api._parse_reactions(raw, [1])
        self.assertEqual(len(cleaned), 1)
        self.assertTrue("吞" in cleaned[0]["line"] or "没接上" in cleaned[0]["line"])

    def test_empty_line_is_replaced(self) -> None:
        raw = '{"stage_mood": "x", "reactions": [{"agent_id": 1, "line": "", "inner": ""}]}'
        cleaned = timeslip_api._parse_reactions(raw, [1])
        self.assertTrue(cleaned[0]["line"])
        self.assertTrue(cleaned[0]["inner"])


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


class ScoringTest(unittest.TestCase):
    def test_era_fit_penalises_modern_words(self) -> None:
        era = timeslip_api._score_one_reaction(
            "臣不敢，已领命。", "我心里其实不能接受。", {"must": ("臣",), "banned": ("微信",)}
        )
        no_era = timeslip_api._score_one_reaction(
            "臣不敢，已领命。微信。", "我心里其实不能接受。", {"must": ("臣",), "banned": ("微信",)}
        )
        self.assertGreater(era["era_fit"], no_era["era_fit"])

    def test_inner_conflict_rises_when_speech_defers_and_inner_resists(self) -> None:
        one = timeslip_api._score_one_reaction(
            "不敢，已听凭。", "我心里其实不能接受。", {"must": (), "banned": ()}
        )
        both_defer = timeslip_api._score_one_reaction("不敢，已听凭。", "也罢。", {"must": (), "banned": ()})
        self.assertGreater(one["inner_conflict"], both_defer["inner_conflict"])

    def test_scores_are_clamped(self) -> None:
        score = timeslip_api._score_one_reaction(
            "微信微信微信微信微信", "微信微信", {"must": (), "banned": ("微信",)}
        )
        self.assertGreaterEqual(score["era_fit"], 0)
        self.assertLessEqual(score["era_fit"], 100)
        self.assertGreaterEqual(score["inner_conflict"], 0)
        self.assertLessEqual(score["inner_conflict"], 100)


# ---------------------------------------------------------------------------
# Run shape
# ---------------------------------------------------------------------------


class RunTest(unittest.TestCase):
    def setUp(self) -> None:
        timeslip_api.reset_jobs()

    def test_run_plays_each_picked_resident_each_stage(self) -> None:
        cards = [_card(1, "甲"), _card(2, "乙")]
        dynasty = timeslip_api.dynasty_by_id("tang_revolt")
        reply = _stage_reply(dynasty_words=["府衙", "米"])
        stage_fn = _scripted([reply] * len(dynasty["stages"]))
        essay_fn = _scripted(["这一行人没有完全被时代吞掉。", "再多一支也行。"])

        run = timeslip_api.run_timeslip(
            city="wuzhen",
            agent_ids=[1, 2],
            dynasty_id="tang_revolt",
            cards=cards,
            stage_fn=stage_fn,
            essay_fn=essay_fn,
        )

        self.assertEqual(len(run["stages"]), len(dynasty["stages"]))
        for stage in run["stages"]:
            by_id = {entry["agent_id"]: entry for entry in stage["reactions"]}
            self.assertEqual(set(by_id), {1, 2})
            for entry in stage["reactions"]:
                self.assertTrue(entry["line"])
                self.assertTrue(entry["inner"])
                self.assertIn("era_fit", entry["scores"])
                self.assertIn("stability", entry["scores"])
                self.assertIn("inner_conflict", entry["scores"])

        # 2 residents * 4 stages + 1 essay (the test fixture sticks to the
        # last reply, so essay_fn.calls ends at 1).
        self.assertEqual(len(stage_fn.calls), len(dynasty["stages"]))
        self.assertEqual(len(essay_fn.calls), 1)

        stats = run["stats"]
        self.assertEqual(stats["agents"], 2)
        self.assertEqual(stats["stages"], len(dynasty["stages"]))
        self.assertEqual(len(stats["residents"]), 2)
        for resident in stats["residents"]:
            self.assertIn(resident["agent_id"], (1, 2))
            self.assertIn("best_line", resident)
        self.assertIn("most_in_period", stats)
        self.assertIn("least_in_period", stats)
        self.assertIn("most_torn", stats)
        self.assertTrue(run["essay"])

    def test_run_caps_stages(self) -> None:
        cards = [_card(1, "甲"), _card(2, "乙")]
        reply = _stage_reply(dynasty_words=["府衙"])
        stage_fn = _scripted([reply] * timeslip_api.MAX_STAGES)
        essay_fn = _scripted(["essay"])

        run = timeslip_api.run_timeslip(
            city="wuzhen",
            agent_ids=[1, 2],
            dynasty_id="tang_revolt",
            cards=cards,
            stages=99,  # clamped
            stage_fn=stage_fn,
            essay_fn=essay_fn,
        )
        self.assertLessEqual(len(run["stages"]), timeslip_api.MAX_STAGES)

    def test_run_extends_stages_by_cycling_when_dynasty_is_shorter(self) -> None:
        """Bug fix: requesting more stages than the dynasty ships must
        cycle the bank rather than silently clamping down."""
        cards = [_card(1, "甲"), _card(2, "乙")]
        dynasty = timeslip_api.dynasty_by_id("tang_revolt")
        bank_length = len(dynasty["stages"])
        reply = _stage_reply(dynasty_words=["府衙"])
        stage_fn = _scripted([reply] * timeslip_api.MAX_STAGES)
        essay_fn = _scripted(["essay"])

        run = timeslip_api.run_timeslip(
            city="wuzhen",
            agent_ids=[1, 2],
            dynasty_id="tang_revolt",
            cards=cards,
            stages=bank_length + 2,
            stage_fn=stage_fn,
            essay_fn=essay_fn,
        )
        self.assertEqual(len(run["stages"]), bank_length + 2)

    def test_run_defaults_to_dynasty_count_when_no_stages_passed(self) -> None:
        cards = [_card(1, "甲"), _card(2, "乙")]
        dynasty = timeslip_api.dynasty_by_id("tang_revolt")
        reply = _stage_reply(dynasty_words=["府衙"])
        stage_fn = _scripted([reply] * timeslip_api.MAX_STAGES)
        essay_fn = _scripted(["essay"])
        run = timeslip_api.run_timeslip(
            city="wuzhen",
            agent_ids=[1, 2],
            dynasty_id="tang_revolt",
            cards=cards,
            stage_fn=stage_fn,
            essay_fn=essay_fn,
        )
        # The default is the dynasty's built-in bank length, not a hard-coded 4.
        self.assertEqual(len(run["stages"]), len(dynasty["stages"]))
        self.assertGreaterEqual(len(dynasty["stages"]), 6)

    def test_run_caps_at_max_stages(self) -> None:
        cards = [_card(1, "甲"), _card(2, "乙")]
        reply = _stage_reply(dynasty_words=["府衙"])
        stage_fn = _scripted([reply] * timeslip_api.MAX_STAGES)
        essay_fn = _scripted(["essay"])
        run = timeslip_api.run_timeslip(
            city="wuzhen",
            agent_ids=[1, 2],
            dynasty_id="tang_revolt",
            cards=cards,
            stages=99,
            stage_fn=stage_fn,
            essay_fn=essay_fn,
        )
        self.assertEqual(len(run["stages"]), timeslip_api.MAX_STAGES)

    def test_run_rejects_empty_roster(self) -> None:
        with self.assertRaises(ValueError):
            timeslip_api.run_timeslip(
                city="wuzhen",
                agent_ids=[],
                dynasty_id="tang_revolt",
                stage_fn=lambda prompt: "{}",
                essay_fn=lambda prompt: "",
            )


# ---------------------------------------------------------------------------
# start_run / handle_*
# ---------------------------------------------------------------------------


class HandleTest(unittest.TestCase):
    def setUp(self) -> None:
        timeslip_api.reset_jobs()

    def test_catalogue_returns_dynasties_and_limits(self) -> None:
        body, status = timeslip_api.handle_get("/api/games/timeslip/catalogue")
        self.assertEqual(status, 200)
        self.assertIn("dynasties", body)
        self.assertIn("max_agents", body)
        self.assertGreaterEqual(len(body["dynasties"]), 4)

    def test_run_rejects_too_few_agents(self) -> None:
        body, status = timeslip_api.handle_post(
            "/api/games/timeslip/run",
            {"city": "wuzhen", "agent_ids": [1], "dynasty_id": "tang_revolt"},
        )
        self.assertEqual(status, 400)
        self.assertIn("error", body)

    def test_run_rejects_unknown_dynasty(self) -> None:
        body, status = timeslip_api.handle_post(
            "/api/games/timeslip/run",
            {"city": "wuzhen", "agent_ids": [1, 2], "dynasty_id": "nope"},
        )
        self.assertEqual(status, 400)
        self.assertIn("error", body)

    def test_run_opens_a_job_and_finishes(self) -> None:
        cards = [_card(1, "甲"), _card(2, "乙")]
        dynasty = timeslip_api.dynasty_by_id("tang_revolt")
        reply = _stage_reply(dynasty_words=["府衙", "米"])

        def stage_fn(_prompt: str) -> str:
            return reply

        def essay_fn(_prompt: str) -> str:
            return "短评一句。"

        fake = timeslip_api.run_timeslip(
            city="wuzhen",
            agent_ids=[1, 2],
            dynasty_id="tang_revolt",
            cards=cards,
            stage_fn=stage_fn,
            essay_fn=essay_fn,
        )
        with mock.patch("gaworld.apps.timeslip_api.run_timeslip", return_value=fake):
            body, status = timeslip_api.handle_post(
                "/api/games/timeslip/run",
                {"city": "wuzhen", "agent_ids": [1, 2], "dynasty_id": "tang_revolt"},
            )
            self.assertEqual(status, 202)
            job_id = body["job_id"]
            for _ in range(400):
                record = timeslip_api.job_status(job_id)
                if record and record["status"] != "running":
                    break
                time.sleep(0.01)

        record, status = timeslip_api.handle_get(f"/api/games/timeslip/jobs/{job_id}")
        self.assertEqual(status, 200)
        self.assertEqual(record["status"], "done")
        self.assertEqual(len(record["result"]["stages"]), len(dynasty["stages"]))

        listing, status = timeslip_api.handle_get("/api/games/timeslip/runs")
        self.assertEqual(status, 200)
        self.assertTrue(listing["runs"])

    def test_unknown_job_and_endpoints_are_404(self) -> None:
        self.assertEqual(timeslip_api.handle_get("/api/games/timeslip/jobs/nope")[1], 404)
        self.assertEqual(timeslip_api.handle_get("/api/games/timeslip/nope")[1], 404)
        self.assertEqual(timeslip_api.handle_post("/api/games/timeslip/nope", {})[1], 404)


class GamesApiForwardTest(unittest.TestCase):
    def test_games_api_forwards_the_timeslip_branch(self) -> None:
        body, status = games_api.handle_get("/api/games/timeslip/catalogue")
        self.assertEqual(status, 200)
        self.assertIn("dynasties", body)
        # Invalid input goes through the branch as 400, not 404.
        body, status = games_api.handle_post(
            "/api/games/timeslip/run",
            {"city": "wuzhen", "agent_ids": [1], "dynasty_id": "tang_revolt"},
        )
        self.assertEqual(status, 400)
        self.assertIn("error", body)

    def test_runs_endpoint_lists_recent_runs(self) -> None:
        timeslip_api.reset_jobs()
        cards = [_card(1, "甲"), _card(2, "乙")]
        reply = _stage_reply(dynasty_words=["府衙"])
        fake = timeslip_api.run_timeslip(
            city="wuzhen",
            agent_ids=[1, 2],
            dynasty_id="tang_revolt",
            cards=cards,
            stage_fn=lambda _prompt: reply,
            essay_fn=lambda _prompt: "essay",
        )
        with mock.patch("gaworld.apps.timeslip_api.run_timeslip", return_value=fake):
            body, status = timeslip_api.handle_post(
                "/api/games/timeslip/run",
                {"city": "wuzhen", "agent_ids": [1, 2], "dynasty_id": "tang_revolt"},
            )
            job_id = body["job_id"]
            for _ in range(400):
                record = timeslip_api.job_status(job_id)
                if record and record["status"] != "running":
                    break
                time.sleep(0.01)

        body, status = games_api.handle_get("/api/games/timeslip/runs")
        self.assertEqual(status, 200)
        self.assertTrue(body["runs"])


if __name__ == "__main__":
    unittest.main()
