"""Backward-compatible re-export of the environment system.

The implementation lives in :mod:`gaworld.env.system`; this module is a thin
shim so the historical ``from environment import EnvironmentSystem`` import
keeps working (``AGENTS.md``: active code lives under ``gaworld/``, root
modules stay as stable entrypoints until their callers migrate).

It used to be a *copy* rather than a shim — 705 lines duplicating 836 — and
the two drifted in both directions: the root copy grew a ``_safe_float``
hardening pass that the package copy lacked, while the package copy grew the
``_annotate_anomaly`` pass that the root copy lacked. Since the simulator
imported the root copy, ``event["anomaly"]`` was never set and the
anomaly-aware branch in ``gaworld/behavior/dynamic.py`` was dead code. Both
sides were merged into ``gaworld/env/system.py`` before this shim replaced
the duplicate; see CHANGELOG.
"""

from __future__ import annotations

from gaworld.env.system import (  # noqa: F401 - re-exported for compatibility
    EnvironmentSystem,
    RemoteEnvironmentClient,
    _clip,
    _safe_float,
)

__all__ = ["EnvironmentSystem", "RemoteEnvironmentClient"]
