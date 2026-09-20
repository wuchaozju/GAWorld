"""Personal finance & macro-economy simulation.

Hosts the migrated ``economy_module`` — tax + social insurance, Engel-
coefficient spending, multi-account portfolio with monthly returns,
four-phase macro cycles, and shock events (layoff / raise / medical /
year-end bonus).

For backwards compatibility the legacy ``economy_module`` import path is
preserved by a ``sys.modules`` alias shim at the project root, so both
``import economy_module`` and ``from gaworld.economy.finance import ...``
return the same module object.

New code should import from ``gaworld.economy.finance`` directly.
"""

from __future__ import annotations

__all__: list[str] = []
