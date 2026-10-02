"""Worlds (proposal 2026-10-01-multi-user, P2).

* Paths: a world pins every runtime path, the Recorder, the intervention queue
  and its own copy of the residents under ``output/worlds/<id>/``.
* Config: a world's settings layer over the global file; writes go to the
  world, never to ``dashboard_config.json``.
* Access: a private world is invisible to others (API, static files, replay
  list); only its owner writes in it; the shared default world is admin-only.
* Runs: one per world, limited by admin-tunable caps; the rest wait in a FIFO
  queue and start, in their own world, when a slot frees.
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

PASSWORD = "correct horse"
CSV = "id,name,emotion\n1,甲,0.5\n2,乙,0.4\n"
MD = "## Profile 1 | 甲\n一位居民。\n\n## Profile 2 | 乙\n另一位。\n"


def _read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


class PathsTest(unittest.TestCase):
    def test_overrides_pin_everything_under_the_world(self):
        patch = worlds.overrides("w0123abcd")
        base = "output/worlds/w0123abcd"
        self.assertEqual(patch["memory_dir"], f"{base}/memory")
        self.assertEqual(patch["visualization"]["output_dir"], f"{base}/visualization")
        self.assertEqual(patch["records"]["output_dir"], f"{base}/records")
        self.assertEqual(patch["kernel"]["interventions_path"], f"{base}/kernel/interventions.json")
        self.assertEqual((patch["csv_path"], patch["md_path"]), worlds.seed_paths("w0123abcd"))

    def test_ids_are_validated(self):
        for bad in ("", "../x", "w0123", "W0123ABCD", "w0123abcd/.."):
            with self.assertRaises(ValueError):
                worlds.root(bad)


class PolicyTest(unittest.TestCase):
    OWNER = {"id": 2, "role": "member"}  # noqa: RUF012
    OTHER = {"id": 3, "role": "member"}  # noqa: RUF012

    def test_world_writes(self):
        world = {"id": "w0123abcd", "owner_id": 2}
        for path in (
            "/api/config",
            "/api/run/start",
            "/api/agents/3/state",
            "/api/interventions/set_agent_state",
        ):
            self.assertEqual(policy.required("POST", path), "world", path)
        self.assertEqual(policy.required("POST", "/api/agents/3/big5"), "admin")
        self.assertTrue(policy.allows(self.OWNER, "world", world))
        self.assertFalse(policy.allows(self.OTHER, "world", world))
        self.assertFalse(policy.allows(self.OWNER, "world", None))  # the shared default world
        self.assertEqual(policy.required("POST", "/api/worlds/w0123abcd/delete"), "member")
        self.assertEqual(policy.required("POST", "/api/worlds/settings"), "admin")


class FakeProc:
    """Stands in for the simulator: runs until terminated."""

    started: list[FakeProc] = []  # noqa: RUF012

    def __init__(self, *args, env=None, **kwargs):
        self.env = env or {}
        self.code = None
        FakeProc.started.append(self)

    def poll(self):
        return self.code

    def terminate(self):
        self.code = 0

    def kill(self):
        self.code = -9

    def wait(self, timeout=None):
        return self.code


class WorldsHttpTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = self.tmp.name
        os.makedirs(os.path.join(root, "seed"))
        self.csv = os.path.join(root, "seed", "a.csv")
        self.md = os.path.join(root, "seed", "a.md")
        with open(self.csv, "w", encoding="utf-8") as f:
            f.write(CSV)
        with open(self.md, "w", encoding="utf-8") as f:
            f.write(MD)
        self.global_config = os.path.join(root, "dashboard_config.json")
        with open(self.global_config, "w", encoding="utf-8") as f:
            json.dump({"sim_days": 9}, f)
        db = os.path.join(root, "accounts.sqlite")
        self.store = AccountStore(db)
        self.store.init_schema()
        self.store.create_user("老师", PASSWORD, role="admin")
        self.store.create_user("小王", PASSWORD)
        self.store.create_user("小李", PASSWORD)
        FakeProc.started = []
        self.patches = [
            mock.patch.dict(os.environ, {"GAWORLD_ACCOUNTS_DB": db}),
            mock.patch.object(ds, "REPO_ROOT", root),
            mock.patch.object(ds, "DASHBOARD_CONFIG_PATH", self.global_config),
            mock.patch.object(ds, "_city_seed_files", return_value=("", self.csv, self.md)),
            mock.patch.object(ds.subprocess, "Popen", FakeProc),
            mock.patch.object(ds, "DISPATCH_SECONDS", 0.05),
            mock.patch.object(ds, "WORLD_RUNS", {}),
            mock.patch.object(ds, "RUN_QUEUE", []),
        ]
        for patch in self.patches:
            patch.start()
        os.environ.pop("GAWORLD_DASHBOARD_TOKEN", None)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), ds.DashboardHandler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.port = self.server.server_address[1]

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        for patch in reversed(self.patches):
            patch.stop()
        self.tmp.cleanup()

    def _req(self, method, path, body=None, cookies=()):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        headers = {"Cookie": "; ".join(c for c in cookies if c)} if any(cookies) else {}
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        conn.request(method, path, body=data, headers=headers)
        resp = conn.getresponse()
        raw = resp.read()
        conn.close()
        try:
            return resp, json.loads(raw) if raw else None
        except ValueError:
            return resp, None

    def _login(self, nickname):
        resp, _ = self._req("POST", "/api/auth/login", {"nickname": nickname, "password": PASSWORD})
        return resp.getheader("Set-Cookie").split(";", 1)[0]

    def _new_world(self, session, name):
        resp, body = self._req("POST", "/api/worlds/create", {"name": name}, [session])
        self.assertEqual(resp.status, 200, body)
        return body["world"]["id"], resp.getheader("Set-Cookie").split(";", 1)[0]

    def test_world_config_is_private_and_layered(self):
        wang = self._login("小王")
        li = self._login("小李")
        world_id, in_world = self._new_world(wang, "小王的世界")
        base = os.path.join(self.tmp.name, "output", "worlds", world_id)
        self.assertEqual(_read(os.path.join(base, "seed", "agents.csv")), CSV)

        # The global file is the base layer; the world's own writes land in the world.
        self.assertEqual(self._req("GET", "/api/config", cookies=[wang, in_world])[1]["sim_days"], 9)
        resp, body = self._req("POST", "/api/config", {"sim_days": 3}, [wang, in_world])
        self.assertEqual((resp.status, body["sim_days"]), (200, 3))
        self.assertEqual(json.loads(_read(self.global_config))["sim_days"], 9)
        self.assertEqual(json.loads(_read(os.path.join(base, "config.json")))["sim_days"], 3)
        self.assertEqual(self._req("GET", "/api/config", cookies=[wang])[1]["sim_days"], 9)

        # Only the owner writes in a world, and only an admin in the default one.
        self.assertEqual(self._req("POST", "/api/config", {"sim_days": 1}, [wang])[0].status, 403)
        # Someone else's private world: the cookie is ignored, the world unlisted.
        self.assertEqual(self._req("GET", "/api/config", cookies=[li, in_world])[1]["sim_days"], 9)
        self.assertEqual(self._req("GET", "/api/worlds", cookies=[li])[1]["worlds"], [])
        self.assertEqual(self._req("POST", "/api/worlds/select", {"id": world_id}, [li])[0].status, 404)

        # Static files of a private world are hidden; sharing it opens reads only.
        os.makedirs(os.path.join(base, "visualization"))
        with open(os.path.join(base, "visualization", "simulation_trace.json"), "w") as f:
            f.write("{}")
        trace = f"/output/worlds/{world_id}/visualization/simulation_trace.json"
        self.assertEqual(self._req("GET", trace, cookies=[li])[0].status, 404)
        self.assertEqual(
            self._req("POST", f"/api/worlds/{world_id}/visibility", {"visibility": "class"}, [li])[0].status,
            404,
        )
        resp, body = self._req("POST", f"/api/worlds/{world_id}/visibility", {"visibility": "class"}, [wang])
        self.assertEqual(body["world"]["visibility"], "class")
        self.assertEqual(self._req("GET", trace, cookies=[li])[0].status, 200)
        self.assertEqual(self._req("GET", "/api/config", cookies=[li, in_world])[1]["sim_days"], 3)
        resp, body = self._req("POST", "/api/config", {"sim_days": 1}, [li, in_world])
        self.assertEqual(resp.status, 403)
        self.assertIn("创建者", body["error"])

    def test_world_paths_while_active(self):
        world = self.store.create_world(1, "w")
        token = ds._WORLD.set(world)
        try:
            cfg = ds._effective_config()
            self.assertEqual(cfg["memory_dir"], f"output/worlds/{world['id']}/memory")
            self.assertEqual(
                ds._state_csv_path(), os.path.join(self.tmp.name, worlds.seed_paths(world["id"])[0])
            )
            self.assertTrue(ds._records_dir().endswith(f"output/worlds/{world['id']}/records"))
        finally:
            ds._WORLD.reset(token)
        self.assertEqual(ds._state_csv_path(), ds.STATE_CSV_PATH)

    def _status(self, cookies):
        return self._req("GET", "/api/run/status", cookies=cookies)[1]

    def test_run_limits_queue_and_isolation(self):
        teacher = self._login("老师")
        wang = self._login("小王")
        li = self._login("小李")
        self.assertEqual(
            self._req("POST", "/api/worlds/settings", {"max_concurrent_runs": 1}, [wang])[0].status, 403
        )
        resp, body = self._req("POST", "/api/worlds/settings", {"max_concurrent_runs": 1}, [teacher])
        self.assertEqual(body["limits"], {"max_concurrent_runs": 1, "max_runs_per_user": 1, "daily_llm_calls_per_user": 0})

        wang_world, in_wang = self._new_world(wang, "甲")
        li_world, in_li = self._new_world(li, "乙")
        resp, body = self._req("POST", "/api/run/start", {}, [wang, in_wang])
        self.assertTrue(body["running"], body)
        overrides = json.loads(FakeProc.started[0].env["GAWORLD_CONFIG_OVERRIDES"])
        self.assertEqual(overrides["memory_dir"], f"output/worlds/{wang_world}/memory")

        resp, body = self._req("POST", "/api/run/start", {}, [li, in_li])
        self.assertEqual((body["running"], body["queued"]), (False, 1))
        self.assertEqual(
            self._req("POST", "/api/run/start", {}, [li, in_li])[1]["error"], "Simulation is already queued"
        )
        resp, body = self._req("POST", f"/api/worlds/{wang_world}/delete", {}, [wang])
        self.assertEqual(resp.status, 400)

        self._req("POST", "/api/run/stop", {}, [wang, in_wang])
        deadline = time.time() + 5
        while time.time() < deadline and not self._status([li, in_li])["running"]:
            time.sleep(0.05)
        self.assertTrue(self._status([li, in_li])["running"])
        overrides = json.loads(FakeProc.started[1].env["GAWORLD_CONFIG_OVERRIDES"])
        self.assertEqual(overrides["memory_dir"], f"output/worlds/{li_world}/memory")
        self.assertFalse(self._status([wang, in_wang])["running"])
        self.assertTrue(os.path.exists(os.path.join(self.tmp.name, "output", "worlds", li_world, "run.log")))

        resp, _ = self._req("POST", f"/api/worlds/{wang_world}/delete", {}, [wang])
        self.assertEqual(resp.status, 200)
        self.assertFalse(os.path.exists(os.path.join(self.tmp.name, "output", "worlds", wang_world)))
        actions = [row["action"] for row in self.store.list_audit()]
        for action in ("world_create", "world_delete", "limits"):
            self.assertIn(action, actions)


class ModuleEntryPointTest(unittest.TestCase):
    """`python -m gaworld.apps.dashboard_server` must not split the state.

    Run as `__main__`, the file used to serve requests from one copy of the
    module while the API modules imported a second: the world `_guard` chose was
    invisible to `/api/worlds`, the run table and the queue were doubled.
    """

    def test_selected_world_is_seen_by_the_api_modules(self):
        import socket
        import subprocess

        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "accounts.sqlite")
            store = AccountStore(db)
            store.init_schema()
            user = store.create_user("小王", PASSWORD)
            world = store.create_world(user["id"], "甲")
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                port = sock.getsockname()[1]
            env = dict(os.environ, GAWORLD_ACCOUNTS_DB=db)
            env.pop("GAWORLD_DASHBOARD_TOKEN", None)
            proc = subprocess.Popen(
                [sys.executable, "-m", "gaworld.apps.dashboard_server", "--port", str(port)],
                cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            try:

                def call(method, path, body=None, cookie=""):
                    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
                    headers = {"Content-Type": "application/json", "Cookie": cookie}
                    conn.request(
                        method, path, body=json.dumps(body) if body is not None else None, headers=headers
                    )
                    resp = conn.getresponse()
                    data = resp.read()
                    conn.close()
                    return resp, json.loads(data) if data else None

                deadline = time.time() + 30
                while True:
                    try:
                        resp, _ = call("POST", "/api/auth/login", {"nickname": "小王", "password": PASSWORD})
                        break
                    except OSError:
                        if time.time() > deadline:
                            raise
                        time.sleep(0.2)
                session = resp.getheader("Set-Cookie").split(";", 1)[0]
                resp, _ = call("POST", "/api/worlds/select", {"id": world["id"]}, session)
                cookie = session + "; " + resp.getheader("Set-Cookie").split(";", 1)[0]
                self.assertEqual(call("GET", "/api/worlds", cookie=cookie)[1]["current"]["id"], world["id"])
            finally:
                proc.terminate()
                proc.wait(timeout=10)


if __name__ == "__main__":
    unittest.main()
