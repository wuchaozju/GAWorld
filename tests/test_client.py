"""`gaworld.client` against a live dashboard handler (temp repo, no model calls)."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from gaworld.accounts import AccountStore
from gaworld.apps import dashboard_server as ds
from gaworld.apps import kernel_api, world_paths
from gaworld.client import (
    APIError,
    AuthError,
    ConflictError,
    GAWorldClient,
    JobFailed,
    NotFoundError,
)


class _Server:
    def __init__(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = world_paths.REPO_ROOT, world_paths.RECORDS_DIR, kernel_api.POLL_SECONDS
        world_paths.REPO_ROOT = self.tmp.name
        world_paths.RECORDS_DIR = os.path.join(self.tmp.name, "records")
        os.makedirs(world_paths.RECORDS_DIR)
        kernel_api.POLL_SECONDS = 0.05
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), ds.DashboardHandler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        world_paths.REPO_ROOT, world_paths.RECORDS_DIR, kernel_api.POLL_SECONDS = self.saved
        self.tmp.cleanup()


class ClientTest(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.dict(os.environ, {"GAWORLD_ACCOUNTS_DB": os.path.join(tempfile.gettempdir(), "none")})
        self.env.start()
        os.environ.pop("GAWORLD_DASHBOARD_TOKEN", None)
        self.srv = _Server()
        self.gw = GAWorldClient(self.srv.url)

    def tearDown(self):
        self.srv.close()
        self.env.stop()

    def test_call_reaches_any_operation_by_id(self):
        self.assertIn("get_agents_agent_id_state", self.gw.operations())
        listing = self.gw.call("get_interventions")
        self.assertFalse(listing["running"])
        self.assertEqual(self.gw.call("get_auth_me"), {"mode": "single"})

    def test_call_fills_path_parameters_and_checks_them(self):
        with self.assertRaises(NotFoundError) as ctx:
            self.gw.call("get_bench_jobs_job_id", job_id="no-such-job")
        self.assertEqual(ctx.exception.status, 404)
        self.assertEqual(ctx.exception.message, "unknown job")
        with self.assertRaises(ValueError):
            self.gw.call("get_bench_jobs_job_id")
        with self.assertRaises(ValueError):
            self.gw.call("get_nothing_at_all")

    def test_errors_carry_status_and_message(self):
        with self.assertRaises(APIError) as ctx:
            self.gw.get("/api/run/start")
        self.assertEqual(ctx.exception.status, 405)
        self.assertEqual(ctx.exception.body["allowed"], ["POST"])
        with self.assertRaises(ConflictError):
            self.gw.intervene("set_agent_state", agent_id=1, key="stress", value=0.5)
        with self.assertRaises(NotFoundError) as ctx:
            self.gw.get("/api/no/such/route")
        self.assertEqual(ctx.exception.message, "Unknown endpoint")

    def test_run_job_polls_the_sibling_jobs_route(self):
        fake = {"run_id": "abc", "created_at": 1.0, "agents": [], "stages": [], "stats": {}}
        with mock.patch("gaworld.apps.disaster_api.run_disaster", return_value=fake):
            result = self.gw.run_job(
                "/api/games/disaster/run",
                {"city": "wuzhen", "agent_ids": [1, 2], "disaster_id": "earthquake"},
                interval=0.01, timeout=10,
            )
        self.assertEqual(result["run_id"], "abc")

    def test_a_failed_job_raises(self):
        with mock.patch("gaworld.apps.disaster_api.run_disaster", side_effect=RuntimeError("boom")):
            with self.assertRaises(JobFailed) as ctx:
                self.gw.run_job("/api/games/disaster/run",
                                {"city": "wuzhen", "agent_ids": [1], "disaster_id": "earthquake"},
                                interval=0.01, timeout=10)
        self.assertEqual(ctx.exception.job["status"], "failed")

    def test_events_yields_table_and_row(self):
        stream = self.gw.events(["traffic.tick"], timeout=5)
        received = []

        def follow():
            for table, row in stream:
                received.append((table, row))
                return

        reader = threading.Thread(target=follow, daemon=True)
        reader.start()
        path = os.path.join(world_paths.RECORDS_DIR, "traffic.tick.jsonl")
        for _ in range(100):  # until the reader is connected and sees the new row
            with open(path, "a") as f:
                f.write(json.dumps({"n": 1}) + "\n")
            reader.join(0.1)
            if received:
                break
        self.assertEqual(received[0], ("traffic.tick", {"n": 1}))

    def test_operator_token_is_sent_as_bearer(self):
        with mock.patch.dict(os.environ, {"GAWORLD_DASHBOARD_TOKEN": "s3cret"}):
            with self.assertRaises(AuthError) as ctx:
                GAWorldClient(self.srv.url, token="wrong").run_status()
            self.assertEqual(ctx.exception.status, 401)
            self.assertIsInstance(GAWorldClient(self.srv.url).run_status(), dict)  # token from the environment
            self.assertIsInstance(GAWorldClient(self.srv.url, token="s3cret").agents(), list)


class ClientAccountsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db = os.path.join(self.tmp.name, "accounts.sqlite")
        self.env = mock.patch.dict(os.environ, {"GAWORLD_ACCOUNTS_DB": db})
        self.env.start()
        os.environ.pop("GAWORLD_DASHBOARD_TOKEN", None)
        store = AccountStore(db)
        store.init_schema()
        store.create_user("老师", "correct horse battery", role="admin")
        self.srv = _Server()

    def tearDown(self):
        self.srv.close()
        self.env.stop()
        self.tmp.cleanup()

    def test_login_keeps_the_session_cookie(self):
        gw = GAWorldClient(self.srv.url)
        with self.assertRaises(AuthError):
            gw.agents()
        user = gw.login("老师", "correct horse battery")
        self.assertEqual(user["role"], "admin")
        self.assertEqual(gw.me()["mode"], "accounts")
        self.assertEqual(gw.worlds()["mode"], "accounts")
        gw.use_world("")
        gw.logout()
        with self.assertRaises(AuthError):
            gw.agents()


if __name__ == "__main__":
    unittest.main()
