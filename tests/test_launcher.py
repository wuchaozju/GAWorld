"""Portable installs preserve user work and include real runtime assets."""

from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

import pytest

from gaworld.launcher import MARKER, initialize_workspace


def bundle(path: Path, extra=None):
    with ZipFile(path, "w") as archive:
        for name in (
            "generative_city_sim.py",
            "site/dashboard/index.html",
            "data/hangzhou_agents_state_init.csv",
            "data/hangzhou_profiles_with_names.md",
        ):
            archive.writestr(name, "public asset")
        if extra:
            archive.writestr(extra, "unsafe")
    return path


def test_workspace_is_complete_and_idempotent(tmp_path):
    archive = bundle(tmp_path / "runtime.zip")
    root = tmp_path / "world"
    with patch("importlib.metadata.version", return_value="0.2.1"):
        initialize_workspace(root, archive)
    assert (root / "site/dashboard/index.html").is_file()
    (root / "data/hangzhou_agents_state_init.csv").write_text("my residents")
    initialize_workspace(root, archive)
    assert (root / "data/hangzhou_agents_state_init.csv").read_text() == "my residents"
    assert (root / MARKER).is_file()


def test_workspace_refuses_existing_directory(tmp_path):
    root = tmp_path / "world"
    root.mkdir()
    (root / "my-data.txt").write_text("keep")
    with pytest.raises(ValueError, match="empty directory"):
        initialize_workspace(root, bundle(tmp_path / "runtime.zip"))
    assert (root / "my-data.txt").read_text() == "keep"


def test_archive_rejected_before_any_write(tmp_path):
    root = tmp_path / "world"
    with pytest.raises(ValueError, match="Unsafe"):
        initialize_workspace(root, bundle(tmp_path / "runtime.zip", "../escape.txt"))
    assert not root.exists()
    assert not (tmp_path / "escape.txt").exists()
