"""Tests for 谣言扩散局 (gaworld.apps.rumor_api).

What we defend:

* **The derived graph.** Same address beats same trade, a shared surname
  under one roof reads as kin, the non-work job buckets ("退休", "学生",
  "无业…") never become colleagues, and no one keeps more than ``MAX_TIES``
  ties. The same selection always yields the same edges.
* **Propagation.** Only people who received something speak; a forward
  reaches at most ``FANOUT`` *new* neighbours; 私下求证 reaches exactly the
  closest one (and that is how they hear it); 不管 stops the chain dead.
* **Everyone speaks once, except a believer who is then told it is false.**
  That exception is the only reason 辟谣 is worth playing, so it is pinned.
* **The prompt** carries the persona, who told them, and the social proof.
* **Stats** — reach, believers, the diffusion tree, the superspreader and the
  firewalls — match the reactions.
* HTTP delegation returns the documented shapes and the 400/404 contract,
  including the ``/api/games/rumor/`` branch in ``games_api``.

No LLM is reached: ``answer_fn`` / ``summary_fn`` are injected and the nodes
are handed in directly.
"""

from __future__ import annotations

import time
import unittest
from unittest import mock

from gaworld.apps import games_api, rumor_api


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


#: Distinct surnames: the kin heuristic keys on "same roof + same surname",
#: so a cast that all shares one surname would turn every tie into 亲属.
_SURNAMES = "甲乙丙丁戊己庚辛壬癸"


def _cast(n: int, residence: str = "A小区") -> list[dict]:
    """*n* neighbours in one 小区, one surname each, three years apart."""
    return [_person(i, f"{_SURNAMES[i - 1]}{i}", age=30 + i, residence=residence) for i in range(1, n + 1)]


def _nodes(*people) -> dict[int, rumor_api.Node]:
    return {
        int(p["id"]): rumor_api.Node(
            agent_id=int(p["id"]),
            name=p["name"],
            age=p["age"],
            job=p["job"],
            residence=p["residence"],
            persona_text=f"你是{p['name']}，{p['age']}岁。",
        )
        for p in people
    }


def _say(action: str, belief: int = 80, text: str = "我看是真的"):
    return f'{{"belief": {belief}, "action": "{action}", "say": "{text}"}}'


def _always(reply: str):
    calls: list[str] = []

    def fn(prompt: str) -> str:
        calls.append(prompt)
        return reply

    fn.calls = calls  # type: ignore[attr-defined]
    return fn


class GraphTest(unittest.TestCase):
    def test_same_address_is_a_neighbour_tie(self) -> None:
        edges = rumor_api.build_graph([_person(1, "甲一"), _person(2, "乙二")])
        self.assertEqual(len(edges), 1)
        self.assertEqual(edges[0]["role"], "neighbor")
        self.assertEqual(edges[0]["closeness"], 0.55)

    def test_shared_surname_under_one_roof_reads_as_kin(self) -> None:
        edges = rumor_api.build_graph([_person(1, "闫然", age=41), _person(2, "闫嘉", age=12)])
        self.assertEqual(edges[0]["role"], "relative")
        self.assertEqual(edges[0]["label"], "亲属")

    def test_non_work_jobs_do_not_become_colleagues(self) -> None:
        # Two retirees in different 小区, 20 years apart: nothing should link them.
        edges = rumor_api.build_graph(
            [
                _person(1, "甲一", age=66, job="退休", residence="A小区"),
                _person(2, "乙二", age=86, job="退休", residence="B小区"),
            ]
        )
        self.assertEqual(edges, [])

    def test_same_real_job_across_addresses_is_a_coworker_tie(self) -> None:
        edges = rumor_api.build_graph(
            [
                _person(1, "甲一", age=30, job="美发店员", residence="A小区"),
                _person(2, "乙二", age=55, job="美发店员", residence="B小区"),
            ]
        )
        self.assertEqual(edges[0]["role"], "coworker")

    def test_same_age_across_addresses_is_only_a_weak_tie(self) -> None:
        edges = rumor_api.build_graph(
            [
                _person(1, "甲一", age=30, job="教师", residence="A小区"),
                _person(2, "乙二", age=31, job="司机", residence="B小区"),
            ]
        )
        self.assertEqual(edges[0]["role"], "acquaintance")
        self.assertEqual(edges[0]["closeness"], 0.25)

    def test_degree_is_capped_and_deterministic(self) -> None:
        people = _cast(10)  # one big 小区
        edges = rumor_api.build_graph(people)
        degree: dict[int, int] = {}
        for edge in edges:
            degree[edge["a"]] = degree.get(edge["a"], 0) + 1
            degree[edge["b"]] = degree.get(edge["b"], 0) + 1
        self.assertTrue(degree)
        self.assertLessEqual(max(degree.values()), rumor_api.MAX_TIES)
        self.assertEqual(edges, rumor_api.build_graph(people))


