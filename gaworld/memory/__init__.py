"""Memory persistence layer.

Hosts the migrated ``memory_store`` module — agent memory, vector DB,
schedule / action caches, log persistence, and sim state.

For backwards compatibility the legacy ``memory_store`` import path is
preserved by a shim at the project root that re-exports everything from
:mod:`gaworld.memory.store`. New code should import directly from this
package.
"""

from __future__ import annotations

__all__: list[str] = []
