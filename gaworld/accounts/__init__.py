"""Accounts for a shared deployment (proposal 2026-10-01-multi-user, P1).

Dashboard startup explicitly selects single-user mode by default.
``--multi-user True`` enables accounts and requires an initialized administrator.
"""

from __future__ import annotations

import os
import sqlite3

from .mode import explicit_mode
from .store import AccountError, AccountStore

DEFAULT_DB = os.path.join("output", "accounts", "accounts.sqlite")


class AccountConfigurationError(RuntimeError):
    """The deployment requires accounts, but its account store is not ready."""


def required() -> bool:
    mode = explicit_mode()
    if mode is not None:
        return mode
    return os.environ.get("GAWORLD_REGISTRATION") == "open" or os.environ.get(
        "GAWORLD_REQUIRE_ACCOUNTS", ""
    ).strip().lower() in {"1", "true", "yes", "on"}


def db_path(repo_root: str) -> str:
    return os.environ.get("GAWORLD_ACCOUNTS_DB", "").strip() or os.path.join(repo_root, DEFAULT_DB)


#: Databases whose schema this process has brought up to date. A database
#: made by an older version gains its new tables on first use.
_SCHEMA_CHECKED: set[str] = set()


def enabled_store(repo_root: str) -> AccountStore | None:
    """Respect the dashboard startup mode; legacy library consumers may auto-detect."""
    if explicit_mode() is False:
        return None
    path = db_path(repo_root)
    if not os.path.exists(path):
        if required():
            raise AccountConfigurationError(
                "Account database missing; initialize or restore it before serving users"
            )
        return None
    store = AccountStore(path)
    try:
        if path not in _SCHEMA_CHECKED:
            store.init_schema()
            _SCHEMA_CHECKED.add(path)
        if required() and not store.has_admin():
            raise AccountConfigurationError(
                "Account database has no administrator; finish account initialization"
            )
    except (OSError, sqlite3.Error) as exc:
        raise AccountConfigurationError(
            "Account database unavailable; check the server account configuration"
        ) from exc
    return store


__all__ = [
    "DEFAULT_DB",
    "AccountConfigurationError",
    "AccountError",
    "AccountStore",
    "db_path",
    "enabled_store",
    "required",
]
