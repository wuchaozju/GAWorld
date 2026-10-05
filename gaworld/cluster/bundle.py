"""The world package a node downloads before it runs its residents.

A zip with:

- ``settings.json`` -- the world's own settings layers (the global console
  config and the world's ``config.json``) without the model section and
  without ``city``: a node keeps its own model and key, and runs the city
  from this package rather than from its own ``data/cities``;
- ``seed/agents.csv``, ``seed/profiles.md`` -- the world's residents, plus
  whichever of their agent-keyed inputs the world has (Big Five, family pins);
- ``city/…`` -- the city bundle the world was made from, if any (its
  ``city.json`` manifest, map, environment), so the node needs nothing but a
  checkout of GAWorld.

No API keys, no account data, nothing of another world.
"""

from __future__ import annotations

import io
import json
import os
import zipfile
from typing import Any

#: Config sections a node keeps from its own machine.
LOCAL_SECTIONS = ("llm",)
#: Path-valued settings: meaningless on another machine, re-pinned by the node.
PATH_KEYS = ("csv_path", "md_path", "map_path", "real_map_path", "city")
MAX_FILE_BYTES = 20 * 1024 * 1024


def settings_for_node(layers: list[dict[str, Any]]) -> dict[str, Any]:
    from gaworld.settings.overrides import deep_update

    merged: dict[str, Any] = {}
    for layer in layers:
        deep_update(merged, json.loads(json.dumps(layer or {})))
    for key in (*LOCAL_SECTIONS, *PATH_KEYS):
        merged.pop(key, None)
    return merged


def build(
    settings: dict[str, Any],
    seed_csv: str,
    seed_md: str,
    city_dir: str | None = None,
    seed_files: dict[str, str] | None = None,
) -> bytes:
    """*seed_files* maps a file name under ``seed/`` to the file to ship there."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("settings.json", json.dumps(settings, ensure_ascii=False, indent=2))
        archive.write(seed_csv, "seed/agents.csv")
        archive.write(seed_md, "seed/profiles.md")
        for name, path in sorted((seed_files or {}).items()):
            archive.write(path, f"seed/{name}")
        if city_dir and os.path.isdir(city_dir):
            for base, _dirs, files in os.walk(city_dir):
                for name in sorted(files):
                    full = os.path.join(base, name)
                    if name.startswith(".") or os.path.getsize(full) > MAX_FILE_BYTES:
                        continue
                    rel = os.path.relpath(full, city_dir).replace(os.sep, "/")
                    archive.write(full, f"city/{rel}")
    return buffer.getvalue()


def extract(data: bytes, dest: str) -> dict[str, Any]:
    """Unpack into *dest*; returns ``{"settings", "seed_csv", "seed_md", "city_dir"}``."""
    dest_abs = os.path.abspath(dest)
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for info in archive.infolist():
            target = os.path.abspath(os.path.join(dest_abs, info.filename))
            if not target.startswith(dest_abs + os.sep):
                raise ValueError(f"世界包里有越界路径：{info.filename}")
        archive.extractall(dest_abs)
    with open(os.path.join(dest_abs, "settings.json"), encoding="utf-8") as handle:
        settings = json.load(handle)
    city_dir = os.path.join(dest, "city")
    return {
        "settings": settings if isinstance(settings, dict) else {},
        "seed_csv": os.path.join(dest, "seed", "agents.csv"),
        "seed_md": os.path.join(dest, "seed", "profiles.md"),
        "city_dir": city_dir if os.path.isfile(os.path.join(city_dir, "city.json")) else None,
    }


__all__ = ["build", "extract", "settings_for_node"]
