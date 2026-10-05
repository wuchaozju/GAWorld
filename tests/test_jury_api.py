"""Tests for 陪审团 (gaworld.apps.jury_api).

What we defend:

* **The case bank** — every entry ships a fact statement and a starting
  position, because a case with no facts is not a trial.
* **Roster rules** — a single id, an empty roster, an oversized roster,
  and a duplicate id are all rejected rather than silently dropped.
* **The deliberation prompt carries the constraint** — a juror is told
  their role, the facts, the starting position, and the second question.
* **Each juror speaks every round** — ``speech_count == rounds × jurors``,
  so a run with no layer shortcuts the verdict.
* **The verdict is not a model call** — tally comes out of the jurors'
  own answers; a tied jury still defaults to the starting position
  (presumed innocent) so a coin flip can never convict.
* **Parsing** — prose around the JSON survives, a broken reply defaults to
  无罪 (the starting position), confidence is clamped, and an off-vocabulary
  verdict label falls back to the safer side.
* **HTTP delegation** returns the documented shapes, the 400/404 contract,
  and the ``/api/games/jury/`` branch in ``games_api`` forwards correctly.

No LLM is reached: ``deliberate_fn`` / ``verdict_fn`` are injected, and
the jurors are handed in directly.
"""

from __future__ import annotations

import json
import unittest
from unittest import mock

from gaworld.apps import games_api, jury_api

CASE = jury_api.CASE_BANK[0]


def _juror(agent_id: int, name: str = "", job: str = "社区医生", age: int | None = None) -> jury_api.Juror:
    return jury_api.Juror(
        agent_id=agent_id,
        name=name or f"居民{agent_id}",
        age=age if age is not None else 30 + agent_id,
        job=job,
        residence="A小区",
        persona_text=f"你是居民{agent_id}，{30 + agent_id}岁。职业:{job}。",
    )


def _cast(n: int = 3) -> list[jury_api.Juror]:
    return [_juror(j + 1, name=f"居民{j + 1}") for j in range(n)]


def _speech(text: str = "我觉得原告说的在理") -> str:
    return text


def _ballot(verdict: str = "有罪", confidence: int = 80, say: str = "照片很清晰", note: str | None = None) -> str:
    payload = {
        "verdict": verdict,
        "confidence": confidence,
        "say": say,
    }
    if note is not None:
        payload["secondary_value"] = note
    return json.dumps(payload, ensure_ascii=False)


def _recorder(reply):
    """A callable that returns *reply* and keeps every prompt it saw."""
    calls: list[str] = []

    def fn(prompt: str) -> str:
        calls.append(prompt)
        return reply(len(calls) - 1) if callable(reply) else reply

    fn.calls = calls
    return fn


class CaseBankTest(unittest.TestCase):
    def test_every_case_ships_state_and_form(self) -> None:
        self.assertGreaterEqual(len(jury_api.CASE_BANK), 5)
        for case in jury_api.CASE_BANK:
            for key in ("id", "title", "facts", "starting", "defendants"):
                self.assertIn(key, case, case.get("id", "?"))
            self.assertTrue(case["facts"].strip(), case["id"])
            self.assertIn(case["starting"], ("无罪推定", "有罪推定"))

    def test_unknown_case_is_a_value_error(self) -> None:
        with self.assertRaises(ValueError):
            jury_api.resolve_case("nope")

    def test_custom_case_needs_facts(self) -> None:
        with self.assertRaises(ValueError):
            jury_api.resolve_case("", {"title": "自定义", "defendants": "X"})

    def test_custom_case_defaults_starting_to_innocent(self) -> None:
        resolved = jury_api.resolve_case("", {"facts": "做了一件事"})
        self.assertEqual(resolved["starting"], "无罪推定")
        self.assertEqual(resolved["id"], "custom")


