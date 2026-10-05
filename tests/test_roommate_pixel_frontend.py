"""Offline geometry regression for the roommate apartment renderer."""

import shutil
import subprocess
from pathlib import Path

import pytest


def test_roommate_pixel_frontend():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is needed for the browser renderer's offline tests")
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [node, "--test", "tests/roommate-pixel.test.js"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
