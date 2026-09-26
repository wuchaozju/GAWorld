"""Tests for the 游戏场 backend (gaworld.apps.games_api).

What we defend:

* ``start_session`` asks the opening question once and opens a session on
  the answer, clamping ``max_turns`` into ``[1, MAX_TURNS_LIMIT]``.
* ``send_message`` alternates player / agent turns, refuses an empty
  message, and settles automatically on the last allowed turn.
* ``settle`` re-asks the original question and scores via the judge:
  a changed answer is a win, an unchanged one is a loss, and settling
  twice is a no-op rather than a second bill.
* ``judge_change`` parses a clean JSON verdict and tolerates prose around
  it, the same contract the arena judge has.
* ``load_persona`` reads the roster + profile block, and says which agent
  is missing rather than returning a blank persona.
* HTTP delegation returns the documented shapes and the 400/404 contract.

No LLM is reached at runtime: ``answer_fn`` and ``judge_fn`` are injected
as plain callables, and the persona is handed in directly.
"""

from __future__ import annotations

import unittest
from unittest import mock

from gaworld.apps import games_api

PERSONA = {
    "agent_id": 3,
    "name": "闫然",
    "age": 41,
    "gender": "男",
    "job": "美发店员",
    "profile_md": "**价值观与公共事务态度**：对公共事务关注有限。",
}


def _scripted(replies: list[str]):
    """An answer_fn that returns the scripted replies in order."""
    calls: list[str] = []

    def fn(prompt: str) -> str:
        calls.append(prompt)
        return replies[min(len(calls) - 1, len(replies) - 1)]

    fn.calls = calls  # type: ignore[attr-defined]
    return fn


def _verdict(changed: bool):
    return lambda prompt: (
        '{"changed": true, "reason": "改口了"}' if changed else '{"changed": false, "reason": "没变"}'
    )


class SessionLifecycleTest(unittest.TestCase):
    def setUp(self) -> None:
        games_api.reset_sessions()

    def test_start_records_opening_answer(self) -> None:
        session = games_api.start_session(
            city="wuzhen",
            agent_id=3,
            question="该不该搬去杭州？",
            max_turns=3,
            persona=PERSONA,
            answer_fn=_scripted(["不该，我在这儿挺好。"]),
        )
        self.assertEqual(session["initial_answer"], "不该，我在这儿挺好。")
        self.assertEqual(session["agent_name"], "闫然")
        self.assertEqual(session["max_turns"], 3)
        self.assertEqual(session["turns_used"], 0)
        self.assertEqual(session["turns_left"], 3)
        self.assertEqual(session["status"], "open")
        self.assertEqual(session["outcome"], "")

    def test_start_requires_a_question(self) -> None:
        with self.assertRaises(ValueError):
            games_api.start_session(
                city="wuzhen", agent_id=3, question="   ", persona=PERSONA, answer_fn=_scripted(["x"])
            )

    def test_max_turns_is_clamped(self) -> None:
        low = games_api.start_session(
            city="", agent_id=3, question="q", max_turns=0, persona=PERSONA, answer_fn=_scripted(["a"])
        )
        high = games_api.start_session(
            city="", agent_id=3, question="q", max_turns=999, persona=PERSONA, answer_fn=_scripted(["a"])
        )
        self.assertEqual(low["max_turns"], 1)
        self.assertEqual(high["max_turns"], games_api.MAX_TURNS_LIMIT)

    def test_persona_reaches_the_prompt(self) -> None:
        answer = _scripted(["不该。"])
        games_api.start_session(
            city="wuzhen", agent_id=3, question="该不该搬去杭州？", persona=PERSONA, answer_fn=answer
        )
        prompt = answer.calls[0]  # type: ignore[attr-defined]
        self.assertIn("闫然", prompt)
        self.assertIn("对公共事务关注有限", prompt)
        self.assertIn("该不该搬去杭州？", prompt)

    def test_chat_turn_appends_both_sides(self) -> None:
        session = games_api.start_session(
            city="", agent_id=3, question="q", max_turns=3, persona=PERSONA, answer_fn=_scripted(["原答案"])
        )
        updated = games_api.send_message(
            session["id"], "杭州工资高一倍", answer_fn=_scripted(["工资高也顶不住房租。"])
        )
        self.assertEqual([m["role"] for m in updated["messages"]], ["player", "agent"])
        self.assertEqual(updated["messages"][1]["text"], "工资高也顶不住房租。")
        self.assertEqual(updated["turns_used"], 1)
        self.assertEqual(updated["turns_left"], 2)
        self.assertEqual(updated["status"], "open")

    def test_empty_message_is_rejected(self) -> None:
        session = games_api.start_session(
            city="", agent_id=3, question="q", persona=PERSONA, answer_fn=_scripted(["a"])
        )
        with self.assertRaises(ValueError):
            games_api.send_message(session["id"], "   ")

    def test_unknown_session_raises_key_error(self) -> None:
        with self.assertRaises(KeyError):
            games_api.send_message("persuade-nope", "hi")
        self.assertIsNone(games_api.get_session("persuade-nope"))

    def test_last_turn_settles_automatically(self) -> None:
        session = games_api.start_session(
            city="", agent_id=3, question="q", max_turns=1, persona=PERSONA, answer_fn=_scripted(["不该"])
        )
        settled = games_api.send_message(
            session["id"],
            "再想想",
            answer_fn=_scripted(["你说得有道理。", "现在我觉得该搬。"]),
            judge_fn=_verdict(True),
        )
        self.assertEqual(settled["status"], "settled")
        self.assertEqual(settled["outcome"], "success")
        self.assertEqual(settled["final_answer"], "现在我觉得该搬。")
        self.assertIsNotNone(settled["finished_at"])

    def test_chatting_after_settlement_is_rejected(self) -> None:
        session = games_api.start_session(
            city="", agent_id=3, question="q", max_turns=1, persona=PERSONA, answer_fn=_scripted(["不该"])
        )
        games_api.send_message(
            session["id"], "再想想", answer_fn=_scripted(["嗯", "还是不该。"]), judge_fn=_verdict(False)
        )
        with self.assertRaises(ValueError):
            games_api.send_message(session["id"], "再劝一句")