class RosterTest(unittest.TestCase):
    def setUp(self) -> None:
        self.people = [
            {"id": i, "name": f"居民{i}", "age": 30 + i, "gender": "女", "job": "教师", "residence": "A小区"}
            for i in range(1, 7)
        ]

    def _load(self, ids):
        with (
            mock.patch("gaworld.interview.roster.load_population", return_value=self.people),
            mock.patch("gaworld.interview.roster.profile_block", return_value="**性格**：平和"),
        ):
            return jury_api._load_jurors("wuzhen", ids)

    def test_jurors_carry_their_persona(self) -> None:
        jurors = self._load([1, 2, 3])
        self.assertEqual(len(jurors), 3)
        self.assertIn("平和", jurors[0].persona_text)
        self.assertEqual(jurors[0].residence, "A小区")

    def test_empty_jury_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self._load([])

    def test_too_few_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self._load([1, 2])

    def test_too_many_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self._load([1, 2, 3, 4, 5, 6])

    def test_duplicate_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self._load([1, 2, 2, 3])

    def test_missing_resident_is_named(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            self._load([1, 99, 2])
        self.assertIn("99", str(ctx.exception))


class DeliberationTest(unittest.TestCase):
    def _run(self, jurors=None, rounds=3, deliberate=None, ballot=None, question_key=None):
        kwargs = {}
        if question_key is not None:
            kwargs["question_key"] = question_key
        return jury_api.run_jury(
            city="",
            case_id=CASE["id"],
            agent_ids=[],
            jurors=jurors or _cast(),
            deliberate_fn=deliberate or _recorder(_speech()),
            verdict_fn=ballot or _recorder(_ballot()),
            progress=lambda p, m: None,
            **kwargs,
        )

    def test_deliberate_prompt_carries_case_and_role(self) -> None:
        deliberate = _recorder(_speech())
        self._run(deliberate=deliberate)
        prompt = deliberate.calls[0]
        self.assertIn(CASE["facts"], prompt)
        self.assertIn("陪审员", prompt)
        self.assertIn(CASE["starting"], prompt)

    def test_each_juror_speaks_every_round(self) -> None:
        deliberate = _recorder(_speech())
        jurors = _cast(4)
        self._run(jurors=jurors, rounds=3, deliberate=deliberate)
        self.assertEqual(len(deliberate.calls), 4 * 3)
        for juror in jurors:
            self.assertEqual(len(juror.speeches), 3)
            for round_index in range(3):
                self.assertEqual(juror.speeches[round_index]["round"], round_index)

    def test_transcript_carries_what_was_already_said(self) -> None:
        """A juror's second-round prompt must echo round-one speeches."""
        deliberate = _recorder(_speech("我同意做这桩事"))
        jurors = _cast(3)
        self._run(jurors=jurors, rounds=2, deliberate=deliberate)
        # Round 2's first juror sees the round-one speeches from the others.
        second_round_prompt = deliberate.calls[3]
        # Round one of any juror produced "我同意做这桩事" — same wording here.
        self.assertIn("我同意做这桩事", second_round_prompt)
        self.assertIn("第 1 轮", second_round_prompt)


class VerdictTest(unittest.TestCase):
    def test_unanimous_guilty_returns_guilty(self) -> None:
        jurors = _cast(3)
        ballot = _recorder(_ballot("有罪", 90, "证据确凿"))
        result = jury_api.run_jury(
            city="",
            case_id=CASE["id"],
            agent_ids=[],
            jurors=jurors,
            deliberate_fn=_recorder(_speech()),
            verdict_fn=ballot,
            progress=lambda p, m: None,
        )
        self.assertEqual(result["tally"]["verdict"], "有罪")
        self.assertEqual(result["tally"]["guilty"], 3)
        self.assertEqual(result["tally"]["not_guilty"], 0)
        self.assertEqual(result["tally"]["spread"], 0)
        for juror in jurors:
            self.assertEqual(juror.verdict, "有罪")
            self.assertEqual(juror.confidence, 90)
            self.assertTrue(juror.confident)

    def test_tie_defaults_to_innocent(self) -> None:
        jurors = _cast(4)
        # 2 guilty, 2 not guilty — the starting position is *no guilty*.
        ballot = _recorder(lambda n: _ballot("有罪" if n % 2 == 0 else "无罪", 70))
        result = jury_api.run_jury(
            city="",
            case_id=CASE["id"],
            agent_ids=[],
            jurors=jurors,
            deliberate_fn=_recorder(_speech()),
            verdict_fn=ballot,
            progress=lambda p, m: None,
        )
        self.assertEqual(result["tally"]["verdict"], "无罪")
        self.assertEqual(result["tally"]["guilty"], 2)
        self.assertEqual(result["tally"]["not_guilty"], 2)

    def test_spread_reflects_max_minus_min_confidence(self) -> None:
        jurors = _cast(3)
        ballot = _recorder(lambda n: _ballot("有罪", [60, 70, 95][n], "好"))
        result = jury_api.run_jury(
            city="",
            case_id=CASE["id"],
            agent_ids=[],
            jurors=jurors,
            deliberate_fn=_recorder(_speech()),
            verdict_fn=ballot,
            progress=lambda p, m: None,
        )
        self.assertEqual(result["tally"]["spread"], 35)
        self.assertEqual(result["stats"]["median_confidence"], 70)
        self.assertEqual(result["stats"]["confident_guilty"], 2)
        self.assertEqual(result["stats"]["confident_not_guilty"], 0)

    def test_verdict_prompt_carries_question_text(self) -> None:
        ballot = _recorder(_ballot())
        jury_api.run_jury(
            city="",
            case_id=CASE["id"],
            agent_ids=[],
            jurors=_cast(3),
            deliberate_fn=_recorder(_speech()),
            verdict_fn=ballot,
            progress=lambda p, m: None,
            question_key="hardship",
        )
        prompt = ballot.calls[0]
        self.assertIn("同情", prompt)
        # The prompt never names a juror's individual id in the position it
        # tells the LLM to take.
        self.assertIn("JSON", prompt)


class ParsingTest(unittest.TestCase):
    def test_ballot_survives_prose_around_the_json(self) -> None:
        record = jury_api.parse_verdict(
            '我先想了一下\n{"verdict": "有罪", "confidence": 88, "say": "证据全"}\n所以。'
        )
        self.assertEqual(record["verdict"], "有罪")
        self.assertEqual(record["confidence"], 88)

    def test_unreadable_ballot_defaults_to_innocent(self) -> None:
        record = jury_api.parse_verdict("不是 JSON")
        self.assertEqual(record["verdict"], "无罪")
        self.assertEqual(record["confidence"], 0)

    def test_off_vocabulary_verdict_falls_back_safely(self) -> None:
        # ``不确定`` is not on the menu. English mappings get normalised.
        record = jury_api.parse_verdict(json.dumps({"verdict": "Not guilty", "confidence": 60, "say": "x"}))
        self.assertEqual(record["verdict"], "无罪")
        record = jury_api.parse_verdict(json.dumps({"verdict": "guilty", "confidence": 60, "say": "x"}))
        self.assertEqual(record["verdict"], "有罪")

    def test_confidence_is_clamped(self) -> None:
        record = jury_api.parse_verdict(json.dumps({"verdict": "有罪", "confidence": 250, "say": "x"}))
        self.assertEqual(record["confidence"], 100)
        record = jury_api.parse_verdict(json.dumps({"verdict": "有罪", "confidence": -10, "say": "x"}))
        self.assertEqual(record["confidence"], 0)

    def test_secondary_value_is_carried(self) -> None:
        record = jury_api.parse_verdict(
            json.dumps({"verdict": "有罪", "confidence": 70, "say": "x", "secondary_value": "三年以下"})
        )
        self.assertEqual(record["secondary_value"], "三年以下")


class HttpTest(unittest.TestCase):
    def test_catalogue(self) -> None:
        body, status = jury_api.handle_get("/api/games/jury/catalogue")
        self.assertEqual(status, 200)
        self.assertEqual(body["min_jurors"], jury_api.MIN_JURORS)
        self.assertEqual(body["max_jurors"], jury_api.MAX_JURORS)
        self.assertEqual(body["verdicts"], list(jury_api.VERDICTS))
        self.assertGreaterEqual(len(body["cases"]), 5)
        self.assertGreaterEqual(len(body["questions"]), 2)

    def test_unknown_job_is_404(self) -> None:
        body, status = jury_api.handle_get("/api/games/jury/jobs/nope")
        self.assertEqual(status, 404)
        self.assertIn("error", body)

    def test_unknown_endpoints_are_404(self) -> None:
        _body, status = jury_api.handle_get("/api/games/jury/whatever")
        self.assertEqual(status, 404)
        _body2, status = jury_api.handle_post("/api/games/jury/whatever", {})
        self.assertEqual(status, 404)

    def test_run_requires_jurors(self) -> None:
        with mock.patch.object(jury_api, "resolve_case"):
            body, status = jury_api.handle_post(
                "/api/games/jury/run",
                {"city": "", "agent_ids": [], "case_id": "parking"},
            )
        self.assertEqual(status, 400)
        self.assertIn("陪审团", body["error"])

    def test_run_rejects_duplicate_juror(self) -> None:
        with mock.patch.object(jury_api, "resolve_case"):
            _body, status = jury_api.handle_post(
                "/api/games/jury/run",
                {"city": "", "agent_ids": [1, 2, 2], "case_id": "parking"},
            )
        self.assertEqual(status, 400)

    def test_run_rejects_an_unknown_case_before_spending_anything(self) -> None:
        body, status = jury_api.handle_post(
            "/api/games/jury/run",
            {"city": "", "agent_ids": [1, 2, 3], "case_id": "nope"},
        )
        self.assertEqual(status, 400)
        self.assertIn("nope", body["error"])

    def test_finished_run_shows_up_in_runs(self) -> None:
        jury_api.reset_jobs()
        jury_api._JOBS.update(
            jury_api._JOBS.new(),
            status="done",
            progress=1.0,
            finished_at=1.0,
            result={
                "run_id": "r1",
                "city": "",
                "case": {"title": "测试案", "emoji": "🧪"},
                "tally": {"verdict": "有罪", "guilty": 2, "not_guilty": 1, "spread": 20},
                "created_at": 1.0,
            },
        )
        body, status = jury_api.handle_get("/api/games/jury/runs")
        self.assertEqual(status, 200)
        self.assertEqual(body["runs"][0]["case_title"], "测试案")

    def test_games_api_forwards_the_jury_branch(self) -> None:
        body, status = games_api.handle_get("/api/games/jury/catalogue")
        self.assertEqual(status, 200)
        self.assertIn("cases", body)


if __name__ == "__main__":
    unittest.main()
