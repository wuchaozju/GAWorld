"""Distributed worlds (proposal 2026-10-02-distributed-worlds).

* Node tokens: issued once, stored as a hash, scoped to one world; residents
  belong to at most one node; the hub's own token is minted per run.
* Hub state: tick sync waits only for live participants that are behind; a
  node cannot write the hub's own record tables; the world package carries the
  residents and the city but no model section or paths.
* The sync plugin waits, gives up after the timeout, never blocks on a dead hub.
* HTTP: the owner manages nodes; a node token reaches only its world's node
  endpoints and relay; the hub run gets its share of the residents; players'
  actions are routed to the machine running the resident, including speech
  between machines; nodes' records join the world's stream; ``/play/<id>``.
* The node process against a real dashboard: downloads the package, starts its
  share with the right config, forwards actions and records, stops with the
  hub, and gives up on a revoked token.
"""

from __future__ import annotations

import http.client
import io
import json
import os
import sys
import tempfile
import threading
import time
import unittest
import zipfile
from http.server import ThreadingHTTPServer
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import requests

from gaworld import worlds
from gaworld.accounts import AccountStore, policy
from gaworld.apps import cluster_api, play_api, runs, world_paths
from gaworld.apps import dashboard_server as ds
from gaworld.cluster import bundle, hub, nodes
from gaworld.cluster import plugin as cluster_plugin
from gaworld.cluster.node import NodeRunner, Revoked
from gaworld.kernel import build_kernel, remote
from gaworld.multiplayer import plugin as mp
from gaworld.plugins import builtin_plugins

PASSWORD = "correct horse"


