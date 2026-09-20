"""Life-events package.

Hosts the migrated ``life_events`` module — scheduled life events
(birthdays, illness, job change, off-screen ghost-event injection) and
the queue/drain helpers that surface due events to the simulator each
tick.

For backwards compatibility the legacy ``life_events`` import path is
preserved by a ``sys.modules`` alias shim at the project root, so both
``import life_events`` and ``from gaworld.events.life import ...``
return the same module object.

New code should import from ``gaworld.events.life`` directly.
"""

from __future__ import annotations

__all__: list[str] = []
