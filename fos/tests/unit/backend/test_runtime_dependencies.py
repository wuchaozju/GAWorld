"""
This file checks that normal app dependencies list packages imported by app code.

Each test verifies one thing:
- test_normal_requirements_include_apscheduler checks that APScheduler is installed
  for normal app runs because PollingService imports it directly.
"""

from __future__ import annotations

from pathlib import Path


def _read_requirement_names(path: Path) -> set[str]:
    names: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        clean_line = line.split("#", maxsplit=1)[0].strip()
        if not clean_line:
            continue
        package_name = clean_line.split("==", maxsplit=1)[0]
        package_name = package_name.split(">=", maxsplit=1)[0]
        package_name = package_name.split("<", maxsplit=1)[0]
        names.add(package_name.lower())
    return names


def test_normal_requirements_include_apscheduler() -> None:
    requirements_path = Path("requirements.txt")

    requirement_names = _read_requirement_names(requirements_path)

    assert "apscheduler" in requirement_names