def _rows(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


class NodesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.world = "w0000abcd"

    def tearDown(self):
        self.tmp.cleanup()

    def test_tokens_and_assignments(self):
        node, token = nodes.add(self.root, self.world, " 机房 7 号 ", [3, 2], {1, 2, 3, 4})
        self.assertEqual((node["id"], node["name"], node["agent_ids"]), ("n1", "机房 7 号", [2, 3]))
        self.assertNotIn("token_hash", node)
        self.assertTrue(token.startswith(f"{self.world}.n1."))
        stored = json.dumps(nodes.load(self.root, self.world))
        self.assertNotIn(token.split(".", 2)[2], stored)  # only a hash on disk

        self.assertEqual(nodes.authenticate(self.root, token)[1]["id"], "n1")
        self.assertIsNone(nodes.authenticate(self.root, token + "x"))
        self.assertIsNone(nodes.authenticate(self.root, "w0000ffff" + token[9:]))  # another world
        self.assertIsNone(nodes.authenticate(self.root, "garbage"))

        with self.assertRaises(ValueError):  # #3 is taken
            nodes.add(self.root, self.world, "B", [3, 4], {1, 2, 3, 4})
        with self.assertRaises(LookupError):
            nodes.add(self.root, self.world, "B", [9], {1, 2, 3, 4})
        with self.assertRaises(ValueError):
            nodes.add(self.root, self.world, "", [4], {1, 2, 3, 4})
        second, _ = nodes.add(self.root, self.world, "B", [4], {1, 2, 3, 4})
        self.assertEqual(nodes.assigned(self.root, self.world), {2: "n1", 3: "n1", 4: "n2"})
        nodes.set_agents(self.root, self.world, "n1", [1], {1, 2, 3, 4})
        self.assertEqual(nodes.assigned(self.root, self.world), {1: "n1", 4: "n2"})

        nodes.remove(self.root, self.world, "n1")
        self.assertIsNone(nodes.authenticate(self.root, token))
        self.assertEqual(second["id"], "n2")

    def test_the_hub_token_lasts_one_run(self):
        first = nodes.hub_token(self.world)
        self.assertEqual(nodes.authenticate(self.root, first)[1]["id"], nodes.HUB)
        nodes.hub_token(self.world)
        self.assertIsNone(nodes.authenticate(self.root, first))


class HubTest(unittest.TestCase):
    def setUp(self):
        hub.reset()
        self.hub = hub.get("w0000abcd")
        self.hub.start_run("r1", {"hub": [1], "n1": [2], "n2": [3]})

    def _running(self, node_id, run_id="r1"):
        self.hub.heartbeat(node_id, {"state": "running", "run_id": run_id})

    def test_sync_waits_for_live_participants_behind(self):
        self._running("n1")
        self._running("n2")
        # Nobody else has reported yet: n1 waits for the hub and n2.
        self.assertEqual(self.hub.sync("n1", "r1", 1, "08:00", True)["waiting_for"], ["hub", "n2"])
        self.hub.sync("hub", "r1", 1, "08:00", True)
        self.assertEqual(self.hub.sync("n1", "r1", 1, "08:00", True)["waiting_for"], ["n2"])
        self.assertTrue(self.hub.sync("n2", "r1", 1, "08:30", True)["go"] is False)  # others are behind
        self.assertTrue(self.hub.sync("n1", "r1", 1, "08:00", True)["go"])
        # A node that stopped sending heartbeats is not waited for.
        self.hub.status["n2"]["seen"] -= hub.LIVE_SECONDS + 1
        self.assertTrue(self.hub.sync("hub", "r1", 1, "09:00", True)["go"] is False)  # n1 at 08:00
        self.hub.sync("n1", "r1", 2, "00:00", True)
        self.assertTrue(self.hub.sync("hub", "r1", 1, "09:00", True)["go"])
        # A dead hub run is not waited for either, and a stale run never waits.
        self.assertTrue(self.hub.sync("n1", "r1", 3, "00:00", False)["go"])
        self.assertTrue(self.hub.sync("n1", "old", 9, "00:00", True)["stale"])

    def test_records_are_tagged_and_hub_tables_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            written = self.hub.append_records(
                tmp,
                "n1",
                {
                    "multiplayer.act": [{"agent_id": 2, "_node": "hub"}, "not a row"],
                    "multiplayer.presence": [{"event": "claim"}],
                    "../../escape": [{"x": 1}],
                },
            )
            self.assertEqual(written, 2)
            self.assertEqual(_rows(os.path.join(tmp, "multiplayer.act.jsonl")), [{"agent_id": 2, "_node": "n1"}])
            self.assertFalse(os.path.exists(os.path.join(tmp, "multiplayer.presence.jsonl")))
            self.assertEqual(sorted(os.listdir(tmp)), ["escape.jsonl", "multiplayer.act.jsonl"])

    def test_outbox_is_taken_once_and_a_new_run_clears_it(self):
        self.hub.push("n1", "player_act", {"agent_id": 2, "text": "x"})
        self.assertEqual([item["name"] for item in self.hub.take("n1")], ["player_act"])
        self.assertEqual(self.hub.take("n1"), [])
        self.hub.push("n1", "player_act", {"agent_id": 2, "text": "x"})
        self.hub.start_run("r2")
        self.assertEqual(self.hub.take("n1"), [])


class BundleTest(unittest.TestCase):
    def test_package_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            csv, md = os.path.join(tmp, "a.csv"), os.path.join(tmp, "a.md")
            for path in (csv, md):
                with open(path, "w", encoding="utf-8") as f:
                    f.write("x")
            city = os.path.join(tmp, "city")
            os.makedirs(city)
            with open(os.path.join(city, "city.json"), "w", encoding="utf-8") as f:
                f.write("{}")
            with open(os.path.join(city, ".secret"), "w", encoding="utf-8") as f:
                f.write("no")
            settings = bundle.settings_for_node(
                [
                    {"llm": {"provider": "x"}, "sim_days": 3, "city": "a", "map_path": "m"},
                    {"sim_days": 5, "multiplayer": {"wait_for_players_seconds": 10}},
                ]
            )
            self.assertEqual(settings, {"sim_days": 5, "multiplayer": {"wait_for_players_seconds": 10}})
            data = bundle.build(settings, csv, md, city)
            self.assertNotIn("city/.secret", zipfile.ZipFile(io.BytesIO(data)).namelist())
            package = bundle.extract(data, os.path.join(tmp, "out"))
            self.assertEqual(package["settings"]["sim_days"], 5)
            self.assertTrue(os.path.isfile(package["seed_csv"]))
            self.assertTrue(package["city_dir"].endswith("city"))

            evil = io.BytesIO()
            with zipfile.ZipFile(evil, "w") as archive:
                archive.writestr("../escape.txt", "x")
            with self.assertRaises(ValueError):
                bundle.extract(evil.getvalue(), os.path.join(tmp, "out2"))


class SyncPluginTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ctx = build_kernel(
            {
                "records": {"output_dir": self.tmp.name},
                "kernel": {"interventions_path": os.path.join(self.tmp.name, "queue.json")},
                "cluster": {
                    "enabled": True,
                    "hub_url": "http://hub",
                    "token": "t",
                    "run_id": "r1",
                    "sync_timeout_seconds": 0.3,
                },
            },
            load_entry_points=False,
        )
        self.plugin = cluster_plugin.ClusterSyncPlugin()
        self.plugin.setup(self.ctx)

    def tearDown(self):
        self.tmp.cleanup()

    def _tick(self):
        started = time.time()
        self.ctx.bus.emit("on_time_tick", sim=self.ctx, day=1, time_str="08:00")
        return time.time() - started

    def test_registered_after_multiplayer(self):
        ids = [p.id for p in builtin_plugins()]
        self.assertGreater(ids.index("cluster"), ids.index("multiplayer"))

    def test_waits_then_gives_up(self):
        answers = iter([{"go": False, "waiting_for": ["n2"]}, {"go": True}])
        with (
            mock.patch.object(cluster_plugin, "POLL_SECONDS", 0.05),
            mock.patch.object(self.plugin, "_post", side_effect=lambda *a: next(answers)) as post,
        ):
            self.assertLess(self._tick(), 0.3)
            self.assertEqual(post.call_count, 2)
        with (
            mock.patch.object(cluster_plugin, "POLL_SECONDS", 0.05),
            mock.patch.object(self.plugin, "_post", return_value={"go": False, "waiting_for": ["n2"]}),
        ):
            self.assertGreaterEqual(self._tick(), 0.3)
        timeouts = _rows(os.path.join(self.tmp.name, "cluster.sync_timeout.jsonl"))
        self.assertEqual(timeouts[0]["waiting_for"], ["n2"])

    def test_an_unreachable_hub_never_blocks(self):
        with mock.patch.object(self.plugin, "_post", side_effect=requests.ConnectionError("down")):
            self.assertLess(self._tick(), 0.1)
        self.assertEqual(len(_rows(os.path.join(self.tmp.name, "cluster.sync_error.jsonl"))), 1)

    def test_inactive_outside_a_distributed_world(self):
        self.ctx.config["cluster"] = {}
        with mock.patch.object(self.plugin, "_post") as post:
            self._tick()
        post.assert_not_called()


class RemoteSpeechTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ctx = build_kernel({"records": {"output_dir": self.tmp.name}}, load_entry_points=False)
        self.agents = [{"id": 1, "name": "甲"}]
        self.ctx.set_agents(self.agents)
        mp.MultiplayerPlugin().setup(self.ctx)

    def tearDown(self):
        self.tmp.cleanup()

    def test_speech_between_machines(self):
        do = self.ctx.controller.intervene
        do("player_claim", self.ctx, agent_id=1, player="小王", until=time.time() + 60)
        with self.assertRaises(ValueError):  # unknown target and no name: refused as before
            do("player_say", self.ctx, agent_id=1, target_id=7, text="你好")
        do("player_say", self.ctx, agent_id=1, target_id=7, text="你好", target_name="丁")
        sections = self.ctx.bus.collect("perception.sections", agent=self.agents[0], sim=self.ctx)
        self.assertTrue(any("你对丁说了：「你好」" in line for line in sections))
        say = _rows(os.path.join(self.tmp.name, "multiplayer.say.jsonl"))[0]
        self.assertEqual((say["target_id"], say["target_name"]), (7, "丁"))
        # The other direction: a played resident elsewhere spoke to ours.
        do("player_hear", self.ctx, agent_id=1, speaker_id=7, speaker_name="丁", text="回头见")
        sections = self.ctx.bus.collect("perception.sections", agent=self.agents[0], sim=self.ctx)
        self.assertTrue(any("丁对你说：「回头见」" in line for line in sections))


class _Server(unittest.TestCase):
    """A dashboard with accounts and a world of four residents."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = self.tmp.name
        os.makedirs(os.path.join(root, "seed"))
        self.csv, self.md = os.path.join(root, "seed", "a.csv"), os.path.join(root, "seed", "a.md")
        names = ["甲", "乙", "丙", "丁"]
        with open(self.csv, "w", encoding="utf-8") as f:
            f.write("id,name\n" + "".join(f"{i},{n}\n" for i, n in enumerate(names, 1)))
        with open(self.md, "w", encoding="utf-8") as f:
            f.write("".join(f"## Profile {i} | {n}\n居民。\n\n" for i, n in enumerate(names, 1)))
        db = os.path.join(root, "accounts.sqlite")
        self.store = AccountStore(db)
        self.store.init_schema()
        self.store.create_user("小王", PASSWORD)
        self.store.create_user("小李", PASSWORD)
        self.patches = [
            mock.patch.dict(os.environ, {"GAWORLD_ACCOUNTS_DB": db}),
            mock.patch.object(world_paths, "REPO_ROOT", root),
            mock.patch.object(world_paths, "DASHBOARD_CONFIG_PATH", os.path.join(root, "dashboard_config.json")),
            mock.patch.object(ds, "_city_seed_files", return_value=("", self.csv, self.md)),
        ]
        for patch in self.patches:
            patch.start()
        os.environ.pop("GAWORLD_DASHBOARD_TOKEN", None)
        play_api.reset()
        hub.reset()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), ds.DashboardHandler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.port = self.server.server_address[1]
        self.url = f"http://127.0.0.1:{self.port}"

        self.wang, self.li = self._login("小王"), self._login("小李")
        resp, body = self._req("POST", "/api/worlds/create", {"name": "分布城"}, [self.wang])
        self.world_id, self.in_world = body["world"]["id"], self._cookie(resp)
        self._req("POST", "/api/config", {"agent_ids": [1, 2, 3, 4]}, [self.wang, self.in_world])
        self._req("POST", f"/api/worlds/{self.world_id}/visibility", {"visibility": "open"}, [self.wang])

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        with runs._RUNS_LOCK:
            runs.WORLD_RUNS.clear()
        play_api.reset()
        hub.reset()
        for patch in reversed(self.patches):
            patch.stop()
        self.tmp.cleanup()

    def _req(self, method, path, body=None, cookies=(), token=None, raw=False):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        headers = {"Cookie": "; ".join(cookies), "Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        conn.request(method, path, body=json.dumps(body) if body is not None else None, headers=headers)
        resp = conn.getresponse()
        data = resp.read()
        conn.close()
        if raw:
            return resp, data
        return resp, json.loads(data) if data else None

    def _cookie(self, resp):
        return resp.getheader("Set-Cookie").split(";", 1)[0]

    def _login(self, nickname):
        return self._cookie(
            self._req("POST", "/api/auth/login", {"nickname": nickname, "password": PASSWORD})[0]
        )

    def _add_node(self, agent_ids, name="7 号机"):
        resp, body = self._req(
            "POST", "/api/cluster/nodes", {"name": name, "agent_ids": agent_ids}, [self.wang, self.in_world]
        )
        self.assertEqual(resp.status, 200, body)
        return body["node"], body["token"]

    def _fake_hub_run(self):
        """Pretend the hub run started: a live process, a run id, a live local queue."""
        proc = mock.Mock()
        proc.poll.return_value = None
        with runs._RUNS_LOCK:
            runs.WORLD_RUNS[self.world_id] = {"process": proc, "run_id": "r1", "log_path": ""}
        world_hub = hub.get(self.world_id)
        token = ds._WORLD.set(self.store.get_world(self.world_id))
        try:
            plan = cluster_api.placement(self.world_id)
        finally:
            ds._WORLD.reset(token)
        world_hub.start_run("r1", plan)
        queue = os.path.join(self.tmp.name, worlds.root(self.world_id), "kernel", "interventions.json")
        os.makedirs(os.path.dirname(queue), exist_ok=True)
        names = ["player_act", "player_claim", "player_release", "player_say", "player_hear"]
        with open(queue, "w", encoding="utf-8") as f:
            json.dump({"active": True, "pid": os.getpid(), "registered": names, "pending": []}, f)
        return queue


class ClusterHttpTest(_Server):
    def test_policy(self):
        self.assertEqual(policy.required("POST", "/api/cluster/nodes"), "member")
        self.assertEqual(policy.required("POST", "/api/cluster/nodes/n1/delete"), "member")
        self.assertTrue(cluster_api.is_node_path("/api/cluster/node/sync"))
        self.assertFalse(cluster_api.is_node_path("/api/cluster/nodes"))

    def test_owner_manages_nodes(self):
        # Another member, even inside the open world, cannot see or add nodes.
        self.assertEqual(self._req("GET", "/api/cluster", cookies=[self.li, self.in_world])[0].status, 403)
        resp, _ = self._req(
            "POST", "/api/cluster/nodes", {"name": "x", "agent_ids": [2]}, [self.li, self.in_world]
        )
        self.assertEqual(resp.status, 403)

        node, token = self._add_node("2-3")
        self.assertEqual(node["agent_ids"], [2, 3])
        view = self._req("GET", "/api/cluster", cookies=[self.wang, self.in_world])[1]
        self.assertEqual(view["hub"]["agent_ids"], [1, 4])
        self.assertEqual(view["nodes"][0]["running_agent_ids"], [2, 3])
        self.assertFalse(view["nodes"][0]["online"])
        self.assertNotIn(token.split(".", 2)[2], json.dumps(view))

        resp, body = self._req(
            "POST", "/api/cluster/nodes/n1/agents", {"agent_ids": [2]}, [self.wang, self.in_world]
        )
        self.assertEqual(body["node"]["agent_ids"], [2])
        self._req("POST", "/api/cluster/nodes/n1/delete", {}, [self.wang, self.in_world])
        self.assertEqual(self._req("GET", "/api/cluster/node", token=token)[0].status, 401)

    def test_a_node_token_reaches_only_its_world(self):
        _, token = self._add_node([2, 3])
        resp, me = self._req("GET", "/api/cluster/node", token=token)
        self.assertEqual((resp.status, me["agent_ids"], me["running"]), (200, [2, 3], False))
        self.assertEqual(self._req("GET", "/api/cluster/node", token=token + "x")[0].status, 401)
        # Not a session: nothing else in the console answers it.
        self.assertEqual(self._req("GET", "/api/worlds", token=token)[0].status, 401)
        self.assertEqual(self._req("GET", "/api/cluster", token=token)[0].status, 401)

        resp, data = self._req("GET", "/api/cluster/node/bundle", token=token, raw=True)
        archive = zipfile.ZipFile(io.BytesIO(data))
        self.assertIn("seed/profiles.md", archive.namelist())
        settings = json.loads(archive.read("settings.json"))
        self.assertEqual(settings["agent_ids"], [1, 2, 3, 4])
        self.assertNotIn("llm", settings)

    def test_relay_is_scoped_to_the_nodes_residents(self):
        _, token = self._add_node([2, 3])
        self._fake_hub_run()
        resp, body = self._req(
            "POST",
            "/api/cluster/relay/register",
            {"cluster": "other", "node_id": "spoof", "agents": [{"id": 2, "name": "乙"}, {"id": 1, "name": "甲"}]},
            token=token,
        )
        self.assertEqual([(a["agent_id"], a["node_id"]) for a in body["directory"]], [(2, "n1")])
        message = {"from_agent": 1, "to_agent": 4, "text": "冒充"}
        resp, _ = self._req("POST", "/api/cluster/relay/message/send", {"message": message}, token=token)
        self.assertEqual(resp.status, 403)
        message["from_agent"] = 2
        self.assertEqual(
            self._req("POST", "/api/cluster/relay/message/send", {"message": message}, token=token)[0].status, 200
        )
        hub_token = nodes.hub_token(self.world_id)
        polled = self._req(
            "POST", "/api/cluster/relay/message/poll", {"recipient_ids": [4, 2], "since": {}}, token=hub_token
        )[1]
        self.assertEqual([(m["from_agent"], m["to_agent"]) for m in polled["messages"]], [(2, 4)])

    def test_the_hub_run_gets_its_share(self):
        world = self.store.get_world(self.world_id)
        token = ds._WORLD.set(world)
        try:
            self.assertNotIn("cluster", json.loads(runs.simulation_env()["GAWORLD_CONFIG_OVERRIDES"]))
            self._add_node([2, 3])
            patch = json.loads(runs.simulation_env()["GAWORLD_CONFIG_OVERRIDES"])
            self.assertEqual(patch["distributed"]["local_agent_ids"], [1, 4])
            self.assertEqual(patch["distributed"]["relay"]["base_url"], f"{self.url}/api/cluster/relay")
            self.assertEqual(patch["cluster"]["sync_timeout_seconds"], 60)
            run_id = patch["cluster"]["run_id"]
            self.assertEqual(hub.get(self.world_id).run_id, run_id)
            self.assertEqual(nodes.authenticate(self.tmp.name, patch["cluster"]["token"])[1]["id"], "hub")
            self._add_node([1, 4], name="另一台")
            with self.assertRaises(ValueError):  # nothing left for the hub
                runs.simulation_env()
        finally:
            ds._WORLD.reset(token)

    def test_actions_are_routed_to_the_residents_machine(self):
        _, token = self._add_node([2, 3])
        queue = self._fake_hub_run()
        with mock.patch.object(play_api, "_running", return_value=True):
            # The node is not up yet: an action for its resident cannot be delivered.
            self._req("POST", "/api/play/claim", {"agent_id": 2}, [self.li, self.in_world])
            resp, _ = self._req("POST", "/api/play/act", {"text": "去河边"}, [self.li, self.in_world])
            self.assertEqual(resp.status, 409)

            self._req("POST", "/api/cluster/node/heartbeat", {"state": "running", "run_id": "r1"}, token=token)
            self._req("POST", "/api/play/claim", {"agent_id": 2}, [self.li, self.in_world])
            self.assertEqual(
                self._req("POST", "/api/play/act", {"text": "去河边"}, [self.li, self.in_world])[0].status, 200
            )
            # 乙 (node) speaks to 丙 (same node), then to 甲 (the hub).
            self._req("POST", "/api/play/say", {"target_id": 3, "text": "同机"}, [self.li, self.in_world])
            self._req("POST", "/api/play/say", {"target_id": 1, "text": "跨机"}, [self.li, self.in_world])
            # 甲 is played on the hub and answers 乙 on the node.
            self._req("POST", "/api/play/claim", {"agent_id": 1}, [self.wang, self.in_world])
            self._req("POST", "/api/play/say", {"target_id": 2, "text": "收到"}, [self.wang, self.in_world])

        items = self._req("GET", "/api/cluster/node/interventions", token=token)[1]["items"]
        self.assertEqual(
            [(i["name"], i["kwargs"].get("text")) for i in items],
            [
                ("player_claim", None),
                ("player_act", "去河边"),
                ("player_say", "同机"),
                ("player_say", "跨机"),
                ("player_hear", "收到"),
            ],
        )
        self.assertEqual(items[3]["kwargs"]["target_name"], "甲")
        self.assertEqual(items[4]["kwargs"]["speaker_name"], "甲")
        self.assertEqual(self._req("GET", "/api/cluster/node/interventions", token=token)[1]["items"], [])
        with open(queue, encoding="utf-8") as handle:
            local = [(p["name"], p["kwargs"].get("text")) for p in json.load(handle)["pending"]]
        self.assertEqual(local, [("player_hear", "跨机"), ("player_claim", None), ("player_say", "收到")])

    def test_node_records_join_the_world_stream_and_sync(self):
        _, token = self._add_node([2, 3])
        self._fake_hub_run()
        self._req("POST", "/api/cluster/node/heartbeat", {"state": "running", "run_id": "r1"}, token=token)
        rows = {"multiplayer.act": [{"agent_id": 2, "text": "去河边"}], "multiplayer.presence": [{"x": 1}]}
        body = self._req("POST", "/api/cluster/node/records", {"tables": rows}, token=token)[1]
        self.assertEqual(body["written"], 1)
        records = os.path.join(self.tmp.name, worlds.root(self.world_id), "records")
        self.assertEqual(_rows(os.path.join(records, "multiplayer.act.jsonl"))[0]["_node"], "n1")
        self.assertFalse(os.path.exists(os.path.join(records, "multiplayer.presence.jsonl")))

        answer = self._req("POST", "/api/cluster/node/sync", {"run_id": "r1", "day": 1, "time": "08:00"}, token=token)
        self.assertEqual(answer[1]["waiting_for"], ["hub"])
        view = self._req("GET", "/api/cluster", cookies=[self.wang, self.in_world])[1]
        self.assertEqual((view["nodes"][0]["online"], view["nodes"][0]["sim_time"]), (True, "08:00"))
        big = {"t": [{"x": "y" * (cluster_api.MAX_BODY + 10)}]}
        self.assertEqual(self._req("POST", "/api/cluster/node/records", {"tables": big}, token=token)[0].status, 413)

    def test_play_link_enters_the_world(self):
        resp, _ = self._req("GET", f"/play/{self.world_id}", cookies=[self.li], raw=True)
        self.assertEqual((resp.status, resp.getheader("Location")), (303, "/site/dashboard/play.html"))
        self.assertIn(f"gaworld_world={self.world_id}", resp.getheader("Set-Cookie"))
        resp, _ = self._req("GET", f"/play/{self.world_id}", raw=True)  # signed out: log in first
        self.assertIn("/login?next=", resp.getheader("Location"))
        self._req("POST", f"/api/worlds/{self.world_id}/visibility", {"visibility": "private"}, [self.wang])
        resp, _ = self._req("GET", f"/play/{self.world_id}", cookies=[self.li], raw=True)
        self.assertEqual(resp.status, 404)


class NodeRunnerTest(_Server):
    """The node process against the real dashboard, with the simulator stubbed."""

    def _runner(self, token):
        runner = NodeRunner(self.url, token, repo_root=self.tmp.name, log=lambda *_: None)
        self.launched = []

        def launch(env):
            self.launched.append(json.loads(env["GAWORLD_CONFIG_OVERRIDES"]))
            # The "simulator" publishes its queue the way remote.publish does.
            os.makedirs(os.path.dirname(runner.queue_path), exist_ok=True)
            with open(runner.queue_path, "w", encoding="utf-8") as f:
                json.dump({"active": True, "pid": os.getpid(), "registered": ["player_act", "player_claim"], "pending": []}, f)
            proc = mock.Mock()
            proc.poll.return_value = None
            return proc

        runner.launch = launch
        return runner

    def test_a_node_follows_the_hub(self):
        _, token = self._add_node([2, 3])
        runner = self._runner(token)
        runner.step()  # the world is not running: nothing to do
        self.assertEqual((runner.state, self.launched), ("idle", []))

        self._fake_hub_run()
        runner.ticks = 0
        runner.step()
        self.assertEqual(runner.state, "running")
        patch = self.launched[0]
        self.assertEqual(patch["distributed"]["local_agent_ids"], [2, 3])
        self.assertEqual(patch["agent_ids"], [2, 3])
        self.assertEqual(patch["cluster"]["run_id"], "r1")
        self.assertEqual(patch["records"]["output_dir"], f"output/nodes/{self.world_id}/run/records")
        self.assertTrue(os.path.isfile(patch["md_path"]))
        self.assertEqual(patch["city"], "")

        # A player's action reaches the local queue; local records reach the hub.
        with mock.patch.object(play_api, "_running", return_value=True):
            self._req("POST", "/api/play/claim", {"agent_id": 2}, [self.li, self.in_world])
            self._req("POST", "/api/play/act", {"text": "去河边"}, [self.li, self.in_world])
        os.makedirs(runner.records_dir, exist_ok=True)
        with open(os.path.join(runner.records_dir, "multiplayer.act.jsonl"), "w", encoding="utf-8") as f:
            f.write(json.dumps({"agent_id": 2, "text": "去河边"}) + "\n" + '{"half')
        runner.step()
        pending = remote.read(runner.queue_path)["pending"]
        self.assertEqual(pending[-1]["kwargs"]["text"], "去河边")
        records = os.path.join(self.tmp.name, worlds.root(self.world_id), "records", "multiplayer.act.jsonl")
        self.assertEqual([r["_node"] for r in _rows(records)], ["n1"])
        runner.step()  # the half line is not sent twice nor half
        self.assertEqual(len(_rows(records)), 1)

        # The hub stops: so does the node.
        with runs._RUNS_LOCK:
            runs.WORLD_RUNS[self.world_id]["process"].poll.return_value = 0
        runner.ticks = 0
        runner.step()
        self.assertEqual((runner.state, runner.run_id), ("idle", ""))

        self._req("POST", "/api/cluster/nodes/n1/delete", {}, [self.wang, self.in_world])
        runner.ticks = 0
        with self.assertRaises(Revoked):
            runner.step()


if __name__ == "__main__":
    unittest.main()


class FullSimTest(_Server):
    """The hub's share of a world inside the real main loop, with a scripted model.

    The relay client registers through the dashboard with its token, a message
    from a resident on another machine reaches the perception of ours, our
    residents write back across, and every tick reports to the sync table --
    giving up on a node that never arrives.
    """

    def test_hub_share_runs_against_the_dashboard(self):
        import generative_city_sim as sim
        from gaworld.settings import CONFIG
        from tests.fixtures import scratch_cwd
        from tests.fixtures.mock_llm import install

        scratch_cwd.enter(self)  # keep the run's output/ out of the repo

        _, node_token = self._add_node([2, 3])
        self._fake_hub_run()
        world_hub = hub.get(self.world_id)
        hub_token = nodes.hub_token(self.world_id)
        # The node is up and one of its residents has something to say to #1.
        self._req("POST", "/api/cluster/node/heartbeat", {"state": "running", "run_id": "r1"}, token=node_token)
        self._req("POST", "/api/cluster/relay/register", {"agents": [{"id": 2, "name": "周婉清"}]}, token=node_token)
        line = {"from_agent": 2, "from_name": "周婉清", "to_agent": 1, "text": "今晚运河边见", "day": 1}
        self._req("POST", "/api/cluster/relay/message/send", {"message": line}, token=node_token)

        distributed = {
            "enabled": True,
            "cluster": self.world_id,
            "node_id": "hub",
            "local_agent_ids": [1, 4],
            "send_probability": 1.0,
            "relay": {"base_url": f"{self.url}/api/cluster/relay", "token": hub_token},
        }
        records = os.path.join(self.tmp.name, "records")
        touched = (
            "agent_ids", "sim_days", "stateful", "simulate_realtime", "seconds_per_day", "news",
            "intervention", "extensions", "external_environment_service", "distributed", "visualization",
            "life_events", "external_rag", "records", "cluster",
        )  # fmt: skip
        originals = {key: CONFIG[key] for key in touched if key in CONFIG}

        def restore():
            # Keys this test added must go too: a leftover `records` points every
            # later run's Recorder at this test's (deleted) temp directory.
            for key in touched:
                if key in originals:
                    CONFIG[key] = originals[key]
                else:
                    CONFIG.pop(key, None)

        self.addCleanup(restore)
        CONFIG.update(agent_ids=[1, 4], sim_days=1, stateful=False, simulate_realtime=False, seconds_per_day=1)
        CONFIG["records"] = {"output_dir": records}
        CONFIG["distributed"] = distributed
        CONFIG["cluster"] = {
            "enabled": True,
            "hub_url": self.url,
            "token": hub_token,
            "run_id": "r1",
            "sync_timeout_seconds": 0.05,
        }
        for key in ("news", "intervention", "external_environment_service", "visualization", "life_events"):
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
            ("AGENT_IDS", [1, 4]),
            ("DISTRIBUTED_CONFIG", distributed),
            ("DISTRIBUTED_ENABLED", True),
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

        directory = {a["agent_id"]: a["node_id"] for a in world_hub.relay.get_directory(self.world_id)["agents"]}
        self.assertEqual(directory, {1: "hub", 2: "n1", 4: "hub"})
        prompts = [c["prompt"] for c in llm.calls if c.get("agent_id") == 1]
        self.assertTrue(any("今晚运河边见" in p for p in prompts), "the remote message never reached #1")
        sent = [m for m in world_hub.relay.messages if m["node_id"] == "hub"]
        self.assertTrue(sent and all(m["to_agent"] == 2 for m in sent))
        self.assertEqual(world_hub.progress["hub"][0], 1)  # the hub reported its ticks
        timeouts = _rows(os.path.join(records, "cluster.sync_timeout.jsonl"))
        self.assertTrue(timeouts and timeouts[0]["waiting_for"] == ["n1"])