class SpreadTest(unittest.TestCase):
    def setUp(self) -> None:
        self.people = _cast(5)
        self.edges = rumor_api.build_graph(self.people)

    def _run(self, reply: str, **kwargs):
        answer = _always(reply)
        run = rumor_api.run_rumor(
            city="",
            agent_ids=[],
            rumor_id=kwargs.pop("rumor_id", "water"),
            nodes=kwargs.pop("nodes", _nodes(*self.people)),
            edges=kwargs.pop("edges", self.edges),
            answer_fn=answer,
            summary_fn=lambda p: "简报",
            **kwargs,
        )
        return run, answer

    def test_only_the_seeds_speak_when_nobody_forwards(self) -> None:
        run, answer = self._run(_say("不管", belief=10), seeds=[1], rounds=3)
        self.assertEqual(len(answer.calls), 1)  # type: ignore[attr-defined]
        self.assertEqual(run["stats"]["reached"], 1)
        self.assertEqual(run["transmissions"], [])

    def test_a_forward_reaches_new_neighbours_only(self) -> None:
        run, _ = self._run(_say("转发"), seeds=[1], rounds=2)
        first_hop = [t for t in run["transmissions"] if t["round"] == 0]
        self.assertTrue(first_hop)
        self.assertLessEqual(len(first_hop), rumor_api.FANOUT)
        self.assertTrue(all(t["from"] == 1 and t["kind"] == "rumor" for t in first_hop))
        # Nobody is told twice by the same hop.
        self.assertEqual(len({t["to"] for t in first_hop}), len(first_hop))

    def test_asking_around_reaches_exactly_the_closest_contact(self) -> None:
        run, _ = self._run(_say("私下求证", belief=40), seeds=[1], rounds=2)
        hop = [t for t in run["transmissions"] if t["round"] == 0]
        self.assertEqual(len(hop), 1)
        self.assertEqual(hop[0]["kind"], "question")
        # Being asked counts as hearing it.
        asked = hop[0]["to"]
        heard = {n["agent_id"]: n["heard_round"] for n in run["nodes"]}
        self.assertEqual(heard[asked], 1)

    def test_everyone_speaks_at_most_once(self) -> None:
        run, answer = self._run(_say("转发"), seeds=[1], rounds=rumor_api.MAX_ROUNDS)
        self.assertLessEqual(len(answer.calls), len(self.people))  # type: ignore[attr-defined]
        for node in run["nodes"]:
            self.assertLessEqual(len(node["spoke_rounds"]), 1)

    def test_a_believer_gets_one_more_turn_when_corrected(self) -> None:
        # #1 forwards it; #2 debunks; #1 (a believer) is allowed to answer again.
        replies = {1: _say("转发", belief=90), 2: _say("辟谣", belief=5)}

        def answer(prompt: str) -> str:
            if "你是甲1" not in prompt:
                return replies[2]
            # "你之前听到这条的时候信了…" appears only on the corrected turn;
            # "这是假的" would also match the action glossary in every prompt.
            return _say("不管", belief=20) if "你之前听到这条" in prompt else replies[1]

        nodes = _nodes(*self.people)
        run = rumor_api.run_rumor(
            city="",
            agent_ids=[],
            rumor_id="water",
            nodes=nodes,
            edges=self.edges,
            seeds=[1],
            rounds=3,
            answer_fn=answer,
            summary_fn=lambda p: "",
        )
        first = next(n for n in run["nodes"] if n["agent_id"] == 1)
        self.assertEqual(len(first["spoke_rounds"]), 2)
        self.assertEqual(first["belief"], 20)  # talked back down
        self.assertFalse(first["believes"])

    def test_default_seeds_are_well_connected_and_not_adjacent(self) -> None:
        # Two 小区 joined only by weak ties: the seeds must land one in each,
        # or the second cluster never hears anything.
        people = [
            *_cast(4, residence="A小区"),
            *(
                _person(i, f"{_SURNAMES[i - 1]}{i}", age=60 + i, residence="B小区", job="美发店员")
                for i in range(5, 9)
            ),
        ]
        edges = rumor_api.build_graph(people)
        run = rumor_api.run_rumor(
            city="",
            agent_ids=[],
            rumor_id="water",
            nodes=_nodes(*people),
            edges=edges,
            rounds=1,
            answer_fn=_always(_say("不管", belief=10)),
            summary_fn=lambda p: "",
        )
        self.assertEqual(len(run["seeds"]), 2)
        first, second = run["seeds"]
        adjacent = {(e["a"], e["b"]) for e in run["edges"]} | {(e["b"], e["a"]) for e in run["edges"]}
        self.assertNotIn((first, second), adjacent)

    def test_asking_around_prefers_someone_who_has_not_heard(self) -> None:
        # #1 and #2 both know it; #1 asks around and must not spend the turn
        # on #2, who already heard it.
        nodes = _nodes(*self.people)
        nodes[2].heard_round = 0
        run = rumor_api.run_rumor(
            city="",
            agent_ids=[],
            rumor_id="water",
            nodes=nodes,
            edges=self.edges,
            seeds=[1],
            rounds=1,
            answer_fn=_always(_say("私下求证", belief=40)),
            summary_fn=lambda p: "",
        )
        hop = run["transmissions"][0]
        self.assertNotEqual(hop["to"], 2)

    def test_an_isolated_resident_never_hears_it(self) -> None:
        people = [*self.people, _person(9, "辛九", age=88, job="退休", residence="Z小区")]
        run = rumor_api.run_rumor(
            city="",
            agent_ids=[],
            rumor_id="water",
            nodes=_nodes(*people),
            edges=rumor_api.build_graph(people),
            seeds=[1],
            rounds=rumor_api.MAX_ROUNDS,
            answer_fn=_always(_say("转发")),
            summary_fn=lambda p: "",
        )
        lonely = next(n for n in run["nodes"] if n["agent_id"] == 9)
        self.assertIsNone(lonely["heard_round"])
        self.assertIsNone(lonely["belief"])

    def test_prompt_carries_persona_source_and_social_proof(self) -> None:
        run, answer = self._run(_say("转发"), seeds=[1], rounds=2)
        first, second = answer.calls[0], answer.calls[1]  # type: ignore[attr-defined]
        self.assertIn("你是甲1", first)
        self.assertIn("自来水", first)
        self.assertIn("小区群里刷到的", first)  # a seed has no sender
        self.assertIn("是甲1", second)  # who told them
        self.assertIn("在你认识的人里", second)  # social proof
        self.assertTrue(any(t["to"] for t in run["transmissions"]))

    def test_a_broken_reply_stops_at_that_person(self) -> None:
        run, _ = self._run("模型今天不想说话", seeds=[1], rounds=2)
        node = next(n for n in run["nodes"] if n["agent_id"] == 1)
        self.assertEqual(node["action"], rumor_api.OTHER_ACTION)
        self.assertEqual(node["belief"], 0)
        self.assertEqual(run["transmissions"], [])

    def test_a_failing_summary_does_not_fail_the_run(self) -> None:
        def boom(prompt: str) -> str:
            raise RuntimeError("provider down")

        run = rumor_api.run_rumor(
            city="",
            agent_ids=[],
            rumor_id="bank",
            nodes=_nodes(*self.people),
            edges=self.edges,
            seeds=[1],
            rounds=1,
            answer_fn=_always(_say("转发")),
            summary_fn=boom,
        )
        self.assertEqual(run["summary"], "")
        self.assertEqual(run["stats"]["reached"], 1)


