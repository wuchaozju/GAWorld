"""Venue capacity: a full place turns people away.

Proposal: ``docs/proposals/2026-10-03-venue-capacity.md``. Nodes have always
carried a ``capacity`` and the loop has always counted who is where, but the
count only ever reached perception ("比较拥挤"): any number of residents could
walk into any place. This module is the bookkeeping behind the
``venue_capacity`` validator in :class:`gaworld.world.plugin.VenueCapacityPlugin`.

Design invariants (change them knowingly):

* **Live count, shuffled order.** Admission counts the people already at the
  venue at the start of the tick, the people travelling there, *and* everyone
  admitted earlier in the same tick — otherwise twenty residents arriving at
  12:00 together all get in. Counting within the tick makes the outcome depend
  on processing order, so the plugin shuffles that order per tick with a
  seeded RNG (:func:`shuffled`): who gets the last seat is a fair, repeatable
  draw instead of always the lowest agent id.
* **Conservative about departures.** Someone leaving the venue this tick is
  still counted until the next tick: arrivals and departures in one tick are
  not ordered against each other.
* **Represented crowd, not sample size.** One simulated resident stands for
  ``agents_represent`` people (the same modelling knob as the congestion
  layer); at 1.0 a 600-person venue never fills in a 500-resident town.
"""

from __future__ import annotations

import random
from collections.abc import Iterable
from typing import Any

#: Places people choose to go to, and could choose another of. Homes, work,
#: school, hospitals, stations and unclassified nodes are never capped — see
#: the proposal §2.4 for why each is out.
DEFAULT_CATEGORIES = ("commerce", "leisure")


def is_capped(node: dict[str, Any] | None, categories: Iterable[str]) -> bool:
    return bool(node) and str(node.get("category", "")).lower() in set(categories)


def is_full(load: int, capacity: Any, represent: float) -> bool:
    """Would one more simulated visitor push the represented crowd past capacity?"""
    try:
        cap = float(capacity)
    except (TypeError, ValueError):
        return False
    if cap <= 0 or represent <= 0:
        return False
    return (load + 1) * represent > cap


def start_counts(
    agents: Iterable[dict[str, Any]],
    node_id_of,
) -> dict[str, int]:
    """Per node: residents there at the start of the tick plus residents on
    their way there. *node_id_of* maps a location string to a node id (or None)."""
    counts: dict[str, int] = {}
    for agent in agents or []:
        locations = agent.get("locations") if isinstance(agent, dict) else None
        if not isinstance(locations, dict):
            continue
        where = locations.get("destination") if locations.get("in_transit") else locations.get("current")
        node_id = node_id_of(where) if where else None
        if node_id:
            counts[node_id] = counts.get(node_id, 0) + 1
    return counts


class TickLedger:
    """Load of each venue during one tick: start-of-tick count + admissions."""

    def __init__(self) -> None:
        self._start: dict[str, int] = {}
        self._admitted: dict[str, set] = {}

    def reset(self, start: dict[str, int]) -> None:
        self._start = dict(start)
        self._admitted = {}

    def load(self, node_id: str) -> int:
        return self._start.get(node_id, 0) + len(self._admitted.get(node_id, ()))

    def admit(self, node_id: str, agent_id: Any) -> None:
        self._admitted.setdefault(node_id, set()).add(agent_id)


def shuffled(agents: list, seed: Any, day: Any, time_str: Any) -> list:
    """This tick's processing order: a seeded shuffle, same for the same run."""
    order = list(agents or [])
    random.Random(f"venue_capacity:{seed}:{day}:{time_str}").shuffle(order)
    return order


__all__ = ["DEFAULT_CATEGORIES", "TickLedger", "is_capped", "is_full", "shuffled", "start_counts"]
