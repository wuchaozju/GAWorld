"""Backwards-compatible shim for the legacy ``city_map_system`` import path.

The canonical home for these symbols is now :mod:`gaworld.world.city_map`.
We alias this module to the canonical one via ``sys.modules`` so that
``import city_map_system`` and ``from gaworld.world.city_map import ...``
return the *same* module object — preserving any writes to module-level
state.

New code should import from ``gaworld.world.city_map`` directly.
"""

from __future__ import annotations

import sys

from gaworld.world import city_map as _city_map

sys.modules[__name__] = _city_map
