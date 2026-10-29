"""Explicit dashboard process mode, inherited by simulation child processes."""

from __future__ import annotations

import os
from contextlib import contextmanager

MODE_ENV = "GAWORLD_MULTI_USER"


def explicit_mode() -> bool | None:
    value = os.environ.get(MODE_ENV)
    if value is None:
        return None  # Library consumers retain their existing account-store behavior.
    # Unknown explicit values fail closed instead of opening an authenticated deployment.
    return value.strip().lower() not in {"0", "false", "no", "off"}


@contextmanager
def dashboard_mode(enabled: bool, repo_root: str):
    """The startup argument wins over leftover registration/database settings."""
    if not isinstance(enabled, bool):
        raise TypeError("multi_user must be a bool")
    previous = os.environ.get(MODE_ENV)
    os.environ[MODE_ENV] = "True" if enabled else "False"
    try:
        if enabled:
            from gaworld.accounts import enabled_store

            enabled_store(repo_root)  # Refuse to bind a multi-user server without a usable admin store.
        yield
    finally:
        if previous is None:
            os.environ.pop(MODE_ENV, None)
        else:
            os.environ[MODE_ENV] = previous
