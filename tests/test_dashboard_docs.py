"""The 文档 panel: the docs it lists must actually be there, and be reachable.

The panel does not keep its own copy of the documentation — it fetches the
repository's Markdown over the same static route the dashboard already serves,
so the page always shows what is really in ``docs/``. That design has exactly
one failure mode worth pinning down: a document gets renamed or moved, the
hand-written manifest in ``docs.js`` keeps pointing at the old path, and the
panel shows "读不到" for a tutorial that still exists. The list is short and
manual, so nothing else catches it.

The rest is wiring: the Console shell has to register the tab (a page nobody
can reach is the same as a missing page), and the static route has to answer
for repository Markdown, not just for files under ``site/``.
"""

from __future__ import annotations

import os
import re
import sys
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from gaworld.apps import dashboard_server as ds

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SITE = os.path.join(REPO_ROOT, "site")
DOCS_JS = os.path.join(SITE, "dashboard", "docs.js")


def _manifest_paths():
    with open(DOCS_JS, encoding="utf-8") as handle:
        source = handle.read()
    paths = re.findall(r'^\s*path:\s*"([^"]+)"', source, flags=re.MULTILINE)
    assert paths, "docs.js should declare a DOCS manifest with path entries"
    return paths


def _read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


class DocsManifestTest(unittest.TestCase):
    def test_every_listed_document_exists(self):
        for path in _manifest_paths():
            with self.subTest(path=path):
                self.assertTrue(path.startswith("/"), "paths are served, so they are absolute")
                self.assertTrue(
                    os.path.isfile(os.path.join(REPO_ROOT, path.lstrip("/"))),
                    f"{path} is listed in the 文档 panel but missing from the repository",
                )

    def test_the_tutorials_are_listed(self):
        paths = _manifest_paths()
        self.assertIn("/docs/TUTORIAL.md", paths)
        self.assertIn("/docs/TUTORIAL.v2.md", paths)

    def test_console_registers_the_docs_tab(self):
        console_js = _read(os.path.join(SITE, "console", "console.js"))
        console_html = _read(os.path.join(SITE, "console", "index.html"))
        self.assertIn('{ id: "docs", src: "/site/dashboard/docs.html" }', console_js)
        self.assertIn('data-tab="docs"', console_html)

    def test_page_loads_its_two_scripts(self):
        page = _read(os.path.join(SITE, "dashboard", "docs.html"))
        self.assertIn("/site/dashboard/docs-markdown.js", page)
        self.assertIn("/site/dashboard/docs.js", page)


class DocsServingTest(unittest.TestCase):
    """The panel fetches raw Markdown, so the static route must serve it."""

    def setUp(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), ds.DashboardHandler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def _get(self, path):
        url = f"http://127.0.0.1:{self.port}{path}"
        with urllib.request.urlopen(url, timeout=10) as res:
            return res.read().decode("utf-8"), res.status

    def test_listed_documents_are_served(self):
        for path in _manifest_paths():
            with self.subTest(path=path):
                body, status = self._get(path)
                self.assertEqual(200, status)
                self.assertTrue(body.strip(), f"{path} is served but empty")

    def test_panel_assets_are_served(self):
        for path in (
            "/site/dashboard/docs.html",
            "/site/dashboard/docs.js",
            "/site/dashboard/docs.css",
            "/site/dashboard/docs-markdown.js",
        ):
            with self.subTest(path=path):
                _, status = self._get(path)
                self.assertEqual(200, status)


if __name__ == "__main__":
    unittest.main()
