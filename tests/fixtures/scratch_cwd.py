"""Run an in-process simulation from a throwaway working directory.

The simulator's output paths are relative (``output/economy``,
``output/memory``, ``output/diaries`` …) and many are bound to module
constants when ``generative_city_sim`` is imported, so patching CONFIG inside
a test cannot move them. A test that calls ``run_simulation()`` from the repo
root therefore writes into the developer's real ``output/`` — and that residue
is then read back as real data (GAWorld-Bench Track A once scored test
agents 4 and 5 from ``output/economy/wealth_snapshot.csv``).

``data/`` is copied, not linked: a run writes back into it (the news cache).
Same pattern as ``tests/test_e2e_smoke.py``.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def enter(test: unittest.TestCase) -> str:
    """chdir into a fresh directory holding a copy of ``data/``; undone on cleanup."""
    scratch = tempfile.TemporaryDirectory(prefix="gaworld-sim-")
    test.addCleanup(scratch.cleanup)
    shutil.copytree(REPO_ROOT / "data", Path(scratch.name) / "data")
    previous = os.getcwd()
    os.chdir(scratch.name)
    test.addCleanup(os.chdir, previous)
    return scratch.name
