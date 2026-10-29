"""Tests for runtime task visibility."""

from __future__ import annotations

from fos.backend.services.runtime_tasks import RuntimeTaskRegistry


def test_runtime_task_registry_records_success_and_failure() -> None:
    registry = RuntimeTaskRegistry()

    success = registry.start("advance", "Advance node", task_id="advance:1")
    registry.finish(success.id, metadata={"node": 1})
    failure = registry.start("ai_analysis", "AI analysis", task_id="ai:1")
    registry.fail(failure.id, "provider missing")

    snapshot = registry.snapshot()

    assert snapshot["active"] == 0
    recent = {task["id"]: task for task in snapshot["recent"]}
    assert recent["advance:1"]["status"] == "finished"
    assert recent["advance:1"]["metadata"]["node"] == 1
    assert recent["ai:1"]["status"] == "error"
    assert recent["ai:1"]["error"] == "provider missing"
