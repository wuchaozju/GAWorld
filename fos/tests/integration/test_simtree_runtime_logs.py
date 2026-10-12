"""Tests for showing runtime failures in the simulation tree.

This file checks that a node can keep its logs even when its simulator stops
with a runtime problem.
"""

from __future__ import annotations

import pytest

from fos.backend.services.simtree_advance import (
    record_advance_runtime_failure,
    run_simulator_for_advance,
)
from fos.backend.services.runtime_tasks import RUNTIME_TASKS
from fos.backend.api.routes.simulations import tree_operations


class RuntimeFailingSimulator:
    """Small simulator that raises a runtime problem when it runs."""

    def __init__(self) -> None:
        self.run_calls = 0

    def run(self, max_turns: int = 1) -> None:
        self.run_calls += max_turns
        raise RuntimeError("missing gaworld api key")


@pytest.mark.asyncio
async def test_advance_runner_returns_runtime_error_for_log_hydration() -> None:
    """Advance runner returns runtime errors so the frontend can still hydrate logs."""
    simulator = RuntimeFailingSimulator()

    error = await run_simulator_for_advance(simulator, max_turns=1)

    assert isinstance(error, RuntimeError)
    assert str(error) == "missing gaworld api key"
    assert simulator.run_calls == 1


def test_record_advance_runtime_failure_adds_node_status_and_log() -> None:
    """Runtime failures are visible on the node and in its event logs."""
    simulator = RuntimeFailingSimulator()
    emitted: list[tuple[str, dict]] = []
    simulator.log_event = lambda event_type, data: emitted.append((event_type, data))  # type: ignore[attr-defined]
    node = {"logs": [], "meta": {}}

    message = record_advance_runtime_failure(
        node,
        simulator,
        RuntimeError("model not found"),
    )

    assert message == "The configured model was not found by the provider."
    assert node["meta"]["runtime_status"] == "failed"
    assert node["meta"]["runtime_error"] == "model not found"
    assert node["meta"]["runtime_error_readable"] == "The configured model was not found by the provider."
    assert emitted == [
        (
            "run_failed",
            {
                "message": "The configured model was not found by the provider.",
                "error": "model not found",
                "category": "provider",
                "error_type": "RuntimeError",
            },
        )
    ]


def test_node_advance_task_helper_records_running_status() -> None:
    """Node advance operations are visible through the shared runtime task registry."""
    RUNTIME_TASKS.clear()

    task_id = tree_operations._start_node_advance_task(
        "sim1",
        node_id=7,
        parent_id=3,
        op="advance_chain",
        turns=1,
    )

    snapshot = RUNTIME_TASKS.snapshot()
    assert task_id == "node_advance:SIM1:7"
    assert snapshot["active"] == 1
    assert snapshot["recent"][0]["kind"] == "node_advance"
    assert snapshot["recent"][0]["metadata"]["parent"] == 3
    RUNTIME_TASKS.clear()
