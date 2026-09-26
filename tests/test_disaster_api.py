"""Tests for 灾害模式 (gaworld.apps.disaster_api).

What we defend:

* ``run_disaster`` asks every participant once per stage, in stage order,
  and clamps the stage count to what the disaster actually has.
* The prompt carries the persona, the stage text, the resident's own earlier
  actions, and — from stage 2 on — what the crowd did last stage.
* ``parse_reaction`` survives whatever the provider returns: clean JSON,
  JSON wrapped in prose, an off-vocabulary action, or plain garbage. A bad
  reply degrades one reaction instead of killing the round.
* The aggregate (histogram / panic / help rate) matches the reactions.
* ``resolve_disaster`` accepts the bank and a custom script, and rejects an
  unknown id; ``start_run`` refuses an empty roster before opening a job.
* HTTP delegation returns the documented shapes and the 400/404 contract,
  including the ``/api/games/disaster/`` branch in ``games_api``.

No LLM is reached: ``answer_fn`` / ``summary_fn`` are injected and the
participants are handed in directly.
"""

from __future__ import annotations

import unittest
from unittest import mock

from gaworld.apps import disaster_api, games_api


def _people(n: int = 3) -> list[disaster_api.Participant]:
    return [
        disaster_api.Participant(
            agent_id=i,
            name=f"居民{i}",
            job="教师",
            persona_text=f"你是居民{i}，40岁，女。职业：教师。",
        )
        for i in range(1, n + 1)
    ]


def _replies(*items: str):
    """An answer_fn returning the scripted replies in order (last one sticks)."""
    calls: list[str] = []

    def fn(prompt: str) -> str:
        calls.append(prompt)
        return items[min(len(calls) - 1, len(items) - 1)]

    fn.calls = calls  # type: ignore[attr-defined]
    return fn


def _json(action: str, panic: int = 3, help_: bool = False, detail: str = "做点什么") -> str:
    return (
        f'{{"action": "{action}", "detail": "{detail}", '
        f'"panic": {panic}, "help": {"true" if help_ else "false"}, "say": "唉。"}}'
    )


class RunTest(unittest.TestCase):
    def test_every_participant_reacts_to_every_stage(self) -> None:
        answer = _replies(_json("避险逃离"))
        run = disaster_api.run_disaster(
            city="wuzhen",
            agent_ids=[],
            disaster_id="earthquake",
            stages=2,
            participants=_people(3),
            answer_fn=answer,
            summary_fn=lambda p: "简报",
        )
        self.assertEqual(len(answer.calls), 6)  # type: ignore[attr-defined]
        self.assertEqual(len(run["stages"]), 2)
        self.assertEqual([len(a["reactions"]) for a in run["agents"]], [2, 2, 2])
        self.assertEqual([r["stage"] for r in run["agents"][0]["reactions"]], [0, 1])
        self.assertEqual(run["summary"], "简报")
        self.assertEqual(run["disaster"]["name"], "地震")

    def test_stage_count_is_clamped_to_the_script(self) -> None:
        run = disaster_api.run_disaster(
            city="",
            agent_ids=[],
            disaster_id="epidemic",
            stages=99,
            participants=_people(1),
            answer_fn=_replies(_json("照常生活")),
            summary_fn=lambda p: "",
        )
        self.assertEqual(len(run["stages"]), disaster_api.MAX_STAGES)

        short = disaster_api.run_disaster(
            city="",
            agent_ids=[],
            custom={"name": "泥石流", "stages": "山上垮了。"},
            stages=3,
            participants=_people(1),
            answer_fn=_replies(_json("避险逃离")),
            summary_fn=lambda p: "",
        )
        self.assertEqual(len(short["stages"]), 1)

    def test_prompt_carries_persona_stage_history_and_crowd(self) -> None:
        answer = _replies(_json("囤积物资"))
        disaster_api.run_disaster(
            city="",
            agent_ids=[],
            disaster_id="flood",
            stages=2,
            participants=_people(2),
            answer_fn=answer,
            summary_fn=lambda p: "",
        )
        first, _, third, _ = answer.calls  # type: ignore[attr-defined]
        self.assertIn("你是居民1", first)
        self.assertIn("连续暴雨", first)
        self.assertNotIn("你看到身边的人", first)  # no crowd in the opening stage

        self.assertIn("第 1 阶段，你囤积物资", third)  # their own earlier action
        self.assertIn("你看到身边的人：2 人囤积物资", third)  # what everyone else did

    def test_a_broken_reply_degrades_one_reaction_only(self) -> None:
        answer = _replies("模型今天不想说话", _json("救助他人", panic=5, help_=True))
        run = disaster_api.run_disaster(
            city="",
            agent_ids=[],
            disaster_id="war",
            stages=1,
            participants=_people(2),
            answer_fn=answer,
            summary_fn=lambda p: "",
        )
        reactions = [a["reactions"][0] for a in run["agents"]]
        self.assertEqual(reactions[0]["action"], disaster_api.OTHER_ACTION)
        self.assertEqual(reactions[1]["action"], "救助他人")
        self.assertEqual(run["stats"]["overall"]["n"], 2)

    def test_a_failing_summary_does_not_fail_the_round(self) -> None:
        def boom(prompt: str) -> str:
            raise RuntimeError("provider down")

        run = disaster_api.run_disaster(
            city="",
            agent_ids=[],
            disaster_id="blackout",
            stages=1,
            participants=_people(1),
            answer_fn=_replies(_json("打探消息")),
            summary_fn=boom,
        )
        self.assertEqual(run["summary"], "")
        self.assertEqual(len(run["agents"][0]["reactions"]), 1)

    def test_no_agents_is_a_value_error(self) -> None:
        with self.assertRaises(ValueError):
            disaster_api.run_disaster(city="", agent_ids=[], disaster_id="earthquake")


