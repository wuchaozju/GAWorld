"""Phase 1: the built FOS frontend is hosted by the GAWorld dashboard at /fos/.

The FOS React app is grafted at ``fos/`` and built into ``fos/frontend/dist``
with ``FRONTEND_BASE_URL=/fos/``. The dashboard server must host that build
under ``/fos/``:

- ``/fos`` and ``/fos/`` (and any deep SPA route like ``/fos/simulations/test``)
  serve ``fos/frontend/dist/index.html`` so that refreshing a deep route works;
- real files under ``/fos/assets/`` are served from the build output, but a
  nonexistent asset is a plain 404 — never the SPA fallback (that would serve
  HTML to a ``<script src>`` and silently break the app);
- ``/fos/api/*`` is reserved for Phase 2: it must never SPA-fallback, it stays
  a 404 / non-success until the backend lands;
- the existing dotfile guard is untouched: ``/.env`` stays blocked.

These tests were written first (TDD RED) and expect a shared GET/HEAD routing
helper in ``gaworld/apps/dashboard_server.py``; they fail against HEAD because
the ``/fos`` routes do not exist yet.
"""

from __future__ import annotations

import os
import sys
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from gaworld.apps import dashboard_server as ds

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
FOS_INDEX = os.path.join(REPO_ROOT, "fos", "frontend", "dist", "index.html")


def _fos_index_html():
    with open(FOS_INDEX, encoding="utf-8") as handle:
        return handle.read()


class FosFrontendHostingTest(unittest.TestCase):
    """Requests against a live dashboard server (ThreadingHTTPServer)."""

    @classmethod
    def setUpClass(cls):
        if not os.path.isfile(FOS_INDEX):
            raise unittest.SkipTest("fos/frontend/dist/index.html missing — build the FOS frontend first")
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), ds.DashboardHandler)
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def _request(self, path, method="GET"):
        url = f"http://127.0.0.1:{self.port}{path}"
        req = urllib.request.Request(url, method=method)
        try:
            with urllib.request.urlopen(req, timeout=10) as res:
                return res.status, res.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as err:
            return err.code, err.read().decode("utf-8", errors="replace")

    # -- SPA entry and deep routes ------------------------------------------

    def test_get_fos_root_serves_index_html(self):
        status, body = self._request("/fos/")
        self.assertEqual(200, status, "/fos/ must serve the built FOS index")
        self.assertEqual(_fos_index_html(), body, "/fos/ must serve dist/index.html verbatim")

    def test_get_fos_without_trailing_slash_serves_index_html(self):
        status, body = self._request("/fos")
        self.assertEqual(200, status, "/fos must serve the built FOS index")
        self.assertEqual(_fos_index_html(), body)

    def test_get_deep_spa_route_serves_index_html(self):
        status, body = self._request("/fos/simulations/test")
        self.assertEqual(200, status, "deep SPA routes must fall back to index.html")
        self.assertEqual(_fos_index_html(), body)

    # -- assets -------------------------------------------------------------

    def test_missing_asset_is_404_not_spa_fallback(self):
        status, body = self._request("/fos/assets/definitely-not-real.js")
        self.assertEqual(404, status, "a nonexistent asset must 404")
        self.assertNotIn("<!doctype html", body.lower(), "404 must not be the SPA index")

    # -- reserved API namespace ---------------------------------------------

    def test_fos_api_is_reserved_never_spa_fallback(self):
        status, body = self._request("/fos/api/test")
        self.assertNotEqual(200, status, "/fos/api/* is Phase 2; it must not succeed yet")
        self.assertNotIn("<!doctype html", body.lower(), "/fos/api/* must never SPA-fallback")

    # -- HEAD variants share the same routing --------------------------------

    def test_head_fos_root_matches_get(self):
        status, body = self._request("/fos/", method="HEAD")
        self.assertEqual(200, status, "HEAD /fos/ must answer like GET")
        self.assertEqual("", body, "HEAD must not carry a body")

    def test_head_deep_spa_route_matches_get(self):
        status, body = self._request("/fos/simulations/test", method="HEAD")
        self.assertEqual(200, status, "HEAD deep SPA route must answer like GET")
        self.assertEqual("", body)

    def test_head_missing_asset_is_404(self):
        status, body = self._request("/fos/assets/definitely-not-real.js", method="HEAD")
        self.assertEqual(404, status)
        self.assertEqual("", body)

    def test_head_fos_api_is_reserved(self):
        status, body = self._request("/fos/api/test", method="HEAD")
        self.assertNotEqual(200, status)
        self.assertEqual("", body)

    # -- existing security is preserved --------------------------------------

    def test_dotenv_stays_blocked(self):
        status, body = self._request("/.env")
        self.assertEqual(404, status, "/.env must stay blocked (dotfile guard)")
        self.assertNotIn("API_KEY", body.upper(), "blocked responses must not leak file contents")

    def test_head_dotenv_stays_blocked(self):
        status, _ = self._request("/.env", method="HEAD")
        self.assertEqual(404, status)


if __name__ == "__main__":
    unittest.main()
