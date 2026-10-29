"""The home panel inside the indoor mode — front-end wiring.

The 居家模式 panel used to sit in the console's right column. It now lives
inside the 室内模式: the resident's own flat is drawn as a floor plan and the
home card (户型 / 家具 / 氛围 / 在家的记录) sits next to it. These tests pin
the three things that can silently break:

1. the home-layout compiler (rooms → floor plan, furniture → drawable kinds),
2. the home card renderer (the "where am I now" line, the reload button),
3. the page wiring: the module is loaded, the standalone panel is gone, the
   view follows the resident (at home → the indoor mode).
"""

from __future__ import annotations

import json
import os
import subprocess
import unittest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DASHBOARD = os.path.join(REPO_ROOT, "site", "dashboard")


def _read(*parts: str) -> str:
    with open(os.path.join(DASHBOARD, *parts), encoding="utf-8") as handle:
        return handle.read()


class TestHomeFrontend(unittest.TestCase):
    def _node(self, script: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["node", script],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=60,
        )

    def test_home_layout_suite_passes(self):
        result = self._node(os.path.join(DASHBOARD, "home-layout.test.js"))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_home_card_suite_passes(self):
        result = self._node(os.path.join(DASHBOARD, "home.test.js"))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_indoor_view_suite_passes(self):
        result = subprocess.run(
            ["node", "--test", os.path.join(DASHBOARD, "indoor-view.test.js")],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_the_console_page_loads_the_home_layout_module(self):
        html = _read("index.html")
        self.assertIn("/site/dashboard/home-layout.js", html)
        # The home panel is not a column of its own any more.
        self.assertNotIn('id="homeDetail"', html)
        self.assertNotIn("home-panel", html)
        # …but the indoor mode is on the page.
        self.assertIn('id="indoorView"', html)

    def test_the_view_follows_the_resident(self):
        app = _read("app.js")
        # The mode is derived from the frame: at home → the indoor mode.
        self.assertIn("home_room", app)
        self.assertIn("syncSceneMode", app)
        # A manual click wins until another resident is picked.
        self.assertIn("sceneMode", app)

    def test_the_indoor_view_draws_the_residents_own_flat(self):
        view = _read("indoor-view.js")
        self.assertIn("buildHomePlan", view)
        self.assertIn("home_room", view)
        # The card lives inside the indoor pane.
        self.assertIn("iv-card", view)

    def test_the_locales_carry_the_new_keys(self):
        for locale in ("zh-CN", "en"):
            with open(os.path.join(DASHBOARD, "locales", f"{locale}.json"), encoding="utf-8") as handle:
                data = json.load(handle)
            for key in (
                "home.card_title",
                "home.now",
                "home.now_room",
                "home.now_activity",
                "home.away",
                "indoor.possessive",
                "indoor.rooms",
                "indoor.at_home",
                "indoor.room.dining",
            ):
                self.assertIn(key, data, f"{locale} is missing {key}")
            # A key with a placeholder must never be rendered through __().
            self.assertIn("{room}", data["home.now_room"])
            self.assertIn("{room}", data["home.now_activity"])

    def test_the_home_css_uses_theme_tokens(self):
        css = _read("home.css")
        # No hard-coded cream surfaces: the dark theme must be able to flip them.
        self.assertNotIn("rgba(245, 244, 232", css)
        self.assertIn("var(--surface-alt)", css)


if __name__ == "__main__":
    unittest.main()
