"""Tests for 严肃游戏 (gaworld.research.serious_game + gaworld.apps.serious_game_api).

What we defend:

* a model's design is normalised into a playable spec — ids made unique,
  indicators clamped, an unplayable design (one role, no rounds) refused;
* a session seats roles with residents or humans, and residents are not
  seated twice;
* a round is simultaneous: it waits for every human, the facilitator then
  resolves it, the indicators move within their bounds, and the last round
  ends in a debrief with scores on the fixed scale;
* views hide private briefs and agents' thoughts from everyone but the seat
  that owns them and the host;
* the HTTP routes behind ``/api/research/games`` return the documented
  shapes and the 400/404 contract, through ``research_api``.

No LLM is reached and no city bundle is read: the model is a scripted
function and personas are injected.
"""

from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from gaworld.apps import research_api, serious_game_api
from gaworld.research import serious_game as sg

DESIGN = {
    "title": "垃圾分类收费协商",
    "summary": "三方商量垃圾分类收费",
    "learning_objectives": ["体会多方协商中的信任建立"],
    "setting": "某小区要推行垃圾分类按量收费。",
    "roles": [
        {
            "id": "committee",
            "name": "居委会主任",
            "public": "推动方",
            "goal": "方案落地",
            "private": "上级有考核",
        },
        {
            "id": "committee",
            "name": "物业经理",
            "public": "执行方",
            "goal": "不亏钱",
            "private": "保洁人手不够",
        },
        {
            "id": "resident",
            "name": "居民代表",
            "public": "利益相关方",
            "goal": "少交钱",
            "private": "邻居不信任物业",
        },
    ],
    "indicators": [{"id": "trust", "name": "信任", "initial": 150, "min": 0, "max": 100}],
    "rounds": [
        {"title": "开场", "event": "通知贴出", "prompt": "表态", "options": ["支持", "反对"]},
        {"title": "讨价还价", "event": "居民群炸了", "prompt": "提出方案"},
    ],
    "scoring": [{"criterion": "协商", "description": "是否推动共识"}, "公平"],
    "debrief_questions": ["信任是怎么变化的？"],
}


def scripted_llm(prompt: str, task: str = "", provider: str = "") -> str:
    if "严肃游戏（serious game）设计师" in prompt:
        return "好的：\n```json\n" + json.dumps(DESIGN, ensure_ascii=False) + "\n```"
    if "裁定这一轮的结果" in prompt:
        return json.dumps(
            {
                "narration": "大家吵了一架，最后同意再谈。",
                "indicator_changes": {"trust": -30},
                "role_outcomes": {"committee": "压力变大"},
            },
            ensure_ascii=False,
        )
    if "复盘引导师" in prompt:
        return json.dumps(
            {
                "summary": "信任先降后稳。",
                "scores": [{"role_id": "committee", "scores": {"协商": 9, "公平": 3}, "comment": "积极"}],
                "objectives": [{"objective": "体会信任", "met": "maybe", "evidence": "第二轮"}],
                "answers": [{"question": "信任是怎么变化的？", "answer": "先降后稳"}],
                "insights": ["先听再说"],
            },
            ensure_ascii=False,
        )
    return json.dumps(
        {"choice": "支持", "action": "我先表个态，支持。", "thought": "其实心里没底"}, ensure_ascii=False
    )


def persona(city: str, agent_id: int | None) -> dict:
    return {
        "agent_id": agent_id or 7,
        "name": f"居民{agent_id or 7}",
        "age": 50,
        "gender": "女",
        "job": "退休教师",
    }


class SpecTest(unittest.TestCase):
    def test_design_is_normalised(self) -> None:
        spec = sg.normalize_spec(DESIGN)
        self.assertEqual([r["id"] for r in spec["roles"]], ["committee", "committee_2", "resident"])
        self.assertEqual(spec["indicators"][0]["initial"], 100)
        self.assertEqual([c["criterion"] for c in spec["scoring"]], ["协商", "公平"])
        self.assertEqual(spec["rounds"][1]["options"], [])

    def test_unplayable_design_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            sg.normalize_spec({**DESIGN, "roles": DESIGN["roles"][:1]})
        with self.assertRaises(ValueError):
            sg.normalize_spec({**DESIGN, "rounds": []})

    def test_roles_keyed_by_id_or_titled_are_accepted(self) -> None:
        roles = {"a": {"title": "甲"}, "b": {"role": "乙"}}
        spec = sg.normalize_spec({**DESIGN, "roles": roles})
        self.assertEqual([(r["id"], r["name"]) for r in spec["roles"]], [("a", "甲"), ("b", "乙")])

    def test_design_prompt_carries_the_requested_shape(self) -> None:
        prompt = sg.design_prompt("社区议事", rounds=3, roles=4)
        self.assertIn("正好 3 轮", prompt)
        self.assertIn("正好 4 个角色", prompt)
        self.assertIn("社区议事", prompt)

    def test_agent_action_falls_back_to_prose(self) -> None:
        move = sg.parse_agent_action("我会先去找物业谈谈。", ["支持"])
        self.assertEqual(move["action"], "我会先去找物业谈谈。")
        self.assertEqual(
            sg.parse_agent_action('{"choice": "支持一下", "action": "好"}', ["支持"])["choice"], "支持"
        )


