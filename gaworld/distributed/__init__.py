"""Distributed multi-machine communication package.

Hosts the migrated ``distributed_comm`` module — the relay-client
abstraction used when the simulator runs across machines and needs to
exchange inbox / external-environment messages between processes.

For backwards compatibility the legacy ``distributed_comm`` import path
is preserved by a ``sys.modules`` alias shim at the project root, so
both ``import distributed_comm`` and ``from gaworld.distributed.comm
import ...`` return the same module object.

New code should import from ``gaworld.distributed.comm`` directly.
"""

from __future__ import annotations

__all__: list[str] = []
