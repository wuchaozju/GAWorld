"""Backwards-compatible shim for the legacy ``economy_module`` import path.

The canonical home for these symbols is now :mod:`gaworld.economy.finance`.
``sys.modules`` aliasing makes both import paths return the *same* module
object — preserving module-level state and monkey-patching.

New code should import from ``gaworld.economy.finance`` directly.
"""

from __future__ import annotations

import sys

from gaworld.economy import finance as _finance

sys.modules[__name__] = _finance