class _StoreCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        patcher = mock.patch.object(sg, "games_root", return_value=Path(self.tmp.name))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)
        serious_game_api.reset()
        serious_game_api._LLM_OVERRIDE = scripted_llm
        self.addCleanup(setattr, serious_game_api, "_LLM_OVERRIDE", None)

    def design(self) -> dict:
        return sg.design_game("小区垃圾分类收费，三方协商", lambda p: scripted_llm(p))


class DesignRetryTest(_StoreCase):
    def test_an_unplayable_first_answer_is_retried_once(self) -> None:
        answers = iter(['{"roles": [], "rounds": []}', json.dumps(DESIGN, ensure_ascii=False)])
        game = sg.design_game("小区", lambda p: next(answers))
        self.assertEqual(len(game["spec"]["roles"]), 3)
        with self.assertRaises(ValueError):
            sg.design_game("小区", lambda p: "不会")


class SessionTest(_StoreCase):
    def test_full_game_with_one_human(self) -> None:
        game = self.design()
        seats = [{"role_id": "resident", "kind": "human", "player_name": "小王"}]
        session = sg.new_session(game, seats, persona_fn=persona)
        human = next(s for s in session["seats"] if s["kind"] == "human")
        self.assertEqual(human["player_name"], "小王")
        self.assertEqual(len(sg.pending_seats(session, "agent")), 2)

        for round_no in range(2):
            for seat in sg.pending_seats(session, "agent"):
                move = sg.parse_agent_action(scripted_llm(sg.agent_prompt(session, seat)), [])
                sg.record_action(session, seat["role_id"], move["action"], thought=move["thought"])
            self.assertEqual([s["role_id"] for s in sg.pending_seats(session)], ["resident"])
            sg.record_action(session, "resident", f"第{round_no + 1}轮我反对")
            with self.assertRaises(ValueError):
                sg.record_action(session, "resident", "再来一次")
            sg.apply_resolution(session, scripted_llm(sg.resolve_prompt(session)))

        self.assertEqual(session["status"], "debriefing")
        # 100 → 70 → 40, never below the floor.
        self.assertEqual(session["indicators"]["trust"], 40)
        debrief = sg.apply_debrief(session, scripted_llm(sg.debrief_prompt(session)))
        self.assertEqual(session["status"], "finished")
        self.assertEqual(debrief["scores"][0]["scores"], {"协商": 5, "公平": 3})
        self.assertEqual(debrief["objectives"][0]["met"], "partly")
        markdown = sg.export_markdown(session)
        self.assertIn("第2轮我反对", markdown)
        self.assertIn("信任 -30", markdown)

    def test_views_keep_secrets(self) -> None:
        game = self.design()
        session = sg.new_session(game, [{"role_id": "resident", "kind": "human"}], persona_fn=persona)
        sg.record_action(session, "committee", "支持", thought="心虚")
        token = next(s["token"] for s in session["seats"] if s["role_id"] == "resident")

        public = sg.public_view(session)
        self.assertTrue(all("private" not in r for r in public["roles"]))
        self.assertTrue(all("token" not in s for s in public["seats"]))
        self.assertNotIn("open_actions", public)

        mine = sg.public_view(session, seat_token=token)
        privates = {r["id"]: r.get("private") for r in mine["roles"]}
        self.assertEqual(privates["resident"], "邻居不信任物业")
        self.assertIsNone(privates["committee"])
        self.assertFalse(mine["me"]["acted"])

        host = sg.public_view(session, host=True)
        self.assertEqual(host["open_actions"]["committee"]["thought"], "心虚")
        self.assertTrue(all("token" in s for s in host["seats"]))

    def test_residents_are_not_seated_twice(self) -> None:
        game = self.design()
        people = [{"id": 1}, {"id": 2}, {"id": 3}]
        with (
            mock.patch("gaworld.interview.roster.load_population", return_value=people),
            mock.patch("gaworld.apps.games_api.load_persona", side_effect=lambda c, a: persona(c, a)),
        ):
            session = sg.new_session(game, [], city="wuzhen")
        ids = [s["persona"]["agent_id"] for s in session["seats"]]
        self.assertEqual(sorted(ids), [1, 2, 3])


