"""Accounts for a shared deployment (proposal 2026-10-01-multi-user, P1).

The account database is opt-in: until ``python -m gaworld.accounts init`` has
created it, the dashboard behaves exactly as the single-user console.
"""

from __future__ import annotations

import os

from .store import AccountError, AccountStore

DEFAULT_DB = os.path.join("output", "accounts", "accounts.sqlite")


def db_path(repo_root: str) -> str:
    return os.environ.get("GAWORLD_ACCOUNTS_DB", "").strip() or os.path.join(repo_root, DEFAULT_DB)


#: Databases whose schema this process has brought up to date. A database
#: made by an older version gains its new tables on first use.
_SCHEMA_CHECKED: set[str] = set()


def enabled_store(repo_root: str) -> AccountStore | None:
    """The store when accounts are switched on (the database exists), else None."""
    path = db_path(repo_root)
    if not os.path.exists(path):
        return None
    store = AccountStore(path)
    if path not in _SCHEMA_CHECKED:
        store.init_schema()
        _SCHEMA_CHECKED.add(path)
    return store


__all__ = ["DEFAULT_DB", "AccountError", "AccountStore", "db_path", "enabled_store"]
