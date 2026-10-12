"""
This file checks that the production /css/fos path has the routes it needs.

Each test verifies one thing:
- test_app_serves_css_fos_api_and_assets checks prefixed API and asset routes are registered.
"""

from __future__ import annotations

from pathlib import Path


def test_app_serves_css_fos_api_and_assets() -> None:
    source = Path("src/fos/backend/main.py").read_text(encoding="utf-8")

    assert 'path="/css/fos/api"' in source
    assert '"/css/fos/assets/{file_path:path}"' in source
