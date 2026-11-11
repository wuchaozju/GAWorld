"""The shared button busy-state helper — front-end behaviour.

Every run control in the console ("运行仿真", "重置并运行", "保存配置", "刷新轨迹" …)
is wrapped in `site/dashboard/_button-busy.js`, so a defect in it shows up as
buttons that keep a busy copy ("启动中…") long after the work is done — the
symptom that sent us here: after a simulation run the button still read
"启动中" instead of "运行仿真".

The JS suite drives the real helper with a stubbed DOM; this file only runs it
so it is covered by pytest like the other front-end suites.
"""

from __future__ import annotations

import os
import subprocess
import unittest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DASHBOARD = os.path.join(REPO_ROOT, "site", "dashboard")
SUITE = os.path.join(DASHBOARD, "button-busy.test.js")


class TestButtonBusyFrontend(unittest.TestCase):
    def test_button_busy_suite_passes(self):
        result = subprocess.run(
            ["node", "--test", SUITE],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_the_console_loads_the_busy_helper_before_the_app(self):
        with open(os.path.join(DASHBOARD, "index.html"), encoding="utf-8") as handle:
            html = handle.read()
        helper = html.index("/site/dashboard/_button-busy.js")
        app = html.index("/site/dashboard/app.js")
        self.assertLess(helper, app, "the helper must be loaded before app.js uses it")
