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
from gaworld.apps import residents, runs, world_paths

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
        self.assertEqual(policy.required("POST", "/api/agents/3/big5"), "world")
        self.assertTrue(policy.allows(self.OWNER, "world", world))
        self.assertFalse(policy.allows(self.OTHER, "world", world))
        self.assertFalse(policy.allows(self.OWNER, "world", None))  # the shared default world
        self.assertEqual(policy.required("POST", "/api/worlds/w0123abcd/delete"), "member")
        self.assertEqual(policy.required("POST", "/api/worlds/settings"), "admin")

    def test_members_may_tune_parameters_but_not_repoint_a_running_world(self):
        refuse = policy.config_update_refusal
        self.assertIsNone(refuse("economy.credit.annual_interest_rate", 0.15))
        self.assertIsNone(refuse("multiplayer.wait_for_players_seconds", 30))
        self.assertIsNone(refuse("cluster.sync_timeout_seconds", 5))
        self.assertIsNone(refuse("economy.tax.brackets", [[3000, 0.03, 0]]))
        for path, value in (
            ("llm.providers.minimax.base_url", "https://example.com"),  # the model endpoint
            ("real_work.external_hooks.webhook_url", "https://example.com"),
            ("memory_dir", "/tmp"),
            ("economy.output_dir", "/tmp"),  # a path inside an allowed section
            ("life_events.events_file", "x.json"),
            ("cluster.hub_url", "http://example.com"),
            ("economy.credit", {"annual_interest_rate": 1.0}),  # a whole section at once
        ):
            self.assertIsNotNone(refuse(path, value), path)


class BackgroundThreadTest(unittest.TestCase):
    def test_api_jobs_start_through_ownership_spawn(self):
        """A bare thread starts with an empty context: its job forgets the
        asking user's world (and its model calls go uncounted)."""
        apps = os.path.join(os.path.dirname(__file__), "..", "gaworld", "apps")
        # The run dispatcher runs each queued entry in the entry's own copied context.
        allowed = {"runs.py": 1}
        for name in sorted(os.listdir(apps)):
            if name.endswith(".py"):
                count = _read(os.path.join(apps, name)).count("threading.Thread(")
                self.assertLessEqual(count, allowed.get(name, 0), f"{name}: use ownership.spawn()")


