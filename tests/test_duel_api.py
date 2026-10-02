"""Tests for 双队竞赛 (gaworld.apps.duel_api).

What we defend:

* **The task bank** — every entry ships two contrasting methods, because a
  task with one route is not a duel.
* **Roster rules** — an id on both sides is rejected rather than silently
  dropped, an empty side is rejected, and the size caps hold.
* **The prompt carries the constraint** — a member is told their own method,
  told the rival's method is off-limits, and from round two sees both plans.
* **Both teams answer the same snapshot** — team B never gets to read team
  A's *fresh* plan inside the same round, which would hand it the win on turn
  order.
* **Blind judging** — plans reach the judge as 方案一 / 方案二 in a shuffled
  order, the returned scores are mapped back to the right team, and the
  winner comes from the summed scores rather than from the model's claim
  (a contradiction is reported as ``judge_disagreed``).
* **Parsing** — prose around the JSON survives, a broken reply degrades to an
  empty contribution, and scores are clamped into ``[0, MAX_SCORE]``.
* HTTP delegation returns the documented shapes and the 400/404 contract,
  including the ``/api/games/duel/`` branch in ``games_api``.

No LLM is reached: ``move_fn`` / ``plan_fn`` / ``judge_fn`` are injected and
the members are handed in directly.
"""

from __future__ import annotations

import json
import random
import time
import unittest
from unittest import mock

from gaworld.apps import duel_api, games_api

TASK = duel_api.TASK_BANK[0]


def _member(agent_id: int, team: str, name: str = "", job: str = "社区医生") -> duel_api.Member:
    return duel_api.Member(
        agent_id=agent_id,
        name=name or f"居民{agent_id}",
        age=30 + agent_id,
        job=job,
        team=team,
        persona_text=f"你是居民{agent_id}，{30 + agent_id}岁。职业：{job}。",
    )


def _cast() -> list[duel_api.Member]:
    return [_member(1, "A"), _member(2, "A"), _member(3, "B"), _member(4, "B")]


def _move(text: str = "挨家挨户谈", confidence: int = 70) -> str:
    return json.dumps({"move": text, "why": "我熟这片", "confidence": confidence}, ensure_ascii=False)


def _plan(headline: str = "先摸底再谈") -> str:
    return json.dumps(
        {"headline": headline, "steps": ["摸底", "开会", "签字"], "risk": "低层不同意"},
        ensure_ascii=False,
    )


def _verdict(one: int = 8, two: int = 5, winner: str = "one") -> str:
    return json.dumps(
        {
            "one": {key: one for key, _ in duel_api.CRITERIA},
            "two": {key: two for key, _ in duel_api.CRITERIA},
            "winner": winner,
            "reason": "落地更实",
        },
        ensure_ascii=False,
    )


def _recorder(reply):
    """A callable that returns *reply* and keeps every prompt it saw."""
    calls: list[str] = []

    def fn(prompt: str) -> str:
        calls.append(prompt)
        return reply(len(calls) - 1) if callable(reply) else reply

    fn.calls = calls  # type: ignore[attr-defined]
    return fn


class TaskBankTest(unittest.TestCase):
    def test_every_task_ships_two_methods(self) -> None:
        self.assertGreaterEqual(len(duel_api.TASK_BANK), 5)
        for task in duel_api.TASK_BANK:
            for key in ("id", "title", "text", "goal", "method_a", "method_b"):
                self.assertIn(key, task, task["id"])
            self.assertTrue(task["method_a"]["text"].strip())
            self.assertTrue(task["method_b"]["text"].strip())
            self.assertNotEqual(task["method_a"]["title"], task["method_b"]["title"])

    def test_unknown_task_is_a_value_error(self) -> None:
        with self.assertRaises(ValueError):
            duel_api.resolve_task("nope")

    def test_custom_task_needs_both_methods(self) -> None:
        with self.assertRaises(ValueError):
            duel_api.resolve_task("", {"text": "做件事", "method_a": {"text": "甲"}})
        resolved = duel_api.resolve_task(
            "", {"title": "自定义", "text": "做件事", "method_a": {"text": "甲"}, "method_b": {"text": "乙"}}
        )
        self.assertEqual(resolved["id"], "custom")
        self.assertEqual(resolved["method_b"]["text"], "乙")

    def test_custom_task_needs_a_description(self) -> None:
        with self.assertRaises(ValueError):
            duel_api.resolve_task("", {"method_a": {"text": "甲"}, "method_b": {"text": "乙"}})