class StatsTest(unittest.TestCase):
    def test_aggregate_counts_actions_panic_and_help(self) -> None:
        answers = iter([_json("避险逃离", 5, True), _json("囤积物资", 1, False)])
        run = disaster_api.run_disaster(
            city="",
            agent_ids=[],
            disaster_id="earthquake",
            stages=1,
            participants=_people(2),
            answer_fn=lambda prompt: next(answers),
            summary_fn=lambda p: "",
        )
        stage = run["stats"]["per_stage"][0]
        self.assertEqual(stage["actions"], {"避险逃离": 1, "囤积物资": 1})
        self.assertEqual(stage["avg_panic"], 3.0)
        self.assertEqual(stage["max_panic"], 5)
        self.assertEqual(stage["help_rate"], 0.5)
        self.assertEqual(stage["stage"], 0)
        self.assertEqual(run["stats"]["overall"]["n"], 2)
        self.assertTrue(run["agents"][0]["helped"])
        self.assertFalse(run["agents"][1]["helped"])


class ParseTest(unittest.TestCase):
    def test_clean_json(self) -> None:
        got = disaster_api.parse_reaction(_json("救助他人", 4, True, detail="去敲邻居的门"))
        self.assertEqual(got["action"], "救助他人")
        self.assertEqual(got["detail"], "去敲邻居的门")
        self.assertEqual(got["panic"], 4)
        self.assertTrue(got["help"])

    def test_json_wrapped_in_prose(self) -> None:
        got = disaster_api.parse_reaction('好的：\n{"action": "囤积物资", "panic": 2}\n希望有用')
        self.assertEqual(got["action"], "囤积物资")
        self.assertEqual(got["panic"], 2)

    def test_off_vocabulary_action_is_mapped_or_othered(self) -> None:
        self.assertEqual(disaster_api.parse_reaction('{"action": "赶紧避险逃离外地"}')["action"], "避险逃离")
        self.assertEqual(
            disaster_api.parse_reaction('{"action": "写一首诗"}')["action"], disaster_api.OTHER_ACTION
        )

    def test_a_stray_closing_brace_still_parses(self) -> None:
        got = disaster_api.parse_reaction('{"action": "救助他人", "panic": 4}} 就这样')
        self.assertEqual(got["action"], "救助他人")
        self.assertEqual(got["panic"], 4)

    def test_panic_is_clamped_and_garbage_is_neutral(self) -> None:
        self.assertEqual(disaster_api.parse_reaction('{"action": "照常生活", "panic": 99}')["panic"], 5)
        self.assertEqual(disaster_api.parse_reaction('{"action": "照常生活", "panic": "高"}')["panic"], 3)
        garbage = disaster_api.parse_reaction("完全不是 JSON")
        self.assertEqual(garbage["action"], disaster_api.OTHER_ACTION)
        self.assertEqual(garbage["panic"], 3)
        self.assertFalse(garbage["help"])


