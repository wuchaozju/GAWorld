"""社会调查/实验拟合度页签的评分说明 — front-end behaviour.

The fidelity score gained a dispersion component: residents that agree far more
than the people did now cost points. The console has to say which formula a
record was scored with, and a record scored under the old formula must be
flagged rather than silently compared with new ones.

The JS suite drives the real `scoreNote` from `site/dashboard/replication.js`;
this file only runs it so it is covered by pytest like the other front-end suites.
"""

from __future__ import annotations

import os
import subprocess
import unittest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DASHBOARD = os.path.join(REPO_ROOT, "site", "dashboard")
SUITE = os.path.join(DASHBOARD, "replication-score.test.js")


class TestReplicationScoreFrontend(unittest.TestCase):
    def test_replication_score_suite_passes(self):
        result = subprocess.run(
            ["node", "--test", SUITE],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_the_locales_carry_the_new_labels(self):
        import json

        for name in ("zh-CN.json", "en.json"):
            with open(os.path.join(DASHBOARD, "locales", name), encoding="utf-8") as handle:
                locale = json.load(handle)
            for key in (
                "research.rp_spread",
                "research.rp_spread_n",
                "research.rp_col_spread",
                "research.rp_spread_note",
                "research.rp_score_note",
                "research.rp_score_note_old",
                "research.rp_score_weights",
                "research.rp_score_collapse_note",
                "research.rp_ci_collapsed",
                "research.rp_ci_collapsed_note",
            ):
                self.assertIn(key, locale, f"{name} is missing {key}")
