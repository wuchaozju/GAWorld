"""
This file checks that cached simulations can be cleaned up safely.

Each test verifies one thing:
- test_registry_evicts_only_idle_records checks idle trees are removed while active trees stay.
- test_registry_remove_cleans_runtime_resources checks removing a tree stops child resources.
- test_registry_metrics_include_tree_node_count checks health metrics can spot tree growth.
"""

from __future__ import annotations

import time
from types import SimpleNamespace

from fos.backend.services.simtree_runtime import SimTreeRecord, SimTreeRegistry


class FakeTree:
    """Small test tree that records cleanup calls."""

    def __init__(self, node_count: int = 1) -> None:
        self.nodes = {index: {"sim": SimpleNamespace()} for index in range(node_count)}
        self.cleaned = False

    def cleanup_runtime_resources(self) -> None:
        self.cleaned = True


def test_registry_evicts_only_idle_records() -> None:
    registry = SimTreeRegistry()
    idle = SimTreeRecord(FakeTree())
    active = SimTreeRecord(FakeTree())
    subscribed = SimTreeRecord(FakeTree())

    now = time.monotonic()
    idle.last_accessed_at = now - 120
    active.last_accessed_at = now - 120
    active.running.add(0)
    subscribed.last_accessed_at = now - 120
    subscribed.subs.append(object())
    registry._records = {
        "IDLE": idle,
        "ACTIVE": active,
        "SUBSCRIBED": subscribed,
    }

    evicted = registry.evict_idle_records(idle_ttl_seconds=60, now=now)

    assert evicted == ["IDLE"]
    assert "IDLE" not in registry._records
    assert "ACTIVE" in registry._records
    assert "SUBSCRIBED" in registry._records
    assert idle.tree.cleaned is True
    assert active.tree.cleaned is False


def test_registry_remove_cleans_runtime_resources() -> None:
    registry = SimTreeRegistry()
    tree = FakeTree()
    registry._records = {"SIM": SimTreeRecord(tree)}

    registry.remove("sim")

    assert tree.cleaned is True
    assert registry.get("SIM") is None


def test_registry_metrics_include_tree_node_count() -> None:
    registry = SimTreeRegistry()
    registry._records = {"SIM": SimTreeRecord(FakeTree(node_count=3))}

    metrics = registry.metrics()

    assert metrics["active_simulations"] == 1
    assert metrics["tree_nodes"] == 3