class RosterTest(unittest.TestCase):
    def setUp(self) -> None:
        self.people = [
            {"id": i, "name": f"居民{i}", "age": 30 + i, "gender": "女", "job": "教师", "residence": "A小区"}
            for i in range(1, 7)
        ]

    def _load(self, team_a, team_b):
        with (
            mock.patch("gaworld.interview.roster.load_population", return_value=self.people),
            mock.patch("gaworld.interview.roster.profile_block", return_value="**性格**：平和"),
        ):
            return duel_api.load_members("wuzhen", team_a, team_b)

    def test_members_carry_their_team_and_persona(self) -> None:
        members = self._load([1, 2], [3])
        self.assertEqual([m.team for m in members], ["A", "A", "B"])
        self.assertIn("平和", members[0].persona_text)

    def test_same_person_on_both_sides_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self._load([1, 2], [2, 3])

    def test_empty_side_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self._load([1, 2], [])

    def test_missing_resident_is_named(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            self._load([1], [99])
        self.assertIn("99", str(ctx.exception))

    def test_team_size_is_capped(self) -> None:
        members = self._load(list(range(1, 7)), [6])
        # Six requested on side A, but only MAX_PER_TEAM are taken — and #6,
        # dropped from A by the cap, is free to play for B.
        self.assertEqual(sum(1 for m in members if m.team == "A"), duel_api.MAX_PER_TEAM)


class PromptTest(unittest.TestCase):
    def setUp(self) -> None:
        self.members = _cast()

    def _run(self, rounds=1, move=None, plan=None, judge=None):
        return duel_api.run_duel(
            city="",
            task_id=TASK["id"],
            rounds=rounds,
            members=self.members,
            move_fn=move or _recorder(_move()),
            plan_fn=plan or _recorder(_plan()),
            judge_fn=judge or _recorder(_verdict()),
            rng=random.Random(0),
        )

    def test_move_prompt_states_own_method_and_forbids_the_rival(self) -> None:
        move = _recorder(_move())
        self._run(move=move)
        prompt = move.calls[0]  # type: ignore[attr-defined]
        self.assertIn(TASK["method_a"]["text"], prompt)
        self.assertIn(TASK["method_b"]["title"], prompt)
        self.assertIn("不许用", prompt)
        self.assertIn(TASK["goal"], prompt)

    def test_first_round_shows_no_plans(self) -> None:
        move = _recorder(_move())
        self._run(move=move)
        self.assertNotIn("对手的东西摆在你面前", move.calls[0])  # type: ignore[attr-defined]

    def test_second_round_shows_both_plans(self) -> None:
        move = _recorder(_move())
        self._run(rounds=2, move=move, plan=_recorder(_plan("甲队方案")))
        later = move.calls[len(self.members)]  # type: ignore[attr-defined]
        self.assertIn("对手的东西摆在你面前", later)
        self.assertIn("甲队方案", later)

    def test_both_teams_answer_the_same_snapshot(self) -> None:
        # Each plan call returns a distinct headline, so a prompt that quoted a
        # plan written *this* round would name a later one than the snapshot.
        plan = _recorder(lambda n: _plan(f"方案{n}"))
        move = _recorder(_move())
        self._run(rounds=2, move=move, plan=plan)
        # Round 2, team B's first member: the rival (A) plan it sees must be
        # A's round-1 plan (方案0), not the one A wrote moments ago (方案2).
        team_a_size = sum(1 for m in self.members if m.team == "A")
        prompt = move.calls[len(self.members) + team_a_size]  # type: ignore[attr-defined]
        self.assertIn("方案0", prompt)
        self.assertNotIn("方案2", prompt)

    def test_plan_prompt_lists_member_moves(self) -> None:
        plan = _recorder(_plan())
        self._run(move=_recorder(_move("找楼长带头")), plan=plan)
        self.assertIn("找楼长带头", plan.calls[0])  # type: ignore[attr-defined]
        self.assertIn(self.members[0].name, plan.calls[0])  # type: ignore[attr-defined]

    def test_call_count_is_rounds_times_members_plus_two_plus_one(self) -> None:
        move, plan, judge = _recorder(_move()), _recorder(_plan()), _recorder(_verdict())
        self._run(rounds=2, move=move, plan=plan, judge=judge)
        self.assertEqual(len(move.calls), 2 * len(self.members))  # type: ignore[attr-defined]
        self.assertEqual(len(plan.calls), 2 * 2)  # type: ignore[attr-defined]
        self.assertEqual(len(judge.calls), 1)  # type: ignore[attr-defined]


class VerdictTest(unittest.TestCase):
    def _judged(self, verdict_raw, seed=0):
        return duel_api.run_duel(
            city="",
            task_id=TASK["id"],
            rounds=1,
            members=_cast(),
            move_fn=_recorder(_move()),
            plan_fn=_recorder(_plan()),
            judge_fn=_recorder(verdict_raw),
            rng=random.Random(seed),
        )

    def test_scores_map_back_to_the_right_team(self) -> None:
        # Whatever the shuffle, the team presented first gets the "one" scores.
        for seed in range(4):
            result = self._judged(_verdict(one=9, two=4), seed=seed)
            verdict = result["verdict"]
            first, second = verdict["order"]
            self.assertEqual(verdict["scores"][first]["total"], 9 * len(duel_api.CRITERIA))
            self.assertEqual(verdict["scores"][second]["total"], 4 * len(duel_api.CRITERIA))
            self.assertEqual(verdict["winner"], first)

    def test_judge_prompt_never_names_a_team(self) -> None:
        judge = _recorder(_verdict())
        duel_api.run_duel(
            city="",
            task_id=TASK["id"],
            rounds=1,
            members=_cast(),
            move_fn=_recorder(_move()),
            plan_fn=_recorder(_plan()),
            judge_fn=judge,
            rng=random.Random(0),
        )
        prompt = judge.calls[0]  # type: ignore[attr-defined]
        self.assertNotIn("甲队", prompt)
        self.assertNotIn("乙队", prompt)
        self.assertIn("方案一", prompt)
        self.assertIn("方案二", prompt)

    def test_presentation_order_is_not_always_the_same(self) -> None:
        orders = {tuple(self._judged(_verdict(), seed=s)["verdict"]["order"]) for s in range(8)}
        self.assertEqual(len(orders), 2)

    def test_equal_scores_are_a_tie_even_if_the_judge_picks_one(self) -> None:
        result = self._judged(_verdict(one=6, two=6, winner="one"))
        self.assertEqual(result["verdict"]["winner"], "tie")
        self.assertTrue(result["stats"]["judge_disagreed"])

    def test_agreement_is_not_flagged(self) -> None:
        result = self._judged(_verdict(one=9, two=3, winner="one"))
        self.assertFalse(result["stats"]["judge_disagreed"])
        self.assertEqual(result["stats"]["margin"], 6 * len(duel_api.CRITERIA))

    def test_unreadable_verdict_scores_zero_and_ties(self) -> None:
        result = self._judged("评审跑了")
        self.assertEqual(result["verdict"]["winner"], "tie")
        self.assertEqual(result["verdict"]["scores"]["A"]["total"], 0)


class ParsingTest(unittest.TestCase):
    def test_move_survives_prose_around_the_json(self) -> None:
        parsed = duel_api.parse_move('好的：{"move": "去谈", "why": "熟", "confidence": 55} 以上')
        self.assertEqual(parsed["move"], "去谈")
        self.assertEqual(parsed["confidence"], 55)

    def test_broken_move_contributes_nothing(self) -> None:
        parsed = duel_api.parse_move("我不知道")
        self.assertEqual(parsed["confidence"], 0)
        self.assertEqual(parsed["move"], "我不知道")

    def test_confidence_is_clamped(self) -> None:
        self.assertEqual(duel_api.parse_move('{"move": "x", "confidence": 480}')["confidence"], 100)
        self.assertEqual(duel_api.parse_move('{"move": "x", "confidence": -9}')["confidence"], 0)

    def test_plan_tolerates_a_string_instead_of_a_step_list(self) -> None:
        parsed = duel_api.parse_plan('{"headline": "上门谈", "steps": "一步到位", "risk": "没人开门"}')
        self.assertEqual(parsed["steps"], ["一步到位"])

    def test_plan_keeps_prose_as_the_headline(self) -> None:
        self.assertEqual(duel_api.parse_plan("就这么办")["headline"], "就这么办")

    def test_scores_are_clamped(self) -> None:
        sheet = duel_api.parse_verdict(
            json.dumps({"one": {"effect": 99}, "two": {"effect": -4}, "winner": "one"})
        )
        self.assertEqual(sheet["one"]["effect"], duel_api.MAX_SCORE)
        self.assertEqual(sheet["two"]["effect"], 0)
        self.assertEqual(sheet["one"]["total"], duel_api.MAX_SCORE)


class HttpTest(unittest.TestCase):
    def setUp(self) -> None:
        duel_api.reset_jobs()

    def test_catalogue(self) -> None:
        body, status = duel_api.handle_get("/api/games/duel/catalogue")
        self.assertEqual(status, 200)
        self.assertEqual(len(body["tasks"]), len(duel_api.TASK_BANK))
        self.assertEqual(body["max_per_team"], duel_api.MAX_PER_TEAM)
        self.assertEqual(body["max_score"], duel_api.MAX_SCORE * len(duel_api.CRITERIA))

    def test_run_requires_two_teams(self) -> None:
        body, status = duel_api.handle_post(
            "/api/games/duel/run", {"city": "", "team_a": [1], "task_id": TASK["id"]}
        )
        self.assertEqual(status, 400)
        self.assertIn("error", body)

    def test_run_rejects_an_unknown_task_before_spending_anything(self) -> None:
        _body, status = duel_api.handle_post(
            "/api/games/duel/run", {"city": "", "team_a": [1], "team_b": [2], "task_id": "nope"}
        )
        self.assertEqual(status, 400)
        self.assertEqual(duel_api.list_runs(), [])

    def test_unknown_job_is_404(self) -> None:
        body, status = duel_api.handle_get("/api/games/duel/jobs/nope")
        self.assertEqual(status, 404)
        self.assertIn("error", body)

    def test_unknown_endpoints_are_404(self) -> None:
        self.assertEqual(duel_api.handle_get("/api/games/duel/nope")[1], 404)
        self.assertEqual(duel_api.handle_post("/api/games/duel/nope", {})[1], 404)

    def test_games_api_forwards_the_duel_branch(self) -> None:
        body, status = games_api.handle_get("/api/games/duel/catalogue")
        self.assertEqual(status, 200)
        self.assertIn("tasks", body)
        body, status = games_api.handle_post("/api/games/duel/run", {"city": ""})
        self.assertEqual(status, 400)

    def test_finished_run_shows_up_in_runs(self) -> None:
        people = [
            {"id": i, "name": f"居民{i}", "age": 30 + i, "gender": "女", "job": "教师", "residence": "A小区"}
            for i in range(1, 4)
        ]
        with (
            mock.patch("gaworld.interview.roster.load_population", return_value=people),
            mock.patch("gaworld.interview.roster.profile_block", return_value=""),
            mock.patch("gaworld.apps.duel_api._default_move_llm", return_value=_move()),
            mock.patch("gaworld.apps.duel_api._default_plan_llm", return_value=_plan()),
            mock.patch("gaworld.apps.duel_api._default_judge_llm", return_value=_verdict(9, 4)),
        ):
            body, status = duel_api.handle_post(
                "/api/games/duel/run",
                {"city": "", "team_a": [1], "team_b": [2], "task_id": TASK["id"], "rounds": 1},
            )
            self.assertEqual(status, 200)
            job_id = body["job_id"]
            for _ in range(200):
                record = duel_api.job_status(job_id)
                if record and record["status"] != "running":
                    break
                time.sleep(0.01)
        self.assertEqual(record["status"], "done", record.get("error"))
        result = record["result"]
        self.assertEqual(len(result["teams"]), 2)
        self.assertEqual(result["verdict"]["scores"][result["verdict"]["order"][0]]["effect"], 9)
        runs = duel_api.list_runs()
        self.assertEqual(runs[0]["job_id"], job_id)
        self.assertIn(runs[0]["winner"], ("A", "B"))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
