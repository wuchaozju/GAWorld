"""Tests for 连续剧 (gaworld.apps.serial_api).

What we defend:

* **Catalogue shapes.** Themes + styles expose id / title / tone (theme) /
  shot_style (style); both have a built-in ``open`` / ``custom`` slot.
* **Style / theme resolution.** Built-ins resolve by id; custom blocks
  surface as ``id="custom"`` with the caller-supplied text.
* **Shot-card parsing.** Loose JSON is tolerated; missing fields fall back
  to defaults; transition tokens outside the allow-list are clamped to
  ``cut``; per-episode shot counts are normalised to the requested count.
* **Episode shaping.** Outline rows are trimmed / padded to the requested
  episode count; garbage falls back to per-row placeholder episodes that
  still mention every picked agent.
* **Premise parsing.** Cast rows with agent_ids outside the picked set are
  dropped; empty model output yields a "every-picked-agent-as-witness"
  fallback so the run still produces a coherent show.
* **Run shape.** Result has theme_id / style_id / cast / episodes /
  shots / logline / stats. Every picked agent_id appears in the cast.
  ``shots_per_episode`` and ``seconds_per_episode`` echoes the request.
* **Cost.** Two planner calls + one episode call per episode + one logline
  call. Injected callables are pure, no real LLM is reached.
* **HTTP delegation.** The ``/api/games/serial/`` branch in
  ``games_api`` returns catalogue / agents / runs / jobs[id] and starts
  jobs through ``/api/games/serial/run``. Bad input returns 400, unknown
  job 404.

No LLM is reached: ``planner_fn`` / ``episode_fn`` / ``logline_fn`` are
injected as plain callables, and persona cards are handed in directly.
"""

from __future__ import annotations

import unittest
from unittest import mock

from gaworld.apps import games_api, serial_api


def _card(agent_id, name, age=40, job="客服专员", residence="A小区"):
    return {
        "agent_id": agent_id,
        "name": name,
        "age": age,
        "gender": "女",
        "job": job,
        "residence": residence,
        "profile_md": f"**身份**：{name}，{job}。",
        "persona_short": f"你是{name}，{age}岁，{job}。",
    }


def _scripted(replies):
    """A planner/episode/logline fn that returns the scripted replies in order."""
    calls = []

    def fn(prompt: str) -> str:
        calls.append(prompt)
        return replies[min(len(calls) - 1, len(replies) - 1)]

    fn.calls = calls  # type: ignore[attr-defined]
    return fn


# ---------------------------------------------------------------------------
# Catalogue
# ---------------------------------------------------------------------------


class CatalogueTest(unittest.TestCase):
    def test_themes_and_styles_are_lists(self) -> None:
        themes = serial_api.list_themes()
        styles = serial_api.list_styles()
        for entry in themes:
            self.assertIn("id", entry)
            self.assertIn("title", entry)
            self.assertIn("tone", entry)
        for entry in styles:
            self.assertIn("id", entry)
            self.assertIn("title", entry)
            self.assertIn("text", entry)
            self.assertIn("shot_style", entry)

    def test_open_theme_and_custom_style_resolve(self) -> None:
        theme = serial_api.resolve_theme("open", {"tone": "一件小事", "prompt_seed": "扩展"})
        self.assertEqual(theme["id"], "custom")
        self.assertEqual(theme["tone"], "一件小事")
        style = serial_api.resolve_style("custom", {"text": "胶片质感", "shot_style": "固定机位"})
        self.assertEqual(style["id"], "custom")
        self.assertEqual(style["shot_style"], "固定机位")

    def test_unknown_ids_raise(self) -> None:
        with self.assertRaises(ValueError):
            serial_api.resolve_theme("nope")
        with self.assertRaises(ValueError):
            serial_api.resolve_style("nope")

    def test_custom_theme_without_tone_raises(self) -> None:
        with self.assertRaises(ValueError):
            serial_api.resolve_theme("open", {"tone": ""})
        with self.assertRaises(ValueError):
            serial_api.resolve_style("custom", {"text": ""})


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


