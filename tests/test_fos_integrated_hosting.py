"""FOS integrated build hosting and launcher validation.

The console hosts the built FOS frontend at ``/fos/``; the bundle must be the
*integrated* build (``npm run build:integrated``, asset refs ``/fos/assets/*``).
These tests use a tiny fixture dist (no npm build) and check:

- ``GET /fos/`` serves index.html whose local refs start ``/fos/assets/``;
- the referenced main JS answers 200 with a JS MIME type, main CSS 200 text/css;
- a deep SPA route (``/fos/simulations/<id>``) serves the same index.html;
- ``fos_supervisor.validate_fos_dist`` rejects a bad dist with one actionable
  message naming ``npm run build:integrated``.
"""

from __future__ import annotations

import os
import re
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from gaworld.apps import dashboard_server as ds
from gaworld.apps import fos_supervisor

FIXTURE_INDEX = (
    "<!doctype html><html><head>"
    '<link rel="stylesheet" href="/fos/assets/index-test.css">'
    "</head><body>"
    '<script type="module" src="/fos/assets/index-test.js"></script>'
    "</body></html>"
)


def _write_fixture_dist(extra_files=()):
    dist = tempfile.mkdtemp(prefix="fos-fixture-dist-")
    assets = os.path.join(dist, "assets")
    os.makedirs(assets)
    with open(os.path.join(dist, "index.html"), "w", encoding="utf-8") as fh:
        fh.write(FIXTURE_INDEX)
    with open(os.path.join(assets, "index-test.js"), "w", encoding="utf-8") as fh:
        fh.write("console.log('ok');\n")
    with open(os.path.join(assets, "index-test.css"), "w", encoding="utf-8") as fh:
        fh.write("body{color:rebeccapurple}\n")
    for name, content in extra_files:
        with open(os.path.join(dist, name), "w", encoding="utf-8") as fh:
            fh.write(content)
    return dist


def _bad_dist_standalone_base():
    dist = _write_fixture_dist()
    bad = FIXTURE_INDEX.replace("/fos/assets/", "/assets/")
    with open(os.path.join(dist, "index.html"), "w", encoding="utf-8") as fh:
        fh.write(bad)
    return dist


class FosFixtureHostingTest(unittest.TestCase):
    """Serve a fixture dist through the dashboard hosting path."""

    @classmethod
    def setUpClass(cls):
        cls._saved = ds.FOS_DIST
        ds.FOS_DIST = _write_fixture_dist()
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), ds.DashboardHandler)
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        ds.FOS_DIST = cls._saved

    def _get(self, path):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}")
        try:
            with urllib.request.urlopen(req, timeout=10) as res:
                return res.status, res.headers.get("Content-Type", ""), res.read()
        except urllib.error.HTTPError as err:
            return err.code, "", err.read()

    def test_get_fos_root_200_with_fos_asset_refs(self):
        status, _, body = self._get("/fos/")
        self.assertEqual(200, status)
        html = body.decode("utf-8")
        refs = re.findall(r'(?:src|href)="/([^"]+)"', html)
        self.assertTrue(refs, "fixture index must reference local assets")
        for ref in refs:
            self.assertTrue(ref.startswith("fos/assets/"), ref)

    def test_main_js_200_with_js_mime(self):
        status, ctype, _ = self._get("/fos/assets/index-test.js")
        self.assertEqual(200, status)
        self.assertIn("javascript", ctype)

    def test_main_css_200_with_text_css(self):
        status, ctype, _ = self._get("/fos/assets/index-test.css")
        self.assertEqual(200, status)
        self.assertIn("text/css", ctype)

    def test_deep_spa_route_serves_index(self):
        status, _, body = self._get("/fos/simulations/abc123")
        self.assertEqual(200, status)
        self.assertEqual(FIXTURE_INDEX, body.decode("utf-8"))


class FosDistValidatorTest(unittest.TestCase):
    """Unit tests for fos_supervisor.validate_fos_dist."""

    def test_good_fixture_passes(self):
        dist = _write_fixture_dist()
        self.assertEqual(dist, fos_supervisor.validate_fos_dist(dist))

    def test_missing_dist_is_rejected_with_actionable_message(self):
        with self.assertRaises(fos_supervisor.FosBackendError) as ctx:
            fos_supervisor.validate_fos_dist(os.path.join(tempfile.mkdtemp(), "nope"))
        msg = str(ctx.exception)
        self.assertIn("npm run build:integrated", msg)

    def test_standalone_base_dist_is_rejected_with_actionable_message(self):
        dist = _bad_dist_standalone_base()
        with self.assertRaises(fos_supervisor.FosBackendError) as ctx:
            fos_supervisor.validate_fos_dist(dist)
        msg = str(ctx.exception)
        self.assertIn("npm run build:integrated", msg)
        self.assertIn("/assets/", msg)

    def test_incomplete_dist_is_rejected_with_actionable_message(self):
        dist = _write_fixture_dist()
        os.remove(os.path.join(dist, "assets", "index-test.js"))
        with self.assertRaises(fos_supervisor.FosBackendError) as ctx:
            fos_supervisor.validate_fos_dist(dist)
        msg = str(ctx.exception)
        self.assertIn("npm run build:integrated", msg)
        self.assertIn("index-test.js", msg)


if __name__ == "__main__":
    unittest.main()
