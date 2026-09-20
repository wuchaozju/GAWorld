"""Cognition layer — human-realism helpers.

Hosts the migrated ``human_realism`` module — intentions, habits,
context-aware memory consolidation, relationship update / weight, and
episode-salience scoring.

For backwards compatibility the legacy ``human_realism`` import path is
preserved by a ``sys.modules`` alias shim at the project root, so both
``import human_realism`` and ``from gaworld.cognition.realism import ...``
return the same module object.

New code should import from ``gaworld.cognition.realism`` directly.
"""

from __future__ import annotations

__all__: list[str] = []