class SettlementTest(unittest.TestCase):
    def setUp(self) -> None:
        games_api.reset_sessions()
        self.session = games_api.start_session(
            city="",
            agent_id=3,
            question="该不该搬去杭州？",
            max_turns=5,
            persona=PERSONA,
            answer_fn=_scripted(["不该，我在这儿挺好。"]),
        )

    def test_unchanged_answer_loses(self) -> None:
        result = games_api.settle(
            self.session["id"], answer_fn=_scripted(["还是不该。"]), judge_fn=_verdict(False)
        )
        self.assertEqual(result["outcome"], "failed")
        self.assertEqual(result["reason"], "没变")

    def test_changed_answer_wins(self) -> None:
        result = games_api.settle(
            self.session["id"], answer_fn=_scripted(["行吧，我搬。"]), judge_fn=_verdict(True)
        )
        self.assertEqual(result["outcome"], "success")

    def test_settling_twice_does_not_call_the_llm_again(self) -> None:
        answer = _scripted(["还是不该。"])
        games_api.settle(self.session["id"], answer_fn=answer, judge_fn=_verdict(False))
        games_api.settle(self.session["id"], answer_fn=answer, judge_fn=_verdict(True))
        self.assertEqual(len(answer.calls), 1)  # type: ignore[attr-defined]

    def test_final_prompt_carries_the_transcript(self) -> None:
        games_api.send_message(self.session["id"], "杭州机会多", answer_fn=_scripted(["机会多也累。"]))
        answer = _scripted(["还是不该。"])
        games_api.settle(self.session["id"], answer_fn=answer, judge_fn=_verdict(False))
        prompt = answer.calls[0]  # type: ignore[attr-defined]
        self.assertIn("杭州机会多", prompt)
        self.assertIn("机会多也累。", prompt)
        self.assertIn("不该，我在这儿挺好。", prompt)


class JudgeTest(unittest.TestCase):
    def test_parses_json_verdict(self) -> None:
        changed, reason = games_api.judge_change(
            "q", "a", "b", llm_fn=lambda p: '{"changed": true, "reason": "结论反转"}'
        )
        self.assertTrue(changed)
        self.assertEqual(reason, "结论反转")

    def test_tolerates_prose_around_the_verdict(self) -> None:
        changed, _ = games_api.judge_change(
            "q", "a", "b", llm_fn=lambda p: 'verdict: {"changed": true, "reason": "ok"} done'
        )
        self.assertTrue(changed)

    def test_unparsable_reply_is_not_a_win(self) -> None:
        changed, _ = games_api.judge_change("q", "a", "b", llm_fn=lambda p: "谁知道呢")
        self.assertFalse(changed)


