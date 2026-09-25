"""Dashboard access control.

Two failure modes:

* **Secrets served as static files.** The handler serves the repo root, so
  before the dot-path filter `/.env` (live API keys) and `/.git/config`
  returned 200 — reachable from the network under the documented 0.0.0.0
  deployment. Refused with or without a token.
* **A token that breaks the console or leaks.** With the token set every
  request needs it; the browser logs in once via `?token=` and then rides an
  HttpOnly SameSite cookie, scripts use Bearer, and the token never reaches the
  request log.
"""

from __future__ import annotations

import http.client
import io
import json
import os
import sys
import threading
import unittest
from contextlib import redirect_stderr
from http.server import ThreadingHTTPServer
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from gaworld.apps import dashboard_server as ds

TOKEN = "s3cret-token"


class AuthTest(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), ds.DashboardHandler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.port = self.server.server_address[1]

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def _req(self, method, path, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request(method, path, headers=headers or {})
        resp = conn.getresponse()
        body = resp.read()
        conn.close()
        return resp, body

    def test_dot_paths_are_never_served(self):
        for env in ({}, {"GAWORLD_DASHBOARD_TOKEN": TOKEN}):
            with mock.patch.dict(os.environ, env, clear=False):
                if not env:
                    os.environ.pop("GAWORLD_DASHBOARD_TOKEN", None)
                for path in ("/.env", "/.git/config", "/site/../.env", "/x/.hidden"):
                    resp, body = self._req("GET", path, {"Authorization": f"Bearer {TOKEN}"})
                    self.assertEqual(resp.status, 404, path)
                    self.assertNotIn(b"API_KEY", body)
                self.assertEqual(self._req("HEAD", "/.env")[0].status, 404)

    def test_without_token_everything_is_open_as_before(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("GAWORLD_DASHBOARD_TOKEN", None)
            self.assertEqual(self._req("GET", "/api/interventions")[0].status, 200)
            self.assertEqual(self._req("GET", "/site/console/index.html")[0].status, 200)

    def test_token_gates_api_static_and_post(self):
        with mock.patch.dict(os.environ, {"GAWORLD_DASHBOARD_TOKEN": TOKEN}):
            resp, body = self._req("GET", "/api/interventions")
            self.assertEqual(resp.status, 401)
            self.assertIn("error", json.loads(body))
            self.assertEqual(self._req("GET", "/site/console/index.html")[0].status, 401)
            self.assertEqual(self._req("POST", "/api/interventions/x")[0].status, 401)
            self.assertEqual(self._req("GET", "/api/interventions",
                                       {"Authorization": "Bearer wrong"})[0].status, 401)
            self.assertEqual(self._req("GET", "/api/interventions",
                                       {"Authorization": f"Bearer {TOKEN}"})[0].status, 200)

    def test_browser_login_sets_a_strict_cookie_and_strips_the_token(self):
        with mock.patch.dict(os.environ, {"GAWORLD_DASHBOARD_TOKEN": TOKEN}):
            log = io.StringIO()
            with redirect_stderr(log):
                resp, _ = self._req("GET", f"/dashboard?tab=a&token={TOKEN}")
            self.assertEqual(resp.status, 303)
            self.assertEqual(resp.getheader("Location"), "/dashboard?tab=a")
            cookie = resp.getheader("Set-Cookie")
            for attr in ("HttpOnly", "SameSite=Strict", "Path=/"):
                self.assertIn(attr, cookie)
            self.assertNotIn(TOKEN, log.getvalue())
            jar = cookie.split(";", 1)[0]
            self.assertEqual(self._req("GET", "/api/interventions", {"Cookie": jar})[0].status, 200)
            self.assertEqual(self._req("GET", "/site/console/index.html", {"Cookie": jar})[0].status, 200)
            self.assertEqual(self._req("GET", "/?token=nope")[0].status, 401)


if __name__ == "__main__":
    unittest.main()
