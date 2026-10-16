"""Launch pip installations from a writable, self-contained runtime workspace.

The simulator has repository-relative paths. Its wheel therefore includes a
versioned source/asset bundle, extracted outside site-packages before starting
any simulator process. Source checkouts keep their existing behavior.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from zipfile import ZipFile

MARKER = ".gaworld-workspace.json"


def _bundle() -> Path:
    return Path(__file__).resolve().parent / "_assets" / "runtime.zip"


def initialize_workspace(destination: Path, bundle: Path | None = None) -> Path:
    """Initialize an empty directory; never replace an existing user's files."""
    destination = destination.expanduser().resolve()
    if (destination / MARKER).is_file():
        if not (destination / "generative_city_sim.py").is_file():
            raise ValueError(f"Incomplete GAWorld workspace: {destination}")
        return destination
    if destination.exists() and any(destination.iterdir()):
        raise ValueError(f"Choose an empty directory; existing files will be preserved: {destination}")
    source = bundle or _bundle()
    if not source.is_file():
        raise ValueError("Runtime assets are missing. Reinstall GAWorld from the project repository.")
    with ZipFile(source) as archive:
        # Validate every entry before writing any archive member.
        for member in archive.infolist():
            path = Path(member.filename)
            if path.is_absolute() or ".." in path.parts or "\\" in member.filename:
                raise ValueError("Unsafe runtime archive path")
            if (member.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError("Runtime archive cannot contain symbolic links")
        names = set(archive.namelist())
        required = {
            "generative_city_sim.py",
            "site/dashboard/index.html",
            "data/hangzhou_agents_state_init.csv",
            "data/hangzhou_profiles_with_names.md",
        }
        if not required.issubset(names):
            raise ValueError("Runtime archive is incomplete")
        destination.mkdir(parents=True, exist_ok=True)
        archive.extractall(destination)
    from importlib.metadata import version

    (destination / MARKER).write_text(
        json.dumps({"package": "gaworld", "version": version("gaworld")}, indent=2) + "\n",
        encoding="utf-8",
    )
    return destination


def main() -> int:
    """CLI entrypoint; cloud model calls remain explicitly user-configured."""
    arguments = sys.argv[1:]
    if arguments and arguments[0] == "init":
        if len(arguments) > 2:
            print("Usage: gaworld init [empty-directory]", file=sys.stderr)
            return 2
        try:
            root = initialize_workspace(Path(arguments[1] if len(arguments) == 2 else "gaworld-workspace"))
        except (OSError, ValueError) as error:
            print(str(error), file=sys.stderr)
            return 2
        print(f"GAWorld workspace ready: {root}\nRun: cd {root}\n     gaworld dashboard")
        return 0
    source_root = Path(__file__).resolve().parents[1]
    selected = os.environ.get("GAWORLD_WORKSPACE", "").strip()
    if selected:
        root = Path(selected).expanduser().resolve()
        if not (root / "generative_city_sim.py").is_file():
            print("GAWORLD_WORKSPACE must point to an initialized workspace.", file=sys.stderr)
            return 2
    elif (Path.cwd() / MARKER).is_file():
        root = Path.cwd()
    elif (source_root / "pyproject.toml").is_file() and (source_root / "site/dashboard/index.html").is_file():
        root = source_root
    else:
        try:
            root = initialize_workspace(Path.home() / ".local/share/gaworld/workspaces/default")
        except (OSError, ValueError) as error:
            print(str(error), file=sys.stderr)
            return 2
    env = dict(os.environ)
    env["PYTHONPATH"] = str(root) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    command = [sys.executable, str(root / "generative_city_sim.py"), *arguments]
    try:
        return subprocess.call(command, cwd=root, env=env)
    except KeyboardInterrupt:
        return 130
