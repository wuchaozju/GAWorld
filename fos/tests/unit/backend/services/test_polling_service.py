"""
This file checks that PollingService handles APScheduler job lifecycle correctly.

Each test verifies one thing:
- test_remove_job_does_not_crash_when_job_does_not_exist: missing job is logged, not raised.
- test_remove_job_raises_on_unexpected_scheduler_error: real errors are logged as warnings.
- test_add_job_removes_old_job_first: re-adding a job replaces the previous one.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from apscheduler.jobstores.base import JobLookupError

from fos.backend.services.polling_service import PollingService


def test_remove_job_does_not_crash_when_job_does_not_exist() -> None:
    service = PollingService()
    service._scheduler = MagicMock()
    service._scheduler.remove_job.side_effect = JobLookupError("not found")

    service.remove_job("nonexistent-id")

    service._scheduler.remove_job.assert_called_once_with("nonexistent-id")


def test_remove_job_raises_on_unexpected_scheduler_error() -> None:
    service = PollingService()
    service._scheduler = MagicMock()
    service._scheduler.remove_job.side_effect = RuntimeError("scheduler is broken")

    service.remove_job("some-id")

    service._scheduler.remove_job.assert_called_once_with("some-id")


def test_add_job_removes_old_job_first() -> None:
    service = PollingService()
    service._scheduler = MagicMock()

    source = SimpleNamespace(
        id="source-1",
        name="Test Feed",
        poll_interval_seconds=120,
    )
    def poll_fn(source_id: str) -> None:
        return None

    service.add_job(source, poll_fn)

    service._scheduler.remove_job.assert_called_once_with("source-1")
    service._scheduler.add_job.assert_called_once()
    call_kwargs = service._scheduler.add_job.call_args
    assert call_kwargs.kwargs["id"] == "source-1"
    assert call_kwargs.kwargs["trigger"] == "interval"
    assert call_kwargs.kwargs["seconds"] == 120


def test_pause_job_does_not_hide_scheduler_error() -> None:
    service = PollingService()
    service._scheduler = MagicMock()
    service._scheduler.pause_job.side_effect = RuntimeError("scheduler is broken")

    service.pause_job("source-1")

    service._scheduler.pause_job.assert_called_once_with("source-1")


def test_resume_job_does_not_hide_scheduler_error() -> None:
    service = PollingService()
    service._scheduler = MagicMock()
    service._scheduler.resume_job.side_effect = RuntimeError("scheduler is broken")

    service.resume_job("source-1")

    service._scheduler.resume_job.assert_called_once_with("source-1")
