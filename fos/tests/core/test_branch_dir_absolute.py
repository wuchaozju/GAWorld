"""Regression test — review 2835 Finding 1: absolutize GAWORLD_RUNS_ROOT.

The GAWorld subprocess runs with ``cwd = gaworld_path``
(subprocess_manager.py), while the FOS backend materializes
``kernel/interventions.json`` from its OWN cwd. A relative default runs
root (``data/gaworld_runs``) therefore resolved to two different absolute
files and fork ``interventions_text`` was silently never drained.

Contract: with the default relative root, ``derive_branch_dir`` must
return an ABSOLUTE path anchored at the backend process cwd — the same
file the kernel would read regardless of the subprocess's cwd.
"""

from __future__ import annotations
import os
from pathlib import Path

from fos.backend.services.simtree_gaworld import derive_branch_dir

DEFAULT_RUNS_ROOT = os.path.join("data", "gaworld_runs")


def test_relative_runs_root_is_absolutized(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    branch = derive_branch_dir(DEFAULT_RUNS_ROOT, 7, run_id=42)
    assert os.path.isabs(branch), f"branch_dir must be absolute, got {branch!r}"
    expected = tmp_path / "data" / "gaworld_runs" / "node_7_run_42"
    assert Path(branch) == expected


def test_absolute_runs_root_is_untouched(tmp_path: Path):
    root = tmp_path / "runs"
    assert Path(derive_branch_dir(str(root), 3)) == root / "node_3"


def test_interventions_path_resolves_identically_from_any_cwd(
    tmp_path: Path, monkeypatch
):
    """The kernel resolves the forwarded path verbatim; it must therefore
    be the SAME file whether resolved from the backend cwd or the
    subprocess cwd (gaworld_path)."""
    monkeypatch.chdir(tmp_path)
    branch = derive_branch_dir(DEFAULT_RUNS_ROOT, 5)
    interventions = f"{branch.rstrip('/')}/kernel/interventions.json"
    # Resolve as the subprocess would: cwd = gaworld_path (any other dir).
    subprocess_cwd = tmp_path / "gaworld"
    subprocess_cwd.mkdir()
    from_subprocess = (subprocess_cwd / interventions).resolve()
    assert from_subprocess == Path(interventions).resolve()


def test_old_relative_behavior_would_fail():
    """Guard: the pre-fix behavior (plain string join) produced a relative
    path, which this module's contract rejects."""
    base = f"{DEFAULT_RUNS_ROOT.rstrip('/')}/node_1"
    assert not os.path.isabs(base)
