"""Active time and approximate ETA exclude time spent on hold."""

import pytest


def test_eta_needs_observed_progress_and_freezes_while_paused():
    from gaworld.research.progress import RunTiming

    now = [100.0]
    timing = RunTiming(clock=lambda: now[0])
    assert timing.snapshot(0.0)["remaining_seconds"] is None
    now[0] += 40
    assert timing.snapshot(0.25)["remaining_seconds"] == pytest.approx(120)
    timing.set_paused(True)
    now[0] += 300
    assert timing.snapshot(0.25)["elapsed_seconds"] == pytest.approx(40)
    assert timing.snapshot(0.25)["remaining_seconds"] == pytest.approx(120)
    timing.set_paused(True)  # duplicate pause must not reset its timestamp
    now[0] += 100
    timing.set_paused(False)
    now[0] += 20
    assert timing.snapshot(0.5)["elapsed_seconds"] == pytest.approx(60)
    assert timing.snapshot(0.5)["remaining_seconds"] == pytest.approx(60)
    timing.finish()
    now[0] += 50
    assert timing.snapshot(0.5)["elapsed_seconds"] == pytest.approx(60)
    assert timing.snapshot(0.5)["remaining_seconds"] is None


def test_eta_is_unknown_at_start_and_when_complete():
    from gaworld.research.progress import RunTiming

    now = [0.0]
    timing = RunTiming(clock=lambda: now[0])
    assert timing.snapshot(0.5)["remaining_seconds"] is None
    now[0] = 20
    assert timing.snapshot(0)["remaining_seconds"] is None
    assert timing.snapshot(1)["remaining_seconds"] is None


@pytest.mark.parametrize("status", ["done", "stopped", "error"])
def test_late_control_requests_cannot_mark_terminal_jobs_paused_or_stopping(monkeypatch, status):
    from gaworld.apps import research_api

    monkeypatch.setattr(research_api, "_JOBS", {})
    job_id = research_api._new_job("run")
    research_api._update_job(job_id, progress=0.4, status=status)
    research_api._update_job(job_id, paused=True, stopping=True)
    job = research_api.job_status(job_id)
    assert job["status"] == status
    assert not job["paused"] and not job["stopping"]
    assert job["remaining_seconds"] is None
