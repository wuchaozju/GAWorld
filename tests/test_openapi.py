"""`/api/openapi.json` must be valid and must not drift from the router.

Both directions are checked:

* every documented GET is requested against a live handler — the dashboard's
  fall-through answer is ``{"error": "Unknown endpoint"}``, so seeing it means
  the document lists a route the server does not have. POSTs are not sent (a
  bare ``{}`` starts runs and rewrites config); their static segments must
  appear in the server code instead;
* every ``/api/…`` literal in the server code and in the console's scripts must
  be a documented route (or a prefix of one), so a new route without an entry
  fails here.
"""

from __future__ import annotations

import ast
import json
import os
import pathlib
import re
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from gaworld.apps import dashboard_server as ds
from gaworld.apps import openapi, runs, world_paths

try:
    from openapi_spec_validator import validate as _validate
except ImportError:  # optional dev dependency
    _validate = None

ROOT = pathlib.Path(__file__).resolve().parent.parent
APPS = ROOT / "gaworld" / "apps"
#: Other servers (own docs section) and the modules that hold prefixes, not routes.
NOT_DASHBOARD = {"twin_server.py", "distributed_comm_server.py", "external_environment_server.py",
                 "openapi.py", "routes.py"}
#: Long-lived: routed and tested in test_kernel_api.
NOT_PROBED = {"/api/events/stream"}


def _server_literals() -> set[str]:
    """String constants (and f-string heads) starting with /api/ in the server modules."""
    found = set()
    for path in APPS.glob("*.py"):
        if path.name in NOT_DASHBOARD:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.JoinedStr) and node.values and isinstance(node.values[0], ast.Constant):
                head = node.values[0].value
                if isinstance(head, str) and head.startswith("/api/"):
                    found.add(head + "\0")  # a prefix: something follows
            elif isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value.startswith("/api/"):
                found.add(node.value)
    return found


def _console_literals() -> set[str]:
    found = set()
    for path in (ROOT / "site").rglob("*"):
        if path.suffix not in (".js", ".html") or "mobile" in path.parts or path.name.endswith(".test.js"):
            continue
        for match in re.finditer(r"""["'`](/api/[A-Za-z0-9_./-]*)""", path.read_text(encoding="utf-8")):
            found.add(match.group(1))
    return found


def _documented(literal: str) -> bool:
    prefix = literal.endswith("\0")
    literal = literal.rstrip("\0").split("?")[0]
    if not prefix and not literal.endswith("/") and openapi.allowed_methods(literal):
        return True
    return any(template.startswith(literal) or template == literal.rstrip("/")
               for template in openapi.spec()["paths"])


class OpenApiDocumentTest(unittest.TestCase):
    @unittest.skipIf(_validate is None, "openapi-spec-validator not installed")
    def test_document_is_valid_openapi(self):
        _validate(openapi.spec())

    def test_operation_ids_are_unique_and_derived(self):
        ids = [op["operationId"] for item in openapi.spec()["paths"].values() for op in item.values()]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertIn("get_agents_agent_id_state", ids)

    def test_every_operation_states_its_access_level(self):
        for template, item in openapi.spec()["paths"].items():
            for method, op in item.items():
                with self.subTest(route=f"{method.upper()} {template}"):
                    if op["tags"] == ["cluster-node"]:
                        self.assertEqual(op["security"], [{"node": []}])
                    else:
                        self.assertIn(op["x-gaworld-access"], ("public", "member", "city", "world", "admin"))
                    self.assertIn("default", op["responses"])

    def test_every_server_route_is_documented(self):
        missing = sorted(lit.rstrip("\0") for lit in _server_literals() if not _documented(lit))
        self.assertEqual(missing, [], "add these routes to gaworld/apps/openapi.py")

    def test_every_route_the_console_calls_is_documented(self):
        missing = sorted(lit for lit in _console_literals() if not _documented(lit))
        self.assertEqual(missing, [], "the console calls routes the API document does not list")

    def test_every_documented_post_is_spelled_in_the_server(self):
        source = "\n".join(p.read_text(encoding="utf-8") for p in APPS.glob("*.py") if p.name not in NOT_DASHBOARD)
        for template, item in openapi.spec()["paths"].items():
            if "post" not in item:
                continue
            # Routers compare whole paths, prefixes or split segments, so ask
            # only that each fixed segment is spelled somewhere as one.
            words = [w for w in template.split("/")[2:] if not w.startswith("{")]
            with self.subTest(route=template):
                for word in words:
                    self.assertTrue(re.search(rf"""["'/]{re.escape(word)}["'/]""", source), word)

    def test_allowed_methods_matches_templates(self):
        self.assertEqual(openapi.allowed_methods("/api/run/start"), {"POST"})
        self.assertEqual(openapi.allowed_methods("/api/agents/7/state/"), {"GET", "POST"})
        self.assertEqual(openapi.allowed_methods("/api/games/rumor/jobs/rumor-1"), {"GET"})
        self.assertEqual(openapi.allowed_methods("/api/no/such/thing"), frozenset())


class OpenApiServerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._saved = world_paths.REPO_ROOT
        world_paths.REPO_ROOT = self.tmp.name
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), ds.DashboardHandler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        world_paths.REPO_ROOT = self._saved
        self.tmp.cleanup()

    def _call(self, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else (b"{}" if method == "POST" else None)
        req = urllib.request.Request(self.base + path, data=data, method=method,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status, resp.read(), resp.headers
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read(), exc.headers

    def test_served_document_matches_the_module(self):
        status, body, _ = self._call("GET", "/api/openapi.json")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), json.loads(json.dumps(openapi.spec())))

    def test_every_documented_get_is_routed(self):
        from gaworld.llm import providers

        with mock.patch.object(providers, "call_llm", side_effect=RuntimeError("no model in tests")):
            for template, item in openapi.spec()["paths"].items():
                if "get" not in item or template in NOT_PROBED:
                    continue
                path = re.sub(r"\{[^}]+\}", "x", template)
                status, body, _ = self._call("GET", path)
                with self.subTest(route=f"GET {template}"):
                    self.assertNotIn(b"Unknown endpoint", body, f"{status}")
                    self.assertNotEqual(status, 405)

    def test_known_route_with_the_wrong_method_is_405(self):
        status, body, headers = self._call("GET", "/api/run/start")
        self.assertEqual(status, 405)
        self.assertEqual(headers["Allow"], "POST")
        self.assertEqual(json.loads(body)["allowed"], ["POST"])
        status, _, headers = self._call("POST", "/api/run/status")
        self.assertEqual((status, headers["Allow"]), (405, "GET"))

    def test_unknown_routes_answer_the_same_body_everywhere(self):
        for method, path in (("GET", "/api/nope"), ("GET", "/api/population/nope"), ("GET", "/api/city/nope"),
                             ("GET", "/api/games/rumor/nope"), ("POST", "/api/research/nope"),
                             ("POST", "/api/settings/nope"), ("GET", "/api/home/1/2")):
            status, body, _ = self._call(method, path)
            with self.subTest(route=f"{method} {path}"):
                self.assertEqual((status, json.loads(body)), (404, {"error": "Unknown endpoint"}))

    def test_starting_a_second_run_is_409(self):
        with mock.patch.object(runs, "start_simulation", side_effect=runs.RunConflict("Simulation is already running")):
            status, body, _ = self._call("POST", "/api/run/start", {})
        self.assertEqual(status, 409)
        self.assertEqual(json.loads(body), {"error": "Simulation is already running"})


if __name__ == "__main__":
    unittest.main()
