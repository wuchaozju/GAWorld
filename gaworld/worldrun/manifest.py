"""Shared run-manifest primitives (additive manifest v2).

One atomic writer, one loader, one validator. The parallel-worlds runner and
worldrun's own executor both write ``experiment.json`` through here, so a
partially written manifest is never discoverable and secrets never reach
disk. Version 2 fields are strictly additive: legacy manifests validate
unchanged.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

MANIFEST_FILENAME = "experiment.json"

#: Additive v2 fields — optional, never required, never renumbered.
V2_FIELDS = (
    "worldrun_version",
    "completed_day",
    "checkpoint_lineage",
    "seed_refs",
    "parent_run",
)

_SECRET_KEY_RE = re.compile(r"key|secret|token|password|credential", re.IGNORECASE)
_SECRET_VALUE_RE = re.compile(r"\bsk-[A-Za-z0-9]")


def _redact(node: Any) -> Any:
    """Strip secret-looking material before it reaches the manifest file."""
    if isinstance(node, dict):
        clean: dict[str, Any] = {}
        for key, value in node.items():
            if _SECRET_KEY_RE.search(str(key)):
                continue  # drop secret-bearing entries entirely
            else:
                clean[key] = _redact(value)
        return clean
    if isinstance(node, list):
        return [_redact(item) for item in node]
    if isinstance(node, str) and _SECRET_VALUE_RE.search(node):
        return "[REDACTED]"
    return node


def manifest_path(base_dir: str, root_rel: str | None = None) -> str:
    """Path of the manifest for the run whose root is *root_rel*.

    ``root_rel`` may be absolute (worldrun runs materialise absolute output
    dirs) or relative to *base_dir* (the parallel-worlds convention).
    """
    root = root_rel or base_dir
    if not os.path.isabs(root):
        root = os.path.join(base_dir, root_rel) if root_rel else base_dir
    return os.path.join(root, MANIFEST_FILENAME)


def write_manifest(base_dir: str, manifest: dict[str, Any]) -> None:
    """Atomically write a run manifest (temp file + ``os.replace``)."""
    path = manifest_path(base_dir, manifest.get("root"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(_redact(manifest), handle, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def load_manifest(base_dir: str, root_rel: str | None = None) -> dict[str, Any] | None:
    """Load a run manifest, tolerating a missing or corrupt file."""
    path = manifest_path(base_dir, root_rel)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def validate_manifest(manifest: Any) -> None:
    """Validate a v1 (legacy) or v2 manifest. v2 fields are additive only."""
    if not isinstance(manifest, dict):
        raise ValueError("manifest 必须是对象")
    for key in ("root", "worlds"):
        if key not in manifest:
            raise ValueError(f"manifest 缺少必填字段 {key}")
    if not isinstance(manifest["worlds"], dict):
        raise ValueError("manifest.worlds 必须是对象")


__all__ = [
    "MANIFEST_FILENAME",
    "V2_FIELDS",
    "load_manifest",
    "manifest_path",
    "validate_manifest",
    "write_manifest",
]