class StatsTest(unittest.TestCase):
    def test_reach_believers_and_roles(self) -> None:
        people = _cast(3)
        edges = rumor_api.build_graph(people)

        def answer(prompt: str) -> str:
            return _say("转发", belief=90) if "你是甲1" in prompt else _say("不管", belief=10)

        run = rumor_api.run_rumor(
            city="",
            agent_ids=[],
            rumor_id="grain",
            nodes=_nodes(*people),
            edges=edges,
            seeds=[1],
            rounds=2,
            answer_fn=answer,
            summary_fn=lambda p: "",
        )
        stats = run["stats"]
        self.assertEqual(stats["total"], 3)
        self.assertEqual(stats["reached"], 3)
        self.assertEqual(stats["believers"], 1)
        self.assertEqual(stats["silent"], 2)
        self.assertEqual(stats["superspreader"]["agent_id"], 1)
        self.assertEqual(stats["superspreader"]["n"], 2)
        self.assertEqual(stats["firewalls"], [2, 3])
        self.assertEqual([r["round"] for r in run["rounds"]], [0, 1])
        self.assertEqual(run["rounds"][0]["reached"], 1)
        self.assertEqual(run["rounds"][1]["reached"], 3)


class ParseTest(unittest.TestCase):
    def test_clean_json(self) -> None:
        got = rumor_api.parse_reaction(_say("辟谣", belief=5, text="别传了"))
        self.assertEqual(got, {"belief": 5, "action": "辟谣", "say": "别传了"})

    def test_json_wrapped_in_prose(self) -> None:
        got = rumor_api.parse_reaction('嗯：\n{"belief": 70, "action": "转发"}\n就这样')
        self.assertEqual(got["action"], "转发")
        self.assertEqual(got["belief"], 70)

    def test_a_stray_closing_brace_still_parses(self) -> None:
        # Seen in a real run: the model emitted one brace too many.
        got = rumor_api.parse_reaction('{"belief": 35, "action": "私下求证", "say": "真的假的？"}}')
        self.assertEqual(got["action"], "私下求证")
        self.assertEqual(got["belief"], 35)

    def test_belief_is_clamped_and_garbage_is_zero(self) -> None:
        self.assertEqual(rumor_api.parse_reaction('{"belief": 900, "action": "不管"}')["belief"], 100)
        self.assertEqual(rumor_api.parse_reaction('{"belief": "很信", "action": "不管"}')["belief"], 0)
        self.assertEqual(rumor_api.parse_reaction("啥也不是")["action"], rumor_api.OTHER_ACTION)

    def test_off_vocabulary_action_is_mapped_or_othered(self) -> None:
        self.assertEqual(rumor_api.parse_reaction('{"action": "赶紧转发出去"}')["action"], "转发")
        self.assertEqual(rumor_api.parse_reaction('{"action": "报警"}')["action"], rumor_api.OTHER_ACTION)


