"""Minimal xihu_round1 stub.

Xihu round-1 package loading was not migrated from the legacy codebase.
This stub unblocks backend imports. Package listing returns empty.

TODO: Implement xihu_round1 package loading for fos if needed.

Contains: get_xihu_package_dir, list_xihu_packages, load_xihu_package
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List


def get_xihu_package_dir(package_id: str) -> Path:
    """Return a dummy path — no xihu packages are available."""
    return Path("/tmp/xihu_packages") / package_id


def list_xihu_packages() -> List[Dict[str, Any]]:
    """Return empty list — no xihu packages are loaded."""
    return []


def load_xihu_package(package_id: str) -> Dict[str, Any]:
    """Return empty package dict — no xihu packages are loaded."""
    return {"id": package_id, "materials": []}
