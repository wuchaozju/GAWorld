"""Browser smoke tests: two editors load and work in a real Chromium.

The Python and Node suites check the pages' code; these check that the pages
actually come up in a browser against the real dashboard server — the
Population Studio walks from its template step to the structure step and
re-checks the parameters, and the Agent Studio family editor opens and adds a
child. Nothing is saved, and any page error fails the test.

Skipped unless Playwright and a Chromium it can launch are installed::

    pip install playwright && python -m playwright install chromium

(CI installs both.)
"""

from __future__ import annotations

import threading
import unittest
from http.server import ThreadingHTTPServer

from gaworld.apps import dashboard_server as ds

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover - depends on the environment
    sync_playwright = None

TIMEOUT_MS = 20_000


class BrowserSmokeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if sync_playwright is None:
            raise unittest.SkipTest("playwright is not installed")
        cls.playwright = sync_playwright().start()
        try:
            cls.browser = cls.playwright.chromium.launch()
        except Exception as exc:  # no browser binary, or missing system libraries
            cls.playwright.stop()
            raise unittest.SkipTest(f"Chromium cannot start: {str(exc).splitlines()[0]}") from exc
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), ds.DashboardHandler)
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()
        cls.server.shutdown()
        cls.server.server_close()

    def _page(self):
        page = self.browser.new_page()
        page.set_default_timeout(TIMEOUT_MS)
        errors = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        self.addCleanup(page.close)
        return page, errors

    def test_population_studio_walks_to_the_structure_step_and_rechecks(self):
        page, errors = self._page()
        page.goto(self.base + "/site/dashboard/population.html")
        # the schema loaded and the first parameter check came back
        page.wait_for_selector("#popIssues .pop-issue")
        page.click("#popNext")
        page.wait_for_selector('#popSteps .step.is-active[data-step="2"]')
        slider = page.wait_for_selector('#popPanel input[type="range"][data-path]')
        with page.expect_response(lambda r: r.url.endswith("/api/population/preview")) as checked:
            slider.evaluate("el => { el.value = el.min; el.dispatchEvent(new Event('input')); }")
        self.assertEqual(checked.value.status, 200)
        self.assertEqual(errors, [])

    def test_agent_studio_family_editor_adds_a_child(self):
        page, errors = self._page()
        # the editor re-renders when the family preview arrives: wait for it
        with page.expect_response(lambda r: "/api/family/preview" in r.url) as preview:
            page.goto(self.base + "/site/dashboard/studio.html")
        self.assertEqual(preview.value.status, 200)
        page.click('#stepRail button[data-step="5"]')
        page.locator('input[data-fam-manual="children"]').check()
        page.locator('[data-fam-add="children"]').click()
        page.wait_for_selector('[data-fam-name][data-fam-kind="children"]')
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