class ParsePremiseTest(unittest.TestCase):
    def test_garbage_falls_back_to_all_witnesses(self) -> None:
        got = serial_api._parse_premise("not json", [1, 2])
        self.assertEqual([c["agent_id"] for c in got["cast"]], [1, 2])
        self.assertTrue(all(c["role"] == "见证者" for c in got["cast"]))

    def test_drops_unknown_agent_ids(self) -> None:
        raw = '{"premise":"x","cast":[{"agent_id":1,"role":"主角","arc":"a"},{"agent_id":99,"role":"对手","arc":"b"}],"arc":"y"}'
        got = serial_api._parse_premise(raw, [1])
        self.assertEqual([c["agent_id"] for c in got["cast"]], [1])
        self.assertEqual(got["premise"], "x")
        self.assertEqual(got["arc"], "y")


class ParseOutlineTest(unittest.TestCase):
    def test_pads_and_trims_to_requested(self) -> None:
        raw = '{"episodes":[{"episode":1,"title":"E1","logline":"l","characters":[1,2],"hook_to_next":"h"},{"episode":2,"title":"E2","logline":"l2","characters":[1],"hook_to_next":""}]}'
        out = serial_api._parse_outline(raw, [1, 2], episodes=4)
        self.assertEqual([e["episode"] for e in out], [1, 2, 3, 4])
        # E3+E4 placeholders get every picked id.
        self.assertEqual(out[2]["characters"], [1, 2])

    def test_garbage_creates_four_placeholders(self) -> None:
        out = serial_api._parse_outline("not json", [1, 2], episodes=3)
        self.assertEqual([e["episode"] for e in out], [1, 2, 3])
        self.assertTrue(all(e["title"].startswith("第") for e in out))


class ParseEpisodeTest(unittest.TestCase):
    def _raw(self, shots):
        import json

        return json.dumps({"shots": shots})

    def test_basic_shape(self) -> None:
        raw = self._raw(
            [
                {
                    "shot": 1,
                    "location": "楼下",
                    "time": "傍晚",
                    "shot_type": "中景",
                    "characters": [1],
                    "visual_prompt": "a",
                    "dialogue": "hi",
                    "sound": "wind",
                    "duration": 5,
                    "transition": "dissolve",
                }
            ]
        )
        shots = serial_api._parse_episode(raw, {"episode": 1, "characters": [1, 2]}, shots_per_episode=2)
        self.assertEqual(len(shots), 2)  # padded to shots_per_episode
        self.assertEqual(shots[0]["shot"], 1)
        self.assertEqual(shots[0]["duration"], 5)
        self.assertEqual(shots[0]["transition"], "dissolve")
        self.assertEqual(shots[0]["dialogue"], "hi")
        self.assertEqual(shots[1]["shot"], 2)

    def test_unknown_transition_clamps_to_cut(self) -> None:
        raw = self._raw([{"shot": 1, "characters": [1], "duration": 3, "transition": "banana"}])
        shots = serial_api._parse_episode(raw, {"episode": 1, "characters": [1]}, shots_per_episode=1)
        self.assertEqual(shots[0]["transition"], "cut")

    def test_duration_clamped_to_range(self) -> None:
        raw = self._raw(
            [
                {"shot": 1, "characters": [1], "duration": 9999},
                {"shot": 2, "characters": [1], "duration": 0},
            ]
        )
        shots = serial_api._parse_episode(raw, {"episode": 1, "characters": [1]}, shots_per_episode=2)
        self.assertEqual(shots[0]["duration"], serial_api.MAX_SHOT_SECONDS)
        self.assertEqual(shots[1]["duration"], serial_api.MIN_SHOT_SECONDS)

    def test_characters_filtered_to_episode(self) -> None:
        raw = self._raw([{"shot": 1, "characters": [1, 99], "duration": 5}])
        shots = serial_api._parse_episode(raw, {"episode": 1, "characters": [1]}, shots_per_episode=1)
        self.assertEqual(shots[0]["characters"], [1])

    def test_dialogue_list_shape_preserved(self) -> None:
        raw = self._raw(
            [{"shot": 1, "characters": [1], "duration": 4, "dialogue": [{"character": 1, "line": "你好"}]}]
        )
        shots = serial_api._parse_episode(raw, {"episode": 1, "characters": [1]}, shots_per_episode=1)
        self.assertEqual(shots[0]["dialogue"][0]["line"], "你好")

    def test_empty_input_yields_placeholder(self) -> None:
        shots = serial_api._parse_episode("not json", {"episode": 1, "characters": [1]}, shots_per_episode=2)
        self.assertEqual(len(shots), 2)
        self.assertEqual(shots[0]["characters"], [1])
        self.assertEqual(shots[0]["duration"], serial_api.DEFAULT_SHOT_SECONDS)


