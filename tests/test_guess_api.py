"""Tests for 猜人局 (gaworld.apps.guess_api).

What we defend:

* dealing a round costs no model call and never leaks the persona prompt to
  the browser;
* the guess must be one of the dealt options, and a round is scored once;
* the resident's pick is matched by letter, by letter inside prose, and by
  the option text — a round should not be lost to formatting;
* ``ask_again`` re-samples the same dilemma up to ``MAX_SAMPLES`` and only
  after the round has been scored;
* the scoreboard counts accuracy, the live streak, the best streak and the
  persona-stability read;
* HTTP delegation returns the documented shapes and the 400/404 contract,
  including the ``/api/games/guess/`` branch in ``games_api``.

No LLM is reached: ``llm_fn`` is injected, and the roster is mocked.
"""

from __future__ import annotations

import random
import unittest
from typing import ClassVar
from unittest import mock

from gaworld.apps import games_api, guess_api

PEOPLE = [
    {
        "id": 3,
        "name": "闫然",
        "age": 41,
        "gender": "男",
        "job": "美发店员",
        "residence": "A小区",
        "state": {},
        "hukou": "本地",
    }
]


def _deal(dilemma_id: str = "wallet", **kwargs):
    with (
        mock.patch("gaworld.interview.roster.load_population", return_value=PEOPLE),
        mock.patch("gaworld.interview.roster.profile_block", return_value="**性格**：谨慎，怕麻烦。"),
    ):
        return guess_api.deal(city="wuzhen", agent_id=3, dilemma_id=dilemma_id, **kwargs)


class DealTest(unittest.TestCase):
    def setUp(self) -> None:
        guess_api.reset_rounds()

    def test_dealing_costs_nothing_and_returns_the_file(self) -> None:
        with mock.patch("gaworld.apps.guess_api._default_choice_llm") as llm:
            record = _deal()
        llm.assert_not_called()
        self.assertEqual(record["agent"]["name"], "闫然")
        self.assertIn("谨慎", record["agent"]["file"])
        self.assertEqual(record["dilemma"]["id"], "wallet")
        self.assertFalse(record["settled"])

    def test_the_persona_prompt_never_reaches_the_browser(self) -> None:
        record = _deal()
        self.assertNotIn("persona_text", record["agent"])

    def test_a_random_deal_picks_from_the_roster(self) -> None:
        with (
            mock.patch("gaworld.interview.roster.load_population", return_value=PEOPLE),
            mock.patch("gaworld.interview.roster.profile_block", return_value="档案"),
        ):
            record = guess_api.deal(city="wuzhen", rng=random.Random(7))
        self.assertEqual(record["agent"]["agent_id"], 3)
        self.assertTrue(record["dilemma"]["options"])

    def test_an_empty_city_is_a_value_error(self) -> None:
        with mock.patch("gaworld.interview.roster.load_population", return_value=[]):
            with self.assertRaises(ValueError):
                guess_api.deal(city="wuzhen")


class ScoringTest(unittest.TestCase):
    def setUp(self) -> None:
        guess_api.reset_rounds()
        self.round = _deal()

    def test_a_right_guess_scores(self) -> None:
        got = guess_api.answer(
            self.round["id"], "b", llm_fn=lambda p: '{"choice": "B", "why": "群里发一下就好"}'
        )
        self.assertTrue(got["correct"])
        self.assertEqual(got["choice"], "B")
        self.assertEqual(got["guess"], "B")
        self.assertEqual(got["why"], "群里发一下就好")
        self.assertTrue(got["settled"])

    def test_a_wrong_guess_does_not(self) -> None:
        got = guess_api.answer(self.round["id"], "A", llm_fn=lambda p: '{"choice": "D"}')
        self.assertFalse(got["correct"])

    def test_the_guess_must_be_a_dealt_option(self) -> None:
        with self.assertRaises(ValueError):
            guess_api.answer(self.round["id"], "Z", llm_fn=lambda p: '{"choice": "A"}')
        with self.assertRaises(ValueError):
            guess_api.answer(self.round["id"], "", llm_fn=lambda p: '{"choice": "A"}')

    def test_a_round_is_scored_once(self) -> None:
        guess_api.answer(self.round["id"], "A", llm_fn=lambda p: '{"choice": "A"}')
        with self.assertRaises(ValueError):
            guess_api.answer(self.round["id"], "B", llm_fn=lambda p: '{"choice": "B"}')

    def test_an_unreadable_answer_is_never_correct(self) -> None:
        got = guess_api.answer(self.round["id"], "A", llm_fn=lambda p: "谁知道呢")
        self.assertEqual(got["choice"], "")
        self.assertFalse(got["correct"])

    def test_unknown_round(self) -> None:
        with self.assertRaises(KeyError):
            guess_api.answer("guess-nope", "A", llm_fn=lambda p: '{"choice": "A"}')


class ParseTest(unittest.TestCase):
    options: ClassVar[list[dict[str, str]]] = [
        {"key": "A", "text": "送到派出所"},
        {"key": "B", "text": "在小区群里发失物招领"},
    ]

    def test_letter_in_json(self) -> None:
        got = guess_api.parse_choice('{"choice": "b", "why": "省事"}', self.options)
        self.assertEqual(got, {"choice": "B", "why": "省事"})

    def test_letter_inside_prose_json(self) -> None:
        got = guess_api.parse_choice('{"choice": "选 A", "why": "稳妥"}', self.options)
        self.assertEqual(got["choice"], "A")

    def test_option_text_without_json(self) -> None:
        got = guess_api.parse_choice("我会送到派出所，别的麻烦", self.options)
        self.assertEqual(got["choice"], "A")

    def test_nothing_matched(self) -> None:
        self.assertEqual(guess_api.parse_choice("不知道", self.options)["choice"], "")


