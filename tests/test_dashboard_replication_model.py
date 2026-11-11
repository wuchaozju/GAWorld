"""The research page's model-parameter panel, driven by the real front-end source.

The panel is the only place a researcher can see and change the temperature
and token budget, so its behaviour is checked against the actual JavaScript
rather than a copy of it.
"""

from __future__ import annotations

import json
import os
import subprocess
import unittest
from pathlib import Path

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DASHBOARD = Path(REPO_ROOT) / "site" / "dashboard"
SUITE = DASHBOARD / "replication-model.test.js"

NEW_KEYS = [
    "research.rp_gen_title",
    "research.rp_gen_hint",
    "research.rp_gen_extract",
    "research.rp_gen_answer",
    "research.rp_gen_interpret",
    "research.rp_gen_temp",
    "research.rp_gen_tokens",
    "research.rp_gen_bad",
    "research.rp_gen_bad_temp",
    "research.rp_gen_bad_tokens",
    "research.rp_gen_values",
    "research.rp_model_route",
    "research.rp_model_known",
    "research.rp_model_unknown",
    "research.rp_model_unknown_name",
    "research.rp_run_model_title",
    "research.rp_run_model",
    "research.rp_run_backend",
    "research.rp_run_endpoint",
    "research.rp_run_config",
    "research.rp_run_model_hint",
    "research.rp_export_bundle",
]


class ReplicationModelPanelTest(unittest.TestCase):
    def test_the_javascript_suite_passes(self) -> None:
        result = subprocess.run(
            ["node", "--test", str(SUITE)],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_the_locales_carry_the_new_labels(self) -> None:
        for name in ("zh-CN.json", "en.json"):
            locale = json.loads((DASHBOARD / "locales" / name).read_text(encoding="utf-8"))
            for key in NEW_KEYS:
                self.assertIn(key, locale, f"{name} is missing {key}")

    def test_the_page_carries_the_parameter_fields(self) -> None:
        html = (DASHBOARD / "research.html").read_text(encoding="utf-8")
        for field in (
            "rpGenExtractTemp",
            "rpGenExtractMax",
            "rpGenAnswerTemp",
            "rpGenAnswerMax",
            "rpGenInterpretTemp",
            "rpGenInterpretMax",
            "rpModelInfo",
        ):
            self.assertIn(f'id="{field}"', html)

    def test_the_export_offers_the_data_package(self) -> None:
        script = (DASHBOARD / "replication.js").read_text(encoding="utf-8")
        self.assertIn("rpBundle", script)
        self.assertIn("/bundle", script)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