# ---------------------------------------------------------------------------
# Run shape
# ---------------------------------------------------------------------------


class RunShapeTest(unittest.TestCase):
    def _premise_reply(self):
        return '{"premise":"小区里一夜之间传开一桩陈年旧事","cast":[{"agent_id":1,"role":"主角","arc":"从回避到直面"},{"agent_id":2,"role":"对手","arc":"一直守着秘密"}],"arc":"从秘密被发现到各自做出选择"}'

    def _outline_reply(self):
        return '{"episodes":[{"episode":1,"title":"敲门声","logline":"老王敲了楼上门","characters":[1,2],"hook_to_next":"门开了"},{"episode":2,"title":"旧账","logline":"两人翻起三年前的账","characters":[1,2],"hook_to_next":"门外有人听见"}]}'

    def _episode_replies(self):
        return [
            '{"shots":[{"shot":1,"location":"楼下便利店","time":"傍晚","shot_type":"中景","characters":[1,2],"visual_prompt":"便利店玻璃门前","dialogue":"进来坐","sound":"环境","duration":6,"transition":"cut"},{"shot":2,"location":"便利店","time":"傍晚","shot_type":"特写","characters":[1],"visual_prompt":"她眼睛盯住","dialogue":[],"sound":"风","duration":4,"transition":"dissolve"}]}',
            '{"shots":[{"shot":1,"location":"咖啡店","time":"夜里","shot_type":"对话双人中近景","characters":[1,2],"visual_prompt":"咖啡桌","dialogue":[{"character":1,"line":"还钱"}],"sound":"","duration":7,"transition":"cut"}]}',
        ]

    def test_run_with_injected_fns(self) -> None:
        cards = [_card(1, "老王"), _card(2, "阿芳")]
        replies = [self._premise_reply(), self._outline_reply(), *self._episode_replies()]
        planner = _scripted([replies[0]])
        episode = _scripted(replies[2:])
        logline = _scripted(["一部关于邻里秘密的小剧。"])
        serial = serial_api.run_serial(
            city="",
            agent_ids=[1, 2],
            theme_id="family_secret",
            style_id="realistic_cn",
            episodes=2,
            shots_per_episode=3,  # MIN_SHOTS_PER_EPISODE; below this gets clamped.
            seconds_per_episode=18,
            title_hint="",
            user_brief="",
            cards=cards,
            planner_fn=planner,
            episode_fn=episode,
            logline_fn=logline,
        )
        self.assertEqual(serial["city"], "")
        self.assertEqual(serial["theme_id"], "family_secret")
        self.assertEqual(serial["style_id"], "realistic_cn")
        self.assertEqual(len(serial["episodes"]), 2)
        self.assertEqual(len(serial["episodes"][0]["shots"]), 3)
        self.assertEqual(serial["episodes"][0]["shots"][0]["location"], "楼下便利店")
        self.assertEqual(serial["episodes"][0]["shots"][1]["transition"], "dissolve")
        self.assertEqual(serial["stats"]["episodes"], 2)
        self.assertEqual(serial["stats"]["shots"], 6)  # 3 + 3 (each episode pads to shots_per_episode)
        # Cast mirrors picked ids.
        cast_ids = sorted(c["agent_id"] for c in serial["cast"])
        self.assertEqual(cast_ids, [1, 2])
        # Cost: 1 planner call (outline merged into planner_fn — premise and outline
        # share a callable), 2 episode calls, 1 logline call.
        self.assertEqual(len(planner.calls), 2)
        self.assertEqual(len(episode.calls), 2)
        self.assertEqual(len(logline.calls), 1)

    def test_run_below_min_shots_clamped(self) -> None:
        """shots_per_episode below MIN_SHOTS_PER_EPISODE must clamp, not crash."""
        cards = [_card(1, "老王"), _card(2, "阿芳")]
        replies = [
            self._premise_reply(),
            self._outline_reply(),
            '{"shots":[{"shot":1,"characters":[1],"duration":5,"transition":"cut"}]}',
            '{"shots":[{"shot":1,"characters":[1],"duration":5,"transition":"cut"}]}',
        ]
        planner = _scripted([replies[0]])
        episode = _scripted(replies[2:])
        serial = serial_api.run_serial(
            city="",
            agent_ids=[1, 2],
            theme_id="family_secret",
            style_id="realistic_cn",
            episodes=2,
            shots_per_episode=1,
            seconds_per_episode=12,
            cards=cards,
            planner_fn=planner,
            episode_fn=episode,
            logline_fn=lambda p: "",
        )
        for ep in serial["episodes"]:
            self.assertGreaterEqual(len(ep["shots"]), serial_api.MIN_SHOTS_PER_EPISODE)

    def test_run_min_max_bounds(self) -> None:
        with self.assertRaises(ValueError):
            serial_api.run_serial(city="", agent_ids=[1], cards=[_card(1, "x")])
        with self.assertRaises(ValueError):
            serial_api.run_serial(
                city="", agent_ids=[1, 2, 3, 4, 5, 6, 7], cards=[_card(i, f"n{i}") for i in range(1, 8)]
            )


