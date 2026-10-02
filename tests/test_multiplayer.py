"""People playing residents of an open world (proposal 2026-10-01-multi-user, P4).

* The simulator plugin: a claimed resident's next step follows the player's
  intent (perception + action), speech reaches the target's next perception,
  everything is recorded, a lapsed lease hands the resident back, and the
  optional per-tick wait holds only while a player still has to act.
* ``/api/play``: only open worlds (or your own) are playable; one player per
  resident and one resident per player; actions need a running simulation and
  travel through the world's intervention queue; presence lands in the world's
  record stream, including leases that lapse.
"""

from __future__ import annotations

import http.client
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from gaworld import worlds
from gaworld.accounts import AccountStore, policy
from gaworld.apps import dashboard_server as ds
from gaworld.apps import play_api
from gaworld.kernel import build_kernel
from gaworld.multiplayer import plugin as mp
from gaworld.plugins import builtin_plugins

PASSWORD = "correct horse"


def _rows(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


class PluginTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ctx = build_kernel(
            {
                "records": {"output_dir": self.tmp.name},
                "kernel": {"interventions_path": os.path.join(self.tmp.name, "queue.json")},
            },
            load_entry_points=False,
        )
        self.agents = [{"id": 1, "name": "甲"}, {"id": 2, "name": "乙"}]
        self.ctx.set_agents(self.agents)
        self.plugin = mp.MultiplayerPlugin()
        self.plugin.setup(self.ctx)

    def tearDown(self):
        self.tmp.cleanup()

    def _do(self, name, **kwargs):
        return self.ctx.controller.intervene(name, self.ctx, **kwargs)

    def _sections(self, agent):
        return self.ctx.bus.collect("perception.sections", agent=agent, sim=self.ctx)

    def _action(self, agent):
        return self.ctx.bus.filter("action.selected", "散步", agent=agent, sim=self.ctx)

    def test_registered_as_builtin(self):
        self.assertIn("multiplayer", [p.id for p in builtin_plugins()])

    def test_a_player_steers_one_step_of_their_resident(self):
        with self.assertRaises(ValueError):  # nobody plays #1 yet
            self._do("player_act", agent_id=1, text="去菜市场")
        self._do("player_claim", agent_id=1, player="小王", until=time.time() + 60)
        self._do("player_act", agent_id=1, text="去菜市场  找李阿姨")
        self.assertTrue(any("去菜市场 找李阿姨" in line for line in self._sections(self.agents[0])))
        self.assertEqual(self._action(self.agents[0]), "去菜市场 找李阿姨")
        self.assertEqual(self._action(self.agents[1]), "散步")  # others untouched
        self.ctx.bus.emit("on_agent_post_step", agent=self.agents[0], sim=self.ctx)
        self.assertEqual(self._action(self.agents[0]), "散步")  # an intent drives one action

    def test_a_travelling_step_keeps_the_intent(self):
        self._do("player_claim", agent_id=1, player="小王", until=time.time() + 60)
        self._do("player_act", agent_id=1, text="去菜市场")
        # A step spent travelling never selects an action, so nothing is used up.
        self.ctx.bus.emit("on_agent_post_step", agent=self.agents[0], sim=self.ctx)
        self.assertTrue(any("去菜市场" in line for line in self._sections(self.agents[0])))
        self.assertEqual(self._action(self.agents[0]), "去菜市场")
        acts = _rows(os.path.join(self.tmp.name, "multiplayer.act.jsonl"))
        self.assertEqual((acts[0]["player"], acts[0]["agent_name"]), ("小王", "甲"))

    def test_speech_reaches_the_target_once(self):
        self._do("player_claim", agent_id=1, player="小王", until=time.time() + 60)
        self._do("player_say", agent_id=1, target_id=2, text="明天开会吗？")
        heard = self._sections(self.agents[1])
        self.assertTrue(any("甲对你说：「明天开会吗？」" in line for line in heard))
        self.assertEqual(self._sections(self.agents[1]), [])
        self.assertTrue(any("你对乙说了" in line for line in self._sections(self.agents[0])))
        self.assertEqual(_rows(os.path.join(self.tmp.name, "multiplayer.say.jsonl"))[0]["target_name"], "乙")

    def test_a_lapsed_lease_hands_the_resident_back(self):
        self._do("player_claim", agent_id=1, player="小王", until=time.time() + 60)
        self._do("player_act", agent_id=1, text="去菜市场")
        self._do("player_claim", agent_id=1, player="小王", until=time.time() - 1)
        self.assertEqual(self._action(self.agents[0]), "散步")
        self._do("player_claim", agent_id=1, player="小王", until=time.time() + 60)
        self._do("player_release", agent_id=1)
        with self.assertRaises(ValueError):
            self._do("player_act", agent_id=1, text="x")

    def test_tick_waits_only_for_players_yet_to_act(self):
        self.ctx.config["multiplayer"] = {"wait_for_players_seconds": 0.6}
        with mock.patch.object(mp, "WAIT_POLL_SECONDS", 0.05):
            started = time.time()
            self.ctx.bus.emit("on_time_tick", sim=self.ctx)  # nobody playing: no wait
            self.assertLess(time.time() - started, 0.2)
            self._do("player_claim", agent_id=1, player="小王", until=time.time() + 60)
            started = time.time()
            self.ctx.bus.emit("on_time_tick", sim=self.ctx)
            self.assertGreaterEqual(time.time() - started, 0.55)
            self._do("player_act", agent_id=1, text="去菜市场")
            started = time.time()
            self.ctx.bus.emit("on_time_tick", sim=self.ctx)
            self.assertLess(time.time() - started, 0.2)


class PlayHttpTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = self.tmp.name
        os.makedirs(os.path.join(root, "seed"))
        self.csv, self.md = os.path.join(root, "seed", "a.csv"), os.path.join(root, "seed", "a.md")
        with open(self.csv, "w", encoding="utf-8") as f:
            f.write("id,name\n1,甲\n2,乙\n")
        with open(self.md, "w", encoding="utf-8") as f:
            f.write("## Profile 1 | 甲\n一位居民。\n\n## Profile 2 | 乙\n另一位。\n")
        db = os.path.join(root, "accounts.sqlite")
        self.store = AccountStore(db)
        self.store.init_schema()
        self.store.create_user("小王", PASSWORD)
        self.store.create_user("小李", PASSWORD)
        self.patches = [
            mock.patch.dict(os.environ, {"GAWORLD_ACCOUNTS_DB": db}),
            mock.patch.object(ds, "REPO_ROOT", root),
            mock.patch.object(ds, "DASHBOARD_CONFIG_PATH", os.path.join(root, "dashboard_config.json")),
            mock.patch.object(ds, "_city_seed_files", return_value=("", self.csv, self.md)),
        ]
        for patch in self.patches:
            patch.start()
        os.environ.pop("GAWORLD_DASHBOARD_TOKEN", None)
        play_api.reset()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), ds.DashboardHandler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.port = self.server.server_address[1]

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        play_api.reset()
        for patch in reversed(self.patches):
            patch.stop()
        self.tmp.cleanup()

    def _req(self, method, path, body=None, cookies=()):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        headers = {"Cookie": "; ".join(cookies), "Content-Type": "application/json"}
        conn.request(method, path, body=json.dumps(body) if body is not None else None, headers=headers)
        resp = conn.getresponse()
        data = resp.read()
        conn.close()
        return resp, json.loads(data) if data else None

    def _cookie(self, resp):
        return resp.getheader("Set-Cookie").split(";", 1)[0]

    def _login(self, nickname):
        return self._cookie(
            self._req("POST", "/api/auth/login", {"nickname": nickname, "password": PASSWORD})[0]
        )

    def _queue_live(self, world_id):
        """Pretend the world's simulator is running with the plugin loaded."""
        path = os.path.join(self.tmp.name, worlds.root(world_id), "kernel", "interventions.json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        names = ["player_act", "player_claim", "player_release", "player_say", "update_config"]
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"active": True, "pid": os.getpid(), "registered": names, "pending": []}, f)
        return path

    def test_policy(self):
        self.assertEqual(policy.required("POST", "/api/play/act"), "member")

    def test_two_players_in_an_open_world(self):
        wang, li = self._login("小王"), self._login("小李")
        resp, body = self._req("POST", "/api/worlds/create", {"name": "开放城"}, [wang])
        world_id, in_world = body["world"]["id"], self._cookie(resp)

        # Private: the other student cannot even enter; the owner can play.
        self.assertEqual(self._req("GET", "/api/play", cookies=[li, in_world])[0].status, 403)
        self.assertEqual(self._req("GET", "/api/play", cookies=[wang, in_world])[0].status, 200)
        self._req("POST", f"/api/worlds/{world_id}/visibility", {"visibility": "open"}, [wang])

        resp, body = self._req("POST", "/api/play/claim", {"agent_id": 1}, [li, in_world])
        self.assertEqual((resp.status, body["name"]), (200, "甲"))
        resp, body = self._req("POST", "/api/play/claim", {"agent_id": 1}, [wang, in_world])
        self.assertEqual(resp.status, 409)
        self.assertIn("小李", body["error"])
        self.assertEqual(
            self._req("POST", "/api/play/claim", {"agent_id": 9}, [wang, in_world])[0].status, 404
        )
        self._req("POST", "/api/play/claim", {"agent_id": 2}, [wang, in_world])
        state = self._req("GET", "/api/play", cookies=[li, in_world])[1]
        self.assertEqual(state["mine"], 1)
        self.assertEqual([(c["agent_id"], c["player"]) for c in state["claims"]], [(1, "小李"), (2, "小王")])

        # Not running: claims are fine, actions are not.
        resp, body = self._req("POST", "/api/play/act", {"text": "去菜市场"}, [li, in_world])
        self.assertEqual(resp.status, 409)

        queue = self._queue_live(world_id)
        with mock.patch.object(play_api, "_running", return_value=True):
            self.assertEqual(
                self._req("POST", "/api/play/act", {"text": "去菜市场"}, [li, in_world])[0].status, 200
            )
            self.assertEqual(
                self._req("POST", "/api/play/say", {"target_id": 2, "text": "你好"}, [li, in_world])[
                    0
                ].status,
                200,
            )
            self.assertEqual(
                self._req("POST", "/api/play/say", {"target_id": 1, "text": "自言自语"}, [li, in_world])[
                    0
                ].status,
                404,
            )
        with open(queue, encoding="utf-8") as handle:
            pending = json.load(handle)["pending"]
        self.assertEqual([p["name"] for p in pending], ["player_act", "player_say"])
        self.assertEqual(pending[0]["kwargs"], {"agent_id": 1, "text": "去菜市场"})

        # Switching residents lets go of the first one.
        self._req("POST", "/api/play/release", {}, [wang, in_world])
        self._req("POST", "/api/play/claim", {"agent_id": 2}, [li, in_world])
        self.assertEqual(self._req("GET", "/api/play", cookies=[li, in_world])[1]["mine"], 2)

        presence = _rows(
            os.path.join(self.tmp.name, worlds.root(world_id), "records", "multiplayer.presence.jsonl")
        )
        self.assertEqual(
            [(r["event"], r["agent_id"], r["player"]) for r in presence],
            [
                ("claim", 1, "小李"),
                ("claim", 2, "小王"),
                ("release", 2, "小王"),
                ("release", 1, "小李"),
                ("claim", 2, "小李"),
            ],
        )

    def test_a_closed_tab_lets_go_after_the_lease(self):
        wang = self._login("小王")
        resp, body = self._req("POST", "/api/worlds/create", {"name": "城"}, [wang])
        world_id, in_world = body["world"]["id"], self._cookie(resp)
        with mock.patch.object(play_api, "LEASE_SECONDS", 0.05):
            self._req("POST", "/api/play/claim", {"agent_id": 1}, [wang, in_world])
        time.sleep(0.1)
        self.assertEqual(self._req("GET", "/api/play", cookies=[wang, in_world])[1]["claims"], [])
        presence = _rows(
            os.path.join(self.tmp.name, worlds.root(world_id), "records", "multiplayer.presence.jsonl")
        )
        self.assertEqual([r["event"] for r in presence], ["claim", "lapse"])


