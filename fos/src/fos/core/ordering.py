"""Minimal Pipeline B ordering strategies for legacy Simulator.

Provides SequentialOrdering, CycledOrdering, ControlledOrdering.
Pending Pipeline A port.
See docs/plans/policy-cascade-port-investigation.md

Contains: Ordering, SequentialOrdering, CycledOrdering, ControlledOrdering
"""

from typing import Callable, Iterator, Optional


class Ordering:
    """Base ordering strategy."""

    def set_simulation(self, sim) -> None:
        self._sim = sim

    def iter(self) -> Iterator[str]:
        yield from []

    def post_turn(self, agent_name: str) -> None:
        pass

    def get_state(self) -> Optional[dict]:
        return None

    def set_state(self, state: Optional[dict]) -> None:
        pass

    def serialize(self) -> Optional[dict]:
        import copy
        return copy.deepcopy(self.get_state())

    def deserialize(self, state: Optional[dict]) -> None:
        import copy
        self.set_state(copy.deepcopy(state))


class SequentialOrdering(Ordering):
    """Agents take turns in list order."""

    def __init__(self):
        self._names = []
        self._idx = 0

    def set_simulation(self, sim) -> None:
        super().set_simulation(sim)
        self._names = list(sim.agents.keys())
        self._idx = 0

    def iter(self) -> Iterator[str]:
        while True:
            yield self._names[self._idx % len(self._names)]
            self._idx += 1

    def get_state(self) -> Optional[dict]:
        return {"names": list(self._names), "idx": self._idx}

    def set_state(self, state: Optional[dict]) -> None:
        if state:
            self._names = state.get("names", [])
            self._idx = state.get("idx", 0)


class CycledOrdering(Ordering):
    """Cycle through a predefined name sequence."""

    def __init__(self, names: list[str]):
        self._names = list(names)
        self._idx = 0

    def iter(self) -> Iterator[str]:
        while True:
            yield self._names[self._idx % len(self._names)]
            self._idx += 1

    def get_state(self) -> Optional[dict]:
        return {"names": list(self._names), "idx": self._idx}

    def set_state(self, state: Optional[dict]) -> None:
        if state:
            self._names = state.get("names", [])
            self._idx = state.get("idx", 0)


class ControlledOrdering(Ordering):
    """External function controls who goes next."""

    def __init__(self, next_fn: Optional[Callable] = None):
        self._next_fn = next_fn

    def iter(self) -> Iterator[str]:
        while True:
            name = self._next_fn(self._sim) if self._next_fn else None
            if name is None:
                break
            yield name