class DriverRaceTest(_StoreCase):
    def test_action_landing_as_the_driver_stops_is_not_lost(self) -> None:
        # The driver has just decided to wait for the human, but has not left
        # _DRIVING yet; the human acts in that window, so its _kick is a no-op.
        session = sg.new_session(
            self.design(), [{"role_id": "resident", "kind": "human"}], persona_fn=persona
        )
        sid = session["id"]
        token = next(s["token"] for s in session["seats"] if s["kind"] == "human")
        serious_game_api._SESSIONS[sid] = session
        real_step = serious_game_api._step
        acted = []

        def step(session_id: str) -> bool:
            moved = real_step(session_id)
            if not moved and not acted:
                acted.append(serious_game_api.act(session_id, {"seat": token, "action": "我反对"}))
            return moved

        with mock.patch.object(serious_game_api, "_step", side_effect=step):
            serious_game_api._kick(sid, background=False)

        self.assertTrue(acted)
        self.assertEqual(session["round_index"], 1)
        self.assertNotIn(sid, serious_game_api._DRIVING)


class ApiTest(_StoreCase):
    def _wait(self, fn, timeout: float = 5.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            value = fn()
            if value:
                return value
            time.sleep(0.02)
        self.fail("timed out")

    def test_design_play_and_export_over_http(self) -> None:
        body, status = research_api.handle_post("/api/research/games/design", {"description": "小区垃圾分类"})
        self.assertEqual(status, 202)
        job = self._wait(
            lambda: (
                (rec := research_api.handle_get(f"/api/research/games/jobs/{body['job_id']}")[0])["status"]
                != "running"
                and rec
            )
        )
        self.assertEqual(job["status"], "done", job.get("error"))
        game_id = job["result"]["game_id"]

        listing, _ = research_api.handle_get("/api/research/games")
        self.assertEqual(listing["games"][0]["id"], game_id)

        seats = [{"role_id": "resident", "kind": "human", "player_name": "小王"}]
        with mock.patch.object(
            sg, "resident_persona", side_effect=lambda c, a, taken: persona(c, len(taken) + 1)
        ):
            created, status = research_api.handle_post(
                "/api/research/games/sessions", {"game_id": game_id, "seats": seats}
            )
        self.assertEqual(status, 200)
        sid = created["id"]
        token = next(s["token"] for s in created["seats"] if s["kind"] == "human")

        def agents_done():
            data = research_api.handle_get(f"/api/research/games/sessions/{sid}")[0]
            return data if sum(1 for s in data["seats"] if s["acted"]) == 2 else None

        self._wait(agents_done)
        _bad, status = research_api.handle_post(
            f"/api/research/games/sessions/{sid}/act", {"seat": "nope", "action": "x"}
        )
        self.assertEqual(status, 400)
        mine, status = research_api.handle_post(
            f"/api/research/games/sessions/{sid}/act", {"seat": token, "action": "我反对"}
        )
        self.assertEqual(status, 200)
        # Either still resolving round one, or the instant scripted model already opened round two.
        self.assertTrue(mine["me"]["acted"] or mine["round_index"] == 1)

        # Round two: the host stops waiting for the human.
        def round_two_waiting():
            data = research_api.handle_get(f"/api/research/games/sessions/{sid}")[0]
            return (
                data
                if data["round_index"] == 1 and sum(1 for s in data["seats"] if s["acted"]) == 2
                else None
            )

        self._wait(round_two_waiting)
        _, status = research_api.handle_post(f"/api/research/games/sessions/{sid}/resolve", {})
        self.assertEqual(status, 200)

        final = self._wait(
            lambda: (
                (d := research_api.handle_get(f"/api/research/games/sessions/{sid}")[0])["status"]
                == "finished"
                and d
            )
        )
        self.assertEqual(len(final["rounds"]), 2)
        self.assertEqual(final["rounds"][1]["actions"]["resident"]["action"], "（这一轮没有行动）")
        exported, _ = research_api.handle_get(f"/api/research/games/sessions/{sid}/export")
        self.assertIn("## 复盘", exported["markdown"])

        self.assertEqual(research_api.handle_get("/api/research/games/sessions/nope")[1], 404)
        self.assertEqual(research_api.handle_post("/api/research/games/design", {})[1], 400)
        deleted, _ = research_api.handle_post(f"/api/research/games/sessions/{sid}/delete", {})
        self.assertTrue(deleted["deleted"])


if __name__ == "__main__":
    unittest.main()
