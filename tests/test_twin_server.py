import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from gaworld.apps import twin_server
from gaworld.twin import binding
from gaworld.twin.backend import TwinBackend


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Stop urllib following redirects so the 302 itself can be asserted."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _fake_map():
    return {"nodes": {"home": {"id": "home", "name": "home", "x_km": 0.0, "y_km": 0.0}}}


def _request(url, payload=None, token=None):
    """Return (status, parsed_body)."""
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data)
    request.add_header("Content-Type", "application/json")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


class TestTwinServer(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.bindings = os.path.join(self._tmp.name, "twin_bindings.json")
        backend = TwinBackend(
            root=os.path.join(self._tmp.name, "twin"),
            bindings_path=self.bindings,
            city_map=_fake_map(),
            # Point the life artifacts at the sandbox too, or these tests
            # would read the repo's real output/ and break whenever a
            # simulation had produced a diary for this agent id.
            diary_dir=os.path.join(self._tmp.name, "diaries"),
            state_dir=os.path.join(self._tmp.name, "state"),
            memory_dir=os.path.join(self._tmp.name, "memory"),
        )
        handler = twin_server.make_handler(backend)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

        self.code = binding.issue_code(agent_id=7, label="cw", path=self.bindings)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self._tmp.cleanup()

    def _token(self):
        _, body = _request(f"{self.base}/api/twin/auth", {"code": self.code})
        return body["token"]

    def test_auth_returns_a_token(self):
        status, body = _request(f"{self.base}/api/twin/auth", {"code": self.code})
        self.assertEqual(status, 200)
        self.assertTrue(body["token"])

    def test_auth_rejects_a_bad_code(self):
        status, _ = _request(f"{self.base}/api/twin/auth", {"code": "nope"})
        self.assertEqual(status, 403)

    def test_report_requires_a_token(self):
        status, _ = _request(f"{self.base}/api/twin/report", [])
        self.assertEqual(status, 401)

    def test_report_round_trip(self):
        token = self._token()
        payload = [
            {
                "report_id": "a",
                "ts": 1000,
                "loc": {"lat": 30.2741, "lng": 120.1551, "source": "gps"},
                "action_tag": "work",
            }
        ]
        status, body = _request(f"{self.base}/api/twin/report", payload, token=token)
        self.assertEqual(status, 200)
        self.assertEqual(body["accepted"], 1)

        status, body = _request(f"{self.base}/api/twin/snapshot", token=token)
        self.assertEqual(status, 200)
        self.assertEqual(body["report"]["action_tag"], "work")

    def test_report_rejects_a_non_array_body(self):
        token = self._token()
        status, _ = _request(f"{self.base}/api/twin/report", {"report_id": "a"}, token=token)
        self.assertEqual(status, 400)

    def test_every_read_route_requires_a_token(self):
        for path in ("/api/twin/profile", "/api/twin/trail", "/api/twin/snapshot",
                     "/api/twin/life", "/api/twin/reports", "/api/twin/places"):
            with self.subTest(path=path):
                status, _ = _request(f"{self.base}{path}")
                self.assertEqual(status, 401)

    def test_amend_requires_a_token(self):
        status, _ = _request(f"{self.base}/api/twin/amend",
                             {"target": "a", "op": "delete"})
        self.assertEqual(status, 401)

    def test_amend_round_trips(self):
        token = self._token()
        _request(f"{self.base}/api/twin/report", [
            {"report_id": "a", "ts": 1000,
             "loc": {"lat": 30.2741, "lng": 120.1551, "source": "gps"},
             "action_tag": "work"}
        ], token=token)

        status, _ = _request(f"{self.base}/api/twin/amend",
                             {"target": "a", "op": "update",
                              "patch": {"action_tag": "meal"}, "amend_id": "m1"},
                             token=token)
        self.assertEqual(status, 200)

        _, body = _request(f"{self.base}/api/twin/reports", token=token)
        self.assertEqual(body["reports"][0]["action_tag"], "meal")

        status, _ = _request(f"{self.base}/api/twin/amend",
                             {"target": "a", "op": "delete", "amend_id": "m2"},
                             token=token)
        self.assertEqual(status, 200)
        _, body = _request(f"{self.base}/api/twin/reports", token=token)
        self.assertEqual(body["reports"], [])

    def test_life_returns_empty_structures(self):
        _, body = _request(f"{self.base}/api/twin/life", token=self._token())
        self.assertEqual(body["diary"]["text"], "")
        self.assertEqual(body["goals"]["life_goals"], [])

    def test_profile_returns_an_avatar(self):
        status, body = _request(f"{self.base}/api/twin/profile", token=self._token())
        self.assertEqual(status, 200)
        self.assertIn("<svg", body["avatar_svg"])

    def test_root_redirects_so_relative_assets_resolve(self):
        # The client's HTML, manifest start_url, and service-worker scope are
        # all relative. Serving index.html *at* "/" makes the browser request
        # /core.js instead of /site/mobile/core.js, so the page loads with no
        # JS at all — silently, with a 200 on the HTML itself.
        for path in ("/", "/m", "/m/"):
            with self.subTest(path=path):
                request = urllib.request.Request(f"{self.base}{path}")
                opener = urllib.request.build_opener(_NoRedirect)
                try:
                    opener.open(request)
                    self.fail(f"{path} did not redirect")
                except urllib.error.HTTPError as exc:
                    self.assertEqual(exc.code, 302)
                    self.assertEqual(exc.headers["Location"], "/site/mobile/")

    def test_dashboard_endpoints_are_not_reachable(self):
        # The whole reason this is a separate process: none of the dashboard's
        # unauthenticated config-write or process-spawn routes may exist here.
        for path in ("/api/config", "/api/run/start", "/api/settings", "/api/population"):
            with self.subTest(path=path):
                status, _ = _request(f"{self.base}{path}", {}, token=self._token())
                self.assertEqual(status, 404)

    def test_mobile_assets_are_available(self):
        for path in ("/site/mobile/", "/site/mobile/app.js", "/site/mobile/styles.css",
                     "/site/mobile/core.js", "/site/mobile/sw.js",
                     "/site/mobile/manifest.webmanifest"):
            for method in ("GET", "HEAD"):
                with self.subTest(path=path, method=method):
                    request = urllib.request.Request(self.base + path, method=method)
                    with urllib.request.urlopen(request) as response:
                        self.assertEqual(response.status, 200)
                        body = response.read()
                        self.assertEqual(bool(body), method == "GET")

    def test_repository_files_and_traversal_are_not_public(self):
        for path in ("/AGENTS.md", "/.git/config", "/data/twin_bindings.json",
                     "/output/twin/", "/site/", "/site/mobile/core.test.js",
                     "/site/mobile/../../AGENTS.md",
                     "/site/mobile/%2e%2e/%2e%2e/AGENTS.md"):
            for method in ("GET", "HEAD"):
                with self.subTest(path=path, method=method):
                    request = urllib.request.Request(self.base + path, method=method)
                    with self.assertRaises(urllib.error.HTTPError) as error:
                        urllib.request.urlopen(request)
                    self.assertEqual(error.exception.code, 404)
                    error.exception.close()

    def test_mobile_asset_symlinks_cannot_escape_bundle(self):
        root = Path(self._tmp.name)
        mobile = root / "site/mobile"
        mobile.mkdir(parents=True)
        secret = root / "private.txt"
        secret.write_text("private", encoding="utf-8")
        (mobile / "app.js").symlink_to(secret)
        with patch.object(twin_server, "REPO_ROOT", str(root)):
            for method in ("GET", "HEAD"):
                request = urllib.request.Request(self.base + "/site/mobile/app.js", method=method)
                with self.assertRaises(urllib.error.HTTPError) as error:
                    urllib.request.urlopen(request)
                self.assertEqual(error.exception.code, 404)
                error.exception.close()


if __name__ == "__main__":
    unittest.main()
