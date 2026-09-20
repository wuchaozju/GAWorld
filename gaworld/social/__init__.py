"""Social-network extensions package.

Hosts the migrated ``social_network`` module — schema migration, ghost
roster bootstrap, role-aware relationship decay, and Dunbar tier
enforcement.

For backwards compatibility the legacy ``social_network`` import path is
preserved by a ``sys.modules`` alias shim at the project root, so both
``import social_network`` and ``from gaworld.social.network import ...``
return the same module object. New code should use the new path.
"""

from __future__ import annotations

__all__: list[str] = []
