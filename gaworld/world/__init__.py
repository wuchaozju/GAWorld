"""World layer — geography, maps, transport, spatial queries.

Hosts the migrated ``city_map_system`` module: tile-map generation,
shortest-path routing, transport-mode cost calculation, rush-hour and
weather effects, and category-based spatial matching.

For backwards compatibility the legacy ``city_map_system`` import path
is preserved by a ``sys.modules`` alias shim at the project root, so
both ``import city_map_system`` and ``from gaworld.world.city_map
import ...`` return the same module object. New code should use the
new path.
"""

from __future__ import annotations

__all__: list[str] = []
