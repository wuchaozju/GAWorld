"""The source registry: ``data/info_sources.json`` → ``list[Source]``.

The registry is data, not code, so an operator can add a feed, drop one that is
blocked on their network, or retag a source without touching Python. A bad entry
is logged and skipped rather than failing the run — one typo in a URL must not
take the whole outside world away from every resident.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from gaworld.infosources.schema import Source
from gaworld.logging_setup import get_logger

_LOG = get_logger("gaworld.infosources.registry")

DEFAULT_REGISTRY_PATH = "data/info_sources.json"


def parse_registry(data: Any) -> list[Source]:
    """Turn the decoded JSON into sources, skipping (and logging) invalid ones."""
    raw_entries = data.get("sources") if isinstance(data, dict) else data
    if not isinstance(raw_entries, list):
        return []
    sources: list[Source] = []
    seen: set[str] = set()
    for entry in raw_entries:
        try:
            source = Source.from_dict(entry)
        except ValueError as exc:
            _LOG.warning("info source skipped: %s", exc)
            continue
        if source.id in seen:
            _LOG.warning("info source skipped: duplicate id %r", source.id)
            continue
        seen.add(source.id)
        sources.append(source)
    return sources


def load_registry(path: Any = DEFAULT_REGISTRY_PATH) -> list[Source]:
    """Read the registry file; a missing or corrupt file is an empty registry."""
    target = Path(str(path or DEFAULT_REGISTRY_PATH))
    if not target.exists():
        _LOG.warning("info source registry not found: %s", target)
        return []
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _LOG.warning("info source registry unreadable (%s): %s", target, exc)
        return []
    return parse_registry(data)


def by_id(sources: list[Source]) -> dict[str, Source]:
    return {source.id: source for source in sources}


__all__ = ["DEFAULT_REGISTRY_PATH", "by_id", "load_registry", "parse_registry"]
