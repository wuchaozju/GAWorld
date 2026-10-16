"""Test-infra fixtures for the GAWorld scene tests.

The production scene acquires its GAWorld subprocess slot from the
module-global ``gaworld_subprocess_semaphore()`` (bounded by
``FOS_GAWORLD_MAX_SUBPROCESSES``, default 2). The real manager releases
those slots in its cancel/finish bookkeeping, but the ``FakeManager``
doubles used throughout these tests never do — and tests that call
``scene._launch_subprocess()`` directly never enter ``run_round``'s
``finally`` cleanup either. Two leaked units exhausted the shared
semaphore and every later test in the process blocked forever.

This autouse fixture swaps in a fresh per-test semaphore so a leak can
never poison a neighbouring test. Production code is untouched: the
caller-acquires contract (locked by the Phase 8 lifecycle tests) stands.
"""

from __future__ import annotations

import threading

import pytest

import fos.core.experiment.scenes.gaworld.scene as scene_module


@pytest.fixture(autouse=True)
def _fresh_gaworld_subprocess_semaphore(monkeypatch):
    """Give every test in this directory its own bounded semaphore."""
    sem = threading.BoundedSemaphore(2)
    monkeypatch.setattr(scene_module, "gaworld_subprocess_semaphore", lambda: sem)
    yield sem