class JsonReplyTest(unittest.TestCase):
    """`first_json_object` is what every structured game reply goes through."""

    def test_plain_object(self) -> None:
        self.assertEqual(games_api.first_json_object('{"a": 1}'), {"a": 1})

    def test_stray_closing_brace_and_trailing_prose(self) -> None:
        self.assertEqual(games_api.first_json_object('{"a": 1}}'), {"a": 1})
        self.assertEqual(games_api.first_json_object('好的：{"a": {"b": 2}} 就这样'), {"a": {"b": 2}})

    def test_fenced_block(self) -> None:
        self.assertEqual(games_api.first_json_object('```json\n{"a": 3}\n```'), {"a": 3})

    def test_braces_inside_a_string_do_not_end_the_object(self) -> None:
        self.assertEqual(games_api.first_json_object('{"say": "用了 } 括号"}'), {"say": "用了 } 括号"})

    def test_the_first_broken_object_does_not_hide_a_good_one(self) -> None:
        self.assertEqual(games_api.first_json_object('{坏的} {"ok": 1}'), {"ok": 1})

    def test_nothing_usable(self) -> None:
        self.assertEqual(games_api.first_json_object("没有 JSON"), {})
        self.assertEqual(games_api.first_json_object(None), {})
        self.assertEqual(games_api.first_json_object('[1, 2]'), {})


class PersonaTest(unittest.TestCase):
    def test_load_persona_joins_roster_and_profile(self) -> None:
        people = [{"id": 3, "name": "闫然", "age": 41, "gender": "男", "job": "美发店员"}]
        with (
            mock.patch("gaworld.interview.roster.load_population", return_value=people),
            mock.patch("gaworld.interview.roster.profile_block", return_value="**性格**：平和"),
        ):
            persona = games_api.load_persona("wuzhen", 3)
        self.assertEqual(persona["name"], "闫然")
        self.assertEqual(persona["profile_md"], "**性格**：平和")

    def test_missing_agent_is_a_value_error(self) -> None:
        with mock.patch("gaworld.interview.roster.load_population", return_value=[]):
            with self.assertRaises(ValueError):
                games_api.load_persona("wuzhen", 99)

    def test_list_agents_projects_the_picker_fields(self) -> None:
        people = [
            {
                "id": 1,
                "name": "甲",
                "age": 30,
                "gender": "女",
                "job": "教师",
                "residence": "新亭村·自住房",
                "state": {},
                "hukou": "本地",
            }
        ]
        with mock.patch("gaworld.interview.roster.load_population", return_value=people):
            agents = games_api.list_agents("wuzhen")
        self.assertEqual(
            agents,
            [
                {
                    "id": 1,
                    "name": "甲",
                    "age": 30,
                    "gender": "女",
                    "job": "教师",
                    "residence": "新亭村·自住房",
                }
            ],
        )


class HttpTest(unittest.TestCase):
    def setUp(self) -> None:
        games_api.reset_sessions()

    def test_agents_endpoint(self) -> None:
        with mock.patch("gaworld.interview.roster.load_population", return_value=[]):
            body, status = games_api.handle_get("/api/games/agents", {"city": ["wuzhen"]})
        self.assertEqual(status, 200)
        self.assertEqual(body, {"agents": []})

    def test_session_detail_and_list(self) -> None:
        session = games_api.start_session(
            city="", agent_id=3, question="q", persona=PERSONA, answer_fn=_scripted(["a"])
        )
        body, status = games_api.handle_get("/api/games/persuasion/sessions/" + session["id"])
        self.assertEqual(status, 200)
        self.assertEqual(body["id"], session["id"])

        listing, status = games_api.handle_get("/api/games/persuasion/sessions")
        self.assertEqual(status, 200)
        self.assertEqual(listing["sessions"][0]["id"], session["id"])

    def test_unknown_session_is_404(self) -> None:
        body, status = games_api.handle_get("/api/games/persuasion/sessions/nope")
        self.assertEqual(status, 404)
        self.assertIn("error", body)

        body, status = games_api.handle_post(
            "/api/games/persuasion/say", {"session_id": "nope", "message": "hi"}
        )
        self.assertEqual(status, 404)
        self.assertIn("error", body)

    def test_unknown_endpoints_are_404(self) -> None:
        self.assertEqual(games_api.handle_get("/api/games/nope")[1], 404)
        self.assertEqual(games_api.handle_post("/api/games/nope", {})[1], 404)

    def test_start_without_question_is_400(self) -> None:
        with mock.patch("gaworld.apps.games_api.load_persona", return_value=PERSONA):
            body, status = games_api.handle_post(
                "/api/games/persuasion/start", {"city": "wuzhen", "agent_id": 3, "question": ""}
            )
        self.assertEqual(status, 400)
        self.assertIn("error", body)

    def test_start_via_http_uses_the_provider_path(self) -> None:
        with (
            mock.patch("gaworld.apps.games_api.load_persona", return_value=PERSONA),
            mock.patch("gaworld.apps.games_api._default_answer_llm", return_value="不该。") as llm,
        ):
            body, status = games_api.handle_post(
                "/api/games/persuasion/start",
                {"city": "wuzhen", "agent_id": 3, "question": "该不该搬？", "max_turns": 2},
            )
        self.assertEqual(status, 200)
        self.assertEqual(body["initial_answer"], "不该。")
        self.assertEqual(llm.call_count, 1)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
