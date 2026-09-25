"""`/api/openapi.json` must be valid and must not drift from the router.

Every documented path/method is requested against a live handler; the
dashboard's fall-through answer is ``{"error": "Unknown endpoint"}``, so seeing
it means the document lists a route the server does not have.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from gaworld.apps import dashboard_server as ds
from gaworld.apps import openapi

try:
    from openapi_spec_validator import validate as _validate
except ImportError:  # optional dev dependency
    _validate = None

#: Bodies that exercise routing without side effects (no job is started).
SAFE_BODIES = {"/api/bench/run": {"kind": "none"}}


class OpenApiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._saved = ds.REPO_ROOT
        ds.REPO_ROOT = self.tmp.name
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), ds.DashboardHandler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        ds.REPO_ROOT = self._saved
        self.tmp.cleanup()

    def _call(self, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else (b"{}" if method == "POST" else None)
        req = urllib.request.Request(self.base + path, data=data, method=method,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()

    @unittest.skipIf(_validate is None, "openapi-spec-validator not installed")
    def test_document_is_valid_openapi(self):
        _validate(openapi.spec())

    def test_served_document_matches_the_module(self):
        status, body = self._call("GET", "/api/openapi.json")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), json.loads(json.dumps(openapi.spec())))

    def test_every_documented_route_is_routed(self):
        for template, item in openapi.spec()["paths"].items():
            if template == "/api/events/stream":
                continue  # long-lived; routed and tested in test_kernel_api
            path = template.replace("{", "x").replace("}", "")
            for method in item:
                status, body = self._call(method.upper(), path, SAFE_BODIES.get(template))
                with self.subTest(route=f"{method.upper()} {template}"):
                    self.assertNotIn(b"Unknown endpoint", body, f"{status}")


if __name__ == "__main__":
    unittest.main()