class CatalogueTest(unittest.TestCase):
    def test_bank_entries_are_playable(self) -> None:
        for item in disaster_api.list_disasters():
            self.assertTrue(item["name"])
            self.assertEqual(len(item["stages"]), disaster_api.MAX_STAGES)

    def test_custom_text_splits_into_stages(self) -> None:
        got = disaster_api.resolve_disaster("", {"name": "化工厂爆炸", "stages": "第一天\n\n第二天"})
        self.assertEqual(got["name"], "化工厂爆炸")
        self.assertEqual(got["stages"], ["第一天", "第二天"])

    def test_empty_custom_and_unknown_id_are_value_errors(self) -> None:
        with self.assertRaises(ValueError):
            disaster_api.resolve_disaster("", {"name": "x", "stages": "   "})
        with self.assertRaises(ValueError):
            disaster_api.resolve_disaster("meteor")


class HttpTest(unittest.TestCase):
    def setUp(self) -> None:
        disaster_api.reset_jobs()

    def test_catalogue_endpoint(self) -> None:
        body, status = disaster_api.handle_get("/api/games/disaster/catalogue")
        self.assertEqual(status, 200)
        self.assertEqual(len(body["disasters"]), len(disaster_api.DISASTER_BANK))
        self.assertEqual(body["max_agents"], disaster_api.MAX_AGENTS)
        self.assertIn("救助他人", body["actions"])

    def test_run_without_agents_is_400(self) -> None:
        body, status = disaster_api.handle_post(
            "/api/games/disaster/run", {"city": "wuzhen", "disaster_id": "earthquake"}
        )
        self.assertEqual(status, 400)
        self.assertIn("error", body)

    def test_run_with_unknown_disaster_is_400(self) -> None:
        body, status = disaster_api.handle_post(
            "/api/games/disaster/run", {"agent_ids": [1], "disaster_id": "meteor"}
        )
        self.assertEqual(status, 400)
        self.assertIn("error", body)

    def test_run_opens_a_job_and_finishes(self) -> None:
        fake = {"run_id": "abc", "created_at": 1.0, "agents": [], "stages": [], "stats": {}}
        with mock.patch("gaworld.apps.disaster_api.run_disaster", return_value=fake):
            body, status = disaster_api.handle_post(
                "/api/games/disaster/run",
                {"city": "wuzhen", "agent_ids": [1, 2], "disaster_id": "earthquake"},
            )
            self.assertEqual(status, 200)
            job_id = body["job_id"]
            for _ in range(200):  # the job runs on its own thread
                record = disaster_api.job_status(job_id)
                if record and record["status"] != "running":
                    break
                import time

                time.sleep(0.01)
        record, status = disaster_api.handle_get(f"/api/games/disaster/jobs/{job_id}")
        self.assertEqual(status, 200)
        self.assertEqual(record["status"], "done")
        self.assertEqual(record["result"]["run_id"], "abc")

    def test_unknown_job_is_404(self) -> None:
        self.assertEqual(disaster_api.handle_get("/api/games/disaster/jobs/nope")[1], 404)

    def test_unknown_endpoints_are_404(self) -> None:
        self.assertEqual(disaster_api.handle_get("/api/games/disaster/nope")[1], 404)
        self.assertEqual(disaster_api.handle_post("/api/games/disaster/nope", {})[1], 404)

    def test_games_api_forwards_the_disaster_branch(self) -> None:
        body, status = games_api.handle_get("/api/games/disaster/catalogue")
        self.assertEqual(status, 200)
        self.assertIn("disasters", body)

        body, status = games_api.handle_post("/api/games/disaster/run", {})
        self.assertEqual(status, 400)
        self.assertIn("error", body)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