class CatalogueTest(unittest.TestCase):
    def test_bank_entries_are_playable(self) -> None:
        for item in rumor_api.list_rumors():
            self.assertTrue(item["title"])
            self.assertTrue(item["text"])

    def test_custom_rumor_and_unknown_id(self) -> None:
        got = rumor_api.resolve_rumor("", {"title": "停电三天", "text": "电网检修要停三天"})
        self.assertEqual(got["title"], "停电三天")
        with self.assertRaises(ValueError):
            rumor_api.resolve_rumor("", {"title": "x", "text": "  "})
        with self.assertRaises(ValueError):
            rumor_api.resolve_rumor("nope")


class HttpTest(unittest.TestCase):
    def setUp(self) -> None:
        rumor_api.reset_jobs()

    def test_catalogue_endpoint(self) -> None:
        body, status = rumor_api.handle_get("/api/games/rumor/catalogue")
        self.assertEqual(status, 200)
        self.assertEqual(len(body["rumors"]), len(rumor_api.RUMOR_BANK))
        self.assertIn("辟谣", body["actions"])

    def test_graph_endpoint_costs_nothing_and_reports_isolation(self) -> None:
        people = [
            _person(1, "甲一", age=30),
            _person(2, "乙二", age=31),
            _person(9, "辛九", age=88, job="退休", residence="Z小区"),
        ]
        with mock.patch("gaworld.interview.roster.load_population", return_value=people):
            body, status = rumor_api.handle_get(
                "/api/games/rumor/graph", {"city": ["wuzhen"], "agent_ids": ["1,2,9"]}
            )
        self.assertEqual(status, 200)
        self.assertEqual(len(body["nodes"]), 3)
        self.assertEqual(body["isolated"], [9])

    def test_graph_endpoint_reports_a_missing_agent(self) -> None:
        with mock.patch("gaworld.interview.roster.load_population", return_value=[]):
            body, status = rumor_api.handle_get(
                "/api/games/rumor/graph", {"city": ["wuzhen"], "agent_ids": ["7"]}
            )
        self.assertEqual(status, 400)
        self.assertIn("error", body)

    def test_run_needs_two_people(self) -> None:
        body, status = rumor_api.handle_post(
            "/api/games/rumor/run", {"city": "wuzhen", "agent_ids": [1], "rumor_id": "water"}
        )
        self.assertEqual(status, 400)
        self.assertIn("error", body)

    def test_run_with_unknown_rumor_is_400(self) -> None:
        _, status = rumor_api.handle_post("/api/games/rumor/run", {"agent_ids": [1, 2], "rumor_id": "aliens"})
        self.assertEqual(status, 400)

    def test_run_opens_a_job_and_finishes(self) -> None:
        fake = {"run_id": "abc", "created_at": 1.0, "nodes": [], "stats": {"total": 0}}
        with mock.patch("gaworld.apps.rumor_api.run_rumor", return_value=fake):
            body, status = rumor_api.handle_post(
                "/api/games/rumor/run",
                {"city": "wuzhen", "agent_ids": [1, 2], "rumor_id": "water"},
            )
            self.assertEqual(status, 200)
            job_id = body["job_id"]
            for _ in range(200):  # the job runs on its own thread
                record = rumor_api.job_status(job_id)
                if record and record["status"] != "running":
                    break
                time.sleep(0.01)
        record, status = rumor_api.handle_get(f"/api/games/rumor/jobs/{job_id}")
        self.assertEqual(status, 200)
        self.assertEqual(record["status"], "done")
        self.assertEqual(record["result"]["run_id"], "abc")
        listing, status = rumor_api.handle_get("/api/games/rumor/runs")
        self.assertEqual(listing["runs"][0]["job_id"], job_id)

    def test_unknown_job_and_endpoints_are_404(self) -> None:
        self.assertEqual(rumor_api.handle_get("/api/games/rumor/jobs/nope")[1], 404)
        self.assertEqual(rumor_api.handle_get("/api/games/rumor/nope")[1], 404)
        self.assertEqual(rumor_api.handle_post("/api/games/rumor/nope", {})[1], 404)

    def test_games_api_forwards_the_rumor_branch(self) -> None:
        body, status = games_api.handle_get("/api/games/rumor/catalogue")
        self.assertEqual(status, 200)
        self.assertIn("rumors", body)

        body, status = games_api.handle_post("/api/games/rumor/run", {})
        self.assertEqual(status, 400)
        self.assertIn("error", body)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