# ---------------------------------------------------------------------------
# HTTP delegation
# ---------------------------------------------------------------------------


class HttpTest(unittest.TestCase):
    def setUp(self) -> None:
        serial_api.reset_jobs()
        # Stub the roster loader so HTTP tests don't need a real city bundle.
        self._roster_patch = mock.patch(
            "gaworld.interview.roster.load_population",
            return_value=[
                {"id": 1, "name": "老王", "age": 50, "gender": "男", "job": "退休", "residence": "A小区"}
            ],
        )
        self._roster_patch.start()

    def tearDown(self) -> None:
        self._roster_patch.stop()

    def test_catalogue_shape(self) -> None:
        body, status = serial_api.handle_get("/api/games/serial/catalogue", {})
        self.assertEqual(status, 200)
        self.assertIn("themes", body)
        self.assertIn("styles", body)
        self.assertEqual(body["max_agents"], serial_api.MAX_AGENTS)

    def test_agents_route(self) -> None:
        body, status = serial_api.handle_get("/api/games/serial/agents", {"city": ""})
        self.assertEqual(status, 200)
        self.assertEqual(body["agents"][0]["id"], 1)

    def test_run_validation_errors_return_400(self) -> None:
        _, status = serial_api.handle_post("/api/games/serial/run", {"agent_ids": [1]})
        self.assertEqual(status, 400)
        _, status = serial_api.handle_post("/api/games/serial/run", {"agent_ids": [1], "episodes": 99})
        self.assertEqual(status, 400)
        _, status = serial_api.handle_post("/api/games/serial/run", {"agent_ids": [1, 2], "theme_id": "nope"})
        self.assertEqual(status, 400)

    def test_runs_and_jobs_routes(self) -> None:
        body, status = serial_api.handle_get("/api/games/serial/runs", {})
        self.assertEqual(status, 200)
        self.assertIn("runs", body)
        _, status = serial_api.handle_get("/api/games/serial/jobs/serial-nope", {})
        self.assertEqual(status, 404)

    def test_unknown_endpoint_returns_404(self) -> None:
        _, status = serial_api.handle_get("/api/games/serial/unknown", {})
        self.assertEqual(status, 404)
        _, status = serial_api.handle_post("/api/games/serial/unknown", {})
        self.assertEqual(status, 404)

    def test_games_api_dispatches_to_serial(self) -> None:
        body, status = games_api.handle_get("/api/games/serial/catalogue", {})
        self.assertEqual(status, 200)
        self.assertIn("themes", body)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
