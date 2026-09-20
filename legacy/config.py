"""Backward-compatible CONFIG entrypoint.

The long legacy configuration has been split into focused modules under
``gaworld.settings``. Keep importing ``CONFIG`` from this module in old
scripts; new code can use :mod:`gaworld.settings` directly.
"""

from __future__ import annotations

from gaworld.settings import CONFIG

__all__ = ["CONFIG"]
