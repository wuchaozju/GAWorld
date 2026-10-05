"""Teacher console (proposal 2026-10-01-multi-user, P5).

The page (``site/dashboard/admin.html``) is a client of these endpoints; what
is tested is the server side it relies on:

* invites can be revoked while unused; used ones stay as the record;
* the roster carries usage and a last-seen time (the "online" dot);
* the world list carries queue position and today's calls; owners and admins
  can stop a world's run;
* a broadcast puts one immediate, everyone-event into each chosen world's own
  life-event queue (the shared world included) -- admins only;
* a world's play log exports as Markdown, for those who may see the world.
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
from gaworld.accounts import AccountError, AccountStore, policy, usage
from gaworld.apps import dashboard_server as ds
from gaworld.apps import runs, world_paths

PASSWORD = "correct horse"


class StoreTest(unittest.TestCase):
    def test_only_unused_invites_can_be_revoked(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = AccountStore(os.path.join(tmp, "a.sqlite"))
            store.init_schema()
            used, unused = store.create_invites(2)
            store.register(used, "小王", PASSWORD)
            rows = {row["used_by"]: row["id"] for row in store.list_invites()}
            self.assertFalse(store.revoke_invite(rows["小王"]))
            self.assertTrue(store.revoke_invite(rows[None]))
            self.assertEqual([row["used_by"] for row in store.list_invites()], ["小王"])
            with self.assertRaises(AccountError):
                store.register(unused, "小李", PASSWORD)

    def test_policy(self):
        self.assertEqual(policy.required("POST", "/api/worlds/broadcast"), "admin")
        self.assertEqual(
            policy.required("POST", "/api/worlds/w0123abcd/stop"), "member"
        )  # owner checked in handler


class ConsoleHttpTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = self.tmp.name
        os.makedirs(os.path.join(root, "seed"))
        self.csv, self.md = os.path.join(root, "seed", "a.csv"), os.path.join(root, "seed", "a.md")
        with open(self.csv, "w", encoding="utf-8") as f:
            f.write("id,name\n1,甲\n")
        with open(self.md, "w", encoding="utf-8") as f:
            f.write("## Profile 1 | 甲\n一位居民。\n")
        db = os.path.join(root, "accounts.sqlite")
        self.store = AccountStore(db)
        self.store.init_schema()
        self.store.create_user("老师", PASSWORD, role="admin")
        self.store.create_user("小王", PASSWORD)
        self.store.create_user("小李", PASSWORD)
        self.patches = [
            mock.patch.dict(os.environ, {"GAWORLD_ACCOUNTS_DB": db}),
            mock.patch.object(world_paths, "REPO_ROOT", root),
            mock.patch.object(world_paths, "DASHBOARD_CONFIG_PATH", os.path.join(root, "dashboard_config.json")),
            mock.patch.object(ds, "_city_seed_files", return_value=("", self.csv, self.md)),
            mock.patch.object(runs, "WORLD_RUNS", {}),
            mock.patch.object(runs, "RUN_QUEUE", []),
            mock.patch.object(usage, "TALLY", usage.Tally()),
        ]
        for patch in self.patches:
            patch.start()
        os.environ.pop("GAWORLD_DASHBOARD_TOKEN", None)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), ds.DashboardHandler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.port = self.server.server_address[1]
        self.teacher, self.wang, self.li = (self._login(n) for n in ("老师", "小王", "小李"))
        _, body = self._req("POST", "/api/worlds/create", {"name": "小王的城"}, [self.wang])
        self.world_id = body["world"]["id"]
        self.root = os.path.join(root, worlds.root(self.world_id))

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
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

    def _login(self, nickname):
        resp, _ = self._req("POST", "/api/auth/login", {"nickname": nickname, "password": PASSWORD})
        return resp.getheader("Set-Cookie").split(";", 1)[0]

    def test_invites_and_roster(self):
        codes = self._req("POST", "/api/auth/invites", {"count": 1}, [self.teacher])[1]["codes"]
        invite = self._req("GET", "/api/auth/invites", cookies=[self.teacher])[1]["invites"][0]
        self.assertEqual(
            self._req("POST", f"/api/auth/invites/{invite['id']}/revoke", {}, [self.wang])[0].status, 403
        )
        self.assertTrue(
            self._req("POST", f"/api/auth/invites/{invite['id']}/revoke", {}, [self.teacher])[1]["revoked"]
        )
        self.assertEqual(
            self._req(
                "POST", "/api/auth/register", {"code": codes[0], "nickname": "新同学", "password": PASSWORD}
            )[0].status,
            400,
        )
        rows = {
            r["nickname"]: r for r in self._req("GET", "/api/auth/usage", cookies=[self.teacher])[1]["users"]
        }
        self.assertGreater(rows["小王"]["last_seen"], time.time() - 60)  # seen when creating the world
        self.assertEqual((rows["小王"]["today"], rows["小王"]["total"]), (0, 0))

    def test_world_list_and_stop(self):
        class Running:
            code = None

            def poll(self):
                return self.code

            def terminate(self):
                self.code = 0

            def wait(self, timeout=None):
                return self.code

        proc = Running()
        runs.WORLD_RUNS[self.world_id] = {"process": proc, "log_path": "", "schedule": None}
        listed = self._req("GET", "/api/worlds", cookies=[self.teacher])[1]["worlds"][0]
        self.assertEqual((listed["running"], listed["queued"], listed["calls_today"]), (True, None, 0))
        self.assertEqual(self._req("POST", f"/api/worlds/{self.world_id}/stop", {}, [self.li])[0].status, 404)
        self.assertIsNone(proc.code)
        body = self._req("POST", f"/api/worlds/{self.world_id}/stop", {}, [self.teacher])[1]
        self.assertEqual((proc.code, body["world"]["running"]), (0, False))

    def test_broadcast_reaches_each_chosen_world(self):
        payload = {
            "world_ids": [self.world_id, "", "w00000000"],
            "title": "台风过境",
            "description": "停课一天",
        }
        self.assertEqual(self._req("POST", "/api/worlds/broadcast", payload, [self.wang])[0].status, 403)
        results = self._req("POST", "/api/worlds/broadcast", payload, [self.teacher])[1]["results"]
        self.assertEqual(
            [(r["id"], r["ok"]) for r in results], [(self.world_id, True), ("", True), ("w00000000", False)]
        )
        for events_dir in (
            os.path.join(self.root, "life_events"),
            os.path.join(self.tmp.name, "output", "life_events"),
        ):
            with open(os.path.join(events_dir, "events.json"), encoding="utf-8") as handle:
                events = json.load(handle)
            events = events.get("events", events) if isinstance(events, dict) else events
            self.assertEqual(len(events), 1, events_dir)
            self.assertEqual(
                (events[0]["title"], events[0]["agent_ids"], events[0]["schedule_mode"]),
                ("台风过境", [], "immediate"),
            )

    def test_play_log_export(self):
        records = os.path.join(self.root, "records")
        os.makedirs(records)
        with open(os.path.join(records, "multiplayer.act.jsonl"), "w", encoding="utf-8") as f:
            f.write(
                json.dumps(
                    {"_day": 1, "_time": "08:00", "player": "小王", "agent_name": "甲", "text": "去菜市场"},
                    ensure_ascii=False,
                )
                + "\n"
            )
        self.assertEqual(
            self._req("GET", f"/api/worlds/{self.world_id}/trail", cookies=[self.li])[0].status, 404
        )
        body = self._req("GET", f"/api/worlds/{self.world_id}/trail", cookies=[self.wang])[1]
        self.assertIn("第 1 天 08:00 小王（甲）：去菜市场", body["markdown"])
        self.assertIn("## 对话", body["markdown"])


if __name__ == "__main__":
    unittest.main()
