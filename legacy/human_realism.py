"""Backwards-compatible shim for the legacy ``human_realism`` import path.

The canonical home for these symbols is now :mod:`gaworld.cognition.realism`.
``sys.modules`` aliasing makes both import paths return the *same* module
object — preserving module-level state and monkey-patching.

New code should import from ``gaworld.cognition.realism`` directly.
"""

from __future__ import annotations

import sys

from gaworld.cognition import realism as _realism

sys.modules[__name__] = _realism
