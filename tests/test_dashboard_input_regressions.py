"""Run the Studio click and survey composition regressions in pytest/CI."""

import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize("script", ["studio-actions.test.js", "survey.test.js"])
def test_dashboard_input_regressions(script):
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        ["node", "--test", str(root / "site" / "dashboard" / script)],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
