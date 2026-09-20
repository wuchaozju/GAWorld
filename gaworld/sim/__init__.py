"""Simulator sub-package.

Hosts the migrated pieces of the legacy ``generative_city_sim.py`` monolith.
Public surface is intentionally minimal during the migration: import from
the specific submodule (e.g. ``gaworld.sim._utils``) rather than this
package, so the eventual public API can be designed once the move is done.
"""

from __future__ import annotations

__all__: list[str] = []