class ResampleTest(unittest.TestCase):
    def setUp(self) -> None:
        guess_api.reset_rounds()
        self.round = _deal()

    def test_asking_again_needs_a_scored_round(self) -> None:
        with self.assertRaises(ValueError):
            guess_api.ask_again(self.round["id"], llm_fn=lambda p: '{"choice": "A"}')

    def test_samples_accumulate_up_to_the_cap(self) -> None:
        guess_api.answer(self.round["id"], "A", llm_fn=lambda p: '{"choice": "A"}')
        for _ in range(guess_api.MAX_SAMPLES - 1):
            got = guess_api.ask_again(self.round["id"], llm_fn=lambda p: '{"choice": "C"}')
        self.assertEqual(len(got["samples"]), guess_api.MAX_SAMPLES)
        self.assertEqual([s["choice"] for s in got["samples"]], ["A", "C", "C"])
        with self.assertRaises(ValueError):
            guess_api.ask_again(self.round["id"], llm_fn=lambda p: '{"choice": "C"}')

    def test_resampling_does_not_rescore_the_round(self) -> None:
        guess_api.answer(self.round["id"], "A", llm_fn=lambda p: '{"choice": "A"}')
        got = guess_api.ask_again(self.round["id"], llm_fn=lambda p: '{"choice": "D"}')
        self.assertTrue(got["correct"])
        self.assertEqual(got["choice"], "A")


class ScoreboardTest(unittest.TestCase):
    def setUp(self) -> None:
        guess_api.reset_rounds()

    def _play(self, guess: str, actual: str) -> dict:
        record = _deal()
        return guess_api.answer(record["id"], guess, llm_fn=lambda p: f'{{"choice": "{actual}"}}')

    def test_accuracy_streak_and_best_streak(self) -> None:
        self._play("A", "A")
        self._play("A", "A")
        self._play("A", "B")  # breaks the streak
        self._play("A", "A")
        board = guess_api.scoreboard()
        self.assertEqual(board["played"], 4)
        self.assertEqual(board["correct"], 3)
        self.assertEqual(board["accuracy"], 0.75)
        self.assertEqual(board["streak"], 1)
        self.assertEqual(board["best_streak"], 2)
        self.assertEqual(board["history"][0]["correct"], True)

    def test_stability_counts_only_resampled_rounds(self) -> None:
        stable = self._play("A", "A")
        guess_api.ask_again(stable["id"], llm_fn=lambda p: '{"choice": "A"}')
        wobbly = self._play("A", "A")
        guess_api.ask_again(wobbly["id"], llm_fn=lambda p: '{"choice": "D"}')
        self._play("A", "A")  # never resampled
        board = guess_api.scoreboard()
        self.assertEqual(board["resampled"], 2)
        self.assertEqual(board["stable"], 1)

    def test_an_empty_session(self) -> None:
        board = guess_api.scoreboard()
        self.assertEqual(board["played"], 0)
        self.assertEqual(board["accuracy"], 0.0)
        self.assertEqual(board["history"], [])


class HttpTest(unittest.TestCase):
    def setUp(self) -> None:
        guess_api.reset_rounds()

    def test_catalogue_and_scoreboard(self) -> None:
        body, status = guess_api.handle_get("/api/games/guess/catalogue")
        self.assertEqual(status, 200)
        self.assertEqual(len(body["dilemmas"]), len(guess_api.DILEMMA_BANK))
        body, status = guess_api.handle_get("/api/games/guess/scoreboard")
        self.assertEqual(status, 200)
        self.assertEqual(body["played"], 0)

    def test_deal_answer_and_replay(self) -> None:
        with (
            mock.patch("gaworld.interview.roster.load_population", return_value=PEOPLE),
            mock.patch("gaworld.interview.roster.profile_block", return_value="档案"),
        ):
            body, status = guess_api.handle_post(
                "/api/games/guess/deal", {"city": "wuzhen", "agent_id": 3, "dilemma_id": "job"}
            )
        self.assertEqual(status, 200)
        round_id = body["id"]

        with mock.patch("gaworld.apps.guess_api._default_choice_llm", return_value='{"choice": "B"}'):
            body, status = guess_api.handle_post(
                "/api/games/guess/answer", {"round_id": round_id, "guess": "B"}
            )
        self.assertEqual(status, 200)
        self.assertTrue(body["correct"])

        body, status = guess_api.handle_get(f"/api/games/guess/rounds/{round_id}")
        self.assertEqual(status, 200)
        self.assertEqual(body["choice"], "B")

    def test_bad_guess_is_400_and_unknown_round_is_404(self) -> None:
        record = _deal()
        _, status = guess_api.handle_post("/api/games/guess/answer", {"round_id": record["id"], "guess": "Z"})
        self.assertEqual(status, 400)
        _, status = guess_api.handle_post("/api/games/guess/answer", {"round_id": "nope", "guess": "A"})
        self.assertEqual(status, 404)
        self.assertEqual(guess_api.handle_get("/api/games/guess/rounds/nope")[1], 404)

    def test_unknown_endpoints_are_404(self) -> None:
        self.assertEqual(guess_api.handle_get("/api/games/guess/nope")[1], 404)
        self.assertEqual(guess_api.handle_post("/api/games/guess/nope", {})[1], 404)

    def test_games_api_forwards_the_branch(self) -> None:
        body, status = games_api.handle_get("/api/games/guess/catalogue")
        self.assertEqual(status, 200)
        self.assertIn("dilemmas", body)
        _, status = games_api.handle_post("/api/games/guess/answer", {"round_id": "nope"})
        self.assertEqual(status, 404)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
