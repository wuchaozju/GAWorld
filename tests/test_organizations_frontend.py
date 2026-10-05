from __future__ import annotations

import subprocess
from pathlib import Path


def test_organizations_node_suite():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        ["node", "--test", str(root / "site/dashboard/organizations.test.js")],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
