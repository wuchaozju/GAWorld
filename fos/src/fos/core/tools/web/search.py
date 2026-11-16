"""Minimal web search stub.

Web search was intentionally not migrated from the legacy codebase.
This stub unblocks backend imports. Actual search is a no-op.

TODO: Implement web search for fos if needed.

Contains: create_search_client
"""

from __future__ import annotations

from typing import Optional

from fos.core.search_config import SearchConfig


class _NoOpSearchClient:
    """No-op search client returned when web search is not configured."""

    dialect = "none"

    def search(self, query: str, **kwargs) -> list:
        return []

    def is_available(self) -> bool:
        return False


def create_search_client(
    config: Optional[SearchConfig] = None,
) -> Optional[_NoOpSearchClient]:
    """Create a search client from config.

    Returns a no-op client — web search is not implemented in fos.
    Returns None if config is None or dialect is not set.
    """
    if config is None or not getattr(config, "dialect", None):
        return None
    return _NoOpSearchClient()