INTENT = "去图书馆借一本讲社区自治的书"
_SEEN: dict[str, list] = {"actions": []}


def _play_agent4_on_day1(ctx):
    """A player takes resident #4 at the start of day 1 and tells them what to do."""
    if ctx.get("day") != 1 or _SEEN.get("claimed"):
        return
    _SEEN["claimed"] = True
    sim = ctx["sim"]
    sim.controller.intervene("player_claim", sim, agent_id=4, player="小王", until=time.time() + 600)
    sim.controller.intervene("player_act", sim, agent_id=4, text=INTENT)


def _capture_actions(ctx):
    step = ctx.get("step") or {}
    _SEEN["actions"].append((int(ctx["agent"]["id"]), step.get("action")))


class FullSimTest(unittest.TestCase):
    """The plugin inside the real main loop, with a scripted model."""

    def test_player_intent_reaches_perception_and_action(self):
        import generative_city_sim as sim
        from gaworld.settings import CONFIG
        from tests.fixtures.mock_llm import install

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        touched = (
            "agent_ids",
            "sim_days",
            "stateful",
            "simulate_realtime",
            "seconds_per_day",
            "news",
            "intervention",
            "extensions",
            "external_environment_service",
            "distributed",
            "visualization",
            "life_events",
            "external_rag",
            "records",
        )
        originals = {key: CONFIG[key] for key in touched if key in CONFIG}
        self.addCleanup(lambda: [CONFIG.__setitem__(k, v) for k, v in originals.items()])
        _SEEN.clear()
        _SEEN["actions"] = []

        CONFIG.update(
            agent_ids=[4, 5], sim_days=1, stateful=False, simulate_realtime=False, seconds_per_day=1
        )
        CONFIG["records"] = {"output_dir": tmp.name}
        CONFIG["extensions"] = dict(CONFIG.get("extensions", {}))
        hooks = {phase: list(paths) for phase, paths in CONFIG["extensions"].get("hooks", {}).items()}
        hooks.setdefault("on_day_start", []).append("tests.test_multiplayer:_play_agent4_on_day1")
        hooks.setdefault("on_agent_post_step", []).append("tests.test_multiplayer:_capture_actions")
        CONFIG["extensions"]["hooks"] = hooks
        for key in (
            "news",
            "intervention",
            "external_environment_service",
            "distributed",
            "visualization",
            "life_events",
        ):
            if isinstance(CONFIG.get(key), dict):
                CONFIG[key] = {**CONFIG[key], "enabled": False}
        if isinstance(CONFIG.get("news"), dict):
            CONFIG["news"]["info_seek"] = {**CONFIG["news"].get("info_seek", {}), "enabled": False}
        if isinstance(CONFIG.get("external_rag"), dict):
            CONFIG["external_rag"] = {
                **CONFIG["external_rag"],
                "bootstrap": {**CONFIG["external_rag"].get("bootstrap", {}), "enabled": False},
            }
        for name, value in (
            ("AGENT_IDS", [4, 5]),
            ("SIM_DAYS", 1),
            ("STATEFUL", False),
            ("SIMULATE_REALTIME", False),
            ("SECONDS_PER_DAY", 1),
            ("NEWS_ENABLED", False),
            ("INTERVENTION_ENABLED", False),
            ("HUMAN_REALISM_ENABLED", False),
            ("VISUALIZATION_ENABLED", False),
            ("LIFE_EVENTS_ENABLED", False),
        ):
            patcher = mock.patch.object(sim, name, value, create=True)
            patcher.start()
            self.addCleanup(patcher.stop)

        with install() as llm:
            sim.run_simulation()

        def perceptions(agent_id):
            return [
                c["prompt"]
                for c in llm.calls
                if c.get("agent_id") == agent_id and c.get("task") == "perception"
            ]

        self.assertTrue(
            any(f"【你此刻的决定】{INTENT}" in p for p in perceptions(4)), "intent never reached #4"
        )
        self.assertFalse(any(INTENT in p for p in perceptions(5)))
        self.assertEqual([a for aid, a in _SEEN["actions"] if aid == 4].count(INTENT), 1)  # exactly one step
        self.assertNotIn(INTENT, [a for aid, a in _SEEN["actions"] if aid == 5])
        self.assertEqual(_rows(os.path.join(tmp.name, "multiplayer.act.jsonl"))[0]["text"], INTENT)


if __name__ == "__main__":
    unittest.main()
