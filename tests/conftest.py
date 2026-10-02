"""Isolate the test suite from the developer's local dashboard config.

``gaworld.settings`` merges ``dashboard_config.json`` into ``CONFIG`` at import
time, so whatever city / horizon / randomness happens to be selected in the
dashboard panel silently becomes the configuration the tests run against. That
made results depend on what the developer last clicked: a ``"city": "wuzhen"``
sitting in that file was enough to turn the long-horizon E2E runs red, while CI
— where the file is untouched — stayed green.

The flag has to be set before anything imports ``gaworld.settings``, which is
why this runs at conftest import time rather than from a fixture. Exporting
``GAWORLD_IGNORE_LOCAL_CONFIG=0`` beforehand opts back in, for the rare case of
wanting to reproduce a run with the panel's own settings.
"""

import os
from pathlib import Path

import pytest

os.environ.setdefault("GAWORLD_IGNORE_LOCAL_CONFIG", "1")

# Same for the account database: once a deployment has run
# `python -m gaworld.accounts init`, every dashboard test would otherwise be
# sent to /login. Account tests point this at their own temp file.
os.environ.setdefault("GAWORLD_ACCOUNTS_DB", os.path.join(os.devnull, "no-accounts.sqlite"))


# ---------------------------------------------------------------------------
# Test suites: ``pytest --suite core`` / ``pytest --suite full``
#
# ``full`` is every collected test (the same as passing no flag). ``core`` keeps
# only the node ids listed in ``tests/suites/core.txt`` — the smoke set for the
# main simulation path, see ``docs/TEST_CASES.md``. An entry is a file, a class
# or a single test (``tests/test_x.py[::Class[::test]]``); ``#`` starts a
# comment. An entry that matches nothing in a collected file fails the run, so
# a renamed test cannot silently drop out of the suite.
# ---------------------------------------------------------------------------

_SUITE_DIR = Path(__file__).parent / "suites"


def pytest_addoption(parser):
    parser.addoption(
        "--suite",
        choices=("core", "full"),
        default=None,
        help="core: the smoke set in tests/suites/core.txt; full: every test (default)",
    )


def _suite_entries(name):
    entries = []
    for raw in (_SUITE_DIR / f"{name}.txt").read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if line:
            entries.append(line)
    return entries


def _matches(nodeid, entry):
    return nodeid == entry or nodeid.startswith((entry + "::", entry + "["))


def pytest_collection_modifyitems(config, items):
    if config.getoption("--suite") != "core":
        return
    entries = _suite_entries("core")
    selected, deselected, used = [], [], set()
    for item in items:
        hits = [entry for entry in entries if _matches(item.nodeid, entry)]
        (selected if hits else deselected).append(item)
        used.update(hits)
    collected_files = {item.nodeid.split("::", 1)[0] for item in items}
    stale = [e for e in entries if e not in used and e.split("::", 1)[0] in collected_files]
    if stale:
        raise pytest.UsageError("tests/suites/core.txt lists tests that do not exist: " + ", ".join(stale))
    if deselected:
        config.hook.pytest_deselected(items=deselected)
        items[:] = selected
