"""Distributed worlds: one world's residents run on several machines
(proposal 2026-10-02-distributed-worlds).

The dashboard is the **hub**: it keeps the accounts, the worlds and who plays
whom, and now also each world's relay, a per-node outbox for interventions,
and the tick-sync table. A **node** is another machine that runs part of a
world's residents with ``python -m gaworld.cluster join <hub> --token …``.
Every request goes node → hub, so a node behind NAT works as long as it can
reach the hub.

- :mod:`gaworld.cluster.nodes` -- the world's node list and node tokens;
- :mod:`gaworld.cluster.hub` -- in-memory hub state (relay, outbox, sync, records);
- :mod:`gaworld.cluster.bundle` -- what a node downloads to run its residents;
- :mod:`gaworld.cluster.node` -- the node process;
- :mod:`gaworld.cluster.plugin` -- tick sync inside every simulator of the world.
"""

from __future__ import annotations

__all__: list[str] = []