class ForeignSimulatorTest(unittest.TestCase):
    """A simulator this dashboard did not start — left by a crashed dashboard,
    or run from the command line — still owns its world's files."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        config = os.path.join(self.tmp.name, "dashboard_config.json")
        with open(config, "w", encoding="utf-8") as f:
            f.write("{}")
        for patch in (
            mock.patch.object(world_paths, "REPO_ROOT", self.tmp.name),
            mock.patch.object(world_paths, "DASHBOARD_CONFIG_PATH", config),
            mock.patch.object(runs, "RUN_STATE", {"process": None, "log_path": os.path.join(self.tmp.name, "run.log")}),
            mock.patch.object(runs, "RUN_QUEUE", []),
            mock.patch.dict(os.environ, {"GAWORLD_ACCOUNTS_DB": os.path.join(self.tmp.name, "none.sqlite")}),
        ):
            patch.start()
            self.addCleanup(patch.stop)
        os.environ.pop("GAWORLD_CONFIG_OVERRIDES", None)

    def _publish(self, pid):
        from gaworld.apps import kernel_api

        path = kernel_api._queue_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"active": True, "pid": pid, "registered": [], "pending": [], "applied": []}, f)

    def test_a_foreign_simulator_blocks_a_second_start_and_can_be_stopped(self):
        import subprocess

        sim = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)", "generative_city_sim.py"])
        self.addCleanup(lambda: sim.poll() is None and sim.kill())
        self._publish(sim.pid)
        self.assertEqual(runs.run_status()["foreign_pid"], sim.pid)
        with self.assertRaises(RuntimeError) as caught:
            runs.start_simulation({})
        self.assertIn(str(sim.pid), str(caught.exception))
        runs.stop_simulation()
        self.assertIsNotNone(sim.wait(timeout=10))

    def test_a_reused_pid_is_not_mistaken_for_a_simulator(self):
        self._publish(os.getpid())  # alive, but this is pytest
        self.assertIsNone(runs.run_status()["foreign_pid"])


class RouteTableTest(unittest.TestCase):
    def test_every_route_reaches_a_handler(self):
        import importlib

        from gaworld.apps import routes

        for table, handler in ((routes.GET_ROUTES, "handle_get"), (routes.POST_ROUTES, "handle_post")):
            for route in table:
                module = importlib.import_module(f"gaworld.apps.{route.module}")
                self.assertTrue(callable(getattr(module, handler, None)), f"{route.module}.{handler}")

    def test_first_match_wins_as_in_the_old_chain(self):
        from gaworld.apps import routes

        self.assertEqual(routes.find(routes.GET_ROUTES, "/api/interventions").module, "kernel_api")
        self.assertIsNone(routes.find(routes.POST_ROUTES, "/api/interventions"))
        # The single-agent interview endpoint is the handler's, not interview_api's.
        self.assertIsNone(routes.find(routes.POST_ROUTES, "/api/interview"))
        self.assertEqual(routes.find(routes.POST_ROUTES, "/api/interview/run").module, "interview_api")
        # City writes carry an ownership check in the handler.
        self.assertIsNone(routes.find(routes.POST_ROUTES, "/api/city/create"))
        self.assertEqual(routes.find(routes.GET_ROUTES, "/api/city/agents").module, "city_api")


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
            mock.patch.object(world_paths, "REPO_ROOT", root),
            mock.patch.object(world_paths, "DASHBOARD_CONFIG_PATH", self.global_config),
            mock.patch.object(ds, "_city_seed_files", return_value=("", self.csv, self.md)),
            mock.patch.object(ds.subprocess, "Popen", FakeProc),
            mock.patch.object(runs, "DISPATCH_SECONDS", 0.05),
            mock.patch.object(runs, "WORLD_RUNS", {}),
            mock.patch.object(runs, "RUN_QUEUE", []),
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
        # Empty path segments collapse when the file is served, so they must not
        # slip past the world check either.
        for variant in (
            f"/output//worlds/{world_id}/visualization/simulation_trace.json",
            f"//output/worlds/{world_id}/visualization/simulation_trace.json",
            f"/output/%2Fworlds/{world_id}/visualization/simulation_trace.json",
            f"/output/worlds//{world_id}/visualization/simulation_trace.json",
        ):
            self.assertEqual(self._req("GET", variant, cookies=[li])[0].status, 404, variant)
            self.assertEqual(self._req("HEAD", variant, cookies=[li])[0].status, 404, variant)
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
            cfg = world_paths.effective_config()
            self.assertEqual(cfg["memory_dir"], f"output/worlds/{world['id']}/memory")
            self.assertEqual(
                world_paths.state_csv_path(), os.path.join(self.tmp.name, worlds.seed_paths(world["id"])[0])
            )
            self.assertTrue(world_paths.records_dir().endswith(f"output/worlds/{world['id']}/records"))
        finally:
            ds._WORLD.reset(token)
        self.assertEqual(world_paths.state_csv_path(), world_paths.STATE_CSV_PATH)

    def test_a_world_keeps_its_own_agent_keyed_inputs(self):
        data = os.path.join(self.tmp.name, "data")
        os.makedirs(data)
        big5 = "id,name,o,c,e,a,n,source,unstated,redundant\n1,甲,0.1,0.2,0.3,0.4,0.5,calibrated,,\n"
        for name, text in (
            ("agents_big5.csv", big5),
            ("family_overrides.json", '{"1": {"marital_status": "married"}}'),
            ("moltbook_accounts.json", '{"agents": {"1": {"api_key": "secret"}}}'),
        ):
            with open(os.path.join(data, name), "w", encoding="utf-8") as f:
                f.write(text)
        wang = self._login("小王")
        world_id, in_world = self._new_world(wang, "小王的世界")
        seed = os.path.join(self.tmp.name, "output", "worlds", world_id, "seed")
        # The residents' personalities and family pins come along; live
        # credentials of real Moltbook accounts do not.
        self.assertEqual(_read(os.path.join(seed, "agents_big5.csv")), big5)
        self.assertTrue(os.path.exists(os.path.join(seed, "family_overrides.json")))
        self.assertFalse(os.path.exists(os.path.join(seed, "moltbook_accounts.json")))

        world = self.store.get_world(world_id)
        token = ds._WORLD.set(world)
        try:
            cfg = world_paths.effective_config()
            seed_rel = f"output/worlds/{world_id}/seed"
            self.assertEqual(cfg["personality"]["profile_path"], f"{seed_rel}/agents_big5.csv")
            self.assertEqual(cfg["family"]["overrides_path"], f"{seed_rel}/family_overrides.json")
            self.assertEqual(cfg["moltbook"]["accounts_path"], f"{seed_rel}/moltbook_accounts.json")
            # Editing a personality in the world edits the world's copy only.
            with mock.patch.object(world_paths, "BIG5_CSV_PATH", os.path.join(data, "agents_big5.csv")):
                residents.save_agent_big5(1, {"values": {"o": 1.25}})
        finally:
            ds._WORLD.reset(token)
        self.assertIn("1.25", _read(os.path.join(seed, "agents_big5.csv")))
        self.assertEqual(_read(os.path.join(data, "agents_big5.csv")), big5)

        # Its owner edits a personality over HTTP; the shared default world stays admin-only.
        url = "/api/agents/1/big5"
        resp, body = self._req("POST", url, {"values": {"c": -0.75}}, [wang, in_world])
        self.assertEqual(resp.status, 200, body)
        self.assertIn("-0.75", _read(os.path.join(seed, "agents_big5.csv")))
        with mock.patch.object(world_paths, "BIG5_CSV_PATH", os.path.join(data, "agents_big5.csv")):
            self.assertEqual(self._req("POST", url, {"values": {"c": 1.0}}, [wang])[0].status, 403)
        self.assertEqual(_read(os.path.join(data, "agents_big5.csv")), big5)

    def test_update_config_over_http_is_limited_for_members(self):
        wang = self._login("小王")
        _world_id, in_world = self._new_world(wang, "小王的世界")
        url = "/api/interventions/update_config"
        resp, body = self._req("POST", url, {"path": "llm.routing.default", "value": "x"}, [wang, in_world])
        self.assertEqual(resp.status, 403, body)
        # A parameter passes the policy; with nothing running it then cannot be queued.
        resp, _ = self._req("POST", url, {"path": "economy.credit.apr", "value": 0.1}, [wang, in_world])
        self.assertEqual(resp.status, 409)

    def test_a_reset_does_not_hold_up_other_worlds(self):
        a = self.store.create_world(2, "a")
        b = self.store.create_world(3, "b")
        entered, release = threading.Event(), threading.Event()

        def slow_reset(*args, **kwargs):
            entered.set()
            release.wait(10)
            return mock.Mock(returncode=0)

        errors = []

        def start_a():
            ds._WORLD.set(a)
            try:
                runs.start_simulation({"reset": True})
            except Exception as exc:
                errors.append(exc)

        def poll_b():
            ds._WORLD.set(b)
            runs.run_status()
            answered.set()

        answered = threading.Event()
        with mock.patch.object(ds.subprocess, "run", slow_reset):
            starter = threading.Thread(target=start_a)
            starter.start()
            self.assertTrue(entered.wait(5))
            # Another world's status poll answers while the reset runs…
            threading.Thread(target=poll_b, daemon=True).start()
            self.assertTrue(answered.wait(2), "status poll blocked behind another world's reset")
            # …and the resetting world cannot be started a second time meanwhile.
            token = ds._WORLD.set(a)
            try:
                with self.assertRaises(RuntimeError):
                    runs.start_simulation({})
            finally:
                ds._WORLD.reset(token)
            release.set()
            starter.join(5)
        self.assertEqual(errors, [])
        self.assertEqual(len(FakeProc.started), 1)

    def test_agent_log_tail_comes_from_the_active_world(self):
        world = self.store.create_world(1, "w")
        for base, text in (("output/logs", "默认世界的日志"), (f"output/worlds/{world['id']}/logs", "本世界的日志")):
            os.makedirs(os.path.join(self.tmp.name, base), exist_ok=True)
            with open(os.path.join(self.tmp.name, base, "agent_1.log"), "w", encoding="utf-8") as f:
                f.write(text)
        token = ds._WORLD.set(world)
        try:
            self.assertEqual(residents.memory_payload(1)["log_tail"], "本世界的日志")
        finally:
            ds._WORLD.reset(token)
        self.assertEqual(residents.memory_payload(1)["log_tail"], "默认世界的日志")

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
